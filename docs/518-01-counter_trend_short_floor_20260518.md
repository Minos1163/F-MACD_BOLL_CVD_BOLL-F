# 逆势多单保护 + SHORT 微仓 Floor 修复
**日期**: 2026-05-18  
**两个独立 bug，今天同时修**  
**Bug A**: 价格低于 VWAP 时仍可开大仓多单 → TON/RENDER/ETC 亏损  
**Bug B**: SHORT 仓位被多层压缩到 0.000315 → 执行层 min_notional 拒绝 47 笔

---

## Bug A：逆势多单保护

### 根因

```
三笔亏损多单共同特征：
  TON:    dev=-4.57%, ADX=17.38, RANGE边界, 15M=0.0135, target=0.268
  RENDER: dev=-1.48%, ADX=12.76, RANGE,     15M=0.0135, target=0.268
  ETC:    dev=-1.96%, ADX=25.42, TREND,     15M=0.0120, target=0.040 (trial)

共同问题：价格低于 VWAP 做多 = 从均价下方抢反弹
在空头/弱势环境里，这是逆势操作，不是趋势跟随

VWAP dev < 0 + LONG 的含义：
  价格当前低于日内均价
  买入成本低于市场参与者平均成本
  如果空头持续 → 价格继续下跌 → 立即亏损

正确做法：
  dev < 0 时做多 → 至少要求 15M 出现强反转确认
  dev < -3% 时做多 → 降级为 probe 或 block（视 ADX 和 regime）
```

### [命令 A-1] 逆势多单保护门控

```python
# src/fund_flow/macd_strategy_v2.py
# 在 score_aggregation 之后、threshold_check 之前插入

def _check_counter_trend_long_guard(
    self,
    direction:    str,
    vwap_dev_pct: float,      # (price - vwap) / vwap，负 = 价格低于 VWAP
    adx:          float,
    regime:       str,        # "TREND" / "RANGE" / "NO_TRADE"
    score_15m:    float,      # 15M entry score
    raw_15m:      float,      # 15M raw RSI score
    signal_4h:    str,
    signal_1h:    str,
    current_portion: float,
) -> dict:
    """
    只处理 LONG 方向。
    返回：{ "action": "PASS"|"PROBE"|"BLOCK", "max_portion": float, "reason": str }
    """
    if direction != "long":
        return {"action": "PASS", "max_portion": current_portion, "reason": "not_long"}

    # ── 1. 判断是否逆势多单（价格低于 VWAP）────────────────
    is_below_vwap = vwap_dev_pct < 0
    if not is_below_vwap:
        return {"action": "PASS", "max_portion": current_portion,
                "reason": "above_vwap_long_ok"}

    # ── 2. 计算 15M 确认强度 ─────────────────────────────────
    has_15m_confirm = (raw_15m >= 0.30)   # raw >= 0.30 = 明确 15M 触发

    # ── 3. 分层判断 ──────────────────────────────────────────
    dev_abs = abs(vwap_dev_pct)

    # 极端偏离（>3%）：弱势 ADX 或 RANGE → 直接 block
    if dev_abs > 0.03:
        if regime == "RANGE" or adx < 20:
            return {
                "action":  "BLOCK",
                "max_portion": 0.0,
                "reason":  f"below_vwap_{dev_abs:.2%}_adx={adx:.1f}_range_block",
            }
        # TREND 但 ADX 较强：允许极小 probe
        if not has_15m_confirm:
            return {
                "action":      "PROBE",
                "max_portion": 0.040,
                "reason":      f"below_vwap_{dev_abs:.2%}_no_15m_probe",
            }
        # TREND + 有 15M 确认：允许 probe
        return {
            "action":      "PROBE",
            "max_portion": 0.060,
            "reason":      f"below_vwap_{dev_abs:.2%}_15m_confirmed_probe",
        }

    # 中等偏离（1%~3%）：要求 15M 确认
    if dev_abs > 0.01:
        if not has_15m_confirm:
            return {
                "action":      "PROBE",
                "max_portion": 0.060,
                "reason":      f"below_vwap_{dev_abs:.2%}_no_15m_probe",
            }
        if regime == "RANGE" or adx < 18:
            return {
                "action":      "PROBE",
                "max_portion": 0.060,
                "reason":      f"below_vwap_{dev_abs:.2%}_range_adx_probe",
            }
        # 有 15M + 不是 RANGE + ADX 够：正常通过但压仓
        return {
            "action":      "PASS",
            "max_portion": min(current_portion, 0.12),
            "reason":      f"below_vwap_{dev_abs:.2%}_15m_ok_capped_0.12",
        }

    # 轻微偏离（<1%）：基本通过，轻压仓
    return {
        "action":      "PASS",
        "max_portion": min(current_portion, 0.20),
        "reason":      f"below_vwap_{dev_abs:.2%}_minor_capped_0.20",
    }
```

### [命令 A-2] 插入位置

```python
# 在 final threshold_check 之前，约 _evaluate_signal() 尾部

ct_guard = self._check_counter_trend_long_guard(
    direction    = direction,
    vwap_dev_pct = vwap_dev_actual,   # 从 VWAP gate 计算结果传入
    adx          = market_ctx.adx,
    regime       = market_ctx.regime,
    score_15m    = score_15m,
    raw_15m      = raw_15m_score,
    signal_4h    = signal_4h,
    signal_1h    = signal_1h,
    current_portion = target_portion,
)

if ct_guard["action"] == "BLOCK":
    return self._neutral_signal(
        reason=ct_guard["reason"],
        code="counter_trend_long_block"
    )

if ct_guard["action"] == "PROBE":
    target_portion = min(target_portion, ct_guard["max_portion"])
    signal.max_portion_hard_cap = ct_guard["max_portion"]
    self._log_info(f"[CT_GUARD] {symbol} probe capped: {ct_guard['reason']}")

elif ct_guard["action"] == "PASS" and "max_portion" in ct_guard:
    target_portion = min(target_portion, ct_guard["max_portion"])
```

### [命令 A-3] 配置

```diff
# config/trading_config_fund_flow.json

+ "counter_trend_long_guard": {
+   "enabled":                   true,
+   "vwap_dev_extreme_pct":      0.030,   # >3% → block/probe
+   "vwap_dev_moderate_pct":     0.010,   # 1~3% → 要求 15M
+   "adx_weak_threshold":        18,
+   "min_15m_raw_for_confirm":   0.30,
+   "extreme_trend_max_portion": 0.060,
+   "extreme_range_action":      "BLOCK",
+   "moderate_no_15m_max":       0.060,
+   "moderate_ok_max":           0.120,
+   "minor_max":                 0.200
+ }
```

### 本次覆盖的三个亏损案例

```
TON:    dev=-4.57% (>3%), ADX=17.38 (<20), RANGE边界
        → extreme_range_action = BLOCK ✓

RENDER: dev=-1.48% (1~3%), ADX=12.76 (<18), RANGE
        → moderate + RANGE → PROBE max=0.060 ✓（从 0.268 降到 0.060）

ETC:    dev=-1.96% (1~3%), ADX=25.42 (>=20), TREND
        trial=True, 无 15M 强确认 (raw=0.24 < 0.30)
        → moderate + no_15m → PROBE max=0.060 ✓
```

---

## Bug B：SHORT 微仓 Floor 修复

### 根因

```python
# 仓位压缩链（估算）：
base = 0.35

# green_bar_growing probe overlay（config）
after_probe_overlay = base * 0.10   # green_bar_growing_probe_position_penalty
# → 0.35 × 0.10 = 0.035

# dynamic sizing（vwap/vol/adx 叠加）
after_dynamic = 0.035 * 0.60 * 0.75
# → 0.035 × 0.45 = 0.01575

# RSI rhythm penalty
after_rsi = 0.01575 * 0.88
# → 0.01575 × 0.88 = 0.01386

# combo probe cap
after_combo = min(0.01386, 0.06) → 0.01386（已低于 0.06）

# 账户 111U × 0.01386 = 1.54U < 2U → min_notional rejected

# 实际日志中更极端的案例：
# JSTUSDT target=0.000630 → 111U × 0.000630 = 0.070U
# 这说明 green_bar_growing_probe_position_penalty 之外还有额外压缩

# 最可能是 green_bar_growing_probe_position_penalty=0.1 × 多层 RSI/session 叠加
# = 0.35 × 0.1 × 0.6 × 0.75 × 0.88 × 0.9 × ... ≈ 0.000x
```

### [命令 B-1] 策略层 SHORT 可执行 Floor

```python
# src/fund_flow/macd_strategy_v2.py 或 fund_flow_bot.py
# 在最终 target_portion 确定后、提交 execute 前

def _apply_short_executable_floor(
    self,
    symbol:           str,
    direction:        str,
    target_portion:   float,
    signal_score:     float,
    account_equity:   float,
) -> float | None:
    """
    对已通过方向和分数检查的 SHORT 信号，
    确保 target_portion 对应的名义价值 >= min_notional。
    如果提升后仍有违反其他风控的风险，返回 None（策略层 HOLD，不进执行层）。
    """
    if direction != "short":
        return target_portion   # 只处理 SHORT

    min_notional = self._get_min_notional(symbol)   # 2U / 3U / 5U
    notional = target_portion * account_equity

    if notional >= min_notional:
        return target_portion   # 已经够大

    # 计算达到 min_notional 需要的最小 portion
    min_executable_portion = min_notional / account_equity
    # 111U 账户，2U → 0.01802，3U → 0.02703，5U → 0.04505

    # 仓位提升幅度检查：提升比例不超过 5 倍（防止从 0.0001 跳到 0.02 产生意外）
    MAX_LIFT_RATIO = 5.0
    if min_executable_portion > target_portion * MAX_LIFT_RATIO:
        # 原始仓位太小，提升幅度太大，策略层 HOLD（不进执行层 error）
        self._log_info(
            f"[SHORT_FLOOR] {symbol} target={target_portion:.6f} "
            f"too small to lift (ratio={min_executable_portion/target_portion:.1f}x > {MAX_LIFT_RATIO}x), "
            f"strategy HOLD"
        )
        return None   # 调用方返回 HOLD，不进执行层

    # 提升到可执行水平
    self._log_info(
        f"[SHORT_FLOOR] {symbol} score={signal_score:.4f} "
        f"target={target_portion:.6f}({notional:.3f}U) → "
        f"floor={min_executable_portion:.6f}({min_notional}U)"
    )
    return min_executable_portion
```

### [命令 B-2] green_bar_growing probe penalty 上限

```python
# 根因之一是 green_bar_growing_probe_position_penalty=0.1 过低
# 导致多层叠加后变成 0.0001 数量级

def _apply_green_bar_probe_penalty(
    self,
    base_portion: float,
    penalty_mult: float,   # 当前配置 0.1
) -> float:
    """
    probe penalty 乘以系数，但设置下限：
    结果不能低于 min_notional 对应的 portion
    """
    result = base_portion * penalty_mult

    # 下限：2U 对应的 portion（假设 account ~111U）
    min_portion = self.config.min_open_notional.default_usdt / self.account_equity
    # ≈ 2/111 = 0.018

    if result < min_portion:
        self._log_debug(
            f"green_bar_probe_penalty floor: "
            f"{result:.6f} → {min_portion:.6f}"
        )
        return min_portion

    return result
```

```diff
# config/trading_config_fund_flow.json

  "macd_v2": {
-   "green_bar_growing_probe_position_penalty": 0.10,
+   "green_bar_growing_probe_position_penalty": 0.25,   # 从 0.1 提到 0.25
+   # 0.35 × 0.25 = 0.0875，账户 111U → 9.7U，足够执行

+   "probe_penalty_floor_notional_usdt": 2.0,           # 任何 penalty 结果不低于 2U
  }
```

### [命令 B-3] 执行层 min_notional error 改为策略层 HOLD

```python
# src/fund_flow/risk_engine.py
# validate_target_portion() 目前是 raise，改为 soft return

def validate_target_portion(
    self,
    symbol:          str,
    direction:       str,
    target_portion:  float,
    signal_score:    float,
    account_equity:  float,
) -> float | None:
    notional = target_portion * account_equity
    min_notional = self._get_min_notional(symbol)

    if notional >= min_notional:
        return target_portion   # 通过

    # 不再 raise，改为 None → 调用方做 HOLD
    self._log_info(
        f"[MIN_NOTIONAL] {symbol} {direction} "
        f"notional={notional:.3f}U < {min_notional}U, HOLD"
    )
    return None   # 调用方检查 None → 返回 HOLD decision

# 调用方（fund_flow_bot.py）：
validated_portion = risk_engine.validate_target_portion(...)
if validated_portion is None:
    return DecisionResult.hold(reason="min_notional_below_floor")
```

### 修复后预期

```
修复前：
  47 笔 SELL → execution error → min_notional failed → 日志里是 error
  这些 error 浪费了下单队列时间，且看起来像执行故障

修复后：
  green_bar_growing probe penalty 从 0.10 → 0.25
  → target_portion 从 0.00035 → 约 0.0088
  → 111U × 0.0088 = 0.977U（仍低于 2U → SHORT_FLOOR 提升到 0.018）

  SHORT_FLOOR 提升到 0.018（2U 对应）：
  → 大多数 SELL 能通过 min_notional
  → error 从 47 → 预期 < 5

  对于原始仓位过小（提升超 5 倍）的候选：
  → 策略层 HOLD，不进执行层
  → error 归零
```

---

## 配置汇总

```diff
# config/trading_config_fund_flow.json

+ "counter_trend_long_guard": {
+   "enabled":               true,
+   "vwap_dev_extreme_pct":  0.030,
+   "vwap_dev_moderate_pct": 0.010,
+   "adx_weak_threshold":    18,
+   "min_15m_raw_for_confirm": 0.30,
+   "extreme_range_action":  "BLOCK",
+   "extreme_trend_max":     0.060,
+   "moderate_no_15m_max":   0.060,
+   "moderate_ok_max":       0.120,
+   "minor_max":             0.200
+ },

  "macd_v2": {
-   "green_bar_growing_probe_position_penalty": 0.10,
+   "green_bar_growing_probe_position_penalty": 0.25,
+   "probe_penalty_floor_notional_usdt":        2.0,
+   "short_floor_max_lift_ratio":               5.0
  },

  "min_open_notional": {
    "default_usdt": 2.0,
-   "major_usdt":   5.0,
+   "major_usdt":   2.0,     # SOL/XRP 等也改为 2U，只有 BTC 是 5U
    "btc_usdt":     5.0
  }
```

---

## 执行清单

```
今天：
□ _check_counter_trend_long_guard() 写入并插入 score_aggregation 后
□ _apply_short_executable_floor() 在策略层输出 portion 后调用
□ green_bar_growing_probe_position_penalty: 0.10 → 0.25
□ validate_target_portion raise → 返回 None（调用方 HOLD）
□ major_usdt: 5.0 → 2.0
□ pre_live_assertions 加断言：ct_guard.enabled=true，penalty>=0.20
□ 重启，verify_deployment.py ✅

12H 后验收：
□ execution error 次数：从 47 降到 < 5
□ counter_trend_long_block/probe 出现在日志
□ SHORT_FLOOR 日志出现，说明 floor 在生效

24H 后：
□ LONG WR（含 ct_guard 保护后）>= 65%
□ SHORT 实际成交数量 >= 5/12H
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-18*  
*今天两件：LONG 逆势保护 + SHORT 微仓 Floor。不动其他参数。*
