# VWAP 48H Review — 设计建议 + 伪代码 + DIFF

> 基于 2026-05-06/07 实盘切片。55.9% 胜率，`vwap_score=0.0` 全量进场，`vol_vwap_warn=True` bucket 表现最弱。

---

## 问题逐条回答

### Q1 · VWAP 应该是 hard floor、soft scaler 还是 score contributor？

**结论：三层架构，各司其职，顺序强制。**

```
Layer 1 (HARD GATE)   : vwap_quality_score >= min_vwap_score_for_entry
                         → 不达标 → 直接拒绝，不进入后续评分
Layer 2 (SCORE)       : weight_vwap × location_score 叠加进 composite_score
                         → 当前 weight_vwap=0.0，等 30D 消融验证后再开
Layer 3 (SOFT SCALER) : vol_vwap_warn_position_scale 调节仓位
                         → 当前 =0.0，仅在 RSI+MACD 联合质量极高时开放 probe
```

**原则**：gate > score > scaler，严格分层，不允许 scaler 绕过 gate。

---

### Q2 · `weight_vwap=0.0` 时保留 `min_vwap_score_for_entry` 是否自洽？

**不自洽。** 当前 `score = weight_vwap × location_score = 0.0`，
任何信号的 `vwap_score` 都是 0，gate 永远无法区分 location 好坏。

**修复**：拆分计算路径：

```
vwap_quality_score  ← 独立计算，不乘 weight_vwap，仅用于 gate
vwap_alpha_score    ← weight_vwap × location_score，用于 composite_score

gate 判断：vwap_quality_score >= floor   ← 用 quality，不用 alpha
```

---

### Q3 · 当前 floor 是否合理？

| Floor | 当前值 | 建议 | 理由 |
|---|---:|---:|---|
| `min_vwap_score_for_entry` (long) | `0.12` | `0.12` ✅ | 合理起点，待消融验证 |
| `short_min_vwap_score_for_entry` | `0.12` | `0.14` ↑ | short 做错方向损失更不对称 |
| `flip_bearish_short` | `0.25` | `0.25` ✅ | 反转空单风险最高，保持严格 |
| `flip_bullish_long` | `0.12` (disabled) | `0.15` | 翻多同样需要 location 确认 |

---

### Q4 · `vol_vwap_warn_position_scale` 维持 0.0 还是开 probe？

**维持 0.0，直到满足以下联合条件才开放 probe：**

```
probe_allowed = (
    vol_vwap_warn == True
    AND vwap_quality_score >= 0.12        # 本身过了 gate
    AND rsi_quality_score >= 0.75         # RSI 信号极佳
    AND macd_histogram_quality >= 0.80    # MACD 柱体质量极佳
    AND composite_score >= 0.82           # 整体得分非常高
)

if probe_allowed:
    position_scale = 0.10   # 最大 10%，只开仓探针，不是正常仓位
else:
    position_scale = 0.0    # 默认全拒
```

此 48H 切片的 `vol_vwap_warn=True` bucket 胜率 54.84%，PnL 仅 +0.48，
远低于 `vol_vwap_warn=False` 的 100%（虽然样本量只有 2）。
无统计支撑不应开放。

---

### Q5 · DCA/马丁应禁止在 `vwap_score < floor` 或 `vol_vwap_warn=True` 的原始仓位上触发？

**是，强制。** `PUMPUSDT` DCA 亏损 -0.635894，印证了原始信号质量差时 DCA 只是在亏损仓位上加注。

```
dca_allowed = (
    original_entry.vwap_quality_score >= min_vwap_score_for_entry
    AND original_entry.vol_vwap_warn != True
    AND original_entry.composite_score >= dca_min_entry_score
)

if not dca_allowed:
    BLOCK DCA
    log("DCA blocked: original entry quality insufficient", symbol, reason)
```

---

### Q6 · 当前公式是否过度奖励价格在 VWAP 之上（多头）/ 之下（空头），使 VWAP 变成追涨追跌过滤器？

**是的。** 当前 `long_dual_support`（价格同时高于 session 和 structural VWAP）
虽然确认了趋势方向，但也意味着价格已经远离 VWAP，进场时价值边际较差。

**重新分配权重**，区分"价值进场"和"动量延伸"：

```
原始权重分配（有问题）：
  session_support_quality    0.36   ← 价格高于 session VWAP 就加分，可能追涨
  structural_support_quality 0.26   ← 同上
  reclaim_quality            0.18
  dual_support_quality       0.12   ← 两者都高于 = 追涨最严重
  value_proximity_quality    0.08   ← 权重太低，价值进场没奖励

建议调整：
  reclaim_quality            0.30   ↑  优先奖励"刚回升穿越 VWAP"
  value_proximity_quality    0.20   ↑  价格贴近 VWAP 更有价值
  session_support_quality    0.26   ↓
  structural_support_quality 0.18   ↓
  dual_support_quality       0.06   ↓  大幅降低双轨支撑权重，减少追涨
  extension_penalty          0.15   ↑  强化延伸惩罚
```

---

### Q7 · 多头应该偏好 `long_reclaim_confirmed` 而非 `long_dual_support`？

**是。** Reclaim 是 VWAP 的核心价值捕获点：价格刚刚从 VWAP 以下穿回以上，
表示买方重新夺回定价权，且进场点在价值区附近。

`long_dual_support` 说明价格已在 VWAP 上方站稳，
适合趋势跟随系统，但对于寻找价值进场的策略是次优选择。

---

### Q8 · 空头应该偏好 `short_retest_reject` 而非 `short_dual_pressure`？

**是，且更强烈。** 
- `short_retest_reject`：价格反弹测试 VWAP 后被拒，是空头进场的高质量形态。
- `short_dual_pressure`：价格已同时低于 session 和 structural VWAP，
  意味着价格已经大幅下跌，空头进场可能正好踩在超卖反弹前。

空头比多头更容易遇到"做空破位耗竭"问题，`short_retest_reject` 应给最高权重。

---

### Q9 · `vwap <= 0` 时返回中性 `location_score=0.5` 是否应改为强制禁止进场？

**应该改为禁止，或至少触发降级。**

当前逻辑：`missing VWAP → score=0.5 × weight=0.0 = 0.0`。
表面上无害，实际上是"因为 weight=0.0 所以恰好通过"，一旦 weight 开启就立刻变成 0.5 虚假分数。

```
原规则：missing vwap → location_score=0.5 → score=0.0 (仅因weight=0)
问题：weight 一旦非零，0.5分变成无依据的alpha贡献

改为：
if vwap is None or vwap <= 0:
    vwap_quality_score = 0.0
    vwap_missing = True
    → 若 require_vwap_for_entry=True：直接 BLOCK
    → 若 require_vwap_for_entry=False：允许进场但记录 warn，不计 VWAP 分
```

---

### Q10 · 下一步 30D 消融网格

见文末消融矩阵。接受标准：
- 胜率相比无 VWAP gate baseline 提升，或 total return 提升且 MDD 不恶化超 2%
- Profit factor ≥ 1.3
- 交易数量不低于 400 笔/30D

---

## 伪代码 + DIFF

### DIFF 1 · 拆分 `vwap_quality_score` 与 `vwap_alpha_score`

```diff
# src/fund_flow/decision_engine.py

- def compute_vwap_score(price, vwap, structural_vwap, weight_vwap, ...):
-     """Returns weighted vwap score used for both gating and composite scoring."""
-     if not vwap or vwap <= 0:
-         location_score = 0.5
-         score = weight_vwap * 0.5
-         return score, "no_vwap"
-     location_score = _compute_location_score(price, vwap, structural_vwap, ...)
-     score = weight_vwap * location_score
-     return score, state

+ def compute_vwap_scores(price, vwap, structural_vwap, weight_vwap, ...):
+     """
+     Returns two independent scores:
+       vwap_quality_score : raw location quality [0, 1], used for gate
+       vwap_alpha_score   : weight_vwap * location_score, used in composite
+     Separating them allows weight_vwap=0 while still enforcing entry gate.
+     """
+     if not vwap or vwap <= 0:
+         vwap_quality_score = 0.0          # missing = no quality info
+         vwap_alpha_score   = 0.0
+         state              = "no_vwap"
+         vwap_missing       = True
+         return VwapScoreResult(
+             quality=vwap_quality_score,
+             alpha=vwap_alpha_score,
+             state=state,
+             missing=vwap_missing,
+         )
+
+     location_score     = _compute_location_score(price, vwap, structural_vwap, ...)
+     vwap_quality_score = location_score              # gate uses raw quality
+     vwap_alpha_score   = weight_vwap * location_score   # composite uses weighted
+     return VwapScoreResult(
+         quality=vwap_quality_score,
+         alpha=vwap_alpha_score,
+         state=state,
+         missing=False,
+     )
```

---

### DIFF 2 · Gate 判断使用 `quality` 而非 `alpha`

```diff
# src/fund_flow/decision_engine.py  — entry gate resolution

- vwap_score = compute_vwap_score(price, vwap, structural_vwap, weight_vwap)
- if vwap_score < min_vwap_score_for_entry:
-     return BLOCK, "vwap_gate"

+ vwap_result = compute_vwap_scores(price, vwap, structural_vwap, weight_vwap)
+
+ # Gate: always uses quality score regardless of weight_vwap setting
+ effective_floor = _resolve_vwap_floor(
+     signal_type=signal_type,
+     direction=direction,
+     min_vwap_score_for_entry=min_vwap_score_for_entry,
+     short_min_vwap_score_for_entry=short_min_vwap_score_for_entry,
+     flip_bearish_short_min_vwap_score_for_entry=flip_bearish_short_min_vwap_score_for_entry,
+     flip_bullish_min_vwap_score=flip_bullish_min_vwap_score,
+ )
+
+ if vwap_result.missing and require_vwap_for_entry:
+     return BLOCK, "vwap_missing_hard_block"
+
+ if vwap_result.quality < effective_floor:
+     return BLOCK, f"vwap_gate: quality={vwap_result.quality:.3f} < floor={effective_floor:.3f}"
+
+ # Composite: uses alpha score (zero when weight_vwap=0.0)
+ composite_score += vwap_result.alpha
```

---

### DIFF 3 · `_compute_location_score` 权重重平衡（多头）

```diff
# src/fund_flow/decision_engine.py  — long location score

  def _compute_long_location_score(
      price, session_vwap, structural_vwap,
      tolerance, warning, hard_block,
      long_reclaim_confirmed, session_above, structure_above
  ):
      session_deviation    = (price - session_vwap) / session_vwap
      structural_deviation = (price - structural_vwap) / structural_vwap

      session_support_quality    = clamp((session_deviation + tolerance) / (warning + tolerance), 0, 1)
      structural_support_quality = clamp((structural_deviation + tolerance) / (warning + tolerance), 0, 1)
      extension_penalty          = clamp(max(0, session_deviation - warning) / (hard_block - warning), 0, 1)
      reclaim_quality            = 1 if long_reclaim_confirmed else 0
      dual_support_quality       = 1 if (session_above and structure_above) else 0
      value_proximity_quality    = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

-     location_score = clamp(
-         0.36 * session_support_quality
-       + 0.26 * structural_support_quality
-       + 0.18 * reclaim_quality
-       + 0.12 * dual_support_quality
-       + 0.08 * value_proximity_quality
-       - 0.12 * extension_penalty,
-       0, 1
-     )

+     # Rebalanced: prioritise reclaim + value proximity, reduce dual_support weight
+     # to avoid rewarding already-extended moves above both VWAPs
+     location_score = clamp(
+         0.30 * reclaim_quality               # ↑ from 0.18: key entry-quality signal
+       + 0.26 * session_support_quality       # unchanged
+       + 0.20 * value_proximity_quality       # ↑ from 0.08: reward nearness to value
+       + 0.18 * structural_support_quality    # ↓ from 0.26
+       + 0.06 * dual_support_quality          # ↓ from 0.12: penalise extended entry
+       - 0.15 * extension_penalty,            # ↑ from 0.12: stronger anti-chase
+       0, 1
+     )

      return location_score, state
```

---

### DIFF 4 · 空头权重重平衡

```diff
# src/fund_flow/decision_engine.py  — short location score

  def _compute_short_location_score(
      price, session_vwap, structural_vwap,
      tolerance, warning, hard_block,
      short_retest_reject, session_below, structure_below
  ):
      session_deviation    = (price - session_vwap) / session_vwap
      structural_deviation = (price - structural_vwap) / structural_vwap

      session_pressure_quality    = clamp((-session_deviation + tolerance) / (warning + tolerance), 0, 1)
      structural_pressure_quality = clamp((-structural_deviation + tolerance) / (warning + tolerance), 0, 1)
      extension_penalty           = clamp(max(0, -session_deviation - warning) / (hard_block - warning), 0, 1)
      retest_quality              = 1 if short_retest_reject else 0
      dual_pressure_quality       = 1 if (session_below and structure_below) else 0
      value_proximity_quality     = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

-     location_score = clamp(
-         0.36 * session_pressure_quality
-       + 0.26 * structural_pressure_quality
-       + 0.18 * retest_quality
-       + 0.12 * dual_pressure_quality
-       + 0.08 * value_proximity_quality
-       - 0.12 * extension_penalty,
-       0, 1
-     )

+     # Rebalanced for shorts: retest_reject is far superior to dual_pressure
+     # dual_pressure often means breakdown exhaustion = bad short entry
+     location_score = clamp(
+         0.35 * retest_quality               # ↑ from 0.18: best short entry pattern
+       + 0.25 * value_proximity_quality      # ↑ from 0.08: price near VWAP = better fill
+       + 0.22 * session_pressure_quality     # ↓ from 0.36
+       + 0.14 * structural_pressure_quality  # ↓ from 0.26
+       + 0.04 * dual_pressure_quality        # ↓ from 0.12: strong penalty for breakdown chasing
+       - 0.18 * extension_penalty,           # ↑ from 0.12: shorts must not chase exhaustion
+       0, 1
+     )

      return location_score, state
```

---

### DIFF 5 · `vol_vwap_warn` probe 条件

```diff
# src/fund_flow/decision_engine.py  — position sizing

- if vol_vwap_warn:
-     position_scale = vol_vwap_warn_position_scale   # was 0.50, now 0.0

+ if vol_vwap_warn:
+     # Probe: only open tiny position if signal quality is exceptional across ALL dimensions
+     probe_eligible = (
+         vwap_result.quality >= vol_vwap_warn_min_vwap_score   # 0.12
+         and rsi_quality_score >= 0.75
+         and macd_histogram_quality >= 0.80
+         and composite_score >= 0.82
+     )
+     if probe_eligible and vol_vwap_warn_position_scale > 0:
+         position_scale = vol_vwap_warn_position_scale   # max 0.10 (10% of normal)
+         log_warn("vol_vwap_warn probe entry", symbol, composite_score)
+     else:
+         return BLOCK, "vol_vwap_warn: quality insufficient for probe"
```

---

### DIFF 6 · DCA/马丁 gate

```diff
# src/fund_flow/macd_strategy_v2.py  — DCA trigger

  def should_trigger_dca(position, market_state, config):
-     # Original: DCA triggers on price drop past threshold, no entry quality check
-     if price_drawdown >= dca_trigger_pct:
-         return True, "dca_drawdown_trigger"

+     # New: DCA inherits original entry quality constraints
+     original_entry = position.original_entry_metadata
+
+     dca_quality_gate_pass = (
+         original_entry is not None
+         and original_entry.get("vwap_quality_score", 0.0)
+             >= config.min_vwap_score_for_entry
+         and not original_entry.get("vol_vwap_warn", True)
+         and original_entry.get("composite_score", 0.0)
+             >= config.dca_min_original_composite_score   # suggest 0.70
+     )
+
+     if not dca_quality_gate_pass:
+         log_block(
+             "DCA blocked: original entry below VWAP quality threshold",
+             symbol=position.symbol,
+             original_vwap_quality=original_entry.get("vwap_quality_score"),
+             original_vol_vwap_warn=original_entry.get("vol_vwap_warn"),
+         )
+         return False, "dca_blocked_original_entry_quality"
+
+     if price_drawdown >= dca_trigger_pct:
+         return True, "dca_drawdown_trigger"
+
      return False, "no_trigger"
```

---

### DIFF 7 · `missing VWAP` 处理

```diff
# src/fund_flow/decision_engine.py  — vwap fetch + fallback

  vwap = tf_1h.get("vwap")
  structural_vwap = (
      tf_1h.get("structural_vwap")
      or tf_1h.get("anchored_vwap")
      or tf_1h.get("rolling_vwap")
  )

- if vwap is None or vwap <= 0:
-     location_score = 0.5          # neutral fallback — misleading when weight > 0
-     score = weight_vwap * 0.5
-     state = "no_vwap"
-     return score, state

+ if vwap is None or vwap <= 0:
+     vwap_missing = True
+     vwap_quality_score = 0.0      # no info = no quality score
+     vwap_alpha_score   = 0.0
+     state              = "no_vwap"
+
+     if config.require_vwap_for_entry:
+         # Hard block: missing VWAP means we cannot evaluate location
+         return VwapScoreResult(quality=0.0, alpha=0.0, state=state, missing=True,
+                                veto=VWAP_MISSING_HARD_BLOCK)
+     else:
+         # Soft warn: allow but do not score
+         log_warn("vwap_missing: proceeding without VWAP quality score", symbol)
+         return VwapScoreResult(quality=0.0, alpha=0.0, state=state, missing=True,
+                                veto=None)
```

---

### DIFF 8 · Config `trading_config_fund_flow.json`

```diff
  "scoring_weights": {
-   "weight_vwap": 0.0
+   "weight_vwap": 0.0,              // unchanged: stay at 0 until 30D ablation done
+   "weight_vwap_pending_ablation": 0.05  // candidate once ablation validates
  },

  "entry_filters": {
    "enable_vwap_flip_exemption": true,
    "preflip_trial_min_vwap_score": 0.0,
    "trial_short_below_structure_promotion_min_vwap_score": 0.0,
-   "short_min_vwap_score_for_entry": 0.12,
+   "short_min_vwap_score_for_entry": 0.14,         // ↑ shorts more asymmetric
-   "flip_bearish_short_min_vwap_score_for_entry": 0.25,
+   "flip_bearish_short_min_vwap_score_for_entry": 0.25,  // unchanged ✓
    "stable_bear_continuation_min_vwap_score": 0.0,
    "stable_bull_continuation_min_vwap_score": 0.0,
-   "flip_bullish_min_vwap_score": 0.0,
+   "flip_bullish_min_vwap_score": 0.15,            // was disabled, now gate when re-enabled
    "flip_bearish_retest_reject_min_vwap_score": 0.25,
    "vol_vwap_warn_min_score_vol": 0.05,
    "vol_vwap_warn_min_vwap_score": 0.12,
-   "min_vwap_score_for_entry": 0.12
+   "min_vwap_score_for_entry": 0.12,               // unchanged ✓
+   "require_vwap_for_entry": true,                 // NEW: missing vwap = hard block
+   "dca_min_original_composite_score": 0.70        // NEW: DCA gate on original entry
  },

  "position_management": {
-   "vol_vwap_warn_position_scale": 0.0
+   "vol_vwap_warn_position_scale": 0.0,            // unchanged ✓
+   "vol_vwap_warn_probe_scale": 0.10,              // NEW: probe-only scale, guarded by conditions
+   "vol_vwap_warn_probe_rsi_min": 0.75,            // NEW
+   "vol_vwap_warn_probe_macd_min": 0.80,           // NEW
+   "vol_vwap_warn_probe_composite_min": 0.82       // NEW
  }
```

---

## 完整伪代码：重构后的 VWAP 评分主路径

```python
# ============================================================
# src/fund_flow/decision_engine.py
# VWAP scoring — refactored version
# ============================================================

from dataclasses import dataclass
from typing import Optional

VWAP_HARD_BLOCK         = "vwap_extension_hard_block"
VWAP_MISSING_HARD_BLOCK = "vwap_missing_hard_block"
VWAP_GATE_BLOCK         = "vwap_quality_gate_block"


@dataclass
class VwapScoreResult:
    quality : float           # raw location quality [0, 1], used for gate
    alpha   : float           # weighted alpha contribution, used in composite
    state   : str             # descriptive state label
    missing : bool            # True if vwap data was absent
    veto    : Optional[str]   # BLOCK reason if entry must be rejected


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


# ── 1. Resolve VWAP entry floor ────────────────────────────────────────────────

def resolve_vwap_floor(
    signal_type: str,
    direction: str,
    min_vwap_score_for_entry: float,
    short_min_vwap_score_for_entry: float,
    flip_bearish_short_min_vwap_score_for_entry: float,
    flip_bullish_min_vwap_score: float,
) -> float:
    """
    Returns the effective minimum vwap_quality_score required to pass the gate.
    Uses quality score (not alpha score) for the comparison.
    """
    if direction == "long":
        if signal_type == "flip_bullish":
            floor = max(min_vwap_score_for_entry, flip_bullish_min_vwap_score)
        else:
            floor = min_vwap_score_for_entry

    elif direction == "short":
        short_floor = max(min_vwap_score_for_entry, short_min_vwap_score_for_entry)
        if signal_type == "flip_bearish":
            floor = max(short_floor, flip_bearish_short_min_vwap_score_for_entry)
        else:
            floor = short_floor

    else:
        floor = min_vwap_score_for_entry   # fallback

    return floor


# ── 2. Compute location score — long ──────────────────────────────────────────

def compute_long_location_score(
    price: float,
    session_vwap: float,
    structural_vwap: Optional[float],
    tolerance: float,
    warning: float,
    hard_block: float,
) -> tuple[float, str]:
    """
    Returns (location_score [0,1], state_label).
    Rebalanced weights: reclaim > value_proximity >> dual_support.
    Dual_support weight reduced to discourage chasing extended moves.
    """
    session_deviation = (price - session_vwap) / session_vwap

    # Hard block: price extended too far above VWAP — do not chase
    if session_deviation > hard_block:
        return 0.0, "long_extension_hard_block"

    # Extension penalty: continuous cost for above-warning deviation
    extension_penalty = clamp(
        max(0, session_deviation - warning) / (hard_block - warning), 0, 1
    )

    # Session-VWAP support quality
    session_support_quality = clamp(
        (session_deviation + tolerance) / (warning + tolerance), 0, 1
    )

    # Value proximity: closer to VWAP = better entry value
    value_proximity_quality = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

    # Structural VWAP (optional)
    if structural_vwap and structural_vwap > 0:
        structural_deviation = (price - structural_vwap) / structural_vwap
        structural_support_quality = clamp(
            (structural_deviation + tolerance) / (warning + tolerance), 0, 1
        )

        session_above   = price > session_vwap
        structure_above = price > structural_vwap

        # Reclaim: price just crossed back above session VWAP
        # Heuristic: session_deviation ∈ [-tolerance, +warning]
        long_reclaim_confirmed = (
            session_above
            and abs(session_deviation) <= warning
            and not structure_above   # ideally reclaiming from below structure too
            or (
                session_above
                and session_deviation <= warning * 0.5   # tight range = fresh reclaim
            )
        )

        dual_support_quality = 1 if (session_above and structure_above) else 0
        reclaim_quality      = 1 if long_reclaim_confirmed else 0

        # ── Rebalanced weights ──────────────────────────────────────
        # Old: session=0.36, structural=0.26, reclaim=0.18, dual=0.12, prox=0.08
        # New: reclaim=0.30, session=0.26,   prox=0.20, structural=0.18, dual=0.06
        location_score = clamp(
            0.30 * reclaim_quality
          + 0.26 * session_support_quality
          + 0.20 * value_proximity_quality
          + 0.18 * structural_support_quality
          + 0.06 * dual_support_quality
          - 0.15 * extension_penalty,
          0, 1
        )

        if long_reclaim_confirmed:
            state = "long_reclaim_confirmed"
        elif session_above and structure_above:
            state = "long_dual_support"
        elif session_above:
            state = "long_above_session_below_structure"
        elif structure_above:
            state = "long_above_structure_wait_reclaim"
        else:
            state = "long_below_both"

    else:
        # Fallback: session VWAP only
        structural_support_quality = 0.0
        dual_support_quality       = 0.0
        reclaim_quality            = 0.0

        location_score = clamp(
            0.30 * reclaim_quality
          + 0.26 * session_support_quality
          + 0.20 * value_proximity_quality
          + 0.18 * structural_support_quality
          + 0.06 * dual_support_quality
          - 0.15 * extension_penalty,
          0, 1
        )
        state = "long_session_vwap_only"

    return location_score, state


# ── 3. Compute location score — short ─────────────────────────────────────────

def compute_short_location_score(
    price: float,
    session_vwap: float,
    structural_vwap: Optional[float],
    tolerance: float,
    warning: float,
    hard_block: float,
) -> tuple[float, str]:
    """
    Returns (location_score [0,1], state_label).
    Rebalanced weights: retest_reject >> value_proximity > session_pressure >> dual_pressure.
    dual_pressure weight heavily reduced: it rewards breakdown exhaustion.
    """
    session_deviation = (price - session_vwap) / session_vwap

    # Hard block: price extended too far below VWAP — shorting exhausted move
    if -session_deviation > hard_block:
        return 0.0, "short_extension_hard_block"

    # Extension penalty: continuous cost for over-extended short entry
    extension_penalty = clamp(
        max(0, -session_deviation - warning) / (hard_block - warning), 0, 1
    )

    # Session pressure quality: how far below VWAP
    session_pressure_quality = clamp(
        (-session_deviation + tolerance) / (warning + tolerance), 0, 1
    )

    # Value proximity for shorts: price near VWAP (from below) = better fill
    value_proximity_quality = 1 - clamp(abs(session_deviation) / hard_block, 0, 1)

    if structural_vwap and structural_vwap > 0:
        structural_deviation = (price - structural_vwap) / structural_vwap
        structural_pressure_quality = clamp(
            (-structural_deviation + tolerance) / (warning + tolerance), 0, 1
        )

        session_below   = price < session_vwap
        structure_below = price < structural_vwap

        # Retest reject: price rallied back to VWAP, then was rejected
        # Heuristic: price near VWAP from below but failing to break through
        short_retest_reject = (
            session_below
            and abs(session_deviation) <= warning   # price tested VWAP
            and -session_deviation <= tolerance * 3  # price is very close to VWAP from below
        )

        dual_pressure_quality = 1 if (session_below and structure_below) else 0
        retest_quality        = 1 if short_retest_reject else 0

        # ── Rebalanced weights ──────────────────────────────────────
        # Old: session=0.36, structural=0.26, retest=0.18, dual=0.12, prox=0.08
        # New: retest=0.35, prox=0.25, session=0.22, structural=0.14, dual=0.04
        location_score = clamp(
            0.35 * retest_quality
          + 0.25 * value_proximity_quality
          + 0.22 * session_pressure_quality
          + 0.14 * structural_pressure_quality
          + 0.04 * dual_pressure_quality
          - 0.18 * extension_penalty,           # stronger anti-breakdown-chasing
          0, 1
        )

        if short_retest_reject:
            state = "short_retest_reject"
        elif session_below and structure_below:
            state = "short_dual_pressure"
        elif session_below:
            state = "short_below_session_above_structure"
        elif structure_below:
            state = "short_under_structure_wait_reject"
        else:
            state = "short_above_both"

    else:
        # Fallback: session VWAP only
        structural_pressure_quality = 0.0
        dual_pressure_quality       = 0.0
        retest_quality              = 0.0

        location_score = clamp(
            0.35 * retest_quality
          + 0.25 * value_proximity_quality
          + 0.22 * session_pressure_quality
          + 0.14 * structural_pressure_quality
          + 0.04 * dual_pressure_quality
          - 0.18 * extension_penalty,
          0, 1
        )
        state = "short_session_vwap_only"

    return location_score, state


# ── 4. Main entry point ────────────────────────────────────────────────────────

def compute_vwap_scores(
    price: float,
    tf_1h: dict,
    direction: str,
    signal_type: str,
    weight_vwap: float,
    vwap_retest_tolerance: float,
    vwap_deviation_warning: float,
    vwap_deviation_hard_block: float,
    require_vwap_for_entry: bool,
    config: dict,
) -> VwapScoreResult:
    """
    Main VWAP scoring function.
    Returns VwapScoreResult with quality, alpha, state, missing, veto.
    """
    # ── 4a. Extract VWAP data ────────────────────────────────────────
    session_vwap = tf_1h.get("vwap")
    structural_vwap = (
        tf_1h.get("structural_vwap")
        or tf_1h.get("anchored_vwap")
        or tf_1h.get("rolling_vwap")
    )

    # ── 4b. Missing VWAP guard ───────────────────────────────────────
    if not session_vwap or session_vwap <= 0:
        if require_vwap_for_entry:
            return VwapScoreResult(
                quality=0.0, alpha=0.0,
                state="no_vwap", missing=True,
                veto=VWAP_MISSING_HARD_BLOCK,
            )
        else:
            # Warn but allow; score contributes nothing
            return VwapScoreResult(
                quality=0.0, alpha=0.0,
                state="no_vwap", missing=True,
                veto=None,
            )

    # ── 4c. Tolerance / warning / hard_block resolution ─────────────
    tolerance  = vwap_retest_tolerance
    warning    = max(vwap_deviation_warning,   tolerance * 2)
    hard_block = max(vwap_deviation_hard_block, warning + 1e-6)

    # ── 4d. Direction-specific location score ───────────────────────
    if direction == "long":
        location_score, state = compute_long_location_score(
            price=price,
            session_vwap=session_vwap,
            structural_vwap=structural_vwap,
            tolerance=tolerance,
            warning=warning,
            hard_block=hard_block,
        )
    elif direction == "short":
        location_score, state = compute_short_location_score(
            price=price,
            session_vwap=session_vwap,
            structural_vwap=structural_vwap,
            tolerance=tolerance,
            warning=warning,
            hard_block=hard_block,
        )
    else:
        location_score = 0.5
        state          = "unknown_direction"

    # ── 4e. Hard block check (extension veto) ───────────────────────
    veto = None
    if location_score == 0.0 and "hard_block" in state:
        veto = VWAP_HARD_BLOCK

    # ── 4f. Separate quality vs alpha ───────────────────────────────
    vwap_quality_score = location_score              # gate uses this
    vwap_alpha_score   = weight_vwap * location_score   # composite uses this

    return VwapScoreResult(
        quality=vwap_quality_score,
        alpha=vwap_alpha_score,
        state=state,
        missing=False,
        veto=veto,
    )


# ── 5. Entry gate resolver ─────────────────────────────────────────────────────

def apply_vwap_entry_gate(
    vwap_result: VwapScoreResult,
    direction: str,
    signal_type: str,
    config: dict,
) -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str).
    Gate always uses vwap_result.quality, not .alpha.
    """
    # Hard veto (extension or missing)
    if vwap_result.veto:
        return False, vwap_result.veto

    # Resolve effective floor
    floor = resolve_vwap_floor(
        signal_type=signal_type,
        direction=direction,
        min_vwap_score_for_entry=config["min_vwap_score_for_entry"],
        short_min_vwap_score_for_entry=config["short_min_vwap_score_for_entry"],
        flip_bearish_short_min_vwap_score_for_entry=config[
            "flip_bearish_short_min_vwap_score_for_entry"
        ],
        flip_bullish_min_vwap_score=config["flip_bullish_min_vwap_score"],
    )

    if vwap_result.quality < floor:
        return False, (
            f"vwap_gate: quality={vwap_result.quality:.4f} < floor={floor:.4f} "
            f"state={vwap_result.state}"
        )

    return True, "vwap_gate_pass"


# ── 6. DCA quality gate ────────────────────────────────────────────────────────

def dca_vwap_gate(position, config: dict) -> tuple[bool, str]:
    """
    Prevents DCA on positions where the original entry had poor VWAP quality.
    """
    meta = getattr(position, "original_entry_metadata", None)
    if meta is None:
        return False, "dca_blocked: no original entry metadata"

    original_vwap_quality = meta.get("vwap_quality_score", 0.0)
    original_vol_warn     = meta.get("vol_vwap_warn", True)  # default conservatively to True
    original_composite    = meta.get("composite_score", 0.0)

    floor               = config["min_vwap_score_for_entry"]
    dca_composite_floor = config.get("dca_min_original_composite_score", 0.70)

    if original_vwap_quality < floor:
        return False, (
            f"dca_blocked: original vwap_quality={original_vwap_quality:.3f} < {floor}"
        )
    if original_vol_warn:
        return False, "dca_blocked: original entry had vol_vwap_warn=True"
    if original_composite < dca_composite_floor:
        return False, (
            f"dca_blocked: original composite={original_composite:.3f} < {dca_composite_floor}"
        )

    return True, "dca_gate_pass"


# ── 7. vol_vwap_warn probe sizing ─────────────────────────────────────────────

def resolve_vol_vwap_warn_scale(
    vol_vwap_warn: bool,
    vwap_result: VwapScoreResult,
    rsi_quality_score: float,
    macd_histogram_quality: float,
    composite_score: float,
    config: dict,
) -> float:
    """
    Returns position_scale factor when vol_vwap_warn is True.
    Returns 0.0 unless all multi-signal conditions are met.
    Probe scale is intentionally tiny (≤0.10) to limit exposure.
    """
    if not vol_vwap_warn:
        return 1.0   # normal sizing

    probe_scale = config.get("vol_vwap_warn_probe_scale", 0.0)
    if probe_scale <= 0:
        return 0.0   # feature disabled

    probe_eligible = (
        vwap_result.quality >= config.get("vol_vwap_warn_min_vwap_score", 0.12)
        and rsi_quality_score   >= config.get("vol_vwap_warn_probe_rsi_min", 0.75)
        and macd_histogram_quality >= config.get("vol_vwap_warn_probe_macd_min", 0.80)
        and composite_score     >= config.get("vol_vwap_warn_probe_composite_min", 0.82)
    )

    if probe_eligible:
        return probe_scale   # 0.10 = 10% of normal position
    return 0.0   # block entirely
```

---

## 30D 消融矩阵

| Variant | `weight_vwap` | `min_vwap_score` | `short_min_vwap_score` | `flip_bearish_floor` | `probe_scale` | 预期目标 |
|---|---:|---:|---:|---:|---:|---|
| **Current gate** | `0.0` | `0.12` | `0.14` | `0.25` | `0.0` | 基准，验证 floor 收益 |
| **Gate light** | `0.0` | `0.08` | `0.10` | `0.20` | `0.0` | 测试过松时胜率下降幅度 |
| **Score only** | `0.05` | `0.0` | `0.0` | `0.0` | `0.0` | 纯 alpha 贡献，无 gate |
| **Score + gate** | `0.05` | `0.08` | `0.10` | `0.20` | `0.0` | 两者结合，预期最优 |
| **Probe weak** | `0.0` | `0.12` | `0.14` | `0.25` | `0.10` | 验证 probe 是否有增益 |
| **Reclaim-only** | `0.05` | `0.12` | `0.14` | `0.25` | `0.0` | 仅 `reclaim_confirmed` 才达到高分 |

### 接受标准（所有变体必须满足）

```
win_rate        >= 75%                     （目标）
profit_factor   >= 1.3
max_drawdown    <= baseline_mdd + 2%       （MDD 不能恶化超 2%）
trade_count     >= 400 笔 / 30D            （信号不能稀疏化）
total_return    >= baseline_return - 5%    （不能以牺牲收益换 win rate）
```

---

## 优先级 Checklist

```
[ ] DIFF 1: 拆分 vwap_quality_score / vwap_alpha_score
[ ] DIFF 2: gate 改用 quality 字段
[ ] DIFF 5: DCA gate 实现
[ ] DIFF 6: missing VWAP hard block 启用（require_vwap_for_entry=true）
[ ] Config: short_min_vwap_score_for_entry 0.12 → 0.14
[ ] Config: require_vwap_for_entry=true 新增
[ ] Config: dca_min_original_composite_score=0.70 新增
[ ] 单测: vwap_quality_score 在 weight_vwap=0 时不为 0
[ ] 单测: DCA 在 vol_vwap_warn=True 原始进场上被 block
[ ] 30D 消融: Current gate variant 先跑，拿基准数据
```

---

*本文档基于 48H 实盘切片 (55.9% 胜率, 34 matched entries)。
所有权重调整和 floor 变更需经 30D 消融验证后才可上线。*
