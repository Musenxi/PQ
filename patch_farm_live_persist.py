import sys

path = sys.argv[1]
src = open(path).read()

old_call = '''    if leg == 1:
        track_fair07_binance(a, win, ctx, side)
        publish_fair07_signal(a, win, ctx, side, row)
'''
new_call = '''    if leg == 1:
        track_fair07_binance(a, win, ctx, side)
        publish_fair07_signal(a, win, ctx, side, row)
        publish_live_signal(a, win, ctx, side, row)
'''
assert old_call in src, "call site not found"
src = src.replace(old_call, new_call)

anchor = '''SIGNAL_OUT = "fair07_signals.jsonl"
'''
addition = '''SIGNAL_OUT = "fair07_signals.jsonl"
LIVE_SIGNAL_OUT = "live_signals.jsonl"
LIVE_SIGNAL_ACCOUNT = "fv7-persist"


def publish_live_signal(a, win, ctx, side, row):
    """Live-execution signal source (switched 2026-11-23 at lizi's
    instruction): the Azure probe follows THIS account's confirmed
    leg-1 entries. Until 2026-11-23 ~10:09 JST that account was
    fair-07 (via SIGNAL_OUT); lizi switched the live trigger to the
    fv7-persist variant, so persist entries are published here and
    the Azure sidecar mirrors this file to the probe instead.
    fair-07 publication above continues unchanged for the record."""
    if a.id != LIVE_SIGNAL_ACCOUNT:
        return
    append_jsonl(LIVE_SIGNAL_OUT, {"slug": win.slug, "side": side,
                                   "fair": row.get("fair"),
                                   "ask": row.get("price"),
                                   "gap": row.get("gap"),
                                   "ts": ctx["now"]})

'''
assert anchor in src, "anchor not found"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("patched", path)
