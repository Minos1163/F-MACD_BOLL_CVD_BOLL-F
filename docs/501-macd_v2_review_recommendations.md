# MACD V2 策略评审建议报告
> 基于 2026-02-23 ~ 2026-03-24 / 30天回测 · 44.37% / WR 87.23% / PF 7.20 / MDD 6.11%

---

## 目录

1. [评审摘要与优先级矩阵](#1-评审摘要与优先级矩阵)
2. [Issue-1：flip_bullish 应当退出主链路](#issue-1flip_bullish-应当退出主链路)
3. [Issue-2：4h_shrink_exit 单点依赖风险](#issue-2-4h_shrink_exit-单点依赖风险)
4. [Issue-3：IOC 成交效率瓶颈](#issue-3-ioc-成交效率瓶颈)
5. [Issue-4：max_active_symbols 容量天花板](#issue-4-max_active_symbols-容量天花板)
6. [Issue-5：pretrade_risk_gate 启用建议](#issue-5-pretrade_risk_gate-启用建议)
7. [配置 DIFF 总览](#7-配置-diff-总览)
8. [迭代测试协议](#8-迭代测试协议)

---

## 1. 评审摘要与优先级矩阵

### 当前核心指标

```
初始资金:         10,000
期末资金:         14,437.36
收益率:           +44.37%
胜率:             87.23%   ← 显著高于目标 75%
Profit Factor:    7.20
最大回撤:          6.11%
总成交:           94 笔
IOC 取消:         130 笔  ← 取消率 58%，值得关注
```

### 结构性隐患

```
盈利结构:
  4h_shrink_exit  贡献  +4846.70  (16 笔,  约 104% 毛利润)
  stop_loss       消耗   -182.77  (78 笔,  均为小亏)
  
  => 系统实质上是:
     "用 78 次小止损换 16 次大趋势段"
     任何导致 shrink_exit 失效的市场结构变化
     都会直接导致整体盈利归零
```

### 优先级矩阵

```
Priority  Issue                         Risk Impact   Effort   Recommended Action
────────  ────────────────────────────  ────────────  ───────  ──────────────────
P0        flip_bullish 入场簇负 alpha    负收益拖累     低       禁用或隔离
P1        4h_shrink_exit 单点依赖        回撤风险       中       添加补充退出路径
P2        IOC 取消率 58%               产能损失        中       启用 GTC fallback
P3        max_active_symbols=3          收益上限       低       消融测试后扩展
P4        pretrade_risk_gate 未启用      尾部风险       高       分阶段启用
```

---

## Issue-1：flip_bullish 应当退出主链路

### 数据归因

```
flip_bullish 链路漏斗:

  observed_signals        = 2,652   (100.00%)
  passed_threshold        =     6   (  0.23%)   ← 放行率极低
  blocked_by_sniper       =   396   ( 14.93%)
  blocked_by_capacity     =     1
  ioc_canceled            =     1
  actual_filled           =     4   (  0.15%)
  
  filled_4_trades_pnl     = -79.02  ← 放出来也不赚钱
  flip_bullish_win_rate   = 50%     ← vs 系统平均 87%
  
结论:
  sniper + cooling 两道门把样本缩到极小
  但并没有把剩余样本筛成高质量 alpha
  这是"样本数量收缩" 而非 "样本质量提升"
```

### 建议 — 三步处置

**Step A：先禁用，观察全局 WR 变化**

```pseudocode
# 伪代码：flip_bullish 禁用隔离逻辑
# 文件: src/fund_flow/decision_engine.py

function evaluate_entry_cluster(signal, config):

    cluster = signal.cluster_type   # e.g. "flip_bullish", "red_bar_growing", ...

    # ──────────────────────────────────────────────
    # [NEW] flip_bullish 禁用开关
    # ──────────────────────────────────────────────
    if cluster == "flip_bullish":
        if config.entry_filters.disable_flip_bullish_entries == true:
            log.debug("flip_bullish: disabled by config, skip evaluation")
            counter.increment("blocked_flip_bullish_disabled")
            return Decision.NEUTRAL
        endif
    endif

    # 原有逻辑继续...
    score = compute_signal_score(signal, config)
    threshold = config.entry_thresholds.get(cluster, config.entry_thresholds.default)

    if score < threshold:
        counter.increment("blocked_neutral_signal")
        return Decision.NEUTRAL
    endif

    return Decision.ENTRY(score=score, cluster=cluster)

end function
```

**Step B：若禁用后全局 WR 上升，正式移除**

```pseudocode
# 伪代码：ablation 测试流程
# 文件: scripts/ablation_flip_bullish.py

function run_flip_bullish_ablation():

    DATE_RANGE = ("2026-02-23", "2026-03-24T23:59:59")
    BASE_CONFIG = load_config("config/trading_config_fund_flow.json")

    configs = {
        "baseline":              BASE_CONFIG,
        "flip_bullish_disabled": BASE_CONFIG.with({
            "entry_filters.disable_flip_bullish_entries": true
        }),
        "flip_bullish_score_raised": BASE_CONFIG.with({
            "entry_thresholds.flip_bullish": 0.80,   # 从 0.64 大幅上调
            "entry_filters.flip_bullish_require_pullback_bounce": true,
            "entry_filters.enable_flip_bullish_strict_filter": true
        }),
    }

    results = {}
    for name, cfg in configs.items():
        r = run_backtest(cfg, DATE_RANGE)
        results[name] = {
            "total_return":   r.total_return,
            "win_rate":       r.win_rate,
            "total_trades":   r.total_trades,
            "profit_factor":  r.profit_factor,
            "max_drawdown":   r.max_drawdown,
            "flip_bullish_n": r.trades_by_cluster.get("flip_bullish", 0),
            "flip_bullish_pnl": r.pnl_by_cluster.get("flip_bullish", 0.0),
        }

    print_comparison_table(results)

    # 决策规则:
    # IF disabled_version.win_rate >= baseline.win_rate
    # AND disabled_version.total_return >= baseline.total_return - 0.5%
    # THEN: confirm disable, proceed to config change
    # ELSE: investigate raised_threshold_version
    
    decision = decide(results)
    return decision

end function
```

**Step C（如果选择保留但收紧）：高质量 flip_bullish 筛选器**

```pseudocode
# 伪代码：flip_bullish 强化筛选器
# 文件: src/fund_flow/decision_engine.py

function evaluate_flip_bullish_entry(signal, config):

    filters = config.entry_filters
    score   = signal.score

    # ── 门槛 1: 基础分数阈值提升至 0.80 ──────────────────
    HARD_THRESHOLD = 0.80    # 原 0.64，大幅提升
    if score < HARD_THRESHOLD:
        counter.increment("flip_bullish_blocked_hard_threshold")
        return Decision.NEUTRAL
    endif

    # ── 门槛 2: 1h RSI 结构确认 ──────────────────────────
    rsi_1h = signal.indicators.rsi_1h
    if rsi_1h > 65.0:    # 过热区，拒绝
        counter.increment("flip_bullish_blocked_rsi_hot")
        return Decision.NEUTRAL
    endif
    if rsi_1h < 25.0:    # 过度超卖弹升，风险高
        counter.increment("flip_bullish_blocked_rsi_oversold_bounce")
        return Decision.NEUTRAL
    endif

    # ── 门槛 3: 必须有 15m spring 确认 ───────────────────
    has_spring = signal.indicators.has_15m_spring
    if NOT has_spring:
        counter.increment("flip_bullish_blocked_no_spring")
        return Decision.NEUTRAL
    endif

    # ── 门槛 4: 4h 必须有 momentum reset ─────────────────
    momentum_reset_bars_ago = signal.indicators.momentum_reset_bars_ago
    if momentum_reset_bars_ago is None OR momentum_reset_bars_ago > 6:
        # 原配置允许 12 bars，这里收紧到 6
        counter.increment("flip_bullish_blocked_stale_reset")
        return Decision.NEUTRAL
    endif

    # ── 门槛 5: VWAP 位置必须在支撑区 ────────────────────
    vwap_score = signal.indicators.vwap_score
    VWAP_MIN   = 0.40    # 原 0.0（不要求），现在要求明确支撑
    if vwap_score < VWAP_MIN:
        counter.increment("flip_bullish_blocked_vwap_weak")
        return Decision.NEUTRAL
    endif

    # ── 门槛 6: 仓位缩减，限制风险敞口 ──────────────────
    # flip_bullish 单独用小仓位
    POSITION_SCALE = 0.50    # 只开标准仓位的 50%
    signal.position_scale_override = POSITION_SCALE

    counter.increment("flip_bullish_passed_all_gates")
    return Decision.ENTRY(score=score, cluster="flip_bullish")

end function
```

### 配置 DIFF — flip_bullish 方向

```diff
# config/trading_config_fund_flow.json
# fund_flow.macd_mtf_strategy_v2.entry_filters

  "entry_filters": {

+   "disable_flip_bullish_entries": true,      // [NEW] 第一阶段先禁用
    
    // 若选择保留(高质量筛选路径):
-   "flip_bullish_min_vwap_score": 0.0,
+   "flip_bullish_min_vwap_score": 0.40,
    
-   "enable_flip_bullish_strict_filter": false,
+   "enable_flip_bullish_strict_filter": true,
    
-   "enable_flip_bullish_cvd_context_filter": false,
+   "enable_flip_bullish_cvd_context_filter": true,
    
    "flip_bullish_sniper": {
-     "momentum_reset_max_bars_ago": 12,
+     "momentum_reset_max_bars_ago": 6,
      ...
    },
    
    "flip_bullish_cooling": {
-     "reject_if_1h_rsi_above": 75.0,
+     "reject_if_1h_rsi_above": 65.0,
      
-     "reject_if_15m_no_spring_and_rsi_high": false,
+     "reject_if_15m_no_spring_and_rsi_high": true,
      
-     "reject_if_15m_rsi_above": 65,
+     "reject_if_15m_rsi_above": 60,
    }
  }

# fund_flow.macd_mtf_strategy_v2.entry_thresholds
-   "flip_bullish": 0.64,
+   "flip_bullish": 0.80,   // 仅在不禁用时生效
```

---

## Issue-2：4h_shrink_exit 单点依赖风险

### 数据归因

```
退出结构分析:

  stop_loss_intrabar: 78 笔  PnL = -182.77    avg = -2.34/笔
  4h_shrink_exit:     16 笔  PnL = +4846.70   avg = +302.92/笔

  集中度:
    16 笔 shrink_exit / 94 笔总成交 = 17% 的成交笔数
    贡献了接近 104% 的毛盈利

  隐含风险:
    如果未来 16 笔 shrink_exit 其中 6 笔失效（变成平手）
    整体 30 天收益可能从 +44% 跌至 +7% 甚至更低

    shrink_exit 依赖:
    - 4h MACD histogram 连续收缩 2+ 根
    - 且持仓有浮盈
    这在震荡/横盘市中容易被提前触发，在趋势延续市中也可能过早离场
```

### 建议 — 添加补充退出路径

**Path A：RSI 过热退出（趋势提前结束保护）**

```pseudocode
# 伪代码：RSI 过热退出信号
# 文件: src/fund_flow/exit_engine.py

function check_rsi_overheat_exit(position, market_data, config):
    """
    当 1h RSI 进入过热区且 MACD momentum 开始衰减时，
    主动退出一部分仓位，而不是等待 4h shrink 触发
    """

    exit_cfg = config.exit_filters.rsi_overheat_exit
    if NOT exit_cfg.enabled:
        return ExitSignal.NONE
    endif

    # ── 条件 1: 持仓已有足够浮盈 ─────────────────────────
    MIN_MFE = exit_cfg.min_mfe_to_trigger    # 建议 0.012 (1.2%)
    current_mfe = position.max_favorable_excursion
    if current_mfe < MIN_MFE:
        return ExitSignal.NONE
    endif

    # ── 条件 2: 1h RSI 进入过热区 ───────────────────────
    rsi_1h = market_data.rsi_1h
    RSI_HOT_THRESHOLD = exit_cfg.rsi_1h_overheat    # 建议 78.0
    if rsi_1h < RSI_HOT_THRESHOLD:
        return ExitSignal.NONE
    endif

    # ── 条件 3: 1h MACD momentum 衰减 ────────────────────
    macd_hist_1h_current  = market_data.macd_histogram_1h_current
    macd_hist_1h_prev     = market_data.macd_histogram_1h_prev
    momentum_declining    = (macd_hist_1h_current < macd_hist_1h_prev)
    if NOT momentum_declining:
        return ExitSignal.NONE
    endif

    # ── 触发：部分退出 ────────────────────────────────────
    PARTIAL_EXIT_RATIO = exit_cfg.partial_exit_ratio    # 建议 0.50
    
    return ExitSignal.PARTIAL_CLOSE(
        ratio   = PARTIAL_EXIT_RATIO,
        reason  = "rsi_overheat_momentum_decline",
        urgency = "normal"    # 非紧急，走 IOC，失败可等下一 bar
    )

end function
```

**Path B：1h MACD 翻向退出（早于 4h shrink 的预警）**

```pseudocode
# 伪代码：1h MACD 翻向提前退出
# 文件: src/fund_flow/exit_engine.py

function check_1h_macd_flip_exit(position, market_data, config):
    """
    4h shrink 退出等待 4h 收线，有时候错过最优退出点。
    增加 1h MACD 翻向的早期退出作为补充。
    只在浮盈超过阈值且仓位方向与 1h MACD 相反时触发。
    """

    exit_cfg = config.exit_filters.macd_1h_flip_exit
    if NOT exit_cfg.enabled:
        return ExitSignal.NONE
    endif

    # ── 持仓方向 vs 1h MACD 方向 ─────────────────────────
    position_is_long  = (position.direction == "LONG")
    macd_1h_bullish   = (market_data.macd_histogram_1h_current > 0)
    
    direction_conflict = (position_is_long AND NOT macd_1h_bullish) OR \
                         (NOT position_is_long AND macd_1h_bullish)

    if NOT direction_conflict:
        return ExitSignal.NONE
    endif

    # ── 翻向必须是明确翻（不是浮动误差）─────────────────
    FLIP_MIN_MAGNITUDE = exit_cfg.flip_min_magnitude    # 建议 0.0003
    hist_magnitude = abs(market_data.macd_histogram_1h_current)
    if hist_magnitude < FLIP_MIN_MAGNITUDE:
        return ExitSignal.NONE
    endif

    # ── 确认 bar 数：避免单 bar 假翻 ─────────────────────
    CONFIRM_BARS = exit_cfg.confirm_bars    # 建议 2
    consecutive_flip_bars = count_consecutive_flip_bars(
        position.direction,
        market_data.macd_histogram_1h_history,
        lookback = CONFIRM_BARS
    )
    if consecutive_flip_bars < CONFIRM_BARS:
        return ExitSignal.NONE
    endif

    # ── 浮盈保护：只有有浮盈才允许提前退出 ──────────────
    MIN_PROFIT = exit_cfg.min_profit_to_early_exit    # 建议 0.006
    current_pnl_ratio = position.unrealized_pnl / position.initial_margin
    if current_pnl_ratio < MIN_PROFIT:
        return ExitSignal.NONE
    endif

    # ── 触发：完全退出 ────────────────────────────────────
    return ExitSignal.FULL_CLOSE(
        reason  = "1h_macd_flip_confirmed",
        urgency = "high"    # 走优先 IOC，快速成交
    )

end function
```

**Path C：持仓时间超时退出（保底机制）**

```pseudocode
# 伪代码：持仓时间超时退出
# 文件: src/fund_flow/exit_engine.py

function check_holding_time_exit(position, market_data, config):
    """
    如果一笔仓位持仓超过 max_holding_hours 且浮盈很小，
    说明 4h_shrink 可能迟迟不触发，信号已经变质。
    """

    exit_cfg = config.exit_filters.holding_time_exit
    if NOT exit_cfg.enabled:
        return ExitSignal.NONE
    endif

    MAX_HOLD_HOURS = exit_cfg.max_holding_hours    # 建议 96 (4 天)
    hold_duration_hours = position.holding_duration_seconds / 3600

    if hold_duration_hours < MAX_HOLD_HOURS:
        return ExitSignal.NONE
    endif

    # ── 只在浮盈低迷时触发，不强平盈利仓位 ──────────────
    MIN_PNL_TO_KEEP = exit_cfg.min_pnl_to_hold    # 建议 0.005 (0.5%)
    current_pnl_ratio = position.unrealized_pnl / position.initial_margin
    
    if current_pnl_ratio >= MIN_PNL_TO_KEEP:
        # 仓位还在赚钱，允许继续等 shrink exit，不强制退出
        return ExitSignal.NONE
    endif

    # ── 触发：超时退出 ────────────────────────────────────
    return ExitSignal.FULL_CLOSE(
        reason  = "holding_time_timeout",
        urgency = "normal"
    )

end function
```

**退出引擎主函数整合**

```pseudocode
# 伪代码：退出信号聚合器
# 文件: src/fund_flow/exit_engine.py

function evaluate_all_exit_signals(position, market_data, config):
    """
    按优先级依次检查各退出条件
    高优先级信号优先执行，不叠加
    """

    # 优先级 1: 现有止损（保持不变）
    sl_signal = check_stop_loss(position, market_data, config)
    if sl_signal.is_triggered:
        return sl_signal
    endif

    # 优先级 2: 冲突保护状态机（保持不变）
    conflict_signal = check_conflict_protection(position, market_data, config)
    if conflict_signal.is_exit():
        return conflict_signal
    endif

    # 优先级 3: [EXISTING] 4h shrink exit
    shrink_signal = check_4h_shrink_exit(position, market_data, config)
    if shrink_signal.is_triggered:
        return shrink_signal
    endif

    # 优先级 4: [NEW] 1h MACD 翻向退出
    macd_flip_signal = check_1h_macd_flip_exit(position, market_data, config)
    if macd_flip_signal.is_triggered:
        return macd_flip_signal
    endif

    # 优先级 5: [NEW] RSI 过热部分退出
    rsi_heat_signal = check_rsi_overheat_exit(position, market_data, config)
    if rsi_heat_signal.is_triggered:
        return rsi_heat_signal
    endif

    # 优先级 6: [NEW] 持仓时间超时退出
    timeout_signal = check_holding_time_exit(position, market_data, config)
    if timeout_signal.is_triggered:
        return timeout_signal
    endif

    return ExitSignal.NONE

end function
```

### 配置 DIFF — 退出路径

```diff
# config/trading_config_fund_flow.json
# fund_flow.macd_mtf_strategy_v2.exit_filters

  "exit_filters": {
    
    // 现有 4h shrink exit (保持不变)
    "enable_4h_shrink_exit": true,
    "exit_4h_shrink_bars": 2,
    "exit_4h_min_shrink_pct": 0.20,
    "exit_4h_require_profit": true,

+   // [NEW] 1h MACD 翻向退出
+   "macd_1h_flip_exit": {
+     "enabled": true,
+     "confirm_bars": 2,
+     "flip_min_magnitude": 0.0003,
+     "min_profit_to_early_exit": 0.006
+   },

+   // [NEW] RSI 过热部分退出
+   "rsi_overheat_exit": {
+     "enabled": true,
+     "rsi_1h_overheat": 78.0,
+     "min_mfe_to_trigger": 0.012,
+     "partial_exit_ratio": 0.50
+   },

+   // [NEW] 持仓时间超时退出
+   "holding_time_exit": {
+     "enabled": true,
+     "max_holding_hours": 96,
+     "min_pnl_to_hold": 0.005
+   }
  }
```

---

## Issue-3：IOC 成交效率瓶颈

### 数据归因

```
执行漏斗:
  orders_submitted        = 224
  orders_filled           = 94   (42.0% 成交率)
  orders_canceled         = 130  (58.0% 取消率)
  
  cancel 原因:
    ioc_no_fill           = 130  (100% 是 IOC 流动性不足)
    market_fallback_attempted = 0
    market_fallback_filled    = 0

  当前退化配置:
    open_ioc_retry_times      = 3
    open_ioc_retry_step_bps   = 15   ← 每次滑点 +0.15%
    open_gtc_fallback_enabled = true ← 已开启但没用上
    open_market_fallback_enabled = true ← 已开启但 0 次触发

问题根因假设:
  (A) IOC 滑价范围 3 × 15bps = 45bps 仍然不够宽
  (B) GTC fallback 的触发条件过于苛刻
  (C) market fallback 的 metadata 条件未被满足
```

### 建议一：诊断 GTC/market fallback 未触发的原因

```pseudocode
# 伪代码：执行退化链路诊断
# 文件: scripts/diagnose_ioc_fallback.py

function diagnose_fallback_chain(trade_log_path, execution_log_path):
    """
    找出 130 笔 IOC 取消中，为何 GTC 和 market fallback 没有触发
    """

    canceled_orders = load_canceled_ioc_orders(trade_log_path)
    exec_logs       = load_execution_logs(execution_log_path)

    analysis = {
        "total_canceled":           0,
        "gtc_fallback_eligible":    0,
        "gtc_fallback_blocked_why": Counter(),
        "market_fallback_eligible": 0,
        "market_fallback_blocked_why": Counter(),
    }

    for order in canceled_orders:
        analysis["total_canceled"] += 1

        # 检查 GTC fallback 为何未触发
        exec_meta = exec_logs.get_for_order(order.order_id)

        if exec_meta.gtc_fallback_skipped:
            reason = exec_meta.gtc_skip_reason
            # 常见原因: "signal_expired", "score_too_low_at_retry",
            #           "market_condition_changed", "config_gate_block"
            analysis["gtc_fallback_blocked_why"][reason] += 1
        else:
            analysis["gtc_fallback_eligible"] += 1

        if exec_meta.market_fallback_skipped:
            reason = exec_meta.market_skip_reason
            # 常见原因: "metadata.allow_market_fallback=false",
            #           "priority_exec_expired", "volatility_gate"
            analysis["market_fallback_blocked_why"][reason] += 1
        else:
            analysis["market_fallback_eligible"] += 1

    print_analysis_report(analysis)
    
    # 期望输出示例:
    # gtc_fallback_blocked_why:
    #   signal_expired: 89           ← 信号过期是主因
    #   score_too_low_at_retry: 28   ← 重试时分数已降
    #   config_gate_block: 13
    
    return analysis

end function
```

### 建议二：扩大 IOC 滑价范围 + 动态重试

```pseudocode
# 伪代码：动态 IOC 重试策略
# 文件: src/fund_flow/execution_router.py

function try_open_with_dynamic_ioc(decision, config):
    """
    根据信号分数动态决定 IOC 滑价范围，
    高分信号宽容更多滑价换取成交确定性
    """

    signal_score = decision.signal_score
    base_step_bps = config.execution.open_ioc_retry_step_bps    # 当前 15bps

    # ── 动态滑价步长：高分信号允许更宽滑价 ──────────────
    if signal_score >= 0.90:
        step_bps = base_step_bps * 2    # 30bps/retry，优先成交
        max_retries = 4
    elif signal_score >= 0.80:
        step_bps = base_step_bps * 1.5  # 22bps/retry
        max_retries = 3
    else:
        step_bps = base_step_bps        # 15bps/retry（原逻辑）
        max_retries = 3
    endif

    # ── 最大总滑价上限保护 ────────────────────────────────
    MAX_TOTAL_SLIPPAGE_BPS = 60    # 绝对上限 0.60%
    max_retries = min(
        max_retries,
        floor(MAX_TOTAL_SLIPPAGE_BPS / step_bps)
    )

    # ── 执行 IOC 重试循环 ────────────────────────────────
    for attempt in range(1, max_retries + 1):

        price_adjustment = step_bps * attempt * 0.0001   # bps → pct
        
        if decision.direction == "LONG":
            limit_price = decision.reference_price * (1 + price_adjustment)
        else:
            limit_price = decision.reference_price * (1 - price_adjustment)
        endif

        result = place_ioc_order(
            symbol      = decision.symbol,
            direction   = decision.direction,
            quantity    = decision.quantity,
            limit_price = limit_price,
            timeout_ms  = 500
        )

        if result.is_filled:
            counter.increment("ioc_filled_attempt_" + str(attempt))
            return OrderResult.FILLED(result)
        endif

        log.debug(f"IOC attempt {attempt} no fill, adjusting price by {step_bps}bps")

    endfor

    # ── IOC 全部失败，尝试 GTC fallback ──────────────────
    if config.execution.open_gtc_fallback_enabled:
        gtc_result = try_gtc_fallback(decision, config)
        if gtc_result.is_filled:
            return gtc_result
        endif
    endif

    # ── GTC 也失败，检查 market fallback 条件 ────────────
    if should_use_market_fallback(decision, config):
        market_result = place_market_order(decision)
        return market_result
    endif

    return OrderResult.CANCELED(reason="ioc_no_fill_all_fallbacks_exhausted")

end function

function should_use_market_fallback(decision, config):
    """
    市价单 fallback 条件：
    只有高分信号且不是处于高波动期时才允许
    """

    if NOT config.execution.open_market_fallback_enabled:
        return false
    endif

    # 高分信号才值得用市价单追入
    MIN_SCORE_FOR_MARKET = 0.88
    if decision.signal_score < MIN_SCORE_FOR_MARKET:
        return false
    endif

    # 当前波动率不能太高（保护滑点）
    current_atr_ratio = get_current_atr_ratio(decision.symbol)
    MAX_ATR_FOR_MARKET = 3.0
    if current_atr_ratio > MAX_ATR_FOR_MARKET:
        return false
    endif

    return true

end function
```

### 建议三：优先执行路径的信号有效期延长

```pseudocode
# 伪代码：优先执行信号有效期逻辑
# 文件: src/fund_flow/decision_engine.py

function apply_priority_execution(decision, config):
    """
    当前 priority_exec_expire_seconds = 15
    对高分信号来说 15s 可能不够，特别是流动性差时段
    建议对 score >= 0.92 的 VIP 信号延长到 45s
    """

    priority_cfg = config.entry_filters.priority_execution

    score = decision.signal_score

    if score >= priority_cfg.priority_exec_vip_min_score:    # 0.92
        expire_seconds = priority_cfg.priority_exec_vip_expire_seconds    # 当前 30s
        # [CHANGE] 延长 VIP 到 45s
        # expire_seconds = 45

    elif score >= priority_cfg.priority_exec_min_score:    # 0.90
        expire_seconds = priority_cfg.priority_exec_expire_seconds    # 当前 15s
        # [CHANGE] 提高非 VIP 到 25s
        # expire_seconds = 25

    else:
        expire_seconds = 0    # 不走优先路径
    endif

    decision.expires_at = now() + expire_seconds
    decision.use_priority_execution = (expire_seconds > 0)

    return decision

end function
```

### 配置 DIFF — 执行路由

```diff
# config/trading_config_fund_flow.json
# fund_flow.execution

  "execution": {
-   "open_ioc_retry_times": 3,
+   "open_ioc_retry_times": 4,
    
-   "open_ioc_retry_step_bps": 15,
+   "open_ioc_retry_step_bps": 15,      // 基础不变，由动态逻辑覆盖
+   "open_ioc_max_total_slippage_bps": 60,    // [NEW] 上限保护
+   "open_ioc_dynamic_step_enabled": true,    // [NEW] 启用动态滑价
    
    "open_gtc_fallback_enabled": true,
    "open_market_fallback_enabled": true,
+   "open_market_fallback_min_score": 0.88,   // [NEW] 市价单分数门槛
+   "open_market_fallback_max_atr_ratio": 3.0, // [NEW] 波动率上限
  },

# fund_flow.macd_mtf_strategy_v2.entry_filters
  "priority_exec_expire_seconds": 15,
# 建议测试后改为:
+ "priority_exec_expire_seconds": 25,
  
  "priority_exec_vip_expire_seconds": 30,
# 建议测试后改为:
+ "priority_exec_vip_expire_seconds": 45,
```

---

## Issue-4：max_active_symbols 容量天花板

### 数据归因

```
容量约束实际影响:
  capacity_full_precheck_candidates = 116   ← 预检阶段被容量拒绝
  capacity_competition_dropped      = 71    ← 竞争淘汰
  总容量损耗                         = 187 次候选被阻
  
  信号漏斗:
    signals_generated        = 766
    candidate_entries        = 558  (73% 通过信号评分)
    orders_submitted         = 224  (40% 通过容量)  ← 60% 在容量层损失
    orders_filled            = 94
  
  当前 max_active_symbols = 3
  
问题:
  在当前 30 天窗口中，有 187 个候选被容量杀死。
  如果这些候选的 alpha 质量接近成交样本（WR 87%）
  扩容可以显著提升总收益，代价是更高的名义敞口
```

### 消融测试协议

```pseudocode
# 伪代码：max_active_symbols 消融测试
# 文件: scripts/ablation_capacity.py

function run_capacity_ablation():

    DATE_RANGE    = ("2026-02-23", "2026-03-24T23:59:59")
    BASE_CONFIG   = load_config("config/trading_config_fund_flow.json")

    test_configs = {}

    for max_symbols in [3, 4, 5, 6]:
        cfg = BASE_CONFIG.clone()
        cfg.set("fund_flow.max_active_symbols", max_symbols)
        
        # 注意：扩容时 reserve_pct 应相应下调避免名义资金不足
        # reserve_pct 逻辑:
        #   max_symbols=3: reserve=0.20 (每仓 ~26.7% 净资产)
        #   max_symbols=4: reserve=0.15 (每仓 ~21.3% 净资产)
        #   max_symbols=5: reserve=0.10 (每仓 ~18.0% 净资产)
        #   max_symbols=6: reserve=0.05 (每仓 ~15.8% 净资产)
        
        reserve_pct = max(0.05, 0.20 - (max_symbols - 3) * 0.05)
        cfg.set("fund_flow.reserve_pct", reserve_pct)
        
        test_configs[f"max_{max_symbols}_symbols"] = cfg

    results = {}
    for name, cfg in test_configs.items():
        r = run_backtest(cfg, DATE_RANGE)
        results[name] = {
            "total_return":         r.total_return,
            "win_rate":             r.win_rate,
            "total_trades":         r.total_trades,
            "max_drawdown":         r.max_drawdown,
            "profit_factor":        r.profit_factor,
            "capacity_blocked":     r.capacity_full_precheck_candidates,
            "competition_dropped":  r.capacity_competition_dropped,
            "max_concurrent":       r.max_simultaneous_positions,
        }

    print_comparison_table(results)

    # 决策规则:
    # Accept 扩容条件:
    #   1. max_drawdown <= 10%  (当前 6.11%，预留空间)
    #   2. win_rate >= 82%      (允许小幅下降)
    #   3. total_return >= 当前 44% 的 110%  → >= 48.4%
    # 
    # 如果 max=4 满足，则推进到 max=5 的测试

    for name, r in sorted(results.items(), key=lambda x: x[1]["total_return"], reverse=True):
        accept = (
            r["max_drawdown"] <= 0.10 AND
            r["win_rate"] >= 0.82 AND
            r["total_return"] >= 0.484
        )
        print(f"{name}: return={r['total_return']:+.2%}  wr={r['win_rate']:.2%}  "
              f"mdd={r['max_drawdown']:.2%}  {'✓ ACCEPT' if accept else '✗ REJECT'}")

    return results

end function
```

### 扩容后的仓位竞争算法优化

```pseudocode
# 伪代码：多槽位竞争排序逻辑
# 文件: src/fund_flow/decision_engine.py

function rank_competing_candidates(candidates, available_slots, config):
    """
    当多个候选信号同时竞争有限槽位时，
    按综合评分排序，而非先到先得
    """

    if len(candidates) <= available_slots:
        # 候选数不超过槽位，全部通过
        return candidates, []
    endif

    # ── 计算综合竞争分数 ─────────────────────────────────
    for cand in candidates:
        
        base_score   = cand.signal_score

        # 加权因子 1：信号簇质量权重
        CLUSTER_BONUS = {
            "flip_bearish":    +0.05,    # 历史胜率最高
            "red_bar_growing": +0.02,    # 主力信号
            "flip_bullish":    -0.10,    # 质量差（若保留则降权）
        }
        cluster_adj  = CLUSTER_BONUS.get(cand.cluster, 0.0)

        # 加权因子 2：当前持仓分散度（防止同方向集中）
        existing_long_count  = count_open_positions("LONG")
        existing_short_count = count_open_positions("SHORT")
        
        if cand.direction == "LONG" AND existing_long_count >= 2:
            direction_penalty = -0.03    # 已有 2 个多单，降权
        elif cand.direction == "SHORT" AND existing_short_count >= 2:
            direction_penalty = -0.03
        else:
            direction_penalty = 0.0
        endif

        # 加权因子 3：币种质量（基于历史 30 天）
        symbol_hist_wr = get_symbol_historical_winrate(cand.symbol, lookback_days=30)
        symbol_bonus   = max(-0.05, min(+0.05, (symbol_hist_wr - 0.80) * 0.5))

        cand.competition_score = base_score + cluster_adj + direction_penalty + symbol_bonus

    endfor

    # ── 按竞争分数排序，选取 top-N ───────────────────────
    ranked    = sorted(candidates, key=lambda c: c.competition_score, reverse=True)
    accepted  = ranked[:available_slots]
    dropped   = ranked[available_slots:]

    for d in dropped:
        counter.increment("capacity_competition_dropped")
        log.debug(f"Dropped {d.symbol}/{d.cluster} score={d.competition_score:.4f}")

    return accepted, dropped

end function
```

### 配置 DIFF — 容量扩展

```diff
# config/trading_config_fund_flow.json
# fund_flow

- "max_active_symbols": 3,
+ "max_active_symbols": 4,       // 消融测试通过后改为 4，再评估 5

- "reserve_pct": 0.20,
+ "reserve_pct": 0.15,           // 对应 max=4 的调整

  // 竞争排序增强 (新增)
+ "competition_ranking": {
+   "enabled": true,
+   "cluster_bonus_map": {
+     "flip_bearish": 0.05,
+     "red_bar_growing": 0.02,
+     "flip_bullish": -0.10
+   },
+   "direction_concentration_penalty": 0.03,
+   "symbol_history_lookback_days": 30
+ }
```

---

## Issue-5：pretrade_risk_gate 启用建议

### 当前状态

```
pretrade_risk_gate:
  enabled = false    ← 完全旁路，不参与当前回测结果

该门的作用:
  综合 trend / momentum / volatility / drawdown / equity_fraction / leverage
  做入场与持仓前置判断

风险分析:
  本次 30 天未启用该门仍有良好表现，
  但这可能是因为回测窗口（2026-02-23 ~ 2026-03-24）
  恰好是相对友好的趋势性行情。
  
  在横盘或高波动行情下，不启用该门可能导致:
  - 连续信号进入高波动期，触发连环止损
  - max_consecutive_losses=2 的熔断被快速触发
  - 实盘出现 >10% 的单日回撤
```

### 建议——分阶段启用

**阶段 1：只启用入场阻断，不启用强制平仓**

```pseudocode
# 伪代码：pretrade_risk_gate 分阶段启用
# 文件: src/app/fund_flow_bot.py

function _apply_pretrade_risk_gate(decision, account_state, market_context, config):
    """
    分阶段启用策略:
    Phase 1 (当前建议): 只做入场阻断，不强制平仓
    Phase 2 (后续):     加入持仓风控和强制减仓
    """

    gate_cfg = config.fund_flow.pretrade_risk_gate

    if NOT gate_cfg.enabled:
        return decision    # 旁路，原样返回

    # ── 计算综合风险评分 ─────────────────────────────────
    risk_score = compute_risk_score(account_state, market_context, gate_cfg)

    # risk_score 组成:
    #   trend_score     = 当前趋势评分        weight = 0.45
    #   momentum_score  = 动量评分            weight = 0.30
    #   volatility_score= 波动率惩罚          weight = 0.20
    #   drawdown_score  = 回撤惩罚            weight = 0.35
    
    # ── Phase 1: 入场阻断（只阻止开新仓）────────────────
    if decision.action == "OPEN":
        
        # 条件 A：波动率过高
        current_volatility = market_context.get_volatility(decision.symbol)
        if current_volatility > gate_cfg.volatility_cap:    # 0.012
            log.info(f"Pretrade gate: BLOCK open {decision.symbol}, "
                     f"volatility {current_volatility:.4f} > cap {gate_cfg.volatility_cap}")
            counter.increment("pretrade_gate_blocked_volatility")
            decision.action = "BLOCK"
            return decision
        endif

        # 条件 B：当日已达最大回撤
        daily_drawdown = account_state.daily_drawdown_pct
        if daily_drawdown > gate_cfg.max_drawdown:    # 0.02 = 2%
            log.info(f"Pretrade gate: BLOCK open, daily_drawdown {daily_drawdown:.2%} "
                     f"> max {gate_cfg.max_drawdown:.2%}")
            counter.increment("pretrade_gate_blocked_drawdown")
            decision.action = "BLOCK"
            return decision
        endif

        # 条件 C：综合风险评分过低
        if risk_score < gate_cfg.entry_threshold:    # 0.06
            log.info(f"Pretrade gate: BLOCK open {decision.symbol}, "
                     f"risk_score {risk_score:.4f} < threshold {gate_cfg.entry_threshold}")
            counter.increment("pretrade_gate_blocked_risk_score")
            decision.action = "BLOCK"
            return decision
        endif

    endif

    # ── Phase 2 (暂不启用): 强制平仓 ────────────────────
    # if decision.action == "HOLD" or has_open_position(decision.symbol):
    #     if risk_score < gate_cfg.exit_score_threshold:
    #         decision.action = "FORCE_EXIT"
    #         ...
    # endif

    return decision

end function

function compute_risk_score(account_state, market_context, gate_cfg):
    """
    计算当前市场综合风险评分
    分数越高表示越适合入场
    """

    # ── 趋势得分 ─────────────────────────────────────────
    # 用 4h MACD 方向 + 1h 确认得出趋势强度
    trend_signal  = market_context.trend_alignment_score    # 0.0 ~ 1.0
    trend_score   = trend_signal * gate_cfg.trend_weight    # * 0.45

    # ── 动量得分 ─────────────────────────────────────────
    momentum_raw    = market_context.momentum_normalized    # 0.0 ~ 1.0
    momentum_score  = momentum_raw * gate_cfg.momentum_weight    # * 0.30

    # ── 波动率惩罚 ───────────────────────────────────────
    volatility_ratio = market_context.volatility / gate_cfg.volatility_cap
    volatility_score = max(0.0, 1.0 - volatility_ratio) * gate_cfg.volatility_weight

    # ── 回撤惩罚 ─────────────────────────────────────────
    drawdown_ratio = account_state.daily_drawdown_pct / gate_cfg.max_drawdown
    drawdown_score = max(0.0, 1.0 - drawdown_ratio) * gate_cfg.drawdown_weight

    raw_score = trend_score + momentum_score + volatility_score + drawdown_score
    
    # 归一化到 0 ~ 1（各权重之和 = 1.30，这里不做归一化保持原始逻辑）
    return raw_score

end function
```

**Gate 监控：上线前先运行 Shadow Mode**

```pseudocode
# 伪代码：shadow mode 监控
# 文件: src/app/fund_flow_bot.py

function _apply_pretrade_risk_gate_shadow(decision, account_state, market_context, config):
    """
    Shadow Mode: 逻辑正常运行，但不实际阻断交易
    只记录"如果启用了 gate，会有什么效果"
    """

    shadow_cfg = config.fund_flow.pretrade_risk_gate.clone()
    shadow_cfg.enabled = true    # 强制启用，但结果不影响实际决策

    shadow_decision = decision.clone()
    result = _apply_pretrade_risk_gate(shadow_decision, account_state, market_context, shadow_cfg)

    if result.action != decision.action:
        # Gate 会改变决策，记录下来
        shadow_log.record({
            "timestamp":       now(),
            "symbol":          decision.symbol,
            "original_action": decision.action,
            "gate_would_do":   result.action,
            "gate_reason":     result.block_reason,
            "signal_score":    decision.signal_score,
        })
        counter.increment("shadow_gate_would_have_blocked")
    endif

    return decision    # 返回原始决策，不受 gate 影响

end function
```

**启用建议：回测验证 gate 对 WR 和收益的影响**

```pseudocode
# 伪代码：gate 启用影响测试
# 文件: scripts/test_pretrade_gate_impact.py

function test_gate_impact():

    DATE_RANGE  = ("2026-02-23", "2026-03-24T23:59:59")
    BASE_CONFIG = load_config("config/trading_config_fund_flow.json")

    configs = {
        "gate_disabled":  BASE_CONFIG,    # 当前状态
        "gate_phase1": BASE_CONFIG.with({
            "fund_flow.pretrade_risk_gate.enabled": true,
            "fund_flow.pretrade_risk_gate.force_exit_on_gate": false,  # Phase 1 不强平
        }),
        "gate_phase1_tightened": BASE_CONFIG.with({
            "fund_flow.pretrade_risk_gate.enabled": true,
            "fund_flow.pretrade_risk_gate.force_exit_on_gate": false,
            "fund_flow.pretrade_risk_gate.volatility_cap": 0.010,      # 更严格
            "fund_flow.pretrade_risk_gate.max_drawdown": 0.015,
        }),
    }

    for name, cfg in configs.items():
        r = run_backtest(cfg, DATE_RANGE)
        print(f"{name}: return={r.total_return:+.2%}  wr={r.win_rate:.2%}  "
              f"trades={r.total_trades}  mdd={r.max_drawdown:.2%}  "
              f"gate_blocked={r.pretrade_gate_blocked_count}")

    # 决策规则:
    # 如果 gate_phase1 相比 gate_disabled:
    #   total_return >= gate_disabled.total_return * 0.95    (损失 < 5%)
    #   win_rate >= gate_disabled.win_rate                   (WR 不降)
    #   max_drawdown < gate_disabled.max_drawdown            (回撤改善)
    # 则: 启用 gate_phase1

end function
```

### 配置 DIFF — pretrade_risk_gate

```diff
# config/trading_config_fund_flow.json
# fund_flow.pretrade_risk_gate

  "pretrade_risk_gate": {
-   "enabled": false,
+   "enabled": true,            // 回测验证后启用

-   "force_exit_on_gate": true,
+   "force_exit_on_gate": false,  // Phase 1: 不强制平仓

+   "shadow_mode": false,       // 上线前先设为 true 做影子观测

    "entry_block_actions": ["EXIT", "BLOCK", "AVOID"],
    "volatility_cap": 0.012,
    "max_drawdown": 0.02,
    
+   // Phase 1 只检查入场，跳过出场逻辑
+   "phase1_entry_only": true
  }
```

---

## 6. 完整 config DIFF（汇总）

```diff
# config/trading_config_fund_flow.json
{
  "fund_flow": {

    // ── 容量扩展 ──────────────────────────────────────────
-   "max_active_symbols": 3,
+   "max_active_symbols": 4,

-   "reserve_pct": 0.20,
+   "reserve_pct": 0.15,

    // ── 仓位参数（不变）─────────────────────────────────
    "default_target_portion": 0.35,
    "max_symbol_position_portion": 0.35,

    // ── pretrade_risk_gate ────────────────────────────────
    "pretrade_risk_gate": {
-     "enabled": false,
-     "force_exit_on_gate": true,
+     "enabled": true,
+     "force_exit_on_gate": false,
+     "shadow_mode": false,
+     "phase1_entry_only": true
    },

+   // ── 竞争排序 ───────────────────────────────────────────
+   "competition_ranking": {
+     "enabled": true,
+     "cluster_bonus_map": {
+       "flip_bearish": 0.05,
+       "red_bar_growing": 0.02,
+       "flip_bullish": -0.10
+     }
+   },

    "macd_mtf_strategy_v2": {

      // ── entry_thresholds ──────────────────────────────
      "entry_thresholds": {
        "default": 0.68,
        "min_signal_score": 0.68,
        
-       "flip_bullish": 0.64,
+       "flip_bullish": 0.80,     // 若保留 flip_bullish 则提高门槛
      },

      // ── entry_filters ────────────────────────────────
      "entry_filters": {
        
+       "disable_flip_bullish_entries": true,    // Phase 1: 先禁用

        "flip_bullish_cooling": {
-         "reject_if_1h_rsi_above": 75.0,
+         "reject_if_1h_rsi_above": 65.0,

-         "reject_if_15m_no_spring_and_rsi_high": false,
+         "reject_if_15m_no_spring_and_rsi_high": true,

-         "reject_if_15m_rsi_above": 65,
+         "reject_if_15m_rsi_above": 60,
        },

        "flip_bullish_sniper": {
-         "momentum_reset_max_bars_ago": 12,
+         "momentum_reset_max_bars_ago": 6,
        },

-       "flip_bullish_min_vwap_score": 0.0,
+       "flip_bullish_min_vwap_score": 0.40,

-       "enable_flip_bullish_strict_filter": false,
+       "enable_flip_bullish_strict_filter": true,

-       "enable_flip_bullish_cvd_context_filter": false,
+       "enable_flip_bullish_cvd_context_filter": true,

        // ── 优先执行有效期延长 ─────────────────────────
-       "priority_exec_expire_seconds": 15,
+       "priority_exec_expire_seconds": 25,

-       "priority_exec_vip_expire_seconds": 30,
+       "priority_exec_vip_expire_seconds": 45,
      },

      // ── exit_filters ─────────────────────────────────
      "exit_filters": {
        
        // 现有 4h shrink (保持)
        "enable_4h_shrink_exit": true,
        "exit_4h_shrink_bars": 2,
        "exit_4h_min_shrink_pct": 0.20,
        "exit_4h_require_profit": true,

+       // [NEW] 1h MACD 翻向退出
+       "macd_1h_flip_exit": {
+         "enabled": true,
+         "confirm_bars": 2,
+         "flip_min_magnitude": 0.0003,
+         "min_profit_to_early_exit": 0.006
+       },

+       // [NEW] RSI 过热部分退出
+       "rsi_overheat_exit": {
+         "enabled": true,
+         "rsi_1h_overheat": 78.0,
+         "min_mfe_to_trigger": 0.012,
+         "partial_exit_ratio": 0.50
+       },

+       // [NEW] 持仓时间超时退出
+       "holding_time_exit": {
+         "enabled": true,
+         "max_holding_hours": 96,
+         "min_pnl_to_hold": 0.005
+       }
      }
    }
  },

  // ── 执行路由 ──────────────────────────────────────────────
  "execution": {
-   "open_ioc_retry_times": 3,
+   "open_ioc_retry_times": 4,

    "open_ioc_retry_step_bps": 15,
+   "open_ioc_max_total_slippage_bps": 60,
+   "open_ioc_dynamic_step_enabled": true,

    "open_gtc_fallback_enabled": true,
    "open_market_fallback_enabled": true,
+   "open_market_fallback_min_score": 0.88,
+   "open_market_fallback_max_atr_ratio": 3.0,
  }
}
```

---

## 7. 配置 DIFF 总览

### 变更汇总表

```
变更项                               当前值         建议值         优先级  风险
────────────────────────────────────────────────────────────────────────────
disable_flip_bullish_entries         (不存在)       true           P0      低
max_active_symbols                   3             4              P3      中
reserve_pct                          0.20          0.15           P3      中
flip_bullish threshold               0.64          0.80           P0      低
flip_bullish_min_vwap_score          0.0           0.40           P0      低
enable_flip_bullish_strict_filter    false         true           P0      低
momentum_reset_max_bars_ago          12            6              P0      低
reject_if_1h_rsi_above               75.0          65.0           P0      低
reject_if_15m_no_spring_and_rsi_high false         true           P0      低
reject_if_15m_rsi_above              65            60             P0      低
pretrade_risk_gate.enabled           false         true           P4      高
pretrade_risk_gate.force_exit        true          false          P4      低
priority_exec_expire_seconds         15            25             P2      低
priority_exec_vip_expire_seconds     30            45             P2      低
open_ioc_retry_times                 3             4              P2      低
open_ioc_max_total_slippage_bps      (不存在)       60             P2      低
open_market_fallback_min_score       (不存在)       0.88           P2      低
macd_1h_flip_exit.enabled            (不存在)       true           P1      中
rsi_overheat_exit.enabled            (不存在)       true           P1      中
holding_time_exit.enabled            (不存在)       true           P1      低
```

---

## 8. 迭代测试协议

### 测试顺序（必须按顺序）

```pseudocode
# 伪代码：迭代测试主流程
# 原则: 每次只改一个方向，完整回测后再推进

function run_optimization_sequence():

    BASE_DATE_RANGE = ("2026-02-23", "2026-03-24T23:59:59")
    EXTENDED_RANGE  = ("2026-01-01", "2026-03-31T23:59:59")  # 更宽窗口验证稳健性

    BASELINE = run_backtest(load_config("config/trading_config_fund_flow.json"), BASE_DATE_RANGE)
    log_result("Step-0 Baseline", BASELINE)

    # ─────────────────────────────────────────────────────
    # Step 1: 禁用 flip_bullish  (P0, 低风险)
    # ─────────────────────────────────────────────────────
    cfg_1 = BASELINE.config.with({
        "entry_filters.disable_flip_bullish_entries": true
    })
    r1 = run_backtest(cfg_1, BASE_DATE_RANGE)
    log_result("Step-1 flip_bullish disabled", r1)

    # 验收标准:
    assert r1.win_rate >= BASELINE.win_rate - 0.02      # WR 不大幅下降
    assert r1.total_return >= BASELINE.total_return - 0.02  # 收益损失 < 2%

    # 因为 flip_bullish PnL = -79.02，禁用后预期收益略升
    # ─────────────────────────────────────────────────────
    
    # ─────────────────────────────────────────────────────
    # Step 2: 添加补充退出路径  (P1, 中风险)
    # ─────────────────────────────────────────────────────
    cfg_2 = r1.config.with({
        "exit_filters.macd_1h_flip_exit.enabled": true,
        "exit_filters.rsi_overheat_exit.enabled": true,
        "exit_filters.holding_time_exit.enabled": true,
    })
    r2 = run_backtest(cfg_2, BASE_DATE_RANGE)
    log_result("Step-2 + supplemental exits", r2)

    # 验收标准:
    # 新退出路径可能小幅降低最大单笔收益，但应改善 MDD 和稳定性
    assert r2.max_drawdown <= BASELINE.max_drawdown + 0.01   # MDD 不变差
    assert r2.profit_factor >= 5.0                           # PF 仍然强健

    # ─────────────────────────────────────────────────────
    # Step 3: IOC 执行优化  (P2, 低风险)
    # ─────────────────────────────────────────────────────
    cfg_3 = r2.config.with({
        "execution.open_ioc_retry_times": 4,
        "execution.open_ioc_dynamic_step_enabled": true,
        "execution.priority_exec_expire_seconds": 25,
        "execution.priority_exec_vip_expire_seconds": 45,
    })
    r3 = run_backtest(cfg_3, BASE_DATE_RANGE)
    log_result("Step-3 + IOC optimization", r3)

    # 验收标准:
    # IOC 优化应提升成交率，总成交笔数应上升
    assert r3.total_trades >= r2.total_trades    # 成交数不减少
    assert r3.ioc_cancel_rate <= r2.ioc_cancel_rate   # 取消率下降

    # ─────────────────────────────────────────────────────
    # Step 4: 容量扩展  (P3, 中风险)
    # ─────────────────────────────────────────────────────
    cfg_4 = r3.config.with({
        "fund_flow.max_active_symbols": 4,
        "fund_flow.reserve_pct": 0.15,
    })
    r4 = run_backtest(cfg_4, BASE_DATE_RANGE)
    log_result("Step-4 + max_symbols=4", r4)

    # 验收标准:
    assert r4.max_drawdown <= 0.10           # MDD 不超 10%
    assert r4.win_rate >= 0.82               # WR 保持
    assert r4.total_return >= r3.total_return * 1.10   # 收益提升 10%+

    # ─────────────────────────────────────────────────────
    # Step 5: pretrade_risk_gate Phase 1  (P4, 高风险)
    # 在更宽的日期范围内验证 (包含不同市场状态)
    # ─────────────────────────────────────────────────────
    cfg_5 = r4.config.with({
        "fund_flow.pretrade_risk_gate.enabled": true,
        "fund_flow.pretrade_risk_gate.force_exit_on_gate": false,
        "fund_flow.pretrade_risk_gate.phase1_entry_only": true,
    })
    r5 = run_backtest(cfg_5, EXTENDED_RANGE)   # 用更长窗口
    log_result("Step-5 + pretrade_gate Phase1 (3 month)", r5)

    # 验收标准:
    assert r5.win_rate >= 0.80               # WR 不大幅下降
    assert r5.max_drawdown <= 0.10           # MDD 改善
    assert r5.total_return >= r4.total_return * 0.90  # 容忍 10% 损失换更低回撤

    # ─────────────────────────────────────────────────────
    # 最终 sign-off 标准
    # ─────────────────────────────────────────────────────
    FINAL = r5
    sign_off = (
        FINAL.win_rate >= 0.82 AND
        FINAL.total_return >= 0.50 AND          # > 50% for 30d 基准窗口
        FINAL.max_drawdown <= 0.10 AND
        FINAL.profit_factor >= 5.0 AND
        FINAL.total_trades >= 80                # 样本量不能太小
    )

    if sign_off:
        print("✓ SIGN-OFF: All optimization steps verified, ready for live deployment")
    else:
        print("✗ NOT READY: Review failing metrics before deployment")
        print_failing_metrics(FINAL)
    endif

    return FINAL

end function
```

### 回滚协议

```pseudocode
# 伪代码：快速回滚机制
# 每个步骤的配置都应该版本化

function rollback_to_step(target_step):
    """
    如果某步骤上线后实盘出现问题，快速回滚到前一版本
    """

    CONFIG_SNAPSHOTS = {
        "step_0_baseline":  "config/snapshots/baseline_20260430.json",
        "step_1_no_flip":   "config/snapshots/step1_flip_disabled.json",
        "step_2_exits":     "config/snapshots/step2_supplemental_exits.json",
        "step_3_ioc":       "config/snapshots/step3_ioc_optimized.json",
        "step_4_capacity":  "config/snapshots/step4_max4_symbols.json",
        "step_5_gate":      "config/snapshots/step5_gate_phase1.json",
    }

    target_config = load_config(CONFIG_SNAPSHOTS[target_step])
    
    # 触发回滚:
    #   1. 关闭当前 bot 的开仓功能
    #   2. 等待现有仓位自然退出（或手动平仓）
    #   3. 切换配置文件
    #   4. 重启 bot

    apply_config_hot_reload(target_config)
    log.critical(f"ROLLBACK executed to {target_step}")

end function

# 实盘监控触发条件（任一触发则自动告警）:
LIVE_ALERT_RULES = {
    "consecutive_loss_3":        "3 连亏 → 通知",
    "daily_drawdown_5pct":       "当日回撤 > 5% → 告警",
    "ioc_fill_rate_below_30pct": "成交率 < 30% → 检查流动性",
    "win_rate_below_60pct_10t":  "最近 10 笔 WR < 60% → 质量下降",
    "gate_blocks_above_50pct":   "Gate 阻断率 > 50% → 市场环境恶化",
}
```

---

## 附录：关键指标对比预期

```
                        当前基准      Step-1       Step-2       Step-4
                        (baseline)   (no flip)    (+exits)     (+cap4)
─────────────────────────────────────────────────────────────────────────
Win Rate                87.23%       ≥88%         ≥85%         ≥82%
Total Return (30d)      +44.37%      ≥44.5%       ≥42%         ≥50%
Max Drawdown             6.11%       ≤6.11%       ≤6.5%        ≤10%
Profit Factor            7.20        ≥7.0         ≥5.5         ≥4.5
Total Trades            94           ≤94          ≤94          ≥100
IOC Cancel Rate         58.0%        58%          58%          ≤45%   (Step-3 影响)
flip_bullish PnL        -79.02       0 (disabled) 0            0
4h_shrink_exit PnL      +4846.70     +4846        +4200-4800   +5000+
flip_bearish PnL        +1555.09     +1555        +1555        +2000+
```

> 所有建议均需通过完整回测验证后才推进实盘。
> 请按 Issue-1 → Issue-2 → Issue-3 → Issue-4 → Issue-5 顺序执行，每步独立消融。
