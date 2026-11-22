"""Page Gamma closed daily-temperature events -> raw json pages (untrusted data)."""
import json, os, sys, time, urllib.request, gzip
RAW = "/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_weather/gamma"
cutoff = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
off = 0
while True:
    fn = f"{RAW}/p{off:06d}.json"
    if not os.path.exists(fn):
        url = f"https://gamma-api.polymarket.com/events?tag_slug=daily-temperature&closed=true&limit=100&offset={off}&order=endDate&ascending=false"
        for k in range(5):
            try:
                req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "research"})
                r = urllib.request.urlopen(req, timeout=60).read()
                try: r = gzip.decompress(r)
                except OSError: pass
                json.loads(r); open(fn, "wb").write(r); break
            except Exception as ex:
                print("retry", ex); time.sleep(2 * (k + 1))
        time.sleep(0.5)
    d = json.load(open(fn))
    if not d: break
    last = d[-1]["endDate"]
    print(off, len(d), last, flush=True)
    if last < cutoff: break
    off += 100
