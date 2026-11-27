TASK-005 完成
train-end: 1795564800
运行耗时秒: 3.485
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
 "train_rows": 6280,
 "test_rows": 2304,
 "train_windows": 1570,
 "test_windows": 576,
 "logloss_model": 0.4834129299683491,
 "logloss_market_mid": 0.46818542448620487,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 1051,
   "pnl": 226.89640955433958,
   "win_rate": 0.4234062797335871,
   "avg_ask": 0.4189200761179828,
   "bands": {
    "band_0.20_0.60": {
     "n": 612,
     "win_rate": 0.40032679738562094,
     "avg_ask": 0.3839869281045752,
     "win_minus_ask": 0.01633986928104575,
     "pnl": 25.74299829126067
    },
    "band_0.60_0.80": {
     "n": 187,
     "win_rate": 0.6310160427807486,
     "avg_ask": 0.6871657754010695,
     "win_minus_ask": -0.05614973262032086,
     "pnl": -87.9212237243975
    }
   }
  },
  "gap_0.05": {
   "trades": 802,
   "pnl": -118.18742767432332,
   "win_rate": 0.4139650872817955,
   "avg_ask": 0.415280548628429,
   "bands": {
    "band_0.20_0.60": {
     "n": 526,
     "win_rate": 0.39923954372623577,
     "avg_ask": 0.383212927756654,
     "win_minus_ask": 0.01602661596958175,
     "pnl": 40.08858230020184
    },
    "band_0.60_0.80": {
     "n": 146,
     "win_rate": 0.6164383561643836,
     "avg_ask": 0.6849999999999999,
     "win_minus_ask": -0.06856164383561644,
     "pnl": -81.83135324654992
    }
   }
  },
  "gap_0.08": {
   "trades": 510,
   "pnl": 99.25083492244704,
   "win_rate": 0.4294117647058823,
   "avg_ask": 0.41115098039215686,
   "bands": {
    "band_0.20_0.60": {
     "n": 381,
     "win_rate": 0.4041994750656168,
     "avg_ask": 0.3874803149606299,
     "win_minus_ask": 0.016719160104986884,
     "pnl": -15.308405562981829
    },
    "band_0.60_0.80": {
     "n": 76,
     "win_rate": 0.6842105263157895,
     "avg_ask": 0.674078947368421,
     "win_minus_ask": 0.010131578947368413,
     "pnl": 3.5663944466709543
    }
   }
  }
 }
}
备注: 执行成功；stderr 出现非阻塞 LightGBM eval_set 弃用警告。此为管线测量，不是交易结论。
