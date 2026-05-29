# 2026-05-14 昨晚21点后开仓稀少根因复盘

分析范围：北京时间 `2026-05-13 21:00` 至 `2026-05-14 12:15`，UTC `2026-05-13 13:00` 至 `2026-05-14 04:15`。
策略更新切点按用户描述取北京时间 `2026-05-14 02:55`，即 UTC `2026-05-13 18:55`。

## 核心结论

这次开仓数量没有明显增加，关键不是单一阈值没降够，而是两个层面同时失败：

1. **部署/运行态不一致持续存在**：昨晚 21:00 后仍出现 `probe_floor_rescue.shadow_mode=true` 的 `ENTRY_GATE_BLOCK`，说明至少到 UTC 15:45 / 北京时间 23:45，运行进程仍在用旧逻辑。
2. **真正生效后的主瓶颈转移到方向门控和 VWAP hard block**：最新 4H 仍几乎全 HOLD，主要死在 `4H无明确方向` 与 `vwap_hard_block`，而不是 final threshold。
3. **ExitGuard 不是多余优化，但执行层有新故障**：今天 12:00 BJ 左右 ExitGuard 触发 DOGE `CLOSE`，但 Binance 返回 `-2022 ReduceOnly Order is rejected`，说明退出信号守卫能触发，实际平仓路由仍需修。
4. **继续堆策略参数会扩大屎山**：当前最该做的是先把配置加载、日志字段、执行路由、回测切片对齐，再决定是否放开 neutral/RSI/VWAP。

## 昨晚 21:00 后全窗口

窗口：UTC `2026-05-13 13:00` - `2026-05-14 04:15`，北京时间 `2026-05-13 21:00` - `2026-05-14 12:15`。

### 调度与决策

- runtime 决策行：`1726`
- attribution decision：`1698`，execution：`1698`
- API cycles：`63`，allow_new_entries=True：`61`，ingestion_only：`2`
- 处理标的分布：`28/28=63`

runtime 决策类型：
| 项 | 次数 |
|---|---:|
| `HOLD` | 1723 |
| `SELL` | 1 |
| `BUY` | 1 |
| `CLOSE` | 1 |

attribution 决策类型：
| 项 | 次数 |
|---|---:|
| `hold` | 1695 |
| `sell` | 1 |
| `buy` | 1 |
| `close` | 1 |

execution 状态：
| 项 | 次数 |
|---|---:|
| `noop` | 1695 |
| `pending` | 2 |
| `error` | 1 |


### HOLD 主因

按 runtime `HOLD归因`：
| 项 | 次数 |
|---|---:|
| `vwap_hard_block` | 718 |
| `4H无明确方向` | 680 |
| `rsi_1h_direction_against_veto` | 134 |
| `rsi_15m_extreme_veto` | 53 |
| `信号评分低于阈值` | 49 |
| `rsi_1h_direction_flat_veto` | 32 |
| `vwap_score_filter` | 21 |
| `flip_bullish_sniper_no_trend_alignment` | 17 |
| `short_regime_guard` | 6 |
| `rsi_neutral_resume_short_disabled` | 5 |
| `-` | 5 |
| `green_bar_growing_short_adx_1h_range_filter` | 3 |

按 stage：
| 项 | 次数 |
|---|---:|
| `vwap` | 718 |
| `neutral_upgrade_gate` | 513 |
| `rsi_rhythm` | 219 |
| `neutral_upgrade_mode` | 167 |
| `threshold_check` | 49 |
| `vwap_score_filter` | 21 |
| `flip_bullish_sniper_gate` | 17 |
| `short_regime_guard` | 6 |
| `rsi_neutral_resume_short_disabled` | 5 |
| `final` | 5 |
| `green_bar_growing_short_adx_1h_range_filter` | 3 |


### ENTRY_GATE_BLOCK

- gate 总数：`8`
- `min_open_portion`：`8`
- `same_side_add_guard`：`0`
- min_open 中 shadow_mode=true：`4`，shadow_mode=false：`4`
| 项 | 次数 |
|---|---:|
| `min_open_portion` | 8 |

代表样例：
| UTC | 北京时间 | Symbol | gate | reason | value | score | shadow | line |
|---|---|---|---|---|---:|---:|---|---:|
| 2026-05-13 13:00 | 2026-05-13 21:00 | `ATOMUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7852 | `True` | 2844 |
| 2026-05-13 13:30 | 2026-05-13 21:30 | `SOLUSDT` | `min_open_portion` | `target_below_min_open` | 0.0008 | 0.8211 | `True` | 3218 |
| 2026-05-13 13:30 | 2026-05-13 21:30 | `ATOMUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7805 | `True` | 3292 |
| 2026-05-13 13:30 | 2026-05-13 21:30 | `ZROUSDT` | `min_open_portion` | `target_below_min_open` | 0.0003 | 0.6972 | `True` | 3390 |
| 2026-05-13 13:45 | 2026-05-13 21:45 | `SOLUSDT` | `min_open_portion` | `target_below_min_open` | 0.0420 | 0.8177 | `False` | 3436 |
| 2026-05-13 13:45 | 2026-05-13 21:45 | `ATOMUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7782 | `False` | 3510 |
| 2026-05-14 02:15 | 2026-05-14 10:15 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0009 | 0.6662 | `False` | 4201 |
| 2026-05-14 02:30 | 2026-05-14 10:30 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7021 | `False` | 4427 |


### 非 HOLD 与成交

- attribution 非 HOLD：`3`
| UTC | 北京时间 | Symbol | op | target | lev | reason |
|---|---|---|---|---:|---:|---|
| 2026-05-13 22:00 | 2026-05-14 06:00 | `ATOMUSDT` | `sell` | 0.1020 | 3 | `macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.63` |
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | `buy` | 0.1200 | 3 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.13` |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | `close` | 1.0000 | 1 | `EXIT_SIGNAL_GUARD_CLOSE: reverse signal confirmed 3 bars, mae=-0.88%, full close` |

- fills 去重：`8`
| UTC | 北京时间 | Symbol | 方向 | 价格 | 数量 | PnL |
|---|---|---|---|---:|---:|---:|
| 2026-05-13 22:00 | 2026-05-14 06:00 | `ATOMUSDT` | 卖出 | 2.053 | 14.55 | 0.0 |
| 2026-05-14 02:50 | 2026-05-14 10:50 | `ATOMUSDT` | 买入 | 2.011 | 14.55 | 0.6111 |
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | 买入 | 0.11335 | 311.0 | 0.0 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 55.0 | -0.05885 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 46.0 | -0.04922 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 120.0 | -0.1284 |


### ExitGuard / 执行错误

- ExitGuard 触发：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00` `DOGEUSDT` `CLOSE`: reverse signal confirmed 3 bars, mae=-0.88%, full close
- 执行失败详情：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00`: `place_market_order exception: Binance Error: {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}`

## 02:55 更新后

窗口：UTC `2026-05-13 18:55` - `2026-05-14 04:15`，北京时间 `2026-05-14 02:55` - `2026-05-14 12:15`。

### 调度与决策

- runtime 决策行：`1060`
- attribution decision：`1032`，execution：`1032`
- API cycles：`38`，allow_new_entries=True：`37`，ingestion_only：`1`
- 处理标的分布：`28/28=38`

runtime 决策类型：
| 项 | 次数 |
|---|---:|
| `HOLD` | 1057 |
| `SELL` | 1 |
| `BUY` | 1 |
| `CLOSE` | 1 |

attribution 决策类型：
| 项 | 次数 |
|---|---:|
| `hold` | 1029 |
| `sell` | 1 |
| `buy` | 1 |
| `close` | 1 |

execution 状态：
| 项 | 次数 |
|---|---:|
| `noop` | 1029 |
| `pending` | 2 |
| `error` | 1 |


### HOLD 主因

按 runtime `HOLD归因`：
| 项 | 次数 |
|---|---:|
| `4H无明确方向` | 573 |
| `vwap_hard_block` | 299 |
| `rsi_1h_direction_against_veto` | 63 |
| `信号评分低于阈值` | 41 |
| `rsi_15m_extreme_veto` | 31 |
| `flip_bullish_sniper_no_trend_alignment` | 17 |
| `vwap_score_filter` | 13 |
| `rsi_1h_direction_flat_veto` | 13 |
| `-` | 5 |
| `rsi_neutral_resume_short_disabled` | 2 |

按 stage：
| 项 | 次数 |
|---|---:|
| `neutral_upgrade_gate` | 419 |
| `vwap` | 299 |
| `neutral_upgrade_mode` | 154 |
| `rsi_rhythm` | 107 |
| `threshold_check` | 41 |
| `flip_bullish_sniper_gate` | 17 |
| `vwap_score_filter` | 13 |
| `final` | 5 |
| `rsi_neutral_resume_short_disabled` | 2 |


### ENTRY_GATE_BLOCK

- gate 总数：`2`
- `min_open_portion`：`2`
- `same_side_add_guard`：`0`
- min_open 中 shadow_mode=true：`0`，shadow_mode=false：`2`
| 项 | 次数 |
|---|---:|
| `min_open_portion` | 2 |

代表样例：
| UTC | 北京时间 | Symbol | gate | reason | value | score | shadow | line |
|---|---|---|---|---|---:|---:|---|---:|
| 2026-05-14 02:15 | 2026-05-14 10:15 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0009 | 0.6662 | `False` | 4201 |
| 2026-05-14 02:30 | 2026-05-14 10:30 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7021 | `False` | 4427 |


### 非 HOLD 与成交

- attribution 非 HOLD：`3`
| UTC | 北京时间 | Symbol | op | target | lev | reason |
|---|---|---|---|---:|---:|---|
| 2026-05-13 22:00 | 2026-05-14 06:00 | `ATOMUSDT` | `sell` | 0.1020 | 3 | `macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.63` |
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | `buy` | 0.1200 | 3 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.13` |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | `close` | 1.0000 | 1 | `EXIT_SIGNAL_GUARD_CLOSE: reverse signal confirmed 3 bars, mae=-0.88%, full close` |

- fills 去重：`8`
| UTC | 北京时间 | Symbol | 方向 | 价格 | 数量 | PnL |
|---|---|---|---|---:|---:|---:|
| 2026-05-13 22:00 | 2026-05-14 06:00 | `ATOMUSDT` | 卖出 | 2.053 | 14.55 | 0.0 |
| 2026-05-14 02:50 | 2026-05-14 10:50 | `ATOMUSDT` | 买入 | 2.011 | 14.55 | 0.6111 |
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | 买入 | 0.11335 | 311.0 | 0.0 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 55.0 | -0.05885 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 46.0 | -0.04922 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 120.0 | -0.1284 |


### ExitGuard / 执行错误

- ExitGuard 触发：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00` `DOGEUSDT` `CLOSE`: reverse signal confirmed 3 bars, mae=-0.88%, full close
- 执行失败详情：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00`: `place_market_order exception: Binance Error: {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}`

## 最新 4H

窗口：UTC `2026-05-14 00:15` - `2026-05-14 04:15`，北京时间 `2026-05-14 08:15` - `2026-05-14 12:15`。

### 调度与决策

- runtime 决策行：`473`
- attribution decision：`445`，execution：`445`
- API cycles：`16`，allow_new_entries=True：`16`，ingestion_only：`0`
- 处理标的分布：`28/28=16`

runtime 决策类型：
| 项 | 次数 |
|---|---:|
| `HOLD` | 471 |
| `BUY` | 1 |
| `CLOSE` | 1 |

attribution 决策类型：
| 项 | 次数 |
|---|---:|
| `hold` | 443 |
| `buy` | 1 |
| `close` | 1 |

execution 状态：
| 项 | 次数 |
|---|---:|
| `noop` | 443 |
| `pending` | 1 |
| `error` | 1 |


### HOLD 主因

按 runtime `HOLD归因`：
| 项 | 次数 |
|---|---:|
| `4H无明确方向` | 309 |
| `vwap_hard_block` | 63 |
| `rsi_1h_direction_against_veto` | 25 |
| `信号评分低于阈值` | 23 |
| `flip_bullish_sniper_no_trend_alignment` | 14 |
| `rsi_15m_extreme_veto` | 13 |
| `rsi_1h_direction_flat_veto` | 13 |
| `vwap_score_filter` | 7 |
| `-` | 3 |
| `rsi_neutral_resume_short_disabled` | 1 |

按 stage：
| 项 | 次数 |
|---|---:|
| `neutral_upgrade_gate` | 174 |
| `neutral_upgrade_mode` | 135 |
| `vwap` | 63 |
| `rsi_rhythm` | 51 |
| `threshold_check` | 23 |
| `flip_bullish_sniper_gate` | 14 |
| `vwap_score_filter` | 7 |
| `final` | 3 |
| `rsi_neutral_resume_short_disabled` | 1 |


### ENTRY_GATE_BLOCK

- gate 总数：`2`
- `min_open_portion`：`2`
- `same_side_add_guard`：`0`
- min_open 中 shadow_mode=true：`0`，shadow_mode=false：`2`
| 项 | 次数 |
|---|---:|
| `min_open_portion` | 2 |

代表样例：
| UTC | 北京时间 | Symbol | gate | reason | value | score | shadow | line |
|---|---|---|---|---|---:|---:|---|---:|
| 2026-05-14 02:15 | 2026-05-14 10:15 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0009 | 0.6662 | `False` | 4201 |
| 2026-05-14 02:30 | 2026-05-14 10:30 | `JSTUSDT` | `min_open_portion` | `target_below_min_open` | 0.0002 | 0.7021 | `False` | 4427 |


### 非 HOLD 与成交

- attribution 非 HOLD：`2`
| UTC | 北京时间 | Symbol | op | target | lev | reason |
|---|---|---|---|---:|---:|---|
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | `buy` | 0.1200 | 3 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.13` |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | `close` | 1.0000 | 1 | `EXIT_SIGNAL_GUARD_CLOSE: reverse signal confirmed 3 bars, mae=-0.88%, full close` |

- fills 去重：`7`
| UTC | 北京时间 | Symbol | 方向 | 价格 | 数量 | PnL |
|---|---|---|---|---:|---:|---:|
| 2026-05-14 02:50 | 2026-05-14 10:50 | `ATOMUSDT` | 买入 | 2.011 | 14.55 | 0.6111 |
| 2026-05-14 03:00 | 2026-05-14 11:00 | `DOGEUSDT` | 买入 | 0.11335 | 311.0 | 0.0 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 55.0 | -0.05885 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 45.0 | -0.04815 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 46.0 | -0.04922 |
| 2026-05-14 04:00 | 2026-05-14 12:00 | `DOGEUSDT` | 卖出 | 0.11228 | 120.0 | -0.1284 |


### ExitGuard / 执行错误

- ExitGuard 触发：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00` `DOGEUSDT` `CLOSE`: reverse signal confirmed 3 bars, mae=-0.88%, full close
- 执行失败详情：`1`
  - `2026-05-14 04:00` / `2026-05-14 12:00`: `place_market_order exception: Binance Error: {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}`

## 最新 4H 关键样例

### `4H无明确方向`

| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-05-14 00:15 | 2026-05-14 08:15 | `HYPEUSDT` | `neutral_upgrade_mode` | `green_bar_shrinking` | `flip_bullish` | -0.0600/0.6800 | 0.00% | 0.0078 | `-/-, raw=0.00` |
| 2026-05-14 00:15 | 2026-05-14 08:15 | `XRPUSDT` | `neutral_upgrade_gate` | `green_bar_shrinking` | `green_bar_shrinking` | 0.0000/0.6800 | 0.00% | 0.0081 | `-/-, raw=0.00` |
| 2026-05-14 00:15 | 2026-05-14 08:15 | `SOLUSDT` | `neutral_upgrade_gate` | `green_bar_shrinking` | `green_bar_shrinking` | 0.0000/0.6800 | 0.00% | 0.0103 | `-/-, raw=0.00` |
| 2026-05-14 00:15 | 2026-05-14 08:15 | `ADAUSDT` | `neutral_upgrade_mode` | `green_bar_shrinking` | `flip_bullish` | 0.0000/0.6800 | 0.00% | 0.0105 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 00:15 | 2026-05-14 08:15 | `BCHUSDT` | `neutral_upgrade_mode` | `green_bar_shrinking` | `red_bar_growing` | 0.0000/0.6800 | 0.00% | 0.0057 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 00:15 | 2026-05-14 08:15 | `XLMUSDT` | `neutral_upgrade_gate` | `green_bar_shrinking` | `green_bar_shrinking` | 0.0000/0.6800 | 0.00% | 0.0095 | `-/-, raw=0.00` |

### `vwap_hard_block`

| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-05-14 00:15 | 2026-05-14 08:15 | `POLUSDT` | `vwap` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -5.49% | 0.0116 | `-/-, raw=0.00` |
| 2026-05-14 00:30 | 2026-05-14 08:30 | `POLUSDT` | `vwap` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -5.54% | 0.0116 | `-/-, raw=0.00` |
| 2026-05-14 00:45 | 2026-05-14 08:45 | `POLUSDT` | `vwap` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -5.48% | 0.0116 | `-/-, raw=0.00` |
| 2026-05-14 01:00 | 2026-05-14 09:00 | `POLUSDT` | `vwap` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -5.57% | 0.0110 | `-/-, raw=0.00` |
| 2026-05-14 01:15 | 2026-05-14 09:15 | `TONUSDT` | `vwap` | `green_bar_growing` | `green_bar_growing` | 0.0000/0.6800 | -13.51% | 0.0197 | `-/-, raw=0.00` |
| 2026-05-14 01:15 | 2026-05-14 09:15 | `POLUSDT` | `vwap` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -5.29% | 0.0112 | `-/-, raw=0.00` |

### `rsi_15m_extreme_veto`

| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-05-14 00:15 | 2026-05-14 08:15 | `JSTUSDT` | `rsi_rhythm` | `red_bar_shrinking` | `green_bar_growing` | 0.0000/0.6800 | 3.68% | 0.0059 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 00:30 | 2026-05-14 08:30 | `JSTUSDT` | `rsi_rhythm` | `red_bar_shrinking` | `green_bar_growing` | 0.0000/0.6800 | 3.78% | 0.0059 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 00:45 | 2026-05-14 08:45 | `ATOMUSDT` | `rsi_rhythm` | `green_bar_growing` | `green_bar_growing` | 0.0000/0.6800 | -1.25% | 0.0156 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 00:45 | 2026-05-14 08:45 | `DOGEUSDT` | `rsi_rhythm` | `red_bar_growing` | `red_bar_growing` | 0.0000/0.6800 | 3.76% | 0.0154 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 00:45 | 2026-05-14 08:45 | `JSTUSDT` | `rsi_rhythm` | `red_bar_shrinking` | `green_bar_growing` | 0.0000/0.6800 | 3.81% | 0.0059 | `rsi_extreme_block/-, raw=0.00` |
| 2026-05-14 01:15 | 2026-05-14 09:15 | `RENDERUSDT` | `rsi_rhythm` | `green_bar_shrinking` | `red_bar_growing` | 0.0000/0.6800 | -3.57% | 0.0135 | `rsi_extreme_block/-, raw=0.00` |

### `rsi_1h_direction_flat_veto`

| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-05-14 01:00 | 2026-05-14 09:00 | `ATOMUSDT` | `rsi_rhythm` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -1.13% | 0.0139 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 01:30 | 2026-05-14 09:30 | `ATOMUSDT` | `rsi_rhythm` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -1.42% | 0.0145 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 01:45 | 2026-05-14 09:45 | `ATOMUSDT` | `rsi_rhythm` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -1.46% | 0.0145 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 02:00 | 2026-05-14 10:00 | `ATOMUSDT` | `rsi_rhythm` | `green_bar_growing` | `green_bar_shrinking` | 0.0000/0.6800 | -1.28% | 0.0123 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 02:15 | 2026-05-14 10:15 | `TRUMPUSDT` | `rsi_rhythm` | `green_bar_shrinking` | `flip_bullish` | 0.0000/0.6800 | -2.68% | 0.0122 | `rsi_1h_direction_block/-, raw=0.00` |
| 2026-05-14 02:30 | 2026-05-14 10:30 | `TRUMPUSDT` | `rsi_rhythm` | `green_bar_shrinking` | `flip_bullish` | 0.0000/0.6800 | -2.56% | 0.0123 | `rsi_1h_direction_block/-, raw=0.00` |

### `信号评分低于阈值`

| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-05-14 00:45 | 2026-05-14 08:45 | `TRUMPUSDT` | `threshold_check` | `green_bar_growing` | `green_bar_shrinking` | 0.6594/0.6900 | -3.59% | 0.0171 | `-/-, raw=0.21` |
| 2026-05-14 01:00 | 2026-05-14 09:00 | `HYPEUSDT` | `threshold_check` | `green_bar_shrinking` | `red_bar_growing` | 0.3811/0.6800 | -6.46% | 0.0072 | `-/-, raw=0.21` |
| 2026-05-14 01:00 | 2026-05-14 09:00 | `SUIUSDT` | `threshold_check` | `green_bar_shrinking` | `red_bar_growing` | 0.3830/0.6800 | -3.76% | 0.0128 | `-/-, raw=0.21` |
| 2026-05-14 01:00 | 2026-05-14 09:00 | `ETCUSDT` | `threshold_check` | `green_bar_shrinking` | `red_bar_growing` | 0.2401/0.6800 | -3.64% | 0.0102 | `-/-, raw=0.06` |
| 2026-05-14 01:00 | 2026-05-14 09:00 | `RENDERUSDT` | `threshold_check` | `green_bar_shrinking` | `red_bar_growing` | 0.3363/0.6600 | -3.78% | 0.0134 | `-/-, raw=0.00` |
| 2026-05-14 01:15 | 2026-05-14 09:15 | `HYPEUSDT` | `threshold_check` | `green_bar_shrinking` | `red_bar_growing` | 0.4118/0.6800 | -6.22% | 0.0076 | `-/-, raw=0.21` |


## 部署生效性判断

- runtime 中 `shadow_mode=true` 命中：`23`
- runtime 中 `shadow_mode=false` 命中：`4`
- runtime 中 `vwap_gate_action` 命中：`0`
- runtime 中 `probe_min_open` 命中：`0`

解释：如果最新 4H 已经跑新代码，但 runtime 没有打印 `vwap_gate_action`，可能只是日志格式未展示；但 `vwap_hard_block` 数量仍高，说明 ATR normalized gate 没有带来预期放行，或实际 ATR 阈值仍小于多数偏离。这里必须用更完整 metadata 或临时 debug 字段确认。

## 根因判断

### 1. 上次“增加开仓”的改动没有形成闭环

`total_compression_floor` 和 `probe_floor_rescue` 只影响已经到达 final sizing/min-open 的少数候选。最新窗口的大多数 HOLD 仍在 `neutral_upgrade_gate`、`vwap`、`rsi_rhythm` 阶段被归零，根本没有走到仓位压缩修复能发挥作用的位置。

### 2. min_open 不是唯一问题，但部署旧配置确实浪费了高分候选

昨晚 21:00 后出现多个 `signal_score >= 0.80`、`target=0.042` 的候选被 `min_open=0.06` 丢弃，同时 `probe_floor_rescue.shadow_mode=true`。这说明旧进程至少在该窗口前半段仍未加载 live rescue。

### 3. 最新 4H 主要不是 final threshold 问题

最新 4H 的 HOLD 主因集中在方向/VWAP/RSI 早期阶段。若只降 `entry_threshold`，只能影响已到 final 的候选，无法释放 `4H无明确方向`、`vwap_hard_block`、`rsi_15m_extreme_veto`。

### 4. VWAP ATR gate 需要重新核验，不应假设已经有效

最新 runtime 仍大量 `vwap_hard_block`。样例中 HYPE `dev=-7.31%`、`atr_pct=0.0068`，按 `4*ATR=2.72%` 仍会 hard block；这类不是固定 3% 一刀切的问题，而是趋势极端偏离确实超过 ATR block。对 SOL `dev=-4.57%`、`atr_pct=0.0069` 也同理。

### 5. ExitGuard 有效触发，但执行失败暴露了路由问题

`[ExitGuard] DOGEUSDT CLOSE` 后的平仓订单被 `ReduceOnly Order is rejected` 拒绝。这个问题不影响开仓数量，但会让风控修复在真实成交层失效，必须优先修。

## 给 Claude 的评审问题

1. 是否同意：当前开仓少的第一问题不是 threshold，而是 `4H无明确方向`、`vwap_hard_block`、`rsi_15m_extreme_veto` 的前置归零？
2. 是否同意：`total_compression_floor/probe_floor_rescue` 只能救 final 后的小仓位候选，不能解决大多数 early HOLD？
3. 是否应先加完整运行态配置指纹日志，例如启动时打印 config hash、probe shadow、VWAP gate mode、neutral/rsi/vwap 参数，而不是继续猜部署是否生效？
4. VWAP ATR gate 目前只把 3% 改成 `4*ATR`，但多数样例仍超过 `4*ATR`。是否应该引入 `PROBE_ONLY` 路径，还是保持 hard block 等回测？
5. `neutral_upgrade partial_confirm` 是否应该成为下一阶段主改动？日志显示 `4H无明确方向` 仍是最大 HOLD 来源。
6. `rsi_15m_extreme_veto` 是否过硬？最新 4H 它已经比 final threshold 更常见。
7. ExitGuard 平仓被 `-2022 ReduceOnly rejected` 打回，应优先审查 close 路由、positionSide、reduceOnly 参数与持仓同步。

## 建议下一步

不要继续无序叠参数。建议顺序：

1. 先修部署可观测性：每次启动和每个 cycle 首行打印 config hash 与关键参数。
2. 修 ExitGuard 平仓执行：复盘 DOGE `-2022`，保证退出守卫能真实平仓。
3. 增加完整 metadata 输出或 debug JSONL，至少保留 `vwap_gate_action`、`vwap_deviation_in_atr`、`neutral_upgrade_mode`、`rsi_veto_reason`。
4. 对最新 12H 做离线 counterfactual：把 `neutral_upgrade partial_confirm`、`VWAP PROBE_ONLY`、`rsi_15m_extreme_veto soft` 分别模拟，比较释放候选数量。
5. 只有确认候选质量后，再改 live 参数。

一句话：这两天的改动像是在下游补仓位和 min-open，但真正堵点在上游方向/VWAP/RSI 门控；而且部署和执行层又没有闭环，所以开仓数量自然不会上来。
