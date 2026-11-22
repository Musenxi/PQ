import json, glob, re, datetime as dt
from zoneinfo import ZoneInfo
BASE = "/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_weather"
TZ = {'ZGSZ':'Asia/Shanghai','ZUUU':'Asia/Shanghai','ZBAA':'Asia/Shanghai','ZSPD':'Asia/Shanghai','RJTT':'Asia/Tokyo',
'NZWN':'Pacific/Auckland','RKSI':'Asia/Seoul','RPLL':'Asia/Manila','ZSQD':'Asia/Shanghai','ZGGG':'Asia/Shanghai',
'WMKK':'Asia/Kuala_Lumpur','RKPK':'Asia/Seoul','ZHHH':'Asia/Shanghai','ZUCK':'Asia/Shanghai','RCSS':'Asia/Taipei',
'WSSS':'Asia/Singapore','VILK':'Asia/Kolkata','MMMX':'America/Mexico_City','SBGR':'America/Sao_Paulo','MPMG':'America/Panama',
'CYYZ':'America/Toronto','SAEZ':'America/Argentina/Buenos_Aires','KLAX':'America/Los_Angeles','KDEN':'America/Denver',
'KSEA':'America/Los_Angeles','KSFO':'America/Los_Angeles','KHOU':'America/Chicago','KAUS':'America/Chicago','KMIA':'America/New_York',
'KLGA':'America/New_York','KORD':'America/Chicago','KATL':'America/New_York','KDAL':'America/Chicago','OPKC':'Asia/Karachi',
'OEJN':'Asia/Riyadh','EFHK':'Europe/Helsinki','EHAM':'Europe/Amsterdam','UUWW':'Europe/Moscow','EPWA':'Europe/Warsaw',
'LEMD':'Europe/Madrid','LIMC':'Europe/Rome','LLBG':'Asia/Jerusalem','EDDM':'Europe/Berlin','LTAC':'Europe/Istanbul',
'LFPB':'Europe/Paris','EGLC':'Europe/London','FACT':'Africa/Johannesburg','LTFM':'Europe/Istanbul'}
MON = {m.lower(): i for i, m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'], 1)}

def parse_bucket(t):
    t = t.replace('°', '').replace('−', '-')
    unit = 'C' if t.strip().endswith('C') or 'C ' in t else 'F'
    rg = re.match(r'\s*(-?\d+)\s*-\s*(-?\d+)', t)
    if rg: return (int(rg.group(1)), int(rg.group(2)), unit)
    num = re.findall(r'-?\d+', t)
    if 'below' in t: return (-999, int(num[0]), unit)
    if 'higher' in t or 'above' in t: return (int(num[0]), 999, unit)
    if len(num) == 2: return (int(num[0]), int(num[1]), unit)
    return (int(num[0]), int(num[0]), unit)

def load_events():
    out = {}
    for f in sorted(glob.glob(f"{BASE}/gamma/p*.json")):
        for e in json.load(open(f)):
            d = e['description']
            m = re.search(r'ids=(\w+)', d)
            if not m or 'hourly temperature remark' not in d: continue
            stn = m.group(1)
            s = e['slug']
            mm = re.match(r'(highest|lowest)-temperature-in-(.+)-on-([a-z]+)-(\d+)-(\d{4})$', s)
            if not mm: continue
            kind = 'H' if mm.group(1) == 'highest' else 'L'
            date = dt.date(int(mm.group(5)), MON[mm.group(3)], int(mm.group(4)))
            bks = []
            for mk in e['markets']:
                lo, hi, unit = parse_bucket(mk['groupItemTitle'])
                op = json.loads(mk['outcomePrices']) if mk.get('outcomePrices') else None
                bks.append(dict(lo=lo, hi=hi, unit=unit, title=mk['groupItemTitle'], yes=json.loads(mk['clobTokenIds'])[0],
                                no=json.loads(mk['clobTokenIds'])[1], cond=mk['conditionId'], vol=float(mk.get('volume') or 0),
                                res=float(op[0]) if op else None, fee=mk.get('feeSchedule')))
            bks.sort(key=lambda b: b['lo'])
            out[e['id']] = dict(id=e['id'], slug=s, city=mm.group(2), kind=kind, date=date, stn=stn, tz=TZ[stn],
                                unit=bks[0]['unit'], buckets=bks, vol=float(e.get('volume') or 0), closed=e.get('closed'))
    return out

def day_bounds(date, tz):
    z = ZoneInfo(tz)
    a = dt.datetime(date.year, date.month, date.day, tzinfo=z)
    b = a + dt.timedelta(days=1)
    b = dt.datetime(b.year, b.month, b.day, tzinfo=z)
    return a.timestamp(), b.timestamp()

def load_metar(stn):
    """returns sorted list of (ts, label, raw). Label METAR/SPECI. dedup by (time, label) keeping latest-seen."""
    import os
    seen = {}
    for f in sorted(glob.glob(f"{BASE}/metar/{stn}_*.txt")):
        for line in open(f, encoding='utf-8', errors='replace'):
            line = line.strip()
            m = re.match(r'(METAR|SPECI)?\s*(\w{4}) (\d{2})(\d{2})(\d{2})Z', line)
            if not m: continue
            seen[(m.group(3) + m.group(4) + m.group(5), m.group(1) or 'METAR')] = line
    return seen

def metar_ts(ddhhmm, ref_month=(2026, 11)):
    dd, hh, mi = int(ddhhmm[:2]), int(ddhhmm[2:4]), int(ddhhmm[4:])
    y, mo = ref_month
    if dd > 25: mo = 10  # data span Oct 26 - Nov 22
    return dt.datetime(y, mo, dd, hh, mi, tzinfo=dt.timezone.utc).timestamp()

def temps(raw):
    """returns (tgroup_tenthsC or None, body_C or None, max6 tenths or None, min6 tenths or None)"""
    body = raw.split(' RMK')[0]
    tg = re.search(r' T([01])(\d{3})([01])(\d{3})\b', raw)
    t = (-1 if tg.group(1) == '1' else 1) * int(tg.group(2)) if tg else None
    b = re.search(r' (M?\d{2})/(M?\d{2})?\b', body)
    bc = int(b.group(1).replace('M', '-')) if b else None
    rm = raw.split(' RMK')[1] if ' RMK' in raw else ''
    x1 = re.search(r' 1([01])(\d{3})\b', rm); x2 = re.search(r' 2([01])(\d{3})\b', rm)
    mx = (-1 if x1.group(1) == '1' else 1) * int(x1.group(2)) if x1 else None
    mn = (-1 if x2.group(1) == '1' else 1) * int(x2.group(2)) if x2 else None
    return t, bc, mx, mn

def to_unit(c10, unit):
    """c10: tenths degC (int). round half toward +inf per market rules."""
    from fractions import Fraction
    import math
    v = Fraction(c10, 10)
    if unit == 'F': v = v * 9 / 5 + 32
    return math.floor(v + Fraction(1, 2))
