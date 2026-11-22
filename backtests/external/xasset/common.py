"""Shared helpers for external cross-asset research (polite HTTP, paths)."""
import gzip, json, os, time, urllib.request, urllib.error, threading

RAW = os.environ.get("XASSET_RAW",
    "/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_xasset")
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "research-client/0.1", "Accept-Encoding": "gzip"}
_last = {}
_lock = threading.Lock()

def _log(msg):
    with open(os.path.join(RAW, "http.log"), "a") as f:
        f.write(f"{time.time():.0f} {msg}\n")

def get_json(url, min_gap=0.36, tries=6):
    host = url.split("/")[2]
    for k in range(tries):
        with _lock:
            wait = _last.get(host, 0) + min_gap - time.time()
            _last[host] = max(time.time(), _last.get(host, 0) + min_gap)
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                _log(f"{e.code} {host} retry-after={e.headers.get('retry-after')} k={k}")
                time.sleep(min(2 ** k, 8)); continue
            if e.code == 404:
                return None
            raise
        except Exception as ex:
            _log(f"EXC {host} {type(ex).__name__} {str(ex)[:80]} k={k}")
            time.sleep(min(2 ** k, 8))
    raise RuntimeError("failed " + url)

def save_gz(path, obj):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def load_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)
