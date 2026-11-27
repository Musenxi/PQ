TASK-005 完成
train-end: 1795651200
运行耗时秒: 2.445
{
 "engine": "lightgbm",
 "files": [
  "TASK-003-features-Ju_Cue_JP2_Bot.csv",
  "TASK-004-features-2026-11-19-Ju_Cue_JP2_Bot.csv",
  "TASK-004-features-2026-11-20-Ju_Cue_SG1_bot.csv",
  "TASK-004-features-2026-11-21-Ju_Cue_JP1_bot.csv",
  "TASK-004-features-2026-11-22-Ju_Cue_JP2_Bot.csv",
  "TASK-004-features-2026-11-23-Ju_Cue_SG1_bot.csv",
  "TASK-004-features-2026-11-24-Ju_Cue_JP1_bot.csv",
  "TASK-004-features-2026-11-26-Ju_Cue_JP2_Bot.csv"
 ],
 "train_rows": 7432,
 "test_rows": 1152,
 "train_windows": 1858,
 "test_windows": 288,
 "logloss_model": 0.490361052517537,
 "logloss_market_mid": 0.4681480939546254,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 559,
   "pnl": -3.8977676284952736,
   "win_rate": 0.37924865831842575,
   "avg_ask": 0.3857477638640429,
   "bands": {
    "band_0.20_0.60": {
     "n": 332,
     "win_rate": 0.3614457831325301,
     "avg_ask": 0.3671385542168675,
     "win_minus_ask": -0.005692771084337345,
     "pnl": -128.8759790625325
    },
    "band_0.60_0.80": {
     "n": 96,
     "win_rate": 0.6041666666666666,
     "avg_ask": 0.6813541666666666,
     "win_minus_ask": -0.0771875,
     "pnl": -64.2881448455173
    }
   }
  },
  "gap_0.05": {
   "trades": 420,
   "pnl": -204.39077804161357,
   "win_rate": 0.3523809523809524,
   "avg_ask": 0.38358809523809523,
   "bands": {
    "band_0.20_0.60": {
     "n": 280,
     "win_rate": 0.34285714285714286,
     "avg_ask": 0.36542857142857144,
     "win_minus_ask": -0.022571428571428572,
     "pnl": -173.66405653085494
    },
    "band_0.60_0.80": {
     "n": 69,
     "win_rate": 0.5507246376811594,
     "avg_ask": 0.6826086956521742,
     "win_minus_ask": -0.13188405797101446,
     "pnl": -73.29294120200778
    }
   }
  },
  "gap_0.08": {
   "trades": 278,
   "pnl": -119.50215430444565,
   "win_rate": 0.37410071942446044,
   "avg_ask": 0.3816546762589928,
   "bands": {
    "band_0.20_0.60": {
     "n": 214,
     "win_rate": 0.3691588785046729,
     "avg_ask": 0.3655607476635514,
     "win_minus_ask": 0.0035981308411215016,
     "pnl": -58.44519004978373
    },
    "band_0.60_0.80": {
     "n": 35,
     "win_rate": 0.6,
     "avg_ask": 0.6694285714285715,
     "win_minus_ask": -0.06942857142857142,
     "pnl": -21.200073989784087
    }
   }
  }
 }
}
备注: 运行成功；stderr 有 LightGBM LGBMDeprecationWarning（eval_set 参数已弃用）；退出码 0。
