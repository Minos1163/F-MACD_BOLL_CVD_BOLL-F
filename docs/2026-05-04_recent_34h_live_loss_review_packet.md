# MACD V2 Recent 34H Live Loss Review Packet

- Date: `2026-05-04`
- Window: `2026-05-02 16:15:14 UTC` to `2026-05-04 02:15:14 UTC`
- Purpose: Re-analyze the recent live period where losses exceeded wins, with detailed attribution for direction quality, stop behavior, risk control, and holding time.
- Data sources:
  - `logs/2026-05/**/trade_fills_utc.csv`
  - `logs/2026-05/**/fund_flow_attribution.jsonl`
  - `logs/2026-05/**/fund_flow/fund_flow_strategy.db`
  - `logs/2026-05/**/runtime.out.*.log`
  - `config/trading_config_fund_flow.json`
  - `src/fund_flow/decision_engine.py`
  - `src/fund_flow/macd_strategy_v2.py`
  - `src/app/fund_flow_bot.py`

## 1. Evidence Boundary

`trade_fills_utc.csv` contains duplicate historical rows across days. Fills were deduplicated by exchange fill/order/symbol/time/side/price/qty before aggregation.

The live decision metadata is partially compacted before persistence. Both `fund_flow_attribution.jsonl` and SQLite `decision_json` preserve key fields such as `regime`, `regime_adx`, `score_volume`, `vwap_score`, `vol_vwap_warn`, target portion, and leverage, but many deeper scoring fields are replaced by `_omitted_keys`. Therefore:

- Trade-level attribution below uses observed fills, observed decision metadata, runtime risk logs, and price snapshots.
- Full scoring-chain details are derived from current code and config in `docs/2026-05-04_macd_v2_live_entry_risk_chain_review_packet.md`.
- Any conclusion marked as `inference` should be reviewed by Claude against raw runtime logs and code.

## 2. Executive Summary

The recent loss cluster is primarily an entry-quality and direction-quality problem, not a holding-time problem.

Key facts:

| Metric | Value |
|---|---:|
| Deduped window fills | `38` |
| Closed trade groups | `13` |
| Wins / losses | `2 / 11` |
| Gross win | `+0.28825` |
| Gross loss | `-2.34199` |
| Net realized PnL | `-2.05374` |
| Fees on closed groups | `-0.15636` |
| Long trades | `9`, `2W / 7L`, `-1.18774` |
| Short trades | `4`, `0W / 4L`, `-0.86600` |

Primary conclusion:

```text
Most closed entries in this slice were low-volume + low-VWAP entries.
The short side was directionally poor, especially flip_bearish shorts with VWAP score below 0.04.
Several long trades were held for many hours, so simply extending holding time is not supported by this evidence.
Risk protection appears to have placed/repaired protection orders, but runtime summaries show many stop=0.0000 lines and need code/log review.
```

## 3. Closed Trade Reconstruction

| # | Symbol | Side | Entry | Exit | Hold h | Entry reason | Regime | ADX | Vol score | VWAP score | `vol_vwap_warn` | Portion | Lev | Price move | MFE | MAE | PnL |
|---:|---|---|---|---|---:|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `TRUMPUSDT` | long | `2026-05-02 14:45:14` | `2026-05-02 18:50:35` | `4.09` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.04` | `TREND` | `56.21` | `0.033` | `0.0425` | `true` | `0.1400` | `1` | `+1.936%` | `+1.678%` | `+0.043%` | `+0.22725` |
| 2 | `AVAXUSDT` | long | `2026-05-02 14:45:14` | `2026-05-02 23:57:42` | `9.21` | `macd_v2_long_1h_red_bar_growing_15m_rsi_neutral_resume_vwap_0.04` | `TREND` | `29.83` | `0.033` | `0.0364` | `true` | `0.1680` | `1` | `+0.669%` | `+1.042%` | `+0.022%` | `+0.06100` |
| 3 | `XLMUSDT` | long | `2026-05-02 15:15:14` | `2026-05-02 23:57:51` | `8.71` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.04` | `TREND` | `27.87` | `0.033` | `0.0401` | `true` | `0.1680` | `2` | `-0.256%` | `+0.300%` | `-0.356%` | `-0.02829` |
| 4 | `AAVEUSDT` | long | `2026-05-02 19:15:13` | `2026-05-03 01:02:34` | `5.79` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.05` | `TREND` | `21.07` | `0.033` | `0.0457` | `true` | `0.1680` | `3` | `-1.003%` | `+0.731%` | `-0.613%` | `-0.28000` |
| 5 | `ICPUSDT` | short | `2026-05-03 02:30:14` | `2026-05-03 05:51:44` | `3.36` | `macd_v2_short_1h_flip_bearish_15m__vwap_0.00` | `TREND` | `25.78` | `0.033` | `0.0029` | `true` | `0.1785` | `3` | `-1.204%` | `+0.000%` | `-0.946%` | `-0.53200` |
| 6 | `BCHUSDT` | long | `2026-05-03 13:00:15` | `2026-05-03 17:01:14` | `4.02` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.03` | `RANGE` | `9.69` | `0.033` | `0.0340` | `true` | `0.0735` | `3` | `-0.549%` | `+0.094%` | `-0.401%` | `-0.11270` |
| 7 | `AVAXUSDT` | long | `2026-05-03 17:15:14` | `2026-05-03 21:46:44` | `4.53` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.04` | `TREND` | `37.41` | `0.033` | `0.0374` | `true` | `0.2100` | `3` | `-0.495%` | `+0.605%` | `-0.253%` | `-0.18000` |
| 8 | `ATOMUSDT` | long | `2026-05-03 12:15:14` | `2026-05-03 23:23:16` | `11.13` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.04` | `RANGE` | `10.40` | `0.033` | `0.0428` | `true` | `0.2100` | `3` | `-0.847%` | `+0.106%` | `-0.688%` | `-0.44480` |
| 9 | `JUPUSDT` | long | `2026-05-03 22:15:14` | `2026-05-03 23:58:05` | `1.71` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.04` | `TREND` | `34.94` | `0.033` | `0.0446` | `true` | `0.1680` | `3` | `-1.117%` | `+0.056%` | `-0.894%` | `-0.33400` |
| 10 | `SOLUSDT` | long | `2026-05-03 14:00:15` | `2026-05-04 00:00:34` | `10.01` | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.02` | `NO_TRADE` | `14.52` | `0.033` | `0.0232` | `true` | `0.1680` | `3` | `-0.309%` | `+0.761%` | `-0.250%` | `-0.09620` |
| 11 | `SUIUSDT` | short | `2026-05-04 00:15:14` | `2026-05-04 01:31:34` | `1.27` | `macd_v2_short_1h_flip_bearish_15m__vwap_0.03` | `TREND` | `34.68` | `0.033` | `0.0321` | `true` | `0.0625` | `3` | `-0.818%` | `+0.164%` | `-0.316%` | `-0.12600` |
| 12 | `AVAXUSDT` | short | `2026-05-04 01:00:15` | `2026-05-04 01:31:48` | `0.53` | `macd_v2_short_1h_flip_bearish_15m__vwap_0.01` | `TREND` | `21.43` | `0.033` | `0.0144` | `true` | `0.0625` | `3` | `-0.608%` | `+0.155%` | `+0.033%` | `-0.05500` |
| 13 | `SOLUSDT` | short | `2026-05-04 00:30:14` | `2026-05-04 01:32:35` | `1.04` | `macd_v2_short_1h_flip_bearish_15m__vwap_0.03` | `TREND` | `37.44` | `0.033` | `0.0250` | `true` | `0.0625` | `3` | `-1.080%` | `-0.072%` | `-0.468%` | `-0.15300` |

Important observations:

- `13/13` closed entries had `vol_vwap_warn=true` at entry.
- `11/11` losing entries had `vol_vwap_warn=true` at entry.
- `4/4` short trades lost money; all four were `flip_bearish` with VWAP score below `0.04`.
- Several losing long trades held for `4h` to `11h`; extending holding time is not supported by this slice.

## 4. Direction Accuracy

### 4.1 Long Direction

Long side was weak but not uniformly directionally wrong.

| Bucket | Trades | Wins / losses | Net PnL | Read |
|---|---:|---:|---:|---|
| Long total | `9` | `2 / 7` | `-1.18774` | poor expectancy in this slice |
| Long with MFE `> +0.60%` | `4` | mixed | includes `AVAX`, `AAVE`, `SOL`, prior `AVAX` | direction had some favorable excursion |
| Long with MFE `< +0.15%` | `3` | mostly loss | `BCH`, `ATOM`, `JUP` | weak follow-through |

Interpretation:

- Some long entries were directionally acceptable but not protected after modest favorable excursion, especially `AAVEUSDT` and `SOLUSDT`.
- Other long entries were simply weak: `ATOMUSDT`, `BCHUSDT`, and `JUPUSDT` had limited MFE before loss.
- The common entry-quality issue is low `score_volume=0.033` and low VWAP score around `0.02~0.05`.

### 4.2 Short Direction

Short side was directionally poor.

| Symbol | Entry reason | VWAP | Hold | MFE | MAE | PnL | Read |
|---|---|---:|---:|---:|---:|---:|---|
| `ICPUSDT` | `flip_bearish` | `0.0029` | `3.36h` | `0.000%` | `-0.946%` | `-0.53200` | no favorable move |
| `SUIUSDT` | `flip_bearish` | `0.0321` | `1.27h` | `+0.164%` | `-0.316%` | `-0.12600` | tiny MFE, then loss |
| `AVAXUSDT` | `flip_bearish` | `0.0144` | `0.53h` | `+0.155%` | `+0.033%` | `-0.05500` | small adverse close |
| `SOLUSDT` | `flip_bearish` | `0.0250` | `1.04h` | `-0.072%` | `-0.468%` | `-0.15300` | immediately wrong |

Interpretation:

- The short entries were not accurate in this slice.
- The worst single realized loss was `ICPUSDT` short, and it never developed favorable excursion.
- A `flip_bearish` short entry with VWAP below `0.04` is a clear risk pattern in this window.
- This supports the live change to raise `flip_bearish_short_min_vwap_score_for_entry` to `0.25`.

## 5. Stop / Small-Loss Behavior

### 5.1 Did the system stop small losses?

Observed loss sizes were mostly small at the account/fill scale, but price moves reached `-0.5%` to `-1.2%` on several trades.

| Loss band | Trades | Examples |
|---|---:|---|
| Better than `-0.35%` price move | `2` | `XLMUSDT`, `SOLUSDT` long |
| Around `-0.5%` to `-0.85%` | `5` | `BCH`, `AVAX` long, `ATOM`, `SUI` short, `AVAX` short |
| Worse than `-1.0%` | `3` | `AAVE` long, `ICP` short, `JUP` long |

Interpretation:

- The system did cut losses before they became multi-percent tail losses.
- It did not consistently cut at `0.5%`; realized price loss exceeded `1%` for `AAVE`, `ICP`, and `JUP`.
- Short stop distances in runtime logs were often around `0.59%~0.93%`, but realized `ICP` short lost `1.204%`, likely due to stop placement/fill timing or protection execution details.

### 5.2 Runtime Risk Log Concerns

Runtime logs show protection behavior such as:

```text
SUIUSDT protection order repair completed, SLA restored
SOLUSDT protection order repair completed, SLA restored
AVAXUSDT protection order repair completed, SLA restored
AAVEUSDT / JUPUSDT / ZROUSDT protection order repair completed, SLA restored
```

But the same logs repeatedly show:

```text
MACD_V2 stop: stop=0.0000, stop_pct=2.00%
```

Review concern for Claude:

- Verify whether `stop=0.0000` means no valid strategy-level stop in the risk summary, or only that the runtime risk summary could not map existing exchange protection orders back to the strategy stop object.
- Verify whether protection coverage checks are based on exchange open orders, local persisted protection plans, or both.
- Verify whether old positions from before current config can carry different stop behavior than new positions.

## 6. Risk Control Accuracy

### 6.1 What worked

- Protection SLA logic appears active and repairs missing protection orders.
- Capacity/entry finalization logic exists and ranks pending entries before execution.
- Actual position sizes were small in this account slice, so account-level loss was limited.
- Recent live config now includes `ADAUSDT`, `FETUSDT`, and `XLMUSDT` in `fund_flow.symbol_blacklist`.

### 6.2 What did not work before the latest parameter change

Before the latest live parameter update, low-volume + low-VWAP entries were not blocked. They were scaled, usually by `vol_vwap_warn_position_scale=0.50`, but still traded.

Observed evidence:

| Pattern | Count |
|---|---:|
| Closed entries with `vol_vwap_warn=true` | `13/13` |
| Losing entries with `vol_vwap_warn=true` | `11/11` |
| Short losing entries with `vwap_score < 0.04` | `4/4` |

This supports the current live changes:

```text
fund_flow.macd_mtf_strategy_v2.entry_filters.min_vwap_score_for_entry = 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.short_min_vwap_score_for_entry = 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.flip_bearish_short_min_vwap_score_for_entry = 0.25
fund_flow.macd_mtf_strategy_v2.entry_filters.vol_vwap_warn_min_vwap_score = 0.12
fund_flow.macd_mtf_strategy_v2.position_management.vol_vwap_warn_position_scale = 0.0
```

### 6.3 Risk gate caveat

`fund_flow.pretrade_risk_gate.enabled=false` in current config. That means the separate pretrade risk gate is not the active blocking mechanism; entry quality must be enforced mainly by MACD V2 filters, symbol blacklist, capacity gates, min-open gates, and protection-gap gates.

## 7. Holding Time Assessment

The evidence does not support extending holding time as the primary fix.

| Side | Avg hold | Read |
|---|---:|---|
| Long | `~6.58h` | not too short; several losses held `4h~11h` |
| Short | `~1.55h` | shorter, but mainly because direction went wrong quickly |

Examples:

- `ATOMUSDT` long held `11.13h`, lost `-0.847%`, MFE only `+0.106%`.
- `SOLUSDT` long held `10.01h`, had MFE `+0.761%`, then exited at `-0.309%`.
- `AAVEUSDT` long held `5.79h`, had MFE `+0.731%`, then exited at `-1.003%`.
- `ICPUSDT` short held `3.36h`, had MFE `0.000%`, so longer holding would likely worsen or delay loss recognition.

Conclusion:

```text
Do not globally extend holding time from this evidence.
For longs with MFE around +0.6% to +0.8%, earlier BE/trailing protection is more relevant than longer holding.
For weak shorts with near-zero MFE, the fix is entry filtering, not hold extension.
```

## 8. Root Cause Attribution

| Cause | Evidence | Confidence | Action |
|---|---|---:|---|
| Low volume + low VWAP entries were allowed | `13/13` closed entries had `vol_vwap_warn=true`; `11/11` losing entries too | High for this window | Keep `vol_vwap_warn_position_scale=0.0`; keep VWAP entry floor `0.12` |
| Weak `flip_bearish` shorts | `4/4` shorts lost; VWAP `0.0029~0.0321` | High for this window | Keep `flip_bearish_short_min_vwap_score_for_entry=0.25`; consider enabling short quality filter |
| Some long profits were not protected | `AAVE`, `AVAX`, `SOL` had MFE `+0.60%~+0.76%` before loss/weak exit | Medium | Current BE/trailing thresholds were lowered; monitor next live sample |
| Holding time too short | Long avg hold `~6.58h`, losses held up to `11.13h` | Low | Do not extend globally |
| Global stop too loose | Losses mostly `-0.5%~-1.2%`, not `-3%` tail | Medium-low | Do not deploy global hard stop based on this slice |
| Protection SLA broken | Repairs show success, but `stop=0.0000` appears often | Unknown | Claude should inspect protection-state mapping and stop summary logic |

## 9. Current Production Adjustments Already Applied

These changes were applied before this packet was written:

```text
fund_flow.symbol_blacklist += ADAUSDT, FETUSDT, XLMUSDT
fund_flow.macd_mtf_strategy_v2.entry_filters.min_vwap_score_for_entry: 0.0 -> 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.short_min_vwap_score_for_entry: 0.06 -> 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.flip_bearish_short_min_vwap_score_for_entry: 0.08 -> 0.25
fund_flow.macd_mtf_strategy_v2.entry_filters.vol_vwap_warn_min_vwap_score: 0.10 -> 0.12
fund_flow.macd_mtf_strategy_v2.position_management.vol_vwap_warn_position_scale: 0.50 -> 0.0
fund_flow.engine_params.TREND.tp_break_even_trigger_pnl_ratio: 0.008 -> 0.0055
fund_flow.engine_params.TREND.tp_trailing_activate_mfe_ratio: 0.02 -> 0.0075
fund_flow.engine_params.TREND.tp_trailing_distance_ratio: 0.01 -> 0.003
```

## 10. Recommended Next Actions

1. Do not extend holding time globally.
2. Keep the low VWAP / low volume blocks live and monitor whether new entries with VWAP below `0.12` disappear.
3. Review `short_quality_filter.enabled=false`; consider a controlled experiment enabling it only for `flip_bearish` shorts, because the code already supports funding/OI/VWAP-deviation quality checks.
4. Audit why `SOLUSDT` at `2026-05-04 02:00:15` had `vwap_score=0.0092` but `vol_vwap_warn=false` due to `score_volume=0.1`; the new `min_vwap_score_for_entry=0.12` should block it now.
5. Ask Claude to inspect the protection SLA and stop summary mismatch: repeated `stop=0.0000` versus successful protection repairs.
6. Re-run a post-change live review after the next comparable live window; do not mix further Light TP/capacity/global stop changes until this entry-quality change has a clean read.

## 11. Review Questions For Claude

1. Is `vol_vwap_warn_position_scale=0.0` sufficient to block weak low-volume + low-VWAP entries, or are there paths that bypass position scaling/min-open checks?
2. Does `min_vwap_score_for_entry=0.12` apply to all long entries, including 4H regime entries, neutral upgrades, and `rsi_neutral_resume` paths?
3. Does `short_min_vwap_score_for_entry=0.12` apply to non-`flip_bearish` shorts, and does `flip_bearish_short_min_vwap_score_for_entry=0.25` override it as intended?
4. Why did prior `vol_vwap_warn=true` entries still execute after being scaled to `0.50`? Confirm final target portion and min-open behavior.
5. Should `short_quality_filter.enabled` be turned on for `flip_bearish`, given all four recent shorts lost and had very low VWAP?
6. Does runtime protection summary `stop=0.0000` indicate a real missing stop, a logging/mapping issue, or old-position state mismatch?
7. Are BE/trailing thresholds now appropriate for observed MFE around `+0.6%~+0.8%`, or could they over-tighten future winners?
8. Are `RANGE` / `NO_TRADE` regime labels compatible with long entries in the current regime-entry path, or should those be blocked unless a stronger override exists?
