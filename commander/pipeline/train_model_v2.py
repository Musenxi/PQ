#!/usr/bin/env python3
"""Retrain harness v2: residual learning on top of the analytic fair.

Same data, split, features and simulation as train_model.py (v1), with one
architectural change borrowed from the Quant repo's pm1h_intra model: the
GBM does not predict P(Up) from scratch. It starts from the analytic
random-walk fair p0 = Phi(z_move) (z_move already carries the TWAP-60
variance adjustment, sqrt(tau + 60)) passed as LightGBM init_score, and
only learns the deviation from that fair.

The report adds logloss_fair_base (the analytic fair alone) so each run
shows three numbers on the same test rows: analytic fair, residual model,
market mid. Market price levels are still never model inputs.

Usage:
  python3 train_model_v2.py --features 'results/TASK-00*-features-*.csv' \
      --train-end 1795478400 [--fee-rate 0.05] [--stake 5]
Measurement only; no verdicts.
"""
import argparse, glob, json, math, sys

import numpy as np
import pandas as pd


def norm_cdf(z):
    return 0.5 * (1.0 + np.array([math.erf(v / math.sqrt(2.0)) for v in z]))

BASE_FEATURES = [
    "offset_s", "move", "sigma_1s", "n_prints_900", "twap_margin",
    "early_max_abs_move_120", "early_move_120",
    "up_bid_depth", "up_ask_depth", "book_imbalance", "spread", "lt_up",
]
FEE_RATE_DEFAULT = 0.05
STAKE_DEFAULT = 5.0


def load_frames(patterns):
    files = sorted({f for p in patterns for f in glob.glob(p)})
    if not files:
        sys.exit(f"no feature files matched: {patterns}")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    return df, files


def add_derived(df):
    spot = df["spot_now"].replace(0, np.nan)
    denom = df["sigma_1s"] * spot * np.sqrt(df["tau_s"] + 60.0)
    df["z_move"] = df["move"] / denom.replace(0, np.nan)
    df["rel_move"] = df["move"] / spot
    df["rel_twap_margin"] = df["twap_margin"] / spot
    p0 = norm_cdf(df["z_move"].fillna(0.0).to_numpy())
    df["p0"] = p0.clip(1e-4, 1 - 1e-4)
    return df


FEATURES = BASE_FEATURES + ["z_move", "rel_move", "rel_twap_margin", "p0"]


def logit(p):
    return np.log(p / (1 - p))


def fit_residual(X_tr, y_tr, base_tr, X_va, y_va, base_va):
    import lightgbm as lgb
    dtr = lgb.Dataset(X_tr, label=y_tr, init_score=logit(base_tr))
    dva = lgb.Dataset(X_va, label=y_va, init_score=logit(base_va),
                      reference=dtr)
    params = {
        "objective": "binary", "learning_rate": 0.05, "num_leaves": 31,
        "min_data_in_leaf": 50, "feature_fraction": 0.8, "bagging_fraction": 0.8,
        "bagging_freq": 1, "seed": 7, "verbose": -1,
    }
    booster = lgb.train(params, dtr, num_boost_round=600, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(60, verbose=False)])
    return booster


def predict_residual(booster, X, base):
    # The trees predict a margin correction on top of each row's own base
    # score, so compose manually: p = sigmoid(logit(p0) + raw tree margin).
    raw = booster.predict(X, raw_score=True)
    margin = logit(np.asarray(base, dtype=float)) + np.asarray(raw, dtype=float)
    return 1.0 / (1.0 + np.exp(-margin))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def simulate(df, p_up, gap, fee_rate, stake):
    edge_up = p_up - df["up_ask"]
    edge_dn = (1 - p_up) - df["down_ask"]
    take_up = (edge_up >= gap) & (edge_up >= edge_dn)
    take_dn = (edge_dn >= gap) & (edge_dn > edge_up)
    tr = df[take_up | take_dn].copy()
    if tr.empty:
        return tr
    tr["side_up"] = take_up[take_up | take_dn]
    tr["ask"] = np.where(tr["side_up"], tr["up_ask"], tr["down_ask"])
    tr["win"] = (tr["label_up"] == 1) == tr["side_up"]
    shares = stake / tr["ask"]
    fee = shares * fee_rate * tr["ask"] * (1 - tr["ask"])
    tr["pnl"] = np.where(tr["win"], shares, 0.0) - stake - fee
    return tr


def band_stats(tr):
    out = {}
    for name, lo, hi in [("band_0.20_0.60", 0.20, 0.60), ("band_0.60_0.80", 0.60, 0.80)]:
        b = tr[(tr["ask"] >= lo) & (tr["ask"] < hi)]
        out[name] = {
            "n": int(len(b)),
            "win_rate": float(b["win"].mean()) if len(b) else None,
            "avg_ask": float(b["ask"].mean()) if len(b) else None,
            "win_minus_ask": float((b["win"] - b["ask"]).mean()) if len(b) else None,
            "pnl": float(b["pnl"].sum()) if len(b) else 0.0,
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", nargs="+", required=True)
    ap.add_argument("--train-end", type=int, required=True,
                    help="windows with window_start < train-end are train")
    ap.add_argument("--fee-rate", type=float, default=FEE_RATE_DEFAULT)
    ap.add_argument("--stake", type=float, default=STAKE_DEFAULT)
    args = ap.parse_args()

    df, files = load_frames(args.features)
    df = add_derived(df)
    df = df[df["label_up"] != ""].copy()
    df["label_up"] = df["label_up"].astype(int)
    train = df[df["window_start"] < args.train_end]
    test = df[df["window_start"] >= args.train_end]
    cut = train["window_start"].quantile(0.8)
    tr_in = train[train["window_start"] <= cut]
    va_in = train[train["window_start"] > cut]

    booster = fit_residual(tr_in[FEATURES], tr_in["label_up"], tr_in["p0"],
                           va_in[FEATURES], va_in["label_up"], va_in["p0"])

    ev = test[test["up_mid"].notna()].copy()
    p_ev = predict_residual(booster, ev[FEATURES], ev["p0"])
    sim_df = test[test["up_ask"].notna() & test["down_ask"].notna()].copy()
    p_sim = predict_residual(booster, sim_df[FEATURES], sim_df["p0"])

    report = {
        "engine": "lightgbm-residual",
        "files": [f.split("/")[-1] for f in files],
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "train_windows": int(train["slug"].nunique()),
        "test_windows": int(test["slug"].nunique()),
        "logloss_model": logloss(p_ev, ev["label_up"].to_numpy()),
        "logloss_fair_base": logloss(ev["p0"].to_numpy(), ev["label_up"].to_numpy()),
        "logloss_market_mid": logloss(ev["up_mid"].to_numpy(), ev["label_up"].to_numpy()),
        "logloss_coin": logloss(np.full(len(ev), 0.5), ev["label_up"].to_numpy()),
        "sim": {},
    }
    for gap in (0.03, 0.05, 0.08):
        tr = simulate(sim_df, p_sim, gap, args.fee_rate, args.stake)
        report["sim"][f"gap_{gap:.2f}"] = {
            "trades": int(len(tr)),
            "pnl": float(tr["pnl"].sum()) if len(tr) else 0.0,
            "win_rate": float(tr["win"].mean()) if len(tr) else None,
            "avg_ask": float(tr["ask"].mean()) if len(tr) else None,
            "bands": band_stats(tr),
        }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
