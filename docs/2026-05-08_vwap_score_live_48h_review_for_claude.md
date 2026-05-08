# VWAP Score 48H Live Review For Claude

Date: `2026-05-08`

Window requested:

- Beijing time: `2026-05-06 00:00:00` to `2026-05-07 23:59:59`
- UTC: `2026-05-05 16:00:00` to `2026-05-07 15:59:59`

Data sources:

- `logs/2026-05/2026-05-05/fund_flow_attribution.jsonl`
- `logs/2026-05/2026-05-06/fund_flow_attribution.jsonl`
- `logs/2026-05/2026-05-07/fund_flow_attribution.jsonl`
- `logs/2026-05/2026-05-05/trade_fills_utc.csv`
- `logs/2026-05/2026-05-06/trade_fills_utc.csv`
- `logs/2026-05/2026-05-07/trade_fills_utc.csv`
- Derived artifact: `output/analysis/vwap_48h_20260506_0000_bj_to_20260507_2359_bj.json`

## Executive Summary

This 48H live slice cannot answer whether high VWAP score outperforms low VWAP score, because every live entry decision in the window had `vwap_score = 0.0`.

It can answer a narrower but important question: allowing zero-VWAP-score entries created a noisy live opportunity set. Matched closed entries with `vwap_score = 0.0` had only `55.9%` win rate. `vol_vwap_warn=True` entries were weaker than the small non-warning subset.

Current live config after the latest fix now raises VWAP floors:

| Parameter | Current value |
|---|---:|
| `weight_vwap` | `0.0` |
| `min_vwap_score_for_entry` | `0.12` |
| `short_min_vwap_score_for_entry` | `0.12` |
| `flip_bearish_short_min_vwap_score_for_entry` | `0.25` |
| `vol_vwap_warn_min_vwap_score` | `0.12` |
| `vol_vwap_warn_position_scale` | `0.0` |

Interpretation: VWAP is currently not an alpha score contributor (`weight_vwap=0.0`). It is now intended to act as an entry-quality gate and weak-signal blocker.

## Data Quality Notes

`trade_fills_utc.csv` contains duplicate fill rows. The analysis deduplicated by:

```text
fill_id, order_id, symbol, timestamp, side, price, quantity
```

Entry-to-PnL attribution is approximate. It matches each nonzero realized-PnL fill to the latest prior entry decision with the same symbol and inferred closing side:

- Sell fill closes a long.
- Buy fill closes a short.

This is good enough for VWAP signal-quality review, but not a perfect exchange-level position ledger. Some PnL rows are unmatched because positions were opened before the requested window or because hedge/partial-close state is not fully reconstructable from the compact logs.

## 48H Live Summary

| Metric | Value |
|---|---:|
| Decision events | `4125` |
| Execution events | `4125` |
| Entry decisions | `41` |
| Long entries | `35` |
| Short entries | `6` |
| Entry decisions with `vwap_score=0.0` | `41 / 41` |
| Deduped fills | `118` |
| Duplicate fills removed | `522` |
| Deduped realized PnL in requested window | `+5.019584 USDT` |
| Matched closed entry groups | `34` |
| Matched closed entry PnL | `+2.019754 USDT` |
| Matched closed entry win rate | `19 / 34 = 55.88%` |

Important caveat: total deduped realized PnL includes positions not necessarily opened during this 48H window. Matched closed entry PnL is the cleaner subset for entry-quality review.

## VWAP Score Versus Outcome

Because all entry decisions had `vwap_score=0.0`, the bucket table collapses to one bucket:

| VWAP score bucket | Entries | Matched closed entries | Wins | Losses | Win rate | Matched PnL |
|---|---:|---:|---:|---:|---:|---:|
| `<= 0` | `41` | `34` | `19` | `15` | `55.88%` | `+2.019754` |

This means the live data does not validate a graduated score curve. It only shows that the system was willing to trade when VWAP contributed no score.

## VWAP Warning Versus Outcome

Entry counts:

| `vol_vwap_warn` | Entries |
|---|---:|
| `True` | `36` |
| `False` | `4` |
| `None` | `1` |

Matched outcome:

| `vol_vwap_warn` | Matched closed entries | Wins | Losses | Win rate | Matched PnL |
|---|---:|---:|---:|---:|---:|
| `True` | `31` | `17` | `14` | `54.84%` | `+0.476528` |
| `False` | `2` | `2` | `0` | `100.00%` | `+2.179120` |
| `None` | `1` | `0` | `1` | `0.00%` | `-0.635894` |

The non-warning sample is tiny, so do not overfit the `100%` win rate. But it is still directionally important: the bulk of weak-quality trades came from `vol_vwap_warn=True`, and that bucket had mediocre win rate.

## Top Matched Losses

| Symbol | Side | PnL | VWAP score | `vol_vwap_warn` | Entry reason |
|---|---|---:|---:|---|---|
| `JSTUSDT` | LONG | `-1.873360` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `ONDOUSDT` | LONG | `-0.866840` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `RENDERUSDT` | LONG | `-0.842400` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `POLUSDT` | LONG | `-0.654610` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `PUMPUSDT` | LONG | `-0.635894` | `0.0` | `None` | `DCA/马丁触发 stage=1/1` |
| `JSTUSDT` | LONG | `-0.476520` | `0.0` | `True` | `macd_v2_long_1h_green_bar_shrinking_15m_rsi_neutral_resume_vwap_0.00` |
| `ATOMUSDT` | LONG | `-0.396240` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `JSTUSDT` | LONG | `-0.371700` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `AAVEUSDT` | LONG | `-0.258000` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `AAVEUSDT` | LONG | `-0.230000` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |

## Top Matched Wins

| Symbol | Side | PnL | VWAP score | `vol_vwap_warn` | Entry reason |
|---|---|---:|---:|---|---|
| `SOLUSDT` | LONG | `+1.729000` | `0.0` | `False` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `ALGOUSDT` | LONG | `+0.835440` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `ZROUSDT` | LONG | `+0.736740` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `ONDOUSDT` | LONG | `+0.596050` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `VETUSDT` | LONG | `+0.542360` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `TRUMPUSDT` | LONG | `+0.510410` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `PUMPUSDT` | LONG | `+0.490770` | `0.0` | `True` | `DCA/马丁触发 stage=1/1` |
| `VETUSDT` | LONG | `+0.460576` | `0.0` | `True` | `macd_v2_long_1h_red_bar_shrinking_15m_rsi_neutral_resume_vwap_0.00` |
| `DOGEUSDT` | LONG | `+0.450120` | `0.0` | `False` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |
| `JUPUSDT` | LONG | `+0.444600` | `0.0` | `True` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.00` |

Read: `vwap_score=0.0` is not always losing. The problem is not "zero VWAP guarantees loss." The problem is that zero VWAP does not discriminate. It lets both good and bad MACD/RSI entries pass, and the bad tail is large.

## Current VWAP Parameters

From `config/trading_config_fund_flow.json`:

```json
"scoring_weights": {
  "weight_vwap": 0.0
}
```

```json
"entry_filters": {
  "enable_vwap_flip_exemption": true,
  "preflip_trial_min_vwap_score": 0.0,
  "trial_short_below_structure_promotion_min_vwap_score": 0.0,
  "short_min_vwap_score_for_entry": 0.12,
  "flip_bearish_short_min_vwap_score_for_entry": 0.25,
  "stable_bear_continuation_min_vwap_score": 0.0,
  "stable_bull_continuation_min_vwap_score": 0.0,
  "flip_bullish_min_vwap_score": 0.0,
  "flip_bearish_retest_reject_min_vwap_score": 0.25,
  "vol_vwap_warn_min_score_vol": 0.05,
  "vol_vwap_warn_min_vwap_score": 0.12,
  "min_vwap_score_for_entry": 0.12
}
```

```json
"position_management": {
  "vol_vwap_warn_position_scale": 0.0
}
```

## VWAP Formula In Code

Relevant files:

- `src/fund_flow/decision_engine.py`
- `src/fund_flow/macd_strategy_v2.py`

### Input selection

Decision engine reads VWAP from the 1H timeframe context:

```python
vwap = tf_1h.get("vwap")
structural_vwap = (
    tf_1h.get("structural_vwap")
    or tf_1h.get("anchored_vwap")
    or tf_1h.get("rolling_vwap")
)
```

It also passes optional series:

```python
vwap_1h_series = tf_1h.get("vwap_series") or tf_1h.get("vwap_array")
structural_vwap_1h_series = (
    tf_1h.get("structural_vwap_series")
    or tf_1h.get("anchored_vwap_series")
    or tf_1h.get("rolling_vwap_series")
)
```

### If session VWAP is missing

If `vwap <= 0`, the function returns a neutral partial score:

```python
location_score = 0.5
score = weight_vwap * 0.5
state = "no_vwap"
```

Because live `weight_vwap=0.0`, missing VWAP produces `score=0.0`.

### If structural VWAP is missing

If session VWAP exists but structural VWAP is missing, the logic falls back to session-VWAP-only scoring:

```python
deviation = (price - vwap) / vwap
```

For long:

```python
directional_extension = deviation
entry_edge = -deviation
```

For short:

```python
directional_extension = -deviation
entry_edge = deviation
```

Hard block:

```python
if directional_extension > vwap_deviation_hard_block:
    score = 0.0
    veto = VWAP_HARD_BLOCK
```

Continuous score:

```python
entry_edge_quality = 0.5 + 0.5 * clamp(entry_edge / warning, -1, 1)
value_proximity_quality = 1 - clamp(abs(deviation) / hard_block, 0, 1)
extension_quality = 1 - clamp(max(0, directional_extension) / hard_block, 0, 1)

location_score = clamp(
    0.75 * entry_edge_quality
  + 0.15 * value_proximity_quality
  + 0.10 * extension_quality,
  0,
  1
)
score = weight_vwap * location_score
```

### If both session and structural VWAP exist

The full formula uses:

```python
session_deviation = (price - session_vwap) / session_vwap
structural_deviation = (price - structural_vwap) / structural_vwap
tolerance = vwap_retest_tolerance
warning = max(vwap_deviation_warning, tolerance * 2)
hard_block = max(vwap_deviation_hard_block, warning + 1e-6)
```

For long, supportive states are based on price above session and/or structural VWAP:

- `long_reclaim_confirmed`
- `long_dual_support`
- `long_above_structure_wait_reclaim`
- `long_above_session_below_structure`
- `long_below_both`

Long score:

```python
session_support_quality = clamp((session_deviation + tolerance) / (warning + tolerance), 0, 1)
structural_support_quality = clamp((structural_deviation + tolerance) / (warning + tolerance), 0, 1)
extension_penalty = clamp(max(0, session_deviation - warning) / (hard_block - warning), 0, 1)
reclaim_quality = 1 if long_reclaim_confirmed else 0
dual_support_quality = 1 if session_above and structure_above else 0
value_proximity_quality = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

location_score = clamp(
    0.36 * session_support_quality
  + 0.26 * structural_support_quality
  + 0.18 * reclaim_quality
  + 0.12 * dual_support_quality
  + 0.08 * value_proximity_quality
  - 0.12 * extension_penalty,
  0,
  1
)
score = weight_vwap * location_score
```

For short, supportive states are based on price below session and/or structural VWAP:

- `short_retest_reject`
- `short_dual_pressure`
- `short_under_structure_wait_reject`
- `short_below_session_above_structure`
- `short_above_both`

Short score:

```python
session_pressure_quality = clamp((-session_deviation + tolerance) / (warning + tolerance), 0, 1)
structural_pressure_quality = clamp((-structural_deviation + tolerance) / (warning + tolerance), 0, 1)
extension_penalty = clamp(max(0, -session_deviation - warning) / (hard_block - warning), 0, 1)
retest_quality = 1 if short_retest_reject else 0
dual_pressure_quality = 1 if session_below and structure_below else 0
value_proximity_quality = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

location_score = clamp(
    0.36 * session_pressure_quality
  + 0.26 * structural_pressure_quality
  + 0.18 * retest_quality
  + 0.12 * dual_pressure_quality
  + 0.08 * value_proximity_quality
  - 0.12 * extension_penalty,
  0,
  1
)
score = weight_vwap * location_score
```

### Entry floor resolution

The entry floor is separate from scoring:

```python
global_floor = min_vwap_score_for_entry
short_floor = max(global_floor, short_min_vwap_score_for_entry)
```

For long:

```python
if signal_type == "flip_bullish":
    floor = max(global_floor, flip_bullish_min_vwap_score)
else:
    floor = global_floor
```

For short:

```python
if signal_type == "flip_bearish":
    floor = max(short_floor, flip_bearish_short_min_vwap_score_for_entry)
else:
    floor = short_floor
```

Current live result:

- Long floor: `0.12`
- Ordinary short floor: `0.12`
- `flip_bearish` short floor: `0.25`
- `flip_bullish` long floor: effectively `0.12`, but `disable_flip_bullish_entries=true`

## Critical Observation

The 48H logs show `vwap_score=0.0` for every entry, yet the system traded. That happened because the historical/live config during the window allowed zero VWAP:

- VWAP weight had already been removed from score contribution.
- VWAP entry floors were effectively open or not enforced for the live path in that run.
- `vol_vwap_warn_position_scale=0.50` allowed weak volume plus weak VWAP signals to enter at half size.

The current config has been changed to block this:

- `min_vwap_score_for_entry=0.12`
- `short_min_vwap_score_for_entry=0.12`
- `flip_bearish_short_min_vwap_score_for_entry=0.25`
- `vol_vwap_warn_min_vwap_score=0.12`
- `vol_vwap_warn_position_scale=0.0`

## What This Review Suggests

1. VWAP should not be used as a return alpha amplifier until we have nonzero VWAP-score samples and an ablation showing monotonic improvement.
2. VWAP is useful as a hygiene gate: it can block entries where the location model contributes nothing.
3. `vol_vwap_warn` should not be a half-size entry mode in live unless a backtest proves that bucket is profitable. In this 48H slice, the warning bucket is noisy and mediocre.
4. DCA/martingale entries need separate review. `PUMPUSDT` had a DCA matched loss of `-0.635894`, and DCA bypasses ordinary entry quality metadata like `vol_vwap_warn`.
5. Do not infer that `vwap_score=0.0` always loses. In this slice it had winners too. The issue is low discrimination and fat-tail losses, not deterministic badness.

## Questions For Claude

Please review the VWAP design and answer:

1. Should VWAP be a hard entry floor, a soft position scaler, or a score contributor?
2. With `weight_vwap=0.0`, is it coherent to keep `min_vwap_score_for_entry` as a hard gate, or should the system compute a separate `vwap_quality` field for gating?
3. Are the current floors reasonable?
   - Global/long: `0.12`
   - Ordinary short: `0.12`
   - `flip_bearish` short: `0.25`
4. Should `vol_vwap_warn_position_scale` remain `0.0`, or should it become a very small probe only when RSI/MACD quality is exceptional?
5. Should DCA be forbidden when the original entry had `vwap_score < floor` or `vol_vwap_warn=True`?
6. Does the current formula over-reward price being above VWAP for longs and below VWAP for shorts, effectively making VWAP a continuation filter rather than a value-entry filter?
7. Should long entries prefer `long_reclaim_confirmed` over `long_dual_support` to avoid chasing extended moves?
8. Should short entries prefer `short_retest_reject` over `short_dual_pressure` to avoid shorting breakdown exhaustion?
9. How should missing VWAP be handled? Current `vwap <= 0` returns neutral `location_score=0.5`, which becomes `0.0` only because `weight_vwap=0.0`. Should missing VWAP be a hard no-trade instead?
10. What 30D ablation grid should be run next to validate VWAP usage?

Suggested ablation grid:

| Variant | `weight_vwap` | `min_vwap_score_for_entry` | `short_min_vwap_score_for_entry` | `flip_bearish_short_min_vwap_score_for_entry` | `vol_vwap_warn_position_scale` |
|---|---:|---:|---:|---:|---:|
| Current gate | `0.0` | `0.12` | `0.12` | `0.25` | `0.0` |
| Gate light | `0.0` | `0.08` | `0.10` | `0.20` | `0.0` |
| Score only | `0.05` | `0.0` | `0.0` | `0.0` | `0.0` |
| Score plus gate | `0.05` | `0.08` | `0.10` | `0.20` | `0.0` |
| Probe weak VWAP | `0.0` | `0.12` | `0.12` | `0.25` | `0.10` |

Acceptance criteria:

- Win rate improves versus no-VWAP-gate baseline, or total return improves without worse drawdown.
- Profit factor stays above `1.3`.
- Max drawdown does not increase by more than `2%` absolute.
- Trade count does not collapse so far that the live system becomes sparse/noisy.

## Bottom Line

This 48H live window supports using VWAP as a protective entry-quality gate, not yet as a calibrated alpha score. The strongest immediate fix is to prevent `vwap_score=0.0` plus weak volume entries from opening real positions. The next decision should be made from a 30D ablation, not from this 48H slice alone.
