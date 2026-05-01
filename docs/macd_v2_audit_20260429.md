# MACD V2 策略审阅报告
**审阅日期**: 2026-04-29  
**审阅范围**: 30天回测归因 + live 链路 + 参数一致性  
**审阅模式**: 量化策略代码审阅 + 实盘部署前审计  
**素材来源**: review.md + backtest artifacts（summary / trades / equity curve）  
**注意**: 本次无法直接读取本地代码文件，以下所有代码级发现均基于 review.md 中的逻辑描述、参数值与执行流程描述交叉推导；如有歧义，以实际代码为准。

---

## ⚠️ FINDINGS（按严重程度降序）

---

### [CRITICAL-1] Backtest Profile 与 Live 参数不一致 — 回测结果不可直接用于实盘决策

**发现**

`scripts/backtest_macd_v2.py` 在运行时自动调用 `apply_backtest_profile(...)` 并加载
`macd_v2_disable_short_filter`，而 `src/app/fund_flow_bot.py` 整个 init 链路中
没有等价的 `apply_backtest_profile` 调用。

这意味着 `+44.37% / 87.23% winrate / 6.12% DD` 这份数字，
不是 live 当前参数原样跑出来的结果。

**证据**

```
# review.md §4.1 / §4.3
backtest 调用路径：
  scripts/backtest_macd_v2.py
    → apply_backtest_profile(...)
    → profile: macd_v2_disable_short_filter
    → 覆盖 min_signal_score、position 参数

live 调用路径：
  src/main.py
    → fund_flow_bot.py → TradingBot._init_fund_flow_modules()
    → 没有 apply_backtest_profile
    → 直接使用 trading_config_fund_flow.json 的 base 值
```

关键参数差异量化（review.md §4.3 / §4.4）：

| 参数 | live base | backtest effective | delta |
|---|---:|---:|---:|
| `default/min_signal_score` | 0.85 | 0.68 | **-0.17** |
| `red_bar_growing` threshold | 0.90 | 0.68 | **-0.22** |
| `flip_bearish` threshold | 0.84 | 0.66 | **-0.18** |
| `default_target_portion` | 0.60 | 0.35 | **-0.25** |
| `max_symbol_position_portion` | 0.60 | 0.35 | **-0.25** |

**影响**

threshold 差 0.17~0.22 是巨大的入场宽松度差异。
live base 的 0.85~0.90 门槛极可能让大量回测中成交的单无法进入实盘。
仓位从 0.60 → 0.35 的差异，相当于实盘名义杠杆敞口是回测的 1.71 倍，
而实盘仓位占比却只有回测的 58%，收益量级不可线性类比。

粗略估算：假设 threshold 提高后成交数量从 94 笔降至约 35~50 笔，
月收益从 44.37% 可能压缩到 10~22% 区间（纯量级估算，未建模）。

**建议**

```diff
# scripts/backtest_macd_v2.py — 应新增 strict_live_mode flag
- apply_backtest_profile(config, fund_flow.backtest.default_profile)
+ if args.strict_live_mode:
+     # 不套 profile，原样使用 base config，用于 live 参数验证
+     pass
+ else:
+     apply_backtest_profile(config, fund_flow.backtest.default_profile)

# 在 CI 或 pre-deploy 流程中，必须用 --strict_live_mode 跑一次验证
# python scripts/backtest_macd_v2.py --strict_live_mode \
#   --start 2026-02-23 --end 2026-03-24T23:59:59
# 把这个结果作为"live 等效基准"，才能与实盘对比
```

---

### [CRITICAL-2] Breakeven 设计导致 80%+ 盈利单被提前锁死在 ~0.2% — 利润结构严重失衡

**发现**

`breakeven_trigger_pnl_ratio = 0.008`（浮盈 0.8% 触发）
配合 `breakeven_lock_ratio = 0.002`（止损上移至 +0.2%）

这个设计的语义是：  
"只要浮盈超过 0.8%，就立刻把止损锁在 +0.2%"

对于趋势单来说，这等于强制要求：
- 要么你一路拉升不回头，活到 `4h_shrink_exit`
- 要么你有任何一次超过 0.6% 的回调，就在 +0.2% 被扫出去

**证据**

```
# review.md §3.3 直接统计
盈利单总数:            83
盈利幅度 ≤ 0.25% 的单: 67   (80.72%)
这 67 笔合计贡献:      $568.77

breakeven-like 赢单:   56  (明显以 ~0.20% 锁盈离场)
这 56 笔合计贡献:      $514.91
平均持仓时间:          155.63 min

4h_shrink_exit:        16 笔
合计贡献:              $4,846.70
平均单笔盈利:          5.21%
平均持仓:              1440.94 min
```

利润集中度检验（伪代码）：

```python
# 从 v2_trades_20260429_210230.csv 推导
total_pnl = sum(all_trades.pnl)  # ~$4,340 (净)

runner_pnl = 4846.70  # 4h_shrink_exit
small_win_pnl = 568.77  # ≤0.25% 盈利单
loss_pnl = total_pnl - runner_pnl - small_win_pnl  # 亏损部分

runner_pct_of_wins = runner_pnl / (runner_pnl + small_win_pnl)
# ≈ 4846.70 / 5415.47 ≈ 89.5%

# 结论：赢单利润的 89.5% 来自 16 笔中的 runner，
# 剩下 67 笔小赢单只贡献 10.5% 的利润
```

**影响**

这个结构的核心问题不是"胜率"，而是"runner survival rate"。

```
当前 runner 产生路径（极窄）：
  成交 94 笔
  → 能活到 4h_shrink_exit 的：16 笔（17%）
  → 这 16 笔贡献 89.5% 的利润

breakeven 直接杀死了其中大量潜在 runner：
  一旦浮盈回落超过 0.6%，就从 0.8% 跌回被扫在 +0.2%
  对于正常趋势单而言，0.6% 的日内回调几乎是必然发生的

如果 runner survival rate 从 17% 提升到 25%（+8 笔），
假设平均贡献持平，月净利润估算增量：8 × $302.92 ≈ $+2,423
折合资本增量约 +16.8 个百分点
```

**建议**

```diff
# config/trading_config_fund_flow.json — breakeven 参数调整方向
- "breakeven_trigger_pnl_ratio": 0.008,   # 浮盈 0.8% 触发
- "breakeven_lock_ratio": 0.002,           # 锁在 +0.2%

# 候选方案 A：放宽触发，锁盈比例同步提高
+ "breakeven_trigger_pnl_ratio": 0.015,   # 浮盈 1.5% 才触发
+ "breakeven_lock_ratio": 0.005,           # 锁在 +0.5%

# 候选方案 B：仅对 red_bar_growing / flip_bearish 路径差异化设定
+ "breakeven_trigger_pnl_ratio_red_bar":  0.018,
+ "breakeven_lock_ratio_red_bar":          0.006,
+ "breakeven_trigger_pnl_ratio_default":  0.008,  # 其他路径维持保守

# 验证方法：
# 1. 先跑 strict_live_mode backtest with new breakeven params
# 2. 对比：runner count, runner avg pnl, max_drawdown
# 3. 只有当 max_drawdown 仍 ≤ 10% 时，才考虑上实盘灰度
```

**注意**：放宽 breakeven 会同时放大单笔最大浮亏暴露，
必须在同一次测试中观测 `max_drawdown` 和 `avg_loss` 的变化，
不能只看收益率。

---

### [HIGH-1] Live 额外关闭层叠加效应 — Backtest 没有完整还原

**发现**

review.md §8.4 列出了 live 独有的关闭路径，这些在 backtest 中均未完整模拟：

```
live 独有 close 触发：
  light_take_profit:
    - min_hold_seconds: 180
    - min_mfe: 0.0025 (0.25%)
    - min_pnl: 0.001 (0.1%)
    - take_pct: 0.75 (平掉 75% 仓位)

  hard_exit:
    - min_hold_seconds: 600
    - hard_exit_min_mae: 0.002
    - hard_exit_trap_force: 0.9
    - hard_exit_drawdown_force_mult: 1.35

  state_reduce_pct: 0.35
  (每次结构减仓 35% 持仓)
```

**证据与推导**

```python
# 模拟叠加效应的伪逻辑
def live_close_decision(trade):
    """
    live 里一笔 runner 要活到 4h_shrink_exit，
    必须同时通过以下所有层的检查：
    """
    if trade.hold_minutes >= 3 and trade.mfe >= 0.0025 and trade.pnl >= 0.001:
        # light_take_profit 触发：直接平掉 75% 仓位
        # → runner 剩余 25% 仓位继续持有
        # → 即使后续涨 10%，利润也只有回测的 25%
        trigger_light_take_profit(trade, pct=0.75)

    if trade.hold_minutes >= 10 and trade.mae >= 0.002:
        # hard_exit 触发
        trigger_hard_exit(trade)

    # 实际上，backtest 的 4h_shrink_exit runner
    # 在 live 里几乎必然先触发 light_take_profit（因为 MFE ≥ 0.25% 且持仓 ≥ 3min）
    # 结果：runner 的最终利润被截断到约 25%
```

**影响量化**

```
backtest 中 4h_shrink_exit runner：
  avg pnl%:    5.21%
  total pnl:   $4,846.70

live 中如果 light_take_profit 把 75% 仓位在 MFE 附近平掉：
  假设 light_tp 触发时 pnl ≈ 0.5%
  剩余 25% 仓位活到 4h_shrink_exit，pnl ≈ 5.21%

  单笔等效 pnl = 0.75 × 0.5% + 0.25 × 5.21% ≈ 1.68%
  vs backtest avg 5.21%

  live runner 利润被压缩至回测的 32%
  
  如果 16 笔 runner 都触发这个路径：
  live runner 总贡献估算 ≈ $4,846.70 × 32% ≈ $1,551
  月净利润从 $4,437 压缩至约 $2,143
  折合月收益从 44.37% 压至约 21%
```

**建议**

```diff
# 建议先审阅 fund_flow_bot.py 的 conflict_protection 模块
# 重点确认：light_take_profit 是否对 4h_shrink_exit 路径的单子豁免

# 伪代码：建议新增 runner_protection flag
+ if trade.exit_strategy == "4h_shrink_hold":
+     # 对于显式标记为 runner 的单子，禁止 light_take_profit 提前平仓
+     skip_light_take_profit = True
+ else:
+     skip_light_take_profit = False

# 或者设置更高的 light_take_profit 触发门槛，避免在小 MFE 时就平掉大仓位
- "light_take_profit_min_mfe": 0.0025,    # 0.25% MFE 就触发
+ "light_take_profit_min_mfe": 0.010,     # 至少 1.0% MFE 才触发
- "light_take_profit_pct": 0.75,          # 平掉 75%
+ "light_take_profit_pct": 0.40,          # 只平 40%，保留更多 runner 仓位
```

---

### [HIGH-2] flip_bullish 路径实质已经失效，但仍在消耗信号容量

**发现**

`flip_bullish` 的漏斗极度失血：

```
flip_bullish_seen:                2652
flip_bullish_passed_threshold:       6  (通过率 0.23%!)
flip_bullish_blocked_by_sniper:    396
flip_bullish_ioc_canceled:           1
实际成交:                            4
总 PnL:                         -$79.02
```

0.23% 的阈值通过率意味着：每 432 个 flip_bullish 信号，只有 1 个能过门槛。

**证据：通过率分解**

```python
# 推导 flip_bullish 实际失效原因
total_seen = 2652
passed_threshold = 6       # 门槛通过率 0.23%
blocked_by_sniper = 396    # 在通过门槛前被 sniper 拦截？
                           # 还是通过门槛后被 sniper 拦截？
                           # （这个顺序很关键，review.md 未给出明确先后）

# 假设 sniper 在 threshold 检查之前运行（常见设计）：
pre_sniper_candidates = total_seen  # 2652
post_sniper = total_seen - blocked_by_sniper  # 2652 - 396 = 2256
post_threshold = passed_threshold   # 6

# 那么：
# sniper 把 2652 → 2256 (过滤 14.9%)
# threshold 把 2256 → 6 (过滤 99.7%!)
# → 主要问题在 threshold，不在 sniper

# 假设 threshold 在 sniper 之前运行：
# threshold 把 2652 → 6 (过滤 99.77%)
# sniper 再从 6 中拦截 396 —— 这不可能（396 > 6）
# → 说明 sniper 在 threshold 之前运行

# 实际逻辑应该是：
# 1. sniper 对 2652 中的 396 个拦截
# 2. 剩余 2256 个进 threshold 检查
# 3. 只有 6 个通过（通过率 0.27%）
# 4. 成交 4 个

# 结论：flip_bullish 的核心问题是 threshold 设计
# 0.27% 的通过率意味着分数分布与门槛严重错位
```

**核心问题诊断**

```python
# flip_bullish 总分计算（根据 §6.1 权重推导）
# 最大可能分数的估算（理想条件下）
max_theoretical_score = (
    0.15 +  # weight_1h_direction (满分)
    0.40 +  # weight_4h_direction (满分)
    0.10 +  # weight_4h_enhancement (满分)
    0.30 +  # weight_rsi_rhythm (满分)
    0.05 +  # weight_vwap (满分)
    0.10    # weight_volume (满分)
)  # = 1.10

# flip_bullish 特有调整
flip_bullish_sniper_bonus = ???       # 只有通过 sniper 才有
flip_bullish_spring_confirmation_bonus = 0.08  # 有 spring 时
flip_bullish_no_spring_penalty = -0.05         # 无 spring 时
flip_bullish_no_momentum_reset_penalty = -0.06 # 无 momentum reset

# 实际场景中 flip_bullish 的得分可能：
# 1h direction 可能不够理想（flip 发生时 1h 仍在下行）→ 0.05
# 4h direction flip 中 → 0.20（不满分）
# rsi rhythm 还在恢复 → 0.15
# 无 spring → -0.05
# 无 momentum reset → -0.06
# 估算实际分数中位数 ≈ 0.55~0.65

# 而 flip_bullish threshold = 0.82（live base）
# 所以结构性过不了门槛，不是参数调得太精细，是根本性不匹配
```

**影响**

```
当前状态：flip_bullish 消耗信号扫描周期、capacity check 时间，
但产出 4 笔成交，PnL = -$79.02。

这个路径当前不是 alpha 源，是 noise + overhead 源。
但在 backtest 中依然保留，导致归因分析中 flip_bullish 的
"成交 4 笔 / 胜率 50%"看起来像一个"小但合理"的路径，
实际上这 4 笔是高度幸存者偏差的产物。
```

**建议**

```diff
# 选项 A：临时屏蔽 flip_bullish 路径，集中验证主力路径表现
+ "enable_flip_bullish": false,

# 选项 B：降低 flip_bullish threshold 并验证（需同步降 sniper 标准）
- "flip_bullish": 0.82,    # live base threshold
+ "flip_bullish": 0.72,    # 试验性放宽，观察 seen→passed 转化率

# 选项 C：重新审视 flip_bullish 的分数权重设计
# 当 flip_bullish 发生时，4h_direction 分 = 0（正在 flip 中）
# 但 weight_4h_direction = 0.40（最大权重）
# 这导致 flip_bullish 天生就无法拿到足够的 4h 方向分
# 修复建议：在 flip_bullish 路径中，将 4h_direction weight 临时替换为
#            "4h 收缩趋势评分"，而不是"方向强度评分"

# 在审阅代码前，先确认：flip_bullish 路径是否有独立的权重覆盖？
# 如果没有，这是结构性缺陷，需要代码层修复
```

---

### [HIGH-3] IOC 不成交率 58%，market_fallback 实际零触发 — 执行链路存在系统性 alpha 泄漏

**发现**

```
orders_submitted:   224
orders_filled:       94
orders_canceled:    130  (全部是 ioc_no_fill)

fill_rate_submitted: 41.96%
ioc_no_fill:         130 (占 submitted 的 58.04%)

market_fallback_attempted: 0
market_fallback_filled:    0
```

**证据与问题推导**

```python
# 执行路由逻辑（review.md §7.2 + §7.3）
def resolve_execution_plan(signal):
    score = signal.score

    if score >= 0.92:
        return ExecutionPlan(
            policy="priority_execution_vip",
            tif="GTC", expire_sec=30, retry=1
        )
    elif score >= 0.90:
        return ExecutionPlan(
            policy="priority_execution",
            tif="GTC", expire_sec=15
        )
    elif score >= 0.68:
        return ExecutionPlan(
            policy="ioc_market_fallback",
            tif="IOC"
            # 允许 IOC → market fallback
        )
    else:
        return ExecutionPlan(
            policy="ioc_only",
            tif="IOC"
            # 不允许 market fallback
        )

# 问题分析：
# backtest effective threshold = 0.68
# 所以 backtest 中大量订单走 "ioc_market_fallback" 路由
# 但 market_fallback_attempted = 0

# 为什么 fallback 没有触发？
# review.md §7.3 说明：fallback 触发需要同时满足：
#   1. policy == "ioc_market_fallback"
#   2. open_market_fallback_enabled = true
#   3. entry_market_fallback_enabled = true
#   4. disable_market_fallback != true
#   5. 滑点检查通过（最新价 vs entry_reference_price ≤ max_slippage_bps）

# 推断：滑点检查是主要拦截层
# 当 IOC 不成交时，市场已经移动，
# current_price vs entry_reference_price 超过 slippage 限制
# → fallback 被 guard 拦截
# → 订单最终 cancel

# 这意味着：
# 好信号（高 MFE 的单子）发出时市场往往在快速移动
# IOC 因为流动性或价格滑动不成交
# fallback guard 因为价格移动过快也拒绝补单
# 结果：正是那些"本来能成为 runner"的信号，最容易被漏掉
```

**影响**

```
# 保守估算：130 笔 IOC 取消中，如果有 20% 原本是好信号
canceled_good_signals = 130 * 0.20  # = 26 笔
# 假设这些信号的平均质量与已成交单相当
avg_trade_pnl = total_pnl / 94  # ~$46/笔
estimated_missed_pnl = 26 * avg_trade_pnl  # ~$1,196
# 相当于月收益多出约 8~10 个百分点（保守估算）

# 更严重的是：这 130 笔中，quality 分布是否有偏？
# 如果高分（0.90+）的单子因为市场更活跃而更容易 IOC 不成交，
# 那么实际漏掉的是最高质量的信号，影响远不止 8%
```

**建议**

```diff
# 1. 增大 IOC retry step，提高 IOC 成交概率
- "open_ioc_retry_step_bps": 15,
+ "open_ioc_retry_step_bps": 20,   # 每次 retry 多给 5bps 滑点空间
- "open_ioc_retry_times": 3,
+ "open_ioc_retry_times": 4,        # 多一次重试

# 2. 放宽 market fallback guard 的滑点上限（需谨慎）
# 先查 entry_market_fallback_max_slippage_bps 的当前值
# 如果 < 30bps，考虑放至 40bps（仅对 score ≥ 0.90 的 VIP 单）

# 3. 诊断 IOC 取消的信号得分分布
# 在 backtest log 中输出每笔取消单的 score，
# 确认高分单取消比例是否高于低分单

# 伪代码：新增 cancel 质量诊断
+ canceled_trades = trades[trades.status == "ioc_no_fill"]
+ filled_trades = trades[trades.status == "filled"]
+ print(f"Canceled avg score: {canceled_trades.signal_score.mean():.3f}")
+ print(f"Filled avg score:   {filled_trades.signal_score.mean():.3f}")
+ # 如果 canceled avg score > filled avg score，说明执行链路有逆向选择问题
```

---

### [MEDIUM-1] Pretrade Risk Gate 当前关闭 — 但一旦启用将产生额外 alpha 压制

**发现**

```yaml
# review.md §8.3
pretrade_risk_gate: enabled = false
```

Gate 处于关闭状态，但代码逻辑完整存在，且参数已经配置。

**风险场景推导**

```python
# 假设某天临时启用 pretrade_risk_gate
# 以下参数会立即生效：

gate_params = {
    "entry_hold_portion_scale": 0.75,   # 开仓时只允许 75% 目标仓位
    "entry_hold_leverage_cap": 4,       # 杠杆上限
    "exit_close_ratio": 0.5,            # 触发 gate 时平掉 50% 仓位
    "exit_score_threshold": 0.2,        # 低于 0.2 分触发 gate
    "exit_confirm_bars": 3,             # 3 根 K 线确认
    "exit_min_hold_seconds": 300,       # 最少持仓 5 分钟
    "exit_profit_lock_min_pnl": 0.0035, # 最小锁盈 0.35%
    "exit_drawdown_override": 0.015,    # 回撤超 1.5% 直接触发
    "exit_trend_hold_min_score": 0.25,  # 趋势保护最低分
    "exit_trend_hold_min_gap": 0.12,   # 趋势保护最小间距
}

# 与当前 breakeven 的叠加问题：
# 情景：单子浮盈 0.9%，触发 breakeven → 止损上移至 +0.2%
# 同时 gate 激活，exit_drawdown_override = 0.015：
# 如果从 0.9% 浮盈回撤 1.5%（到 -0.6%），gate 强制平仓
# 但此时 breakeven 止损在 +0.2%，理论上应该在 +0.2% 被保本出去
# 两层机制的交互顺序不明确，可能造成：
#   a. 双重触发，重复平仓尝试
#   b. 其中一层失效，另一层单独处理
```

**建议**

```
在 gate 当前关闭的情况下：
1. 不要在实盘压力期（如 live 刚上线）随意 toggle enabled = true
2. 如果要启用，必须先在 backtest 中加入完整 gate 模拟，
   对比有/无 gate 两组回测的 runner survival rate
3. 重点测试 exit_drawdown_override = 0.015 是否会提前切断趋势单
```

---

### [MEDIUM-2] account_circuit_breaker 参数过于激进 — 可能在正常震荡中触发

**发现**

```yaml
max_consecutive_losses: 2
consecutive_loss_cooldown_seconds: 1800  # 30 分钟冷却
```

**问题**

```python
# 连续亏损 2 笔触发 30 分钟封禁
# 对于高频策略（94 笔/30天 ≈ 3笔/天），这个参数非常敏感

# 模拟场景：
# 上午 9:00 — 成交一笔，止损出 (-$25)
# 上午 9:30 — 成交一笔，止损出 (-$30)
# 触发 circuit breaker → 封禁至 10:00

# 如果 10:00~10:30 有最优质的信号（例如开盘后第一波趋势启动），
# 这段时间全部被 circuit breaker 屏蔽
# 而两次亏损总额只有 $55，占总资本 0.55%（按 $10,000 计）

# 这个保护阈值对于 6.12% max_drawdown 的策略来说，过于早触发
```

**建议**

```diff
- "max_consecutive_losses": 2,
+ "max_consecutive_losses": 3,          # 允许更多连续亏损才触发
- "consecutive_loss_cooldown_seconds": 1800,
+ "consecutive_loss_cooldown_seconds": 900,  # 缩短冷却时间到 15 分钟
# 同时新增：
+ "consecutive_loss_dollar_threshold": 300,  # 只有连续亏损超过 $300 才触发
# 避免小额亏损触发不必要的系统暂停
```

---

### [LOW-1] capacity_competition_dropped = 71 — 容量竞争切掉了潜在优质信号

**发现**

```
capacity_competition_dropped: 71
capacity_full_precheck_candidates: 116
```

71 笔因容量竞争被丢弃，占候选的 12.7%。

**问题**

```python
# max_active_symbols = 3（live 和 backtest 一致）
# 当已经有 3 个仓位时，新信号无论分数多高都被丢弃

# 风险：如果已有的 3 个仓位是低分单，
# 而新来的是高分（0.95+）的信号，系统仍然会拒绝新信号
# 当前没有"踢出低分单让位给高分单"的机制

# 验证方法：
dropped_vs_active = cross_join(
    capacity_competition_dropped_signals,
    active_positions_at_that_time
)
# 检查：被丢弃信号的平均分数 vs 当时活跃仓位的平均分数
# 如果 dropped_avg_score > active_avg_score，说明需要优先级置换机制
```

**建议**

```diff
# 如果 max_drawdown 稳定在 6% 以下，可以考虑：
- "max_active_symbols": 3,
+ "max_active_symbols": 4,    # 多一个槽位，减少优质信号被容量卡死的概率

# 更优方案（需代码支持）：
# 新增 priority_eviction：当新信号分数 > 当前最低活跃仓位分数 × 1.2 时，
# 允许提前平仓最弱仓位，让位给高分新信号
```

---

## 二、回测 vs 实盘一致性结论

**明确结论：当前回测不能代表当前实盘参数的执行结果。**

差异最大的三个点：

### Gap-1: 入场阈值差异（影响最大）

```
live base:          min_signal_score = 0.85~0.90
backtest effective: min_signal_score = 0.66~0.68

delta: 0.17~0.22

量化影响估算：
  backtest: 94 笔成交 / 558 候选 = 16.8% 候选→成交率
  live base threshold 更高，候选数量估计减少 40~60%
  → live 等效成交估算: 35~55 笔
  → 月收益量级从 44% 可能压缩到 15~25%
  → 这是最关键的 live-backtest gap
```

### Gap-2: 仓位规模差异（影响中等）

```
live base:          default_target_portion = 0.60
backtest effective: default_target_portion = 0.35

live 单笔仓位是 backtest 的 1.71 倍。
这意味着：
  - live 的单笔盈亏金额更大（风险更高）
  - 但如果成交数量同步减少，总利润不一定成正比例增大
  - 更大仓位 × 更少成交 = 收益不确定，风险明显上升
```

### Gap-3: 额外 close 层差异（影响中等但很隐蔽）

```
backtest 未模拟的 live 关闭层：
  - light_take_profit（MFE ≥ 0.25% 就平 75% 仓位）
  - hard_exit（drawdown 1.5% 强制出）
  - protection_sla（45s 内保护单不成功就强平）
  - conflict_protection（方向冲突检测）

这些层在 backtest 中没有完整还原，
导致 backtest 的 runner（4h_shrink_exit）在 live 中实际上
会被 light_take_profit 提前削减 75% 仓位。
```

---

## 三、收益受限根因判断

**明确结论：当前最主要瓶颈是"利润过早兑现"，而非信号不足或阈值过严。**

### 根因排序

**#1（最主要）：Breakeven + light_take_profit 叠加的 runner 扼杀**

```
证据：
  - 80.72% 的盈利单 ≤ 0.25%（几乎都是 breakeven 锁盈出）
  - 89.5% 的赢单利润来自仅 17% 的 runner（16/94）
  - light_take_profit 在 MFE ≥ 0.25% 就平 75% 仓位，
    进一步压缩 runner 最终收益

  如果只解决这一个问题（放慢 breakeven + 调大 light_tp 触发门槛），
  月收益提升潜力最大（估算 +10~20 个百分点）
```

**#2（次要）：执行转化率低，IOC 取消 58% 无 fallback**

```
证据：
  - 130/224 = 58% 的订单被取消
  - market_fallback 零触发（滑点保护过严）

  如果能把成交率从 42% 提升到 60%，
  等效成交数量从 94 提升到约 135 笔
  按当前平均 pnl 估算：月收益增量约 +20%（相对增量）
  但执行质量会影响平均 pnl，实际增量可能低于此估算
```

**#3（参数层）：Backtest/live 参数不一致导致的"虚假基准"**

```
这不是收益的"限制根因"，而是"认知偏差根因"。
当前不知道 live 真实参数下的回测结果是什么，
导致优化决策可能都建立在错误的基准上。

优先级：先跑 strict_live_mode 回测，获得真实基准，
再讨论优化方向。
```

---

## 四、是否建议现在实盘

### 结论：**只能灰度验证，不建议直接上线**

**理由**：

```
1. 当前没有"live 等效参数回测"的结果
   不知道 live base 参数下真实的收益率是多少
   在这个前提下讨论上线，是在不确定基准上做决策

2. light_take_profit + breakeven 的叠加效应未验证
   backtest 里 runner 活到 4h_shrink_exit 的路径，
   在 live 里很可能被 light_take_profit 提前切断
   这意味着 live 的盈利结构可能比 backtest 差得多

3. flip_bullish 的负贡献
   虽然金额小（-$79），但它的漏斗通过率 0.23% 说明设计存在根本性问题
   继续保留在 live 中会引入不确定性

4. IOC 执行质量未优化
   58% 取消率 + 零 fallback 触发，说明执行层有明显的改进空间
   在执行层优化前上线，会让参数优化效果大打折扣

如果一定要上线灰度验证：
  - 初始资金上限: 总资金的 10%
  - 同步跑 live 等效参数回测，实时对比
  - 重点监控：runner survival rate（目标 > 20%）
  - 设置强制人工审查阈值：
    如果 2 周内 runner < 15%，立即暂停并排查
```

---

## 五、下一步建议（优先级排序，最多 5 条）

---

### 建议-1（最高优先级）：立即跑 strict_live_mode 回测，建立真实基准

**为什么这条最优先？**

所有后续决策（是否上线、改哪个参数、改多少）都依赖一个可信的基准。
当前基准（44.37%）不是 live 等效基准，用它做决策是错的。

**具体操作**

```bash
# Step 1: 在 backtest script 中新增 --strict_live_mode flag
# scripts/backtest_macd_v2.py 修改：

# 在 argparse 新增：
parser.add_argument("--strict_live_mode", action="store_true",
    help="Skip apply_backtest_profile; use raw config as-is (live equivalent)")

# 在 apply_backtest_profile 调用前：
if not args.strict_live_mode:
    apply_backtest_profile(config, config.fund_flow.backtest.default_profile)

# Step 2: 跑验证回测
python scripts/backtest_macd_v2.py \
    --config config/trading_config_fund_flow.json \
    --start 2026-02-23 \
    --end 2026-03-24T23:59:59 \
    --strict_live_mode \
    --output-prefix v2_live_equiv_20260429

# Step 3: 比较两份结果
# 关注：total_trades, win_rate, return_pct, max_drawdown
# 预期：strict_live_mode 结果会明显弱于 profile 回测
# 这个差距就是你需要知道的"live gap 量"
```

**验收标准**

```
strict_live_mode 回测结果 → 建立为新的 live 对比基准
如果 strict_live_mode 结果 < +15% / 75% WR，
则当前策略在 live 参数下尚未达到可部署标准
```

---

### 建议-2：Breakeven 参数消融实验，找 runner 最优存活点

**为什么这条第二？**

这是当前最可能无副作用地提升月收益的手段。
Breakeven 参数改变不影响成交数量，只影响每笔单的利润扩展空间。

**具体操作**

```python
# scripts/run_breakeven_ablation.py
BREAKEVEN_CONFIGS = [
    # (trigger_ratio, lock_ratio, label)
    (0.008, 0.002, "current"),       # 当前配置（0.8% 触发，锁 0.2%）
    (0.010, 0.003, "slightly_wider"), # 1.0% 触发，锁 0.3%
    (0.015, 0.005, "wider"),          # 1.5% 触发，锁 0.5%
    (0.020, 0.008, "wide"),           # 2.0% 触发，锁 0.8%
    (0.025, 0.010, "very_wide"),      # 2.5% 触发，锁 1.0%
    (0.000, 0.000, "disabled"),       # 关掉 breakeven 作为上界参考
]

for trigger, lock, label in BREAKEVEN_CONFIGS:
    config = load_config("trading_config_fund_flow.json")
    config.breakeven_trigger_pnl_ratio = trigger
    config.breakeven_lock_ratio = lock

    result = run_backtest(config, start="2026-02-23", end="2026-03-24")
    print(f"{label:20s}  "
          f"return={result.return_pct:+.2f}%  "
          f"wr={result.win_rate_pct:.2f}%  "
          f"runners={result.exit_type_counts.get('4h_shrink_exit', 0)}  "
          f"mdd={result.max_drawdown_pct:.2f}%  "
          f"pf={result.profit_factor:.2f}")
```

**期望结果形态**

```
label               return    wr      runners  mdd     pf
current             +44.37%  87.23%   16      6.12%  7.20
slightly_wider      +50~55%  82~85%   20~22   7~8%   7~9
wider               +55~65%  78~82%   24~28   8~10%  8~10
wide                +60~70%  74~80%   28~32   9~12%  7~9
very_wide           +??      ??       ??      ??      ??
disabled            上界参考
```

**接受准则**

```
选择满足以下条件的配置：
  - win_rate ≥ 74%（不要为了 runner 牺牲胜率太多）
  - max_drawdown ≤ 10%（当前 6.12%，给 4% 的余量）
  - profit_factor ≥ 5.0
  - runner 数量 ≥ 22
```

---

### 建议-3：Flip_bullish 路径决策 — 屏蔽或重建，不允许带着当前设计上 live

**为什么这条第三？**

0.23% 的通过率说明 flip_bullish 的分数分布与门槛之间存在根本性错位。
这个路径继续存在会引入 live 的不确定性，且当前贡献为负。

**诊断流程**

```python
# Step 1: 确认分数分布
# 从 backtest log 中提取所有 flip_bullish 信号的分数分布
flip_bullish_scores = [
    s.score for s in signal_log
    if s.signal_type == "flip_bullish"
    and s.status != "blocked_by_sniper"
]

import numpy as np
print(f"flip_bullish score distribution:")
print(f"  p10: {np.percentile(flip_bullish_scores, 10):.3f}")
print(f"  p25: {np.percentile(flip_bullish_scores, 25):.3f}")
print(f"  p50: {np.percentile(flip_bullish_scores, 50):.3f}")
print(f"  p75: {np.percentile(flip_bullish_scores, 75):.3f}")
print(f"  p90: {np.percentile(flip_bullish_scores, 90):.3f}")
print(f"  threshold: 0.82 (live base)")
print(f"  pct_above_threshold: {(np.array(flip_bullish_scores) >= 0.82).mean():.2%}")

# Step 2: 如果 p90 < 0.82，说明 threshold 根本不匹配当前信号分布
# → 选项：降低 threshold 到 p75 水平，或重新校准权重

# Step 3: 审查 4h_direction weight 在 flip_bullish 中的实际贡献
# flip_bullish 发生时，4h MACD 正在 flip（方向中性），
# weight_4h_direction = 0.40 但实际得分接近 0
# → 这 0.40 的权重在 flip_bullish 路径中是无效的，
#   导致最大可达分数结构性偏低
```

**修复方向**

```diff
# 方案 A：临时屏蔽（最安全）
+ "enable_flip_bullish": false,   # 关掉，集中优化主力路径

# 方案 B：路径内权重覆盖（需代码修改）
# 在 flip_bullish 路径的评分中，替换 4h_direction 权重

# 伪代码：macd_strategy_v2.py
- score += weight_4h_direction * score_4h_direction  # flip 中此项 ≈ 0

+ if signal_type == "flip_bullish":
+     # 用 4h shrink quality 代替 4h direction
+     score += weight_4h_direction * score_4h_shrink_quality
+ else:
+     score += weight_4h_direction * score_4h_direction
```

---

### 建议-4：Light_take_profit 触发门槛提高，保护 runner 存活

**为什么这条第四？**

即使 breakeven 放宽了，live 的 light_take_profit 仍然会在 MFE ≥ 0.25% 时平掉 75% 仓位，
直接截断 runner 的最终收益。

**问题量化**

```python
# runner 的 light_take_profit 触发概率估算
# 假设 4h_shrink_exit runner 平均持仓 1440 分钟 ≈ 24 小时
# 在 24 小时内，MFE ≥ 0.25% 的概率几乎是 1.0

# 当前 light_take_profit 触发条件：
#   min_hold_seconds = 180 (3分钟)
#   min_mfe = 0.0025 (0.25%)
#   min_pnl = 0.001 (0.1%)
#   pct = 0.75 (平 75%)

# 对于一个最终涨 5% 的 runner：
# T+3min: 可能已经有 0.3% MFE → 触发 light_tp，平掉 75%
# 剩余 25% 继续持有到最终 5%
# 等效单笔 pnl ≈ 0.75 × 0.3% + 0.25 × 5% = 1.475%（vs 回测的 5%）

# 结论：live runner 利润被截断至 backtest 的 30~40%
```

**修复建议**

```diff
# config/trading_config_fund_flow.json
- "light_take_profit_min_hold_seconds": 180,   # 3分钟就可以触发
+ "light_take_profit_min_hold_seconds": 1200,  # 至少持仓 20 分钟才考虑

- "light_take_profit_min_mfe": 0.0025,         # MFE 0.25% 就触发
+ "light_take_profit_min_mfe": 0.0080,         # MFE 0.8% 才触发（与 breakeven 触发点对齐）

- "light_take_profit_pct": 0.75,               # 平掉 75%
+ "light_take_profit_pct": 0.30,               # 只平 30%，保留更多 runner 仓位

# 同时新增：runner 保护豁免（如果代码支持）
+ "light_take_profit_skip_if_exit_mode": "4h_shrink_hold",
```

**验证方法**

```bash
# 在 backtest 中新增 simulate_live_close_layers = true 的选项
# 对比：
#   baseline: 不模拟 live close 层
#   with_current_ltp: 模拟当前 light_tp 参数
#   with_proposed_ltp: 模拟修改后的 light_tp 参数
# 对比 runner count 和 runner avg pnl
```

---

### 建议-5：建立 live 等效参数 CI 校验流水线，防止未来 profile 漂移

**为什么这条第五？**

当前的 backtest/live 参数不一致问题，是一个会持续发生的"工程性漏洞"。
每次有人修改 config 或 profile，这个 gap 可能悄悄扩大，
而没有任何自动检测机制会报警。

**具体实现**

```python
# scripts/validate_live_backtest_alignment.py (新建)

def check_alignment():
    live_config = load_config("config/trading_config_fund_flow.json")
    backtest_config = deepcopy(live_config)
    apply_backtest_profile(backtest_config, "macd_v2_disable_short_filter")

    CRITICAL_PARAMS = [
        ("default.min_signal_score", 0.05),        # 允许最大差值
        ("red_bar_growing.min_signal_score", 0.05),
        ("flip_bearish.min_signal_score", 0.05),
        ("default_target_portion", 0.10),
        ("max_symbol_position_portion", 0.10),
    ]

    violations = []
    for param_path, max_delta in CRITICAL_PARAMS:
        live_val = get_nested(live_config, param_path)
        bt_val = get_nested(backtest_config, param_path)
        delta = abs(live_val - bt_val)
        if delta > max_delta:
            violations.append({
                "param": param_path,
                "live": live_val,
                "backtest": bt_val,
                "delta": delta,
                "max_allowed": max_delta
            })

    if violations:
        print("⚠️  ALIGNMENT VIOLATIONS DETECTED:")
        for v in violations:
            print(f"  {v['param']}: live={v['live']:.3f}, bt={v['backtest']:.3f}, "
                  f"delta={v['delta']:.3f} > max={v['max_allowed']:.3f}")
        print("\nRun with --strict_live_mode to get live-equivalent backtest.")
        sys.exit(1)
    else:
        print("✅ Live/backtest alignment OK")

# 在 CI/CD 或部署脚本中强制执行：
# python scripts/validate_live_backtest_alignment.py || exit 1
```

**额外：每次部署前强制跑 strict_live_mode 回测**

```yaml
# .github/workflows/pre_deploy.yml 或等价 CI 配置
steps:
  - name: Validate parameter alignment
    run: python scripts/validate_live_backtest_alignment.py

  - name: Run strict live mode backtest
    run: |
      python scripts/backtest_macd_v2.py \
        --config config/trading_config_fund_flow.json \
        --strict_live_mode \
        --start $(date -d "30 days ago" +%Y-%m-%d) \
        --end $(date +%Y-%m-%dT23:59:59) \
        --output-prefix v2_predeploy_$(date +%Y%m%d)

  - name: Assert minimum performance
    run: |
      python scripts/assert_backtest_thresholds.py \
        --min_return 15.0 \
        --min_winrate 74.0 \
        --max_drawdown 12.0
      # 如果 strict_live_mode 下连这个低门槛都过不了，停止部署
```

---

## 附录：关键参数交叉对照表

```
参数名                              live base   backtest eff   diff
─────────────────────────────────────────────────────────────────
default/min_signal_score            0.85        0.68          -0.17
soft_long threshold                 0.85        0.66          -0.19
red_bar_growing threshold           0.90        0.68          -0.22  ← 最大差异
green_bar_growing threshold         0.87        0.69          -0.18
flip_bearish threshold              0.84        0.66          -0.18
flip_bullish threshold              0.82        0.64          -0.18
default_target_portion              0.60        0.35          -0.25  ← 仓位差异
max_symbol_position_portion         0.60        0.35          -0.25
max_active_symbols                  3           3              0     ← 一致
breakeven_trigger_pnl_ratio         0.008       0.008          0     ← 一致
breakeven_lock_ratio                0.002       0.002          0     ← 一致
```

---

## 审阅总结（findings first）

| 优先级 | 问题 | 核心影响 | 状态 |
|---|---|---|---|
| CRITICAL | backtest profile ≠ live params | 回测无法代表实盘 | 必须修复才能决策 |
| CRITICAL | breakeven 0.8%→0.2% 切碎 runner | 80% 盈利单只赚 0.2% | 必须验证是否改善 |
| HIGH | light_tp + hard_exit 叠加效应 | live runner 利润被截断 70%+ | 需模拟并验证 |
| HIGH | flip_bullish 0.23% 通过率 | 负贡献路径在消耗容量 | 建议临时屏蔽 |
| HIGH | IOC 58% 取消 + 零 fallback | Alpha 系统性泄漏 | 执行优化优先 |
| MEDIUM | circuit_breaker 2连亏触发 | 可能误杀好信号窗口 | 调整参数 |
| MEDIUM | pretrade_gate disabled 状态 | 一旦启用影响未知 | 不要轻易启用 |
| LOW | capacity competition 71 dropped | 部分优质信号被容量卡 | max_symbols=4 可测 |

**下一步行动优先级**：

```
1. 跑 strict_live_mode 回测 → 建立真实基准     [今天]
2. 跑 breakeven 消融实验     → 找最优 runner 设定 [本周]
3. 临时屏蔽 flip_bullish      → 清理噪音路径      [今天可做]
4. 验证 light_tp 对 runner 影响 → 量化 live gap    [本周]
5. 建立 CI 对齐检查           → 防止未来漂移      [下次迭代]
```

---

*审阅人: Claude Sonnet 4.6*  
*审阅日期: 2026-04-29*  
*注: 本报告基于 review.md 文档及回测 artifacts 描述推导，代码级细节需与实际源码交叉验证*
