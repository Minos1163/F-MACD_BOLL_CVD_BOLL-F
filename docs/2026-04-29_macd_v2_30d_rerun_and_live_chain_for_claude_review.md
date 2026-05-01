# MACD V2 30天复跑归因与实盘链路审阅材料

- 日期: `2026-04-29`
- 用途: 给 Claude 做策略/实盘链路评审
- 回测命令:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --start 2026-02-23 --end 2026-03-24T23:59:59
```

- 本次新工件:
  - `output/backtest/v2_summary_20260429_210230.json`
  - `output/backtest/v2_trades_20260429_210230.csv`
  - `output/backtest/v2_equity_curve_20260429_210230.csv`

## 1. Fresh 30天结果

| 指标 | 数值 |
|---|---:|
| `return_pct` | `+44.37%` |
| `final_capital` | `$14,437.36` |
| `total_trades` | `94` |
| `win_rate_pct` | `87.23%` |
| `profit_factor` | `7.20` |
| `max_drawdown_pct` | `6.12%` |
| `signals_generated` | `766` |
| `candidate_entries` | `558` |
| `orders_submitted` | `224` |
| `orders_filled` | `94` |
| `orders_canceled` | `130` |
| `fill_rate_submitted` | `41.96%` |
| `wsr` | `23.30%` |

## 2. 最重要的四个结论

1. 这轮 `+44.37%` 的月收益确实没有把 alpha 吃满。
   当前收益主要靠 `16` 笔 `4h_shrink_exit` 的趋势单撑起来，不是靠大多数赢单持续放大利润。

2. 大多数赢单被保本锁盈切得非常小。
   在 `83` 笔盈利单里，有 `67` 笔盈利幅度 `<= 0.25%`，占盈利单 `80.72%`。

3. “是不是保本盈利太快导致盈利太小”的答案是: `是，且证据很强`。
   `56` 笔明显的 breakeven-like 赢单以 `~0.20%` 锁盈离场，只贡献了 `$514.91`，而 `16` 笔 `4h_shrink_exit` 却贡献了 `$4,846.70`。

4. 这份 `44.37%` 回测结果不是严格的 live 参数回测。
   `scripts/backtest_macd_v2.py` 会自动应用 backtest profile `macd_v2_disable_short_filter`；`src/app/fund_flow_bot.py` 不会套这个 profile。也就是说，回测有效参数和 live 实盘参数目前不是一套。

## 3. 收益归因

### 3.1 按信号族归因

| 信号族 | 笔数 | 胜率 | PnL |
|---|---:|---:|---:|
| `red_bar_growing` | `72` | `86.11%` | `$+3,187.85` |
| `flip_bearish` | `18` | `100.00%` | `$+1,555.09` |
| `flip_bullish` | `4` | `50.00%` | `$-79.02` |

解释:

- 组合主收益已经变成 `red_bar_growing + flip_bearish`。
- `flip_bullish` 当前不是补充 alpha，而是在拖后腿。
- 如果要追求比 `44%` 更高的月收益，最直接的路不是继续抬高胜率，而是让更多优质单从 `0.2%` 小盈利，成长为 `2%~10%` 的 runner。

### 3.2 按平仓原因归因

| 平仓原因 | 笔数 | 胜率 | 总PnL | 平均PnL | 平均PnL% | 平均持仓分钟 |
|---|---:|---:|---:|---:|---:|---:|
| `4h_shrink_exit` | `16` | `100.00%` | `$+4,846.70` | `$302.92` | `5.21%` | `1440.94` |
| `stop_loss_intrabar` | `78` | `84.62%` | `$-182.77` | `$-2.34` | `0.03%` | `173.85` |

这是本轮最关键的归因结论:

- 整个月的净收益几乎全部来自 `4h_shrink_exit`。
- `stop_loss_intrabar` 这一大类虽然胜率看起来不低，但整体 `净贡献是负的`。
- 也就是说，绝大多数“看起来赢了”的单，本质上只是被保本/移动止损提前扫出去，没能形成真正的利润堆积。

### 3.3 保本锁盈是否切得太快

从 `v2_trades_20260429_210230.csv` 直接统计:

- 盈利单总数: `83`
- 盈利幅度 `<= 0.25%` 的单数: `67`
- 占盈利单比例: `80.72%`
- 这 `67` 笔合计只贡献: `$568.77`
- 其中明显接近 `0.20%` 锁盈的 breakeven-like 赢单: `56`
- 这 `56` 笔只贡献: `$514.91`
- 其平均持仓时间: `155.63` 分钟

对照组:

- `4h_shrink_exit` 只有 `16` 笔
- 却贡献了 `$4,846.70`
- 平均单笔盈利 `5.21%`

因此当前结构不是“胜率不够高”，而是:

- 大量单子只拿到 `0.2%` 左右的小肉
- 真正把钱赚出来的是极少数长持有趋势单

如果你的目标是把 `44%` 再往上推，优先级应该是:

1. 让更多 `red_bar_growing / flip_bearish` 单子活到 `4h_shrink_exit`
2. 降低过早 breakeven 对趋势单的切割
3. 再考虑额外扩容成交率

### 3.4 最大盈利单 / 最大亏损单

本轮最大盈利单:

- `ICPUSDT long`, `red_bar_growing`, `4h_shrink_exit`, `+14.49%`, `$+971.91`
- `FETUSDT long`, `red_bar_growing`, `4h_shrink_exit`, `+9.57%`, `$+702.42`
- `WLDUSDT long`, `red_bar_growing`, `4h_shrink_exit`, `+11.06%`, `$+575.15`

本轮最大亏损单:

- `JSTUSDT long`, `red_bar_growing`, `stop_loss_intrabar`, `-2.34%`, `$-229.21`
- `ALGOUSDT long`, `red_bar_growing`, `stop_loss_intrabar`, `-2.94%`, `$-228.50`
- `PUMPUSDT long`, `flip_bullish`, `stop_loss_intrabar`, `-2.55%`, `$-130.67`

观察:

- 最大盈利单全部来自趋势 runner。
- 最大亏损单仍主要来自 `stop_loss_intrabar`。
- `flip_bullish` 不但成交少，而且亏损质量并不好。

### 3.5 执行漏斗归因

| 漏斗阶段 | 数值 |
|---|---:|
| `signals_generated` | `766` |
| `candidate_entries` | `558` |
| `orders_submitted` | `224` |
| `orders_filled` | `94` |
| `orders_canceled` | `130` |
| `capacity_full_precheck_candidates` | `116` |
| `capacity_competition_dropped` | `71` |
| `pending_cancel_reasons.ioc_no_fill` | `130` |

解释:

- 当前不是“信号不够”问题。
- 当前也不只是“阈值过高”问题，因为候选已经有 `558`。
- 主要损耗在两层:
  - 容量竞争: `71`
  - IOC 不成交: `130`

但要注意:

- `market_fallback_attempted = 0`
- `market_fallback_filled = 0`

说明这次结果还不是靠“IOC 后市价补单”抬起来的。

### 3.6 `flip_bullish` 的真实问题

从 summary 里的 funnel 字段:

| 字段 | 数值 |
|---|---:|
| `flip_bullish_seen` | `2652` |
| `flip_bullish_passed_threshold` | `6` |
| `flip_bullish_blocked_by_sniper` | `396` |
| `flip_bullish_blocked_by_cooling` | `0` |
| `flip_bullish_blocked_by_capacity` | `1` |
| `flip_bullish_ioc_canceled` | `1` |
| 实际成交 | `4` |

解释:

- `flip_bullish` 的主问题不是 cooling。
- 主问题是上游总分太难过线，外加 sniper 继续大量拦截。
- 这也是为什么它现在只剩 `4` 笔成交且总收益为负。

## 4. 这次回测和 live 不是同一套参数

这是给 Claude 评审时最需要先看到的点。

### 4.1 backtest script 会自动套 profile

`scripts/backtest_macd_v2.py` 在运行时会调用:

- `apply_backtest_profile(...)`
- 并读取 `fund_flow.backtest.default_profile`

本次 fresh 回测实际生效的 profile 是:

- `macd_v2_disable_short_filter`

### 4.2 live bot 不会套这个 backtest profile

`src/app/fund_flow_bot.py` 没有 `apply_backtest_profile` 这条链。

所以:

- 这份 `+44.37%` 不是“当前 live 原样参数”的回测
- 而是“当前 runtime config + backtest profile 覆盖”的回测

### 4.3 live base 阈值 vs backtest effective 阈值

| 路径 | live base | backtest effective |
|---|---:|---:|
| `default/min_signal_score` | `0.85` | `0.68` |
| `soft_long` | `0.85` | `0.66` |
| `red_bar_growing` | `0.90` | `0.68` |
| `green_bar_growing` | `0.87` | `0.69` |
| `flip_bearish` | `0.84` | `0.66` |
| `flip_bullish` | `0.82` | `0.64` |

### 4.4 live 仓位 vs backtest effective 仓位

| 参数 | live base | backtest effective |
|---|---:|---:|
| `default_target_portion` | `0.60` | `0.35` |
| `max_symbol_position_portion` | `0.60` | `0.35` |
| `max_active_symbols` | `3` | `3` |
| `min_open_portion` | `0.06` | `0.06` |

解读:

- backtest 为了控制波动，明显放宽了入场阈值，但把单笔目标仓位压到了 `35%`。
- 所以 `44.37%` 这个结果，本质上是“更容易进场 + 更轻的单笔仓位”组合出来的。
- Claude 如果要评审“这能不能直接上实盘”，必须先区分清楚这个差异。

## 5. 当前 live 开仓链路

### 5.1 入口

当前实盘入口:

```bash
python3 src/main.py --config config/trading_config_fund_flow.json
```

主链:

1. `src/main.py`
2. `src/app/fund_flow_bot.py -> TradingBot`
3. `_init_fund_flow_modules()`
4. `run_cycle() / _run_cycle_impl()`
5. `_process_symbol()`
6. `FundFlowDecisionEngine`
7. `_apply_pretrade_risk_gate()`
8. `FundFlowExecutionRouter.execute_decision()`
9. `_post_execution_protection_hook() / protection order repair`

### 5.2 模块装配

`TradingBot._init_fund_flow_modules()` 会初始化:

- `FundFlowAttributionEngine`
- `FundFlowRiskEngine`
- `FundFlowDecisionEngine`
- `FundFlowExecutionRouter`
- `MarketIngestionService`
- `TriggerEngine`

也就是说，live 不是纯策略回测器，而是“策略 + 数据摄取 + 风控 + 执行 + 归因”的完整链路。

### 5.3 每轮调度

每个 cycle 会做:

1. 读取并热更新配置
2. 刷新 signal pool runtime
3. 处理 symbols 批次
4. 对每个 symbol 跑 `_process_symbol`
5. 扫描完后再 `_finalize_entries`
6. 记录本轮 API 和调度统计

这意味着 live 里的开仓决策，不是单点函数，而是整个 cycle 的竞争过程。

## 6. 当前 live / strategy 评分与门槛

### 6.1 基础权重

当前 `MACDStrategyV2Config` 的基础权重是:

| 项 | 权重 |
|---|---:|
| `weight_1h_direction` | `0.15` |
| `weight_4h_direction` | `0.40` |
| `weight_4h_enhancement` | `0.10` |
| `weight_rsi_rhythm` | `0.30` |
| `weight_vwap` | `0.05` |
| `weight_volume` | `0.10` |

总分主干:

```text
score
= score_1h
+ score_4h_trend
+ score_rsi_rhythm
+ flip_bullish_sniper_bonus
+ score_vwap
+ score_volume
- overheat_penalty
+ path-specific bonuses
```

### 6.2 当前 live base 门槛

| 路径 | 分数门槛 |
|---|---:|
| `default/min_signal_score` | `0.85` |
| `soft_long` | `0.85` |
| `red_bar_growing` | `0.90` |
| `green_bar_growing` | `0.87` |
| `flip_bearish` | `0.84` |
| `flip_bullish` | `0.82` |

### 6.3 当前回测实际门槛

| 路径 | 分数门槛 |
|---|---:|
| `default/min_signal_score` | `0.68` |
| `soft_long` | `0.66` |
| `red_bar_growing` | `0.68` |
| `green_bar_growing` | `0.69` |
| `flip_bearish` | `0.66` |
| `flip_bullish` | `0.64` |

### 6.4 当前路径级增强/放宽

当前关键路径开关:

- `enable_priority_execution = true`
- `priority_exec_min_score = 0.90`
- `priority_exec_vip_min_score = 0.92`
- `entry_market_fallback_min_score = 0.68`
- `enable_neutral_upgrade = true`
- `neutral_upgrade_min_rsi_score = 0.35`
- `neutral_upgrade_probe_rsi_score = 0.20`
- `neutral_upgrade_probe_threshold_score = 0.82`
- `neutral_upgrade_penalty_mult = 0.90`
- `enable_15m_spring_threshold_override = true`
- `spring_override_min_signal_score = 0.82`
- `spring_override_score_bonus = 0.10`
- `enable_4h_preflip_trial_entries = true`
- `preflip_trial_min_shrink_pct_long = 0.60`
- `preflip_trial_min_shrink_pct_short = 0.30`
- `preflip_trial_min_signal_score = 0.85`
- `preflip_trial_entry_scale = 0.35`
- `preflip_trial_max_leverage = 2`
- `enable_stable_bear_continuation = true`

### 6.5 `flip_bullish` 细节

当前 live base:

- `enable_flip_bullish_strict_filter = false`
- `enable_flip_bullish_cvd_context_filter = false`
- `flip_bullish_min_vwap_score = 0.12`
- `flip_bullish_require_pullback_bounce = true`
- `flip_bullish_require_15m_growing = true`
- `flip_bullish_no_momentum_reset_penalty = 0.06`
- `flip_bullish_spring_confirmation_bonus = 0.08`
- `flip_bullish_no_spring_penalty = 0.05`

但要注意:

- strict filter 虽然关了
- cvd context filter 虽然关了
- sniper 仍然开着

所以 `flip_bullish` 的真正压力还在 sniper 和总分通过率上。

### 6.6 仓位与 probe overlay

当前 live base:

- `default_target_portion = 0.60`
- `max_symbol_position_portion = 0.60`
- `max_active_symbols = 3`
- `min_open_portion = 0.06`
- `green_bar_growing_probe_overlay = true`
- `green_bar_growing_probe_position_penalty = 0.10`
- `green_bar_growing_probe_max_leverage = 2`

这意味着:

- 正常 live base 是重仓系统
- 但 `green_bar_growing` probe 会被大幅压仓

## 7. 当前 live 执行路由

### 7.1 执行退化总开关

当前全局执行退化配置:

- `open_ioc_retry_times = 3`
- `open_ioc_retry_step_bps = 15`
- `open_gtc_fallback_enabled = true`
- `open_market_fallback_enabled = true`
- `close_ioc_retry_times = 1`
- `close_ioc_retry_step_bps = 5`
- `close_gtc_fallback_enabled = false`
- `close_market_fallback_enabled = true`

### 7.2 开仓路由分三档

`MACDStrategyV2Engine._resolve_priority_execution_plan()` 当前逻辑:

1. `score >= 0.92`
   - `execution_policy = priority_execution_vip`
   - `tif = GTC`
   - `expire = 30s`
   - `retry = 1`

2. `0.90 <= score < 0.92`
   - `execution_policy = priority_execution`
   - `tif = GTC`
   - `expire = 15s`

3. `0.68 <= score < 0.90`
   - `execution_policy = ioc_market_fallback`
   - `tif = IOC`
   - 可进入 `IOC -> market fallback guard -> market`

4. `score < 0.68`
   - 普通 `IOC`

### 7.3 IOC -> market fallback 保护

`FundFlowExecutionRouter._try_place_with_fallback()` 当前约束:

- 只有 `execution_policy == "ioc_market_fallback"` 才允许跳过 IOC retry/GTC fallback，直接进入 market fallback guard
- 还必须满足:
  - `open_market_fallback_enabled = true`
  - `entry_market_fallback_enabled = true`
  - `disable_market_fallback != true`

guard 检查:

- 参考价: `entry_reference_price`
- 最新价: `current_price`
- 最大滑点: `entry_market_fallback_max_slippage_bps`

如果超滑点:

- 直接 block market fallback

如果不超滑点:

- 才允许用 `MARKET` 补单

## 8. 当前 live 风控逻辑

### 8.1 账户级 circuit breaker

当前配置:

- `account_circuit_enabled = true`
- `max_daily_loss_percent = 5`
- `max_consecutive_losses = 2`
- `daily_loss_cooldown_seconds = 28800`
- `consecutive_loss_cooldown_seconds = 1800`
- `daily_reset_timezone = Asia/Shanghai`

解释:

- 日亏损达到 `5%` 触发账户级冷却
- 连续亏损达到 `2` 次会触发冷却
- 冷却状态会直接阻断新开仓

### 8.2 protection SLA

当前配置:

- `protection_sla_enabled = true`
- `protection_sla_seconds = 45`
- `protection_sla_force_flatten = true`
- `protection_immediate_close_on_repair_fail = true`
- `protection_sla_alert_cooldown_seconds = 15`

解释:

- 开仓后如果保护单修复/补挂不成功，live 会比 backtest 更激进
- 这层是 backtest 没有真实还原的 live 额外风险层

### 8.3 pretrade risk gate

当前配置里这层存在，但 `enabled = false`。

也就是说:

- 代码有完整 gate 逻辑
- 但当前 live 实际没有启用这层拦截

如果后面要启用，当前关键参数是:

- `entry_hold_portion_scale = 0.75`
- `entry_hold_leverage_cap = 4`
- `exit_close_ratio = 0.5`
- `exit_score_threshold = 0.2`
- `exit_confirm_bars = 3`
- `exit_min_hold_seconds = 300`
- `exit_profit_lock_min_pnl = 0.0035`
- `exit_drawdown_override = 0.015`
- `exit_trend_hold_min_score = 0.25`
- `exit_trend_hold_min_gap = 0.12`

### 8.4 conflict protection / 盈利保护 / 硬退出

当前 live 还额外有一套 backtest 没完整还原的 close 风控:

- `light_confirm_bars = 2`
- `hard_confirm_bars = 5`
- `cooldown_sec = 180`
- `light_take_profit_enabled = true`
- `light_take_profit_min_hold_seconds = 180`
- `light_take_profit_min_mfe = 0.0025`
- `light_take_profit_min_pnl = 0.001`
- `light_take_profit_pct = 0.75`
- `state_reduce_pct = 0.35`
- `hard_exit_min_hold_seconds = 600`
- `directional_eval_interval_seconds = 60`
- `hard_exit_min_mae = 0.002`
- `hard_exit_trap_force = 0.9`
- `hard_exit_drawdown_force_mult = 1.35`

解释:

- live 会做轻量 tighten、轻量止盈、结构减仓和硬退出
- 这些 close path 会进一步放大“利润提前兑现”的倾向
- 所以即便策略层已经因为 `breakeven 0.8% -> lock 0.2%` 偏保守，live 还会比 backtest 多一层提早兑现利润的压力

## 9. 当前盈利平仓细节

### 9.1 策略层固定止盈当前是关的

当前配置:

- `take_profit_pct = 0.0`
- `take_profit_pct_levels = []`

因此当前策略并不是靠固定 TP 赚钱。

### 9.2 当前主要盈利平仓来自两种路径

1. `4h_shrink_exit`
   - 趋势单持有较久
   - 等 4H MACD 收缩到 exit 条件后再走
   - 是本轮真实利润来源

2. `stop_loss_intrabar`
   - 其中大部分正收益单，本质上是 breakeven/移动止损锁住了 `~0.2%`
   - 不是“止损错了”，而是“盈利保护太早”

### 9.3 当前 breakeven 参数

当前配置:

- `breakeven_enabled = true`
- `breakeven_trigger_pnl_ratio = 0.008`
- `breakeven_lock_ratio = 0.002`

对应逻辑:

- 浮盈达到 `0.8%` 后
- 止损上移到 `+0.2%`

从回测结果看，这个设计的副作用非常明显:

- 大量单子只拿到 `0.2%`
- 真正把月收益拉高的是少数幸存到 `4h_shrink_exit` 的 runner

### 9.4 对“盈利太小”的直接判断

当前可以直接下结论:

- `是，当前利润切得太早`
- 问题不在固定 TP，因为固定 TP 现在是关的
- 问题主要在:
  - `breakeven 0.8% -> lock 0.2%`
  - live conflict protection 的轻量止盈/硬退出
  - IOC fill 不稳定导致优质 entry 也不一定都能进

更精确地说:

- 系统已经把“亏损控制”做得很好
- 但“让赢单活下去”的强度还不够

## 10. 建议 Claude 重点审的问题

建议让 Claude 重点看这 6 个问题:

1. 当前 `44.37%` 回测建立在 backtest profile `macd_v2_disable_short_filter` 上，和 live base 参数不一致；这个差异是否允许直接实盘部署。
2. `breakeven_trigger_pnl_ratio = 0.008` 与 `breakeven_lock_ratio = 0.002` 是否过早切断大多数趋势单。
3. `4h_shrink_exit` 是不是应该继续保留为主盈利出口，同时适度放慢 breakeven。
4. `flip_bullish` 当前 `seen=2652 -> passed_threshold=6 -> filled=4 -> pnl=-79.02`，其 sniper 和总分设计是否过度保守或失真。
5. live 的 `conflict_protection + protection_sla + account circuit` 是否会进一步放大“利润过早兑现”，导致 live 表现弱于策略回测。
6. 当前 IOC fill 低、market fallback 又没有实际触发，这是否会让实盘在好信号时继续漏掉 alpha。

## 11. 我自己的审阅结论

如果只看回测数字:

- `+44.37% / 87.23% / 6.12% DD` 是一份漂亮的结果

但如果看结构:

- 这套收益不是均匀稳定地产生
- 而是“很多小锁盈 + 少数大 runner”拼起来的
- 其 backtest 结果还建立在 profile 覆盖上，不等同于 live base

所以我不建议把这份 `44.37%` 直接理解成“当前 live 参数已经 fully validated”。

更准确的说法应该是:

- 当前策略已经证明自己能在 30 天窗口里产出高胜率、低回撤和可观收益
- 但还没有证明“当前 live 原样参数 + 当前 live 附加风控层”能复制这份收益结构
- 在部署前，最值得继续审的是:
  - backtest/live 参数一致性
  - breakeven 是否过早
  - live 额外 close 风控是否压缩了利润空间

## 12. 目标约束更新：不要再把 90-120 笔当成硬目标

这里补充一个新的优化约束:

- 开仓数不再局限于 `90-120`
- 新目标改为: 在 `90-300` 笔区间内，优先追求最高收益
- 交易数只作为约束区间，不再作为主目标函数

### 12.1 仓库历史工件里的区间上限

我直接扫描了 `output/backtest` 里现有 summary 工件，在 `90 <= total_trades <= 300` 这个区间内，历史上已经出现过更高收益的结果:

| summary | profile | trades | return_pct | win_rate | max_dd | profit_factor |
|---|---|---:|---:|---:|---:|---:|
| `v2_summary_20260325_123754.json` | `(empty/legacy)` | `265` | `+229.06%` | `78.49%` | `12.01%` | `4.19` |
| `v2_summary_20260426_092316.json` | `macd_v2_disable_short_filter` | `265` | `+229.06%` | `78.49%` | `12.01%` | `4.19` |
| `v2_summary_20260425_135324.json` | `macd_v2_disable_short_filter` | `260` | `+226.79%` | `78.08%` | `12.01%` | `4.16` |
| `v2_summary_20260323_224510.json` | `macd_v2_disable_short_filter` | `250` | `+166.72%` | `79.60%` | `9.38%` | `4.57` |
| `v2_summary_20260428_203556.json` | `macd_v2_disable_short_filter` | `127` | `+109.03%` | `81.89%` | `16.40%` | `4.88` |

这说明两件事:

1. 从仓库历史上看，`90-300` 区间内显著高于 `+44.37%` 的结果是存在的。
2. 当前 HEAD 的 fresh rerun 只有 `+44.37% / 94笔`，所以“当前版本距离历史高收益状态还有明显回撤”这个判断是成立的。

### 12.2 但这些高收益工件不能直接当作当前版本基准

要特别小心:

- 这些高收益 summary 大多不是当前 HEAD 的 fresh rerun
- 其中一部分 profile 为空或带有历史配置覆盖
- 它们依然可能存在:
  - backtest profile 覆盖
  - 不同版本代码
  - 不同参数组合
  - 未严格等价于当前 live base

因此正确的用法不是:

- “以前跑到过 229%，所以现在也应该直接能上”

而是:

- “历史上这套体系在 90-300 笔区间内存在更高收益上限，因此当前 +44.37% 不是理论极限”

### 12.3 后续优化目标应改成什么

后续建议把目标函数改成:

```text
maximize return_pct
subject to:
  90 <= total_trades <= 300
  max_drawdown_pct <= 12~15
  win_rate_pct >= 74~78
  profit_factor >= 3.0
```

不建议再用:

```text
优先命中 90-120 笔，再看收益
```

因为这会把优化错误地引向“人为压交易数”，而不是“提高单位机会的总利润提取效率”。
