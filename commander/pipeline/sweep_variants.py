#!/usr/bin/env python3
"""Variant sweep for the 5m retrain (discovery screen, measurement only).

Trains a grid of model variants on the extracted feature base and reports,
per variant and per time-split fold: model log-loss vs the market-mid
log-loss on identical test rows, plus the standard taker simulation.

This is a SCREEN, not a read: with this many variants, some will look good
by chance. Ranking is by mean log-loss across folds; a variant is only
FLAGGED if it beats the market mid on every fold. Flagged variants become
candidates for the frozen 2026-12-03 read on fresh data. Nothing here is
a trading conclusion.

Usage:
  python3 sweep_variants.py --features 'results/TASK-00*-features-*.csv' \
      [--limit N]
Prints one JSON object per (variant, fold), then a summary table.
"""
import argparse, glob, itertools, json, math, sys, time

import numpy as np
import pandas as pd

BASE_FEATURES = [
    "offset_s", "move", "sigma_1s", "n_prints_900", "twap_margin",
    "early_max_abs_move_120", "early_move_120",
    "up_bid_depth", "up_ask_depth", "book_imbalance", "spread", "lt_up",
]
BOOK_FEATURES = ["up_bid_depth", "up_ask_depth", "book_imbalance", "spread", "lt_up"]
EARLY_FEATURES = ["early_max_abs_move_120", "early_move_120"]
FOLDS = [1795478400, 1795564800]  # test tails: 11-24..26, 11-25..26


def norm_cdf(z):
    return 0.5 * (1.0 + np.array([math.erf(v / math.sqrt(2.0)) for v in z]))


def logit(p):
    return np.log(p / (1 - p))


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
    df["p0"] = np.clip(norm_cdf(df["z_move"].fillna(0.0).to_numpy()), 1e-4, 1 - 1e-4)
    return df


def feature_set(name, engine):
    cols = list(BASE_FEATURES)
    if name == "nobook":
        cols = [c for c in cols if c not in BOOK_FEATURES]
    elif name == "noearly":
        cols = [c for c in cols if c not in EARLY_FEATURES]
    cols += ["z_move", "rel_move", "rel_twap_margin"]
    if engine == "v2":
        cols += ["p0"]
    return cols


PARAM_SETS = {
    "base":  dict(num_leaves=31, learning_rate=0.05, min_child=50),
    "small": dict(num_leaves=15, learning_rate=0.05, min_child=50),
    "big":   dict(num_leaves=63, learning_rate=0.05, min_child=50),
    "slow":  dict(num_leaves=31, learning_rate=0.03, min_child=50),
    "loose": dict(num_leaves=31, learning_rate=0.05, min_child=20),
    "tight": dict(num_leaves=31, learning_rate=0.05, min_child=100),
}

# (engine, feature set, params, offset filter)
VARIANTS = []
for eng in ("v1", "v2"):
    for pname in PARAM_SETS:
        VARIANTS.append((eng, "full", pname, "all"))
for eng in ("v1", "v2"):
    for fset in ("nobook", "noearly"):
        for pname in ("base", "big"):
            VARIANTS.append((eng, fset, pname, "all"))
for eng in ("v1", "v2"):
    for off in ("ge120", "eq240"):
        VARIANTS.append((eng, "full", "base", off))


def fit_predict(engine, params, X_tr, y_tr, b_tr, X_va, y_va, b_va, X_te, b_te):
    import lightgbm as lgb
    if engine == "v1":
        m = lgb.LGBMClassifier(
            n_estimators=600, learning_rate=params["learning_rate"],
            num_leaves=params["num_leaves"],
            min_child_samples=params["min_child"],
            subsample=0.8, colsample_bytree=0.8, random_state=7, verbose=-1)
        m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)],
              callbacks=[lgb.early_stopping(60, verbose=False)])
        return m.predict_proba(X_te)[:, 1]
    dtr = lgb.Dataset(X_tr, label=y_tr, init_score=logit(b_tr))
    dva = lgb.Dataset(X_va, label=y_va, init_score=logit(b_va), reference=dtr)
    booster = lgb.train(
        {"objective": "binary", "learning_rate": params["learning_rate"],
         "num_leaves": params["num_leaves"],
         "min_data_in_leaf": params["min_child"],
         "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
         "seed": 7, "verbose": -1},
        dtr, num_boost_round=600, valid_sets=[dva],
        callbacks=[lgb.early_stopping(60, verbose=False)])
    raw = booster.predict(X_te, raw_score=True)
    margin = logit(np.asarray(b_te, dtype=float)) + np.asarray(raw, dtype=float)
    return 1.0 / (1.0 + np.exp(-margin))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def simulate(df, p_up, gap, fee_rate=0.05, stake=5.0):
    edge_up = p_up - df["up_ask"]
    edge_dn = (1 - p_up) - df["down_ask"]
    take_up = (edge_up >= gap) & (edge_up >= edge_dn)
    take_dn = (edge_dn >= gap) & (edge_dn > edge_up)
    tr = df[take_up | take_dn].copy()
    if tr.empty:
        return 0, 0.0
    side_up = take_up[take_up | take_dn]
    ask = np.where(side_up, tr["up_ask"], tr["down_ask"])
    win = (tr["label_up"] == 1) == side_up
    shares = stake / ask
    fee = shares * fee_rate * ask * (1 - ask)
    pnl = np.where(win, shares, 0.0) - stake - fee
    return int(len(tr)), float(pnl.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", nargs="+", required=True)
    ap.add_argument("--limit", type=int, default=0, help="run only first N variants")
    args = ap.parse_args()

    df, files = load_frames(args.features)
    df = add_derived(df)
    df = df[df["label_up"] != ""].copy()
    df["label_up"] = df["label_up"].astype(int)
    print(f"# files={len(files)} rows={len(df)} windows={df['slug'].nunique()}",
          file=sys.stderr)

    variants = VARIANTS[: args.limit] if args.limit else VARIANTS
    results = []
    for idx, (engine, fset, pname, off) in enumerate(variants):
        params = PARAM_SETS[pname]
        cols = feature_set(fset, engine)
        sub = df
        if off == "ge120":
            sub = df[df["offset_s"] >= 120]
        elif off == "eq240":
            sub = df[df["offset_s"] == 240]
        for fold in FOLDS:
            train = sub[sub["window_start"] < fold]
            test = sub[sub["window_start"] >= fold]
            cut = train["window_start"].quantile(0.8)
            tr_in = train[train["window_start"] <= cut]
            va_in = train[train["window_start"] > cut]
            ev = test[test["up_mid"].notna()].copy()
            t0 = time.time()
            p_ev = fit_predict(engine, params,
                               tr_in[cols], tr_in["label_up"], tr_in["p0"],
                               va_in[cols], va_in["label_up"], va_in["p0"],
                               ev[cols], ev["p0"])
            ll_model = logloss(p_ev, ev["label_up"].to_numpy())
            ll_mkt = logloss(ev["up_mid"].to_numpy(), ev["label_up"].to_numpy())
            sim_df = test[test["up_ask"].notna() & test["down_ask"].notna()].copy()
            p_sim = fit_predict(engine, params,
                                tr_in[cols], tr_in["label_up"], tr_in["p0"],
                                va_in[cols], va_in["label_up"], va_in["p0"],
                                sim_df[cols], sim_df["p0"])
            sims = {}
            for gap in (0.03, 0.05, 0.08):
                n, pnl = simulate(sim_df, p_sim, gap)
                sims[f"gap_{gap:.2f}"] = {"trades": n, "pnl": round(pnl, 2)}
            rec = {"variant": idx, "engine": engine, "features": fset,
                   "params": pname, "offsets": off, "fold_train_end": fold,
                   "test_rows": int(len(ev)),
                   "logloss_model": round(ll_model, 4),
                   "logloss_market_mid": round(ll_mkt, 4),
                   "delta_vs_market": round(ll_model - ll_mkt, 4),
                   "sim": sims, "fit_seconds": round(time.time() - t0, 2)}
            results.append(rec)
            print(json.dumps(rec), flush=True)

    print("\n# SUMMARY (ranked by mean logloss delta vs market; negative = beats market)")
    by_var = {}
    for r in results:
        by_var.setdefault(r["variant"], []).append(r)
    ranked = sorted(
        by_var.items(),
        key=lambda kv: float(np.mean([x["delta_vs_market"] for x in kv[1]])))
    for vid, rs in ranked:
        r0 = rs[0]
        mean_d = float(np.mean([x["delta_vs_market"] for x in rs]))
        beats_all = all(x["delta_vs_market"] < 0 for x in rs)
        print(f"variant {vid:2d} {r0['engine']} {r0['features']:7s} "
              f"{r0['params']:5s} off={r0['offsets']:5s} "
              f"mean_delta={mean_d:+.4f} beats_market_all_folds={beats_all}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
