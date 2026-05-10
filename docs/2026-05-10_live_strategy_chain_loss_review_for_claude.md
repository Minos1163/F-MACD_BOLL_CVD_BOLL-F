# Live Strategy Chain + Loss Attribution Review For Claude

Date: `2026-05-10`

Window:
- Beijing start: `2026-05-08 19:00:00+08:00`
- Beijing end from logs: `2026-05-10 09:30:13.636670+08:00`
- UTC start: `2026-05-08 11:00:00+00:00`

## Executive Summary

- Scoring weights currently sum to `1.15`, not `1.00`.
- The strategy does not normalize by total weight. It adds component scores and then caps final score at `1.0`.
- The old `0.85` default exists only as fallback/legacy in code and some outer DCA/winner configs. The active MACD V2 live entry thresholds are much lower.
- The observed `0.64` threshold is from the actual runtime logs in this window. Current workspace config is not identical to the logged runtime threshold ladder.
- Current workspace config has `default/min_signal_score=0.68`, `red_bar_growing=0.68`, `green_bar_growing=0.69`, `flip_bearish=0.66`, `flip_bullish=0.64`.
- Runtime logs in this window show a lower ladder: `flip_bullish=0.60`, `flip_bearish=0.62`, `red_bar_growing=0.64`, `green_bar_growing=0.65`, and trial/preflip around `0.66`.
- This review uses compact live logs. Attribution metadata omits many debug fields, so runtime text lines are used for detailed score examples and distribution checks.

## Weight Distribution

| component | weight |
| --- | --- |
| weight_1h_direction | 0.150000 |
| weight_4h_direction | 0.400000 |
| weight_4h_enhancement | 0.100000 |
| weight_rsi_rhythm | 0.300000 |
| weight_vwap | 0.050000 |
| weight_15m_entry | 0.050000 |
| weight_volume | 0.100000 |

Weight sum: `1.15`.

Important interpretation: `weight_4h_enhancement=0.10` is configured, but current scoring folds the 4H enhancement bonus into the capped 4H direction score. The emitted `score_4h_enhancement` is often `0.0`; the effective bonus can appear inside `score_4h`.

## Active Entry Thresholds

| threshold | value |
| --- | --- |
| default | 0.680000 |
| min_entry_score | 0.250000 |
| min_signal_score | 0.680000 |
| soft_long_min_signal_score | 0.660000 |
| stable_bear_continuation_min_signal_score | 0.680000 |
| stable_bull_continuation_min_signal_score | 0.680000 |
| red_bar_growing | 0.680000 |
| green_bar_growing | 0.690000 |
| flip_bearish | 0.660000 |
| flip_bullish | 0.640000 |


Threshold resolution in code:

```text
threshold_signal_type = 4H signal type when primary_mode=4h
threshold = resolve_entry_threshold(signal_type, entry_type_15m, trial/stable flags)
if neutral_upgrade applies: threshold = min(threshold, neutral_upgrade_override)
if RSI spring override applies: threshold = min(threshold, spring_override_min_signal_score)
if RSI launch sovereign applies: threshold = min(threshold, sovereign_threshold)
entry passes only if score >= threshold
```

## Runtime Threshold Distribution

| threshold | samples |
| --- | --- |
| 0.600000 | 103 |
| 0.620000 | 163 |
| 0.640000 | 2682 |
| 0.650000 | 771 |
| 0.660000 | 983 |


Runtime final-stage threshold sources:

| Source | Count | Observed threshold |
|---|---:|---:|
| `primary_4h_red_bar_growing` | 86 | `0.64` |
| `preflip_trial` / `-` | 53 | `0.66` |
| `primary_4h_green_bar_growing` | 32 | `0.65` |
| `primary_4h_flip_bearish` | 10 | `0.62` |
| `primary_4h_flip_bullish` | 10 | `0.60` |

This is the concrete reason `0.64` appears in live logs despite the older mental model of `0.85`.

## Runtime Final Score Examples

| symbol | operation | status | stage | direction | signal_1h | signal_4h | score_1h | score_4h | score_vwap | score_15m | score_vol | total | threshold | threshold_source | trial | target_portion | leverage_actual |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ATOMUSDT | BUY | pending(挂单待成交) | final | long | red_bar_growing | flip_bullish | 0.340000 | 0.150000 | 0.000000 | 0.005300 | 0.033000 | 0.633200 | 0.600000 | primary_4h_flip_bullish | False | 0.210000 | 3.000000 |
| VETUSDT | HOLD | noop | final | short | green_bar_growing | flip_bearish | 0.340000 | 0.150000 | 0.000000 | 0.005300 | 0.033000 | 0.633200 | 0.620000 | primary_4h_flip_bearish | False | 0.000000 | 3.000000 |
| DOGEUSDT | HOLD | noop | final | short | green_bar_growing | flip_bearish | 0.340000 | 0.150000 | 0.000000 | 0.005300 | 0.033000 | 0.633200 | 0.620000 | primary_4h_flip_bearish | False | 0.000000 | 3.000000 |
| BCHUSDT | SELL | pending(挂单待成交) | final | short | flip_bearish | green_bar_shrinking | 0.400000 | 0.025000 | 0.000000 | 0.008700 | 0.033000 | 0.641800 | 0.640000 | primary_4h_green_bar_shrinking | False | 0.010000 | 3.000000 |
| MORPHOUSDT | HOLD | noop | final | short | flip_bearish | green_bar_growing | 0.400000 | 0.150000 | 0.000000 | 0.003500 | 0.033000 | 0.656500 | 0.650000 | primary_4h_green_bar_growing | False | 0.000000 | 3.000000 |
| MORPHOUSDT | HOLD | noop | final | short | flip_bearish | green_bar_growing | 0.400000 | 0.150000 | 0.000000 | 0.003500 | 0.033000 | 0.656500 | 0.650000 | primary_4h_green_bar_growing | False | 0.000000 | 3.000000 |
| TONUSDT | SELL | pending(挂单待成交) | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.138000 | 0.000000 | 0.008700 | 0.033000 | 0.660000 | 0.660000 | - | True | 0.000000 | 3.000000 |
| ZECUSDT | HOLD | noop | final | long | red_bar_growing | green_bar_shrinking | 0.340000 | 0.144300 | 0.000000 | 0.007000 | 0.033000 | 0.664300 | 0.660000 | - | True | 0.000000 | 3.000000 |
| ETCUSDT | HOLD | noop | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.107600 | 0.000000 | 0.008700 | 0.033000 | 0.664300 | 0.660000 | - | True | 0.000000 | 3.000000 |
| SOLUSDT | SELL | pending(挂单待成交) | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.107900 | 0.000000 | 0.008700 | 0.033000 | 0.664700 | 0.660000 | - | True | 0.000000 | 3.000000 |
| ETCUSDT | HOLD | noop | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.109400 | 0.000000 | 0.008700 | 0.033000 | 0.666100 | 0.660000 | - | True | 0.000000 | 3.000000 |
| ZECUSDT | HOLD | noop | final | long | red_bar_growing | green_bar_shrinking | 0.340000 | 0.148400 | 0.000000 | 0.007000 | 0.033000 | 0.668400 | 0.660000 | - | True | 0.000000 | 3.000000 |
| JUPUSDT | SELL | pending(挂单待成交) | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.073400 | 0.000000 | 0.012200 | 0.033000 | 0.668500 | 0.660000 | - | True | 0.000000 | 3.000000 |
| TONUSDT | HOLD | noop | final | short | green_bar_growing | green_bar_growing | 0.340000 | 0.150000 | 0.000000 | 0.007000 | 0.067000 | 0.668800 | 0.650000 | primary_4h_green_bar_growing | False | 0.000000 | 3.000000 |
| JUPUSDT | HOLD | noop | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.073800 | 0.000000 | 0.012200 | 0.033000 | 0.668800 | 0.660000 | - | True | 0.000000 | 3.000000 |
| JUPUSDT | HOLD | noop | final | short | green_bar_growing | red_bar_shrinking | 0.340000 | 0.074000 | 0.000000 | 0.012200 | 0.033000 | 0.669000 | 0.660000 | - | True | 0.000000 | 3.000000 |
| POLUSDT | BUY | pending(挂单待成交) | final | long | red_bar_growing | flip_bullish | 0.340000 | 0.150000 | 0.000000 | 0.007000 | 0.033000 | 0.670000 | 0.600000 | primary_4h_flip_bullish | False | 0.290000 | 3.000000 |
| SOLUSDT | BUY | pending(挂单待成交) | final | long | red_bar_growing | flip_bullish | 0.340000 | 0.150000 | 0.000000 | 0.007000 | 0.033000 | 0.670000 | 0.600000 | primary_4h_flip_bullish | False | 0.290000 | 3.000000 |
| SOLUSDT | HOLD | noop | final | long | red_bar_growing | flip_bullish | 0.340000 | 0.150000 | 0.000000 | 0.007000 | 0.033000 | 0.670000 | 0.600000 | primary_4h_flip_bullish | False | 0.000000 | 3.000000 |
| VETUSDT | CLOSE | pending(挂单待成交) | final | long | red_bar_growing | flip_bullish | 0.340000 | 0.150000 | 0.000000 | 0.007000 | 0.033000 | 0.670000 | 0.600000 | primary_4h_flip_bullish | False | 0.350000 | 3.000000 |


## Loss Attribution Since Start

- Decision events: `3254`
- Entry decisions: `51`
- Non-DCA entry decisions: `49`
- Deduped fills: `153`
- Realized PnL in fill window: `8.279047 USDT`
- Matched closed entries: `44`
- Matched closed entry PnL: `6.732727 USDT`
- Matched win rate: `63.64%`
- Meaningful target threshold: `target_portion >= 0.0100`
- Meaningful matched entries: `29`
- Meaningful matched PnL: `6.582189 USDT`
- Meaningful matched win rate: `68.97%`
- Micro-notional matched entries: `15`
- Micro-notional matched PnL: `0.150538 USDT`
- Micro-notional matched win rate: `53.33%`

Loss concentration:

- Losing LONG entries: `6`, total matched PnL about `-3.72 USDT`.
- Losing SHORT entries: `10`, total matched PnL about `-1.51 USDT`.
- The largest loss cluster is ordinary long `macd_v2_long_1h_red_bar_growing_15m__vwap_0.25`.
- Short losses are more numerous but mostly smaller; the weakest short family by win rate is `short_1h_flip_bearish` in this slice.
- `vol_vwap_warn` is `False` for the top matched losses, so this particular window's losses are not explained by the previous weak VWAP warning bucket.
- A large share of losing longs had `vwap_score=0.25`, which passed current VWAP quality. This suggests the current VWAP gate did not distinguish the long loss tail in this window.

### Top Matched Losses

| bj | symbol | side | matched_realized_pnl | target_portion | leverage | regime | regime_adx | vwap_score | score_volume | vol_vwap_warn | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-09 06:15:12.973638+08:00 | PUMPUSDT | LONG | -1.382645 | 0.336000 | 1 | TREND | 57.373400 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-09 16:15:13.154659+08:00 | ZROUSDT | LONG | -0.826060 | 0.117600 | 1 | TREND | 40.828800 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-09 17:45:12.731597+08:00 | MORPHOUSDT | SHORT | -0.825830 | 0.285600 | 3 | TREND | 37.250200 | 0.250000 | 0.033000 | False | macd_v2_short_1h_flip_bearish_15m__vwap_0.25 |
| 2026-05-09 06:00:13.631126+08:00 | ALGOUSDT | LONG | -0.773110 | 0.336000 | 1 | TREND | 36.378200 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-08 19:30:13.162678+08:00 | VETUSDT | LONG | -0.295952 | 0.117600 | 2 | TREND | 32.574600 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-08 19:15:13.246051+08:00 | POLUSDT | LONG | -0.235350 | 0.336000 | 1 | TREND | 50.586500 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-09 09:45:12.937188+08:00 | TRUMPUSDT | LONG | -0.204100 | 0.336000 | 1 | TREND | 55.938100 | 0.250000 | 0.033000 | False | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| 2026-05-08 19:45:12.782197+08:00 | TONUSDT | SHORT | -0.150860 | 0.002499 | 1 | NO_TRADE | 29.456200 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m__vwap_1.00 |
| 2026-05-09 02:00:13.515445+08:00 | ALGOUSDT | SHORT | -0.146430 | 0.002499 | 2 | TREND | 27.004700 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume_vwap_1.00 |
| 2026-05-08 21:00:13.835874+08:00 | VETUSDT | SHORT | -0.086056 | 0.017500 | 3 | TREND | 36.551800 | 0.694800 | 0.033000 | False | macd_v2_short_1h_flip_bearish_15m__vwap_0.69 |
| 2026-05-08 21:45:12.924569+08:00 | ZECUSDT | SHORT | -0.074910 | 0.008925 | 3 | RANGE | 14.138100 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume_vwap_1.00 |
| 2026-05-10 00:15:13.104135+08:00 | JUPUSDT | SHORT | -0.063000 | 0.002499 | 1 | NO_TRADE | 42.348800 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume_vwap_1.00 |
| 2026-05-08 21:15:13.096431+08:00 | ALGOUSDT | SHORT | -0.061200 | 0.003124 | 2 | TREND | 22.279800 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume_vwap_1.00 |
| 2026-05-10 00:45:13.394642+08:00 | SOLUSDT | SHORT | -0.043800 | 0.000490 | 1 | TREND | 41.860500 | 1.000000 | 0.033000 | False | macd_v2_short_1h_green_bar_growing_15m__vwap_1.00 |
| 2026-05-10 07:30:13.337091+08:00 | BCHUSDT | SHORT | -0.043700 | 0.010500 | 1 | TREND | 29.486300 | 0.250000 | 0.033000 | False | macd_v2_short_1h_flip_bearish_15m__vwap_0.25 |


### Outcome By Side

| side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| LONG | 25 | 19 | 6 | 76.00% | 5.963625 | 0.238545 |
| SHORT | 19 | 9 | 10 | 47.37% | 0.769102 | 0.040479 |


### Outcome By Side, Meaningful Positions Only

| side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| LONG | 25 | 19 | 6 | 76.00% | 5.963625 | 0.238545 |
| SHORT | 4 | 1 | 3 | 25.00% | 0.618564 | 0.154641 |


### Outcome By Side, Micro-Notional Positions

| side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| SHORT | 15 | 8 | 7 | 53.33% | 0.150538 | 0.010036 |


### Outcome By Position Accounting

| position_accounting | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| meaningful | 29 | 20 | 9 | 68.97% | 6.582189 | 0.226972 |
| micro_notional | 15 | 8 | 7 | 53.33% | 0.150538 | 0.010036 |


### Outcome By Regime

| regime | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| TREND | 35 | 23 | 12 | 65.71% | 2.747057 | 0.078487 |
| RANGE | 5 | 3 | 2 | 60.00% | 2.561380 | 0.512276 |
| NO_TRADE | 4 | 2 | 2 | 50.00% | 1.424290 | 0.356072 |


### Outcome By VWAP Bucket

| vwap_bucket | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| (0.12,0.25] | 27 | 19 | 8 | 70.37% | 4.160615 | 0.154097 |
| >0.5 | 16 | 8 | 8 | 50.00% | 1.628552 | 0.101784 |
| (0.25,0.5] | 1 | 1 | 0 | 100.00% | 0.943560 | 0.943560 |


### Outcome By Signal Family

| reason_family | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| macd_v2_long_1h_red_bar_growing_15m_ | 25 | 19 | 6 | 76.00% | 5.963625 | 0.238545 |
| macd_v2_short_1h_flip_bearish_15m_ | 4 | 1 | 3 | 25.00% | 0.618564 | 0.154641 |
| macd_v2_short_1h_green_bar_growing_15m_ | 9 | 6 | 3 | 66.67% | 0.188538 | 0.020949 |
| macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume | 6 | 2 | 4 | 33.33% | -0.038000 | -0.006333 |


## Entry And Position Chain

1. `fund_flow_bot` gets market data and builds flow snapshot.
2. `FundFlowDecisionEngine` runs MACD MTF V2 and creates `MACDSignalV2`.
3. `macd_strategy_v2` gates in stages: 1H direction, BOLL/EMA structure, VWAP, 4H enhancement, RSI rhythm, strict filters, score aggregation, final threshold check.
4. Score aggregation currently uses:
   - 1H direction score up to `weight_1h_direction`.
   - 4H direction score up to `weight_4h_direction`, with folded 4H enhancement bonus.
   - RSI rhythm weighted score `raw_score * weight_rsi_rhythm`.
   - VWAP score from VWAP location model.
   - 15m entry score up to `weight_15m_entry`.
   - Volume score up to `weight_volume`.
   - Multiplicative penalties for RSI/MACD conflict, neutral upgrade, flip-bullish filters, and overheat.
   - Final score is capped with `min(score, 1.0)`.
5. If `score < signal_score_threshold`, the signal is downgraded to HOLD.
6. If it passes, dynamic stop is calculated and decision metadata carries score, threshold, stop, route, and sizing hints.
7. Bot applies pretrade risk gate, same-side add guard, conflict protection, protection-gap block, active symbol capacity, min-open-portion, and position cap.
8. Orders are submitted through the execution router; pending entry protection is deferred until fill, then protection hooks/SLA monitor attach or repair TP/SL.

## Position Management And Risk Controls

Configured fund-flow position values:

```json
{
  "default_target_portion": 0.35,
  "add_position_portion": 0.6,
  "max_symbol_position_portion": 0.35,
  "min_open_portion": 0.06,
  "max_active_symbols": 3,
  "default_leverage": 4,
  "min_leverage": 3,
  "max_leverage": 5
}
```

Configured RSI rhythm values:

```json
{
  "period": 4,
  "rhythm": {
    "enabled": true,
    "enable_hard_veto": true,
    "enable_1h_direction_gate": true,
    "direction_flat_threshold": 0.3,
    "enable_leading_conflict_pass": true,
    "leading_slope_threshold": 2.0,
    "conflict_penalty_mult": 0.95,
    "conflict_threshold": 0.2,
    "leading_portion_mult": 0.8,
    "divergence_portion_mult": 0.85,
    "high_score_min": 0.3,
    "block_score": -0.3,
    "probe_exposure_mult": 0.2,
    "probe_portion_scale": 0.25,
    "probe_forced_leverage": 2
  }
}
```

Configured MACD V2 position management:

```json
{
  "priority_allocation_overdraft_pct": 0.08,
  "enable_red_bar_growing_probe_overlay": false,
  "red_bar_growing_probe_position_penalty": 0.5,
  "red_bar_growing_probe_max_leverage": 2,
  "enable_green_bar_growing_probe_overlay": true,
  "green_bar_growing_probe_position_penalty": 0.1,
  "green_bar_growing_probe_max_leverage": 2,
  "vol_vwap_warn_position_scale": 0.5
}
```

Configured pretrade risk gate:

```json
{
  "enabled": false,
  "force_exit_on_gate": false,
  "phase1_entry_only": true,
  "shadow_mode": false,
  "entry_block_actions": [
    "EXIT",
    "BLOCK",
    "AVOID"
  ],
  "entry_hold_portion_scale": 0.75,
  "entry_hold_leverage_cap": 4,
  "exit_close_ratio": 0.5,
  "exit_score_threshold": 0.2,
  "exit_confirm_bars": 3,
  "exit_min_hold_seconds": 300,
  "exit_profit_lock_enabled": true,
  "exit_profit_lock_min_pnl": 0.0035,
  "exit_profit_lock_require_score_ok": true,
  "exit_profit_lock_require_followthrough": true,
  "exit_require_price_followthrough": true,
  "exit_price_change_min": 0.002,
  "exit_drawdown_override": 0.015,
  "exit_trend_hold_enabled": true,
  "exit_trend_hold_min_score": 0.25,
  "exit_trend_hold_min_gap": 0.12,
  "entry_threshold": 0.06,
  "entry_threshold_capture": 0.05,
  "max_drawdown": 0.02,
  "max_exposure_per_trade": 0.22,
  "volatility_cap": 0.012,
  "volatility_cap_capture": 0.014,
  "momentum_scale": 260,
  "trend_weight": 0.45,
  "momentum_weight": 0.3,
  "volatility_weight": 0.2,
  "drawdown_weight": 0.35
}
```

## Specific Questions For Claude

1. Is it coherent for configured scoring weights to sum to `1.15` while the final score is capped at `1.0`, or should the components be normalized/rebalanced?
2. Are current active thresholds (`0.64-0.69`) too low compared with the historical `0.85` target, given the current component scores and observed loss cases?
3. Should `primary_4h_red_bar_growing` and `flip_bullish` remain at `0.64`, or should they return toward `0.75-0.85`?
4. Do top losses cluster around low VWAP quality, specific regimes, or trial entries enough to justify another gate?
5. Should tiny `target_portion` entries created by min-notional adjustment be treated as probes with separate accounting?
6. Are protection-gap and active-symbol-cap blocks protecting correctly, or are they causing adverse selection by leaving weaker fills active?

## Caveats

- Entry-to-PnL matching is approximate: realized PnL fills are matched to the latest prior same-symbol, same-side non-DCA entry.
- Compact attribution metadata omits detailed score fields; runtime logs are used for detailed score examples.
- Some realized PnL can belong to positions opened before the window and is included only in total fill PnL, not matched entry PnL.
