"""Fetch raw METAR+SPECI (labelled) from aviationweather.gov (the resolution source) per station in 96h chunks."""
import json, os, glob, re, time, urllib.request, datetime as dt
BASE = "/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_weather"
st = set()
for f in glob.glob(f"{BASE}/gamma/p*.json"):
    for e in json.load(open(f)):
        m = re.search(r"ids=(\w+)", e["description"])
        if m: st.add(m.group(1))
os.makedirs(f"{BASE}/metar", exist_ok=True)
end0 = dt.datetime(2026, 11, 22, 12)
for s in sorted(st):
    end = end0
    while end > dt.datetime(2026, 10, 26):
        fn = f"{BASE}/metar/{s}_{end:%Y%m%d%H}.txt"
        if not os.path.exists(fn):
            url = f"https://aviationweather.gov/api/data/metar?ids={s}&format=raw&date={end:%Y-%m-%dT%H:00:00Z}&hours=96"
            for k in range(4):
                try:
                    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=60).read()
                    open(fn, "wb").write(r); break
                except Exception as ex:
                    print("retry", s, ex); time.sleep(3 * (k + 1))
            time.sleep(0.4)
        end -= dt.timedelta(hours=96)
    print(s, flush=True)
