"""Compare first-seen time of new hourly METAR on NWS tgftp (Last-Modified header) vs aviationweather.gov API, poll every 5s."""
import time, urllib.request, re, sys, datetime as dt, email.utils
ST = ["KMIA", "KLGA", "KORD", "KATL", "KDAL", "KDEN", "KLAX", "KSEA"]
OUT = sys.argv[1]; dur = int(sys.argv[2]) * 60; t0 = time.time()
last_tg = {}; last_awc = {}
def now(): return dt.datetime.now(dt.timezone.utc)
with open(OUT, "a") as f:
    while time.time() - t0 < dur:
        for s in ST:
            try:
                r = urllib.request.urlopen(f"https://tgftp.nws.noaa.gov/data/observations/metar/stations/{s}.TXT", timeout=10)
                body = r.read().decode(); lm = r.headers.get("Last-Modified")
                ob = re.search(r"(\d{6})Z", body).group(1)
                if last_tg.get(s) not in (None, ob):
                    f.write(f"TGFTP {s} {ob} seen={now():%H:%M:%S} lastmod={email.utils.parsedate_to_datetime(lm):%H:%M:%S}\n"); f.flush()
                last_tg[s] = ob
            except Exception: pass
        try:
            body = urllib.request.urlopen(urllib.request.Request(f"https://aviationweather.gov/api/data/metar?ids={','.join(ST)}&format=raw&hours=1", headers={"User-Agent": "research"}), timeout=10).read().decode()
            for line in body.splitlines():
                m = re.match(r"(METAR|SPECI)?\s*(\w{4}) (\d{6})Z", line.strip())
                if not m: continue
                s, ob = m.group(2), m.group(3)
                if s in last_awc and ob > last_awc[s]:
                    f.write(f"AWC {s} {ob} {m.group(1)} seen={now():%H:%M:%S}\n"); f.flush()
                last_awc[s] = max(ob, last_awc.get(s, ""))
        except Exception: pass
        time.sleep(4)
