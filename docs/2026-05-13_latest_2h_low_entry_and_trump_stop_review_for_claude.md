# 2026-05-13 最新2H开仓无改善与 TRUMP 止损滞后分析包

## 结论摘要

分析窗口为北京时间 `2026-05-13 19:00:15` 至 `2026-05-13 21:00:15`，即 UTC `2026-05-13 11:00:15` 至 `2026-05-13 13:00:15`。

核心结论：上次两项优化没有看到明显增加开仓，原因不是修复失效，而是两项修复只作用在“已经到 final 且仓位被压小”的候选；最新 2H 的绝大多数候选仍死在更前面的方向/RSI/VWAP 门控。

1. 最新 2H 仍是几乎全 HOLD。
2. `total_compression_floor` 和 `probe_floor_rescue` 只救 final 后的小仓位候选，不会释放 `4H无明确方向`、`rsi_15m_extreme_veto`、`vwap_hard_block`。
3. 最新 2H 的 `ENTRY_GATE_BLOCK` 仍显示 `probe_floor_rescue.shadow_mode=true`，说明运行中的进程很可能没有加载最新配置/代码，或日志来自切换前进程。
4. TRUMP 的问题有两层：入场方向在后验上是错的；更严重的是持仓风控没有在 1H/RSI 已明显转空时触发提前退出，最终等到固定止损才卖出。
5. Claude 提到的方向门控、RSI soft penalty、VWAP ATR gate、权重重平衡不是“多余优化”，但不建议一次性全部 live。当前证据支持优先做“退出风控/反向信号止损”与“确认 live 配置生效”，方向门控和 RSI/VWAP 放行至少需要 12H 日志或回测再动。

## 最新2H运行概况

- 策略决策数：`214`
- `hold`：`214`

执行状态：

| 项 | 次数 | 占比 |
|---|---:|---:|
| `noop` | 214 | 100.0% |

非 HOLD 决策：

最新 2H 未发现非 HOLD 策略决策。

## HOLD 归因

先看 runtime 文本中的细归因：

| 项 | 次数 | 占比 |
|---|---:|---:|
| `4H无明确方向` | 110 | 51.4% |
| `vwap_hard_block` | 52 | 24.3% |
| `rsi_15m_extreme_veto` | 23 | 10.7% |
| `rsi_1h_direction_against_veto` | 9 | 4.2% |
| `rsi_1h_direction_flat_veto` | 2 | 0.9% |
| `green_bar_growing_short_adx_1h_range_filter(42.66 in [35.00` | 1 | 0.5% |
| `信号评分低于阈值: 0.69 < 0.69` | 1 | 0.5% |
| `信号评分低于阈值: 0.58 < 0.69` | 1 | 0.5% |
| `green_bar_growing_short_adx_1h_range_filter(42.39 in [35.00` | 1 | 0.5% |
| `信号评分低于阈值: 0.59 < 0.69` | 1 | 0.5% |
| `信号评分低于阈值: 0.40 < 0.69` | 1 | 0.5% |
| `信号评分低于阈值: 0.41 < 0.68` | 1 | 0.5% |

按 runtime stage：

| 项 | 次数 | 占比 |
|---|---:|---:|
| `neutral_upgrade_gate` | 105 | 49.1% |
| `vwap` | 52 | 24.3% |
| `rsi_rhythm` | 34 | 15.9% |
| `threshold_check` | 9 | 4.2% |
| `vwap_score_filter` | 6 | 2.8% |
| `neutral_upgrade_mode` | 5 | 2.3% |
| `green_bar_growing_short_adx_1h_range_filter` | 2 | 0.9% |
| `short_regime_guard` | 1 | 0.5% |

再看 attribution JSON 中的粗 reason。注意：该 JSON 对 metadata 做了 `_omitted_keys` 压缩，所以比 runtime 粗。

| 项 | 次数 | 占比 |
|---|---:|---:|
| `macd_v2_hold_none_score_0.00` | 146 | 68.2% |
| `macd_v2_hold_vwap_hard_block_score_0.00` | 52 | 24.3% |
| `macd_v2_hold_vwap_score_filter_score_0.00` | 6 | 2.8% |
| `macd_v2_hold_none_score_0.69` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.58` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.59` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.40` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.41` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.60` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.63` | 1 | 0.5% |
| `macd_v2_hold_short_quality_filter_score_0.72` | 1 | 0.5% |
| `macd_v2_hold_none_score_0.44` | 1 | 0.5% |

按 attribution stage：

| 项 | 次数 | 占比 |
|---|---:|---:|
| `-` | 214 | 100.0% |

解释：如果 HOLD 主体仍集中在 `vwap_hard_block`、`rsi_*_veto`、`4H无明确方向/neutral_upgrade_*`，那么降低最终阈值、修复仓位 floor 都不会明显增加开仓。

## min_open 与 probe_floor_rescue

最新 2H runtime 中发现 `ENTRY_GATE_BLOCK`：`10` 次，其中 `min_open_portion` 为 `7` 次，TRUMP 同向加仓拦截 `same_side_add_guard` 为 `3` 次。

min_open_portion 按 Symbol：

| Symbol | 次数 |
|---|---:|
| `ZROUSDT` | 3 |
| `SOLUSDT` | 2 |
| `SUIUSDT` | 1 |
| `ATOMUSDT` | 1 |

代表样例：

| UTC cycle | Symbol | side | target | min_open | score/threshold | probe_floor_rescue |
|---|---|---|---:|---:|---:|---|
| 2026-05-13 11:30:03 | SUIUSDT | SHORT | 0.010500 | 0.0600 | 0.8512/0.6900 | enabled=True, applied=False, shadow=True, reason=eligible |
| 2026-05-13 12:00:03 | ZROUSDT | SHORT | 0.010500 | 0.0600 | 0.7349/0.6900 | enabled=True, applied=False, shadow=True, reason=signal_score=0.7349 |
| 2026-05-13 12:15:03 | ZROUSDT | SHORT | 0.008400 | 0.0600 | 0.7339/0.6900 | enabled=True, applied=False, shadow=True, reason=signal_score=0.7339 |
| 2026-05-13 12:30:03 | SOLUSDT | SHORT | 0.008400 | 0.0600 | 0.7317/0.6900 | enabled=True, applied=False, shadow=True, reason=signal_score=0.7317 |
| 2026-05-13 12:45:03 | SOLUSDT | SHORT | 0.007875 | 0.0600 | 0.8410/0.6900 | enabled=True, applied=False, shadow=True, reason=eligible |
| 2026-05-13 12:45:03 | ZROUSDT | SHORT | 0.003150 | 0.0600 | 0.7195/0.6900 | enabled=True, applied=False, shadow=True, reason=signal_score=0.7195 |
| 2026-05-13 13:00:03 | ATOMUSDT | SHORT | 0.000175 | 0.0600 | 0.7852/0.6600 | enabled=True, applied=False, shadow=True, reason=signal_score=0.7852 |

TRUMP 相关 same_side_add_guard 样例：

| UTC cycle | reason | score/threshold | signal_1h | signal_4h | reject_code |
|---|---|---:|---|---|---|
| 2026-05-13 11:15:03 | `trap_unconfirmed score=0.592` | 0.5910/0.6800 | flip_bearish | red_bar_growing | `信号评分低于阈值` |
| 2026-05-13 11:30:03 | `same_side_add_score<0.110 (0.000)` | 0.0000/0.6800 | flip_bearish | red_bar_growing | `rsi_1h_direction_against_veto` |
| 2026-05-13 11:45:03 | `trap_unconfirmed score=0.500` | 0.5914/0.6800 | flip_bearish | red_bar_growing | `信号评分低于阈值` |

关键异常：当前配置文件中 `probe_floor_rescue.shadow_mode=false`，但最新 runtime 样例仍打印 `shadow_mode=true`。这不是策略逻辑问题，而是部署/进程状态问题：需要确认 bot 是否已重启并加载了最新配置。

当前配置片段：

```json
{
  "enabled": true,
  "shadow_mode": false,
  "min_score_threshold": 0.8,
  "probe_portion": 0.06,
  "probe_min_open_portion": 0.042,
  "probe_leverage_cap": 2
}
```

## TRUMP 交易链路

### 成交记录

| UTC | 北京时间 | side | price | qty | quote_qty | realized_pnl |
|---|---|---|---:|---:|---:|---:|
| 2026-05-13 07:15:15 | 2026-05-13 15:15:15 | 买入 | 2.4830 | 11.7800 | 29.24974 | 0.00000 |
| 2026-05-13 11:52:10 | 2026-05-13 19:52:10 | 卖出 | 2.3870 | 11.7800 | 28.11886 | -1.13088 |

本日 TRUMP：北京时间 `15:15:15` 买入，`19:52:10` 卖出，价格从 `2.483` 到 `2.387`，亏损约 `-3.87%`，realized PnL `-1.13088 USDT`。

### 15:00 后 TRUMP 信号状态

| UTC cycle | 北京时间 | decision | current/risk | price | engine | score摘要 | hold/原因 |
|---|---|---|---|---|---|---|---|
| 2026-05-13 06:45:03 | 2026-05-13 14:45:03 | HOLD | `target=0.0, lev=3` | `open=2.4700 | close=2.4640 | change=-0.24%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=68.47, atr_pct=0.0253` | `stage=threshold_check, dir=neutral, primary=4H:0.4000(flip_bullish), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.5254, VWAPa=0.0263(dev=+0.30%), 15M=0.0060(-/-, raw=0.12), VOL=0.0330(r=0.02), EMA=1.20x/strong, total=0.5853/0.6400, th_src=primary_4h_flip_bullish, trial=False, stable=-, veto=none` | `stage=threshold_check, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm > flip_bullish_sniper_gate > flip_bullish_cooling_gate > flip_bullish_strict_filter > flip_bearish_structure_filter > score_aggregation > threshold_check, reason=信号评分低于阈值: 0.59 < 0.64, code=信号评分低于阈值, detail=0.59 < 0.64, signal_1h=red_bar_shrinking, entry_15m=-, veto=none, lock=BOTH` |
| 2026-05-13 07:00:03 | 2026-05-13 15:00:03 | BUY | `target=0.1, lev=3` | `open=2.4730 | close=2.4770 | change=+0.16%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=67.69, atr_pct=0.0246` | `stage=final, dir=long, primary=4H:0.4000(flip_bullish), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.3557, VWAPa=0.0178(dev=+0.81%), 15M=0.0150(-/-, raw=0.30), VOL=0.0330(r=0.02), EMA=1.20x/strong, total=0.7658/0.6400, th_src=primary_4h_flip_bullish, trial=False, stable=-, veto=none` | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.36` |
| 2026-05-13 07:15:03 | 2026-05-13 15:15:03 | BUY | `target=0.1, lev=3` | `open=2.4730 | close=2.4820 | change=+0.36%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=67.69, atr_pct=0.0249` | `stage=final, dir=long, primary=4H:0.4000(flip_bullish), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.2889, VWAPa=0.0144(dev=+1.01%), 15M=0.0150(-/-, raw=0.30), VOL=0.0330(r=0.00), EMA=1.20x/strong, total=0.7624/0.6400, th_src=primary_4h_flip_bullish, trial=False, stable=-, veto=none` | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.29` |
| 2026-05-13 07:45:03 | 2026-05-13 15:45:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0269 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=901s mfe=0.00% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 08:00:03 | 2026-05-13 16:00:03 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4720 | change=+0.00%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.84, atr_pct=0.0262` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(flip_bullish), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.4283, VWAPa=0.0214(dev=+0.59%), 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), VOL=0.0000(r=0.56), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_1h_direction_against_veto, code=rsi_1h_direction_against_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_1h_direction_block, veto=none, lock=BOTH` |
| 2026-05-13 08:00:03 | 2026-05-13 16:00:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0262 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=1802s mfe=0.00% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 08:15:03 | 2026-05-13 16:15:03 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4840 | change=+0.49%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.84, atr_pct=0.0267` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.2663, VWAPa=0.0133(dev=+1.08%), 15M=0.0000(rsi_extreme_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_15m_extreme_veto, code=rsi_15m_extreme_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_extreme_block, veto=none, lock=BOTH` |
| 2026-05-13 08:15:03 | 2026-05-13 16:15:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0267 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=2701s mfe=0.04% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 08:30:03 | 2026-05-13 16:30:03 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4770 | change=+0.20%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.84, atr_pct=0.0269` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.3619, VWAPa=0.0181(dev=+0.79%), 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_1h_direction_against_veto, code=rsi_1h_direction_against_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_1h_direction_block, veto=none, lock=BOTH` |
| 2026-05-13 08:30:03 | 2026-05-13 16:30:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0269 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=3602s mfe=0.04% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 08:45:03 | 2026-05-13 16:45:03 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4870 | change=+0.61%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.84, atr_pct=0.0269` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.2274, VWAPa=0.0114(dev=+1.19%), 15M=0.0000(rsi_extreme_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_15m_extreme_veto, code=rsi_15m_extreme_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_extreme_block, veto=none, lock=BOTH` |
| 2026-05-13 08:45:03 | 2026-05-13 16:45:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0269 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=4501s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 09:00:03 | 2026-05-13 17:00:03 | HOLD | `target=0.0, lev=3` | `open=2.4820 | close=2.4820 | change=+0.00%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.40, atr_pct=0.0266` | `stage=final, dir=long, primary=4H:0.4000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.3000, VWAPa=0.0150(dev=+0.98%), 15M=0.0150(-/-, raw=0.30), VOL=0.0330(r=0.00), EMA=1.20x/strong, total=0.7630/0.6800, th_src=primary_4h_red_bar_growing, trial=False, stable=-, veto=none` | `stage=final, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm > flip_bullish_sniper_gate > flip_bullish_cooling_gate > flip_bullish_strict_filter > flip_bearish_structure_filter > score_aggregation > threshold_check > final, reason=-, code=-, detail=-, signal_1h=red_bar_shrinking, entry_15m=-, veto=none, lock=BOTH` |
| 2026-05-13 09:00:03 | 2026-05-13 17:00:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0266 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=5402s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 09:15:03 | 2026-05-13 17:15:03 | HOLD | `target=0.0, lev=3` | `open=2.4820 | close=2.4730 | change=-0.36%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.40, atr_pct=0.0272` | `stage=final, dir=long, primary=4H:0.4000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.4225, VWAPa=0.0211(dev=+0.61%), 15M=0.0150(-/-, raw=0.30), VOL=0.0330(r=0.60), EMA=1.20x/strong, total=0.7691/0.6800, th_src=primary_4h_red_bar_growing, trial=False, stable=-, veto=none` | `stage=final, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm > flip_bullish_sniper_gate > flip_bullish_cooling_gate > flip_bullish_strict_filter > flip_bearish_structure_filter > score_aggregation > threshold_check > final, reason=-, code=-, detail=-, signal_1h=red_bar_shrinking, entry_15m=-, veto=none, lock=BOTH` |
| 2026-05-13 09:15:03 | 2026-05-13 17:15:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0272 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=6302s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 09:30:03 | 2026-05-13 17:30:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0279 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=7201s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 09:45:03 | 2026-05-13 17:45:03 | HOLD | `target=0.0, lev=3` | `open=2.4820 | close=2.4640 | change=-0.73%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.04, atr_pct=0.0279` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.5454, VWAPa=0.0273(dev=+0.24%), 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), VOL=0.0000(r=0.51), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_1h_direction_against_veto, code=rsi_1h_direction_against_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_1h_direction_block, veto=none, lock=BOTH` |
| 2026-05-13 09:45:03 | 2026-05-13 17:45:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0279 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=8101s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 10:00:04 | 2026-05-13 18:00:04 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4710 | change=-0.04%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.16, atr_pct=0.0275` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.4556, VWAPa=0.0228(dev=+0.51%), 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_1h_direction_against_veto, code=rsi_1h_direction_against_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_1h_direction_block, veto=none, lock=BOTH` |
| 2026-05-13 10:00:04 | 2026-05-13 18:00:04 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0275 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=9002s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 10:15:03 | 2026-05-13 18:15:03 | HOLD | `target=0.0, lev=3` | `open=2.4720 | close=2.4590 | change=-0.53%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.16, atr_pct=0.0282` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(red_bar_growing), 1H=0.0000(red_bar_shrinking), 4H_enh=0.0000(raw=0.80), VWAPq=0.6185, VWAPa=0.0309(dev=+0.02%), 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.00x/normal, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_1h_direction_against_veto, code=rsi_1h_direction_against_veto, detail=-, signal_1h=red_bar_shrinking, entry_15m=rsi_1h_direction_block, veto=none, lock=BOTH` |
| 2026-05-13 10:15:03 | 2026-05-13 18:15:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0282 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=9901s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 10:30:03 | 2026-05-13 18:30:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0286 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=10801s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 10:45:03 | 2026-05-13 18:45:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0287 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=11701s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 11:00:03 | 2026-05-13 19:00:03 | BUY | `target=0.23, lev=3` | `open=2.4570 | close=2.4570 | change=+0.00%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=62.46, atr_pct=0.0217` | `stage=threshold_check, dir=neutral, primary=4H:0.4000(red_bar_growing), 1H=0.0000(flip_bearish), 4H_enh=0.0000(raw=0.80), VWAPq=0.6397, VWAPa=0.0320(dev=-0.07%), 15M=0.0060(-/-, raw=0.12), VOL=0.0330(r=0.50), EMA=1.00x/normal, total=0.5910/0.6800, th_src=primary_4h_red_bar_growing, trial=False, stable=-, veto=none` | `DCA/马丁触发 stage=1/1, drawdown=0.0105 >= threshold=0.0100, multiplier=1.00, lev=4x | DCA执行 stage=1 drawdown=0.0105/th=0.0100 mult=1.00 target=0.27` |
| 2026-05-13 11:00:03 | 2026-05-13 19:00:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0217 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=12601s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 11:15:03 | 2026-05-13 19:15:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0224 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=13501s mfe=0.16% mae=-1.37% action=none` | - | - | - | - |
| 2026-05-13 11:30:03 | 2026-05-13 19:30:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0227 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=1s mfe=0.00% mae=-1.49% action=none` | - | - | - | - |
| 2026-05-13 11:45:03 | 2026-05-13 19:45:03 | RISK | `symbol=TRUMPUSDT engine=NO_TRADE side=LONG entry=2.483000 atr=0.0226 protect=neutral state=HOLD bars=0 pen=+0.00 votes=0 hold=901s mfe=0.00% mae=-1.49% action=none` | - | - | - | - |
| 2026-05-13 12:00:03 | 2026-05-13 20:00:03 | HOLD | `target=0.0, lev=3` | `open=2.3970 | close=2.3950 | change=-0.08%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=63.71, atr_pct=0.0216` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(flip_bearish), 1H=0.0000(green_bar_growing), 4H_enh=0.0000(raw=0.50), VWAPq=0.0389, VWAPa=0.0019(dev=-2.53%), 15M=0.0000(rsi_extreme_block/-, raw=0.00), VOL=0.0000(r=0.04), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_15m_extreme_veto, code=rsi_15m_extreme_veto, detail=-, signal_1h=green_bar_growing, entry_15m=rsi_extreme_block, veto=none, lock=BOTH` |
| 2026-05-13 12:15:03 | 2026-05-13 20:15:03 | HOLD | `target=0.0, lev=3` | `open=2.3970 | close=2.3900 | change=-0.29%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=63.71, atr_pct=0.0222` | `stage=rsi_rhythm, dir=neutral, primary=4H:0.0000(flip_bearish), 1H=0.0000(green_bar_growing), 4H_enh=0.0000(raw=0.50), VWAPq=0.0235, VWAPa=0.0012(dev=-2.72%), 15M=0.0000(rsi_extreme_block/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=none` | `stage=rsi_rhythm, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm, reason=rsi_15m_extreme_veto, code=rsi_15m_extreme_veto, detail=-, signal_1h=green_bar_growing, entry_15m=rsi_extreme_block, veto=none, lock=BOTH` |
| 2026-05-13 12:30:03 | 2026-05-13 20:30:03 | HOLD | `target=0.0, lev=3` | `open=2.3970 | close=2.3870 | change=-0.42%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=63.71, atr_pct=0.0225` | `stage=vwap_score_filter, dir=neutral, primary=4H:0.0000(flip_bearish), 1H=0.0000(green_bar_growing), 4H_enh=0.0000(raw=0.50), VWAPq=0.0145, VWAPa=0.0007(dev=-2.83%), 15M=0.0000(-/-, raw=0.12), VOL=0.0000(r=0.12), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=vwap_score_filter` | `stage=vwap_score_filter, path=1h_direction > boll_structure > boll_deviation > vwap > flip_bearish_vwap_filter > 4h_enhancement > rsi_rhythm > flip_bullish_sniper_gate > flip_bullish_cooling_gate > flip_bullish_strict_filter > flip_bearish_structure_filter > vwap_score_filter, reason=vwap_score_filter(0.0145<0.0600), code=vwap_score_filter, detail=0.0145<0.0600, signal_1h=green_bar_growing, entry_15m=-, veto=vwap_score_filter, lock=BOTH` |
| 2026-05-13 12:45:03 | 2026-05-13 20:45:03 | HOLD | `target=0.0, lev=3` | `open=2.3970 | close=2.3560 | change=-1.71%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.18, atr_pct=0.0243` | `stage=vwap, dir=neutral, primary=4H:0.0000(flip_bearish), 1H=0.0000(green_bar_growing), 4H_enh=0.0000(raw=0.00), VWAPq=0.0000, VWAPa=0.0000(dev=-3.99%), 15M=0.0000(-/-, raw=0.00), VOL=0.0000(r=0.00), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=vwap_hard_block` | `stage=vwap, path=1h_direction > boll_structure > boll_deviation > vwap, reason=vwap_hard_block, code=vwap_hard_block, detail=-, signal_1h=green_bar_growing, entry_15m=-, veto=vwap_hard_block, lock=BOTH` |
| 2026-05-13 13:00:03 | 2026-05-13 21:00:03 | HOLD | `target=0.0, lev=3` | `open=2.3540 | close=2.3550 | change=+0.04%` | `engine=NO_TRADE, pool=-, direction=BOTH, adx=64.10, atr_pct=0.0210` | `stage=vwap, dir=neutral, primary=4H:0.0000(flip_bearish), 1H=0.0000(green_bar_growing), 4H_enh=0.0000(raw=0.00), VWAPq=0.0000, VWAPa=0.0000(dev=-4.03%), 15M=0.0000(-/-, raw=0.00), VOL=0.0000(r=0.01), EMA=1.20x/strong, total=0.0000/0.6800, th_src=-, trial=False, stable=-, veto=vwap_hard_block` | `stage=vwap, path=1h_direction > boll_structure > boll_deviation > vwap, reason=vwap_hard_block, code=vwap_hard_block, detail=-, signal_1h=green_bar_growing, entry_15m=-, veto=vwap_hard_block, lock=BOTH` |

观察：北京时间 18:00 起，风控摘要连续显示 `engine=NO_TRADE`、`state=HOLD`、`votes=0`、`action=none`。北京时间 18:00/18:15/18:30/17:45 等周期，策略侧已出现 `rsi_1h_direction_against_veto` 或 `rsi_15m_extreme_veto`，但这些只影响新开/加仓，没有转化为持仓退出信号。北京时间 20:00 以后 TRUMP 已经是 `4H=flip_bearish`，但仓位已经在 19:52 由价格止损卖出。

## 为什么上次优化未增加开仓

上次实际落地的是两项：

1. `total_compression_floor`：只在信号已经通过评分、只是仓位被 VWAP/volume/ADX 叠压后发挥作用。
2. `probe_floor_rescue live/probe_min_open`：只在最终 target 低于 min_open、且 score >= 0.80 时发挥作用。

它们不改变以下前置门控：

- `vwap_hard_block`
- `rsi_15m_extreme_veto`
- `rsi_1h_direction_against_veto` / `flat_veto`
- `4H无明确方向` / `neutral_upgrade_gate`

因此，如果最新 2H 的主要阻断仍在这些 stage，开仓数量不会明显提升。

另一个更直接的问题是：最新 runtime 的 `ENTRY_GATE_BLOCK` 仍显示 `probe_floor_rescue.shadow_mode=true`，这与当前配置文件不一致。先确认部署生效，比继续加策略改动更重要。

## Claude 上次提出的未落地优化是否多余

判断：不是多余，但优先级需要拆开。

| 优化项 | 当前判断 | 是否现在 live | 理由 |
|---|---|---|---|
| 方向门控 / neutral partial_confirm | 仍可能必要 | 暂不建议直接 live | 最新日志仍有大量 `4H无明确方向`，但放开会改变入场方向质量，需要至少 12H 样本或回测。 |
| RSI soft penalty | 仍可能必要 | 暂不建议直接 live | RSI veto 仍是阻断源；但 TRUMP 亏损说明“放松入场 RSI”可能增加错误方向交易，必须先把退出风控补上。 |
| VWAP ATR normalized gate | 必要性更强 | 必须回测后 live | 当前 `vwap_hard_block` 仍非常多，且高 ATR 标的固定 3%/4% 偏离一刀切不合理；但直接放开可能追趋势尾部。 |
| 权重重平衡 | 不建议现在做 | 等 12H/回测 | 当前已发现 Claude 对 RSI raw_score > 1 的前提不适用于现代码；权重改动属于大手术。 |
| 降阈值 | 不建议 | 否 | 当前问题仍不是最终阈值为主。 |

## 需要优先修的不是入场，而是持仓风控

TRUMP 暴露的问题：策略能在 15:15 开多，但没有在 1H/MACD/RSI 明显变坏时主动退出，最后等价格止损。

建议 Claude 优先评审一个 `position_exit_signal_guard`：

```text
LONG 持仓提前退出条件候选：
- 1H signal 从 bullish/growing 转为 flip_bearish 或 green_bar_shrinking 且 RSI_1H 下行
- MACD_1H histogram 连续 2 根走弱，或 15m 已 flip_bearish
- engine=NO_TRADE 且 ADX 高于 55，持仓方向与 4H flip 反向
- VWAP dev 从入场顺势转为明显反向偏离

动作：
- 不等固定 2%/4% 价格止损
- 先减仓 50% 或直接 close，具体需回放 TRUMP 与近 30D 止损样本
```

## 建议下一步

1. 先确认部署是否真的加载：runtime 里 `probe_floor_rescue.shadow_mode` 仍是 `true`，这必须先查。
2. 暂停继续放松入场门控，先加/回测持仓侧反向信号止损，TRUMP 说明退出慢比开仓少更危险。
3. 等 12H 日志后再评估方向门控、RSI soft penalty、VWAP ATR gate；其中 VWAP ATR gate 必须单独回测。
4. 权重重平衡最后做，且先修正 Claude 提案里不符合当前代码的前提。

一句话：最新 2H 不能证明上次两项代码修复无效，因为运行日志疑似仍未加载 live probe 配置；但可以证明“只修 final 仓位门槛”不足以解决开仓少。当前更紧急的风险是 TRUMP 这种入场后反向信号未触发提前止损。
