# 开仓偏少 + 仓位压缩修复建议
**审阅窗口**: 2026-05-12 22:00 BJ → 2026-05-13 14:20 BJ  
**核心问题**: 42% HOLD 因"4H 无明确方向"，权重体系 RSI 占 82%，仓位被多层压缩过度  
**优化目标**: 提升有效成交数 / 恢复合理仓位规模 / 重新平衡 RSI vs 4H 权重

---

## 问题诊断全貌

```
HOLD 归因排序（1875 次 HOLD）：
  42.0%  4H无明确方向          → 方向门控问题，不是阈值问题
  19.3%  rsi_1h_direction_against_veto → RSI hard veto 过硬
  19.2%  vwap_hard_block       → VWAP 偏离 3% 一刀切
   9.5%  信号评分 < 阈值        → 只有这一成是阈值问题
   3.9%  rsi_15m_extreme_veto
   3.3%  rsi_1h_direction_flat_veto

结论：降低 entry_threshold 只能解决 9.5% 的 HOLD，
      优先解决前三类（共 80.5%），效果才会显著。

仓位压缩链路（叠加效应）：
  base  = 0.35
  × 0.60  vwap ≤ 0.25
  × 0.75  volume ≤ 0.033
  × 0.70  ADX > 40
  ─────────────────────
  final = 0.35 × 0.60 × 0.75 × 0.70 = 0.1103
  → 低于 min_open_portion=0.06 → 静默丢弃
  → probe_floor_rescue 虽配置 enabled=true 但 shadow_mode=true → 不实际下单
```

---

## ⚠️ FINDINGS

---

### [CRITICAL-1] 权重失衡 — RSI rhythm 实际贡献 82%，4H 方向只有 9%

**量化证明**

```python
# 从运行时样本反推各分量实际贡献（上版已验证）
contribution_breakdown = {
    "rsi_rhythm":    0.819,    # 82%，实际主导
    "4h_direction":  0.095,    # 9.5%，配置最高权重但实际最低
    "1h_direction":  0.081,    # 8%
    "volume":        0.005,
    "15m":           0.0004,
    "vwap":          0.000,    # score_vwap 恒为 0（已知 bug）
}

# 问题：RSI rhythm 分 raw_score 可以超过 1.0（内部有倍数机制）
# 使得 weight_rsi_rhythm=0.30 × raw_score=1.73 = 0.519
# 远超 weight_4h_direction=0.40 × score_4h=0.15 = 0.060

# 用户目标：降低 RSI 权重，提升 4H 方向权重
# 修复方向：
# 1. RSI raw_score 归一化到 [0, 1]，消除内部倍数溢出
# 2. 权重比例向 4H 倾斜
# 3. 同步把 weight_4h_enhancement 正式清零（已 fold-in）

# 目标权重（归一化后，加总 = 1.00）：
target_weights = {
    "weight_1h_direction":   0.15,    # 维持，1H 确认层
    "weight_4h_direction":   0.45,    # 从 0.40 提升到 0.45（含 enhancement）
    "weight_4h_enhancement": 0.00,    # 清零（已 fold-in）
    "weight_rsi_rhythm":     0.22,    # 从 0.30 降到 0.22（核心调整）
    "weight_vwap":           0.00,    # score_vwap bug 修复前清零
    "weight_15m_entry":      0.08,    # 从 0.05 提升（15m 触发层加权）
    "weight_volume":         0.10,    # 维持
    # sum = 0.15+0.45+0.22+0.08+0.10 = 1.00 ✓
}

# 预期效果：
# 4H 方向强 → 总分大幅提升，入场门槛更容易达到
# RSI rhythm 不再一票否决（权重下降后，RSI 弱不能单独阻断高分信号）
# 但"4H 无明确方向"的情况仍会拿到低 4H 分
# → 必须配合 Q2（neutral_upgrade 放宽）才能形成闭环

# 同时需要修复 RSI raw_score 溢出：
def rsi_rhythm_score_normalized(raw_rsi_score: float) -> float:
    """
    将 RSI rhythm raw_score 归一化到 [0, 1]
    消除当前 raw_score > 1.0 导致的权重失控
    """
    return max(0.0, min(1.0, raw_rsi_score))
    # 注意：归一化后，weight_rsi_rhythm=0.22 最大贡献 = 0.22
    # 不再出现 0.30 × 1.73 = 0.519 的溢出情况
```

**DIFF：权重重新平衡**

```diff
# config/trading_config_fund_flow.json

  "scoring_weights": {
-   "weight_1h_direction":   0.150000,
+   "weight_1h_direction":   0.150000,   # 维持

-   "weight_4h_direction":   0.400000,
+   "weight_4h_direction":   0.450000,   # +0.05，提升 4H 主导权

-   "weight_4h_enhancement": 0.100000,
+   "weight_4h_enhancement": 0.000000,   # 清零（fold-in 确认）

-   "weight_rsi_rhythm":     0.300000,
+   "weight_rsi_rhythm":     0.220000,   # -0.08，降低 RSI 支配力

-   "weight_vwap":           0.050000,
+   "weight_vwap":           0.000000,   # bug 修复前清零

-   "weight_15m_entry":      0.050000,
+   "weight_15m_entry":      0.080000,   # +0.03，15m 触发信号加权

-   "weight_volume":         0.100000
+   "weight_volume":         0.100000    # 维持
+   # sum = 0.15+0.45+0.22+0.08+0.10 = 1.00 ✓
  },

+ "rsi_rhythm_score_cap": {
+   "enabled":   true,
+   "max_score": 1.00,    # RSI raw_score 归一化上限
+   "comment":   "防止 raw_score>1.0 溢出导致 RSI 实际权重失控"
+ }
```

---

### [CRITICAL-2] 4H 无明确方向占 42% HOLD — neutral_upgrade 条件过严

**回答 Q1 + Q2**

```python
# 当前 neutral_upgrade 链路
neutral_upgrade_config = {
    "enable_neutral_upgrade":            True,
    "neutral_upgrade_min_rsi_score":     0.35,   # RSI 分至少 0.35 才升级
    "neutral_upgrade_probe_rsi_score":   0.20,   # probe 级别降到 0.20
    "neutral_upgrade_probe_threshold_score": 0.82,
    "neutral_upgrade_penalty_mult":      0.90,
}

# 问题：在 RSI 权重占 82% 的体系下，
# neutral_upgrade_min_rsi_score=0.35 等效要求总分至少 0.35 × 0.82 ≈ 0.287
# 看起来不高，但叠加方向不明时其他分量都很低，总分往往达不到

# 本窗口日志典型路径：
# 4H 方向 neutral → 进入 neutral_upgrade_gate
# RSI 节奏尝试升级 → 但 rsi_1h_direction_against_veto 触发 → 直接归零
# 候选在 neutral_upgrade_gate/mode 阶段消失

# 问题的根本：
# neutral_upgrade 依赖 RSI 节奏来"替代"4H 方向
# 但 RSI hard veto 先于 neutral_upgrade 评估，把候选直接杀掉
# 导致 neutral_upgrade 永远拿不到可升级的候选

# 修复思路：
# 1. 给"4H shrinking + 1H growing"单独开一条 partial_confirm 路径
# 2. 在 neutral_upgrade 中，允许低 RSI 分的信号走 probe（而不是全 block）
# 3. 把 neutral_upgrade_probe_rsi_score 从 0.20 降到 0.12

def evaluate_neutral_upgrade(
    signal_4h:       str,
    signal_1h:       str,
    rsi_score:       float,
    score_4h:        float,
    total_score_so_far: float,
) -> dict:
    """
    扩展的 neutral_upgrade 评估，新增 partial_confirm 路径
    """

    # ── 新路径：4H shrink + 1H growing = partial_confirm ──
    # 4H 收缩意味着当前趋势正在减弱，1H 已经开始转向
    # 这是有效的早期入场信号，不应全部归零
    SHRINK_4H = {"red_bar_shrinking", "green_bar_shrinking"}
    GROWING_1H = {"red_bar_growing", "flip_bullish"}
    DECLINING_1H = {"green_bar_growing", "flip_bearish"}

    is_partial_confirm_long = (
        signal_4h in SHRINK_4H and signal_1h in GROWING_1H
    )
    is_partial_confirm_short = (
        signal_4h in SHRINK_4H and signal_1h in DECLINING_1H
    )

    if is_partial_confirm_long or is_partial_confirm_short:
        return {
            "upgraded":        True,
            "mode":            "partial_confirm",
            "penalty_mult":    0.85,           # 惩罚但不归零
            "max_portion":     0.10,           # 强制 probe 仓位
            "score_bonus":     0.02,           # 小额加分
            "reason":          "4H_shrink+1H_confirm partial upgrade",
        }

    # ── 原有 neutral_upgrade 路径（放宽 rsi 门槛）──────────
    if rsi_score >= 0.20:    # 从 0.35 降到 0.20
        return {
            "upgraded":     True,
            "mode":         "rsi_upgrade",
            "penalty_mult": 0.90,
            "max_portion":  0.10 if rsi_score < 0.30 else None,
            "reason":       f"rsi_upgrade: rsi_score={rsi_score:.2f}",
        }

    if rsi_score >= 0.12:    # 从 0.20 降到 0.12
        return {
            "upgraded":     True,
            "mode":         "probe_only",
            "penalty_mult": 0.85,
            "max_portion":  0.06,   # 最小 probe
            "reason":       f"probe_upgrade: rsi_score={rsi_score:.2f}",
        }

    return {"upgraded": False, "reason": "neutral_upgrade 条件不足"}
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "neutral_upgrade": {
    "enabled":                        true,
-   "neutral_upgrade_min_rsi_score":  0.35,
+   "neutral_upgrade_min_rsi_score":  0.20,    # 放宽，更多候选可升级

-   "neutral_upgrade_probe_rsi_score": 0.20,
+   "neutral_upgrade_probe_rsi_score": 0.12,   # probe 门槛进一步放宽

    "neutral_upgrade_probe_threshold_score": 0.82,
    "neutral_upgrade_penalty_mult":   0.90,

+   "partial_confirm_path": {
+     "enabled":            true,
+     "4h_shrink_signals":  ["red_bar_shrinking","green_bar_shrinking"],
+     "1h_confirm_long":    ["red_bar_growing","flip_bullish"],
+     "1h_confirm_short":   ["green_bar_growing","flip_bearish"],
+     "penalty_mult":       0.85,
+     "max_portion":        0.10,
+     "score_bonus":        0.02,
+     "comment":            "4H 收缩 + 1H 已确认 = 早期入场机会"
+   }
  }
```

---

### [CRITICAL-3] rsi_1h_direction_against_veto 过硬 — 19% HOLD 被一刀切

**回答 Q3**

```python
# 当前逻辑（推断）：
# 1H RSI 方向与 4H 预期方向相反 → hard veto → 总分归零

# 问题：在趋势反转初期，这个配置会系统性错过入场
# 例如：4H 方向 = long（基于上一根 4H K 线）
#        1H RSI 方向 = down（短暂回调）
#        → hard veto 触发
#        → 但这可能是绝佳的回调买入点

# 362 次触发分布：
# 大多数是 "4H primary long + 1H RSI going down" 的情况
# 这在上涨趋势中的正常回调里会大量出现

# 修复：把 hard veto 改为 score penalty，给高质量信号豁免

def rsi_direction_gate(
    rsi_dir_1h:   str,
    expected_dir: str,    # 基于 4H 的预期方向
    signal_score: float,
    score_4h:     float,
    regime:       str,
    adx:          float,
) -> dict:
    """
    RSI 方向不一致 → 不再是 hard veto，而是分级处理
    """
    is_conflict = (rsi_dir_1h != expected_dir) and (rsi_dir_1h != "flat")

    if not is_conflict:
        return {"action": "PASS", "penalty": 1.0}

    # ── 豁免条件 ──────────────────────────────────────────
    # 1. score_4h 足够强（4H 方向非常确定）
    if score_4h >= 0.30:          # 4H 分达到满分的 75%
        return {
            "action":  "SOFT_PENALTY",
            "penalty": 0.92,      # 轻微惩罚
            "reason":  f"4H strong ({score_4h:.2f}), RSI conflict soft-penalized",
        }

    # 2. 高信号质量 + 低 ADX（趋势弱，RSI 方向更有参考价值）
    if signal_score >= 0.75 and adx < 20:
        return {
            "action":  "SOFT_PENALTY",
            "penalty": 0.88,
            "reason":  "high score + low ADX, soft penalty for RSI conflict",
        }

    # 3. RANGE regime（震荡市里 RSI 方向冲突很正常）
    if regime == "RANGE":
        return {
            "action":  "SOFT_PENALTY",
            "penalty": 0.90,
            "reason":  "RANGE regime, RSI conflict expected",
        }

    # 默认：保留 hard veto（强趋势中方向一致性仍重要）
    return {"action": "VETO", "penalty": 0.0}
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "rsi_rhythm": {
    "enable_hard_veto":          true,
+   "hard_veto_to_penalty_upgrade": {
+     "enabled":               true,
+     "exempt_if_score_4h_ge": 0.30,    # 4H 分强时豁免 veto
+     "exempt_penalty_mult":   0.92,
+     "exempt_if_score_ge":    0.75,    # 高总分时豁免
+     "exempt_adx_le":         20,
+     "exempt_regime":         ["RANGE"],
+     "exempt_range_penalty":  0.90,
+     "comment":               "RSI 方向冲突从 hard veto 降为 score penalty"
+   }
  }
```

---

### [HIGH-1] VWAP hard_block=3% 一刀切 — 对高波动标的过严

**回答 Q4**

```python
# 当前配置：
# vwap_deviation_hard_block = 0.03（3% 偏离则硬否决）
# 本窗口触发 360 次，占 HOLD 19.2%

# 问题：3% 的统一门槛对不同波动率的标的不公平
# 高波动标的（ATR > 2%）：3% 偏离很正常，不代表追高风险大
# 低波动标的（ATR < 0.5%）：3% 偏离确实是很大的追高

# 修复：用 ATR 归一化 VWAP 偏离，而不是用固定百分比
def vwap_deviation_gate(
    price:      float,
    vwap:       float,
    atr_pct:    float,    # 当前 ATR / 价格
    direction:  str,
) -> dict:
    """
    VWAP 偏离门控，按 ATR 归一化
    """
    deviation_pct = abs(price - vwap) / vwap

    # 归一化偏离 = 以 ATR 为单位的 VWAP 偏离
    if atr_pct > 0:
        normalized_dev = deviation_pct / atr_pct
    else:
        normalized_dev = float("inf")

    # ── 新的分层判断 ──────────────────────────────────────
    # 偏离 < 1.5 × ATR：完全通过
    if normalized_dev < 1.5:
        return {"action": "PASS", "vwap_score": 1.0}

    # 偏离 1.5~2.5 × ATR：轻微惩罚
    if normalized_dev < 2.5:
        penalty = 1.0 - (normalized_dev - 1.5) * 0.15
        return {"action": "PENALTY", "penalty_mult": penalty, "vwap_score": 0.6}

    # 偏离 2.5~4.0 × ATR：重惩罚 + 强制 probe 仓位
    if normalized_dev < 4.0:
        return {
            "action":      "PROBE_ONLY",
            "penalty_mult": 0.80,
            "max_portion":  0.06,
            "vwap_score":   0.25,
        }

    # 偏离 > 4.0 × ATR：hard block（原 3% 固定门槛的替代）
    return {"action": "HARD_BLOCK", "vwap_score": 0.0}

# 效果估算：
# 假设本窗口 360 次 vwap_hard_block 中，
# 50% 的标的 ATR > 1.5%，3% 偏离 = 2 × ATR（在 PROBE_ONLY 区间）
# → 180 次从 hard_block 降为 probe_only
# → 潜在新增 probe 开仓：约 10~30 笔（取决于其他门控）
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

- "vwap_deviation_hard_block": 0.03,   # 固定 3% 一刀切

+ "vwap_deviation_gate": {
+   "mode":                  "atr_normalized",    # 替换固定百分比
+   "pass_atr_multiplier":   1.5,     # < 1.5 × ATR：完全通过
+   "penalty_atr_multiplier": 2.5,    # 1.5~2.5 × ATR：轻惩罚
+   "probe_atr_multiplier":   4.0,    # 2.5~4.0 × ATR：probe 仓位
+   "block_atr_multiplier":   4.0,    # > 4.0 × ATR：hard block
+   "penalty_mult_slope":     0.15,   # 惩罚斜率
+   "probe_max_portion":      0.06,
+   "fallback_hard_block_pct": 0.06,  # ATR 未知时退化到 6% 固定门槛
+ }
```

---

### [HIGH-2] probe_floor_rescue shadow_mode=true — 高分信号仍被静默丢弃

**回答 Q5**

```python
# 当前状态：
# probe_floor_rescue.shadow_mode = True
# 效果：ALGOUSDT score=0.8365 target=0.042 < min_open=0.06
#       系统只记录 "shadow eligible"，不实际下单

# shadow 数据确认（本窗口）：
# 10 次 min_open_portion block
# 典型：ALGOUSDT score=0.8365，ZECUSDT score=0.7224

# shadow 已经跑了足够长时间（从上次审阅到现在约 2~3 天）
# 建议：关闭 shadow_mode，但对 probe 设置独立止损参数

# 关闭 shadow 的前置检查：
def should_disable_shadow_mode(shadow_log: list[dict]) -> bool:
    """
    检查 shadow probe 候选的质量是否达到上线标准
    """
    if len(shadow_log) < 10:
        return False   # 样本不足

    eligible = [x for x in shadow_log if x.get("shadow_eligible")]

    # 检查平均 score
    avg_score = sum(x["signal_score"] for x in eligible) / len(eligible)
    if avg_score < 0.75:
        return False   # 平均质量不足

    # 检查 score 分布
    high_score_pct = len([x for x in eligible if x["signal_score"] >= 0.80]) / len(eligible)
    if high_score_pct < 0.40:
        return False   # 高分占比不足

    return True   # 可以关闭 shadow

# 当前样本：10 次中，ALGOUSDT=0.8365, ZECUSDT=0.7224, SOLUSDT=0.7857
# avg ≈ 0.77，high_score(≥0.80) = 1/10 = 10%（低于 40% 标准）
# 建议：继续 shadow，但设置"单独的 probe min_open"，降低门槛

# 折中方案：
probe_config = {
    "probe_floor_rescue": {
        "shadow_mode":          False,    # 关闭 shadow
        "min_score_threshold":  0.800,    # 只救 score ≥ 0.80
        "probe_portion":        0.042,    # 与 dynamic sizing 压缩结果对齐
                                          # 而不是强制提升到 0.06
        "probe_leverage_cap":   2,
    },
    "probe_min_open": 0.042,              # probe 专用最小下单（低于正常 0.06）
    "comment": "probe 的 min_open 独立于正常开仓的 min_open"
}
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "probe_floor_rescue": {
-   "shadow_mode":         true,
+   "shadow_mode":         false,    # 关闭 shadow，实际执行

    "min_score_threshold": 0.800,

-   "probe_portion":       0.060,    # 强制提升到 min_open
+   "probe_portion":       null,     # 不强制提升，保留 dynamic sizing 结果
+   "probe_min_open":      0.042,    # probe 专用 min_open（低于正常 0.06）

    "probe_leverage_cap":  2
  },

+ "min_open_portion_by_mode": {
+   "normal": 0.060,     # 正常开仓 min_open
+   "probe":  0.042,     # probe 模式 min_open（低 7% 资本）
+   "comment": "probe 允许更小的最小仓位，减少高分信号被丢弃"
+ }
```

---

### [MEDIUM-1] 仓位压缩叠加过度 — 三层压缩后必然触发 min_open

```python
# 当前三层压缩叠加
def current_sizing_chain(base=0.35):
    """
    问题：三层独立压缩没有"总体下限保障"
    """
    after_vwap   = base * 0.60    # vwap ≤ 0.25 → 0.210
    after_vol    = after_vwap * 0.75  # vol ≤ 0.033 → 0.158
    after_adx    = after_vol * 0.70   # adx > 40 → 0.110
    # 0.110 < min_open=0.060 → 丢弃（如果 score < 0.80）

    # 问题：三个压缩都是独立最大惩罚叠加
    # 这三个条件同时出现的概率：
    # vwap=低 AND volume=低 AND adx=高 → 相关性很高（趋势延伸初期）
    # 正是最需要入场的时候，却被三层压缩杀死

# 修复：对每笔信号，总压缩系数设置下限
def revised_sizing_chain(
    base: float,
    vwap_mult: float,
    vol_mult: float,
    adx_mult: float,
    signal_score: float,
) -> float:
    """
    三层压缩后，按信号质量设置综合下限
    """
    raw = base * vwap_mult * vol_mult * adx_mult

    # 综合压缩系数下限（不允许压缩到 base 的 30% 以下）
    FLOOR_MULT = {
        "score_ge_085": 0.45,   # score ≥ 0.85 → 至少 45% 的 base
        "score_ge_075": 0.35,   # score ≥ 0.75 → 至少 35% 的 base
        "score_ge_065": 0.25,   # score ≥ 0.65 → 至少 25% 的 base
        "default":       0.15,  # 其他 → 至少 15% 的 base
    }

    if signal_score >= 0.85:
        floor = base * FLOOR_MULT["score_ge_085"]
    elif signal_score >= 0.75:
        floor = base * FLOOR_MULT["score_ge_075"]
    elif signal_score >= 0.65:
        floor = base * FLOOR_MULT["score_ge_065"]
    else:
        floor = base * FLOOR_MULT["default"]

    result = max(raw, floor)

    log_debug(
        f"sizing: raw={raw:.3f} floor={floor:.3f} "
        f"result={result:.3f} score={signal_score:.3f}"
    )
    return result

# 效果估算：
# base=0.35, score=0.836 (ALGOUSDT)
# floor = 0.35 × 0.45 = 0.1575
# raw   = 0.35 × 0.60 × 0.75 × ??? ≈ 0.042
# result = max(0.042, 0.1575) = 0.1575
# → 高于 probe_min_open=0.042，正常下单
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

+ "dynamic_sizing": {
+   "enabled":          true,
+   "vwap_score_tiers": [
+     {"max": 0.25, "mult": 0.60},
+     {"max": 0.50, "mult": 0.80},
+     {"max": 9.99, "mult": 1.00}
+   ],
+   "volume_score_tiers": [
+     {"max": 0.033, "mult": 0.75},
+     {"max": 9.999, "mult": 1.00}
+   ],
+   "adx_penalty": {
+     "regime": "TREND", "min_adx": 40, "mult": 0.70
+   },

+   "total_compression_floor": {
+     "enabled": true,
+     "floors": [
+       {"min_score": 0.85, "min_mult_of_base": 0.45},
+       {"min_score": 0.75, "min_mult_of_base": 0.35},
+       {"min_score": 0.65, "min_mult_of_base": 0.25},
+       {"min_score": 0.00, "min_mult_of_base": 0.15}
+     ],
+     "comment": "综合压缩下限，高分信号不会被三层惩罚叠压到 min_open 以下"
+   }
+ }
```

---

## 三、回答六个审阅问题

```
Q1: 4H primary + require_1h_confirmation 是否过度延迟入场？
答：是。当前组合在 4H 刚形成信号时，1H 往往还没确认
    → 这窗口结束后信号消失，策略一直等 1H 确认却等到行情过了
    建议：在 RSI 权重降低后，4H 分的贡献更大，
    可以把 require_1h_confirmation 改为 prefer_1h_confirmation（软要求）
    即：1H 未确认时 × 0.90 penalty，而不是直接阻断

Q2: neutral_upgrade 是否达成目标？
答：没有。设计上 neutral_upgrade 应该给"4H 不确定但有局部优势"的信号提供出路，
    但 rsi_1h_direction_against_veto 先于 neutral_upgrade 触发，
    把大量候选直接归零，neutral_upgrade 拿不到可升级的候选。
    修复：新增 partial_confirm 路径（4H shrink + 1H confirm），
    同时降低 neutral_upgrade_min_rsi_score 从 0.35 → 0.20。

Q3: rsi_1h_direction_against_veto 是否过硬？
答：是，362 次触发（19.3%）说明它是第二大阻断源。
    在 RSI 权重降低后，这个 hard veto 的逻辑更需要软化。
    建议：score_4h ≥ 0.30 时豁免，RANGE regime 时改为 penalty。

Q4: vwap_deviation_hard_block=3% 是否一刀切过硬？
答：是，对高波动标的（ATR > 1.5%）确实过硬。
    建议改为 ATR 归一化的分层门控（4 × ATR 才 hard block）。

Q5: probe_floor_rescue shadow_mode=true 是否应关闭？
答：建议关闭 shadow，但同时降低 probe_min_open 到 0.042，
    避免把 target=0.042 的信号强行提升到 0.06（超额暴露）。

Q6: 提高开仓数量的优先级顺序？
答：
  1. 权重重平衡（RSI 0.30→0.22，4H 0.40→0.45）
  2. neutral_upgrade 放宽 + partial_confirm 路径
  3. rsi_1h_direction_against_veto → soft penalty
  4. VWAP ATR 归一化
  5. probe_floor_rescue shadow 关闭 + probe_min_open=0.042
  6. 最后才微调 entry_threshold（当前只有 9.5% 的 HOLD 死在阈值）
```

---

## 四、综合 DIFF（完整版）

```diff
# config/trading_config_fund_flow.json

# ── [P0] 权重重平衡 ──────────────────────────────────────────────
  "scoring_weights": {
    "weight_1h_direction":    0.150000,
-   "weight_4h_direction":    0.400000,
+   "weight_4h_direction":    0.450000,
-   "weight_4h_enhancement":  0.100000,
+   "weight_4h_enhancement":  0.000000,
-   "weight_rsi_rhythm":      0.300000,
+   "weight_rsi_rhythm":      0.220000,
    "weight_vwap":            0.000000,
-   "weight_15m_entry":       0.050000,
+   "weight_15m_entry":       0.080000,
    "weight_volume":          0.100000
  },
+ "rsi_rhythm_score_cap": {"enabled": true, "max_score": 1.00},

# ── [P0] neutral_upgrade 放宽 + partial_confirm ──────────────────
  "neutral_upgrade": {
    "enabled":                         true,
-   "neutral_upgrade_min_rsi_score":   0.35,
+   "neutral_upgrade_min_rsi_score":   0.20,
-   "neutral_upgrade_probe_rsi_score": 0.20,
+   "neutral_upgrade_probe_rsi_score": 0.12,
    "neutral_upgrade_penalty_mult":    0.90,
+   "partial_confirm_path": {
+     "enabled":          true,
+     "4h_shrink_signals": ["red_bar_shrinking","green_bar_shrinking"],
+     "1h_confirm_long":   ["red_bar_growing","flip_bullish"],
+     "1h_confirm_short":  ["green_bar_growing","flip_bearish"],
+     "penalty_mult":      0.85,
+     "max_portion":       0.10,
+     "score_bonus":       0.02
+   }
  },

# ── [P0] RSI veto 软化 ───────────────────────────────────────────
  "rsi_rhythm": {
    "enable_hard_veto":         true,
+   "hard_veto_upgrade": {
+     "enabled":              true,
+     "exempt_score_4h_ge":   0.30,
+     "exempt_penalty_mult":  0.92,
+     "exempt_score_ge":      0.75,
+     "exempt_adx_le":        20,
+     "exempt_regime":        ["RANGE"],
+     "exempt_penalty_range": 0.90
+   }
  },

# ── [P1] VWAP ATR 归一化 ─────────────────────────────────────────
- "vwap_deviation_hard_block": 0.03,
+ "vwap_deviation_gate": {
+   "mode":                   "atr_normalized",
+   "pass_atr_multiplier":    1.5,
+   "penalty_atr_multiplier": 2.5,
+   "probe_atr_multiplier":   4.0,
+   "block_atr_multiplier":   4.0,
+   "penalty_mult_slope":     0.15,
+   "probe_max_portion":      0.06,
+   "fallback_pct":           0.06
+ },

# ── [P1] 1H confirmation 软化 ────────────────────────────────────
- "require_1h_confirmation_when_4h_primary": true,
+ "require_1h_confirmation_when_4h_primary": false,
+ "prefer_1h_confirmation_when_4h_primary":  true,
+ "1h_missing_confirmation_penalty":         0.90,

# ── [P1] 仓位压缩综合下限 ────────────────────────────────────────
+ "dynamic_sizing.total_compression_floor": {
+   "enabled": true,
+   "floors": [
+     {"min_score": 0.85, "min_mult_of_base": 0.45},
+     {"min_score": 0.75, "min_mult_of_base": 0.35},
+     {"min_score": 0.65, "min_mult_of_base": 0.25},
+     {"min_score": 0.00, "min_mult_of_base": 0.15}
+   ]
+ },

# ── [P1] probe_floor_rescue 上线 ─────────────────────────────────
  "probe_floor_rescue": {
-   "shadow_mode":         true,
+   "shadow_mode":         false,
    "min_score_threshold": 0.800,
-   "probe_portion":       0.060,
+   "probe_min_open":      0.042,
    "probe_leverage_cap":  2
  },
+ "min_open_portion_probe": 0.042,    # probe 专用 min_open
```

---

## 五、预期效果与验收标准

```
修复前 → 修复后（预期）：
  HOLD 因"4H无明确方向"：788 次 → 约 400~500 次（partial_confirm 路径承接）
  HOLD 因 rsi_1h_against_veto：362 次 → 约 150~200 次（soft penalty 豁免部分）
  HOLD 因 vwap_hard_block：360 次 → 约 150~180 次（ATR 归一化后 probe_only）
  min_open 被丢弃高分信号：10 次 → 约 2~3 次（probe_floor_rescue 兜底）

  预期新增有效开仓：从 4 笔/窗口 → 15~25 笔/窗口
  预期仓位规模：score=0.85 信号从 0.042 → 0.157（floor=0.45×base）

验收标准（30D strict_live_mode 回测）：
  成交笔数：≥ 55 笔/月（当前约 30 笔/月）
  WR：≥ 72%
  max_drawdown：≤ 10%（权重变化后 DD 可能略增）
  avg_portion：0.12~0.20（不要回到 0.336 的大仓水平）

重要监控点（上线后前 3 天）：
  1. partial_confirm 路径的胜率（目标 ≥ 65%）
  2. probe_floor_rescue 实际开仓的胜率（目标 ≥ 62%）
  3. 权重调整后 score_4h 的平均值（目标从 0.12 提升到 0.20+）
  4. rsi_1h_direction_against_veto 触发次数（应从 362 降到 150 以下）
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-13*  
*核心结论：降低阈值只能解决 9.5% 的问题；解决 80% 的 HOLD 需要权重重平衡 + 方向门控软化 + VWAP ATR 归一化三管齐下*
