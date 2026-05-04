# Recent 34H Live Loss Review

- Date: `2026-05-04`
- Window: `2026-05-02 16:15:14 UTC` to `2026-05-04 02:15:14 UTC`
- Data sources:
  - `logs/2026-05/2026-05-03/trade_fills_utc.csv`
  - `logs/2026-05/2026-05-04/trade_fills_utc.csv`
  - `logs/2026-05/2026-05-03/fund_flow/fund_flow_strategy.db`
  - `logs/2026-05/2026-05-03/runtime.out.*.log`
  - `logs/2026-05/2026-05-04/runtime.out.*.log`

## Findings

`trade_fills_utc.csv` contains duplicate rows for the same exchange fill IDs, so fills were deduplicated by fill/order/symbol/time before aggregation.

Deduped closed-trade read:

| Metric | Value |
|---|---:|
| Closed trades | `13` |
| Wins / losses | `2 / 11` |
| Gross win | `+0.28825` |
| Gross loss | `-2.34199` |
| Net realized PnL | `-2.05374` |

By side:

| Side | Trades | Wins / losses | Net PnL | Avg hold |
|---|---:|---:|---:|---:|
| Long | `9` | `2 / 7` | `-1.18774` | `~6.2h` |
| Short | `4` | `0 / 4` | `-0.86600` | `~1.55h` |

Main losing symbols:

| Symbol | Side | PnL | Price move | Hold |
|---|---|---:|---:|---:|
| `ICPUSDT` | short | `-0.532` | `-1.204%` | `3.36h` |
| `ATOMUSDT` | long | `-0.4448` | `-0.847%` | `11.13h` |
| `JUPUSDT` | long | `-0.334` | `-1.117%` | `1.71h` |
| `AAVEUSDT` | long | `-0.280` | `-1.003%` | `5.79h` |
| `SOLUSDT` | long+short | `-0.2492` | mixed | `~5.52h avg` |

## Root Cause Read

The recent issue is not primarily "holding too briefly." Several losing long trades held for `4h` to `11h`. Extending hold time would likely delay loss recognition, not fix the entry problem.

The short side is currently poor in this live slice. All `4/4` reconstructed short exits lost money. The losing short entries had low VWAP scores:

| Symbol | Short entry reason | VWAP score | Result |
|---|---|---:|---:|
| `SUIUSDT` | `flip_bearish` | `0.0321` | loss |
| `SOLUSDT` | `flip_bearish` | `0.0250` | loss |
| `AVAXUSDT` | `flip_bearish` | `0.0144` | loss |

Many losing long entries carried `vol_vwap_warn=true`, meaning both volume score and VWAP score were weak. This is a key contributor to the recent loss cluster, though not the only one. Before this update, live config only scaled these entries to `50%`; it still allowed them to trade.

MFE/MAE review:

| Trade | Max MFE | Max MAE | Read |
|---|---:|---:|---|
| `AAVEUSDT` long | `+0.73%` | `-0.61%` | profitable excursion was not protected |
| `AVAXUSDT` long | `+0.60%` | `-0.25%` | profitable excursion was not protected |
| `SOLUSDT` long | `+0.76%` | `-0.25%` | profitable excursion was not protected |
| `ICPUSDT` short | `0.00%` | `-1.12%` | direction quality problem |
| `SOLUSDT` short | `0.00%` | `-0.47%` | direction quality problem |

The trend protection thresholds were too high for the observed live excursion profile: break-even was `0.8%`, and trailing activation was `2.0%`. Recent winners-to-be topped around `0.6%` to `0.76%`, so protection stayed `action=none`.

## Production Parameter Updates

Updated `config/trading_config_fund_flow.json`:

```text
fund_flow.symbol_blacklist += XLMUSDT
fund_flow.macd_mtf_strategy_v2.entry_filters.min_vwap_score_for_entry: 0.0 -> 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.short_min_vwap_score_for_entry: 0.06 -> 0.12
fund_flow.macd_mtf_strategy_v2.entry_filters.flip_bearish_short_min_vwap_score_for_entry: 0.08 -> 0.25
fund_flow.macd_mtf_strategy_v2.entry_filters.vol_vwap_warn_min_vwap_score: 0.10 -> 0.12
fund_flow.macd_mtf_strategy_v2.position_management.vol_vwap_warn_position_scale: 0.50 -> 0.0
fund_flow.engine_params.TREND.tp_break_even_trigger_pnl_ratio: 0.008 -> 0.0055
fund_flow.engine_params.TREND.tp_trailing_activate_mfe_ratio: 0.02 -> 0.0075
fund_flow.engine_params.TREND.tp_trailing_distance_ratio: 0.01 -> 0.003
```

Expected behavior:

- `XLMUSDT` is blocked by `symbol_blacklist`.
- Long and ordinary short entries with VWAP score below `0.12` should not enter.
- Low-volume plus low-VWAP signals are sized to zero and should be blocked by the existing minimum-open gate.
- Weak `flip_bearish` shorts with VWAP score below `0.25` should not enter.
- Trend positions with `~0.55%` current profit can arm break-even.
- Trend positions with `~0.75%` MFE can start tighter trailing.

## Decision

Do not extend holding time based on this slice. The stronger fixes are entry quality filtering and earlier profit protection.

Do not reopen light TP or capacity work from this evidence. The live issue was low-quality entries and unprotected modest MFE, not insufficient capacity or premature TP.
