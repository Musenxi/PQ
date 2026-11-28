TASK-007 完成
train-end: 1795651200
运行耗时秒: 3.918
{
 "engine": "lightgbm-residual",
 "files": [
  "TASK-003-features-Ju_Cue_SG1_bot.csv",
  "TASK-004-features-2026-11-19-Ju_Cue_JP2_Bot.csv",
  "TASK-004-features-2026-11-20-Ju_Cue_SG1_bot.csv",
  "TASK-004-features-2026-11-21-Ju_Cue_JP1_bot.csv",
  "TASK-004-features-2026-11-22-Ju_Cue_JP2_Bot.csv",
  "TASK-004-features-2026-11-23-Ju_Cue_SG1_bot.csv",
  "TASK-004-features-2026-11-24-Ju_Cue_JP1_bot.csv",
  "TASK-004-features-2026-11-26-Ju_Cue_JP2_Bot.csv"
 ],
 "train_rows": 6856,
 "test_rows": 1152,
 "train_windows": 1714,
 "test_windows": 288,
 "logloss_model": 0.49582977134384915,
 "logloss_fair_base": 0.5674039470632927,
 "logloss_market_mid": 0.4681480939546254,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 592,
   "pnl": -204.23364781322218,
   "win_rate": 0.4527027027027027,
   "avg_ask": 0.4623648648648649,
   "bands": {
    "band_0.20_0.60": {
     "n": 290,
     "win_rate": 0.3931034482758621,
     "avg_ask": 0.3843103448275862,
     "win_minus_ask": 0.008793103448275871,
     "pnl": -43.66660868174273
    },
    "band_0.60_0.80": {
     "n": 135,
     "win_rate": 0.6148148148148148,
     "avg_ask": 0.6886666666666668,
     "win_minus_ask": -0.07385185185185184,
     "pnl": -84.36991177494366
    }
   }
  },
  "gap_0.05": {
   "trades": 414,
   "pnl": -110.42049169313961,
   "win_rate": 0.4227053140096618,
   "avg_ask": 0.4443913043478261,
   "bands": {
    "band_0.20_0.60": {
     "n": 222,
     "win_rate": 0.3918918918918919,
     "avg_ask": 0.3892342342342342,
     "win_minus_ask": 0.002657657657657653,
     "pnl": -20.51831731649966
    },
    "band_0.60_0.80": {
     "n": 102,
     "win_rate": 0.5784313725490197,
     "avg_ask": 0.6818627450980393,
     "win_minus_ask": -0.10343137254901957,
     "pnl": -86.43657246703047
    }
   }
  },
  "gap_0.08": {
   "trades": 256,
   "pnl": -91.81251706163002,
   "win_rate": 0.39453125,
   "avg_ask": 0.43841796875000005,
   "bands": {
    "band_0.20_0.60": {
     "n": 159,
     "win_rate": 0.3584905660377358,
     "avg_ask": 0.3955974842767295,
     "win_minus_ask": -0.037106918238993716,
     "pnl": -109.9527239822466
    },
    "band_0.60_0.80": {
     "n": 60,
     "win_rate": 0.5666666666666666,
     "avg_ask": 0.6696666666666666,
     "win_minus_ask": -0.10300000000000001,
     "pnl": -51.76551430522983
    }
   }
  }
 }
}
备注: 无
