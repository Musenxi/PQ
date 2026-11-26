# TASK-001 环境自检

接收方：@Ju_Cue_JP1_bot、@Ju_Cue_JP2_Bot、@Ju_Cue_SG1_bot（三台都要做）
发布：Muse（commander），2026-11-26

在你自己的服务器上原样运行下面这段命令，不要改脚本。报错不要停，
把报错原文写进结果文件的"备注"。

```bash
python3 - <<'PYEOF'
import os, platform, shutil, socket, sys, time
print("主机名:", socket.gethostname())
print("系统:", platform.platform())
print("CPU核数:", os.cpu_count())
try:
    import psutil
    print("内存GB:", round(psutil.virtual_memory().total / 1e9, 1))
except Exception:
    print("内存GB: 未知")
print("磁盘可用GB:", round(shutil.disk_usage("/").free / 1e9, 1))
print("Python:", sys.version.split()[0])
for lib in ["numpy", "pandas", "sklearn", "lightgbm"]:
    try:
        m = __import__(lib)
        print(lib + ":", getattr(m, "__version__", "有"))
    except Exception:
        print(lib + ": 缺失")
t0 = time.time()
s = 0
for i in range(10000000):
    s += i * i
t1 = time.time()
print("校验值A:", s)
print("耗时A秒:", round(t1 - t0, 2))
try:
    import numpy as np
    rng = np.random.default_rng(42)
    a = rng.standard_normal((2000, 2000))
    t2 = time.time()
    b = a @ a
    t3 = time.time()
    print("校验值B:", int((b > 0).sum()))
    print("矩阵乘耗时秒:", round(t3 - t2, 2))
except Exception as e:
    print("矩阵乘: 跳过", e)
try:
    import urllib.request
    urllib.request.urlopen("https://github.com/Musenxi/PQ", timeout=10)
    print("GitHub可达: 是")
except Exception:
    print("GitHub可达: 否")
PYEOF
```

## 结果提交

把脚本输出原样写进文件 `commander/results/TASK-001-<你的 bot 用户名>.md`，
文件格式：

```
TASK-001 完成
<脚本输出原样粘贴>
备注: <无则写"无">
```

然后 commit + push 到 Musenxi/PQ 仓库。推不上去（无权限）就把你的
GitHub 用户名报给 lizi，并把结果文件内容贴在你与 lizi 的对话里。
