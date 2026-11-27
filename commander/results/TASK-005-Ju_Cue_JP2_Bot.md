TASK-005 完成
train-end: 1795478400
运行耗时秒: 2.509
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
 "train_rows": 5128,
 "test_rows": 3456,
 "train_windows": 1282,
 "test_windows": 864,
 "logloss_model": 0.49807660078375793,
 "logloss_market_mid": 0.47061791981729945,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 1729,
   "pnl": 86.93390404709827,
   "win_rate": 0.5124349334875651,
   "avg_ask": 0.5073169462116831,
   "bands": {
    "band_0.20_0.60": {
     "n": 820,
     "win_rate": 0.4317073170731707,
     "avg_ask": 0.4068048780487805,
     "win_minus_ask": 0.024902439024390245,
     "pnl": 100.69902206230138
    },
    "band_0.60_0.80": {
     "n": 485,
     "win_rate": 0.6597938144329897,
     "avg_ask": 0.6933979381443299,
     "win_minus_ask": -0.033604123711340195,
     "pnl": -155.32511439346777
    }
   }
  },
  "gap_0.05": {
   "trades": 1372,
   "pnl": -57.49467342529621,
   "win_rate": 0.5029154518950437,
   "avg_ask": 0.49864285714285717,
   "bands": {
    "band_0.20_0.60": {
     "n": 726,
     "win_rate": 0.43526170798898073,
     "avg_ask": 0.4129889807162534,
     "win_minus_ask": 0.022272727272727274,
     "pnl": 60.51765626791482
    },
    "band_0.60_0.80": {
     "n": 397,
     "win_rate": 0.6523929471032746,
     "avg_ask": 0.6892141057934508,
     "win_minus_ask": -0.036821158690176325,
     "pnl": -138.389484254437
    }
   }
  },
  "gap_0.08": {
   "trades": 971,
   "pnl": 144.76757618739035,
   "win_rate": 0.49433573635427397,
   "avg_ask": 0.49065499485066943,
   "bands": {
    "band_0.20_0.60": {
     "n": 604,
     "win_rate": 0.44867549668874174,
     "avg_ask": 0.4178642384105961,
     "win_minus_ask": 0.030811258278145695,
     "pnl": 141.03122884728757
    },
    "band_0.60_0.80": {
     "n": 281,
     "win_rate": 0.6227758007117438,
     "avg_ask": 0.6835160142348754,
     "win_minus_ask": -0.060740213523131664,
     "pnl": -146.0828163712426
    }
   }
  }
 }
}
备注: 运行成功，LightGBM 通过 stderr 输出 LGBMDeprecationWarning（eval_set 参数已弃用）；退出码 0。
