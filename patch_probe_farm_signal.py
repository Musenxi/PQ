"""Patch live_probe_1h.py: single signal source (2026-11-22, lizi).
Entries follow farm1h fair-07's published signals; the probe's own
fair no longer gates entries. Legacy gate kept under SIGNAL_MODE."""
import re

P = "/home/hatch/workspace/polymarket-paper/live_probe_1h.py"
src = open(P).read()

# 1) constants + helper, after the MIN_RETRY_S comment block
anchor = 'STALE_BOOK_MS = 1000'
add = '''SIGNAL_MODE = "farm"      # 2026-11-22 (lizi): SINGLE SIGNAL SOURCE.
                          # Entries follow farm1h fair-07's published
                          # signals (data/farm_signals.jsonl, mirrored
                          # from the VPS by farm-signal-pull.service);
                          # the probe's own fair is computed for
                          # logging only and no longer gates entries.
                          # This starts SEGMENT 5 with the first full
                          # window after deployment; S4 (probe-computed
                          # fair-07, 2026-11-22 02:00 JST -> switch)
                          # is closed and never pooled with S5.
FARM_SIGNAL_FILE = os.path.join(DATA, "farm_signals.jsonl")
FARM_SIG_MAX_AGE_S = 120  # a farm signal stays actionable this long
FARM_ASK_TOL = 0.03       # live ask may exceed the farm's fill by <= this
FARM_GAP_FLOOR = 0.04     # and must still trail the farm fair by >= this


def latest_farm_signal(slug):
    try:
        with open(FARM_SIGNAL_FILE) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except Exception:
        return None
    rows = [r for r in rows if r.get("slug") == slug]
    return rows[-1] if rows else None


STALE_BOOK_MS = 1000'''
assert src.count(anchor) == 1
src = src.replace(anchor, add, 1)

# 2) basis gate: in farm mode, missing own basis must not block entries
old = '''            if win.basis is None or not win.loaded:
                if now - last_hb > 30:
                    last_hb = now
                    print(f"[hb-gate] {win.slug} loaded={win.loaded} basis={win.basis} "
                          f"sampled={win.basis_sampled} prices={len(prices)} spot={spot}", flush=True)
                time.sleep(2)
                continue
            s_est = spot - win.basis
'''
new = '''            if win.basis is None or not win.loaded:
                if now - last_hb > 30:
                    last_hb = now
                    print(f"[hb-gate] {win.slug} loaded={win.loaded} basis={win.basis} "
                          f"sampled={win.basis_sampled} prices={len(prices)} spot={spot}", flush=True)
                if SIGNAL_MODE != "farm" or not win.token:
                    time.sleep(2)
                    continue
            tau = max(win.end - now, 0)
            fairs = {"Up": None, "Down": None}
            fair_up = None
            if win.basis is not None and win.open_price:
                s_est = spot - win.basis
'''
assert src.count(old) == 1
src = src.replace(old, new, 1)

# 3) indent the fair computation under the guard: from "sigma = 0.00012"
#    through the fairs assignment
start = src.index("            sigma = 0.00012")
end_marker = '            fairs = {"Up": fair_up, "Down": 1.0 - fair_up}\n'
end = src.index(end_marker) + len(end_marker)
block = src[start:end]
indented = "".join(("    " + l if l.strip() else l)
                   for l in block.splitlines(keepends=True))
src = src[:start] + indented + src[end:]

# remove the now-duplicated tau line inside the indented block
dup = "                tau = max(win.end - now, 0)\n"
assert src.count(dup) == 1
src = src.replace(dup, "", 1)

# 4) heartbeat: only when fair exists
old = '''            if now - last_hb > 30:
                last_hb = now
                g_up = round(fairs["Up"] - books["Up"][1][0], 3) if books.get("Up") and books["Up"][1][0] else None
                g_dn = round(fairs["Down"] - books["Down"][1][0], 3) if books.get("Down") and books["Down"][1][0] else None
                print(f"[hb] {win.slug} basis={win.basis:.1f} spot={spot:.1f} fair_up={fair_up:.3f} "
                      f"gap_up={g_up} gap_dn={g_dn} tau={tau:.0f}", flush=True)
'''
new = '''            if now - last_hb > 30 and fair_up is not None:
                last_hb = now
                g_up = round(fairs["Up"] - books["Up"][1][0], 3) if books.get("Up") and books["Up"][1][0] else None
                g_dn = round(fairs["Down"] - books["Down"][1][0], 3) if books.get("Down") and books["Down"][1][0] else None
                print(f"[hb] {win.slug} basis={win.basis:.1f} spot={spot:.1f} fair_up={fair_up:.3f} "
                      f"gap_up={g_up} gap_dn={g_dn} tau={tau:.0f}", flush=True)
'''
assert src.count(old) == 1
src = src.replace(old, new, 1)

# 5) decision block: farm-signal trigger replaces the own-fair gate
old = '''            if now - win.start >= ENTRY_DELAY_S and tau >= TAU_MIN \\
                    and now - last_try >= MIN_RETRY_S \\
                    and not filled_window:
                fairs_adj = dict(fairs)
                best = None
                for s in ("Up", "Down"):
                    if s not in books:
                        continue
                    ask = books[s][1][0]
                    if ask is None or not (BAND[0] <= ask <= BAND[1]):
                        continue
                    gap = fairs_adj[s] - ask
                    if best is None or gap > best[0]:
                        best = (gap, s, ask)
                if best and best[0] >= GAP_MIN:
                    gap, side, ask = best
'''
new = '''            farm_sig_used = None
            if now - last_try >= MIN_RETRY_S and not filled_window:
                best = None
                if SIGNAL_MODE == "farm":
                    fsig = latest_farm_signal(win.slug)
                    if fsig and now - fsig.get("ts", 0) <= FARM_SIG_MAX_AGE_S \\
                            and now < win.end - 60:
                        s = fsig["side"]
                        ask = books.get(s, ((None, 0.0), (None, 0.0)))[1][0]
                        if ask is not None and BAND[0] <= ask <= BAND[1] \\
                                and ask <= fsig["ask"] + FARM_ASK_TOL \\
                                and fsig["fair"] - ask >= FARM_GAP_FLOOR:
                            best = (round(fsig["fair"] - ask, 3), s, ask)
                            farm_sig_used = fsig
                elif now - win.start >= ENTRY_DELAY_S and tau >= TAU_MIN:
                    fairs_adj = dict(fairs)
                    for s in ("Up", "Down"):
                        if s not in books:
                            continue
                        ask = books[s][1][0]
                        if ask is None or not (BAND[0] <= ask <= BAND[1]):
                            continue
                        gap = fairs_adj[s] - ask
                        if best is None or gap > best[0]:
                            best = (gap, s, ask)
                    if not best or best[0] < GAP_MIN:
                        best = None
                if best:
                    gap, side, ask = best
'''
assert src.count(old) == 1
src = src.replace(old, new, 1)

# 6) sig_row: farm fair when in farm mode; basis may be None
old = '''                    sig_row = {"ts": datetime.now(timezone.utc).isoformat(),
                               "slug": win.slug, "side": side,
                               "fair": round(fairs[side], 3),
                               "fair_adj": round(fairs_adj[side], 3), "gap": round(gap, 3),
                               "ask": ask, "book_age_ms": meta[side]["age_ms"],
                               "book_stale": meta[side]["stale"],
                               "basis": round(win.basis, 1),
                               "offset_s": round(now - win.start, 1), "tau": round(tau)}
'''
new = '''                    sig_row = {"ts": datetime.now(timezone.utc).isoformat(),
                               "slug": win.slug, "side": side,
                               "fair": round(farm_sig_used["fair"], 3) if farm_sig_used
                                       else round(fairs[side], 3),
                               "fair_adj": round(farm_sig_used["fair"], 3) if farm_sig_used
                                       else round(fairs[side], 3), "gap": round(gap, 3),
                               "ask": ask, "book_age_ms": meta[side]["age_ms"],
                               "book_stale": meta[side]["stale"],
                               "basis": round(win.basis, 1) if win.basis is not None else None,
                               "offset_s": round(now - win.start, 1), "tau": round(tau)}
                    if farm_sig_used:
                        sig_row.update({"source": "farm",
                                        "farm_ask": farm_sig_used["ask"],
                                        "farm_ts": farm_sig_used["ts"]})
'''
assert src.count(old) == 1
src = src.replace(old, new, 1)

open(P, "w").write(src)
print("patched OK")
