# MACD V2 High Win Rate / Low Return Review Packet

- Date: `2026-05-03`
- Purpose: Explain why the strict-live 30d backtest has very high win rate but relatively low return, and provide a focused review packet for Claude.
- Backtest mode: strict live parameters, no backtest profile override.
- Command:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --output-prefix output/backtest/live_strict_30d_20260503 --initial-capital 10000
```

## 1. Executive Summary

The backtest result is not a signal-quality failure. It is a payoff and execution-structure problem.

The strategy produced `91.36%` win rate and `PF=3.55`, but total return was only `+26.23%` because most wins are small and fast, while a few losses are large enough to consume a large share of gross profit. The system is currently optimized for a high hit rate, not for strong expectancy per unit of capital.

Key numbers:

| Metric | Value |
|---|---:|
| Initial capital | `10000.00` |
| Final capital | `12623.46` |
| Return | `+26.23%` |
| Trades | `162` |
| Wins / losses | `148 / 14` |
| Win rate | `91.36%` |
| Profit factor | `3.55` |
| True max drawdown | `5.01%` |
| Gross win | `+4058.57` |
| Gross loss | `-1141.99` |
| Net PnL | `+2916.57` |

Primary conclusion:

```text
High win rate is coming from many small exits.
Low return is coming from compressed average win, IOC/capacity leakage, and a few oversized losses.
```

## 2. Main Evidence

### 2.1 Win/Loss Asymmetry

The reported average win/loss ratio is weak:

| Metric | Value |
|---|---:|
| Average win | `+27.42` |
| Average loss | `-81.57` |
| Average win / average loss | `0.34` |

This means each losing trade costs roughly `3x` one winning trade. A `91%` win rate can still be profitable, but it becomes hard to compound capital aggressively because one bad stop wipes out many small wins.

The largest loss cluster is concentrated:

| Item | Value |
|---|---:|
| Total gross loss | `-1141.99` |
| Top 6 losses | `-1104.78` |
| Top 6 loss share | `~96.7%` of gross loss |

Worst losses:

| Entry | Exit | Symbol | Side | PnL | Price PnL % | Score | VWAP | ADX |
|---|---|---|---|---:|---:|---:|---:|---:|
| `2026-03-15 03:15` | `2026-03-15 06:15` | `FETUSDT` | long | `-406.29` | `-3.81%` | `0.6639` | `0.0364` | `42.34` |
| `2026-03-02 16:15` | `2026-03-02 23:15` | `ADAUSDT` | long | `-353.29` | `-3.79%` | `0.6617` | `0.0342` | `14.58` |
| `2026-03-09 13:45` | `2026-03-09 19:15` | `XLMUSDT` | long | `-116.23` | `-1.12%` | `0.6709` | `0.0434` | `14.76` |
| `2026-03-01 02:30` | `2026-03-01 08:45` | `SOLUSDT` | long | `-87.93` | `-2.75%` | `0.6638` | `0.0363` | `50.09` |
| `2026-03-02 15:15` | `2026-03-03 00:30` | `ALGOUSDT` | long | `-75.04` | `-2.94%` | `0.6634` | `0.0359` | `10.06` |
| `2026-03-20 19:45` | `2026-03-21 00:30` | `JSTUSDT` | long | `-66.01` | `-2.34%` | `0.6603` | `0.0328` | `24.31` |

Review concern:

Configured runtime stop loss is `stop_loss_pct=0.005` in the summary, but the worst losing trades show price PnL down to `-3.81%`. Claude should verify whether this is expected due to dynamic stop, intrabar stop fill assumptions, gap simulation, or a backtest/live mismatch.

### 2.2 Take-Profit Structure Caps Upside

Most profitable exits are small and fast:

| Exit reason | Trades | Wins | PnL | Avg PnL | Avg Price PnL % |
|---|---:|---:|---:|---:|---:|
| `sim_light_take_profit` | `67` | `67` | `+1924.50` | `+28.72` | `+0.53%` |
| `take_profit_intrabar` | `24` | `24` | `+1900.49` | `+79.19` | `+2.06%` |
| `stop_loss_intrabar` | `69` | `56` | `-900.81` | `-13.06` | `-0.10%` |
| `stop_loss_intrabar_both_hit` | `1` | `0` | `-8.86` | `-8.86` | `-0.05%` |
| `4h_shrink_exit` | `1` | `1` | `+1.26` | `+1.26` | `+0.10%` |

The win distribution confirms early exit compression:

| Winning trade price PnL percentile | Value |
|---|---:|
| P25 | `+0.20%` |
| P50 | `+0.25%` |
| P75 | `+0.80%` |
| P90 | `+2.00%` |

The strategy wins often, but many wins are harvested around `+0.2%` to `+0.5%`. This explains the high win rate and low capital growth.

Review concern:

`sim_light_take_profit` is probably too dominant for a trend strategy. It improves hit rate but may be cutting the right tail before winners can pay for rare losses.

### 2.3 Signal Mix Is Too Narrow

All meaningful PnL comes from one long-side state:

| Signal type | Trades | Win rate | PnL |
|---|---:|---:|---:|
| `red_bar_growing` | `157` | `91.08%` | `+2796.33` |
| `flip_bearish` | `5` | `100.00%` | `+120.25` |

Side breakdown:

| Side | Trades | Win rate | PnL |
|---|---:|---:|---:|
| long | `157` | `91.08%` | `+2796.33` |
| short | `5` | `100.00%` | `+120.25` |

The system is not meaningfully monetizing short-side opportunities in this 30d window. The high win rate mostly reflects one long continuation regime. If market regime changes, this may not transfer.

Review concern:

The strategy may be too conservative or too blocked on short/flip paths after recent guard tightening. This is acceptable for avoiding bad ICP-like shorts, but it reduces total return if short-side alpha is almost absent.

### 2.4 Execution Funnel Leaks Too Much Opportunity

Execution funnel:

| Stage | Count |
|---|---:|
| Candidate entries | `378` |
| Orders submitted | `232` |
| Orders filled | `95` |
| Orders canceled | `137` |
| IOC no-fill cancels | `137` |
| Capacity full precheck candidates | `55` |
| Capacity competition dropped | `38` |

Derived ratios:

| Ratio | Value |
|---|---:|
| submitted / candidate | `61.4%` |
| filled / submitted | `40.9%` |
| filled / candidate | `25.1%` |

This means most candidate opportunities never become filled entries. The strategy may be selecting decent setups, but the current IOC + capacity policy only realizes a quarter of candidates.

Review concern:

There may be a material return ceiling from `IOC` execution and `max_active_symbols=3`. The backtest shows `position_value_zero=52`, `ioc_no_fill=137`, and capacity drops. Claude should review whether the execution model is too strict relative to live intent, or whether relaxed fill policies would degrade win rate.

### 2.5 Capital Is Often Concentrated But Not Compounding Hard

Position sizing from filled trades:

| Field | Median | P75 | P90 |
|---|---:|---:|---:|
| Margin | `756.16` | `1818.67` | `2070.38` |
| Entry notional | `3024.65` | `7274.68` | `8281.52` |
| Remaining margin after entry | `0.00` | `499.05` | `643.44` |

The system often uses available margin, but because many exits happen at small price PnL and some candidate entries are dropped, capital turnover does not translate into high total return.

Holding time is also short:

| Hold time percentile | Hours |
|---|---:|
| P25 | `0.25` |
| P50 | `0.50` |
| P75 | `1.75` |
| P90 | `5.20` |

This suggests the strategy behaves more like fast scalping with trend filters than a trend-capture engine.

## 3. Symbol Attribution

Top contributors:

| Symbol | Trades | Win rate | PnL |
|---|---:|---:|---:|
| `JUPUSDT` | `8` | `87.50%` | `+479.60` |
| `ZROUSDT` | `7` | `100.00%` | `+441.29` |
| `AVAXUSDT` | `12` | `91.67%` | `+328.00` |
| `SUIUSDT` | `6` | `100.00%` | `+319.19` |
| `WLDUSDT` | `10` | `100.00%` | `+271.11` |
| `ICPUSDT` | `11` | `100.00%` | `+243.36` |

Worst contributors:

| Symbol | Trades | Win rate | PnL |
|---|---:|---:|---:|
| `ADAUSDT` | `7` | `57.14%` | `-263.95` |
| `FETUSDT` | `8` | `87.50%` | `-261.29` |
| `XLMUSDT` | `3` | `66.67%` | `-59.79` |
| `SOLUSDT` | `8` | `75.00%` | `+5.12` |
| `ALGOUSDT` | `6` | `83.33%` | `+22.10` |

Review concern:

`FETUSDT` is a clear example where high win rate does not imply positive expectancy. It had `87.5%` win rate but still lost `-261.29` because one large loss overwhelmed the small wins.

## 4. Post-Ablation Conclusions

Initial hypotheses were tested directly. The result is no longer "try TP/SL, capacity, and light TP"; the data points to one lever and closes several others.

### 4.1 Ablation Result Table

| Case | Return | Win rate | PF | MDD | Trades | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `00_baseline` | `+26.23%` | `91.36%` | `3.55` | `5.01%` | `162` | reference |
| `B1_disable_light_tp` | `+24.76%` | `85.11%` | `2.90` | `6.55%` | `94` | rejected |
| `B3_light_tp_only_low_adx` | `+26.76%` | `88.14%` | `3.27` | `5.07%` | `118` | marginal, not primary |
| `D1_max_symbols_4` | `+26.29%` | `90.80%` | `3.44` | `4.71%` | `174` | neutral |
| `D2_max_symbols_5` | `+26.11%` | `89.78%` | `3.36` | `5.04%` | `186` | rejected |
| `F1_blacklist_adausdt` | `+29.69%` | `93.04%` | `4.72` | `4.13%` | `158` | supported |
| `F2_blacklist_ada_fet` | `+35.23%` | `94.12%` | `13.58` | `3.22%` | `153` | strongest |
| `S1_max_stop_2pct` | `+23.13%` | `90.68%` | `2.94` | `5.70%` | `161` | rejected |
| `S2_max_stop_1_5pct` | `+22.23%` | `89.94%` | `2.83` | `5.79%` | `159` | rejected |
| `S3_max_stop_1pct` | `+15.87%` | `85.71%` | `2.16` | `7.36%` | `154` | harmful |
| `S4_hard_stop_2pct` | `+19.93%` | `89.31%` | `2.41` | `7.80%` | `159` | harmful |
| `S5_hard_stop_1_5pct` | `+18.48%` | `87.18%` | `2.27` | `8.43%` | `156` | harmful |
| `S6_hard_stop_1pct` | `+15.71%` | `84.21%` | `2.01` | `6.04%` | `152` | harmful |

### 4.2 Hypotheses Rejected By Data

Global hard stop is not a deployable fix. `S5_hard_stop_1_5pct` reduced some tail loss size, but it increased losing trades from `14` to `20`, gross loss from `-1141.99` to `-1685.47`, and MDD from `5.01%` to `8.43%`. Root cause: the large loss problem is concentrated in a few symbols; a global cap also cuts normal trades that would otherwise recover or reach TP.

Full `sim_light_take_profit` removal is rejected. `B1_disable_light_tp` dropped return, win rate, PF, and trade count. Light TP is part of the current high-win-rate structure; it can only be tested conditionally later.

Capacity expansion is not the current return bottleneck. `max_active_symbols=4/5` increased trades but did not improve return. More fills are not automatically higher-quality fills.

IOC/GTC work is deferred. The capacity tests show that adding more trade opportunities without improving signal/risk selection does not improve return in this window.

### 4.3 Hypothesis Supported By Data

Symbol selection is the strongest tested lever. `F2_blacklist_ada_fet` improved all major metrics at once:

| Metric | Baseline | F2 ADA+FET blacklist | Change |
|---|---:|---:|---:|
| Return | `+26.23%` | `+35.23%` | `+9.00 ppt` |
| Win rate | `91.36%` | `94.12%` | `+2.76 ppt` |
| Profit factor | `3.55` | `13.58` | `+10.03` |
| MDD | `5.01%` | `3.22%` | `-1.79 ppt` |
| Trades | `162` | `153` | `-9` |

The stop audit supports the same read: `5/14` losing trades exceeded a `1.5%` hard-loss threshold and contributed `-988.55` of gross loss, but the broad fix failed. This points to symbol-level risk control, not global stop tightening.

## 5. Deployment Candidate

Candidate config:

- `config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json`

Verified command:

```bash
python scripts/backtest_macd_v2.py --config config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json --strict-live-mode --simulate-live-close-layers --output-prefix output/backtest/candidate_blacklist_ada_fet_20260503 --initial-capital 10000
```

Verified result:

| Metric | Value |
|---|---:|
| Return | `+35.23%` |
| Win rate | `94.12%` |
| Profit factor | `13.58` |
| Max drawdown | `3.22%` |
| Trades | `153` |
| Orders filled | `88` |

Risk note: `PF=13.58` is excellent but should not be treated as stable until longer-window and cross-period validation pass. It may partly reflect ADA/FET being unusually bad in this 30d slice.

## 6. Immediate Action Plan

### 6.1 Run 60d Candidate Validation

Purpose: check whether the 30d ADA/FET blacklist result is overfit to one short window.

Current CLI supports `--start` and `--end`, not `--days`. Use an explicit 60d window based on available data coverage.

Example command:

```bash
python scripts/backtest_macd_v2.py --config config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json --strict-live-mode --simulate-live-close-layers --start 2026-03-04 --end 2026-05-03 --output-prefix output/backtest/candidate_blacklist_ada_fet_60d_20260503 --initial-capital 10000
```

Suggested pass criteria:

| Metric | Threshold |
|---|---:|
| Win rate | `>= 90%` |
| Return | `>= +60%` over 60d |
| PF | `>= 4.0` |
| MDD | `<= 7%` |
| Trades | enough sample to exceed the 30d trade count materially |

### 6.2 Validate ADA/FET Cross-Period Net PnL

Purpose: decide whether ADA/FET should be a hard blacklist or a dynamic risk tier.

Run period slices and inspect symbol attribution:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2025-10-01 --end 2025-12-31 --output-prefix output/backtest/period_q4_2025_baseline --initial-capital 10000
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2026-01-01 --end 2026-03-31 --output-prefix output/backtest/period_q1_2026_baseline --initial-capital 10000
```

Decision rule:

- If ADA/FET are net negative in at least `2/3` tested periods, promote hard blacklist.
- If ADA/FET are only negative in the current 30d window, prefer dynamic risk-tier throttle instead of permanent blacklist.
- If either symbol is structurally positive outside this window, do not hard-blacklist without a separate regime condition.

### 6.3 Deploy Only After Validation

If 60d validation and cross-period ADA/FET attribution both pass, promote only the symbol control:

```diff
   "fund_flow": {
     "symbol_blacklist": [
       "QNTUSDT",
       "... existing entries ...",
-      "APTUSDT"
+      "APTUSDT",
+      "ADAUSDT",
+      "FETUSDT"
     ]
   }
```

Do not bundle this deployment with light TP, capacity, IOC/GTC, global hard stop, or global `max_stop_loss_pct` changes.

## 7. Next Experiment Queue

Use `F2_blacklist_ada_fet` as the new baseline only after it passes the validation above.

### 7.1 SS Group: Symbol-Scoped Risk

Goal: reduce residual tail losses without harming the improved F2 baseline.

Candidates:

| Case | Scope | Test |
|---|---|---|
| `SS0_new_baseline` | ADA/FET blacklist | new reference |
| `SS1_xlm_control` | `XLMUSDT` | blacklist or tighter symbol cap |
| `SS2_sol_control` | `SOLUSDT` | tighter symbol cap only |
| `SS3_algo_jst_control` | `ALGOUSDT`, `JSTUSDT` | tighter symbol cap only |
| `SS4_all_tail_risk` | `XLM/SOL/ALGO/JST` | combined residual-tail test |

Implementation warning: symbol-scoped stop overrides should only be tested after the code path is verified to exist. If current code only supports global stop settings, do not encode fake `symbol_risk_overrides` in config and assume it works.

### 7.2 LT Group: Light TP Refinement

Light TP remains deferred. The only next valid line is conditional upgrade, not full disable.

Preferred later test:

- `LT6`: when `ADX > 30`, replace `sim_light_take_profit` with tiered TP.
- Compare against F2 baseline, not the original baseline.
- Reject if win rate falls below `90%`, PF falls below `5.0`, or MDD exceeds `5.5%`.

## 8. Closed Directions

Stop tracking these as primary fixes:

| Direction | Status | Reason |
|---|---|---|
| Global `hard_stop_loss_pct` | closed | S4/S5 worsened return, PF, win rate, and MDD |
| Global `max_stop_loss_pct` tightening | closed | S1/S2/S3 all underperformed baseline |
| Full `sim_light_take_profit` disable | closed | B1 damaged win rate and trade count |
| `max_active_symbols` expansion | closed | D1/D2 added trades without adding return |
| IOC/GTC rewrite | deferred | execution volume is not useful until symbol/risk selection is cleaner |

## 9. Files For Review

Backtest artifacts:

- `output/backtest/live_strict_30d_20260503_summary.json`
- `output/backtest/live_strict_30d_20260503_trades.csv`
- `output/backtest/live_strict_30d_20260503_equity_curve.csv`
- `output/backtest/live_strict_30d_20260503_pending_cancels.csv`
- `output/backtest/live_strict_30d_20260503_attribution_report.json`
- `output/backtest/live_strict_30d_20260503_attr_symbol_breakdown.csv`
- `output/backtest/live_strict_30d_20260503_attr_true_drawdown_breakdown.csv`
- `output/backtest/live_strict_30d_20260503_stop_loss_audit.json`
- `output/backtest/live_strict_30d_20260503_stop_loss_audit.csv`
- `output/backtest/ablation_20260503_min/ablation_results_20260503_151648.csv`
- `output/backtest/ablation_20260503_stop/ablation_results_20260503_183706.csv`
- `output/backtest/candidate_blacklist_ada_fet_20260503_summary.json`
- `output/backtest/candidate_blacklist_ada_fet_20260503_trades.csv`

Code/config:

- `config/trading_config_fund_flow.json`
- `config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json`
- `scripts/backtest_macd_v2.py`
- `scripts/audit_backtest_stop_losses.py`
- `scripts/run_macd_v2_return_ablation.py`
- `src/fund_flow/macd_strategy_v2.py`
- `src/fund_flow/decision_engine.py`
- `src/app/fund_flow_bot.py`

## 10. Final Validation And Deployment Decision

The ADA/FET symbol-control candidate was promoted after additional local validation. The production-sized change is limited to `fund_flow.symbol_blacklist += ["ADAUSDT", "FETUSDT"]`.

### 10.1 Validation Results

| Check | Baseline | ADA/FET blacklist | Decision |
|---|---:|---:|---|
| 30d return | `+26.23%` | `+35.23%` | pass |
| 30d win rate | `91.36%` | `94.12%` | pass |
| 30d PF | `3.55` | `13.58` | pass |
| 30d MDD | `5.01%` | `3.22%` | pass |
| 30d trades | `162` | `153` | pass |
| cache-range return, `2026-01-20 -> 2026-03-21` | `+23.51%` | `+32.33%` | pass |
| cache-range win rate | `91.03%` | `94.20%` | pass |
| cache-range PF | `3.32` | `13.15` | pass |
| cache-range MDD | `5.01%` | `3.22%` | pass |
| cache-range trades | `145` | `138` | pass |

Important limitation:

- Q4 2025 validation could not be completed from local cache. The command produced `0/26` available symbols after time-window filtering.
- The available extended validation is therefore cache-range validation, not independent Q4 regime validation.
- The cache-range result still supports promotion because the candidate improves return, win rate, PF, and MDD while reducing only `7` trades.

### 10.2 ADA/FET Attribution

| Window | ADAUSDT net PnL | FETUSDT net PnL | Combined read |
|---|---:|---:|---|
| `2026-01-20 -> 2026-03-21` cache range | `-263.95` | `-264.33` | both negative, combined `-528.28` |
| `2026-02-23 -> 2026-03-08` slice | `-301.69` | `+61.51` | ADA drove the loss |
| `2026-03-09 -> 2026-03-21` slice | `+23.31` | `-283.53` | FET drove the loss |

Read:

- The pair is persistently negative across the available cache range.
- The bad contribution alternates by symbol and period, which supports pair-level risk control more than a single-symbol-only blacklist.
- This is not proof for all future regimes; it is sufficient for the current strict-live deployment candidate.

### 10.3 Production Promotion

Production config changed:

- `config/trading_config_fund_flow.json`

Only expected field changed:

```diff
     "symbol_blacklist": [
       "QNTUSDT",
       "UNIUSDT",
       "NEARUSDT",
       "HBARUSDT",
       "XMRUSDT",
       "TRXUSDT",
       "ENAUSDT",
       "TAOUSDT",
       "LINKUSDT",
       "ARBUSDT",
       "LTCUSDT",
       "HYPEUSDT",
       "KASUSDT",
       "DOTUSDT",
       "FILUSDT",
       "XRPUSDT",
-      "APTUSDT"
+      "APTUSDT",
+      "ADAUSDT",
+      "FETUSDT"
     ],
```

Live gating path verified:

- `src/fund_flow/decision_engine.py` reads `fund_flow.symbol_blacklist`.
- Blacklisted symbols are mapped to `NO_TRADE`.

Production config verification command:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --output-prefix output/backtest/production_blacklist_ada_fet_20260503 --initial-capital 10000
```

Production verification result:

| Metric | Value |
|---|---:|
| Return | `+35.23%` |
| Win rate | `94.12%` |
| PF | `13.58` |
| MDD | `3.22%` |
| Trades | `153` |

Decision:

```text
Promote ADAUSDT and FETUSDT to production fund_flow.symbol_blacklist.
Do not bundle this with global stop, light TP, capacity, or IOC/GTC changes.
```

### 10.4 New Outputs

- `output/backtest/validation_60d_20260503/baseline_60d_cache_summary.json`
- `output/backtest/validation_60d_20260503/candidate_blacklist_ada_fet_60d_cache_summary.json`
- `output/backtest/validation_60d_20260503/baseline_60d_cache_ada_fet_symbol_pnl.csv`
- `output/backtest/validation_periods_20260503/baseline_slice_20260223_20260308_ada_fet_symbol_pnl.csv`
- `output/backtest/validation_periods_20260503/baseline_slice_20260309_20260321_ada_fet_symbol_pnl.csv`
- `output/backtest/production_blacklist_ada_fet_20260503_summary.json`
- `output/backtest/production_blacklist_ada_fet_20260503_trades.csv`
- `config/candidates/trading_config_fund_flow_post_ada_fet_20260503.json`
- `scripts/summarize_backtest_symbol_pnl.py`
- `tests/test_summarize_backtest_symbol_pnl.py`

Verification:

```bash
python -m py_compile scripts\backtest_macd_v2.py scripts\run_macd_v2_return_ablation.py scripts\audit_backtest_stop_losses.py scripts\summarize_backtest_symbol_pnl.py
pytest tests\test_summarize_backtest_symbol_pnl.py -q
```

Result:

```text
2 passed
py_compile passed
```

## 11. SS Group Results: Symbol-Scoped Risk

The SS group was run after promoting ADA/FET into the current production config. Therefore `00_baseline` below is the new production baseline, not the original pre-blacklist baseline.

Code support was implemented and verified before testing. The supported config path is:

```json
{
  "fund_flow": {
    "macd_mtf_strategy_v2": {
      "symbol_risk_tiers": {
        "max_stop_loss_pct_by_symbol": {
          "XLMUSDT": 0.010,
          "SOLUSDT": 0.015
        }
      }
    }
  }
}
```

The implementation only allows symbol-scoped caps to tighten the global `max_stop_loss_pct`; looser symbol values cannot relax the global stop. No fake top-level `symbol_risk_overrides` were used.

### 11.1 SS Ablation Results

| Case | Return | Win rate | PF | MDD | Trades | Delta vs new baseline | Read |
|---|---:|---:|---:|---:|---:|---:|---|
| `00_baseline` | `+35.23%` | `94.12%` | `13.58` | `3.22%` | `153` | reference | current production baseline |
| `SS1_xlm_stop_1pct` | `+35.14%` | `94.12%` | `13.23` | `3.28%` | `153` | `-0.09 ppt` | reject; XLM stop cap slightly worsens PF/MDD |
| `SS2_sol_stop_1_5pct` | `+35.23%` | `94.12%` | `13.58` | `3.22%` | `153` | `+0.00 ppt` | neutral; no measurable effect |
| `SS3_algo_jst_stop_1_5pct` | `+35.60%` | `94.08%` | `16.52` | `3.22%` | `152` | `+0.37 ppt` | supported but small; validation required |
| `SS4_tail_risk_stop_caps` | `+35.51%` | `94.08%` | `16.01` | `3.28%` | `152` | `+0.28 ppt` | weaker than SS3 because XLM cap hurts |
| `SS5_blacklist_xlm` | `+36.18%` | `94.67%` | `21.80` | `2.26%` | `150` | `+0.95 ppt` | strongest, but requires cross-period validation |

Run commands:

```bash
python scripts/run_macd_v2_return_ablation.py --cases 00_baseline --output-dir output/backtest/ablation_20260503_ss_single --timeout-seconds 1800
python scripts/run_macd_v2_return_ablation.py --cases SS1_xlm_stop_1pct SS2_sol_stop_1_5pct SS3_algo_jst_stop_1_5pct SS4_tail_risk_stop_caps SS5_blacklist_xlm --output-dir output/backtest/ablation_20260503_ss_remaining --timeout-seconds 1800
```

### 11.2 SS Decision

Do not deploy a broad SS stop-cap bundle. `SS4_tail_risk_stop_caps` is positive but weaker than the narrower `SS3`, and `SS1` shows that forcing XLM into a tighter stop cap is counterproductive.

The only symbol-scoped stop-cap candidate worth continuing is:

```text
ALGOUSDT max_stop_loss_pct = 1.5%
JSTUSDT  max_stop_loss_pct = 1.5%
```

Even that is a small improvement, not a production-sized change by itself. It should be validated on the same cache-range and slice framework before promotion.

The strongest next candidate is not a stop-cap variant; it is `SS5_blacklist_xlm`. Because it removes only `3` trades and improves return, win rate, PF, and MDD, it deserves the same validation path used for ADA/FET:

```text
1. Run cache-range validation against current production baseline.
2. Check XLMUSDT cross-period net PnL.
3. Promote only if XLM is consistently negative or tail-risk dominated outside this 30d window.
```

Updated priority:

1. Validate `SS5_blacklist_xlm` across periods before considering production.
2. Validate `SS3_algo_jst_stop_1_5pct` only as a secondary, smaller risk-control candidate.
3. Do not deploy `SS1`, `SS2`, or `SS4`.
4. Keep light TP, capacity, IOC/GTC, and global stop settings unchanged.

### 11.3 New SS Outputs

- `output/backtest/ablation_20260503_ss_single/ablation_results_20260503_231353.csv`
- `output/backtest/ablation_20260503_ss_single/ablation_results_20260503_231353.json`
- `output/backtest/ablation_20260503_ss_remaining/ablation_results_20260503_232728.csv`
- `output/backtest/ablation_20260503_ss_remaining/ablation_results_20260503_232728.json`
- `output/backtest/ablation_20260503_ss_remaining/runs/20260503_232728_05_SS5_blacklist_xlm_summary.json`
- `output/backtest/ablation_20260503_ss_remaining/runs/20260503_232728_05_SS5_blacklist_xlm_trades.csv`

Verification:

```bash
python -m py_compile src\fund_flow\macd_strategy_v2.py src\fund_flow\decision_engine.py scripts\backtest_macd_v2.py scripts\run_macd_v2_return_ablation.py scripts\summarize_backtest_symbol_pnl.py
pytest tests\test_backtest_review_followup.py tests\test_summarize_backtest_symbol_pnl.py -q
```

Result:

```text
26 passed
py_compile passed
```
