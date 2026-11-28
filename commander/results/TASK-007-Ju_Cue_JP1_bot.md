TASK-007 完成
train-end: 1795478400
运行耗时秒: 2.370
{
 "engine": "lightgbm-residual",
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
 "train_rows": 5128,
 "test_rows": 3456,
 "train_windows": 1282,
 "test_windows": 864,
 "logloss_model": 0.4928748741492169,
 "logloss_fair_base": 0.537613594678919,
 "logloss_market_mid": 0.47061791981729945,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 1910,
   "pnl": 18.69560401303562,
   "win_rate": 0.5575916230366492,
   "avg_ask": 0.5430659685863873,
   "bands": {
    "band_0.20_0.60": {
     "n": 804,
     "win_rate": 0.43532338308457713,
     "avg_ask": 0.4067761194029851,
     "win_minus_ask": 0.028547263681592043,
     "pnl": 172.51525545498492
    },
    "band_0.60_0.80": {
     "n": 486,
     "win_rate": 0.6872427983539094,
     "avg_ask": 0.6910658436213992,
     "win_minus_ask": -0.0038230452674897115,
     "pnl": -55.159012155821564
    }
   }
  },
  "gap_0.05": {
   "trades": 1494,
   "pnl": 163.2322851809283,
   "win_rate": 0.5461847389558233,
   "avg_ask": 0.5300033467202142,
   "bands": {
    "band_0.20_0.60": {
     "n": 679,
     "win_rate": 0.43888070692194403,
     "avg_ask": 0.4070515463917526,
     "win_minus_ask": 0.03182916053019146,
     "pnl": 179.52161280942738
    },
    "band_0.60_0.80": {
     "n": 409,
     "win_rate": 0.6723716381418093,
     "avg_ask": 0.6888948655256725,
     "win_minus_ask": -0.016523227383863078,
     "pnl": -79.07076907714506
    }
   }
  },
  "gap_0.08": {
   "trades": 961,
   "pnl": 224.56807736457682,
   "win_rate": 0.5327783558792925,
   "avg_ask": 0.5051956295525495,
   "bands": {
    "band_0.20_0.60": {
     "n": 508,
     "win_rate": 0.4547244094488189,
     "avg_ask": 0.4066102362204725,
     "win_minus_ask": 0.048114173228346456,
     "pnl": 245.22564931946954
    },
    "band_0.60_0.80": {
     "n": 274,
     "win_rate": 0.6605839416058394,
     "avg_ask": 0.6833503649635037,
     "win_minus_ask": -0.022766423357664226,
     "pnl": -66.3239699033226
    }
   }
  }
 }
}
备注: 无
