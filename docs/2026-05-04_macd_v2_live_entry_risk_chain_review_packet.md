# MACD V2 Live Entry / Scoring / Position / Risk Chain Review Packet

- Date: `2026-05-04`
- Purpose: Provide Claude with a detailed review packet for the live MACD V2 opening chain, thresholds, scoring weights, position management, and risk controls.
- Primary config: `config/trading_config_fund_flow.json`
- Primary code:
  - `src/app/fund_flow_bot.py`
  - `src/fund_flow/decision_engine.py`
  - `src/fund_flow/macd_strategy_v2.py`
- Companion loss review: `docs/2026-05-04_recent_34h_live_loss_review_packet.md`

## 1. High-Level Live Chain

Live execution is not just `MACDStrategyV2Engine.analyze()`. The practical chain is:

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

Important design point:

```text
There are multiple gates after MACD V2 produces a signal.
A passing strategy signal does not guarantee execution.
A weak signal can still execute if it passes min-open, capacity, and finalization gates.
```

## 2. Current Key Live Parameters

### 2.1 Top-Level Fund Flow

| Parameter | Value | Read |
|---|---:|---|
| `strategy_mode` | `macd_mtf_strategy_v2` | active strategy |
| `entry_side_mode` | `BOTH` | both long and short allowed unless symbol/regime gates block |
| `max_active_symbols` | `3` | active symbol cap |
| `default_target_portion` | `0.35` | base top-level portion, overridden by engine params in regimes |
| `max_symbol_position_portion` | `0.35` top-level / `0.60` TREND engine | cap depends path/context |
| `default_leverage` | `4` top-level / `4` TREND engine | strategy leverage then clamped |
| `min_leverage` | `3` | final clamp in decision engine can lift low strategy leverage |
| `max_leverage` | `5` | final cap |
| `take_profit_pct` | `0.02` | base TP |
| `stop_loss_pct` | `0.005` | fallback/default stop |
| `long_open_threshold` | `0.09` top-level / `0.095` TREND | fund-flow score threshold path |
| `short_open_threshold` | `0.07` top-level / `0.08` TREND | fund-flow score threshold path |
| `min_open_portion` | `0.06` | final execution gate below which entries are skipped |
| `entry_slippage` | `0.0015` | IOC/GTC limit band |
| `trigger_dedupe_seconds` | `180` | duplicate trigger guard |

### 2.2 Symbol Blacklist

Current `fund_flow.symbol_blacklist` includes:

```text
QNTUSDT, UNIUSDT, NEARUSDT, HBARUSDT, XMRUSDT, TRXUSDT, ENAUSDT, TAOUSDT,
LINKUSDT, ARBUSDT, LTCUSDT, HYPEUSDT, KASUSDT, DOTUSDT, FILUSDT, XRPUSDT,
APTUSDT, ADAUSDT, FETUSDT, XLMUSDT
```

Code behavior:

- `FundFlowDecisionEngine._parse_symbol_side_overrides()` converts `symbol_blacklist` into symbol side override mode `NO_TRADE`.
- This should block both long and short entries for blacklisted symbols.
- Claude should verify all live entry paths apply `_apply_symbol_side_override()` or equivalent after decision generation.

## 3. MACD V2 Entry Thresholds

### 3.1 Scoring Weights

Current `macd_mtf_strategy_v2.scoring_weights`:

| Component | Weight |
|---|---:|
| `weight_1h_direction` | `0.15` |
| `weight_4h_direction` | `0.40` |
| `weight_4h_enhancement` | `0.10` |
| `weight_rsi_rhythm` | `0.30` |
| `weight_vwap` | `0.05` |
| `weight_15m_entry` | `0.05` |
| `weight_volume` | `0.10` |

Code notes from `MACDStrategyV2Engine.analyze()`:

- 1H direction contributes up to `0.15`.
- 4H direction contributes up to `0.40`; 4H enhancement is folded into 4H score as a capped bonus.
- RSI rhythm contributes weighted score from RSI rhythm module, up to configured weight.
- VWAP score is added as `score_vwap = vwap_score`; the underlying VWAP scorer already scales by `weight_vwap`.
- 15m entry contributes `min(weight_15m_entry, entry_score_15m * weight_15m_entry)`.
- Volume contributes:
  - `0.10` if `volume_ratio > 1.5`
  - `0.067` if `volume_ratio > 1.0`
  - `0.033` otherwise

Review concern:

```text
Recent losing entries all had score_volume=0.033 and VWAP around 0.0029~0.0457.
This means they were accepted despite weak volume and weak VWAP before the latest config change.
```

### 3.2 Signal Score Thresholds

Current `macd_mtf_strategy_v2.entry_thresholds`:

| Signal / mode | Threshold |
|---|---:|
| `default` | `0.68` |
| `min_signal_score` | `0.68` |
| `soft_long_min_signal_score` | `0.66` |
| `stable_bear_continuation_min_signal_score` | `0.68` |
| `stable_bull_continuation_min_signal_score` | `0.68` |
| `red_bar_growing` | `0.68` |
| `green_bar_growing` | `0.69` |
| `flip_bearish` | `0.66` |
| `flip_bullish` | `0.64` |
| `preflip_trial_min_signal_score` | `0.66` |
| `trial_short_below_structure_promotion_min_signal_score` | `0.68` |

Code path:

```text
MACDStrategyV2Config.resolve_entry_threshold(...)
  -> stable continuation override if active
  -> primary_4h signal threshold if primary_mode=4h
  -> preflip trial override if transition entry
  -> soft long override if soft 15m path applies
  -> RSI spring / neutral / sovereign overrides can lower threshold in specific cases
```

### 3.3 VWAP Entry Floors

Current effective entry filters after latest live update:

| Parameter | Value | Intended effect |
|---|---:|---|
| `min_vwap_score_for_entry` | `0.12` | generic long / fallback floor |
| `short_min_vwap_score_for_entry` | `0.12` | non-`flip_bearish` short floor |
| `flip_bearish_short_min_vwap_score_for_entry` | `0.25` | strict floor for `flip_bearish` shorts |
| `vol_vwap_warn_min_score_vol` | `0.05` | low volume warning threshold |
| `vol_vwap_warn_min_vwap_score` | `0.12` | low VWAP warning threshold |
| `vol_vwap_warn_position_scale` | `0.0` | low-volume + low-VWAP entries size to zero |

Code path:

```text
MACDStrategyV2Engine._resolve_min_vwap_score_for_entry(...)
  if trial entry: preflip_trial_min_vwap_score
  if long and flip_bullish exemption enabled: 0.0
  if long: min_vwap_score_for_entry
  if short and signal_type_1h == flip_bearish: flip_bearish_short_min_vwap_score_for_entry
  if short: short_min_vwap_score_for_entry
  if unknown direction and flip exemption applies: 0.0
  else: min_vwap_score_for_entry
```

Then:

```text
if min_vwap_score_for_entry > 0 and vwap_score < min_vwap_score_for_entry:
    return neutral signal with VetoType.VWAP_SCORE_FILTER
```

Review questions:

1. Does this VWAP gate execute before all alternate entry paths that can produce live BUY/SELL?
2. Do regime entries, neutral upgrades, preflip trials, and `rsi_neutral_resume` all honor the intended `0.12` floor?
3. Should `preflip_trial_min_vwap_score=0.0`, `trial_short_below_structure_promotion_min_vwap_score=0.0`, `stable_bear_continuation_min_vwap_score=0.0`, or `flip_bullish_min_vwap_score=0.0` remain open exceptions?

## 4. Direction And Signal Routing

### 4.1 Primary Direction Mode

Current entry filter:

```text
primary_direction_timeframe = 4h
require_1h_confirmation_when_4h_primary = true
allow_neutral_1h_confirmation = true
light_1h_confirmation_when_4h_primary = true
```

This means 4H is the primary trend source, but 1H confirmation can be light or neutral depending on path.

### 4.2 Recent Loss-Relevant Signal Types

The 34H closed loss cluster was dominated by:

```text
Long: 1h red_bar_growing
Short: 1h flip_bearish
```

The loss review found:

- `4/4` short trades were `flip_bearish` and all lost.
- `flip_bearish` entries had VWAP `0.0029~0.0321`, far below the new `0.25` floor.
- Multiple long `red_bar_growing` entries had VWAP `0.02~0.05` and volume score `0.033`.

### 4.3 Signal Pool Layer

Current signal definitions include fund-flow metrics:

| Signal | Side | Metric | Operator | Threshold | Timeframe |
|---|---|---|---|---:|---|
| `trend_long_cvd` | LONG | `cvd_momentum` | `>=` | `0.0005` | `5m` |
| `trend_long_imb` | LONG | `imbalance` | `>=` | `0.06` | `5m` |
| `trend_short_cvd` | SHORT | `cvd_momentum` | `<=` | `-0.0005` | `5m` |
| `trend_short_imb` | SHORT | `imbalance` | `<=` | `-0.06` | `5m` |
| `trend_major_long_cvd` | LONG | `cvd_momentum` | `>=` | `0.0003` | `5m` |
| `trend_major_long_imb` | LONG | `imbalance` | `>=` | `0.045` | `5m` |
| `trend_major_short_cvd` | SHORT | `cvd_momentum` | `<=` | `-0.0003` | `5m` |
| `trend_major_short_imb` | SHORT | `imbalance` | `<=` | `-0.045` | `5m` |
| `range_long_extreme` | LONG | `imbalance` | `<=` | `-0.14` | `5m` |
| `range_short_extreme` | SHORT | `imbalance` | `>=` | `0.14` | `5m` |

Current pools:

| Pool | Logic | Long min | Short min | Edge trigger | Signals |
|---|---|---:|---:|---|---|
| `trend_pool` | AND/min pass `1` | `0.04` | `0.05` | false | regular trend long/short CVD/imb |
| `trend_pool_major` | AND/min pass `1` | `0.10` | `0.10` | true | major trend CVD/imb |
| `trend_pool_short_only` | AND/min pass `1` | `999.0` | `0.06` | true | short CVD/imb |
| `range_pool` | AND/min pass `0` | `0.30` | `0.30` | true | range extreme |

Review concern:

```text
The recent bad entries were not obviously blocked by low fund-flow volume/VWAP quality before the latest VWAP update.
Claude should inspect how signal-pool scores interact with MACD V2 scores and whether RANGE/NO_TRADE regime labels should be allowed to produce new longs.
```

## 5. Position Sizing And Leverage

### 5.1 Strategy Position Portion

Code path:

```text
MACDStrategyV2Engine.calculate_position_portion(...)
  portion_mult by score:
    score >= 0.90 -> 1.2
    score >= 0.80 -> 1.0
    score >= 0.65 -> 0.8
    score >= 0.55 -> 0.6
    else -> 0.0
  target_portion = base_default_portion
  priority signal may multiply target by 1.10
  dual pressure may add bonus
  vwap_score_position_tiers may reduce portion
  trial entry applies entry_scale
  RSI exposure/conflict/probe can reduce portion
  red/green probe overlays can reduce portion
  symbol/session risk scale applies last
```

Recent observed portions before latest change:

| Pattern | Typical portion |
|---|---:|
| Weak low-volume low-VWAP long | `0.168` or `0.210` |
| Weak low-volume low-VWAP flip_bearish short | `0.062475` |
| Low-volume low-VWAP warning scale | `0.50` before latest change |
| Current low-volume low-VWAP warning scale | `0.0` |

### 5.2 Volume + VWAP Warning Scale

Code path:

```text
FundFlowDecisionEngine._apply_macd_v2_vol_vwap_warn_position_scale(...)
  if signal.details.vol_vwap_warn is false: return portion
  original_portion = portion
  scale = vol_vwap_warn_position_scale
  adjusted_portion = original_portion * scale
```

With current config:

```text
vol_vwap_warn_position_scale = 0.0
```

Expected result:

```text
Any signal with vol_vwap_warn=true should get target portion 0.0 and then fail min_open_portion=0.06 before execution.
```

Review question:

```text
Confirm that all BUY/SELL construction paths call _apply_macd_v2_vol_vwap_warn_position_scale before min_open_portion and finalization.
```

### 5.3 Leverage

Code path:

```text
MACDStrategyV2Engine.calculate_leverage(...)
  score >= 0.90 -> base 4x
  score >= 0.85 -> base 3x
  score >= 0.75 -> base 2x
  else -> 0x
  strong BOLL/EMA can reduce leverage
  red/green probe overlays cap leverage
  RSI probe can cap leverage
  RSI conflict can reduce leverage by 1 step
  flip_bearish normal EMA max leverage can cap
  trial entries can cap
  watchlist can cap
```

Then `FundFlowDecisionEngine` clamps leverage:

```text
leverage = min(leverage, regime_state.max_leverage)
leverage = max(min_leverage, min(max_leverage, leverage))
```

Review concern:

```text
If strategy leverage returns 1 or 2 but global min_leverage=3, the final clamp can lift leverage to 3.
Recent low-quality entries often executed at leverage=3.
Claude should verify whether min_leverage=3 is intended for weak/probe entries.
```

## 6. TP / SL / Protection Logic

### 6.1 Decision-Time TP/SL

For long decisions:

```text
stop_loss_price = suggested_stop_price if valid else price * (1 - stop_loss_pct)
take_profit_price = price * (1 + take_profit_pct)
```

For short decisions:

```text
stop_loss_price = suggested_stop_price if valid else price * (1 + stop_loss_pct)
take_profit_price = price * (1 - take_profit_pct)
```

Current TREND engine:

```text
take_profit_pct = 0.02
stop_loss_pct = 0.005
dynamic_stop_loss_enabled = true
short_stop_loss_min_pct = 0.005
short_stop_loss_max_pct = 0.005
short_stop_loss_atr_mult = 1.1
```

### 6.2 MACD V2 Dynamic Stop

Code path:

```text
MACDStrategyV2Engine.calculate_dynamic_stop(...)
  long:
    if close >= bb_middle: stop = bb_middle - atr * ema_stop_atr_multiplier
    elif bb_lower exists: stop = bb_lower - atr * 0.2
    else: stop = entry * (1 - max_stop_loss_pct)
    stop is clamped no looser than entry * (1 - max_stop_loss_pct)
  short:
    if close <= bb_middle: stop = bb_middle + atr * ema_stop_atr_multiplier
    elif bb_upper exists: stop = bb_upper + atr * 0.2
    else: stop = entry * (1 + max_stop_loss_pct)
    stop is clamped no looser than entry * (1 + max_stop_loss_pct)
```

Current config:

```text
max_stop_loss_pct = 0.025
boll_stop_atr_multiplier = 0.5
vwap_alert_deviation = 0.005
```

Review concern:

```text
Recent runtime logs frequently printed stop=0.0000, stop_pct=2.00% even while protection repairs succeeded.
Claude should verify whether this is a display/state mapping issue or a real missing strategy stop.
```

### 6.3 Protection SLA

Current top-level protection settings:

```text
protection_sla_enabled = true
protection_sla_seconds = 45
protection_sla_force_flatten = true
protection_immediate_close_on_repair_fail = true
rollback_on_tp_sl_fail = true
```

Code path in `fund_flow_bot.py`:

```text
_handle_symbol_protection_and_sla(...)
  if existing position lacks TP/SL coverage:
    _repair_missing_protection(...)
    if repaired: clear missing state
    else: block new entries, emit alerts, and after SLA timeout force flatten if configured
```

Runtime evidence in the recent window:

```text
SUIUSDT protection order repair completed
SOLUSDT protection order repair completed
AVAXUSDT protection order repair completed
AAVEUSDT / JUPUSDT / ZROUSDT protection order repair completed
```

Review concern:

```text
Protection repair appears active, but stop summary output is ambiguous.
Claude should inspect _protection_coverage(), _repair_missing_protection(), and the risk summary printer.
```

### 6.4 Break-Even / Trailing

Current TREND engine after latest change:

| Parameter | Value |
|---|---:|
| `tp_break_even_trigger_pnl_ratio` | `0.0055` |
| `tp_break_even_lock_ratio` | `0.002` |
| `tp_trailing_activate_mfe_ratio` | `0.0075` |
| `tp_trailing_distance_ratio` | `0.003` |
| `ev_lw_flip_exit_mfe_ratio` | `0.0015` |

Why changed:

- Recent `AAVEUSDT`, `AVAXUSDT`, `SOLUSDT` long trades had MFE around `+0.60%~+0.76%`.
- Previous BE trigger `0.8%` and trailing trigger `2.0%` did not protect those excursions.
- Current thresholds aim to arm BE around `+0.55%` and trailing around `+0.75%`.

Review concern:

```text
This may reduce giveback, but it can also over-tighten future trend winners.
Needs a post-change live read; do not combine with Light TP/capacity changes yet.
```

## 7. Finalization / Capacity / Execution

### 7.1 Min Open Gate

Before adding to pending entries, bot checks:

```text
if decision.target_portion_of_balance < min_open_portion:
    block entry with gate=min_open_portion
```

Current `min_open_portion=0.06`.

Expected with current low-quality-entry block:

```text
vol_vwap_warn=true -> portion scaled to 0.0 -> below min_open_portion -> blocked.
```

### 7.2 Capacity Gate

Finalization estimates active symbols:

```text
active_symbols_estimate = current active position symbols + opened symbols this cycle
if active_count >= item_max_active_symbols and not bypass_capacity_guard:
    block with active_symbol_capacity
```

Current `max_active_symbols=3`.

Previous ablations showed expanding capacity did not improve 30d return, so capacity is not the current priority.

### 7.3 Execution Policy

Priority execution applies when signal score is high enough:

```text
priority_exec_min_score = 0.90
priority_exec_vip_min_score = 0.92
priority_exec_expire_seconds = 25
priority_exec_vip_expire_seconds = 45
priority_exec_vip_allow_retry = true
```

Otherwise entries use IOC limit policy.

Recent weak entries were generally not priority entries. Their reason strings and target portions indicate they were low-quality entries that still passed the old gates.

## 8. Pretrade Risk Gate

Current config:

```text
fund_flow.pretrade_risk_gate.enabled = false
```

Configured but inactive thresholds include:

| Parameter | Value |
|---|---:|
| `entry_threshold` | `0.06` |
| `entry_threshold_capture` | `0.05` |
| `max_drawdown` | `0.02` |
| `max_exposure_per_trade` | `0.22` |
| `volatility_cap` | `0.012` |
| `volatility_cap_capture` | `0.014` |
| `trend_weight` | `0.45` |
| `momentum_weight` | `0.30` |
| `volatility_weight` | `0.20` |
| `drawdown_weight` | `0.35` |

Review question:

```text
Should pretrade_risk_gate remain disabled now that MACD V2 is carrying most entry-quality risk control?
If enabled, it must be ablated carefully because it may block good trades as well as bad ones.
```

## 9. Short Quality Filter

Current config:

```text
short_quality_filter.enabled = false
min_funding_rate = 0.0005
max_oi_delta_ratio = 0.0
min_vwap_deviation = 0.005
```

Code behavior if enabled for `flip_bearish`:

```text
Require funding_rate > 0.0005
Require oi_delta_ratio < 0
Require price > vwap * 1.005
Otherwise neutralize short with SHORT_QUALITY_FILTER veto
```

Recent evidence:

```text
4/4 recent shorts lost.
All were flip_bearish.
All had VWAP below 0.04.
```

Recommendation for Claude review:

```text
Consider a controlled SS/short-quality experiment that enables this filter only after confirming it would have blocked the recent weak shorts and would not remove historically profitable shorts.
```

## 10. Known Open Risks / Review Hotspots

| Area | Why it matters | Claude review ask |
|---|---|---|
| VWAP floor bypasses | Recent losses all had very low VWAP | Confirm no alternate BUY/SELL path bypasses `_resolve_min_vwap_score_for_entry` |
| `vol_vwap_warn_position_scale=0.0` | Should block weak low-volume + low-VWAP entries | Confirm all paths apply scaling before min-open/finalization |
| `min_leverage=3` | Weak entries executed at 3x | Confirm weak/probe entries are not unintentionally lifted to 3x |
| `RANGE` / `NO_TRADE` labels | Recent losing longs included `RANGE` and `NO_TRADE` regimes | Confirm regime labels should allow new entries under current path |
| Protection summary `stop=0.0000` | Ambiguous risk state | Inspect protection coverage, repair, and logging state mapping |
| `short_quality_filter=false` | Recent flip_bearish shorts failed | Evaluate controlled enablement or stricter short gating |
| Compacted metadata | Limits live forensics | Consider logging full score breakdown for executed orders only |

## 11. Suggested Instrumentation Improvement

The current persistent metadata is too compact for forensic review. For executed orders only, add a compact but complete score breakdown, for example:

```json
{
  "score_1h": 0.1275,
  "score_4h": 0.3500,
  "score_rsi_rhythm_weighted": 0.1800,
  "score_vwap": 0.0374,
  "score_15m": 0.0000,
  "score_volume": 0.0330,
  "total_score": 0.7279,
  "signal_score_threshold": 0.6800,
  "min_vwap_score_for_entry": 0.1200,
  "vol_vwap_warn": true,
  "position_before_warn_scale": 0.3360,
  "position_after_warn_scale": 0.0000,
  "final_leverage": 0,
  "block_or_execute_reason": "min_open_portion"
}
```

This should be logged only for executed or blocked-at-finalization candidates to avoid log bloat.

## 12. Review Questions For Claude

1. Are all live BUY/SELL paths covered by the current blacklist, VWAP floor, and `vol_vwap_warn_position_scale` logic?
2. Is there any path where `signal.details.vol_vwap_warn=true` is not present or not propagated into `FundFlowDecisionEngine._apply_macd_v2_vol_vwap_warn_position_scale()`?
3. Does `min_vwap_score_for_entry=0.12` now block the `SOLUSDT` style entry with `vwap_score=0.0092` and `vol_vwap_warn=false`?
4. Should `preflip_trial_min_vwap_score`, `trial_short_below_structure_promotion_min_vwap_score`, or stable continuation VWAP floors remain `0.0`?
5. Should `min_leverage=3` be reduced or bypassed for probe/low-quality entries, so strategy leverage caps are respected?
6. Why did recent `RANGE` / `NO_TRADE` regime entries still open? Is that expected because MACD V2 signal overrides regime, or a gate bug?
7. Does protection SLA actually guarantee both TP and SL are live at the exchange after entry, or can local state say repaired while the risk summary prints `stop=0.0000`?
8. Should `short_quality_filter` be enabled for `flip_bearish` shorts, or is the new `flip_bearish_short_min_vwap_score_for_entry=0.25` sufficient?
9. Are the new BE/trailing values (`0.55%`, `0.75%`, `0.30%`) too tight for trend winners, or appropriate given recent MFE distribution?
10. What minimal instrumentation should be added so the next live review can reconstruct score breakdown without relying on `_omitted_keys`?
