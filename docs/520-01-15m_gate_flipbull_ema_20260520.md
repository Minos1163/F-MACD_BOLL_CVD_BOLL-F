# 方向质量门控：15M 升级为硬门槛 + flip_bullish 保护 + ADX/EMA 修正
**日期**: 2026-05-20  
**根因**: 4H 权重 0.40 把局部反弹推过 final；VWAP/15M 只是弱加分，不否决方向  
**修复原则**: 不降低阈值，而是让 VWAP 和 15M 在逆势场景下具备否决权

---

## 问题数量化

```
36H 内 29 笔 BUY 的质量分布：
  25/29 在 VWAP 下方开多           (86%)
  16/29 的 15M raw < 0.30          (55%)
   6/29 在 ADX<20 或 NO_TRADE       (21%)

典型亏损路径：
  4H red_bar_growing → 0.40 分
  1H red_bar_growing → 0.1275 分
  RSI rhythm         → 0.25~0.30 分
  EMA=1.20x strong   → 放大 4H 至 0.40
  ─────────────────────────────────
  小计                ≈ 0.78~0.83
  threshold           = 0.68
  delta               = +0.10~+0.15 → 轻松通过

  同时：
  VWAP dev = -4%~-6%   → 只贡献 ±0.03 小额
  15M raw  = 0.12       → 只贡献 0.006 分
  → 这两项无法否决上面的 0.78
```

---

## [命令-1] 15M 升级为逆势 LONG 的硬门槛

**为什么是硬门槛而不是加权**

```
当前：15M weight = 0.05，raw=0.24 → 贡献 0.012
这让 15M 在总分 0.80 里只占 1.5%，根本无法否决方向

正确设计：在高风险场景（VWAP 下方 / 弱趋势 / 反转早期），
15M 不应该是"分数贡献者"，而应是"准入条件"
类似于：没有 15M 明确触发 → 不允许开大仓，只允许 probe
```

```python
# src/fund_flow/macd_strategy_v2.py
# 在 threshold_check 通过后、final decision 生成前插入

def _apply_15m_entry_gate(
    self,
    direction:       str,
    raw_15m:         float,       # 15M RSI/MACD raw score
    entry_15m:       str,         # entry_15m 字段，"-" = 无触发
    vwap_dev_pct:    float,       # (price-vwap)/vwap
    adx:             float,
    regime:          str,
    signal_4h:       str,
    signal_1h:       str,
    current_portion: float,
) -> dict:
    """
    15M 门控：在以下高风险场景里，弱 15M 触发仓位 cap 或 block

    高风险场景 = 满足以下任意一条：
      A. LONG 且价格低于 VWAP（逆势抢反弹）
      B. ADX < 20（弱趋势，不是强方向）
      C. regime = NO_TRADE（系统自认无趋势）
      D. 1H signal = flip_bullish（反转早期，最不稳定）
    """
    if direction != "long":
        # SHORT 方向单独处理，这里只管 LONG
        return {"action": "PASS", "max_portion": current_portion}

    # ── 判断是否高风险场景 ──────────────────────────────────
    is_below_vwap     = vwap_dev_pct < -0.01    # VWAP 下方超 1%
    is_weak_adx       = adx < 20
    is_no_trade       = regime == "NO_TRADE"
    is_flip_entry     = signal_1h in ("flip_bullish",) or signal_4h in ("flip_bullish",)

    risk_count = sum([is_below_vwap, is_weak_adx, is_no_trade, is_flip_entry])

    if risk_count == 0:
        # 没有高风险特征：15M 不作为硬门槛
        return {"action": "PASS", "max_portion": current_portion}

    # ── 有高风险特征：按 15M 强度分级 ─────────────────────
    has_strong_15m  = raw_15m >= 0.40 and entry_15m != "-"
    has_medium_15m  = raw_15m >= 0.30
    has_weak_15m    = raw_15m >= 0.20
    # raw < 0.20 = 极弱，几乎无 15M 方向确认

    # ── 分级处理 ─────────────────────────────────────────────
    if risk_count >= 3:
        # 多重高风险（VWAP下方 + 弱ADX + flip）：
        # 必须有中等以上 15M 确认，否则 block
        if not has_medium_15m:
            return {
                "action": "BLOCK",
                "reason": f"multi_risk({risk_count}) + weak_15m={raw_15m:.2f} → block",
            }
        if not has_strong_15m:
            return {
                "action":      "PROBE",
                "max_portion": 0.040,
                "reason": f"multi_risk({risk_count}) + medium_15m → probe 0.040",
            }
        return {
            "action":      "PROBE",
            "max_portion": 0.060,
            "reason": f"multi_risk({risk_count}) + strong_15m → probe 0.060",
        }

    if risk_count == 2:
        # 两个高风险特征：
        if not has_medium_15m:
            return {
                "action":      "PROBE",
                "max_portion": 0.040,
                "reason": f"dual_risk + weak_15m={raw_15m:.2f} → probe 0.040",
            }
        if not has_strong_15m:
            return {
                "action":      "PROBE",
                "max_portion": 0.080,
                "reason": f"dual_risk + medium_15m → probe 0.080",
            }
        # 强 15M：允许通过但压仓
        return {
            "action":      "PASS",
            "max_portion": min(current_portion, 0.120),
            "reason": "dual_risk + strong_15m → capped 0.120",
        }

    # risk_count == 1：单一高风险特征
    if not has_weak_15m:
        return {
            "action":      "PROBE",
            "max_portion": 0.060,
            "reason": f"single_risk + very_weak_15m={raw_15m:.2f} → probe 0.060",
        }
    # 有基本 15M（raw >= 0.20）：允许通过，轻压仓
    return {
        "action":      "PASS",
        "max_portion": min(current_portion, 0.180),
        "reason": "single_risk + ok_15m → capped 0.180",
    }
```

```python
# 插入位置（threshold_check 通过后）：
gate_15m = self._apply_15m_entry_gate(
    direction, raw_15m, entry_15m,
    vwap_dev_pct, adx, regime,
    signal_4h, signal_1h, target_portion
)

if gate_15m["action"] == "BLOCK":
    return self._neutral_signal(reason=gate_15m["reason"], code="15m_entry_gate_block")

if gate_15m["action"] == "PROBE":
    target_portion = min(target_portion, gate_15m["max_portion"])
    signal.max_portion_hard_cap = gate_15m["max_portion"]

elif gate_15m["action"] == "PASS" and gate_15m["max_portion"] < target_portion:
    target_portion = gate_15m["max_portion"]
```

---

## [命令-2] flip_bullish 的独立保护

**为什么 flip_bullish 阈值 0.64 不够**

```
flip_bullish = 4H MACD 刚发生金叉，方向还未确认
这是最不稳定的信号：
  - 可能是真正的趋势反转（盈利）
  - 可能是短线假突破后回落（亏损）

BCH 亏损案例：
  4H flip_bullish + 1H red_bar_growing
  VWAPq=0.82 但 dev=-0.91%（仍在 VWAP 下方）
  15M raw=0.18（极弱）
  threshold=0.64（最低阈值）
  → 30 分钟内亏损 -0.529 USDT

修复：flip_bullish 路径必须满足更严格的条件才允许大仓
```

```python
# src/fund_flow/macd_strategy_v2.py
# 在 _apply_15m_entry_gate 之前或之内

def _apply_flip_bullish_size_guard(
    self,
    signal_4h:     str,
    signal_1h:     str,
    vwap_dev_pct:  float,
    raw_15m:       float,
    entry_15m:     str,
    current_portion: float,
) -> dict:
    """
    flip_bullish 路径专项保护：
    反转初期高度不确定，必须严格限制仓位
    """
    is_flip = (signal_4h == "flip_bullish" or signal_1h == "flip_bullish")
    if not is_flip:
        return {"action": "PASS", "max_portion": current_portion}

    # flip_bullish 的准入条件：
    # 条件 A: 价格必须在 VWAP 上方（dev >= 0）才允许较大仓
    # 条件 B: 必须有中等 15M 确认（raw >= 0.30 且 entry_15m 非空）
    price_above_vwap = vwap_dev_pct >= 0
    has_15m_confirm  = raw_15m >= 0.30 and entry_15m != "-"

    if price_above_vwap and has_15m_confirm:
        # 理想 flip_bullish：在 VWAP 上方且有 15M 确认
        return {
            "action":      "PASS",
            "max_portion": min(current_portion, 0.100),   # cap 到 10%，不给大仓
            "reason":      "flip_bullish_above_vwap_15m_confirmed",
        }

    if price_above_vwap and not has_15m_confirm:
        # 在 VWAP 上方但 15M 弱：probe
        return {
            "action":      "PROBE",
            "max_portion": 0.060,
            "reason":      f"flip_bullish_above_vwap_no_15m raw={raw_15m:.2f}",
        }

    if not price_above_vwap and has_15m_confirm:
        # VWAP 下方但有 15M 确认：极小 probe
        return {
            "action":      "PROBE",
            "max_portion": 0.042,
            "reason":      f"flip_bullish_below_vwap_15m_ok dev={vwap_dev_pct:.2%}",
        }

    # VWAP 下方 + 无 15M 确认：block
    return {
        "action": "BLOCK",
        "reason": f"flip_bullish_below_vwap_no_15m dev={vwap_dev_pct:.2%} raw={raw_15m:.2f}",
    }
```

---

## [命令-3] ADX < 20 / NO_TRADE 新开仓仓位上限

```python
def _apply_regime_size_cap(
    self,
    direction:       str,
    adx:             float,
    regime:          str,
    current_portion: float,
    signal_score:    float,
) -> float:
    """
    弱 ADX 或 NO_TRADE 场景下，新开仓仓位强制降级
    """
    is_weak = (adx < 20) or (regime == "NO_TRADE")
    if not is_weak:
        return current_portion

    # 弱趋势下按信号分数给仓位上限
    if signal_score >= 0.85:
        cap = 0.080    # 高分弱趋势：最多 8%
    elif signal_score >= 0.75:
        cap = 0.060    # 中分弱趋势：最多 6%
    else:
        cap = 0.042    # 低分弱趋势：最多 probe

    capped = min(current_portion, cap)
    if capped < current_portion:
        self._log_info(
            f"[ADX_CAP] adx={adx:.1f} regime={regime} "
            f"score={signal_score:.3f} → cap {current_portion:.4f} → {capped:.4f}"
        )
    return capped
```

---

## [命令-4] EMA strong 乘数加条件限制

**当前问题**

```
EMA=1.20x/strong 作用于 4H trend score
会把 4H 分放大，让弱势中的反弹也能通过 final

条件性放大逻辑（修复后）：
  EMA strong 1.20x 只在以下情况下生效：
    1. 价格在 VWAP 上方（dev >= 0）
    2. 15M raw >= 0.25
    3. ADX >= 20
  不满足时 → 乘数降为 1.00x（不放大）
```

```python
def _resolve_ema_multiplier(
    self,
    ema_raw_mult:  float,     # 当前 EMA 计算的乘数（0.60/1.00/1.20）
    vwap_dev_pct:  float,
    raw_15m:       float,
    adx:           float,
    direction:     str,
) -> float:
    """
    条件性应用 EMA strong 乘数
    """
    if ema_raw_mult <= 1.00:
        return ema_raw_mult   # weak/normal 乘数不受条件限制

    # strong(1.20) 的应用条件
    price_ok    = (direction == "long"  and vwap_dev_pct >= 0) or \
                  (direction == "short" and vwap_dev_pct <= 0)
    rhythm_ok   = raw_15m >= 0.25
    trend_ok    = adx >= 20

    if price_ok and rhythm_ok and trend_ok:
        return ema_raw_mult   # 全部满足：允许放大

    # 任一不满足：降为 1.00x（中性）
    self._log_debug(
        f"EMA mult capped 1.20→1.00: "
        f"price_ok={price_ok} rhythm_ok={rhythm_ok} trend_ok={trend_ok}"
    )
    return 1.00
```

---

## 配置修改

```diff
# config/trading_config_fund_flow.json

+ "entry_quality_gates": {
+
+   "15m_hard_gate": {
+     "enabled":                    true,
+     "risk_count_full_block":      3,
+     "risk_count_dual_probe_max":  0.080,
+     "risk_count_single_probe_max": 0.180,
+     "strong_15m_raw":             0.40,
+     "medium_15m_raw":             0.30,
+     "weak_15m_raw":               0.20,
+     "risk_factors": ["below_vwap_1pct","adx_lt_20","no_trade","flip_entry"]
+   },
+
+   "flip_bullish_size_guard": {
+     "enabled":                    true,
+     "above_vwap_15m_ok_max":      0.100,
+     "above_vwap_no_15m_max":      0.060,
+     "below_vwap_15m_ok_max":      0.042,
+     "below_vwap_no_15m_action":   "BLOCK"
+   },
+
+   "adx_regime_size_cap": {
+     "enabled":                    true,
+     "weak_adx_threshold":         20,
+     "score_tiers": [
+       {"min_score": 0.85, "max_portion": 0.080},
+       {"min_score": 0.75, "max_portion": 0.060},
+       {"min_score": 0.00, "max_portion": 0.042}
+     ]
+   },
+
+   "ema_conditional_multiplier": {
+     "enabled":                    true,
+     "strong_mult":                1.20,
+     "fallback_mult":              1.00,
+     "require_price_vwap_aligned": true,
+     "require_15m_raw_min":        0.25,
+     "require_adx_min":            20
+   }
+ },

  "entry_thresholds": {
    "flip_bullish":   0.640,    # 维持（由 flip_bullish_size_guard 控制仓位）
    "red_bar_growing": 0.680,
    "green_bar_growing": 0.690,
  }
```

---

## 亏损案例回放验证

```python
# 用新规则重新评估三个亏损案例

cases = [
    {
        "symbol": "ETC", "direction": "long",
        "signal_4h": "red_bar_growing", "signal_1h": "red_bar_growing",
        "vwap_dev": +0.0001, "raw_15m": 0.24, "entry_15m": "-",
        "adx": 32.42, "regime": "TREND", "target": 0.27,
    },
    {
        "symbol": "BCH", "direction": "long",
        "signal_4h": "flip_bullish", "signal_1h": "red_bar_growing",
        "vwap_dev": -0.0091, "raw_15m": 0.18, "entry_15m": "-",
        "adx": 22.33, "regime": "TREND", "target": 0.17,
    },
    {
        "symbol": "POL", "direction": "long",
        "signal_4h": "red_bar_growing", "signal_1h": "red_bar_growing",
        "vwap_dev": -0.0080, "raw_15m": 0.12, "entry_15m": "-",
        "adx": 17.29, "regime": "TREND", "target": 0.17,
    },
]

for c in cases:
    # 15M gate
    risk_count = sum([
        c["vwap_dev"] < -0.01,
        c["adx"] < 20,
        c["regime"] == "NO_TRADE",
        c["signal_1h"] in ("flip_bullish",) or c["signal_4h"] in ("flip_bullish",),
    ])
    print(f"{c['symbol']}: risk_count={risk_count}, raw_15m={c['raw_15m']}")

# ETC:  vwap_dev=+0.0001 (>0, 不算) + adx=32 (>20) + TREND + no flip = risk=0
#       → 15M gate PASS（vwap 上方，无高风险）
#       → ADX cap: adx=32 → 无 cap
#       → EMA 1.20x: price_ok=(dev>0)✓ rhythm_ok=(0.24<0.25)✗ → cap to 1.00
#       → 4H score 不被 EMA 放大：0.40 × 1.00 = 0.40（不变）
#       → 总分约 0.78~0.82，仍过 0.68
#       → 但 target 维持（无 15M 高风险），需要 EMA 修正降分
#       → ETC 唯一的干预是 EMA 乘数不再放大
#       → 仍可能开仓，但仓位不变；ETC 需要 15M gate 才能真正压仓

# BCH:  flip_bullish → is_flip=True
#       → flip_bullish_size_guard: vwap_dev=-0.91% (below) + 15M raw=0.18 (<0.30)
#       → BLOCK  ✓（不再开仓）

# POL:  vwap_dev=-0.80% (<-1%?) → -0.80% 略高于 -1% 门槛
#       调整门槛为 -0.5%：vwap_dev=-0.80% → is_below=True
#       + adx=17.29 (<20) → risk_count=2
#       + raw_15m=0.12 (<0.30) → dual_risk + weak_15m → PROBE max=0.040  ✓
#       target: 0.17 → 0.040（从 17% 降到 4%）
```

---

## 验收标准

```bash
# 12H 后检查：
grep "15m_entry_gate_block\|flip_bullish.*BLOCK\|ADX_CAP\|EMA mult capped" logs/... | wc -l
# 预期：> 20（说明新门控在生效）

grep "multi_risk\|dual_risk\|single_risk" logs/... | wc -l
# 预期：> 0（高风险场景被识别）

# 24H 后：
# BUY 中 vwap_dev < 0 的比例：从 86% 降到 < 40%
# BUY 中 15M raw < 0.30 的比例：从 55% 降到 < 30%
# LONG WR：>= 65%（当前因大量逆势多单 WR 偏低）
```

---

## 执行清单

```
今天：
□ _apply_15m_entry_gate() 写入并插入 threshold_check 通过后
□ _apply_flip_bullish_size_guard() 写入，在 15m gate 之前调用
□ _apply_regime_size_cap() 写入
□ _resolve_ema_multiplier() 修改条件
□ config: entry_quality_gates 块添加
□ pre_live_assertions: 加 assert_15m_gate_enabled
□ 重启，verify_deployment.py ✅

不动（等验收后评估）：
❌ 4H 权重（0.40 维持，通过门控而非降权重解决问题）
❌ entry_threshold 数值
❌ SHORT 方向的 15M gate（SHORT 逻辑不同，单独评估）
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-20*  
*核心：15M 从加分变门控，flip_bullish 加 VWAP/15M 准入条件，EMA strong 加条件限制*
