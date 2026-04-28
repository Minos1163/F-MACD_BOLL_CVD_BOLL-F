# MACD V2 30天回测归因与实盘开仓链路审计

- 日期: `2026-04-28`
- 回测窗口: `2026-02-23 -> 2026-03-24T23:59:59`
- 回测命令:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --start 2026-02-23 --end 2026-03-24T23:59:59
```

- 本轮最终工件:
  - `output/backtest/v2_summary_20260428_220648.json`
  - `output/backtest/v2_trades_20260428_220648.csv`
  - `output/backtest/v2_equity_curve_20260428_220648.csv`

## 1. 执行结论

这轮修复已经把系统从 `0` 交易的前端塌缩状态救回到可用吞吐:

- `total_trades = 119`
- `return_pct = +38.19%`
- `win_rate_pct = 81.51%`
- `profit_factor = 3.48`
- `signals_generated = 756`
- `candidate_entries = 495`
- `orders_submitted = 285`
- `orders_filled = 119`
- `max_drawdown_pct = 10.20%`

结论分成两层:

1. “前端漏斗锁死”已经解除，系统不再是 `0 -> 0 -> 0` 的静默状态。
2. 当前结果已经满足交易数 `90-120` 区间和 `80%+` 胜率要求，但仍有两个残留缺口:
   - `profit_factor = 3.48`，低于希望的 `4.0+`
   - `max_drawdown_pct = 10.20%`，略高于 `10%` 红线

这意味着本轮是“修复成功，但还有优化空间”，不是最终最优态。

## 2. 三个状态的对照

### 2.1 同日参考工件

来源: `output/backtest/v2_summary_20260428_082355.json`

| 指标 | 数值 |
|---|---:|
| total_trades | 96 |
| return_pct | 82.17% |
| win_rate_pct | 79.17% |
| profit_factor | 6.09 |
| candidate_entries | 390 |
| orders_submitted | 209 |
| orders_filled | 96 |

### 2.2 塌缩态

来源: `output/backtest/v2_summary_head_20260428_133557.json`

| 指标 | 数值 |
|---|---:|
| total_trades | 0 |
| return_pct | 0.00% |
| signals_generated | 0 |
| candidate_entries | 0 |
| orders_submitted | 0 |
| orders_filled | 0 |

### 2.3 本轮修复后最终结果

来源: `output/backtest/v2_summary_20260428_220648.json`

| 指标 | 数值 |
|---|---:|
| total_trades | 119 |
| return_pct | 38.19% |
| win_rate_pct | 81.51% |
| profit_factor | 3.48 |
| signals_generated | 756 |
| candidate_entries | 495 |
| orders_submitted | 285 |
| orders_filled | 119 |
| orders_canceled | 166 |
| max_drawdown_pct | 10.20% |

## 3. 根因归因

### 3.1 第一阶段根因: 前端信号塌缩

塌缩态的真实问题不是成交率，也不是容量，而是前端根本没有生成可执行信号。

关键证据:

- `signals_generated = 0`
- `candidate_entries = 0`
- `orders_submitted = 0`
- `orders_filled = 0`

### 3.2 直接触发塌缩的三个技术原因

1. `4H shrinking` 预翻转链路会把大量 bar 直接送进 `HOLD`
   - `shrink_pct = 0` 时也会触发 `preflip` 检查
   - `shrink_pct` 不足时也会直接 neutral，而不是回退到常规主方向解析

2. 回测/运行时配置传播不完整
   - `volume_vwap_both_low_*`
   - shrinking-state disable flag
   - `green_bar_growing_min_signal_score`
   这些字段在回测构建链路里并非全部真实生效

3. 评分阈值与仓位门槛组合成“数学不可成交”
   - 信号分数上限大约在 `0.69`
   - 原 profile 阈值在 `0.82~0.90`
   - `calculate_portion_multiplier()` 在 `<0.75` 时直接返回 `0.0`
   - 结果是即使恢复了 signal/candidate，也会被 `position_value_zero` 再次静默拦截

### 3.3 修复后的剩余瓶颈

当前已不再是前端完全锁死，但执行漏斗里仍有两个明显瓶颈:

- `pending_cancel_reasons.ioc_no_fill = 166`
- `capacity_full_precheck_candidates = 134`
- `capacity_competition_dropped = 73`

以及一个结构性弱项:

- `green_bar_growing: 34 笔, 67.65% 胜率, 盈亏 +331.34`

它仍然是当前 PF 被拉低的主要拖累项。

## 4. 本轮实际修复项

### 4.1 代码修复

文件: `src/fund_flow/macd_strategy_v2.py`

- 修复 `4H preflip` 零缩短误触发
  - `shrink_pct == 0` / `shrink_bars == 0` 时回退到常规主方向解析
- 修复 `4H preflip` 非充分缩短时的硬阻断
  - 不再把“缩短不足”直接当作最终 neutral
  - 只在满足真实 trial 条件时激活 preflip
- 下调仓位乘数地板
  - `score >= 0.80 -> 1.0`
  - `score >= 0.65 -> 0.8`
  - `score >= 0.55 -> 0.6`
  - `< 0.55 -> 0.0`

文件: `scripts/backtest_macd_v2.py`

- 补全 `green_bar_growing_min_signal_score` 的回测配置传播
- 补全前期 hotfix 字段传播:
  - `volume_vwap_both_low_min_score_vol`
  - `volume_vwap_both_low_min_vwap_score`
  - shrinking-state disable flag
  - `flip_bullish_cooling_hard_rsi_buffer`

文件: `src/fund_flow/decision_engine.py`

- 保持与回测构建链路同口径的配置传播
- 确保 live/backtest 元数据字段一致

### 4.2 回测 profile 热修口径

文件: `config/trading_config_fund_flow.json`

本轮运行使用默认 backtest profile:

- `fund_flow.backtest.default_profile = macd_v2_disable_short_filter`

该 profile 的关键覆盖项:

- 仓位上限
  - `default_target_portion = 0.35`
  - `max_symbol_position_portion = 0.35`
- 阈值
  - `default / min_signal_score = 0.68`
  - `red_bar_growing = 0.68`
  - `green_bar_growing = 0.69`
  - `flip_bearish = 0.66`
  - `flip_bullish = 0.64`
  - `soft_long_min_signal_score = 0.66`
  - `stable_bear_continuation_min_signal_score = 0.68`
  - `stable_bull_continuation_min_signal_score = 0.68`
  - `preflip_trial_min_signal_score = 0.66`
  - `trial_short_below_structure_promotion_min_signal_score = 0.68`
- VWAP/缩短态放行
  - `min_vwap_score_for_entry = 0.0`
  - `flip_bullish_min_vwap_score = 0.0`
  - `preflip_trial_min_vwap_score = 0.0`
  - `trial_short_below_structure_promotion_min_vwap_score = 0.0`
  - `stable_bear_continuation_min_vwap_score = 0.0`
  - `stable_bull_continuation_min_vwap_score = 0.0`
  - `flip_bearish_retest_reject_min_vwap_score = 0.0`
  - `volume_vwap_both_low_min_score_vol = 0.0`
  - `volume_vwap_both_low_min_vwap_score = 0.0`
  - `disable_green_bar_shrinking_short_dual_pressure_entries = false`
  - `disable_red_bar_shrinking_long_dual_support_entries = false`
- `flip_bullish_cooling`
  - `reject_if_1h_rsi_above = 75`
  - `reject_if_15m_no_spring_and_rsi_high = false`

## 5. 当前真实门槛与打分

### 5.1 基础权重

当前 live/base 策略权重:

| 项 | 权重 |
|---|---:|
| `weight_4h_direction` | 0.40 |
| `weight_1h_direction` | 0.15 |
| `weight_4h_enhancement` | 0.10 |
| `weight_rsi_rhythm` | 0.30 |
| `weight_vwap` | 0.05 |
| `weight_15m_entry` | 0.00 |
| `weight_volume` | 0.10 |

核心事实:

- `VWAP` 权重只有 `0.05`
- `15m` 已不再有独立权重层
- `RSI rhythm` 是主要节奏层

### 5.2 分数聚合

总分在 `macd_strategy_v2.py::analyze()` 内按下列主干聚合:

```text
score
= score_4h
+ score_1h
+ score_4h_enhancement
+ score_rsi_rhythm_weighted
+ score_vwap
+ score_volume
+ spring_override / sovereign bonus
```

### 5.3 当前回测 profile 有效阈值

本轮真实有效阈值不是 base config，而是 backtest profile 覆盖后的值:

| 信号族/路径 | 阈值 |
|---|---:|
| default | 0.68 |
| red_bar_growing | 0.68 |
| green_bar_growing | 0.69 |
| flip_bearish | 0.66 |
| flip_bullish | 0.64 |
| soft_long override | 0.66 |
| preflip trial | 0.66 |
| short-below-structure promotion | 0.68 |
| stable continuation | 0.68 |

### 5.4 当前分数上限与策略含义

这轮排查里最关键的发现之一:

- 当前信号实际得分天花板大约在 `0.69`
- 因此原来的 `0.82~0.90` 阈值会把系统推入“数学上不可能成交”的状态

也就是说，本轮并不是“简单放量”，而是先把阈值修回到与当前真实打分尺度匹配的区间。

## 6. 当前实盘开仓链路

### 6.1 Bot 主循环

文件: `src/app/fund_flow_bot.py`

主链路:

1. `_run_cycle_impl(...)`
2. `_prepare_cycle_context(...)`
3. 逐 symbol 组装行情/持仓/风控上下文
4. 调用 `FundFlowDecisionEngine.decide(...)`
5. 通过 bot 侧方向/频控/持仓 gate
6. `_execute_and_log_decision(...)`
7. 执行器下单
8. 保护单 / 保本 / 减仓 / 平仓

### 6.2 决策引擎

文件: `src/fund_flow/decision_engine.py`

核心入口:

- `_decide_macd_v2_strategy(...)`

主过程:

1. 取 `15m/1h/4h` 数据
2. 过 `TimeWindowFilter`
3. 构造 MACD / BOLL / VWAP / RSI / volume / CVD 输入
4. 调用 `macd_v2_engine.analyze(...)`
5. 把策略信号映射为 `BUY / SELL / HOLD / CLOSE`
6. 注入 execution metadata
7. 经过 regime gating 和方向锁

### 6.3 策略 analyze 主顺序

文件: `src/fund_flow/macd_strategy_v2.py`

真实顺序:

1. 计算 `1H MACD` 方向
2. 计算 `4H MACD` 方向
3. 构造 `4H shrinking / stable trend` 上下文
4. 决定 `trade_direction`
   - 正常 `4H primary`
   - `preflip trial`
   - `stable continuation`
   - `neutral_upgrade`
5. BOLL 结构检查
6. VWAP 打分与 `3% hard block`
7. 15m/RSI 节奏检查
8. `flip_bullish` sniper/cooling/strict
9. RSI-MACD conflict / sovereign / spring override
10. 总分聚合
11. 阈值检查
12. 杠杆、仓位、止损、执行 metadata

## 7. 当前仓位与执行逻辑

### 7.1 当前回测运行时仓位口径

来源: `runtime_limits`

| 项 | 当前值 |
|---|---:|
| `max_positions` | 3 |
| `default_target_portion` | 0.35 |
| `max_symbol_position_portion` | 0.35 |
| `min_open_portion` | 0.06 |
| `reserve_pct` | 0.20 |
| `min_leverage` | 2 |
| `default_leverage` | 3 |
| `max_leverage` | 4 |

### 7.2 仓位乘数

当前 `calculate_portion_multiplier(score)`:

| 分数段 | 仓位乘数 |
|---|---:|
| `>= 0.90` | 1.2 |
| `>= 0.80` | 1.0 |
| `>= 0.65` | 0.8 |
| `>= 0.55` | 0.6 |
| `< 0.55` | 0.0 |

这是本轮最关键的执行修复之一。没有这条修复，即使候选恢复，仍会因为 `position_value_zero` 无法下单。

### 7.3 执行路由

当前回测与 live 使用同一条执行 metadata 语义:

- 普通信号:
  - `IOC`
  - `limit`
- priority signal:
  - 仍走 priority metadata
  - 当前这轮大部分成交并未走 VIP 分支
- 本轮执行漏斗:
  - `orders_submitted = 285`
  - `orders_filled = 119`
  - `orders_canceled = 166`
  - `ioc_no_fill = 166`
  - `wsr = 0.335`

说明当前吞吐恢复后，第二大问题已经转移成:

- `IOC` 取消仍然偏高

## 8. 当前风控链

本轮没有改动以下核心风控:

- `VWAP 3% hard block`
- `stop_loss_pct = 0.50%`
- `breakeven_enabled = true`
- `breakeven_trigger_pnl_ratio = 0.80%`
- `breakeven_lock_ratio = 0.20%`
- `max_positions = 3`
- `reserve_pct = 20%`
- 账户冷却/连续亏损控制

当前风险结果:

- `max_drawdown_value = 1335.96`
- `max_drawdown_pct = 10.20%`
- 回撤区间:
  - `2026-02-28 17:30:00 -> 2026-03-04 00:30:00`

## 9. 本轮结果怎么理解

### 9.1 已经解决的问题

- 不再是 `0` 交易塌缩
- `candidate -> submitted -> filled` 漏斗恢复
- 交易数恢复到目标区间: `119`
- 胜率恢复到目标区间: `81.5%`
- 收益率恢复到目标区间: `38.19%`

### 9.2 仍然没有解决的问题

- `flip_bullish` 本轮仍然没有恢复成主要盈利引擎
- `green_bar_growing` 仍然是当前最弱信号家族
- `profit_factor = 3.48`，未回到 `4+`
- `max_drawdown_pct = 10.20%`，略高于 `10%`
- `IOC` 取消率依旧高

### 9.3 对 Claude / DeepSeek 最有价值的问题

建议重点评审这三件事:

1. `green_bar_growing` 是否还应继续存在于当前强度下
   - 它提供了吞吐，但显著拖累 PF
2. `flip_bullish` 为什么在吞吐恢复后仍然缺席
   - 当前结构恢复的是“总吞吐”，不是“多头核心 Alpha”
3. `IOC no fill` 是否应该针对高分单改为更积极的成交路径
   - 当前 `orders_submitted -> orders_filled = 119 / 285`
   - 执行层仍有明显优化空间

## 10. 一句话总结

**这轮修复已经完成了“从 0 笔回测塌缩恢复到 119 笔可交易状态”的核心任务，当前 HEAD 的真实状态是：吞吐恢复、胜率合格、收益合格，但 PF 仍偏低、回撤略高、`flip_bullish` 仍未回归主引擎。后续优化应从削弱 `green_bar_growing` 噪音、恢复 `flip_bullish` 产能、以及降低 `IOC no fill` 三个方向继续推进。**
