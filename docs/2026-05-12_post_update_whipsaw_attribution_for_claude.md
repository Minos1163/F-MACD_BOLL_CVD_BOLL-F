# 2026-05-12 Post-Update Whipsaw Attribution For Claude

**审阅窗口**: `2026-05-11 21:30:16.641714+08:00` -> `2026-05-12 21:30:16.641714+08:00`
**日志来源**: `logs\2026-05\2026-05-11; logs\2026-05\2026-05-12-1; logs\2026-05\2026-05-12-2`
**对照文档**: `docs\2026-05-11_latest_24h_btc_selloff_loss_attribution_for_claude.md`

## Executive Summary

- 最新 24H 决策事件 `2754`，其中 `BUY=2`、`SELL=11`、`HOLD=2741`。
- 去重成交 `36`，realized PnL `2.524391 USDT`。
- 权益从 `105.960981` 到 `108.752099`，净变化 `2.791118 USDT` (`2.63%`)。
- 低点 `2026-05-12 09:00:05.493555+08:00` total_assets=`104.776439`，随后到窗口末端修复 `3.97566 USDT` (`3.79%`)。
- 结论：策略不是完全停摆，而是上升段只开了 2 笔 LONG，且都在上升后半段/回落前入场；下跌段直到 14:00 BJ 后才集中开 SHORT，错过 08:00-09:30 的主要下跌。
- 双腿对冲目标没有真正实现：本窗口没有出现 `dual_leg_allowed` 日志，反向保护只存在于配置和极端 ATR 条件里，未形成 BTC 主导冲击时的实时对冲。
- 昨天的 P0 配置修复有副作用：`min_vwap_score_for_entry=0.12` 和 dynamic sizing 降低了低 VWAP 追涨风险，但也把大量信号压成 `target < min_open_portion`，尤其是高分 SHORT 只剩微仓位、被最小下单阈值过滤。

## Portfolio Timeline

```json
{
  "start": {
    "bj": "2026-05-11 21:45:04.958971+08:00",
    "cash": 36.971916,
    "total_assets": 105.960981,
    "position_count": 1,
    "active_symbols": "BCHUSDT"
  },
  "end": {
    "bj": "2026-05-12 21:30:16.641213+08:00",
    "cash": 55.37888,
    "total_assets": 108.752099,
    "position_count": 0,
    "active_symbols": ""
  },
  "high": {
    "bj": "2026-05-12 21:30:05.138256+08:00",
    "cash": 55.37888,
    "total_assets": 108.752099,
    "position_count": 1,
    "active_symbols": "XLMUSDT"
  },
  "low": {
    "bj": "2026-05-12 09:00:05.493555+08:00",
    "cash": 36.220931,
    "total_assets": 104.776439,
    "position_count": 1,
    "active_symbols": "BTCUSDT"
  },
  "start_to_end_delta": 2.791118,
  "start_to_end_pct": 0.026341,
  "high_to_low_delta": -3.97566,
  "high_to_low_pct": -0.036557,
  "low_to_end_delta": 3.97566,
  "low_to_end_pct": 0.037944
}
```

## Market Path Proxy

| symbol | start_bj | start_price | high_bj | high_price | low_bj | low_price | end_price | start_to_high_pct | high_to_end_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 2026-05-11 22:30:06 | 80710.900000 | 2026-05-12 02:30:05 | 81992.000000 | 2026-05-12 19:15:06 | 80542.400000 | 80764.400000 | 1.59% | -1.50% |
| ETHUSDT | 2026-05-11 22:30:07 | 2311.900000 | 2026-05-12 06:15:06 | 2340.900000 | 2026-05-12 19:15:06 | 2282.530000 | 2283.830000 | 1.25% | -2.44% |
| BNBUSDT | 2026-05-11 22:30:17 | 654.130000 | 2026-05-12 07:45:07 | 672.790000 | 2026-05-11 22:30:17 | 654.130000 | 661.160000 | 2.85% | -1.73% |
| SOLUSDT | 2026-05-11 22:00:05 | 95.190000 | 2026-05-12 04:00:08 | 98.150000 | 2026-05-12 19:30:04 | 94.720000 | 94.940000 | 3.11% | -3.27% |
| DOGEUSDT | 2026-05-11 22:00:06 | 0.109880 | 2026-05-12 01:45:05 | 0.111670 | 2026-05-12 19:30:08 | 0.108790 | 0.109110 | 1.63% | -2.29% |


## Actual Entries After Update

| bj | symbol | side | portion | pnl | regime | adx | atr_pct | vwap | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-11 22:30:17 | BNBUSDT | SHORT | 0.214200 | -0.103600 | TREND | 20.560000 | 0.48% | 0.783000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.78 |
| 2026-05-11 23:00:17 | SOLUSDT | SHORT | 0.214200 | -0.222000 | TREND | 15.070000 | 0.81% | 0.850000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.85 |
| 2026-05-12 00:15:16 | BTCUSDT | LONG | 0.201600 | -0.868000 | TREND | 19.540000 | 0.49% | 0.169200 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.17 |
| 2026-05-12 00:45:16 | DOGEUSDT | LONG | 0.151200 | -0.148920 | TREND | 20.810000 | 0.97% | 0.184400 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.18 |
| 2026-05-12 02:00:17 | ONDOUSDT | SHORT | 0.214200 | -0.701910 | NO_TRADE | 23.210000 | 2.22% | 0.863000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.86 |
| 2026-05-12 05:00:17 | FETUSDT | SHORT | 0.214200 | 0.617400 | RANGE | 13.420000 | 1.29% | 0.917300 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.92 |
| 2026-05-12 07:15:16 | MORPHOUSDT | SHORT | 0.214200 | 0.477560 | TREND | 28.600000 | 0.91% | 0.653700 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.65 |
| 2026-05-12 14:00:16 | VETUSDT | SHORT | 0.171360 | 0.818511 | RANGE | 8.150000 | 0.86% | 0.453700 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.45 |
| 2026-05-12 14:00:16 | SOLUSDT | SHORT | 0.214200 | 1.045000 | TREND | 37.390000 | 0.78% | 0.850000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.85 |
| 2026-05-12 14:00:16 | XLMUSDT | SHORT | 0.214200 | 0.000000 | TREND | 30.410000 | 0.77% | 0.816300 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.82 |
| 2026-05-12 14:15:16 | AAVEUSDT | SHORT | 0.214200 | 0.414000 | TREND | 32.710000 | 1.01% | 0.865600 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.87 |
| 2026-05-12 16:30:16 | POLUSDT | SHORT | 0.214200 | 0.000000 | TREND | 24.950000 | 0.68% | 0.638000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.64 |
| 2026-05-12 21:15:17 | BTCUSDT | SHORT | 0.214200 | 0.000000 | TREND | 59.100000 | 0.39% | 0.645000 | macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.65 |


### Entry Summary By Side

| side | entries | avg_portion | closed | pnl |
| --- | --- | --- | --- | --- |
| LONG | 2 | 0.176400 | 2 | -1.016920 |
| SHORT | 11 | 0.210305 | 8 | 2.344961 |


### Entry Summary By Family

| family | entries | avg_portion | closed | pnl |
| --- | --- | --- | --- | --- |
| macd_v2_long_1h_red_bar_growing_15m_ | 2 | 0.176400 | 2 | -1.016920 |
| macd_v2_short_1h_green_bar_shrinking_15m_ | 11 | 0.210305 | 8 | 2.344961 |


## Fill PnL By Symbol

| symbol | fills | pnl | notional |
| --- | --- | --- | --- |
| BTCUSDT | 3 | -0.868000 | 243.425500 |
| ONDOUSDT | 3 | -0.701910 | 60.966910 |
| AVAXUSDT | 1 | -0.690000 | 51.060000 |
| DOGEUSDT | 2 | -0.148920 | 48.469080 |
| BNBUSDT | 3 | -0.103600 | 52.452400 |
| POLUSDT | 1 | 0.000000 | 27.670560 |
| XLMUSDT | 3 | 0.000000 | 52.972750 |
| AAVEUSDT | 2 | 0.414000 | 39.686000 |
| MORPHOUSDT | 3 | 0.477560 | 48.015560 |
| SOLUSDT | 5 | 0.517000 | 210.148400 |
| BCHUSDT | 1 | 0.520200 | 45.409380 |
| FETUSDT | 2 | 0.617400 | 58.678200 |
| VETUSDT | 6 | 0.818511 | 84.071759 |
| TRUMPUSDT | 1 | 1.672150 | 75.278300 |


## Top Realized Losses

| bj | symbol | fill_side | price | notional | pnl |
| --- | --- | --- | --- | --- | --- |
| 2026-05-12 09:36:11 | BTCUSDT | 卖出 | 80897.100000 | 80.897100 | -0.868000 |
| 2026-05-11 23:26:18 | AVAXUSDT | 买入 | 10.212000 | 51.060000 | -0.690000 |
| 2026-05-12 03:42:59 | ONDOUSDT | 买入 | 0.434900 | 24.180440 | -0.550440 |
| 2026-05-11 22:06:37 | SOLUSDT | 买入 | 95.820000 | 34.495200 | -0.306000 |
| 2026-05-11 23:24:47 | SOLUSDT | 买入 | 95.680000 | 35.401600 | -0.222000 |
| 2026-05-12 03:42:59 | ONDOUSDT | 买入 | 0.434900 | 6.653970 | -0.151470 |
| 2026-05-12 12:26:46 | DOGEUSDT | 卖出 | 0.110320 | 24.160080 | -0.148920 |
| 2026-05-11 23:06:34 | BNBUSDT | 买入 | 656.950000 | 26.278000 | -0.103600 |


## Runtime Blockers

### Marker Counts

```json
{
  "rsi_1h_direction_block": 2026,
  "vwap_hard_block": 927,
  "rsi_1h_direction_against_veto": 773,
  "rsi_15m_extreme_veto": 294,
  "threshold_low": 217,
  "rsi_1h_direction_flat_veto": 160,
  "target_below_min_open": 157,
  "short_regime_guard": 40,
  "dca_hold": 39,
  "active_symbol_capacity": 4
}
```

### Entry Gate Blocks

| gate | count | avg_score | top_symbols |
| --- | --- | --- | --- |
| min_open_portion | 157 | 0.768786 | FETUSDT, WLDUSDT, POLUSDT, ZROUSDT, ETCUSDT |
| active_symbol_capacity | 4 | 0.728413 | AVAXUSDT, WLDUSDT, BTCUSDT |
| same_side_add_guard | 1 | 0.000000 | ONDOUSDT |


### Highest-Score Blocked Entry Candidates

| bj | symbol | side | gate | score | threshold | value | vwap | signal_1h | signal_4h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-11 22:30:03 | WLDUSDT | SHORT | min_open_portion | 0.919300 | 0.660000 | 0.001312 | 0.875800 | green_bar_growing | flip_bearish |
| 2026-05-12 16:00:03 | WLDUSDT | SHORT | min_open_portion | 0.919100 | 0.690000 | 0.001312 | 0.871800 | green_bar_growing | green_bar_growing |
| 2026-05-12 17:15:03 | SUIUSDT | SHORT | min_open_portion | 0.918000 | 0.660000 | 0.001312 | 0.850000 | green_bar_growing | flip_bearish |
| 2026-05-12 07:15:03 | ONDOUSDT | SHORT | min_open_portion | 0.909000 | 0.690000 | 0.013125 | 0.850000 | flip_bearish | green_bar_growing |
| 2026-05-12 16:45:03 | FETUSDT | SHORT | min_open_portion | 0.890500 | 0.690000 | 0.001050 | 0.299600 | green_bar_growing | green_bar_growing |
| 2026-05-11 23:00:03 | BTCUSDT | SHORT | min_open_portion | 0.878100 | 0.660000 | 0.000175 | 0.692100 | green_bar_growing | red_bar_shrinking |
| 2026-05-11 21:45:03 | FETUSDT | SHORT | min_open_portion | 0.857900 | 0.690000 | 0.001750 | 0.907300 | green_bar_growing | green_bar_growing |
| 2026-05-11 23:00:03 | FETUSDT | SHORT | min_open_portion | 0.857600 | 0.690000 | 0.001312 | 0.903000 | green_bar_growing | green_bar_growing |
| 2026-05-11 22:45:03 | WLDUSDT | SHORT | min_open_portion | 0.857200 | 0.660000 | 0.001312 | 0.893100 | green_bar_growing | flip_bearish |
| 2026-05-11 23:00:03 | WLDUSDT | SHORT | min_open_portion | 0.855700 | 0.660000 | 0.001312 | 0.863600 | green_bar_growing | flip_bearish |
| 2026-05-12 14:30:03 | ONDOUSDT | SHORT | min_open_portion | 0.855700 | 0.690000 | 0.001312 | 0.864900 | green_bar_growing | green_bar_growing |
| 2026-05-12 11:15:03 | VETUSDT | SHORT | min_open_portion | 0.854145 | 0.690000 | 0.005355 | 0.471600 | green_bar_growing | green_bar_growing |


### MACD_V2 Score Stages

| stage | count | avg_total | top_signal_1h |
| --- | --- | --- | --- |
| rsi_rhythm | 1227 | 0.000000 | green_bar_growing, green_bar_shrinking, red_bar_shrinking, red_bar_growing |
| neutral_upgrade_gate | 554 | 0.000000 | green_bar_shrinking, red_bar_shrinking |
| vwap | 309 | 0.000000 | green_bar_growing, green_bar_shrinking, red_bar_growing, red_bar_shrinking |
| neutral_upgrade_mode | 250 | 0.000120 | red_bar_growing, flip_bullish, green_bar_growing, flip_bearish |
| threshold_check | 217 | 0.481494 | green_bar_shrinking, red_bar_growing, green_bar_growing, red_bar_shrinking |
| final | 52 | 0.757896 | green_bar_shrinking, green_bar_growing, red_bar_growing |
| green_bar_growing_short_adx_1h_range_filter | 44 | 0.000000 | green_bar_growing |
| vwap_score_filter | 22 | 0.000000 | red_bar_growing, red_bar_shrinking, green_bar_growing |
| rsi_neutral_resume_short_disabled | 21 | 0.681429 | green_bar_growing, green_bar_shrinking, red_bar_growing, flip_bearish |
| short_regime_guard | 20 | 0.523565 | flip_bearish |
| flip_bullish_sniper_gate | 14 | 0.000000 | flip_bullish |
| flip_bullish_cooling_gate | 3 | 0.000000 | flip_bullish |
| flip_bullish_disabled | 3 | 0.000000 | flip_bullish |


## 05-08 Comparison

| day | decision_events | entry_decisions | buy_entries | sell_entries | fill_pnl | assets_start | assets_end | asset_delta_pct | asset_high_to_low_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-08 | 2019 | 24 | 19 | 5 | 12.183023 | 99.844153 | 104.736298 | 4.90% | -7.71% |


05-08 的核心差异：当时主导交易族是 `LONG + red_bar_growing`，且允许 `vwap_score=0.25` 的大仓进入；这在微涨/顺风市场里捕捉了大部分上涨。05-12 更新后，低 VWAP floor 和 dynamic sizing 把这类早期追涨能力显著压低，但系统又没有引入可替代的 BTC shock / trend-following breakout 入口。

## Root Cause Findings

### [CRITICAL-1] 上升段失效：VWAP floor + RSI 方向门控使趋势早期 LONG 变稀疏

- BTC 22:30 BJ -> 02:30 BJ 从约 `80710.9` 涨到 `81992.0`，约 `+1.59%`；SOL 同期从 `94.97` 附近涨到 `98.15`，约 `+3.35%`。
- 策略在这个上涨段只开了 `BTC LONG 00:15` 和 `DOGE LONG 00:45` 两笔，且都是 `red_bar_growing`、低 VWAP 分 `0.1692/0.1844`，属于被 dynamic sizing 压仓后的晚入场。
- 大量候选停在 `rsi_1h_direction_block / rsi_1h_direction_against_veto / 4H无明确方向`，说明 4H-primary + RSI 方向门控在反转初期太慢。

### [CRITICAL-2] 下跌段失效：没有 BTC shock 触发器，SHORT 在 14:00 后才集中出现

- BTC 从 02:30 BJ 高点 `81992` 回落到 09:00 BJ `81030`，再到 19:00 BJ `80631`。
- 08:00-09:30 的下跌主段中，系统已有 BTC/DOGE LONG，未触发双腿对冲；BTC 到 09:36 才止损/平仓，亏 `-0.868 USDT`。
- 14:00 BJ 才出现 `SOL/VET/XLM/AAVE/POL` 等 SHORT 群，说明 4H/MACD 反应滞后，下午才捕捉到跌势尾段。

### [CRITICAL-3] 双腿对冲没有真实上线到 BTC 主导冲击场景

- 本窗口 runtime marker 中 `dual_leg_allowed=0`。
- 当前极端双腿 gate 依赖 `current leg loss + signal_score + regime_atr_pct`；而 BTC 跌势初期 ATR 不一定达到阈值，且反向 SHORT 信号常被 RSI/4H/容量/最小仓位挡掉。
- 这解释了为什么“黑天鹅对冲”目标没有兑现：我们只放开了很窄的同品种反向例外，没有实现 BTC return/beta 级别的系统冲击检测。

### [HIGH-1] shrink cap 覆盖错层：实际成交多为 1H shrinking，不是 4H shrinking

- 昨天配置 `signal_type_caps.red_bar_shrinking/green_bar_shrinking` 只由 `signal_type_4h` 解析。
- 本窗口主要成交族是 `macd_v2_short_1h_green_bar_shrinking_15m__vwap_*`，但对应 4H 多数是 `green_bar_growing` 或 `flip_bearish`，所以 shrink cap 没有覆盖这些 1H shrink 成交。
- 结果仍出现 `0.2142/0.2856` 的 SHORT 仓位，而不是预期的 `<=0.10`。

### [HIGH-2] dynamic sizing 与 min_open_portion 相互打架，产生大量高分但不可下单的微仓信号

- `ENTRY_GATE_BLOCK.min_open_portion` 大量出现，且最高分 blocked 信号包括 `score>0.85` 的 SHORT。
- 典型：`BTCUSDT SHORT score=0.8781` 被压到 `target=0.000175 < min_open=0.06`；`ETHUSDT SHORT score≈0.86` 多次进入 short quality/filter/微仓路径但没有形成有效开仓。
- 这不是单纯门槛过高，而是仓位缩放链把信号质量和可执行性断开了：分数足够，但 target 被压到交易所/系统最小仓位以下。

### [MEDIUM-1] 05-08 的高收益来自顺风高 beta LONG 暴露，昨天更新削弱了这类暴露但没有补上趋势跟随替代路径

- 05-08 同口径：`entry_decisions=24`，`BUY=19`，`SELL=5`，fill PnL `+12.1830 USDT`，权益约 `+4.90%`。
- 最新 24H：`entry_decisions=14`，`BUY=2`，`SELL=12`，fill PnL `+0.6609 USDT`，权益约 `+1.61%`，并经历低点回撤。
- 换句话说，昨天更新减少了坏 LONG，但也砍掉了 05-08 那套赚钱的主要来源；下午 SHORT 修复了一部分，但没有替代早盘趋势捕捉能力。

## Questions For Claude

1. `signal_type_position_caps` 是否应该同时支持 `signal_type_1h` 和 `signal_type_4h`？当前只 cap 4H，导致 `1h_green_bar_shrinking` 仍能大仓开。
2. `min_open_portion=0.06` 与 dynamic sizing 是否应该联动？对于 score>0.85 但 target 被压到 0.001 的信号，是应放大到 probe 仓、还是彻底不生成 entry？
3. 是否应把 BTC/ETH/BNB 从 tradable 改为 context-only，直到大币独立参数回测通过？本窗口 BTC LONG 是最大亏损之一。
4. 双腿对冲是否应由 BTC 5m/15m return + volume shock 触发，而不是等待单品种 `regime_atr_pct`？
5. 4H-primary + RSI direction hard veto 是否应在 shock/reversal regime 下临时降级为 soft penalty？当前它在上升初期和下跌初期都明显滞后。
6. 是否需要恢复一个 05-08 风格的 trend-following LONG lane，但只在 BTC/ETH context 同向、且 account profit lock 未触发时允许？

## Suggested Next Experiment

```text
A. baseline_current_patched
B. current + signal_type_caps_apply_to_1h
C. current + min_open_probe_floor(score>=0.80 -> target=max(target,0.06))
D. current + BTC shock detector (context-only) + hedge shadow orders
E. current + disable BTC/ETH/BNB tradable, keep context-only
F. 05-08-style long lane restored with profit-lock and BTC context guard
```

验收标准：30D WR >= 72%，成交数 >= 55，总 PnL >= current 95%，最大回撤不高于 current；另需单独检查 05-11/05-12 两个冲击窗口的 high-to-low DD。
