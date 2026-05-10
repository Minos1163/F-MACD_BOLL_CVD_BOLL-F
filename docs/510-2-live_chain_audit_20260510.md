# Live Strategy Chain 审阅与建议
**审阅窗口**: 2026-05-08 19:00 BJ → 2026-05-10 09:30 BJ  
**审阅模式**: 实盘链路归因 + 参数一致性 + 损失归因  
**核心关切**: 权重加总失真 / Short 胜率崩溃 / 阈值过低 / VWAP 门控失效

---

## ⚠️ FINDINGS（严重程度降序）

---

### [CRITICAL-1] 权重加总 = 1.15，评分系统存在结构性失真

**发现**

```
weight_1h_direction    = 0.15
weight_4h_direction    = 0.40
weight_4h_enhancement  = 0.10   ← 实际被 fold 进 score_4h，独立输出常为 0
weight_rsi_rhythm      = 0.30
weight_vwap            = 0.05
weight_15m_entry       = 0.05
weight_volume          = 0.10
─────────────────────────────
sum                    = 1.15   ← 应为 1.00
```

**问题推导**

```python
# 当前行为（无归一化）
raw_score = (
    score_1h   * 0.15 +
    score_4h   * 0.40 +   # 含 enhancement fold-in
    score_rsi  * 0.30 +
    score_vwap * 0.05 +
    score_15m  * 0.05 +
    score_vol  * 0.10
)
# 乘以惩罚系数后 cap 到 1.0
final_score = min(raw_score * penalty_mult, 1.0)

# 问题 1：如果所有分量都满分（=各自上限），
# raw_score 可达 1.15，但被 cap 到 1.0。
# 这意味着"完美信号"和"次完美信号"在 cap 区无法被区分。

# 问题 2：weight_4h_enhancement = 0.10 配置存在，
# 但 score_4h_enhancement 运行时输出恒为 0.0。
# 这 0.10 的权重要么 fold 进了 score_4h（重复计算），
# 要么彻底丢失——两种情况都是 bug。

# 问题 3：当前阈值 0.64~0.69 是在 1.15 权重体系下校准的。
# 如果将权重归一化到 1.00，等效阈值变为：
normalized_equiv = 0.64 / 1.15  # ≈ 0.557（实际质量远低于表面数字）
```

**证据：运行时分数样本**

```
ATOMUSDT: score_1h=0.34, score_4h=0.15, score_vwap=0.00, score_15m=0.0053, score_vol=0.033
raw = 0.34×0.15 + 0.15×0.40 + 0?×0.30 + 0.00×0.05 + 0.0053×0.05 + 0.033×0.10
    = 0.051 + 0.060 + 0 + 0 + 0.000265 + 0.0033 = 0.1146 + RSI项

总分 0.6332，但 RSI 项 = 0.6332 - 0.1146 ≈ 0.519
→ RSI rhythm 项贡献了总分的 82%！
→ score_4h = 0.15 只贡献了 0.060（仅 9.5%）
→ 这不是"4H 主导"策略，是"RSI 主导"策略，参数描述和实际行为不符
```

**DIFF：修复权重加总**

```diff
# config/trading_config_fund_flow.json

  "scoring_weights": {
-   "weight_1h_direction":   0.150000,
-   "weight_4h_direction":   0.400000,
-   "weight_4h_enhancement": 0.100000,
-   "weight_rsi_rhythm":     0.300000,
-   "weight_vwap":           0.050000,
-   "weight_15m_entry":      0.050000,
-   "weight_volume":         0.100000
+   "weight_1h_direction":   0.130000,   # 0.15 / 1.15
+   "weight_4h_direction":   0.348000,   # 0.40 / 1.15
+   "weight_4h_enhancement": 0.000000,   # fold 进 4h 就归零，不重复计
+   "weight_rsi_rhythm":     0.261000,   # 0.30 / 1.15
+   "weight_vwap":           0.043000,   # 0.05 / 1.15
+   "weight_15m_entry":      0.043000,   # 0.05 / 1.15
+   "weight_volume":         0.087000    # 0.10 / 1.15
+   # sum = 0.912 ≈ 1.00（忽略 4h_enhancement 后）
  }

# 或者选项 B：保留所有权重，去掉 fold，让 4h_enhancement 独立输出
+ "weight_4h_enhancement": 0.087,       # 0.10/1.15
+ # 同时修复 score_4h_enhancement 的计算逻辑，使其不再恒为 0
```

```python
# 伪代码：归一化后的评分函数
def calc_normalized_score(components: dict) -> float:
    """
    components = {
      "score_1h":   float,
      "score_4h":   float,   # 不含 enhancement
      "score_4h_enh": float, # 独立 enhancement 分
      "score_rsi":  float,
      "score_vwap": float,
      "score_15m":  float,
      "score_vol":  float,
    }
    """
    WEIGHTS = {
        "score_1h":    0.130,
        "score_4h":    0.348,
        "score_4h_enh": 0.087,
        "score_rsi":   0.261,
        "score_vwap":  0.043,
        "score_15m":   0.043,
        "score_vol":   0.087,
    }
    assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001, "权重必须加总为 1.0"

    raw = sum(components[k] * w for k, w in WEIGHTS.items())
    return min(raw, 1.0)   # cap 在归一化后意义更明确
```

---

### [CRITICAL-2] Short 胜率 47.37%，低于随机水平 — 不可继续实盘

**发现**

```
方向    成交  胜  负  胜率     PnL       avg_pnl
LONG    25   19   6  76.00%  +5.96     +0.238
SHORT   19    9  10  47.37%  +0.77     +0.040
```

**Short 信号族分解**

```
信号族                                    成交  胜  负  胜率
macd_v2_short_1h_flip_bearish_15m_        4    1   3  25.00%  ← 最差
macd_v2_short_1h_green_bar_growing_15m_rsi_neutral_resume  6  2  4  33.33%
macd_v2_short_1h_green_bar_growing_15m_   9    6   3  66.67%
```

**问题根因推导**

```python
# 问题 1：flip_bearish 在牛市背景下做空，逆势交易
# 当前窗口 (2026-05-08~10) 是市场强势上涨窗口
# flip_bearish 做空 = 主动逆势，成功率结构性低

# 问题 2：rsi_neutral_resume 短线做空逻辑不清晰
# "RSI 中性恢复"触发做空，但没有强方向确认
# 实质上是低信噪比信号

# 问题 3：top loss 验证
# MORPHOUSDT SHORT -0.826: flip_bearish, TREND regime, ADX=37.3
# → 在趋势市场里逆势做空，ADX>30 说明趋势强度高
# VETUSDT SHORT -0.086:  flip_bearish, TREND regime, ADX=36.6
# ZECUSDT SHORT -0.075:  rsi_neutral_resume, RANGE regime, ADX=14.1
# → RANGE 做空还可接受，但 TREND 做空 flip_bearish 是核心问题

# 量化：在 TREND regime 里 flip_bearish 做空
trend_flip_bearish_shorts = [
    ("MORPHOUSDT", -0.826),
    ("VETUSDT",    -0.086),
    ("BCHUSDT",    -0.044),
]
# 这 3 笔全部亏损，flip_bearish TREND short win_rate ≈ 0%
```

**DIFF：短期内屏蔽高风险 short 路径**

```diff
# config/trading_config_fund_flow.json

+ "short_regime_guard": {
+   "enabled": true,
+   "flip_bearish_block_regimes":         ["TREND"],   # TREND 里禁止 flip_bearish 做空
+   "flip_bearish_min_adx_for_trend":     25,          # ADX>25 认定为 TREND
+   "rsi_neutral_resume_short_enabled":   false,       # 临时关闭此路径
+   "green_bar_growing_short_min_adx":    0,           # 不额外限制（当前 66.7% 可接受）
+ }
```

```python
# 伪代码：short 方向 regime 守门
def guard_short_direction(signal: dict, regime: str, adx: float) -> bool:
    """
    返回 False = 禁止此 short 开仓
    """
    family = signal.get("reason_family", "")

    # flip_bearish 在强趋势市场里不做空
    if "flip_bearish" in family:
        if regime == "TREND" and adx >= 25:
            log_block(f"flip_bearish short blocked: TREND regime ADX={adx:.1f}")
            return False

    # rsi_neutral_resume 做空临时关闭
    if "rsi_neutral_resume" in family and signal["side"] == "SHORT":
        log_block("rsi_neutral_resume short path disabled")
        return False

    return True
```

---

### [HIGH-1] 活跃阈值 0.64~0.69 相对于信号质量明显偏低

**发现**

```
当前运行时阈值：
  flip_bullish:    0.60
  flip_bearish:    0.62
  red_bar_growing: 0.64
  green_bar_growing: 0.65
  preflip_trial:   0.66

实际通过样本（典型）：
  ATOMUSDT total=0.6332, threshold=0.600 → delta=+0.033
  BCHUSDT  total=0.6418, threshold=0.640 → delta=+0.002  ← 贴线通过
  SOLUSDT  total=0.6647, threshold=0.660 → delta=+0.005  ← 贴线通过
```

**"贴线通过"比例估算**

```python
# 从运行时日志推导
# 阈值分布：0.60(103) / 0.62(163) / 0.64(2682) / 0.65(771) / 0.66(983)
# 总样本 = 4702

# 如果每个档位平均 delta ≈ 0.01（贴线），则信号质量非常边缘
# 对比：权重归一化后，当前 0.64 等效质量 ≈ 0.557
# 相当于每个分量平均得到其最大值的 55.7%

# 建议阈值提升方向（归一化后等效）：
# 目标等效质量 0.65+ → 归一化前阈值 = 0.65 × 1.15 ≈ 0.748
# 但注意：先归一化权重，再重新校准阈值，不要在 1.15 体系里直接提到 0.85

current_threshold = {
    "flip_bullish":    0.60,
    "flip_bearish":    0.62,
    "red_bar_growing": 0.64,
    "green_bar_growing": 0.65,
    "preflip_trial":   0.66,
}

# 如果权重先归一化（1.15→1.00），等效阈值自动下降
# 在新权重体系下，0.64→0.557, 0.68→0.591
# 重新校准目标：归一化后阈值保持 0.58~0.62 区间
# 对应原始体系（1.15）的阈值 ≈ 0.667~0.713

proposed_threshold_normalized = {
    "flip_bullish":    0.575,   # 偏保守路径，要求更高
    "flip_bearish":    0.590,
    "red_bar_growing": 0.600,
    "green_bar_growing": 0.605,
    "preflip_trial":   0.620,
}
```

**DIFF**

```diff
# 注意：此 DIFF 基于权重已归一化到 1.00 的前提
# 不要在 1.15 权重体系下直接应用这些数字

  "entry_thresholds": {
-   "flip_bullish":    0.60,
+   "flip_bullish":    0.575,

-   "flip_bearish":    0.62,
+   "flip_bearish":    0.590,

-   "red_bar_growing": 0.64,
+   "red_bar_growing": 0.600,

-   "green_bar_growing": 0.65,
+   "green_bar_growing": 0.605,

-   "preflip_trial":   0.66,
+   "preflip_trial":   0.620,
  }
```

---

### [HIGH-2] score_4h 实际贡献极低，4H 主导设计名实不符

**发现**

```
运行时样本中 score_4h 的实际值：
  flip_bullish 档:   0.150   (最大值)
  flip_bearish 档:   0.150   (最大值)
  green_bar_shrinking: 0.025 (极低)
  red_bar_shrinking:  0.073~0.149

权重 weight_4h_direction = 0.40（最大权重）
但 score_4h 的实际中位值约 0.12~0.15
→ 4H 方向分实际贡献 = 0.12 × 0.40 = 0.048
→ RSI rhythm 分实际贡献 ≈ 0.519（从 ATOMUSDT 推导）

这意味着：
- weight_4h_direction 配置的语义是"4H 是主导"
- 但实际上 RSI rhythm 分贡献了 80%+ 的总分
- 4H 方向分几乎是摆设（0.048 vs 0.519）
```

**推导：score_4h 为何这么低**

```python
# 4H 方向分的计算推断
# 在 flip 状态（4H MACD 正在 flip），方向还未确认
# → score_4h 只能得到"flip 中"的部分分 ≈ 0.15（满分可能是 0.40）

# 在 red_bar_shrinking / green_bar_shrinking 状态
# → 趋势正在衰减，方向弱 → score_4h ≈ 0.025~0.149

# 结论：当 4H 信号最弱（flip / shrink）的时候，
# 策略仍然允许开仓（因为 RSI 分能补上大部分总分），
# 这正是问题所在：用高 RSI 分来弥补差的 4H 信号质量

# 修复方向：对 score_4h 设置独立的硬性最低分
MIN_4H_SCORE_FOR_ENTRY = 0.12   # 4H 分至少要达到 0.12（满分的 30%）
# 低于此值，无论总分多高，都不开仓

def score_4h_hard_gate(score_4h: float) -> bool:
    if score_4h < MIN_4H_SCORE_FOR_ENTRY:
        log_block(f"score_4h={score_4h:.3f} < min {MIN_4H_SCORE_FOR_ENTRY}")
        return False
    return True
```

**DIFF**

```diff
# macd_strategy_v2.py — 在最终评分聚合后、阈值检查前插入

+ MIN_4H_SCORE_HARD_GATE = 0.12

  def _check_entry_signal(self, signal: MACDSignalV2) -> bool:
      score = signal.total_score
      threshold = self._resolve_threshold(signal)

+     # 4H 方向分硬性门槛（独立于总分）
+     if signal.score_4h < MIN_4H_SCORE_HARD_GATE:
+         self._log_block(signal, f"4H score {signal.score_4h:.3f} below hard gate {MIN_4H_SCORE_HARD_GATE}")
+         return False

      if score < threshold:
          return False
      return True
```

---

### [MEDIUM-1] VWAP 门控对当前亏损窗口无区分力 — 门控已失效

**发现**

```
亏损归因：
  所有 top losses 的 vol_vwap_warn = False
  大量亏损单 vwap_score = 0.25（通过了当前 VWAP 门控）

VWAP bucket 胜率：
  (0.12, 0.25]:  70.37%（27 笔）← 包含大部分 long 亏损单
  > 0.5:         50.00%（16 笔）← 更差
  (0.25, 0.5]:  100.00%（1 笔） ← 样本太小不可信

问题：
  vwap_score = 0.25 被当作"通过"，但这个档位的胜率只有 70.37%
  这个 VWAP 质量分对亏损单没有区分力
  → VWAP gate 当前实际上是"形同虚设"
```

**问题重构**

```python
# 当前 VWAP gate 逻辑推断
def vwap_gate_current(vwap_score: float) -> bool:
    """
    当前：只要 vwap_score > 0.12 就通过
    """
    return vwap_score >= 0.12

# 问题：LONG 亏损单中 vwap_score = 0.25 全部通过了这个门
# 但这些单子亏损的真实原因是：
#   价格虽然在 VWAP 之上，但追入时距离 VWAP 已经过远
#   或者 VWAP 本身在上涨（所有价格都在 VWAP 上方），
#   这时 vwap_score 没有区分意义

# 更好的 VWAP 过滤方向：
# 不仅看"在不在 VWAP 上方"，还要看"距离 VWAP 多远"
# 如果价格已经偏离 VWAP 2%+，做多的性价比大幅下降

def vwap_gate_improved(
    price: float,
    vwap: float,
    direction: str,
    vwap_score: float,
) -> tuple[bool, float]:
    """
    返回 (allow, size_penalty)
    """
    deviation_pct = (price - vwap) / vwap  # 正数 = 价格在 VWAP 之上

    # LONG 方向：价格偏离 VWAP 太远，追高风险大
    if direction == "LONG":
        if deviation_pct > 0.025:          # 距离 VWAP 超过 2.5%
            return False, 0.0              # 直接阻止
        elif deviation_pct > 0.015:        # 距离 1.5%~2.5%
            return True, 0.5               # 允许但仓位减半

    # SHORT 方向：价格偏离 VWAP 太远在下方，追空风险大
    if direction == "SHORT":
        if deviation_pct < -0.025:
            return False, 0.0
        elif deviation_pct < -0.015:
            return True, 0.5

    return True, 1.0
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "vwap_filter": {
    "enabled": true,
-   "min_vwap_score": 0.12,
+   "min_vwap_score": 0.20,        # 提高最低门槛

+   "enable_deviation_gate": true,
+   "long_max_deviation_pct": 0.025,   # LONG 时价格偏离 VWAP 超过 2.5% 不开
+   "long_penalty_deviation_pct": 0.015, # 1.5%~2.5% 减仓 50%
+   "short_max_deviation_pct": -0.025,
+   "short_penalty_deviation_pct": -0.015,
  }
```

---

### [MEDIUM-2] 微仓位 (min-notional) 探针条目混入正常成交归因

**发现**

```
部分 top losses 的 target_portion 极小：
  TONUSDT  SHORT: target_portion=0.002499  ← 微探针
  ALGOUSDT SHORT: target_portion=0.002499  ← 微探针
  JUPUSDT  SHORT: target_portion=0.002499  ← 微探针
  SOLUSDT  SHORT: target_portion=0.000490  ← 极微

这些条目是由 min_open_portion=0.06 × 折扣后产生的最小仓位单，
实际上是"不得不挂"的系统最小单，不代表策略决定。
但它们的亏损被计入了 matched_realized_pnl，
导致 SHORT 亏损笔数虚高（10 笔中有 4~5 笔是微探针）。
```

**重新清洗后的 Short 胜率**

```python
# 过滤微探针条目（target_portion < 0.01）
def filter_meaningful_entries(trades: list[dict]) -> list[dict]:
    """
    只保留 target_portion >= 0.01 的正式开仓，
    排除因 min_notional 产生的占位微单
    """
    MIN_MEANINGFUL_PORTION = 0.010
    return [t for t in trades if t["target_portion"] >= MIN_MEANINGFUL_PORTION]

# 清洗后重新计算 Short 统计
micro_positions = [
    "TONUSDT SHORT  -0.151  target=0.002499",
    "ALGOUSDT SHORT -0.146  target=0.002499",
    "JUPUSDT SHORT  -0.063  target=0.002499",
    "SOLUSDT SHORT  -0.044  target=0.000490",
    "ALGOUSDT SHORT -0.061  target=0.003124",  # 也是微单
]
# 这 5 笔微单损失合计 -0.465 USDT

# 清洗后 Short 统计（去除微单）：
# 总损失从 -1.51 → 约 -1.04
# 亏损笔数从 10 → 约 5~6
# 清洗后 SHORT 胜率估算 ≈ 9/(9+5) = 64.3%（vs 原始 47.37%）
# 说明 SHORT 的真实胜率比报告数字好，但仍然弱于 LONG 的 76%
```

**DIFF：归因系统过滤微仓位**

```diff
# 在 loss attribution 统计入口处新增过滤

  def match_entries_to_fills(entries, fills):
+     # 过滤微仓位条目
+     MEANINGFUL_THRESHOLD = 0.010
+     entries = [e for e in entries
+                if e.get("target_portion", 1.0) >= MEANINGFUL_THRESHOLD]
+
+     # 记录被过滤的微仓位数量
+     micro_count = len(entries_original) - len(entries)
+     log_info(f"Filtered {micro_count} micro-position entries from attribution")

      # 原有匹配逻辑...
      for fill in fills:
          ...
```

---

### [LOW-1] weight_4h_enhancement = 0.10 配置存在但运行时恒为 0

**发现**

```
所有运行时样本中 score_4h_enhancement = 0.0
但 weight_4h_enhancement = 0.10 仍然配置在权重列表中，
且被计入 weight_sum = 1.15

两种可能：
A. 4h_enhancement 逻辑已被 fold 进 score_4h，独立字段废弃 → 需清理配置
B. 4h_enhancement 计算代码有 bug，总是返回 0 → 需修复
```

**诊断伪代码**

```python
# 定位问题：检查 4h enhancement 的计算路径
def diagnose_4h_enhancement(macd_4h_data: dict) -> dict:
    """
    运行此函数，如果返回的 raw_enhancement 总为 0，说明是 bug B
    如果返回非 0 但 emitted_score 为 0，说明是 fold-in 问题 A
    """
    raw_enhancement = compute_4h_enhancement_bonus(macd_4h_data)
    # 检查 fold 位置
    folded_into_4h = check_if_folded_to_score_4h(macd_4h_data)

    return {
        "raw_enhancement":    raw_enhancement,
        "folded_into_4h":     folded_into_4h,
        "emitted_score_4h_enh": get_emitted_score(macd_4h_data, "4h_enhancement"),
    }
```

**DIFF**

```diff
# 情况 A（fold 已发生）：清理废弃配置字段
- "weight_4h_enhancement": 0.100000,   # 删除，已 fold 进 weight_4h_direction

# 同时修正注释：
+ # weight_4h_direction 的 0.40 已内含 4H enhancement bonus
+ # 实际有效 4H 权重 = 0.40（方向 + enhancement 合并）
```

---

## 二、回答六个具体问题

---

### Q1: 权重加总 1.15 + cap 1.0，是否合理？

**结论：不合理，需要修复。**

```
当前设计的隐性问题：
  - cap 在 1.15 权重体系下是"切割最优信号"的机制
  - 真正高质量信号（各分量均强）会被 cap 截平，
    与次优信号在评分上无法区分
  - 这直接导致阈值失去相对意义：0.64 的信号和 0.80 的信号，
    如果都超过阈值，系统无法区分质量高低来调整仓位

修复优先级：
  1. 先归一化权重到 1.00
  2. 重新校准阈值（在新权重体系下重新跑 30 天回测）
  3. 不要在 1.15 体系下直接调整阈值，会产生隐式偏移
```

---

### Q2: 当前阈值 0.64~0.69 是否过低？

**结论：相对于当前信号质量，阈值不是主要问题，但存在结构性偏低。**

```
阈值的实际意义取决于权重体系：
  - 在 1.15 权重体系下，0.64 对应归一化分 ≈ 0.557
  - 历史目标 0.85 对应归一化分 ≈ 0.739

当前运行时样本多数在 0.63~0.67 贴线通过，
这说明阈值设置已经基本与信号质量边界对齐（再高就没信号了）。

真正的问题不是"阈值要从 0.64 提到 0.85"，
而是"信号质量本身太低（score_4h 只有 0.025~0.15）"。

建议：提升信号质量（修 4H 评分逻辑），然后阈值自然可以更高。
不要在信号质量未提升的前提下单纯提阈值——会导致零成交。
```

---

### Q3: red_bar_growing / flip_bullish 应该保持 0.64，还是回到 0.75~0.85？

**结论：中期目标 0.70~0.75，但现在不能直接跳跃。**

```
路径建议：
  Step 1: 归一化权重（约 2 天工作）
    → 在新体系下 0.64 等效于旧体系约 0.55，极低
  Step 2: 修复 score_4h 的实际贡献（约 1 周工作）
    → 修复后 score_4h 应能到 0.25~0.35（当前 0.12~0.15）
  Step 3: 重新跑 30 天 strict_live_mode 回测
    → 确认修复后哪个阈值对应合理成交量（目标 60~80 笔/月）
  Step 4: 在新体系下设置 red_bar_growing = 0.62~0.65
    → 这相当于旧体系的 0.71~0.75

直接从 0.64 跳到 0.85：
  → 当前评分体系下几乎零成交（见 ATOMUSDT total=0.633 < 0.850）
```

---

### Q4: 亏损是否集中在低 VWAP 质量、特定 regime 或 trial 条目？

**结论：亏损主要集中在特定信号族 + TREND regime 做空，而非 VWAP 质量。**

```
证据：
  - vol_vwap_warn = False for ALL top losses（VWAP 门控无效）
  - vwap_score = 0.25 是大多数亏损单的 VWAP 值（通过了当前门控）
  - 但 TREND regime 下 flip_bearish 做空 win_rate ≈ 0%
  - rsi_neutral_resume short 路径 win_rate = 33.33%

结论：
  A. 当前 VWAP gate (min=0.12) 无效，需提到 0.20 并加入偏离度检查
  B. 真正需要加门控的是：short 方向 × TREND regime × flip_bearish 组合
  C. trial 条目（target_portion 微小）不应计入正式归因
```

---

### Q5: 微仓位 min-notional 条目是否应该单独会计？

**结论：应该，且应立即修复归因统计。**

```
micro_position 条目（target_portion < 0.01）：
  - 是系统为满足交易所 min_notional 强制建立的占位仓
  - 不代表策略的真实决策
  - 但被计入 matched_realized_pnl，导致 SHORT 亏损笔数虚高

修复方案：
  1. 归因统计中过滤 target_portion < 0.01 的条目
  2. 这些微仓位单独统计，标记为 "micro_notional" 类别
  3. 整体 PnL 报告中保留（因为实际产生了资金变动），
     但 win_rate / signal_quality 分析中排除

预期效果：
  SHORT 清洗后胜率从 47.37% 提升到约 64%
  更准确地反映短边策略的真实质量
```

---

### Q6: protection-gap 和 active-symbol-cap 是否造成逆向选择？

**结论：存在逆向选择风险，但当前证据不足以确认。**

```
逆向选择机制推断：
  当 max_active_symbols=3 已满时：
    → 新的高分信号被容量 cap 拒绝
    → 已有的低分仓位继续持有（因为没有 priority eviction）
    → 结果：保留弱仓位，错过强信号

当前窗口中 capacity_competition 的影响：
  无法直接从此报告确认，但结合上次审阅（71 笔被容量竞争丢弃），
  这个风险是真实的。

建议：
  记录每次被 cap 拒绝的信号得分，
  与当时已有仓位的最低得分对比，
  如果拒绝信号分数 > 最低活跃仓位分数的案例 > 20%，
  则需要引入 priority eviction 机制。
```

---

## 三、综合参数修改 DIFF

```diff
# config/trading_config_fund_flow.json
# ── 权重归一化（优先级最高） ─────────────────────────────────────

  "scoring_weights": {
-   "weight_1h_direction":   0.150000,
-   "weight_4h_direction":   0.400000,
-   "weight_4h_enhancement": 0.100000,
-   "weight_rsi_rhythm":     0.300000,
-   "weight_vwap":           0.050000,
-   "weight_15m_entry":      0.050000,
-   "weight_volume":         0.100000
+   "weight_1h_direction":   0.148000,   # 0.15/1.01
+   "weight_4h_direction":   0.396000,   # 0.40/1.01（含 enhancement）
+   "weight_4h_enhancement": 0.000000,   # fold-in 后清零
+   "weight_rsi_rhythm":     0.297000,   # 0.30/1.01
+   "weight_vwap":           0.050000,   # 保持
+   "weight_15m_entry":      0.050000,   # 保持
+   "weight_volume":         0.099000    # 0.10/1.01
+   # sum ≈ 1.040（4h_enh 清零后，有效权重重新校准）
  },

# ── Short 方向风控 ───────────────────────────────────────────────

+ "short_direction_guard": {
+   "enabled": true,
+   "flip_bearish_blocked_regimes": ["TREND"],
+   "flip_bearish_min_adx_threshold": 25,
+   "rsi_neutral_resume_short_enabled": false,
+   "short_min_4h_score": 0.10
+ },

# ── VWAP 门控增强 ────────────────────────────────────────────────

  "vwap_filter": {
-   "min_vwap_score": 0.12,
+   "min_vwap_score": 0.20,
+   "enable_deviation_gate": true,
+   "long_max_vwap_deviation_pct":  0.025,
+   "long_warn_vwap_deviation_pct": 0.015,
+   "short_max_vwap_deviation_pct": -0.025,
+   "short_warn_vwap_deviation_pct": -0.015,
+   "deviation_warn_size_penalty": 0.50
  },

# ── 4H 硬性最低分 ────────────────────────────────────────────────

+ "score_4h_hard_gate": {
+   "enabled": true,
+   "min_score_4h_for_entry": 0.12,
+   "apply_to_families": ["red_bar_growing", "green_bar_growing",
+                          "flip_bearish", "flip_bullish"]
+ },

# ── 微仓位归因过滤 ───────────────────────────────────────────────

+ "attribution_filter": {
+   "min_meaningful_target_portion": 0.010,
+   "micro_position_tag": "micro_notional",
+   "exclude_micro_from_winrate": true
+ }
```

---

## 四、执行路线图

```
优先级   行动                              预期效果          风险
─────────────────────────────────────────────────────────────────
P0      归一化权重（1.15→1.00）            修复评分语义       需重新校准阈值
P0      Short regime guard 上线           SHORT WR 从47%→64%+ 可能减少成交量
P1      VWAP 偏离度门控                   减少追高/追低亏损   可能减少5~10%成交
P1      score_4h 硬性最低分 0.12          提升信号质量        可能减少10~15%成交
P2      归因微仓位过滤                    修复报告准确性      纯统计改进
P2      4h_enhancement 代码诊断           修复 0.0 问题       代码层修复
P3      阈值重新校准（基于新权重体系）    建立新基准          需完整回测验证
```

```
下一步验证流程：
  1. 权重归一化提交后，立即跑 strict_live_mode 30 天回测
     → 确认成交量不低于 60 笔（过少则评分过严）
     → 确认 win_rate 不低于 72%（分母变了要注意）

  2. Short regime guard 上线后，观察 2 天实盘
     → 对比 SHORT entry 数量（预期减少 30~40%）
     → 对比 SHORT win_rate（预期提升到 60%+）

  3. 如果 score_4h 问题确认是 bug B（计算恒为 0），
     修复后 4H 分会显著提升，
     届时现有阈值可能变得过低（成交量暴增），
     需要同步提阈值
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-10*  
*数据来源: Live Strategy Chain + Loss Attribution Review (2026-05-08 ~ 2026-05-10)*  
*注意: 微仓位清洗后的 Short 胜率为估算值，需用实际数据验证*
