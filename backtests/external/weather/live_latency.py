"""Poll aviationweather.gov every 10s (one request, many stations) and log first-seen wall time of each METAR/SPECI.
Measures publication latency (first seen - obs time). Run in background for N minutes."""
import time, urllib.request, re, sys, datetime as dt
IDS = "KMIA,KLGA,KORD,KATL,KDAL,KAUS,KHOU,KDEN,KLAX,KSFO,KSEA,CYYZ,EGLC,LFPB,EDDM,RJTT,ZBAA"
OUT = sys.argv[1]; dur = int(sys.argv[2]) * 60
seen = set(); t0 = time.time()
with open(OUT, 'a') as f:
    while time.time() - t0 < dur:
        try:
            r = urllib.request.urlopen(urllib.request.Request(f"https://aviationweather.gov/api/data/metar?ids={IDS}&format=raw&hours=2", headers={"User-Agent": "research"}), timeout=20).read().decode('utf-8', 'replace')
            now = time.time()
            for line in r.splitlines():
                m = re.match(r'(METAR|SPECI)?\s*(\w{4}) (\d{6})Z', line.strip())
                if not m: continue
                k = (m.group(2), m.group(3), m.group(1))
                if k in seen: continue
                seen.add(k)
                if now - t0 > 30:  # skip initial backlog
                    d = dt.datetime.now(dt.timezone.utc); dd, hh, mi = int(m.group(3)[:2]), int(m.group(3)[2:4]), int(m.group(3)[4:])
                    ot = d.replace(day=dd, hour=hh, minute=mi, second=0, microsecond=0)
                    f.write(f"{k[0]} {k[1]} {k[2]} obs={ot:%H:%M} seen={d:%H:%M:%S} lat_s={(d-ot).total_seconds():.0f}\n"); f.flush()
        except Exception as ex:
            pass
        time.sleep(10)
