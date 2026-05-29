# VWAP 完全消融 + 慢牛 Detector 阈值修复
**日期**: 2026-05-24  
**两件事**: VWAP 从阻断者变成纯辅助评分（不阻断任何 entry）+ 慢牛 detector 修复让 is_bull 能进入 true

---

## Part 1：VWAP 完全消融

### 为什么 VWAP 在当前策略里起反作用

```
本窗口证据：
  HYPE +4.75%  → vwap_hard_block，0 次 BUY
  WLD  +2.19%  → vwap_hard_block × 14，0 次 BUY
  ONDO +3.66%  → vwap_score_filter × 10，0 次 BUY
  MORPHO +2.59% → vwap_score_filter × 4，0 次 BUY

VWAP 的原始用途（传统技术分析）：
  日内均价线，价格在上方代表买盘强，在下方代表卖盘强
  作为支撑/阻力参考

为什么在本策略中失效：
  1. 强势上涨行情中，价格加速离开 VWAP 是正常现象
     VWAP score 极低 = 价格已经涨远了，但这正是趋势最强的时候
  2. 弱势标的反而会在 VWAP 附近震荡，vwap_score 反而高
  3. 导致：强的买不了，弱的买了
  
  这是 VWAP 在动量策略中的典型反直觉现象：
  VWAP 适合均值回归策略，不适合趋势跟随/动量策略
```

### 修复方案：VWAP 从 Hard Block 变为纯位置信息

```python
# src/fund_flow/macd_strategy_v2.py
# 找到所有 vwap_hard_block / vwap_score_filter 的阻断点，全部删除

# ── 删除 1：vwap_hard_block 阶段 ───────────────────────────────
# 原有代码（删除）：
# vwap_gate = self._check_vwap_deviation(dev_abs_pct, atr_pct)
# if vwap_gate["action"] == "BLOCK":
#     return self._neutral_signal(reason="vwap_hard_block", ...)

# 替换为（不再 block，只记录信息）：
vwap_info = self._compute_vwap_info(price, vwap, atr_pct)
# vwap_info 用于后续仓位计算参考，不用于阻断


# ── 删除 2：vwap_score_filter 阶段 ─────────────────────────────
# 原有代码（删除）：
# if score_vwap < self.config.vwap_score_min:   # 0.06
#     return self._neutral_signal(reason="vwap_score_filter", ...)

# 替换为（直接跳过，不阻断）：
# vwap_score 仍然计算并进入总分，但不再是独立阻断条件


# ── VWAP 只剩一个作用：小额调整仓位 ───────────────────────────
def _vwap_as_position_modifier(
    self,
    direction:     str,
    price:         float,
    vwap:          float,
    current_portion: float,
) -> float:
    """
    VWAP 的唯一剩余作用：轻微影响仓位，不阻断
    返回调整后的 portion
    """
    if vwap <= 0:
        return current_portion

    dev_pct = (price - vwap) / vwap

    # 做多且价格高于 VWAP：轻微加权（追强势，正当）
    if direction == "long" and dev_pct > 0:
        return min(current_portion * 1.05, self.config.max_symbol_position_portion)

    # 做多且价格低于 VWAP 超过 5%：轻微减仓（逆势，谨慎）
    if direction == "long" and dev_pct < -0.05:
        return current_portion * 0.85

    # 做空且价格低于 VWAP：轻微加权（顺势做空）
    if direction == "short" and dev_pct < 0:
        return min(current_portion * 1.05, self.config.max_symbol_position_portion)

    # 其余情况：不干预
    return current_portion
```

### 配置修改

```diff
# config/trading_config_fund_flow.json

# ── 删除或置零所有 VWAP 阻断参数 ─────────────────────────────

- "vwap_deviation_hard_block": 0.03,
+ "vwap_deviation_hard_block": null,    # 完全禁用

- "vwap_score_filter": {
-   "normal_min":  0.0400,
-   "probe_min":   0.0300,
- },
+ "vwap_score_filter": {
+   "enabled":     false,               # 完全禁用
+ }

- "vwap_deviation_gate": {
-   "mode":                   "atr_normalized",
-   "block_atr_multiplier":    4.0,
- },
+ "vwap_deviation_gate": {
+   "mode":    "position_modifier_only",   # 只做仓位微调
+   "enabled": false,                       # gate 模式禁用
+ }

# ── VWAP 权重降到最小 ─────────────────────────────────────────
  "scoring_weights": {
    "weight_1h_direction":   0.150,
    "weight_4h_direction":   0.450,
    "weight_rsi_rhythm":     0.220,
-   "weight_vwap":           0.000,     # 已经是 0，维持
+   "weight_vwap":           0.000,     # VWAP 不参与总分
    "weight_15m_entry":      0.080,
    "weight_volume":         0.100
  }
```

### 同步删除 VWAP 相关的 pretrade gate

```diff
# config/trading_config_fund_flow.json — entry_quality_gates

  "entry_quality_gates": {
-   "vwap_score_hard_block": {
-     "below_block":  0.12,
-     "below_probe":  0.30,
-     "probe_max":    0.042
-   },
+   "vwap_score_hard_block": {
+     "enabled": false    # 完全禁用
+   },

    "15m_hard_gate": { ... },   # 保留
    "no_trade_gate": { ... },   # 保留
    "range_gate":    { ... },   # 保留
  }
```

### pre_live_assertions 更新

```python
def assert_vwap_fully_ablated(cfg: dict) -> list[str]:
    errors = []

    # vwap_deviation_hard_block 必须不存在或为 null
    hb = cfg.get("vwap_deviation_hard_block")
    if hb is not None and hb > 0:
        errors.append(f"vwap_deviation_hard_block={hb}, must be null/0")

    # vwap_score_filter 必须禁用
    vsf = cfg.get("vwap_score_filter", {})
    if vsf.get("enabled", True):
        errors.append("vwap_score_filter.enabled must be false")

    # vwap_score_hard_block 必须禁用
    vhb = cfg.get("entry_quality_gates", {}).get("vwap_score_hard_block", {})
    if vhb.get("enabled", True):
        errors.append("entry_quality_gates.vwap_score_hard_block.enabled must be false")

    return errors
```

---

## Part 2：慢牛 Detector 修复

### 当前阈值与真实行情的错配

```python
# 当前规则（失效原因）：
current_conditions = {
    "btc_30m":   btc_30m  >= 0.003,   # BTC 涨 0.3% 才算
    "btc_60m":   btc_60m  >= 0.005,   # BTC 涨 0.5% 才算
    "breadth":   breadth  >= 0.60,
    "alt_median": alt_median_60m >= 0.004,  # alt 中位涨 0.4%
}
# 需要 3/4 满足，且连续 2 个 cycle

# 本窗口实际数据：
# breadth=0.96（极强），alt_med60=0.605%（够），
# btc_30m=-0.04%（不够）→ 只满足 2/4 → is_bull=False

# 问题根因：BTC 阈值太高，把"BTC 震荡 + alt 自发广谱上涨"漏掉了
# 而这恰恰是最常见的慢牛形态
```

### 修复：三种慢牛模式分开判断

```python
# src/fund_flow/market_breadth.py — detect() 替换

def detect(self) -> dict:
    """
    三种慢牛识别模式，任一满足即进入 slow_bull
    """
    if len(self._btc_rets) < 2:
        return {"is_slow_bull": False, "mode": None, "reason": "no_data"}

    btc_30m = sum(list(self._btc_rets)[-2:]) if len(self._btc_rets) >= 2 else 0
    btc_60m = sum(list(self._btc_rets)[-4:]) if len(self._btc_rets) >= 4 else btc_30m

    alt_60m_rets = []
    for sym, dq in self._alt_rets.items():
        if len(dq) >= 4:
            alt_60m_rets.append(sum(list(dq)[-4:]))
        elif len(dq) >= 2:
            alt_60m_rets.append(sum(list(dq)[-2:]))

    if not alt_60m_rets:
        return {"is_slow_bull": False, "mode": None, "reason": "no_alt_data"}

    alt_60m_rets.sort()
    n              = len(alt_60m_rets)
    alt_median_60m = alt_60m_rets[n // 2]
    breadth_ratio  = sum(1 for r in alt_60m_rets if r > 0) / n

    # ── 模式 A：强广谱主导（BTC 不需要领涨）──────────────────
    # 本窗口真实场景：breadth=0.96，btc 微涨/震荡
    mode_a = (
        breadth_ratio  >= 0.80 and              # 80%+ 上涨
        alt_median_60m >= 0.0025 and            # alt 中位涨 0.25%+
        btc_30m        >= -0.001                # BTC 没有明显下跌（> -0.1%）
    )

    # ── 模式 B：BTC 领涨 + 广谱跟随（原有逻辑的宽松版）──────
    mode_b = (
        btc_30m        >= 0.002 and             # BTC 30M 涨 0.2%+（降低阈值）
        breadth_ratio  >= 0.60 and
        alt_median_60m >= 0.003                 # alt 中位涨 0.3%+
    )

    # ── 模式 C：极端广谱（几乎全部上涨）─────────────────────
    mode_c = (
        breadth_ratio  >= 0.90 and              # 90%+ 上涨
        alt_median_60m >= 0.001                 # alt 中位涨 0.1%+ 即可
    )

    is_bull_candidate = mode_a or mode_b or mode_c
    mode_name = (
        "alt_breadth_led"  if mode_a else
        "btc_led"          if mode_b else
        "extreme_breadth"  if mode_c else
        "none"
    )

    # 持续确认（仍需 2 个 cycle）
    if is_bull_candidate:
        self._confirm_count  = min(self._confirm_count + 1, self.cfg.confirm_cycles)
        self._invalid_count  = 0
    else:
        self._invalid_count  = min(self._invalid_count + 1, self.cfg.invalidate_cycles)
        self._confirm_count  = max(self._confirm_count - 1, 0)

    self._is_slow_bull = self._confirm_count >= self.cfg.confirm_cycles

    reason = (
        f"mode_a={mode_a}(breadth={breadth_ratio:.2f},btc30={btc_30m:.3%},"
        f"alt_med={alt_median_60m:.3%}) "
        f"mode_b={mode_b} mode_c={mode_c}"
    )

    return {
        "is_slow_bull":     self._is_slow_bull,
        "mode":             mode_name if self._is_slow_bull else None,
        "breadth_ratio":    breadth_ratio,
        "btc_ret_30m":      btc_30m,
        "btc_ret_60m":      btc_60m,
        "alt_median_60m":   alt_median_60m,
        "confirm_count":    self._confirm_count,
        "reason":           reason,
    }
```

### SLOW_BULL_HOLD 必须逐 symbol 打印

```python
# src/fund_flow/macd_strategy_v2.py
# _evaluate_continuation_long_candidate() 修改，不满足时必须打印

def _evaluate_continuation_long_candidate(self, symbol, ...) -> dict:
    if not breadth_state.get("is_slow_bull", False):
        # 必须打印，不能静默
        self._log_debug(
            f"[SLOW_BULL_HOLD] {symbol} not_slow_bull "
            f"breadth={breadth_state.get('breadth_ratio', 0):.2f} "
            f"btc30={breadth_state.get('btc_ret_30m', 0):.3%} "
            f"alt_med60={breadth_state.get('alt_median_60m', 0):.3%} "
            f"confirm={breadth_state.get('confirm_count', 0)}"
        )
        return {"allowed": False, "reason": "not_slow_bull"}

    # ... 动量条件检查 ...
    if met < 4:
        self._log_debug(
            f"[SLOW_BULL_HOLD] {symbol} momentum_insufficient "
            f"({met}/6) failed={failed} "
            f"ret30={symbol_ret_30m:.3%} ret60={symbol_ret_60m:.3%} "
            f"rsi={rsi_15m:.1f} ema_slope={ema_slope_15m:.4f}"
        )
        return {"allowed": False, "reason": f"momentum_insufficient ({met}/6)"}

    # 允许时打印
    self._log_info(
        f"[SLOW_BULL_CANDIDATE] {symbol} {cont_result['reason']}"
    )
    return {"allowed": True, ...}
```

### 修复 short guard 集成位置

```python
# src/fund_flow/decision_engine.py 或 macd_strategy_v2.py
# 错误：BUY 分支内调用了 short guard
# 修复：strict 分支隔离

def _evaluate_signal(self, symbol, market_ctx):
    ...
    # BUY 分支
    if direction == "long":
        # 不调用 short guard
        # 只走：15m_gate → btc_regime_gate → vwap_modifier → continuation
        pass

    # SHORT 分支
    if direction == "short":
        # 只有这里才调用 short guard
        short_guard = self._apply_slow_bull_short_guard(
            direction      = "short",
            signal_1h      = signal_1h,
            vwap_score     = vwap_score,
            breadth_ratio  = breadth_state.get("breadth_ratio", 0),
            is_slow_bull   = breadth_state.get("is_slow_bull", False),
        )
        if short_guard["action"] == "BLOCK":
            return self._neutral_signal(reason=short_guard["reason"])
```

---

## 配置汇总

```diff
# config/trading_config_fund_flow.json

# ── VWAP 完全消融 ────────────────────────────────────────────────
- "vwap_deviation_hard_block": 0.03,
+ "vwap_deviation_hard_block": null,

  "vwap_score_filter":    { "enabled": false },
  "vwap_deviation_gate":  { "mode": "position_modifier_only", "enabled": false },
  "entry_quality_gates.vwap_score_hard_block": { "enabled": false },

# ── 慢牛 Detector 放宽 ───────────────────────────────────────────
  "market_breadth": {
    "enabled":                  true,
+   "mode_a_breadth_min":       0.80,    # 新增模式 A
+   "mode_a_alt_median_min":    0.0025,
+   "mode_a_btc_min":          -0.001,
+   "mode_b_btc_30m_min":       0.002,   # 原 BTC led，阈值降低
+   "mode_b_breadth_min":       0.60,
+   "mode_b_alt_median_min":    0.003,
+   "mode_c_breadth_min":       0.90,    # 新增极端广谱模式
+   "mode_c_alt_median_min":    0.001,
    "confirm_cycles":           2,
    "invalidate_cycles":        2
  }
```

---

## 验收标准

```bash
# VWAP 消融验证
grep "vwap_hard_block\|vwap_score_filter" logs/... | wc -l
# 预期：0（完全消失）

# 慢牛 detector 验证（在 breadth >= 0.8 窗口内）
grep "is_bull=True" logs/... | wc -l
# 预期：> 5

grep "SLOW_BULL_CANDIDATE" logs/... | wc -l
# 预期：> 0，HYPE/ZEC/ONDO 等强势币出现候选

grep "SLOW_BULL_HOLD" logs/... | wc -l
# 预期：每 cycle 有打印（可见候选失败原因）
```

---

## 执行清单

```
今天：
□ macd_strategy_v2.py：删除 vwap_hard_block 和 vwap_score_filter 阻断
□ macd_strategy_v2.py：_vwap_as_position_modifier() 替换（只调整仓位）
□ market_breadth.py：detect() 改三模式
□ _evaluate_continuation_long_candidate()：not_slow_bull 必须打印 SLOW_BULL_HOLD
□ decision_engine.py：short guard 移出 BUY 分支
□ config：VWAP 所有 gate 禁用，market_breadth 三模式阈值
□ pre_live_assertions：assert_vwap_fully_ablated
□ 重启，verify_deployment.py ✅

不动：
❌ ExitGuard（正在有效工作）
❌ 15m_hard_gate（保留）
❌ no_trade/range gate（保留）
❌ BTC beta scorer（正在有效工作）
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-24*  
*VWAP 不再阻断任何 entry；慢牛 detector 支持 BTC 震荡 + alt 广谱上涨的模式*
