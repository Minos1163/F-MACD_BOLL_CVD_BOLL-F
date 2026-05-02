# MACD V2 复盘建议 — 2026-05-01

> **文档性质**：基于本轮四次回测产物（旧基线 / P0-P4 全集成 / 外科修正 / 归核化）的
> 结构性分析与下一轮迭代路线图。包含根因定位、伪代码修正、DIFF 示例、消融计划。

---

## 0. 快速结论（TL;DR）

| 问题 | 根因 | 优先级 |
|---|---|---|
| MDD 8.23% 未回到 6.12% | 持仓重叠时间窗扩大 + 退出路径滞后 | P0 |
| PF 6.15 未回到 7.20 | 取消单质量与成交单同分（0.6649 vs 0.6651）说明阈值未分层 | P0 |
| Return 41.58% 未达 45% | 成交数收缩（94→90）抵消了信号质量改善 | P1 |
| IOC cancel rate 58.5% 不降 | `market_fallback_attempted=0`：fallback 路径未被 metadata 路由触达 | P1 |
| capacity=4 → MDD 10.37% | competition_ranking 新增低质量竞争入场，不是 capacity 本身的问题 | P2 |

**本轮不建议上线任何新功能。下一轮目标是单点消融，优先修复退出延迟和 IOC metadata 路由。**

---

## 1. 数据基准对比

```
版本                        Return    WR       Trades  PF      MDD      Cancel/Submit
────────────────────────────────────────────────────────────────────────────────────
旧基线 20260430            +44.37%  87.23%    94     7.20    6.12%    130/224=58.04%
P0-P4 全集成               +40.93%  86.67%   105     5.48   10.37%    146/251=58.17%
外科修正+强制fallback       +27.13%  74.77%   111     2.54    9.10%     67/178=37.64%
归核化（当前基线）          +41.58%  87.78%    90     6.15    8.23%    127/217=58.53%
────────────────────────────────────────────────────────────────────────────────────
目标线                      ≥45.00%  ≥85.00%  80-100  ≥9.00   ≤6.00%   < 50%
```

**归核化已是当前最佳可用基线，但三项核心指标仍未达标。**

---

## 2. 根因分析

### 2.1 MDD 8.23% 的来源

归核化回撤区间与 P0-P4 全集成相同：`2026-02-28 10:00 → 2026-03-04 00:30`，恢复点 `2026-03-15`。
说明 MDD 不是 capacity 引入的新问题，而是该窗口内**退出滞后**导致浮亏累积。

```
诊断路径：
  旧基线 flip_bullish=4笔 / PnL=-79.02   →  P0 清零后没有退出延迟改善
  旧基线 MDD 6.12%   →  本轮 8.23%  delta = +2.11%

假设：
  flip_bullish 清零节省了 4 笔入场，但同期 red_bar_growing 路径
  多开了 trades（73 vs 旧基线近似），且 macd_1h_flip_exit 触发节点
  比旧系统晚 1-2 根 K 线。

验证方法（伪代码）：
  baseline_exits = load_exit_log("v2_live_equiv_20260430_trades.csv")
  core_exits     = load_exit_log("v2_core_reset_20260501_trades.csv")
  
  for trade in core_exits:
      ref = find_matching_symbol_entry(baseline_exits, trade.symbol, trade.entry_time)
      if ref:
          delay = trade.exit_bar_index - ref.exit_bar_index
          delay_log.append(delay)
  
  avg_delay = mean(delay_log)
  # 如果 avg_delay > 0，说明退出系统性偏晚
  # 如果 avg_delay > 1.5 bars，可以量化为 MDD 贡献
```

### 2.2 PF 从 7.20 降到 6.15

PF = 总盈利 / 总亏损。降低路径有两条：盈利单收益率下降，或亏损单亏损率上升。

```
归因拆解（伪代码）：

baseline_trades = load("v2_live_equiv_20260430_trades.csv")
core_trades     = load("v2_core_reset_20260501_trades.csv")

for dataset, label in [(baseline_trades, "baseline"), (core_trades, "core")]:
    wins   = [t for t in dataset if t.pnl > 0]
    losses = [t for t in dataset if t.pnl <= 0]
    
    print(f"{label}:")
    print(f"  avg_win    = {mean(t.pnl for t in wins):.2f}")
    print(f"  avg_loss   = {mean(t.pnl for t in losses):.2f}")
    print(f"  max_loss   = {min(t.pnl for t in losses):.2f}")
    print(f"  win_count  = {len(wins)}")
    print(f"  loss_count = {len(losses)}")

# 预期结论：avg_loss 绝对值增大，因为 holding_time_exit 没有在峰值附近触发
```

**核心假设：`holding_time_exit` 当前阈值过宽，导致亏损单持有时间过长，拉低 PF。**

### 2.3 IOC cancel rate 58.5% — `market_fallback_attempted=0`

这是本轮技术债务最明确的一条。`attempted=0` 不是策略问题，是路由 metadata 传播缺陷。

```
归核化配置下执行链路（已知）：
  FundFlowExecutionRouter.execute_decision()
    → place_ioc_order()
    → on_ioc_cancel:
        check entry_execution_policy   ← 需要 metadata 携带
        check entry_market_fallback_enabled  ← 需要 metadata 携带
        → if both True: attempt_market_fallback()
        → else: cancel (fallback_not_reached=127)
  
问题定位：
  取消诊断 pending_cancel_reasons = {"ioc_no_fill": 127}
  全部 127 笔都是 fallback_not_reached，不是 slippage_blocked
  
  说明 metadata 在 backtest 路径下没有正确传播，
  导致所有 IOC 取消单都走进了"无 metadata → 跳过 fallback"分支
```

---

## 3. 建议修正（DIFF 格式）

### 3.1 P0：修复退出延迟 — `macd_1h_flip_exit` 提前触发

**当前逻辑（伪代码还原）：**

```python
# macd_strategy_v2.py  — 当前退出判断（简化）
def check_exit_signals(position, bar):
    # 触发条件：1H MACD 已翻转 AND 确认 bar 收盘
    if bar.macd_1h_flip and bar.is_closed:
        return ExitSignal(reason="macd_1h_flip_exit")
    return None
```

**问题：** `bar.is_closed` 等待当根 K 线收盘，最多延迟 1 根 15m bar（= 15 分钟）。
在快速回撤窗口中，1 根 bar 的延迟会显著扩大浮亏。

**建议修正：**

```diff
  # macd_strategy_v2.py
  def check_exit_signals(self, position, bar, config):
-     # 原始：等当根 K 线收盘确认
-     if bar.macd_1h_flip and bar.is_closed:
-         return ExitSignal(reason="macd_1h_flip_exit")
+     # 修正：允许在 K 线进行中触发（early_exit_on_flip_inbar=True 时）
+     flip_confirmed = bar.macd_1h_flip and bar.is_closed
+     flip_early     = (
+         config.macd_1h_flip_exit_early_enabled
+         and bar.macd_1h_flip_inbar          # 当根内已出现翻转信号
+         and bar.bar_completion_pct >= 0.75  # K 线完成度 >= 75%
+         and position.unrealized_pnl < -config.early_exit_pnl_threshold
+     )
+     if flip_confirmed or flip_early:
+         reason = "macd_1h_flip_exit_early" if flip_early else "macd_1h_flip_exit"
+         return ExitSignal(reason=reason)
      return None
```

**对应配置 DIFF：**

```diff
  # trading_config_fund_flow.json
  "exit_config": {
    "macd_1h_flip_exit_enabled": true,
+   "macd_1h_flip_exit_early_enabled": true,
+   "macd_1h_flip_exit_early_bar_completion_pct": 0.75,
+   "early_exit_pnl_threshold": -0.003,
    "rsi_overheat_exit_enabled": true,
    "holding_time_exit_enabled": true
  }
```

**预期效果：** MDD 降低 0.5-1.5%（取决于回撤窗口内触发频次），WR 可能小幅下降（±0.5%）。

---

### 3.2 P0：收紧 `holding_time_exit` — 阻止亏损单过度持有

**当前问题：** 亏损单持有时间未设硬上限，`holding_time_exit` 仅按固定 bars 数触发，
不区分当前浮亏状态。

```diff
  # decision_engine.py  — holding_time_exit 判断
  def check_holding_time_exit(self, position, current_bar_index, config):
      hold_bars = current_bar_index - position.entry_bar_index
-     # 原始：只看持有时间
-     if hold_bars >= config.holding_time_exit_bars:
-         return ExitSignal(reason="holding_time_exit")
+     # 修正 A：时间触发（不变）
+     if hold_bars >= config.holding_time_exit_bars:
+         return ExitSignal(reason="holding_time_exit_time")
+
+     # 修正 B：浮亏 + 时间双门触发（新增）
+     # 思路：亏损超过阈值后，等待时间缩短，更快止损
+     if (position.unrealized_pnl_pct < -config.holding_time_exit_loss_threshold
+             and hold_bars >= config.holding_time_exit_loss_bars):
+         return ExitSignal(reason="holding_time_exit_loss_gate")
+
      return None
```

**对应配置 DIFF：**

```diff
  # trading_config_fund_flow.json
  "exit_config": {
    "holding_time_exit_enabled": true,
    "holding_time_exit_bars": 48,
+   "holding_time_exit_loss_threshold": 0.012,
+   "holding_time_exit_loss_bars": 24
  }
```

**消融验证（伪代码）：**

```python
# 在回测中记录每笔最终亏损单的持有时间分布
loss_trades = [t for t in core_reset_trades if t.pnl < 0]
holding_bars = [t.exit_bar - t.entry_bar for t in loss_trades]
pnl_at_24bar = [t.unrealized_pnl_at_bar(t.entry_bar + 24) for t in loss_trades]

# 如果 pnl_at_24bar 中位数 < -0.012，说明 24bar 双门有效
# 如果 pnl_at_24bar 中位数 > -0.005，说明阈值过紧，需要松到 -0.018
print(f"loss trades median pnl at bar+24: {median(pnl_at_24bar):.4%}")
print(f"loss trades median hold: {median(holding_bars)} bars")
```

---

### 3.3 P1：修复 IOC fallback metadata 路由

**根因（伪代码还原）：**

```python
# execution_router.py  — 当前 IOC 取消回调（问题代码）
def on_ioc_order_canceled(self, order, cancel_reason):
    # 问题：metadata 在 backtest 路径下没有从 pending_order 正确传入
    policy  = order.metadata.get("entry_execution_policy")   # ← backtest 下为 None
    fb_flag = order.metadata.get("entry_market_fallback_enabled")  # ← backtest 下为 None
    
    if policy == "ioc_with_market_fallback" and fb_flag:
        self._attempt_market_fallback(order)
    else:
        # 所有 127 笔取消单都走到这里
        self._record_cancel(order, reason="fallback_not_reached")
```

**根本原因：** backtest 的 `pending_order` 在生成时没有把 `entry_execution_policy`
和 `entry_market_fallback_enabled` 写入 metadata，导致取消回调无法判断是否应进入 fallback。

```diff
  # backtest_macd_v2.py  — pending order 生成
  def _create_pending_order(self, signal, config):
      order = PendingOrder(
          symbol=signal.symbol,
          direction=signal.direction,
          size=signal.size,
          price=signal.limit_price,
          order_type="IOC",
      )
+     # 修正：显式把 execution policy metadata 写入 backtest pending order
+     order.metadata["entry_execution_policy"] = (
+         "ioc_with_market_fallback"
+         if config.open_market_fallback_enabled
+         else "ioc_only"
+     )
+     order.metadata["entry_market_fallback_enabled"] = config.open_market_fallback_enabled
+     order.metadata["open_market_fallback_max_slippage_bps"] = (
+         config.open_market_fallback_max_slippage_bps
+     )
      return order
```

**对应 live router DIFF（确保对称）：**

```diff
  # execution_router.py  — live 路径 order 生成
  def _build_live_order_metadata(self, signal, config):
      meta = {
          "signal_score": signal.score,
          "signal_type":  signal.signal_type,
+         # 确保 live 与 backtest metadata key 完全一致
+         "entry_execution_policy": (
+             "ioc_with_market_fallback"
+             if config.open_market_fallback_enabled
+             else "ioc_only"
+         ),
+         "entry_market_fallback_enabled": config.open_market_fallback_enabled,
+         "open_market_fallback_max_slippage_bps": config.open_market_fallback_max_slippage_bps,
      }
      return meta
```

**验证断言（单测伪代码）：**

```python
# tests/test_ioc_metadata_propagation.py
def test_backtest_pending_order_carries_fallback_metadata():
    config = make_config(open_market_fallback_enabled=True,
                         open_market_fallback_max_slippage_bps=8)
    signal = make_signal(score=0.72, signal_type="red_bar_growing")
    
    order = BacktestEngine._create_pending_order(signal, config)
    
    assert order.metadata["entry_execution_policy"] == "ioc_with_market_fallback"
    assert order.metadata["entry_market_fallback_enabled"] is True
    assert order.metadata["open_market_fallback_max_slippage_bps"] == 8

def test_backtest_ioc_cancel_triggers_fallback_when_metadata_present():
    order = make_pending_order(metadata={
        "entry_execution_policy": "ioc_with_market_fallback",
        "entry_market_fallback_enabled": True,
        "open_market_fallback_max_slippage_bps": 8,
    })
    router = FundFlowExecutionRouter(config=make_config())
    result = router.on_ioc_order_canceled(order, cancel_reason="ioc_no_fill")
    
    assert result.fallback_attempted is True
    # 注意：fallback 不一定成交（取决于滑点），但必须尝试
```

---

### 3.4 P1：IOC fallback 门槛分层（避免外科修正的 PF 崩溃）

外科修正证明：无门槛的全量 fallback 导致 PF 从 5.48 崩到 2.54。
修复 metadata 路由后，必须同时加入信号质量门槛，避免重蹈覆辙。

```diff
  # execution_router.py  — market fallback 决策
  def _attempt_market_fallback(self, order):
      config   = self.config
      metadata = order.metadata
      
+     # 门槛 1：信号分数必须足够高
+     signal_score = metadata.get("signal_score", 0.0)
+     if signal_score < config.market_fallback_min_signal_score:
+         self._record_cancel(order, reason="fallback_score_gate")
+         return
+
+     # 门槛 2：信号类型白名单（外科修正数据：flip_bearish WR=79% >> red_bar_growing WR=74%）
+     signal_type = metadata.get("signal_type", "")
+     allowed_types = config.market_fallback_allowed_signal_types
+     if allowed_types and signal_type not in allowed_types:
+         self._record_cancel(order, reason="fallback_type_gate")
+         return
+
      # 原有滑点保护（保留）
      slippage_bps = self._estimate_slippage_bps(order)
      if slippage_bps > config.open_market_fallback_max_slippage_bps:
          self._record_cancel(order, reason="market_fallback_slippage_blocked")
          return
      
      self._place_market_order(order)
```

**对应配置 DIFF：**

```diff
  # trading_config_fund_flow.json
  "execution_degradation": {
    "force_market_fallback_on_ioc_remainder": false,
    "open_market_fallback_max_slippage_bps": 8,
+   "market_fallback_min_signal_score": 0.88,
+   "market_fallback_allowed_signal_types": ["flip_bearish"],
+   "market_fallback_score_gate_enabled": true
  }
```

**预期效果：** fallback 仅对高分 `flip_bearish` 触发，外科修正中此类型 WR=79%，
预计新增成交质量显著高于全量 fallback 的 WR=74.77%。

---

### 3.5 P2：capacity=4 的正确开启条件

P0-P4 全集成的 MDD 10.37% 不是 `capacity=4` 本身的问题，
而是 `competition_ranking.enabled=true` 引入了低质量候选单。

**消融实验设计：**

```python
# scripts/run_capacity_ablation.py
ABLATION_CONFIGS = [
    # A：归核化基线（当前）
    ("core_reset_cap3_no_rank", dict(
        max_active_symbols=3,
        competition_ranking_enabled=False,
    )),
    
    # B：只加 capacity，不加 ranking（目标：MDD 是否可控？）
    ("cap4_no_rank", dict(
        max_active_symbols=4,
        competition_ranking_enabled=False,
    )),
    
    # C：capacity + ranking（全集成时的问题组合）
    ("cap4_with_rank", dict(
        max_active_symbols=4,
        competition_ranking_enabled=True,
    )),
    
    # D：ranking 但不扩容（定位 ranking 单独影响）
    ("cap3_with_rank", dict(
        max_active_symbols=3,
        competition_ranking_enabled=True,
    )),
]

results = []
for name, overrides in ABLATION_CONFIGS:
    cfg = merge(CORE_RESET_CONFIG, overrides)
    r = run_backtest(cfg, start="2026-02-23", end="2026-03-24T23:59:59")
    results.append({
        "name": name,
        "return": r.total_return,
        "wr": r.win_rate,
        "trades": r.total_trades,
        "pf": r.profit_factor,
        "mdd": r.max_drawdown,
    })

print_table(results)
# 决策规则：
#   若 B.mdd <= 7.5% → capacity=4 可作为 P2 升级
#   若 D.mdd > C.mdd - 0.5% → ranking 是 MDD 贡献主因，不是 capacity
```

---

## 4. 完整消融计划（顺序执行）

```
Round 1：退出路径修复（目标 MDD ≤ 7.0%，PF ≥ 7.0）
  变量：macd_1h_flip_exit_early + holding_time_exit_loss_gate
  基线：归核化 core_reset（return=41.58%, WR=87.78%, MDD=8.23%, PF=6.15）
  验收：
    MDD ≤ 7.5%（比旧基线 6.12% 留余量）
    WR ≥ 86%（不能因为提前退出把胜率打下去）
    PF ≥ 6.5
  
Round 2：IOC metadata 路由修复（目标 fallback_attempted > 0）
  变量：backtest pending_order metadata 传播
  前提：Round 1 已通过
  验收：
    market_fallback_attempted > 0 in 30d strict-live
    fallback 成交 WR ≥ 75%（低于总体 WR 1% 以内可接受）
    cancel_rate 从 58.5% 降至 ≤ 52%
  
Round 3：fallback 门槛分层（目标 PF 不因 fallback 下降）
  变量：market_fallback_min_signal_score + allowed_signal_types
  前提：Round 2 已通过
  验收：
    PF 不低于 Round 2 基线 -0.3
    新增 fallback 成交 WR ≥ 78%
  
Round 4：capacity 消融（目标 cap=4 可控开启）
  变量：max_active_symbols=4，competition_ranking=False
  前提：Round 3 已通过，MDD 已稳定在 ≤ 7%
  验收：
    MDD ≤ 7.5%（capacity 扩张预期带来 +1% MDD）
    Return ≥ 45%
    trades 100-120
```

---

## 5. 单测补充计划

```python
# 需要新增的测试用例清单

# ── Round 1 退出路径 ──────────────────────────────────────────────

def test_macd_1h_flip_exit_early_triggers_at_75pct_bar():
    """K线完成度75%时，浮亏超阈值应触发 early exit"""
    position = make_position(unrealized_pnl=-0.004)  # -0.4%，超过 early_exit_pnl_threshold
    bar = make_bar(
        macd_1h_flip_inbar=True,
        bar_completion_pct=0.80,
        is_closed=False,
    )
    config = make_config(
        macd_1h_flip_exit_early_enabled=True,
        macd_1h_flip_exit_early_bar_completion_pct=0.75,
        early_exit_pnl_threshold=0.003,
    )
    result = strategy.check_exit_signals(position, bar, config)
    assert result is not None
    assert result.reason == "macd_1h_flip_exit_early"

def test_macd_1h_flip_exit_early_does_not_trigger_when_profitable():
    """盈利持仓不应被 early exit 打掉"""
    position = make_position(unrealized_pnl=+0.015)
    bar = make_bar(macd_1h_flip_inbar=True, bar_completion_pct=0.90, is_closed=False)
    config = make_config(macd_1h_flip_exit_early_enabled=True, early_exit_pnl_threshold=0.003)
    result = strategy.check_exit_signals(position, bar, config)
    assert result is None  # 盈利单不触发 early exit

def test_holding_time_loss_gate_triggers():
    """亏损超 1.2% 且持有超 24 bars 时应触发"""
    position = make_position(entry_bar=0, unrealized_pnl_pct=-0.015)
    result = strategy.check_holding_time_exit(position, current_bar=25, config=make_config(
        holding_time_exit_loss_threshold=0.012,
        holding_time_exit_loss_bars=24,
    ))
    assert result is not None
    assert result.reason == "holding_time_exit_loss_gate"

def test_holding_time_loss_gate_does_not_trigger_before_bars():
    """未到 24 bars 即使亏损也不触发"""
    position = make_position(entry_bar=0, unrealized_pnl_pct=-0.020)
    result = strategy.check_holding_time_exit(position, current_bar=20, config=make_config(
        holding_time_exit_loss_threshold=0.012,
        holding_time_exit_loss_bars=24,
    ))
    assert result is None

# ── Round 2 IOC metadata 路由 ──────────────────────────────────────

def test_backtest_pending_order_carries_fallback_metadata():
    """backtest pending order 必须携带 entry_execution_policy"""
    order = create_backtest_pending_order(config=make_config(
        open_market_fallback_enabled=True,
        open_market_fallback_max_slippage_bps=8,
    ))
    assert "entry_execution_policy" in order.metadata
    assert order.metadata["entry_execution_policy"] == "ioc_with_market_fallback"
    assert order.metadata["entry_market_fallback_enabled"] is True

def test_ioc_cancel_enters_fallback_when_metadata_present():
    """IOC 取消后，若 metadata 正确，应进入 fallback 尝试"""
    order = make_ioc_order(metadata={
        "entry_execution_policy": "ioc_with_market_fallback",
        "entry_market_fallback_enabled": True,
        "open_market_fallback_max_slippage_bps": 8,
        "signal_score": 0.90,
        "signal_type": "flip_bearish",
    })
    router = make_router(config=make_config(
        market_fallback_min_signal_score=0.88,
        market_fallback_allowed_signal_types=["flip_bearish"],
    ))
    diag = DiagnosticCollector()
    router.on_ioc_order_canceled(order, cancel_reason="ioc_no_fill", diag=diag)
    
    assert diag.market_fallback_attempted == 1
    assert diag.fallback_not_reached_after_ioc_cancel == 0

def test_ioc_cancel_blocked_by_score_gate():
    """低分信号不应进入 fallback"""
    order = make_ioc_order(metadata={
        "entry_execution_policy": "ioc_with_market_fallback",
        "entry_market_fallback_enabled": True,
        "signal_score": 0.72,        # 低于 0.88 门槛
        "signal_type": "flip_bearish",
    })
    router = make_router(config=make_config(
        market_fallback_min_signal_score=0.88,
    ))
    diag = DiagnosticCollector()
    router.on_ioc_order_canceled(order, cancel_reason="ioc_no_fill", diag=diag)
    
    assert diag.market_fallback_attempted == 0
    assert diag.fallback_score_gate_blocked == 1

def test_ioc_cancel_blocked_by_type_gate():
    """非白名单信号类型不应进入 fallback"""
    order = make_ioc_order(metadata={
        "entry_execution_policy": "ioc_with_market_fallback",
        "entry_market_fallback_enabled": True,
        "signal_score": 0.92,
        "signal_type": "red_bar_growing",  # 不在白名单
    })
    router = make_router(config=make_config(
        market_fallback_min_signal_score=0.88,
        market_fallback_allowed_signal_types=["flip_bearish"],
    ))
    diag = DiagnosticCollector()
    router.on_ioc_order_canceled(order, cancel_reason="ioc_no_fill", diag=diag)
    
    assert diag.market_fallback_attempted == 0
    assert diag.fallback_type_gate_blocked == 1

def test_metadata_alignment_live_equals_backtest():
    """live 和 backtest 生成的 metadata key 集合必须完全一致"""
    config = make_config(open_market_fallback_enabled=True, open_market_fallback_max_slippage_bps=8)
    signal = make_signal()
    
    live_meta     = ExecutionRouter._build_live_order_metadata(signal, config)
    backtest_meta = BacktestEngine._create_pending_order(signal, config).metadata
    
    required_keys = {
        "entry_execution_policy",
        "entry_market_fallback_enabled",
        "open_market_fallback_max_slippage_bps",
        "signal_score",
        "signal_type",
    }
    assert required_keys.issubset(set(live_meta.keys()))
    assert required_keys.issubset(set(backtest_meta.keys()))
```

---

## 6. 配置快照 — 下一轮建议的 live 默认

```json
{
  "_comment": "MACD V2 — 建议 Round 1 验收后的配置快照",
  "_version": "core_reset_r1_exit_fix",
  
  "max_active_symbols": 3,
  "reserve_pct": 0.20,
  "disable_flip_bullish_entries": true,
  
  "exit_config": {
    "macd_1h_flip_exit_enabled": true,
    "macd_1h_flip_exit_early_enabled": true,
    "macd_1h_flip_exit_early_bar_completion_pct": 0.75,
    "early_exit_pnl_threshold": 0.003,
    "rsi_overheat_exit_enabled": true,
    "holding_time_exit_enabled": true,
    "holding_time_exit_bars": 48,
    "holding_time_exit_loss_threshold": 0.012,
    "holding_time_exit_loss_bars": 24
  },
  
  "execution_degradation": {
    "open_ioc_retry_times": 4,
    "open_ioc_dynamic_step_enabled": true,
    "open_ioc_max_total_slippage_bps": 60,
    "force_market_fallback_on_ioc_remainder": false,
    "open_market_fallback_max_slippage_bps": 8,
    "market_fallback_min_signal_score": 0.88,
    "market_fallback_allowed_signal_types": ["flip_bearish"],
    "market_fallback_score_gate_enabled": true
  },
  
  "pretrade_risk_gate": {
    "enabled": false,
    "phase1_entry_only": true,
    "shadow_mode": false
  },
  
  "competition_ranking": {
    "enabled": false
  }
}
```

---

## 7. Sign-off 条件矩阵

```
Round     条件                                    目标值        当前值      通过？
──────────────────────────────────────────────────────────────────────────────
Round 1   30d strict-live Return                 ≥ 43.00%    41.58%      ✗
Round 1   30d strict-live WR                     ≥ 86.00%    87.78%      ✓（当前）
Round 1   30d strict-live MDD                    ≤  7.50%     8.23%      ✗
Round 1   30d strict-live PF                     ≥  6.50      6.15       ✗
Round 1   flip_bullish 成交                      = 0          0          ✓
Round 1   unit tests                             125 passed  125         ✓

Round 2   market_fallback_attempted              > 0          0          ✗
Round 2   fallback 成交 WR                       ≥ 75%        N/A        N/A
Round 2   IOC cancel rate                        ≤ 52%       58.53%     ✗

Round 3   fallback 新增后 PF 不降               ≥ 0 delta    N/A        N/A
Round 3   fallback 成交 WR                       ≥ 78%        N/A        N/A

Round 4   Return（cap=4）                        ≥ 45.00%     N/A        N/A
Round 4   MDD（cap=4）                           ≤  7.50%     N/A        N/A
──────────────────────────────────────────────────────────────────────────────
最终 sign-off  所有 Round 4 条件同时满足          —            —          未开始
```

---

## 8. 问题 9 的逐条回答

文档第 9 节提出的五个问题，逐条给出分析结论：

**Q1：`capacity=4 + competition_ranking + gate + exits` 全集成为什么反而把 MDD 推到 10%+？**

```
根因：competition_ranking 在容量扩充时引入了边际质量较低的候选单。
验证路径：消融实验 D（cap3+ranking）vs A（cap3无ranking）。
若 D.mdd > A.mdd + 1%，则 ranking 是主要贡献者，不是 capacity。
当前建议：先跑消融，数据出来前不恢复 ranking。
```

**Q2：`market_fallback_attempted = 0` 的根本原因是什么？**

```
根本原因：backtest 路径的 pending_order 在创建时没有写入
entry_execution_policy 和 entry_market_fallback_enabled 两个 metadata key。
on_ioc_order_canceled 拿不到 policy，直接跳过 fallback 分支。
修复点：backtest_macd_v2.py 的 _create_pending_order，见 3.3 节 DIFF。
```

**Q3：`pretrade_risk_gate phase1` 当前默认开启，但没有证明它改善了回撤收益比。**

```
当前结论：维持 enabled=false 直到有真实 3 个月数据。
理由：当前验证窗口数据覆盖不足（仅 2831 个 15m 点），
gate 的误判率无法在这个样本量下被准确估计。
恢复条件：补足 2026-01-01 ~ 2026-03-31 真实缓存后，做独立 gate 消融。
```

**Q4：`capacity=4` 是否应该保留为 live 默认？**

```
结论：当前不应保留 capacity=4 为 live 默认。
路径：先跑 Round 1（退出修复）稳住 MDD，再跑 Round 4（cap=4 消融），
有数据支撑后再升到 live 默认。
当前 live 保持 capacity=3。
```

**Q5：扩展窗口验证受数据覆盖限制，是否需要先补足缓存再 sign-off？**

```
结论：必须补足。
当前"2026-01-01 ~ 2026-03-31"产物与 30d strict-live 结果完全一致，
说明只是重放了同一批 2831 个时间点，没有新增市场状态。
建议：在 Round 1 退出修复验收后，把补充缓存列为 Round 2 前置条件，
而不是并行跑。补缓存期间可以把 metadata 路由修复代码准备好但不上线。
```

---

## 9. 关键风险提示

```
风险 1：early exit 引入胜率损耗
  场景：K线完成75%触发退出，但最终 K 线收盘时信号消失（假翻转）
  缓解：early_exit_pnl_threshold 不宜低于 -0.003（等同于 0.3% 浮亏才触发）
  监控：单测覆盖"假翻转场景"（macd_1h_flip_inbar=True 但 flip_confirmed=False）

风险 2：fallback 白名单过窄导致 cancel_rate 仍高
  场景：flip_bearish 占比在本样本中只有 17/90=18.9%，白名单限制后 fallback 触发次数极少
  缓解：如果 Round 3 验收时 cancel_rate 仍 > 55%，考虑把 red_bar_growing 高分段
         (score >= 0.90) 也加入白名单
  监控：分别统计 flip_bearish / red_bar_growing 的 fallback 成交 WR

风险 3：loss_gate 提前止损打乱 red_bar_growing 的正常持仓节奏
  场景：red_bar_growing 信号通常需要 30+ bars 才能到达 TP，
         loss_gate 24bars 可能在正常回撤期触发
  缓解：loss_gate 只在浮亏 > 1.2% 时才触发，正常回撤通常 < 0.8%
  监控：统计 loss_gate 触发的交易后续价格走势（如果触发后 8bars 内价格回升，说明门槛需要松）
```

---

## 10. 诊断脚本模板

```python
# scripts/diagnose_round1_exit_delay.py
"""
Round 1 退出延迟诊断：对比归核化基线与旧基线的退出时序差异
用途：量化 holding_time_exit_loss_gate 和 early_exit 的预期 MDD 改善
"""

import pandas as pd

def analyze_exit_delay(baseline_trades_csv, core_reset_trades_csv):
    baseline = pd.read_csv(baseline_trades_csv, parse_dates=["entry_time", "exit_time"])
    core     = pd.read_csv(core_reset_trades_csv, parse_dates=["entry_time", "exit_time"])
    
    # 按亏损单分析持有时间
    baseline_losses = baseline[baseline["pnl"] < 0].copy()
    core_losses     = core[core["pnl"] < 0].copy()
    
    baseline_losses["hold_min"] = (
        baseline_losses["exit_time"] - baseline_losses["entry_time"]
    ).dt.total_seconds() / 60
    core_losses["hold_min"] = (
        core_losses["exit_time"] - core_losses["entry_time"]
    ).dt.total_seconds() / 60
    
    print("=== 亏损单持有时间对比 ===")
    print(f"旧基线  median={baseline_losses.hold_min.median():.0f}min  "
          f"mean={baseline_losses.hold_min.mean():.0f}min  "
          f"max={baseline_losses.hold_min.max():.0f}min")
    print(f"归核化  median={core_losses.hold_min.median():.0f}min  "
          f"mean={core_losses.hold_min.mean():.0f}min  "
          f"max={core_losses.hold_min.max():.0f}min")
    
    print("\n=== 归核化亏损单 PnL 分布 ===")
    print(core_losses[["symbol", "hold_min", "pnl"]].describe())
    
    # 模拟 loss_gate 效果：如果在 24bars(=360min) 且 pnl < -threshold 时强制退出
    # 需要 bars 粒度数据；此处用时间近似
    LOSS_GATE_MIN   = 360   # 24 * 15min
    LOSS_THRESHOLD  = -0.012
    
    # 筛出"会被 loss_gate 打掉的"亏损单
    gateable = core_losses[
        (core_losses["hold_min"] >= LOSS_GATE_MIN) &
        (core_losses["pnl"] < LOSS_THRESHOLD)
    ]
    print(f"\n=== 模拟 loss_gate 命中 ===")
    print(f"会被 loss_gate 提前止损的亏损单数: {len(gateable)}")
    print(f"这些单的 PnL 合计: {gateable.pnl.sum():.2f}")
    print(f"预期 PF 改善（消除这些亏损）: "
          f"当前总亏损={core_losses.pnl.sum():.2f} → "
          f"修正后={core_losses.pnl.sum() - gateable.pnl.sum():.2f}")

if __name__ == "__main__":
    analyze_exit_delay(
        "output/backtest/v2_live_equiv_20260430_trades.csv",
        "output/backtest/v2_core_reset_20260501_trades.csv",
    )
```

---

*文档生成时间：2026-05-01*
*基于产物版本：v2_core_reset_20260501 / v2_surgical_fix_20260501 / v2_live_equiv_20260430*
*下次更新节点：Round 1 回测产物产出后*
