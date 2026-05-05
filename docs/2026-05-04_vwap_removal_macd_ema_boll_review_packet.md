# VWAP Removal / MACD+EMA+RSI Resonance Review Packet

- Date: `2026-05-04`
- Purpose: Provide Claude with a focused review packet for removing VWAP as a live entry gate and validating whether MACD + EMA + RSI resonance can carry entry direction quality and profitability.
- Primary config: `config/trading_config_fund_flow.json`
- Candidate configs:
  - `config/candidate_a_no_vwap_gate.json`
  - `config/candidate_b_no_vwap_score.json`
  - `config/candidate_c_resonance_gate.json`
- Primary code:
  - `src/fund_flow/macd_strategy_v2.py`
  - `src/fund_flow/decision_engine.py`
  - `src/app/fund_flow_bot.py`
  - `scripts/backtest_macd_v2.py`
- Latest attribution output: `output/backtest/live_strict_30d_20260504_vwap_attr_final_summary.json`

## 1. Executive Conclusion

VWAP is an architecture error in the current MACD trend-continuation entry design, not a single-parameter tuning problem.

The latest strict-live 30d attribution shows:

```text
total_trades = 0
signals_generated = 0
vwap_score_filter = 35,454
vwap_hard_block = 3,591
candidate_entries = 0
orders_filled = 0
```

This is not a normal low-trade regime. It is a full strategy starvation event caused by VWAP gates converting all potential entries into neutral signals before execution.

Root cause:

```text
VWAP is being used as an entry license for a MACD trend strategy.
MACD continuation signals often occur away from VWAP by design.
weight_vwap is only 0.05, but VWAP floors and hard blocks hold 100% veto power.
This weight/gate mismatch is the design defect.
```

Do not continue blind global floor reductions such as `0.12 -> 0.10/0.08`. The veto distribution proves blockers are split across global long, short, preflip/trial, flip_bearish, and hard-block paths.

The required evaluation path is:

```text
candidate_a: remove VWAP gates only, keep weight_vwap=0.05
candidate_b: candidate_a + weight_vwap=0.0 and weight_rsi_rhythm=0.35
candidate_c: candidate_b + MACD+EMA+RSI resonance hard gate
```

Claude review ask:

```text
Do not approve VWAP removal unless MACD+EMA+RSI proves acceptable win rate and profit factor on 30d/60d data and does not re-admit the recent low-quality flip_bearish / low-volume long loss cluster.
```

Key decisions for review:

```text
1. Move weight_vwap 0.05 -> weight_rsi_rhythm, making RSI rhythm 0.35.
2. Protect flip_bearish with a 7-layer non-VWAP stack:
   ADX >= 30, 4H short alignment, 15m/enhancement confirmation,
   EMA not against, RSI rhythm >= 0.40, no RSI rebound/spring conflict,
   funding > 0.0005 and OI delta < 0.
3. Run candidate_a -> candidate_b -> candidate_c in order.
   If candidate_b already meets win rate/PF, candidate_c is optional protection, not mandatory deployment.
```

## 2. VWAP Formula And Current Parameters

### 2.1 Session VWAP Formula

Backtest computes session VWAP in `scripts/backtest_macd_v2.py::calculate_vwap()`:

```text
typical_price = (high + low + close) / 3
tpv = typical_price * volume
session_vwap[t] = cumulative_sum(tpv in same date) / cumulative_sum(volume in same date)
```

Grouping:

```text
date = pd.to_datetime(timestamp, unit='ms').dt.date
```

So the live/backtest VWAP input is effectively daily session VWAP by timestamp date.

### 2.2 Structural VWAP Formula

Current config:

```json
"structural_vwap_mode": "anchored_weekly",
"structural_vwap_rolling_window": 20
```

Anchored weekly VWAP:

```text
typical_price = (high + low + close) / 3
tpv = typical_price * volume
anchor_key = UTC week start
structural_vwap[t] = cumulative_sum(tpv since anchor) / cumulative_sum(volume since anchor)
```

If mode is `rolling`, formula becomes:

```text
rolling_vwap[t] = rolling_sum(tpv, window=20) / rolling_sum(volume, window=20)
```

### 2.3 VWAP Deviation Parameters

Current live config:

```json
"vwap_retest_tolerance": 0.003,
"vwap_deviation_optimal": 0.005,
"vwap_deviation_warning": 0.015,
"vwap_deviation_hard_block": 0.03
```

Definitions:

```text
session_deviation = (price - session_vwap) / session_vwap
structural_deviation = (price - structural_vwap) / structural_vwap
```

Hard block:

```text
long:  if price is more than +3.0% above session VWAP -> VWAP_HARD_BLOCK
short: if price is more than -3.0% below session VWAP -> VWAP_HARD_BLOCK
```

### 2.4 VWAP Score Formula

VWAP score is returned by `MACDStrategyV2Engine.calculate_vwap_score()`.

When structural VWAP is available:

```text
long location_score =
  0.36 * session_support_quality
+ 0.26 * structural_support_quality
+ 0.18 * reclaim_quality
+ 0.12 * dual_support_quality
+ 0.08 * value_proximity_quality
- 0.12 * extension_penalty

short location_score =
  0.36 * session_pressure_quality
+ 0.26 * structural_pressure_quality
+ 0.18 * retest_quality
+ 0.12 * dual_pressure_quality
+ 0.08 * value_proximity_quality
- 0.12 * extension_penalty

vwap_score = weight_vwap * clamp(location_score, 0, 1)
```

Current score weight:

```json
"weight_vwap": 0.05
```

Important detail:

```text
The score weight is small, but the hard entry floors are not small.
The strategy is currently blocked mostly by VWAP as a gate, not by VWAP score contribution.
```

## 3. Current VWAP Gates

Current entry floors:

| Gate | Current value |
|---|---:|
| `min_vwap_score_for_entry` | `0.12` |
| `short_min_vwap_score_for_entry` | `0.12` |
| `flip_bearish_short_min_vwap_score_for_entry` | `0.25` |
| `preflip_trial_min_vwap_score` | `0.12` |
| `trial_short_below_structure_promotion_min_vwap_score` | `0.12` |
| `stable_bear_continuation_min_vwap_score` | `0.12` |
| `stable_bull_continuation_min_vwap_score` | `0.12` |
| `flip_bullish_min_vwap_score` | `0.12` |
| `vol_vwap_warn_min_vwap_score` | `0.12` |
| `vol_vwap_warn_position_scale` | `0.0` |

Resolved entry floor logic:

```text
trial entry:
  long  -> max(preflip_trial_min_vwap_score, global_floor)
  short -> max(preflip_trial_min_vwap_score, short_floor)
  trial flip_bearish short -> max(preflip_trial_min_vwap_score, short_floor, flip_bearish_floor)

standard long:
  global_floor

standard flip_bullish long:
  max(global_floor, flip_bullish_min_vwap_score)

standard short:
  short_floor

standard flip_bearish short:
  max(short_floor, flip_bearish_floor)
```

## 4. Latest Backtest Attribution

Command used:

```powershell
python scripts/backtest_macd_v2.py `
  --config config/trading_config_fund_flow.json `
  --strict-live-mode `
  --simulate-live-close-layers `
  --output-prefix output/backtest/live_strict_30d_20260504_vwap_attr_final
```

Data note:

```text
Local cache latest complete 30d window is not 2026-04-04 -> 2026-05-04.
It is the latest available local cache window around 2026-02-23 -> 2026-03-24.
```

Result:

| Metric | Value |
|---|---:|
| Return | `0.00%` |
| Trades | `0` |
| Signals generated | `0` |
| Candidate entries | `0` |
| Orders filled | `0` |
| Max drawdown | `0.00%` |
| `vwap_score_filter` | `35,454` |
| `vwap_hard_block` | `3,591` |

VWAP veto distribution by floor:

| Floor source | Count |
|---|---:|
| `short_floor` | `15,835` |
| `global_long_floor` | `15,808` |
| `preflip_trial_floor` | `6,354` |
| `flip_bearish_short_floor` | `1,032` |
| `flip_bullish_floor` | `16` |

VWAP veto distribution by side:

| Side | Count |
|---|---:|
| Short | `20,949` |
| Long | `18,096` |

VWAP veto distribution by signal:

| Signal | Count |
|---|---:|
| `green_bar_growing` | `10,387` |
| `red_bar_growing` | `9,695` |
| `green_bar_shrinking` | `8,620` |
| `red_bar_shrinking` | `8,560` |
| `flip_bearish` | `1,763` |
| `flip_bullish` | `20` |

Representative blocked `flip_bearish` examples:

```json
{
  "symbol": "ICPUSDT",
  "signal_type_1h": "flip_bearish",
  "trade_direction": "short",
  "floor_source": "flip_bearish_short_floor",
  "min_vwap_score_for_entry": 0.25,
  "vwap_score": 0.0309,
  "reason": "vwap_score_filter(0.0309<0.2500)"
}
```

Interpretation:

```text
VWAP gates block all entries, not just the known-bad recent loss cluster.
Lowering only global min_vwap_score_for_entry from 0.12 to 0.10 or 0.08 did not restore trades.
The blockers are split across short_floor, global_long_floor, preflip_trial_floor, and hard block.
```

## 5. Why VWAP Is Failing In This Strategy

Current failure mode:

```text
VWAP is used as a hard admission gate for a MACD/EMA/RSI trend strategy.
But many MACD continuation opportunities naturally occur away from VWAP.
The hard floor rejects trend continuation even when MACD, EMA, and RSI rhythm may be aligned.
```

Specific issues:

```text
1. VWAP gate is stronger than its configured score weight.
   weight_vwap is only 0.05, but entry floors of 0.12/0.25 act as hard vetoes.

2. VWAP hard block rejects extension.
   Trend continuation often looks extended versus VWAP; the current logic treats this as unsafe.

3. VWAP blocks both sides broadly.
   Counts are roughly balanced: short 20,949 and long 18,096.

4. Global floor ablation did not help.
   0.12 -> 0.10/0.08 still produced zero trades because short/preflip/special floors and hard block remain.

5. VWAP is not the same as direction quality.
   A low VWAP score does not prove MACD/EMA direction is wrong; it only says the price location is poor relative to VWAP definitions.
```

## 6. Proposed VWAP Removal Experiments

Do not directly deploy VWAP removal. Use ablation.

### 6.1 Baseline

```text
baseline_live_strict:
  current config
  expected from latest run: 0 trades
```

### 6.2 Remove VWAP Gate Only

Goal:

```text
Test whether MACD/EMA/RSI still select profitable entries when VWAP no longer blocks admission.
```

Config changes for experiment only:

```json
{
  "min_vwap_score_for_entry": 0.0,
  "short_min_vwap_score_for_entry": 0.0,
  "flip_bearish_short_min_vwap_score_for_entry": 0.0,
  "preflip_trial_min_vwap_score": 0.0,
  "trial_short_below_structure_promotion_min_vwap_score": 0.0,
  "stable_bear_continuation_min_vwap_score": 0.0,
  "stable_bull_continuation_min_vwap_score": 0.0,
  "flip_bullish_min_vwap_score": 0.0,
  "vwap_deviation_hard_block": 999.0
}
```

Keep initially:

```text
weight_vwap = 0.05
vol_vwap_warn_position_scale = 0.0
```

Reason:

```text
This isolates gate removal from score removal.
```

### 6.3 Remove VWAP From Score

Goal:

```text
Test pure non-VWAP signal quality.
```

Additional config:

```json
{
  "weight_vwap": 0.0,
  "vol_vwap_warn_position_scale": 1.0
}
```

Risk:

```text
This can re-admit the weak low-VWAP, low-volume loss cluster.
Must be combined with volume plus MACD / EMA / RSI direction gates.
```

## 7. Required MACD + EMA + RSI Replacement Gate

If VWAP is removed as a gate, MACD, EMA, and RSI rhythm must carry direction quality.

Minimum proposed long gate:

```text
Long entry allowed only if:
  4H MACD direction is long or stable bullish continuation
  1H signal is red_bar_growing or flip_bullish recovery path
  1H confirmation is not strongly opposite
  EMA structure is normal/strong, or 1H EMA slope is not adverse
  RSI rhythm score is supportive or neutral-upgrade path is explicitly satisfied
  RSI is not in late overheat / conflict state
  15m entry is supportive or soft confirmation path is explicitly enabled
  volume score is not low unless position size is reduced
```

Minimum proposed short gate:

```text
Short entry allowed only if:
  4H MACD direction is short or stable bearish continuation
  1H signal is green_bar_growing or flip_bearish
  1H confirmation is not strongly opposite
  flip_bearish requires ADX >= 30
  EMA structure is normal/strong for short, or EMA slope is not adverse
  RSI rhythm score is supportive for short and not in rebound conflict
  15m bearish confirmation or 4H enhancement exists
  independent short quality filter passes for flip_bearish
```

Current related parameters:

```json
{
  "primary_direction_timeframe": "4h",
  "require_1h_confirmation_when_4h_primary": true,
  "allow_neutral_1h_confirmation": true,
  "light_1h_confirmation_when_4h_primary": true,
  "flip_bearish_min_adx_1h": 30.0,
  "flip_bearish_require_enhancement_or_15m_confirmation": true
}
```

Claude review ask:

```text
Is MACD + EMA + RSI direction quality already strong enough after VWAP removal?
If not, which MACD/EMA/RSI condition should become stricter before considering any other indicator?
```

## 8. Non-VWAP Direction Quality Focus

Do not introduce BOLL as a replacement entry indicator in this review. BOLL has not paired well in other projects and should not be promoted to a new hard gate here.

The replacement direction-quality stack should use only:

```text
MACD:
  4H primary direction
  4H enhancement / stable continuation
  1H signal type and trend health
  15m entry timing confirmation

EMA:
  EMA structure status: strong / normal / weak / against
  EMA multiplier and adverse EMA structure vetoes already in the strategy
  EMA slope or equivalent trend-health fields if already available

RSI:
  RSI rhythm weighted score
  RSI hard veto
  RSI conflict penalty
  RSI probe / exposure scaling
  RSI spring and neutral-upgrade paths
```

Candidate stricter replacement gates:

```text
Long:
  require 4H long/stable-bull context
  require 1H red_bar_growing or approved recovery signal
  require EMA status not against
  require RSI rhythm score >= neutral/support threshold
  reject late-overheat RSI unless 15m spring/reset confirms

Short:
  require 4H short/stable-bear context
  require 1H green_bar_growing or flip_bearish
  require EMA status not against
  require RSI rhythm score supportive for short
  reject flip_bearish if RSI indicates rebound/spring conflict
  keep funding/OI checks for flip_bearish independent short quality
```

## 9. Live Entry Chain

Practical live chain:

```text
fund_flow_bot.run()
  -> run_cycle(...)
  -> _prepare_cycle_context()
  -> _process_symbol_core(symbol)
  -> _handle_symbol_protection_and_sla(...)
  -> _execute_symbol_signal_decision(...)
  -> FundFlowDecisionEngine.decide(...)
  -> MACDStrategyV2Engine.analyze(...)
  -> FundFlowDecisionEngine builds BUY/SELL/CLOSE/HOLD decision
  -> pending_new_entries queue
  -> _finalize_entries(...)
  -> capacity / AI final review / protection-gap gates
  -> _execute_and_log_decision(...)
  -> exchange entry order
  -> post-entry protection hook / protection SLA repair
```

Important:

```text
A MACD V2 signal can pass strategy analysis but still fail later finalization.
Likewise, a weak strategy signal can execute if it passes min-open, capacity, and final review.
```

## 10. Live Score Weights

Current scoring weights:

| Component | Weight |
|---|---:|
| `weight_1h_direction` | `0.15` |
| `weight_4h_direction` | `0.40` |
| `weight_4h_enhancement` | `0.10` |
| `weight_rsi_rhythm` | `0.30` |
| `weight_vwap` | `0.05` |
| `weight_15m_entry` | `0.05` |
| `weight_volume` | `0.10` |

Current score construction:

```text
score_1h: up to 0.15
score_4h: up to 0.40
score_4h_enhancement: folded into 4H score as capped bonus
score_rsi_rhythm: weighted RSI rhythm score up to 0.30
score_vwap: VWAP scorer output, currently up to 0.05
score_15m: min(weight_15m_entry, entry_score_15m * weight_15m_entry)
score_volume:
  volume_ratio > 1.5 -> 0.10
  volume_ratio > 1.0 -> 0.067
  else -> 0.033
```

Entry thresholds:

| Signal / mode | Threshold |
|---|---:|
| `default` | `0.680` |
| `min_signal_score` | `0.680` |
| `soft_long_min_signal_score` | `0.660` |
| `stable_bear_continuation_min_signal_score` | `0.680` |
| `stable_bull_continuation_min_signal_score` | `0.680` |
| `red_bar_growing` | `0.680` |
| `green_bar_growing` | `0.690` |
| `flip_bearish` | `0.660` |
| `flip_bullish` | `0.640` |

Claude review ask:

```text
If weight_vwap becomes 0, should its 0.05 be redistributed to MACD 4H, RSI rhythm, EMA quality, or volume?
Recommendation to test:
  A. weight_vwap=0, do not redistribute
  B. move 0.05 to weight_4h_direction
  C. move 0.05 to weight_rsi_rhythm
  D. move 0.05 to weight_volume
```

## 11. Live Position Management

Top-level:

```json
{
  "default_target_portion": 0.35,
  "max_symbol_position_portion": 0.35,
  "max_active_symbols": 3,
  "min_open_portion": 0.06,
  "min_leverage": 3,
  "default_leverage": 4,
  "max_leverage": 5
}
```

TREND engine params:

```json
{
  "default_target_portion": 0.6,
  "max_symbol_position_portion": 0.6,
  "default_leverage": 4,
  "min_leverage": 3,
  "max_leverage": 5,
  "long_open_threshold": 0.095,
  "short_open_threshold": 0.08
}
```

MACD V2 position sizing:

```text
score >= 0.90 -> 1.2x base target
score >= 0.80 -> 1.0x base target
score >= 0.65 -> 0.8x base target
score >= 0.55 -> 0.6x base target
else -> 0
```

Additional modifiers:

```text
priority signal can multiply target by 1.10
dual pressure may add target portion bonus
vwap_score_position_tiers may reduce portion
trial entry applies entry_scale
RSI exposure/conflict/probe can reduce portion
red/green probe overlays can reduce portion
symbol/session risk scale applies last
vol_vwap_warn_position_scale currently 0.0 can zero portion
```

Weak-entry leverage handling:

```text
FundFlowDecisionEngine avoids lifting weak/probe/vol_vwap_warn/low-score entries to min_leverage.
Weak path returns max(1, strategy_leverage) instead of forcing min_leverage=3.
```

Review ask:

```text
If VWAP is removed, should the vol_vwap_warn zero-size path also be removed or replaced with volume-only warning?
```

## 12. Live Risk Controls

### 12.1 TP / SL

Top-level:

```json
{
  "take_profit_pct": 0.02,
  "stop_loss_pct": 0.005
}
```

TREND:

```json
{
  "take_profit_pct": 0.02,
  "stop_loss_pct": 0.005,
  "dynamic_stop_loss_enabled": true,
  "short_stop_loss_min_pct": 0.005,
  "short_stop_loss_max_pct": 0.005,
  "short_stop_loss_atr_mult": 1.1
}
```

MACD V2 dynamic stop:

```text
long:
  if close >= bb_middle: stop = bb_middle - atr * boll_stop_atr_multiplier
  elif bb_lower exists: stop = bb_lower - atr * 0.2
  else: stop = entry * (1 - max_stop_loss_pct)
  stop clamped no looser than entry * (1 - max_stop_loss_pct)

short:
  if close <= bb_middle: stop = bb_middle + atr * boll_stop_atr_multiplier
  elif bb_upper exists: stop = bb_upper + atr * 0.2
  else: stop = entry * (1 + max_stop_loss_pct)
  stop clamped no looser than entry * (1 + max_stop_loss_pct)
```

Current stop config:

```json
{
  "boll_stop_atr_multiplier": 0.5,
  "max_stop_loss_pct": 0.025,
  "vwap_alert_deviation": 0.005
}
```

If VWAP is removed:

```text
vwap_alert_deviation should be removed from core risk assumptions or kept only as non-blocking telemetry.
```

Note:

```text
The current dynamic stop implementation still references BOLL bands as stop anchors.
This review does not propose using BOLL as an entry indicator or replacement entry gate.
If BOLL stop anchors are also undesired later, that should be a separate risk-management review.
```

### 12.2 Break-Even / Trailing

Current TREND values:

| Parameter | Value |
|---|---:|
| `tp_break_even_trigger_pnl_ratio` | `0.0055` |
| `tp_break_even_lock_ratio` | `0.002` |
| `tp_trailing_activate_mfe_ratio` | `0.0075` |
| `tp_trailing_distance_ratio` | `0.003` |
| `ev_lw_flip_exit_mfe_ratio` | `0.0015` |

### 12.3 Protection SLA

Current:

```json
{
  "protection_sla_enabled": true,
  "protection_sla_seconds": 45,
  "protection_sla_force_flatten": true,
  "protection_immediate_close_on_repair_fail": true,
  "rollback_on_tp_sl_fail": true
}
```

Runtime behavior:

```text
_handle_symbol_protection_and_sla(...)
  if existing position lacks TP/SL coverage:
    _repair_missing_protection(...)
    if repaired: clear missing state
    else: block new entries and alert
    after SLA timeout: force flatten if configured
```

Stop summary mapping has been improved:

```text
The bot can resolve stop from exchange open orders before falling back to local metadata.
If exchange stop is missing despite a protection plan, emergency repair is triggered.
```

### 12.4 Pretrade Risk Gate

Current:

```json
"pretrade_risk_gate": {
  "enabled": false,
  "entry_threshold": 0.06,
  "entry_threshold_capture": 0.05,
  "max_drawdown": 0.02,
  "max_exposure_per_trade": 0.22,
  "volatility_cap": 0.012,
  "volatility_cap_capture": 0.014
}
```

Review ask:

```text
If VWAP gates are removed, should pretrade_risk_gate remain disabled?
Do not enable it without ablation because it may block good MACD/EMA trades.
```

### 12.5 Short Quality Filter

Current:

```json
{
  "enabled": false,
  "flip_bearish_independent_enabled": true,
  "min_funding_rate": 0.0005,
  "max_oi_delta_ratio": 0.0,
  "min_vwap_deviation": 0.005,
  "flip_bearish_min_vwap_score": 0.25
}
```

Important if VWAP is removed:

```text
flip_bearish independent filter still contains VWAP-related checks.
If VWAP is removed fully, this must be replaced by non-VWAP short-quality checks:
  funding_rate > 0.0005
  oi_delta_ratio < 0
  MACD 1H bearish signal remains active
  4H MACD is short or stable-bear compatible
  EMA structure is not adverse for short
  RSI rhythm is not in rebound conflict
  ADX >= 30
```

## 13. Proposed Review Questions For Claude

1. Is VWAP fundamentally incompatible with this MACD trend-continuation strategy, or only over-tight as a hard gate?
2. Should VWAP be removed only as an entry gate while remaining a telemetry field?
3. If `weight_vwap=0`, where should the freed `0.05` weight go: nowhere, 4H direction, RSI rhythm, EMA quality, or volume?
4. Is MACD+EMA+RSI resonance sufficient to maintain win rate and profit factor after VWAP gate removal?
5. If MACD+EMA+RSI is insufficient, which of the three should be strengthened first?
6. How should `flip_bearish` be protected without VWAP score: ADX, MACD 4H/1H alignment, EMA status, RSI conflict, OI/funding, 15m confirmation, or all of them?
7. Should `vol_vwap_warn_position_scale=0.0` be removed or converted into a volume-only warning?
8. Should RANGE / NO_TRADE long gates still reference VWAP, or switch to MACD/EMA/RSI/ADX/signal score only?
9. What minimum ablation set is required before deploying VWAP removal live?
10. What metrics should be mandatory: win rate, profit factor, MDD, trade count, avg loss, worst symbol, and recent 34h replay?

## 13A. Claude Review Answers To Lock

### Q3 Weight Reallocation

Recommendation:

```text
weight_vwap 0.05 -> weight_rsi_rhythm
weight_rsi_rhythm 0.30 -> 0.35
weight_vwap 0.05 -> 0.00
```

Reason:

```text
RSI rhythm is the most independent direction validator in the current MACD+EMA+RSI stack.
Adding the freed 0.05 to 4H MACD would over-concentrate on the already dominant 4H score.
Adding it to volume would strengthen a context signal, not a direction signal.
Leaving it unallocated implicitly raises all score thresholds by reducing max score.
```

### Q6 Flip Bearish Non-VWAP Protection

The replacement protection stack is:

| Layer | Condition | Status |
|---|---|---|
| 1 | `ADX >= 30` | existing, enforced minimum |
| 2 | 4H direction is short-compatible | candidate C hard gate |
| 3 | 15m bearish confirmation or 4H enhancement | existing guard, made explicit |
| 4 | EMA status is not `against` | candidate C hard gate |
| 5 | RSI rhythm raw score `>= 0.40` | candidate C hard gate |
| 6 | RSI conflict is not rebound/spring/divergence | candidate C hard gate |
| 7 | `funding_rate > 0.0005` and `oi_delta_ratio < 0` | independent short quality check |

### Q9 Ablation Order

```text
Do not skip candidate_a or candidate_b.

candidate_a answers:
  Did removing VWAP admission gates restore trade count?

candidate_b answers:
  Does pure MACD+EMA+RSI scoring remain profitable when VWAP contributes no score?

candidate_c answers:
  Do explicit MACD+EMA+RSI hard gates protect the recent weak cluster without starving trades?
```

Decision:

```text
If candidate_b reaches win_rate/PF targets, candidate_c is optional protection.
If candidate_b fails but candidate_c passes, deploy candidate_c only after shadow.
If candidate_c fails, do not deploy VWAP removal.
```

## 14. Minimum Deployment Standard

Do not deploy VWAP removal unless all are true:

```text
30d strict-live backtest:
  total_trades > 50
  win_rate >= 75%
  profit_factor >= 1.30
  max_drawdown <= 15%

60d validation:
  no catastrophic MDD expansion
  no single-symbol loss cluster dominates

Recent 34h loss replay:
  weak low-VWAP flip_bearish shorts are still blocked by non-VWAP filters
  weak low-volume red_bar_growing longs are either blocked or size-reduced

Live shadow:
  run VWAP-removed candidate in shadow for 48h before real execution
```

## 15. Recommended Next Action

Create three temporary configs and run ablation:

```text
candidate_a_no_vwap_gate:
  all VWAP entry floors = 0
  vwap_deviation_hard_block = 999
  weight_vwap remains 0.05

candidate_b_no_vwap_score:
  candidate_a
  weight_vwap = 0

candidate_c_macd_ema_rsi_gate:
  candidate_b
  add stricter MACD+EMA+RSI replacement gates for long/short direction quality
```

Decision rule:

```text
If candidate_b restores trades but win rate/PF collapses, VWAP was hiding weak direction quality.
If candidate_c restores trades and keeps PF/win rate acceptable, replace VWAP gate with MACD+EMA+RSI resonance gates.
If all candidates fail, keep VWAP as telemetry only and redesign entry quality from MACD/EMA/RSI/volume first.
```

## 16. Implemented Candidate Interfaces

Candidate config files have been added for controlled ablation only:

```text
config/candidate_a_no_vwap_gate.json
config/candidate_b_no_vwap_score.json
config/candidate_c_resonance_gate.json
```

Candidate C introduces this config block:

```json
{
  "resonance_gate": {
    "enabled": true,
    "long_rsi_rhythm_min": 0.35,
    "short_rsi_rhythm_min": 0.35,
    "flip_bearish_rsi_rhythm_min": 0.40,
    "flip_bullish_rsi_rhythm_min": 0.30,
    "trial_rsi_rhythm_min": 0.30,
    "require_ema_not_against": true,
    "require_4h_align": true,
    "volume_warn_ratio": 0.80,
    "volume_warn_position_scale": 0.50,
    "structural_vwap_telemetry_position_scale_threshold": 0.05,
    "structural_vwap_telemetry_position_scale": 0.70
  }
}
```

Runtime attribution fields:

```text
resonance_gate_block_by_reason
resonance_gate_block_by_signal
resonance_gate_block_by_side
```

VWAP remains available as telemetry:

```text
vwap_score
session_vwap_deviation
structural_vwap_deviation
resonance_vwap_telemetry_warn
```
