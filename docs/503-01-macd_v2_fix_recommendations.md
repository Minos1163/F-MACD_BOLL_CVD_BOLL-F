# MACD V2 — 高胜率/低回报诊断与修复建议

> 日期: 2026-05-03 | 基准回测: strict-live 30d | 资本: $10,000
> 目标: 维持 ≥88% 胜率, 同时将 30d 回报从 +26% 提升至 +60%+

---

## 目录

1. [核心诊断结论](#1-核心诊断结论)
2. [优先级排序 (建议修复顺序)](#2-优先级排序)
3. [Fix A — 止损机制修复](#fix-a--止损机制修复)
4. [Fix B — sim_light_take_profit 降权](#fix-b--sim_light_take_profit-降权)
5. [Fix C — 分层止盈 (Tiered TP)](#fix-c--分层止盈-tiered-tp)
6. [Fix D — max_active_symbols 容量释放](#fix-d--max_active_symbols-容量释放)
7. [Fix E — IOC 填充策略改善](#fix-e--ioc-填充策略改善)
8. [Fix F — 符号风险分层](#fix-f--符号风险分层)
9. [消融实验脚本](#9-消融实验脚本)
10. [Config DIFF](#10-config-diff)
11. [执行顺序总结](#11-执行顺序总结)

---

## 1. 核心诊断结论

```text
┌─────────────────────────────────────────────────────────────────────┐
│  问题不在信号质量, 在于结构性三重压缩:                                  │
│                                                                     │
│  [1] 止损不受控  → 少数大亏(-3.8%)吃掉大量小赢积累                     │
│  [2] 止盈太早   → sim_light_take_profit 截断右尾, 赢=+0.25%           │
│  [3] 容量太紧   → 378个候选仅25.1%成交, 大量alpha在排队中消散           │
│                                                                     │
│  三个瓶颈叠加 → 91%胜率 + PF=3.55 → 仅+26.23%                        │
│  如果三个都修好 → 预估 88%+胜率 + PF=4.5+ → 目标+60%~+80%             │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 量化证据摘要

| 问题 | 当前数值 | 目标数值 | 影响量级 |
|------|---------|---------|---------|
| 平均盈/亏比 | 0.34x (27/81) | ≥ 0.8x | ★★★★★ |
| 最大单笔亏损 | -406 (占净利润14%) | < 150 | ★★★★★ |
| stop_loss_pct配置 vs 实际 | 0.5% vs -3.81% | 对齐 | ★★★★★ |
| 候选→成交转化率 | 25.1% | ≥ 45% | ★★★★☆ |
| sim_light_tp 占比 | 67/162=41% trades | ≤ 20% | ★★★★☆ |
| max_active_symbols | 3 | 5 | ★★★☆☆ |
| 做空交易占比 | 3.1% | 10%+ | ★★☆☆☆ |

---

## 2. 优先级排序

```text
第1优先级 (立刻): Fix A — 弄清止损实际执行机制, 硬限-1.5%价格亏损
第2优先级 (本周): Fix B+C — 拆分 sim_light_tp, 引入分层止盈
第3优先级 (本周): Fix D — max_active_symbols 3→5
第4优先级 (下周): Fix E — IOC → 限时GTC fallback
第5优先级 (下周): Fix F — 符号风险分层, 黑名单测试

绝对不要同时修改多个. 每次只改一个, 跑回测, 记录指标.
```

---

## Fix A — 止损机制修复

### A.1 问题定位

```
配置:  stop_loss_pct = 0.005  (0.5%)
实际:  最差亏损 = -3.81% 价格移动

可能原因 (按可能性排序):
  [A1] 回测用 bar 收盘价填止损, 不是止损价本身
  [A2] 存在动态止损覆盖 max_stop_loss_pct=0.025
  [A3] stop_loss_pct 仅控制初始止损距离,
       但持仓期间止损被 trailing 或 dynamic 调整为更宽
  [A4] 回测不模拟实际止损单, 仅在决策周期检查, 导致跳空穿越
```

### A.2 诊断伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: stop_loss_audit.py
# 目标: 确认止损实际触发逻辑和填充价格
# ════════════════════════════════════════════════════════════════

function audit_stop_loss_behavior(trades_csv, config):
    # 加载所有亏损交易
    losing_trades = load_trades(trades_csv).filter(pnl < 0)

    for trade in losing_trades:
        entry_price     = trade.entry_price
        exit_price      = trade.exit_price
        configured_stop = entry_price * (1 - config.stop_loss_pct)   # 0.5%止损价
        max_dyn_stop    = entry_price * (1 - config.max_stop_loss_pct) # 2.5%止损价

        actual_loss_pct = (exit_price - entry_price) / entry_price

        # 分类每笔亏损的止损触发原因
        if abs(actual_loss_pct) <= config.stop_loss_pct + 0.001:
            category = "OK: 正常止损"
        elif abs(actual_loss_pct) <= config.max_stop_loss_pct + 0.001:
            category = "WARN: 动态止损宽化 (0.5%→2.5%区间)"
        else:
            category = "CRITICAL: 止损被穿越 (超过max_stop_loss_pct)"

        print(f"{trade.symbol} | {actual_loss_pct:.2%} | {category}")
        print(f"  configured_stop={configured_stop:.4f}")
        print(f"  max_dyn_stop={max_dyn_stop:.4f}")
        print(f"  exit_price={exit_price:.4f}")
        print(f"  exit_reason={trade.exit_reason}")

    # 统计穿越率
    critical_count = count_where(category == "CRITICAL")
    print(f"\nCRITICAL穿越率: {critical_count}/{len(losing_trades)}")
    print("如果穿越率>0, 回测止损填充逻辑需要修复")


function check_backtest_stop_fill_method(backtest_engine_code):
    # 在 macd_strategy_v2.py 中搜索止损填充逻辑

    # 正确行为 (应该是):
    #   当 bar.low <= stop_price: fill at stop_price
    #
    # 危险行为 (常见bug):
    #   当 bar.low <= stop_price: fill at bar.close  ← 会产生超额亏损
    #   当 bar.low <= stop_price: fill at next_bar.open ← 跳空风险

    PATTERN_CORRECT  = "fill_price = stop_price"
    PATTERN_BUGGY_1  = "fill_price = bar.close"
    PATTERN_BUGGY_2  = "fill_price = next_bar.open"

    grep(backtest_engine_code, [PATTERN_BUGGY_1, PATTERN_BUGGY_2])
    # 如果找到 buggy pattern → 修改为 stop_price fill
```

### A.3 修复伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: macd_strategy_v2.py — 止损执行修复
# ════════════════════════════════════════════════════════════════

class PositionExitManager:

    # ── 当前可能存在的问题实现 ────────────────────────────────────
    def check_stop_loss_CURRENT(self, position, bar):
        """可能的当前实现 — 用 bar close 填价"""
        if bar.low <= position.stop_price:
            # BUG: 用 close 填充会造成超额亏损
            fill_price = bar.close
            return ExitSignal(reason="stop_loss_intrabar", fill_price=fill_price)
        return None

    # ── 修复后的实现 ─────────────────────────────────────────────
    def check_stop_loss_FIXED(self, position, bar):
        """
        修复: 止损以止损价填充, 而非 bar close
        同时添加硬上限: 单笔价格亏损不得超过 max_stop_loss_pct
        """
        if bar.low <= position.stop_price:
            # 以止损价填充 (更接近真实成交)
            fill_price = position.stop_price
            return ExitSignal(reason="stop_loss_intrabar", fill_price=fill_price)

        # 硬止损安全网: 防止动态止损过宽
        hard_stop = position.entry_price * (1 - HARD_MAX_LOSS_PCT)   # 建议1.5%
        if bar.low <= hard_stop:
            fill_price = hard_stop
            return ExitSignal(reason="hard_stop_loss", fill_price=fill_price)

        return None


    def compute_dynamic_stop(self, position, config):
        """
        动态止损必须被限制在配置范围内
        当前: stop_loss_pct=0.005, max_stop_loss_pct=0.025

        修复: 动态止损只能在 [stop_loss_pct, max_stop_loss_pct] 区间内收紧
              不允许向外扩展到 max_stop_loss_pct 以外
        """
        atr_based_stop = position.entry_price * config.atr_stop_multiplier * position.entry_atr

        # 下限: 不得比配置止损更紧 (防止噪音触发)
        min_stop_distance = config.stop_loss_pct        # 0.5%
        # 上限: 不得比最大止损更宽 (控制亏损上限)
        max_stop_distance = config.max_stop_loss_pct    # 2.5%

        actual_stop_distance = clip(atr_based_stop_distance,
                                    min_val=min_stop_distance,
                                    max_val=max_stop_distance)

        return position.entry_price * (1 - actual_stop_distance)


# 新增: HARD_MAX_LOSS_PCT 配置项
HARD_MAX_LOSS_PCT = 0.015   # 1.5% 硬止损上限 (介于0.5%和2.5%之间)
                             # 这会修复 -3.81% 的异常亏损
```

---

## Fix B — sim_light_take_profit 降权

### B.1 问题分析

```text
当前:
  sim_light_take_profit: 67笔交易, 67胜, PnL=+1924, 平均+28.72/笔
  take_profit_intrabar:  24笔交易, 24胜, PnL=+1900, 平均+79.19/笔

结论:
  intrabar TP 平均收益是 light TP 的 2.76x
  light TP 吃掉了本可以更大的胜利

  如果 67笔 light TP 改为 intrabar TP, 保守估算每笔多+50:
  潜在增量收益 ≈ 67 × 50 = +3350 → 回报从+26% → ~+59%
```

### B.2 sim_light_take_profit 触发条件分析伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: 分析 light_tp 触发场景
# ════════════════════════════════════════════════════════════════

function analyze_light_tp_triggers(trades_csv, ohlcv_data):
    light_tp_trades = load_trades(trades_csv).filter(exit_reason == "sim_light_take_profit")

    results = []
    for trade in light_tp_trades:
        exit_bar    = get_bar(ohlcv_data, trade.symbol, trade.exit_time)
        bars_after  = get_bars_after(ohlcv_data, trade.symbol, trade.exit_time, n=8)

        # 如果持仓继续持有, 4小时后收益是多少?
        hypothetical_4h_return = (bars_after[8].close - trade.exit_price) / trade.exit_price

        results.append({
            "symbol":              trade.symbol,
            "actual_pnl_pct":      trade.price_pnl_pct,
            "hypothetical_4h_pct": hypothetical_4h_return,
            "gave_up":             hypothetical_4h_return - trade.price_pnl_pct,
            "score":               trade.signal_score,
            "adx":                 trade.adx_at_entry
        })

    # 关键洞察: 高ADX交易中 light_tp 放弃了多少潜在收益?
    high_adx = [r for r in results if r.adx > 25]
    avg_gave_up_high_adx = mean([r.gave_up for r in high_adx])

    print(f"高ADX(>25)交易中 light_tp 平均放弃收益: {avg_gave_up_high_adx:.2%}")
    # 如果这个数 > 0.5%, 高ADX交易不应该用 light_tp


function should_use_light_tp(signal) -> bool:
    """
    修复后的 light_tp 触发条件 — 更保守的使用
    只在低质量、短暂信号中使用 light_tp
    高质量趋势信号应该让仓位跑更远
    """
    # 条件1: 低ADX (弱趋势) — light_tp 可以接受
    if signal.adx < 20:
        return True

    # 条件2: 低信号分数 — light_tp 可以接受
    if signal.signal_score < 0.70:
        return True

    # 条件3: 接近阻力位 (VWAP偏离过大) — light_tp 可以接受
    if signal.vwap_deviation > 0.015:
        return True

    # 高质量趋势信号: 不用 light_tp, 让 intrabar TP 处理
    return False
```

---

## Fix C — 分层止盈 (Tiered TP)

### C.1 设计目标

```text
当前结构 (单一出口):
  全仓 → 触发TP → 全仓平掉

改进结构 (分层出口):
  Layer 1: 50% 仓位 @ +0.6%    (保住利润, 维持胜率)
  Layer 2: 30% 仓位 @ +1.5%    (中等趋势捕获)
  Layer 3: 20% 仓位 @ +2.5%    (强趋势最大化)

理论影响 (保守估算, 基于当前交易分布):
  当前平均盈利: +27.42
  分层TP预期:  +0.006×0.5 + 0.015×0.3 + 0.025×0.2 = +0.013 (价格%)
  vs 当前 +0.25% 中位 → 约5x右尾扩展
```

### C.2 分层止盈实现伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: tiered_take_profit.py
# ════════════════════════════════════════════════════════════════

@dataclass
class TieredTPConfig:
    # 各层价格目标 (相对入场价格)
    layer1_pct:    float = 0.006    # +0.6%  → 50% 仓位出场
    layer2_pct:    float = 0.015    # +1.5%  → 30% 仓位出场
    layer3_pct:    float = 0.025    # +2.5%  → 20% 仓位出场

    # 各层出场比例
    layer1_ratio:  float = 0.50
    layer2_ratio:  float = 0.30
    layer3_ratio:  float = 0.20

    # 高置信度信号 (ADX>30 且 score>0.72) 使用激进配置
    aggressive_layer1_pct:  float = 0.008   # +0.8%
    aggressive_layer2_pct:  float = 0.020   # +2.0%
    aggressive_layer3_pct:  float = 0.035   # +3.5%


class TieredTakeProfitManager:

    def __init__(self, config: TieredTPConfig):
        self.config = config

    def setup_exit_layers(self, position, signal) -> List[ExitLayer]:
        """
        根据信号质量选择止盈配置
        """
        is_high_confidence = (signal.adx > 30 and signal.score > 0.72)

        if is_high_confidence:
            tp1 = self.config.aggressive_layer1_pct
            tp2 = self.config.aggressive_layer2_pct
            tp3 = self.config.aggressive_layer3_pct
        else:
            tp1 = self.config.layer1_pct
            tp2 = self.config.layer2_pct
            tp3 = self.config.layer3_pct

        entry = position.entry_price

        return [
            ExitLayer(price=entry * (1 + tp1),
                      qty_ratio=self.config.layer1_ratio,
                      layer_id=1,
                      reason="tiered_tp_layer1"),
            ExitLayer(price=entry * (1 + tp2),
                      qty_ratio=self.config.layer2_ratio,
                      layer_id=2,
                      reason="tiered_tp_layer2"),
            ExitLayer(price=entry * (1 + tp3),
                      qty_ratio=self.config.layer3_ratio,
                      layer_id=3,
                      reason="tiered_tp_layer3"),
        ]

    def check_exits(self, position, bar) -> List[PartialExitSignal]:
        """
        每根K线检查各层止盈是否触发
        返回本根K线内需要执行的部分平仓列表
        """
        exits = []
        remaining_layers = [l for l in position.exit_layers if not l.triggered]

        for layer in remaining_layers:
            if bar.high >= layer.price:
                # 触发: 以止盈价填充 (不是bar.close)
                fill_price = layer.price
                exits.append(PartialExitSignal(
                    layer_id   = layer.layer_id,
                    fill_price = fill_price,
                    qty_ratio  = layer.qty_ratio,
                    reason     = layer.reason,
                ))
                layer.triggered = True

        return exits

    def get_remaining_position_ratio(self, position) -> float:
        """计算当前剩余仓位比例"""
        triggered_ratio = sum(l.qty_ratio for l in position.exit_layers if l.triggered)
        return 1.0 - triggered_ratio

    def should_trail_stop_after_layer1(self, position) -> bool:
        """
        Layer 1 触发后, 将止损移至入场价 (保本止损)
        这样 Layer2/3 是"免费"的期权
        """
        layer1 = next(l for l in position.exit_layers if l.layer_id == 1)
        return layer1.triggered


# ── 集成到主循环 ──────────────────────────────────────────────────

function process_bar_with_tiered_tp(position, bar, tiered_tp_manager):

    # 1. 检查各层止盈
    partial_exits = tiered_tp_manager.check_exits(position, bar)
    for exit in partial_exits:
        execute_partial_close(position, exit)

        # Layer 1 触发后移动止损至保本位
        if exit.layer_id == 1:
            if tiered_tp_manager.should_trail_stop_after_layer1(position):
                position.stop_price = position.entry_price * 1.0005  # +0.05% 保本缓冲
                log(f"[TRAIL_STOP] Layer1 hit → stop moved to breakeven: {position.stop_price}")

    # 2. 如果全仓已平
    if tiered_tp_manager.get_remaining_position_ratio(position) <= 0:
        position.status = "closed"
        return

    # 3. 检查止损 (对剩余仓位)
    stop_exit = check_stop_loss(position, bar)
    if stop_exit:
        close_remaining_position(position, stop_exit)
```

---

## Fix D — max_active_symbols 容量释放

### D.1 问题量化

```text
当前配置: max_active_symbols = 3
中位持仓时间: 0.5小时
P75 持仓时间: 1.75小时

如果平均持仓0.5h, 理论上一天可以有 48 个仓位周转机会/槽位
但每个槽位一天内只用了约 162/3/30 ≈ 1.8次

capacity_full_precheck_candidates = 55  (被容量拦截)
capacity_competition_dropped = 38       (竞争被丢弃)

→ 共 93 笔潜在交易因为容量被阻止
→ 如果这些有 85% 胜率和平均+25收益:
   93 × 0.85 × 25 = +1976 增量收益 (约+20% 在$10000账户上)
```

### D.2 容量扩展伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: capacity_manager.py — 容量释放
# ════════════════════════════════════════════════════════════════

class CapacityManager:

    def compute_safe_max_symbols(self, account_equity, config) -> int:
        """
        动态计算安全的最大持仓数量
        基于账户规模和单笔风险
        """
        per_position_margin  = account_equity * config.margin_per_position_pct  # 约25%
        max_concurrent_risk  = account_equity * config.max_portfolio_risk_pct   # 约15% MDD预算

        # 每个仓位的最大亏损 (以 hard_stop 1.5% 计)
        risk_per_position = per_position_margin * config.leverage * HARD_MAX_LOSS_PCT

        # 安全并发数 = 总风险预算 / 单仓风险
        safe_count = floor(max_concurrent_risk / risk_per_position)

        # 不超过硬上限
        return min(safe_count, config.absolute_max_symbols)   # 建议硬上限=6


    def should_accept_new_position(self, candidate, current_positions, config) -> bool:
        """
        改进的容量检查: 基于风险而非简单计数
        """
        # 旧逻辑: if len(current_positions) >= max_active_symbols: reject
        # 新逻辑: 基于总风险敞口

        total_margin_in_use = sum(p.margin for p in current_positions)
        candidate_margin    = candidate.estimated_margin

        # 总使用保证金不超过账户 80%
        if (total_margin_in_use + candidate_margin) > account_equity * 0.80:
            return False, "margin_limit"

        # 同一符号不重复开仓
        symbols_in_use = {p.symbol for p in current_positions}
        if candidate.symbol in symbols_in_use:
            return False, "duplicate_symbol"

        # 当前持仓已满但有高分候选: 考虑替换最低分现有仓位
        if len(current_positions) >= config.max_active_symbols:
            lowest_score_position = min(current_positions, key=lambda p: p.entry_score)
            if candidate.score > lowest_score_position.entry_score * 1.15:
                # 候选分数比最低现有仓位高15%以上 → 替换
                return True, "score_displacement"
            return False, "capacity_full"

        return True, "accepted"


# ── 建议配置变更 ──────────────────────────────────────────────

# 消融测试顺序:
#   Step 1: max_active_symbols = 3 (baseline)
#   Step 2: max_active_symbols = 4
#   Step 3: max_active_symbols = 5
#   Step 4: max_active_symbols = 5 + score_displacement 逻辑

# 每步检查: win_rate 是否下降超过 2%, MDD 是否超过 8%
```

---

## Fix E — IOC 填充策略改善

### E.1 IOC 问题分析

```text
当前: 纯IOC → 137笔取消 (全部 ioc_no_fill)

IOC 被取消的可能场景:
  [E1] 入场价太紧 (限价单高于市价太多, 立刻取消)
  [E2] 流动性不足 (小币种滑点大)
  [E3] 网络延迟 (订单到达时价格已移动)

改进方案: IOC → 限时GTC (Time-limited GTC)
  等待3根K线 (约15分钟) 再取消
  但如果信号分数下降则提前取消

预期效果: 137笔中回收50~70笔 → 潜在+30%总收益
风险: 等待期间信号可能变坏 → 需要信号衰减检查
```

### E.2 限时 GTC 伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: order_execution.py — 限时GTC实现
# ════════════════════════════════════════════════════════════════

@dataclass
class PendingOrder:
    symbol:          str
    side:            str
    entry_price:     float
    qty:             float
    signal:          SignalSnapshot
    created_at:      datetime
    max_wait_bars:   int = 3       # 最多等待3根K线
    bars_waited:     int = 0
    status:          str = "pending"  # pending / filled / cancelled


class TimedGTCExecutor:

    def __init__(self, config):
        self.config        = config
        self.pending_queue = []   # 挂起订单队列

    def submit_order(self, signal, entry_price, qty):
        """
        替代纯IOC: 创建限时挂单
        """
        order = PendingOrder(
            symbol      = signal.symbol,
            side        = signal.side,
            entry_price = entry_price,
            qty         = qty,
            signal      = signal.snapshot(),
            created_at  = now(),
            # 高分信号等待更长, 低分信号快速取消
            max_wait_bars = 5 if signal.score > 0.72 else 2,
        )
        self.pending_queue.append(order)
        log(f"[GTC] Order queued: {order.symbol} @ {entry_price:.4f}, "
            f"max_wait={order.max_wait_bars} bars")

    def process_pending_orders(self, current_bar_data):
        """
        每根新K线开始时处理挂单队列
        """
        filled_orders    = []
        cancelled_orders = []

        for order in self.pending_queue:
            current_price = current_bar_data[order.symbol].open
            current_signal = recompute_signal(order.symbol, current_bar_data)

            # ── 取消条件 1: 等待超时 ──────────────────────────────
            if order.bars_waited >= order.max_wait_bars:
                order.status = "cancelled"
                cancelled_orders.append(order)
                log(f"[GTC_TIMEOUT] {order.symbol}: waited {order.bars_waited} bars, cancel")
                continue

            # ── 取消条件 2: 信号衰减 ──────────────────────────────
            signal_decay = order.signal.score - current_signal.score
            if signal_decay > 0.05:   # 信号分数下降超过0.05
                order.status = "cancelled"
                cancelled_orders.append(order)
                log(f"[GTC_SIGNAL_DECAY] {order.symbol}: score {order.signal.score:.3f} → "
                    f"{current_signal.score:.3f}, decay={signal_decay:.3f}, cancel")
                continue

            # ── 取消条件 3: 方向反转 ──────────────────────────────
            if current_signal.direction != order.signal.direction:
                order.status = "cancelled"
                cancelled_orders.append(order)
                log(f"[GTC_DIRECTION_FLIP] {order.symbol}: direction flipped, cancel")
                continue

            # ── 填充条件: 价格到达入场价 ──────────────────────────
            if order.side == "long" and current_price <= order.entry_price:
                order.status = "filled"
                filled_orders.append(order)
                log(f"[GTC_FILLED] {order.symbol} @ {current_price:.4f} "
                    f"(queued {order.bars_waited} bars ago)")
                continue

            if order.side == "short" and current_price >= order.entry_price:
                order.status = "filled"
                filled_orders.append(order)
                continue

            # ── 继续等待 ──────────────────────────────────────────
            order.bars_waited += 1

        # 清理已处理订单
        self.pending_queue = [o for o in self.pending_queue
                              if o.status == "pending"]

        return filled_orders, cancelled_orders


    def compute_entry_price_with_slippage(self, signal, config):
        """
        改进入场价: 给予更合理的滑点容忍
        当前可能设置太紧 (导致IOC立即取消)
        """
        base_price = signal.suggested_entry_price

        # 允许滑点范围 (相对于信号价格)
        slippage_allowance = base_price * config.entry_slippage_pct   # 建议 0.1%~0.2%

        if signal.side == "long":
            # 买入: 允许比理想价高一点
            max_entry_price = base_price * (1 + config.entry_slippage_pct)
            return max_entry_price
        else:
            # 卖出: 允许比理想价低一点
            min_entry_price = base_price * (1 - config.entry_slippage_pct)
            return min_entry_price
```

---

## Fix F — 符号风险分层

### F.1 问题符号分析

```text
ADAUSDT: 7笔交易, 胜率57%, PnL=-263.95  ← 最差
FETUSDT: 8笔交易, 胜率87%, PnL=-261.29  ← 高胜率但净亏损 (一笔-406吞噬所有盈利)
XLMUSDT: 3笔交易, 胜率66%, PnL=-59.79

共同特征: 单笔大亏损主导 (非胜率问题)
根本原因: 在这些符号上, 止损被动态宽化到 -3%+ 而没有硬性上限

临时方案: 这些符号使用更紧的止损参数
永久方案: 基于历史ATR和滑点特征做符号分级
```

### F.2 符号风险分级伪代码

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: symbol_risk_tier.py
# ════════════════════════════════════════════════════════════════

@dataclass
class SymbolRiskProfile:
    symbol:              str
    tier:                int     # 1=优质, 2=标准, 3=受限, 4=黑名单
    max_loss_pct:        float   # 该符号的硬性止损上限
    position_size_ratio: float   # 相对标准仓位的大小倍数
    notes:               str


# 初始风险分级 (基于当前回测数据)
SYMBOL_RISK_TIERS = {
    # ── Tier 1: 优质符号 (满规格运行) ─────────────────────────────
    "JUPUSDT":  SymbolRiskProfile("JUPUSDT",  1, 0.020, 1.0, "最大贡献者"),
    "ZROUSDT":  SymbolRiskProfile("ZROUSDT",  1, 0.020, 1.0, "100%胜率"),
    "AVAXUSDT": SymbolRiskProfile("AVAXUSDT", 1, 0.020, 1.0, "高流动性"),
    "SUIUSDT":  SymbolRiskProfile("SUIUSDT",  1, 0.020, 1.0, "100%胜率"),
    "WLDUSDT":  SymbolRiskProfile("WLDUSDT",  1, 0.020, 1.0, "100%胜率"),
    "ICPUSDT":  SymbolRiskProfile("ICPUSDT",  1, 0.020, 1.0, "100%胜率"),

    # ── Tier 2: 标准符号 ────────────────────────────────────────
    "SOLUSDT":  SymbolRiskProfile("SOLUSDT",  2, 0.015, 0.8, "高ADX但有大亏"),

    # ── Tier 3: 受限符号 (缩仓 + 紧止损) ────────────────────────
    "FETUSDT":  SymbolRiskProfile("FETUSDT",  3, 0.012, 0.5, "单笔-406, 需要更硬止损"),
    "XLMUSDT":  SymbolRiskProfile("XLMUSDT",  3, 0.012, 0.5, "低ADX+高波动"),
    "ALGOUSDT": SymbolRiskProfile("ALGOUSDT", 3, 0.012, 0.6, "几次大亏"),

    # ── Tier 4: 黑名单测试 (从策略移除) ──────────────────────────
    "ADAUSDT":  SymbolRiskProfile("ADAUSDT",  4, 0.000, 0.0, "57%胜率+净-264, 消融测试"),
}

# 默认 (未分级符号)
DEFAULT_TIER = SymbolRiskProfile("DEFAULT", 2, 0.015, 0.8, "标准配置")


class SymbolRiskFilter:

    def get_profile(self, symbol: str) -> SymbolRiskProfile:
        return SYMBOL_RISK_TIERS.get(symbol, DEFAULT_TIER)

    def apply_symbol_risk(self, signal, position_config) -> AdjustedPositionConfig:
        profile = self.get_profile(signal.symbol)

        if profile.tier == 4:
            return None   # 黑名单: 拒绝开仓

        return AdjustedPositionConfig(
            # 仓位大小按符号风险比例缩小
            margin_ratio = position_config.margin_ratio * profile.position_size_ratio,

            # 止损以符号风险上限为准 (覆盖动态止损)
            hard_stop_pct = min(position_config.hard_stop_pct, profile.max_loss_pct),

            # 分层止盈也相应调整
            tp_layer1_pct = position_config.tp_layer1_pct,  # 不变
            tp_layer2_pct = position_config.tp_layer2_pct * profile.position_size_ratio,
        )


function run_symbol_blacklist_ablation(config, blacklist=["ADAUSDT"]):
    """
    消融测试: 移除 ADAUSDT 后回报如何变化
    预期: 移除ADAUSDT → +264 净PnL增加 → 约+2.6% 额外回报
    """
    ablation_config = config.copy()
    ablation_config.symbol_blacklist = blacklist

    result = run_backtest(ablation_config)
    print(f"移除 {blacklist} 后:")
    print(f"  回报: {result.total_return:+.2%} (基准: +26.23%)")
    print(f"  胜率: {result.win_rate:.2%}  (基准: 91.36%)")
    print(f"  交易数: {result.total_trades} (基准: 162)")
```

---

## 9. 消融实验脚本

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: run_ablation_suite.py
# 按顺序执行, 每次只改一个变量
# ════════════════════════════════════════════════════════════════

import json
from dataclasses import dataclass, asdict
from typing import List, Dict

BASE_CONFIG_PATH = "config/trading_config_fund_flow.json"
OUTPUT_LOG       = "output/ablation/ablation_results_20260503.csv"

@dataclass
class AblationResult:
    name:          str
    total_return:  float
    win_rate:      float
    profit_factor: float
    max_drawdown:  float
    total_trades:  int
    avg_win:       float
    avg_loss:      float
    notes:         str


def load_base_config() -> dict:
    with open(BASE_CONFIG_PATH) as f:
        return json.load(f)


def run_single_backtest(config: dict) -> AblationResult:
    """包装回测执行"""
    result = subprocess.run(
        ["python", "scripts/backtest_macd_v2.py",
         "--config-inline", json.dumps(config),
         "--strict-live-mode",
         "--initial-capital", "10000"],
        capture_output=True, text=True
    )
    return parse_backtest_output(result.stdout)


# ── 消融配置列表 (按优先级排序) ──────────────────────────────────

def build_ablation_suite() -> List[Dict]:
    base = load_base_config()

    return [
        # ── 基准 (不改变任何参数) ─────────────────────────────────
        {
            "name":   "00_baseline",
            "config": base.copy(),
            "notes":  "当前生产配置, 基准线"
        },

        # ── A组: 止损修复 ─────────────────────────────────────────
        {
            "name":   "A1_hard_stop_1pct",
            "config": {**base, "hard_max_loss_pct": 0.010},
            "notes":  "硬止损1%上限 (当前无硬上限)"
        },
        {
            "name":   "A2_hard_stop_1.5pct",
            "config": {**base, "hard_max_loss_pct": 0.015},
            "notes":  "硬止损1.5%上限 (建议值)"
        },
        {
            "name":   "A3_stop_fill_at_stop_price",
            "config": {**base, "stop_fill_mode": "stop_price"},  # 非bar_close
            "notes":  "止损以止损价填充而非bar收盘价"
        },

        # ── B组: sim_light_tp 降权 ────────────────────────────────
        {
            "name":   "B1_disable_light_tp",
            "config": {**base, "sim_light_take_profit_enabled": False},
            "notes":  "完全禁用 light_tp, 预期: 胜率略降, 平均盈利大幅增加"
        },
        {
            "name":   "B2_light_tp_only_low_adx",
            "config": {**base, "sim_light_tp_max_adx": 20},
            "notes":  "light_tp 仅在ADX<20时生效"
        },
        {
            "name":   "B3_light_tp_only_low_score",
            "config": {**base, "sim_light_tp_max_score": 0.70},
            "notes":  "light_tp 仅在score<0.70时生效"
        },

        # ── C组: 分层止盈 ────────────────────────────────────────
        {
            "name":   "C1_tiered_tp_conservative",
            "config": {**base,
                       "tiered_tp_enabled": True,
                       "tiered_tp_layer1": 0.006,
                       "tiered_tp_layer2": 0.015,
                       "tiered_tp_layer3": 0.025,
                       "tiered_tp_ratios": [0.5, 0.3, 0.2]},
            "notes":  "分层止盈: 50%@0.6%, 30%@1.5%, 20%@2.5%"
        },
        {
            "name":   "C2_tiered_tp_aggressive",
            "config": {**base,
                       "tiered_tp_enabled": True,
                       "tiered_tp_layer1": 0.008,
                       "tiered_tp_layer2": 0.020,
                       "tiered_tp_layer3": 0.035,
                       "tiered_tp_ratios": [0.4, 0.35, 0.25]},
            "notes":  "分层止盈激进版: 40%@0.8%, 35%@2.0%, 25%@3.5%"
        },

        # ── D组: 容量扩展 ─────────────────────────────────────────
        {
            "name":   "D1_max_symbols_4",
            "config": {**base, "max_active_symbols": 4},
            "notes":  "max_active_symbols 3→4"
        },
        {
            "name":   "D2_max_symbols_5",
            "config": {**base, "max_active_symbols": 5},
            "notes":  "max_active_symbols 3→5"
        },
        {
            "name":   "D3_max_symbols_6",
            "config": {**base, "max_active_symbols": 6},
            "notes":  "max_active_symbols 3→6 (压力测试)"
        },

        # ── E组: IOC替换 ─────────────────────────────────────────
        {
            "name":   "E1_gtc_wait_2bars",
            "config": {**base, "order_type": "timed_gtc", "gtc_max_wait_bars": 2},
            "notes":  "IOC → 限时GTC 2根K线等待"
        },
        {
            "name":   "E2_gtc_wait_3bars",
            "config": {**base, "order_type": "timed_gtc", "gtc_max_wait_bars": 3},
            "notes":  "IOC → 限时GTC 3根K线等待"
        },

        # ── F组: 符号黑名单 ───────────────────────────────────────
        {
            "name":   "F1_blacklist_adausdt",
            "config": {**base, "symbol_blacklist": ["ADAUSDT"]},
            "notes":  "移除ADAUSDT (57%胜率+净-264)"
        },
        {
            "name":   "F2_blacklist_adas_fet",
            "config": {**base, "symbol_blacklist": ["ADAUSDT", "FETUSDT"]},
            "notes":  "移除两个净亏损符号"
        },
        {
            "name":   "F3_tier3_tight_stop",
            "config": {**base,
                       "symbol_risk_tiers": {
                           "ADAUSDT": {"tier": 3, "max_loss_pct": 0.010, "size_ratio": 0.5},
                           "FETUSDT": {"tier": 3, "max_loss_pct": 0.010, "size_ratio": 0.5},
                           "XLMUSDT": {"tier": 3, "max_loss_pct": 0.010, "size_ratio": 0.5},
                       }},
            "notes":  "问题符号缩仓+紧止损 (不黑名单)"
        },

        # ── G组: 最佳组合 (最后运行) ─────────────────────────────
        {
            "name":   "G1_best_combination",
            "config": {**base,
                       "hard_max_loss_pct":             0.015,      # Fix A
                       "stop_fill_mode":                "stop_price",
                       "sim_light_tp_max_adx":          20,         # Fix B
                       "tiered_tp_enabled":             True,       # Fix C
                       "tiered_tp_layer1":              0.006,
                       "tiered_tp_layer2":              0.015,
                       "tiered_tp_layer3":              0.025,
                       "tiered_tp_ratios":              [0.5, 0.3, 0.2],
                       "max_active_symbols":            5,          # Fix D
                       "symbol_blacklist":              ["ADAUSDT"], # Fix F
                       },
            "notes":  "所有最优修复组合 (基于单独消融结果选出)"
        },
    ]


def run_ablation_suite():
    suite   = build_ablation_suite()
    results = []

    print(f"{'名称':<35} {'回报':>8} {'胜率':>7} {'PF':>6} {'MDD':>7} {'交易数':>6} {'avg_W':>7} {'avg_L':>8}")
    print("-" * 95)

    for ablation in suite:
        result = run_single_backtest(ablation["config"])
        result.name  = ablation["name"]
        result.notes = ablation["notes"]
        results.append(result)

        flag = ""
        if result.win_rate < 0.88:      flag += " ⚠WIN_RATE"
        if result.max_drawdown > 0.08:  flag += " ⚠MDD"
        if result.profit_factor < 1.5:  flag += " ⚠PF"

        print(f"{result.name:<35} "
              f"{result.total_return:>+7.1%} "
              f"{result.win_rate:>6.1%} "
              f"{result.profit_factor:>5.2f} "
              f"{result.max_drawdown:>6.1%} "
              f"{result.total_trades:>5d} "
              f"{result.avg_win:>+6.1f} "
              f"{result.avg_loss:>+7.1f}"
              f"{flag}")

    save_csv(results, OUTPUT_LOG)
    print(f"\n结果已保存: {OUTPUT_LOG}")

    # 自动识别最佳单变量修复
    baseline  = results[0]
    best_single = max(results[1:-1],
                      key=lambda r: r.total_return
                      if r.win_rate >= baseline.win_rate * 0.97  # 胜率不降超过3%
                      and r.max_drawdown <= 0.08
                      else -999)
    print(f"\n建议首先实施: {best_single.name}")
    print(f"  回报提升: {baseline.total_return:+.1%} → {best_single.total_return:+.1%}")
    print(f"  胜率变化: {baseline.win_rate:.1%} → {best_single.win_rate:.1%}")


if __name__ == "__main__":
    run_ablation_suite()
```

---

## 10. Config DIFF

```diff
# ════════════════════════════════════════════════════════════════
# DIFF: config/trading_config_fund_flow.json
# 修改说明: 基于消融测试结果的推荐配置变更
# 注意: 先跑消融测试验证, 再应用此DIFF
# ════════════════════════════════════════════════════════════════

--- a/config/trading_config_fund_flow.json
+++ b/config/trading_config_fund_flow.json
@@ -10,8 +10,12 @@
   "strategy": {
     "stop_loss_pct": 0.005,
-    "max_stop_loss_pct": 0.025,
+    "max_stop_loss_pct": 0.015,
+    "hard_max_loss_pct": 0.015,
+    "stop_fill_mode": "stop_price",
     "take_profit_pct": 0.020,
+    "sim_light_take_profit_enabled": true,
+    "sim_light_tp_max_adx": 20,
+    "sim_light_tp_max_score": 0.70,
     "default_leverage": 4,
     "max_leverage": 5

@@ -22,7 +26,7 @@
   "execution": {
-    "max_active_symbols": 3,
+    "max_active_symbols": 5,
     "order_type": "ioc",
+    "order_type": "timed_gtc",
+    "gtc_max_wait_bars": 3,
+    "gtc_signal_decay_threshold": 0.05,
     "entry_slippage_pct": 0.001

@@ -35,5 +43,25 @@
   "risk": {
     "equity_usage_block": 0.85,
     "dd_exit_threshold": 0.10,
-    "symbol_blacklist": []
+    "symbol_blacklist": ["ADAUSDT"],
+    "symbol_risk_tiers": {
+      "FETUSDT": {
+        "tier": 3,
+        "max_loss_pct": 0.012,
+        "position_size_ratio": 0.50,
+        "note": "大亏损符号, 87.5%胜率但净亏-261"
+      },
+      "XLMUSDT": {
+        "tier": 3,
+        "max_loss_pct": 0.012,
+        "position_size_ratio": 0.50,
+        "note": "66.7%胜率, 低ADX高波动"
+      },
+      "ALGOUSDT": {
+        "tier": 3,
+        "max_loss_pct": 0.012,
+        "position_size_ratio": 0.60,
+        "note": "83.3%胜率, 偶发大亏"
+      }
+    }
   }
```

```diff
# ════════════════════════════════════════════════════════════════
# DIFF: src/fund_flow/macd_strategy_v2.py
# 关键止损和止盈逻辑修改
# ════════════════════════════════════════════════════════════════

--- a/src/fund_flow/macd_strategy_v2.py
+++ b/src/fund_flow/macd_strategy_v2.py
@@ -[STOP_LOSS_CHECK] @@
-    def _check_stop_loss(self, position, bar):
-        if bar.low <= position.stop_price:
-            fill_price = bar.close          # BUG: 应为 stop_price
-            return ExitSignal("stop_loss_intrabar", fill_price)
-        return None

+    def _check_stop_loss(self, position, bar):
+        # 硬性安全网: 防止动态止损被宽化超出配置上限
+        hard_stop = position.entry_price * (1 - self.config.hard_max_loss_pct)
+
+        # 常规止损检查
+        if bar.low <= position.stop_price:
+            fill_price = max(position.stop_price, bar.low)  # 以止损价填充
+            return ExitSignal("stop_loss_intrabar", fill_price)
+
+        # 硬止损安全网触发
+        if bar.low <= hard_stop:
+            fill_price = hard_stop
+            logger.warning(f"[HARD_STOP] {position.symbol}: "
+                           f"dynamic stop {position.stop_price:.4f} "
+                           f"exceeded hard limit {hard_stop:.4f}, "
+                           f"forced exit at {fill_price:.4f}")
+            return ExitSignal("hard_stop_loss", fill_price)
+
+        return None

@@ -[LIGHT_TP_CHECK] @@
-    def _check_sim_light_take_profit(self, position, bar, signal):
-        """Always check light TP"""
-        if bar.high >= position.light_tp_price:
-            return ExitSignal("sim_light_take_profit", position.light_tp_price)
-        return None

+    def _check_sim_light_take_profit(self, position, bar, signal):
+        """
+        Light TP 仅在弱趋势/低质量信号中启用
+        强趋势 (ADX>20) 且高分 (score>0.70) 信号应让仓位跑更远
+        """
+        max_adx   = self.config.get("sim_light_tp_max_adx",   20)
+        max_score = self.config.get("sim_light_tp_max_score", 0.70)
+
+        # 强趋势高分信号: 跳过 light_tp, 使用正常 intrabar_tp 或 tiered_tp
+        if signal.adx > max_adx and signal.score > max_score:
+            return None
+
+        if bar.high >= position.light_tp_price:
+            return ExitSignal("sim_light_take_profit", position.light_tp_price)
+        return None

@@ -[TAKE_PROFIT_CHECK] @@
+    def _check_tiered_take_profit(self, position, bar):
+        """
+        新增: 分层止盈检查
+        只有在 tiered_tp_enabled=True 时调用
+        """
+        if not self.config.get("tiered_tp_enabled", False):
+            return None, []
+
+        partial_exits = []
+        for layer in position.exit_layers:
+            if not layer.triggered and bar.high >= layer.price:
+                layer.triggered = True
+                partial_exits.append(PartialExit(
+                    price     = layer.price,
+                    qty_ratio = layer.qty_ratio,
+                    reason    = f"tiered_tp_layer{layer.layer_id}",
+                ))
+
+                # Layer 1 触发后移止损至保本位
+                if layer.layer_id == 1:
+                    position.stop_price = position.entry_price * 1.0003
+                    logger.info(f"[BREAKEVEN_STOP] {position.symbol}: "
+                                f"Layer1 hit, stop → {position.stop_price:.4f}")
+
+        return partial_exits
```

```diff
# ════════════════════════════════════════════════════════════════
# DIFF: src/fund_flow/decision_engine.py
# 容量管理和执行逻辑修改
# ════════════════════════════════════════════════════════════════

--- a/src/fund_flow/decision_engine.py
+++ b/src/fund_flow/decision_engine.py

@@ -[CAPACITY_CHECK] @@
-    def _check_capacity(self, symbol, current_positions):
-        if len(current_positions) >= self.config.max_active_symbols:
-            self.metrics.capacity_full_precheck_candidates += 1
-            return False, "capacity_full"
-        return True, "ok"

+    def _check_capacity(self, candidate, current_positions):
+        max_symbols = self.config.max_active_symbols  # 建议: 3→5
+
+        # 同符号不重复
+        if candidate.symbol in {p.symbol for p in current_positions}:
+            return False, "duplicate_symbol"
+
+        if len(current_positions) < max_symbols:
+            return True, "accepted"
+
+        # 容量已满: 检查是否可以置换低分仓位
+        lowest = min(current_positions, key=lambda p: p.entry_score)
+        if candidate.score > lowest.entry_score * 1.15:
+            logger.info(f"[SCORE_DISPLACEMENT] Replacing {lowest.symbol} "
+                        f"(score={lowest.entry_score:.3f}) with {candidate.symbol} "
+                        f"(score={candidate.score:.3f})")
+            return True, "score_displacement", lowest   # 返回需要替换的仓位
+
+        self.metrics.capacity_full_precheck_candidates += 1
+        return False, "capacity_full"

@@ -[ORDER_EXECUTION] @@
-    def _submit_entry_order(self, signal, entry_price, qty):
-        """Pure IOC: if not filled immediately, cancel"""
-        result = self.exchange.submit_ioc_order(signal.symbol, signal.side,
-                                                qty, entry_price)
-        if not result.filled:
-            self.metrics.ioc_no_fill += 1
-            return None
-        return result

+    def _submit_entry_order(self, signal, entry_price, qty):
+        """
+        限时GTC: 等待最多 gtc_max_wait_bars 根K线
+        如果信号衰减则提前取消
+        """
+        order_type = self.config.get("order_type", "ioc")
+
+        if order_type == "ioc":
+            # 旧行为保留
+            result = self.exchange.submit_ioc_order(signal.symbol, signal.side,
+                                                    qty, entry_price)
+            if not result.filled:
+                self.metrics.ioc_no_fill += 1
+                return None
+            return result
+
+        elif order_type == "timed_gtc":
+            max_wait = self.config.get("gtc_max_wait_bars", 3)
+            order    = PendingGTCOrder(signal, entry_price, qty, max_wait)
+            self.pending_gtc_queue.append(order)
+            logger.debug(f"[GTC_QUEUED] {signal.symbol} @ {entry_price:.4f}, "
+                         f"max_wait={max_wait} bars")
+            return None   # 将在下一轮 process_pending_orders 中处理
```

---

## 11. 执行顺序总结

```text
════════════════════════════════════════════════════════════════
 MACD V2 修复执行路线图
════════════════════════════════════════════════════════════════

 Week 1 (本周)
 ─────────────────────────────────────────────────────────────
 Day 1-2: 诊断止损机制
   ├── 运行 audit_stop_loss_behavior()
   ├── 确认是否是 bar.close 填充问题 (Fix A3)
   └── 运行消融 A1, A2, A3 → 选出最佳止损配置

 Day 3-4: 止盈结构改革
   ├── 运行消融 B1, B2, B3 (light_tp 降权)
   ├── 运行消融 C1, C2 (分层止盈)
   └── 选出最佳止盈配置 (预期: B2+C1 组合)

 Day 5: 容量释放
   ├── 运行消融 D1, D2, D3
   └── 选出 max_active_symbols (预期: 5)

 Week 2 (下周)
 ─────────────────────────────────────────────────────────────
 Day 1-2: 执行改善
   ├── 运行消融 E1, E2 (限时GTC)
   └── 评估成交率提升 vs 信号衰减风险

 Day 3: 符号风险分层
   ├── 运行消融 F1, F2, F3
   └── 决定是黑名单还是分层控制

 Day 4-5: 最佳组合
   ├── 运行 G1_best_combination
   ├── 验证目标: ≥88%胜率 + ≥+50%回报 + MDD≤8%
   └── 如果通过 → 部署到 staging 环境

════════════════════════════════════════════════════════════════
 预期最终结果 (基于理论分析)
════════════════════════════════════════════════════════════════
 当前: 胜率=91.36%, 回报=+26.23%, MDD=5.01%, PF=3.55
 目标: 胜率≥88.0%, 回报=+55~70%, MDD≤8.0%, PF≥4.0

 最大风险点: 分层止盈 + 更大容量 → MDD可能上升
 监控重点: 如果 G1 的 MDD > 8%, 回退 max_active_symbols=4
════════════════════════════════════════════════════════════════
```
