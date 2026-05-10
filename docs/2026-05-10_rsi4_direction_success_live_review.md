# RSI(4) Direction Success Live Review

Generated: `2026-05-10 10:35:49 CST`

## Window

- Beijing: `2026-05-08 19:00:00+08:00` to `2026-05-10 09:30:13.636670+08:00`
- UTC: `2026-05-08 11:00:00+00:00` to `2026-05-10 01:30:13.636670+00:00`

## Data Quality

- RSI fields were not available directly in compacted `fund_flow_attribution.jsonl` metadata.
- RSI(4) was recomputed from per-symbol attribution `context.price` snapshots.
- This is a close-like reconstruction, not exchange OHLC RSI. Buckets with small sample counts should not be overfit.

## Executive Summary

- Decision events analyzed: `3254`
- Entry decisions: `51`
- Non-DCA entry decisions: `49`
- Deduped fills in window: `153`
- Matched closed non-DCA entries: `44`
- Matched closed PnL: `6.732727 USDT`
- Matched win rate: `63.64%`
- Strongest timeframe by absolute matched PnL split: `1h`
- Flat-threshold read: 1h: flat 33.3% vs non-flat 65.9%; 4h: flat/non-flat 样本偏少; 15m: flat/non-flat 样本偏少

## RSI Side Alignment Summary

Aligned means RSI direction supports the trade side: `up` for LONG, `down` for SHORT. Opposed means RSI points against the trade side.

| timeframe | alignment | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15m | aligned | 36 | 23 | 13 | 63.89% | 7.370647 | 0.204740 |
| 15m | flat | 1 | 1 | 0 | 100.00% | 0.011440 | 0.011440 |
| 15m | opposed | 7 | 4 | 3 | 57.14% | -0.649360 | -0.092766 |
| 1h | aligned | 29 | 22 | 7 | 75.86% | 7.403788 | 0.255303 |
| 1h | flat | 3 | 1 | 2 | 33.33% | -1.237405 | -0.412468 |
| 1h | opposed | 12 | 5 | 7 | 41.67% | 0.566344 | 0.047195 |
| 4h | aligned | 35 | 25 | 10 | 71.43% | 7.562394 | 0.216068 |
| 4h | opposed | 9 | 3 | 6 | 33.33% | -0.829667 | -0.092185 |

Read: 1H alignment is the main check for whether the proposed 1H anchor has empirical support in this slice; 15m should be treated as trigger confirmation only when it does not fight 1H/4H.

## Matched Entry Outcomes By RSI Direction

### 1H RSI Direction
| rsi_1h_dir | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up | LONG | 19 | 17 | 2 | 89.47% | 8.106790 | 0.426673 |
| down | SHORT | 10 | 5 | 5 | 50.00% | -0.703002 | -0.070300 |
| up | SHORT | 7 | 3 | 4 | 42.86% | 1.326864 | 0.189552 |
| down | LONG | 5 | 2 | 3 | 40.00% | -0.760520 | -0.152104 |
| flat | SHORT | 2 | 1 | 1 | 50.00% | 0.145240 | 0.072620 |
| flat | LONG | 1 | 0 | 1 | 0.00% | -1.382645 | -1.382645 |

### 4H RSI Direction
| rsi_4h_dir | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up | LONG | 23 | 19 | 4 | 82.61% | 8.172330 | 0.355319 |
| down | SHORT | 12 | 6 | 6 | 50.00% | -0.609936 | -0.050828 |
| up | SHORT | 7 | 3 | 4 | 42.86% | 1.379038 | 0.197005 |
| down | LONG | 2 | 0 | 2 | 0.00% | -2.208705 | -1.104353 |

### 15m RSI Direction
| rsi_15m_dir | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up | LONG | 22 | 18 | 4 | 81.82% | 6.938085 | 0.315367 |
| down | SHORT | 14 | 5 | 9 | 35.71% | 0.432562 | 0.030897 |
| up | SHORT | 4 | 3 | 1 | 75.00% | 0.325100 | 0.081275 |
| down | LONG | 3 | 1 | 2 | 33.33% | -0.974460 | -0.324820 |
| flat | SHORT | 1 | 1 | 0 | 100.00% | 0.011440 | 0.011440 |

### 1H + 4H Combo
| rsi_1h_4h_combo | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up/up | LONG | 19 | 17 | 2 | 89.47% | 8.106790 | 0.426673 |
| down/down | SHORT | 8 | 4 | 4 | 50.00% | -0.733120 | -0.091640 |
| up/up | SHORT | 5 | 2 | 3 | 40.00% | 1.348920 | 0.269784 |
| down/up | LONG | 4 | 2 | 2 | 50.00% | 0.065540 | 0.016385 |
| down/up | SHORT | 2 | 1 | 1 | 50.00% | 0.030118 | 0.015059 |
| flat/down | SHORT | 2 | 1 | 1 | 50.00% | 0.145240 | 0.072620 |
| up/down | SHORT | 2 | 1 | 1 | 50.00% | -0.022056 | -0.011028 |
| down/down | LONG | 1 | 0 | 1 | 0.00% | -0.826060 | -0.826060 |
| flat/down | LONG | 1 | 0 | 1 | 0.00% | -1.382645 | -1.382645 |

### 1H + 15m Combo
| rsi_1h_15m_combo | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up/up | LONG | 19 | 17 | 2 | 89.47% | 8.106790 | 0.426673 |
| down/down | SHORT | 9 | 4 | 5 | 44.44% | -0.714442 | -0.079382 |
| up/down | SHORT | 4 | 1 | 3 | 25.00% | 1.297864 | 0.324466 |
| down/down | LONG | 3 | 1 | 2 | 33.33% | -0.974460 | -0.324820 |
| up/up | SHORT | 3 | 2 | 1 | 66.67% | 0.029000 | 0.009667 |
| down/up | LONG | 2 | 1 | 1 | 50.00% | 0.213940 | 0.106970 |
| down/flat | SHORT | 1 | 1 | 0 | 100.00% | 0.011440 | 0.011440 |
| flat/down | SHORT | 1 | 0 | 1 | 0.00% | -0.150860 | -0.150860 |
| flat/up | LONG | 1 | 0 | 1 | 0.00% | -1.382645 | -1.382645 |
| flat/up | SHORT | 1 | 1 | 0 | 100.00% | 0.296100 | 0.296100 |

### 15m + 1H + 4H Combo
| rsi_3tf_combo | side | entries | wins | losses | win_rate | pnl | avg_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| up/up/up | LONG | 19 | 17 | 2 | 89.47% | 8.106790 | 0.426673 |
| down/down/down | SHORT | 7 | 3 | 4 | 42.86% | -0.744560 | -0.106366 |
| down/down/up | LONG | 3 | 1 | 2 | 33.33% | -0.974460 | -0.324820 |
| down/up/up | SHORT | 3 | 1 | 2 | 33.33% | 1.383920 | 0.461307 |
| down/down/up | SHORT | 2 | 1 | 1 | 50.00% | 0.030118 | 0.015059 |
| up/up/up | SHORT | 2 | 1 | 1 | 50.00% | -0.035000 | -0.017500 |
| down/flat/down | SHORT | 1 | 0 | 1 | 0.00% | -0.150860 | -0.150860 |
| down/up/down | SHORT | 1 | 0 | 1 | 0.00% | -0.086056 | -0.086056 |
| flat/down/down | SHORT | 1 | 1 | 0 | 100.00% | 0.011440 | 0.011440 |
| up/down/down | LONG | 1 | 0 | 1 | 0.00% | -0.826060 | -0.826060 |
| up/down/up | LONG | 1 | 1 | 0 | 100.00% | 1.040000 | 1.040000 |
| up/flat/down | LONG | 1 | 0 | 1 | 0.00% | -1.382645 | -1.382645 |
| up/flat/down | SHORT | 1 | 1 | 0 | 100.00% | 0.296100 | 0.296100 |
| up/up/down | SHORT | 1 | 1 | 0 | 100.00% | 0.064000 | 0.064000 |

## Forward Return Direction Check

This auxiliary view uses all decision snapshots with non-flat weighted RSI consensus and checks whether price moved in the RSI consensus direction.

| horizon | rsi_consensus_direction | samples | correct | success_rate | avg_forward_return |
| --- | --- | --- | --- | --- | --- |
| 1h | SHORT | 1427 | 863 | 60.48% | -0.001698 |
| 1h | LONG | 1362 | 800 | 58.74% | 0.003467 |
| 4h | SHORT | 1298 | 722 | 55.62% | -0.000061 |
| 4h | LONG | 1264 | 764 | 60.44% | 0.008478 |
| 8h | SHORT | 1153 | 610 | 52.91% | 0.002287 |
| 8h | LONG | 1094 | 684 | 62.52% | 0.011848 |

## Top Matched Loss Cases

| symbol | side | ts | matched_realized_pnl | rsi_15m_dir | rsi_1h_dir | rsi_4h_dir | rsi_weighted_direction_score | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PUMPUSDT | LONG | 2026-05-08 22:15:12.973638+00:00 | -1.382645 | up | flat | down | -0.100000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| ZROUSDT | LONG | 2026-05-09 08:15:13.154659+00:00 | -0.826060 | up | down | down | -0.600000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| MORPHOUSDT | SHORT | 2026-05-09 09:45:12.731597+00:00 | -0.825830 | down | down | down | -1.000000 | macd_v2_short_1h_flip_bearish_15m__vwap_0.25 |
| ALGOUSDT | LONG | 2026-05-08 22:00:13.631126+00:00 | -0.773110 | down | down | up | -0.400000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| VETUSDT | LONG | 2026-05-08 11:30:13.162678+00:00 | -0.295952 | up | up | up | 1.000000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| POLUSDT | LONG | 2026-05-08 11:15:13.246051+00:00 | -0.235350 | down | down | up | -0.400000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| TRUMPUSDT | LONG | 2026-05-09 01:45:12.937188+00:00 | -0.204100 | up | up | up | 1.000000 | macd_v2_long_1h_red_bar_growing_15m__vwap_0.25 |
| TONUSDT | SHORT | 2026-05-08 11:45:12.782197+00:00 | -0.150860 | down | flat | down | -0.500000 | macd_v2_short_1h_green_bar_growing_15m__vwap_1.00 |
| ALGOUSDT | SHORT | 2026-05-08 18:00:13.515445+00:00 | -0.146430 | down | up | up | 0.600000 | macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume_vwap_1.00 |
| VETUSDT | SHORT | 2026-05-08 13:00:13.835874+00:00 | -0.086056 | down | up | down | 0.000000 | macd_v2_short_1h_flip_bearish_15m__vwap_0.69 |

## Bottom Line

Forward-return diagnostics are strongest for 8h LONG consensus at 62.52% success. Matched entry buckets should be interpreted with their sample counts. In matched entries, 1h RSI side-alignment was strongest (75.86% win rate, 7.4038 USDT PnL).
