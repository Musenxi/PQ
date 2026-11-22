"""IEM MOS archive: GFS + NBS (NBM) 06Z runs for the 11 US stations."""
import os, time, urllib.request, datetime as dt
BASE = "/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_weather/mos"
for s in ['KLAX','KDEN','KSEA','KHOU','KAUS','KLGA','KSFO','KORD','KATL','KDAL','KMIA']:
    d = dt.date(2026, 10, 27)
    while d <= dt.date(2026, 11, 21):
        for model in ['GFS', 'NBS']:
            fn = f"{BASE}/{s}_{model}_{d:%Y%m%d}06.json"
            if os.path.exists(fn): continue
            url = f"https://mesonet.agron.iastate.edu/api/1/mos.json?station={s}&model={model}&runtime={d:%Y-%m-%d}T06:00Z"
            for k in range(3):
                try:
                    open(fn, 'wb').write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=60).read()); break
                except Exception as ex: time.sleep(3)
            time.sleep(0.35)
        d += dt.timedelta(days=1)
    print(s, flush=True)
