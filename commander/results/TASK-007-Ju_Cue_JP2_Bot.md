TASK-007 完成
train-end: 1795564800
运行耗时秒: 1.949
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
 "train_rows": 6280,
 "test_rows": 2304,
 "train_windows": 1570,
 "test_windows": 576,
 "logloss_model": 0.48853953317294474,
 "logloss_fair_base": 0.537647682263216,
 "logloss_market_mid": 0.46818542448620487,
 "logloss_coin": 0.6931471805599453,
 "sim": {
  "gap_0.03": {
   "trades": 1169,
   "pnl": -23.84722803561337,
   "win_rate": 0.5183917878528657,
   "avg_ask": 0.5056621043627031,
   "bands": {
    "band_0.20_0.60": {
     "n": 556,
     "win_rate": 0.4244604316546763,
     "avg_ask": 0.3894784172661871,
     "win_minus_ask": 0.03498201438848921,
     "pnl": 140.88208527631204
    },
    "band_0.60_0.80": {
     "n": 233,
     "win_rate": 0.6437768240343348,
     "avg_ask": 0.6899141630901288,
     "win_minus_ask": -0.046137339055794,
     "pnl": -96.58084172122108
    }
   }
  },
  "gap_0.05": {
   "trades": 862,
   "pnl": 58.77220674611361,
   "win_rate": 0.494199535962877,
   "avg_ask": 0.4860974477958237,
   "bands": {
    "band_0.20_0.60": {
     "n": 449,
     "win_rate": 0.41648106904231624,
     "avg_ask": 0.3910022271714922,
     "win_minus_ask": 0.025478841870824054,
     "pnl": 32.724122249749996
    },
    "band_0.60_0.80": {
     "n": 194,
     "win_rate": 0.6443298969072165,
     "avg_ask": 0.6887113402061855,
     "win_minus_ask": -0.04438144329896907,
     "pnl": -79.70545854138481
    }
   }
  },
  "gap_0.08": {
   "trades": 519,
   "pnl": 284.8211343766161,
   "win_rate": 0.47591522157996147,
   "avg_ask": 0.4494816955684008,
   "bands": {
    "band_0.20_0.60": {
     "n": 321,
     "win_rate": 0.43613707165109034,
     "avg_ask": 0.3870716510903427,
     "win_minus_ask": 0.04906542056074767,
     "pnl": 129.2588575617067
    },
    "band_0.60_0.80": {
     "n": 118,
     "win_rate": 0.635593220338983,
     "avg_ask": 0.6804237288135593,
     "win_minus_ask": -0.04483050847457627,
     "pnl": -50.17501779073789
    }
   }
  }
 }
}
备注: 无
