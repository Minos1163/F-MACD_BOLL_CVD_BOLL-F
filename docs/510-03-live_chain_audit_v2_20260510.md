# Live Strategy Chain 审阅 v2 — 有效仓位分层后的再归因
**审阅窗口**: 2026-05-08 19:00 BJ → 2026-05-10 09:30 BJ  
**本版新增**: meaningful / micro-notional 分层已确认，重新基于干净数据做结论  
**核心变化**: SHORT 有效仓位胜率 = **25%**（4笔，非上版估算的 64%），结论需要全面修订

---

## ⚠️ FINDINGS（严重程度降序）

---

### [CRITICAL-1] SHORT 有效仓位胜率 25%，flip_bearish 路径实质已经失效

**数据还原**

```
── 全量 SHORT（含微仓） ──
  entries=19  wins=9  losses=10  WR=47.37%

── 有效仓位 SHORT（target_portion ≥ 0.01） ──
  entries=4   wins=1  losses=3   WR=25.00%   ← 本版关键数字

── 微仓位 SHORT（target_portion < 0.01） ──
  entries=15  wins=8  losses=7   WR=53.33%   ← 尚可接受

结论：上版估算"清洗后约 64%"是错的。
真实有效 SHORT 胜率只有 25%，远低于随机水平的 50%。
```

**4 笔有效 SHORT 的逐笔核对**

```python
# 从 top losses 表反向提取有效 SHORT 条目
meaningful_shorts = [
    # target_portion ≥ 0.01 的 SHORT
    {
        "symbol": "MORPHOUSDT",
        "pnl": -0.825830,
        "portion": 0.2856,      # 大仓
        "leverage": 3,
        "regime": "TREND",
        "adx": 37.25,
        "family": "macd_v2_short_1h_flip_bearish_15m__vwap_0.25",
        "result": "LOSS",
    },
    {
        "symbol": "VETUSDT",
        "pnl": -0.086056,
        "portion": 0.0175,
        "leverage": 3,
        "regime": "TREND",
        "adx": 36.55,
        "family": "macd_v2_short_1h_flip_bearish_15m__vwap_0.69",
        "result": "LOSS",
    },
    {
        "symbol": "BCHUSDT",
        "pnl": -0.043700,
        "portion": 0.0105,
        "leverage": 1,
        "regime": "TREND",
        "adx": 29.49,
        "family": "macd_v2_short_1h_flip_bearish_15m__vwap_0.25",
        "result": "LOSS",
    },
    # 第 4 笔：唯一的胜单（来自 flip_bearish 或 green_bar_growing）
    # 从 family 统计表推断：flip_bearish 4笔1胜，即这里的唯一胜单
    {
        "symbol": "?",
        "pnl": "+0.618564",     # flip_bearish total_pnl 为正，说明那 1 笔胜很大
        "family": "macd_v2_short_1h_flip_bearish_15m_",
        "result": "WIN",
    },
]

# 归因结论：
# 3 笔 flip_bearish 亏损全部在 TREND regime，ADX 29~37
# 说明：flip_bearish 在趋势市做空 = 系统性逆势操作
# 唯一的 1 笔胜可能来自趋势短暂修正，属于运气而非边际优势

# flip_bearish 的根本问题（与上版一致，数据现在更确定）：
# - 4H MACD 刚发生 bearish flip 时，趋势可能只是短期修正
# - 本窗口是牛市（LONG WR=76%），所有 flip_bearish 做空都在对抗主趋势
# - TREND regime + ADX>25 是最强烈的"不要逆势"信号
```

**DIFF：flip_bearish 路径立即增加 TREND 阻断**

```diff
# config/trading_config_fund_flow.json

+ "short_entry_guards": {
+   "flip_bearish": {
+     "block_regime":        ["TREND"],
+     "block_min_adx":       25,
+     "comment": "flip_bearish 在 TREND+ADX>25 下 WR≈0%，立即屏蔽"
+   },
+   "rsi_neutral_resume": {
+     "side_enabled":        {"SHORT": false},
+     "comment": "rsi_neutral_resume SHORT WR=33%，负期望，临时关闭"
+   }
+ }
```

```python
# macd_strategy_v2.py — 在 _check_entry_signal 内插入

def _check_short_entry_guard(
    self,
    signal: MACDSignalV2,
    regime: str,
    adx: float,
) -> tuple[bool, str]:
    """
    返回 (allowed, block_reason)
    """
    if signal.direction != "SHORT":
        return True, ""

    family = signal.reason_family

    # ── flip_bearish TREND 阻断 ──────────────────
    if "flip_bearish" in family:
        if regime == "TREND" and adx >= 25:
            return False, (
                f"flip_bearish SHORT blocked: regime={regime} ADX={adx:.1f} >= 25"
            )

    # ── rsi_neutral_resume SHORT 临时关闭 ────────
    if "rsi_neutral_resume" in family:
        return False, "rsi_neutral_resume SHORT path disabled (WR=33%, negative EV)"

    return True, ""


# 插入位置（伪代码，在 score >= threshold 检查之后）：
def _check_entry_signal(self, signal, regime, adx):
    # ... 原有 score 检查 ...
    if signal.total_score < threshold:
        return False

+   # SHORT 方向守门
+   allowed, reason = self._check_short_entry_guard(signal, regime, adx)
+   if not allowed:
+       self._log_blocked(signal, reason)
+       return False

    return True
```

---

### [CRITICAL-2] LONG 有效仓位 76% WR 但最大亏损集中在高 ADX TREND 单

**数据核对**

```
LONG 损失单（全部 6 笔均为有效仓位）：

symbol    pnl       portion  leverage  regime  adx    vwap_score  family
PUMPUSDT  -1.383    0.336    1         TREND   57.37  0.25        red_bar_growing
ZROUSDT   -0.826    0.118    1         TREND   40.83  0.25        red_bar_growing
ALGOUSDT  -0.773    0.336    1         TREND   36.38  0.25        red_bar_growing
VETUSDT   -0.296    0.118    2         TREND   32.57  0.25        red_bar_growing
POLUSDT   -0.235    0.336    1         TREND   50.59  0.25        red_bar_growing
TRUMPUSDT -0.204    0.336    1         TREND   55.94  0.25        red_bar_growing
```

**规律提取**

```python
# 所有 6 笔 LONG 亏损单的共同特征：
long_loss_pattern = {
    "regime":      "全部 TREND",
    "vwap_score":  "全部 0.25（最低通过档）",
    "family":      "全部 red_bar_growing",
    "adx_range":   "32.57 ~ 57.37（中高强度趋势）",
    "volume_score": "全部 0.033（最低档）",
}

# 关键发现：
# 1. ADX 高（>30）的 TREND 市，red_bar_growing LONG 仍然亏损
#    说明：在高 ADX 趋势下，red_bar_growing 多头不是顺势，
#    而是在追 1H 短暂的"红bar增长"，但 4H 趋势可能已在转向
#
# 2. 所有亏损 LONG 的 vwap_score = 0.25（最低通过档）
#    这是结构性弱信号：VWAP 评分刚过门槛、成交量最低档，
#    却用了 0.336 的大仓（接近最大仓位 0.35）
#
# 3. volume_score 全部 = 0.033（仅是最低量档的分值）
#    低量 + 低 VWAP + 高 ADX = 追入高位弱势信号，风险极高

# 期望值估算：
# 已知：6 笔亏损合计 -3.717，平均 -0.620
# 问题：这 6 笔有多少信号在 score 上比其他 LONG 更强/更弱？
# → 需要完整 score 分布，但当前报告未提供
# → 保守结论：这些亏损单不是"低分漏网鱼"，是"边界分通过的高 ADX 逆势单"
```

**仓位 × 信号质量不匹配问题**

```python
# 当前行为：
# vwap_score=0.25（最低门槛）+ volume_score=0.033（最低档）
# → 使用 target_portion=0.336（接近最大仓位 0.35）

# 这是风险杠杆分配的反向操作：
# 弱信号质量 × 大仓位 = 亏损时损失大
# 应该是：弱信号质量 × 小仓位（probe），强信号质量 × 大仓位

# 修复方向：信号质量 → 仓位动态映射
def calc_position_portion(
    base_portion: float,
    vwap_score: float,
    volume_score: float,
    adx: float,
    regime: str,
) -> float:
    """
    根据信号质量动态调整仓位，不能用固定 target_portion
    """
    portion = base_portion   # 0.35

    # VWAP 质量惩罚
    if vwap_score <= 0.25:          # 最低通过档
        portion *= 0.60             # 仓位压缩到 60%
    elif vwap_score <= 0.50:
        portion *= 0.80

    # 成交量质量惩罚
    if volume_score <= 0.033:       # 最低量档
        portion *= 0.75

    # 高 ADX 趋势环境中的逆向开仓惩罚
    # （ADX > 40 说明趋势极强，此时做短线反向的风险高）
    if regime == "TREND" and adx > 40:
        portion *= 0.70

    return max(portion, 0.06)       # 不低于 min_open_portion
```

**DIFF：动态仓位压缩**

```diff
# macd_strategy_v2.py / fund_flow_bot.py
# 在 _calculate_target_portion() 中插入

  def _calculate_target_portion(self, signal, market_ctx) -> float:
      base = self.config.default_target_portion  # 0.35

+     # ── 信号质量 → 仓位动态压缩 ──────────────
+     vwap_score   = signal.score_vwap
+     volume_score = signal.score_volume
+     adx          = market_ctx.regime_adx
+     regime       = market_ctx.regime

+     quality_mult = 1.0

+     # VWAP 质量分层
+     if vwap_score <= 0.25:
+         quality_mult *= 0.60    # 最低 VWAP 档：压到 60%
+     elif vwap_score <= 0.50:
+         quality_mult *= 0.80

+     # 成交量质量分层
+     if volume_score <= 0.033:
+         quality_mult *= 0.75    # 最低量档：额外压 25%

+     # 高 ADX 趋势做短线：压缩仓位
+     if regime == "TREND" and adx > 40:
+         quality_mult *= 0.70

+     # 综合压缩下限
+     quality_mult = max(quality_mult, 0.30)  # 不压到低于 30% 的 base

+     adjusted = base * quality_mult
+     adjusted = max(adjusted, self.config.min_open_portion)  # 0.06

+     self._log_debug(
+         f"portion: base={base:.3f} × quality_mult={quality_mult:.2f} "
+         f"= {adjusted:.3f} | vwap={vwap_score:.2f} vol={volume_score:.3f} "
+         f"adx={adx:.1f}"
+     )
      return adjusted
```

---

### [HIGH-1] 权重加总 1.15 — 评分失真，score_4h 实际贡献仅 9%

**本版补充分析**

```python
# 从运行时样本反推 RSI rhythm 分贡献
# 以 ATOMUSDT 为例：
score_example = {
    "score_1h":    0.340,
    "score_4h":    0.150,
    "score_vwap":  0.000,
    "score_15m":   0.0053,
    "score_vol":   0.033,
    "total":       0.6332,
}

# 已知权重下的非 RSI 贡献：
non_rsi = (
    0.340 * 0.150 +    # 1h:  0.0510
    0.150 * 0.400 +    # 4h:  0.0600
    0.000 * 0.050 +    # vwap: 0.0
    0.0053 * 0.050 +   # 15m: 0.000265
    0.033 * 0.100      # vol: 0.0033
)  # = 0.1146

rsi_contribution = 0.6332 - 0.1146  # = 0.5186
# RSI rhythm 分 = 0.5186
# RSI rhythm 原始分 = 0.5186 / 0.300 = 1.729
# → RSI 原始分 > 1.0，说明 RSI rhythm 有自己的内部 cap 或倍数加成

# 各分量占总分比例：
breakdown = {
    "1h_direction":  0.0510 / 0.6332,   # 8.1%
    "4h_direction":  0.0600 / 0.6332,   # 9.5%  ← 配置为最大权重，实际只有 9.5%
    "rsi_rhythm":    0.5186 / 0.6332,   # 81.9% ← 实际主导
    "vwap":          0.000  / 0.6332,   # 0.0%  ← 完全无贡献
    "15m":           0.000265/ 0.6332,  # 0.04%
    "volume":        0.0033 / 0.6332,   # 0.5%
}

# score_vwap 在所有样本中均为 0.0：
# 这可能是独立 bug，VWAP 评分模型完全没有输出
# 需要检查：
# a. VWAP 数据是否正确传入评分函数
# b. VWAP 评分函数是否有硬性归零条件
```

**score_vwap 恒为 0 的专项诊断**

```python
# 所有 20 个运行时样本的 score_vwap：
score_vwap_samples = [0.0] * 20   # 全部为 0

# 与 loss 表中的 vwap_score 字段对比：
# loss 表中 vwap_score = 0.25 / 0.694 / 1.0（非 0）

# 结论：
# attribution metadata 中的 vwap_score 是入场筛选前的 VWAP 位置分
# score_vwap（运行时总分表中的字段）是评分聚合中 VWAP 组件的输出
# 两者定义不同：vwap_score 是过滤用的，score_vwap 是评分用的

# score_vwap 恒为 0 意味着：
# VWAP 组件在评分聚合中完全没有贡献分值
# 但它占权重 weight_vwap = 0.05
# → 这 0.05 的权重完全浪费掉了

# 诊断步骤：
def diagnose_score_vwap(price: float, vwap: float) -> float:
    """检查 VWAP 评分是否能产生非零输出"""
    if vwap is None or vwap <= 0:
        return 0.0   # ← 可能是这里：VWAP 数据未正确传入

    rel_pos = (price - vwap) / vwap
    # 如果 rel_pos 的计算依赖某个前置条件（如 VWAP 已初始化超过 N 根K线）
    # 在新日 reset 后可能一直为 0

    if abs(rel_pos) < 0.001:
        return 0.0   # 过小的偏离归零，这没问题

    # 但如果有更强的归零条件，就是 bug
    return min(rel_pos * 5, 1.0)   # 示例：5 倍放大，cap 到 1.0
```

**DIFF：权重修复 + score_vwap 诊断开关**

```diff
# config/trading_config_fund_flow.json

  "scoring_weights": {
    "weight_1h_direction":    0.150000,
    "weight_4h_direction":    0.400000,
-   "weight_4h_enhancement":  0.100000,
+   "weight_4h_enhancement":  0.000000,   # fold-in 确认后清零
    "weight_rsi_rhythm":      0.300000,
    "weight_vwap":            0.050000,
    "weight_15m_entry":       0.050000,
    "weight_volume":          0.100000
+   # sum 变为 1.05；进一步归一化：
+   # 1h=0.143, 4h=0.381, rsi=0.286, vwap=0.048, 15m=0.048, vol=0.095
  },

+ "scoring_debug": {
+   "log_score_vwap_zero_threshold": true,   # score_vwap=0 时记录原因
+   "assert_weight_sum_tolerance": 0.02,      # 权重加总误差超过 2% 时报警
+ }
```

```python
# macd_strategy_v2.py — 权重加总断言（每次启动时执行）

def _validate_scoring_weights(self, weights: dict) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 0.02:
        self._log_warning(
            f"SCORING WEIGHT SUM = {total:.4f}, expected 1.00. "
            f"Scores will be distorted. Check weight_4h_enhancement fold-in."
        )
    # 在严格模式下抛出异常：
    # raise ConfigError(f"Weight sum {total:.3f} != 1.00")
```

---

### [HIGH-2] VWAP 评分完全失效（score_vwap 恒为 0），VWAP 门控只靠 vwap_score 字段

**影响量化**

```python
# 当前状态：
# weight_vwap = 0.05，但 score_vwap 恒为 0
# → VWAP 对最终 total_score 无贡献
# → 权重浪费 0.05 × 1.15 / 1.15 ≈ 4.3% 的评分空间

# 与此同时，loss 表中：
# 所有亏损 LONG 的 vwap_score = 0.25（刚过门槛）
# vwap_bucket (0.12, 0.25] 对应 WR = 70.37%（26笔中 8 笔亏损）

# 如果 score_vwap 正常工作，vwap_score=0.25 的单子只能贡献：
# score_vwap_effective = 0.25 × 0.05 = 0.0125（极小）
# 即使修复了 score_vwap，对总分影响也有限

# 真正需要的是：
# vwap_score=0.25（低 VWAP 质量）应该触发仓位压缩，而不是评分扣减
# 因为扣减 0.0125 分对是否过阈值几乎没影响，但压缩仓位对亏损金额影响显著

# 建议：VWAP 作为"仓位调节器"而非"评分贡献者"
def vwap_as_position_scaler(vwap_score: float) -> float:
    """
    vwap_score → 仓位系数（不影响 total_score）
    """
    if vwap_score >= 0.50:
        return 1.00     # 强 VWAP 信号，满仓
    elif vwap_score >= 0.25:
        return 0.65     # 中等 VWAP，压仓 35%
    else:
        return 0.40     # 低 VWAP 质量，压仓 60%（或直接 block）
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "vwap_position_scaler": {
+   "enabled": true,
+   "thresholds": [
+     {"min_vwap_score": 0.50, "position_mult": 1.00},
+     {"min_vwap_score": 0.25, "position_mult": 0.65},
+     {"min_vwap_score": 0.12, "position_mult": 0.40},
+     {"min_vwap_score": 0.00, "block": true}
+   ],
+   "comment": "VWAP 作为仓位调节器，而非评分贡献者"
  },

- "weight_vwap": 0.050000,
+ "weight_vwap": 0.000000,   # score_vwap 修复前先清零，改用 position_scaler
```

---

### [MEDIUM-1] score_4h 在 shrink 状态下极低（0.025~0.14），不应允许正常仓位开仓

**证据**

```python
# 运行时样本中 score_4h 的分布
score_4h_by_signal_type = {
    "flip_bullish":       0.150,    # 最大值
    "flip_bearish":       0.150,    # 最大值
    "green_bar_shrinking": 0.025,   # BCHUSDT，极低
    "red_bar_shrinking":   [0.074, 0.107, 0.109, 0.138, 0.144, 0.148],  # 中低
    "green_bar_growing":   0.150,    # 最大值
}

# shrink 类型的 score_4h 为何这么低？
# 推断：4H bar 在收缩时，方向不明确（多空博弈）
# 策略评分给予 shrink 状态较低的方向确信度
# 这是合理设计，但问题是：shrink 状态的单子仍然可以全额开仓

# 举例：BCHUSDT score_4h=0.025（满分 0.40 的 6.25%）
# 但因为 RSI rhythm 高，total=0.641，过了 threshold=0.640
# 以 target_portion=0.010（probe 级别）开了 SHORT
# 这笔最终亏损 -0.044

# shrink 状态下强制 probe 仓位的伪逻辑
SHRINK_SIGNAL_TYPES = {"green_bar_shrinking", "red_bar_shrinking"}
SHRINK_MAX_PORTION  = 0.10    # shrink 信号最多用 10% target_portion

def apply_shrink_position_cap(signal: dict, portion: float) -> float:
    signal_4h = signal.get("signal_4h", "")
    if signal_4h in SHRINK_SIGNAL_TYPES:
        capped = min(portion, SHRINK_MAX_PORTION)
        if capped < portion:
            log_debug(
                f"Shrink signal ({signal_4h}): portion capped "
                f"{portion:.3f} → {capped:.3f}"
            )
        return capped
    return portion
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

+ "signal_type_position_caps": {
+   "green_bar_shrinking": {
+     "max_target_portion": 0.10,
+     "force_probe": true,
+     "comment": "4H 收缩信号方向不明，限制为探针仓位"
+   },
+   "red_bar_shrinking": {
+     "max_target_portion": 0.12,
+     "force_probe": true
+   }
+ }
```

---

### [MEDIUM-2] NO_TRADE regime 下开仓逻辑矛盾

**发现**

```python
# loss 表中有 NO_TRADE regime 的开仓：
no_trade_entries = [
    {"symbol": "TONUSDT",  "regime": "NO_TRADE", "adx": 29.46, "pnl": -0.151},
    {"symbol": "JUPUSDT",  "regime": "NO_TRADE", "adx": 42.35, "pnl": -0.063},
]

# Outcome by Regime 显示：
# NO_TRADE: entries=4, wins=2, losses=2, WR=50%（随机水平）

# 问题：NO_TRADE regime 字面意思是"不应该交易"
# 但系统仍然在这个 regime 下开仓（包括有效仓位条目）
# 这是命名混乱还是逻辑 bug？

# 可能原因：
# A. NO_TRADE 是 ADX 过滤后的标记（低 ADX），但不是硬性阻断
# B. 某些信号类型豁免了 NO_TRADE 阻断
# C. NO_TRADE 的定义与实际使用场景不一致

# JUPUSDT NO_TRADE 下 ADX=42.35——这个 ADX 值明显是趋势（不是低 ADX）
# 矛盾点：ADX=42 不应该是 NO_TRADE regime
# → 说明 regime 分类逻辑可能有 bug

# 建议：
# 1. 如果 NO_TRADE 意为"不开仓"，必须加硬性阻断
# 2. 如果 NO_TRADE 只是信号质量标记，应重命名为 WEAK_SIGNAL
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

+ "regime_entry_guard": {
+   "NO_TRADE": {
+     "allow_entry": false,
+     "comment": "NO_TRADE regime 下禁止所有新开仓"
+   }
+ }

# 或者，如果 NO_TRADE 允许开仓是有意为之：
+ "regime_naming": {
+   "NO_TRADE": "WEAK_SIGNAL",    # 重命名，避免语义歧义
+   "comment": "NO_TRADE 实际允许开仓，改名反映真实行为"
+ }
```

---

### [LOW-1] 微仓位 SHORT 胜率 53.33% — 可保留，但需要独立 SLA 监控

**发现**

```python
# 微仓位 SHORT（target_portion < 0.01）：
# entries=15  wins=8  losses=7  WR=53.33%  PnL=+0.150

# 这个胜率虽然接近随机，但期望值为正（+0.150 USDT across 15 trades）
# 且微仓位的单笔损失极小（avg ≈ 0.01 USDT）

# 但 JUPUSDT 微仓位 SHORT ADX=42，NO_TRADE regime，亏 -0.063
# 说明即使是微仓位，也需要 regime 守门

# 建议：保留微仓位 SHORT，但：
# 1. 排除 NO_TRADE regime（解决矛盾）
# 2. 独立统计，不混入有效仓位的胜率报告
# 3. 设置微仓位月度净 PnL 监控线（如净亏 > -$0.50 则审查）

MICRO_POSITION_MONITORING = {
    "monthly_pnl_floor": -0.50,    # 微仓位月度净亏损上限
    "alert_on_breach":   True,
    "separate_reporting": True,
}
```

---

## 二、回答六个具体问题（基于本版数据）

---

### Q1: 权重加总 1.15 + cap 1.0 是否合理？

**结论：不合理，需要分两步修复。**

```
Step 1（立即）：
  将 weight_4h_enhancement 归零（已确认 fold-in，不应重复计）
  权重和变为 1.05

Step 2（本周内）：
  归一化 1.05 → 1.00，比例如下：
    weight_1h_direction: 0.143  (0.15/1.05)
    weight_4h_direction: 0.381  (0.40/1.05)
    weight_rsi_rhythm:   0.286  (0.30/1.05)
    weight_vwap:         0.000  (改为 position_scaler)
    weight_15m_entry:    0.048  (0.05/1.05)
    weight_volume:       0.095  (0.10/1.05)
  sum = 0.953（vwap 清零后；补偿：把 vwap 的 0.048 加到 rsi_rhythm）

  最终权重建议：
    weight_1h_direction: 0.14
    weight_4h_direction: 0.38
    weight_rsi_rhythm:   0.33  (吸收 vwap 的 5%)
    weight_15m_entry:    0.05
    weight_volume:       0.10
  sum = 1.00 ✓
```

---

### Q2/Q3: 当前阈值 0.64~0.69 是否过低？应该回到 0.75~0.85？

**结论：阈值调整必须在权重归一化之后做，不能先于权重修复。**

```
当前问题的优先级顺序：
  P0: 修复 score_vwap 恒为 0（bug）
  P0: 归一化权重（结构修复）
  P1: flip_bearish TREND 阻断（立即止血）
  P2: 重跑 strict_live_mode 回测，在新权重体系下确认合适阈值
  P3: 阈值调整（基于新权重体系的回测结果）

在当前 1.15 权重 + score_vwap=0 的双重失真下：
  直接把阈值从 0.64 提到 0.75，
  等效于归一化后从 0.557 提到 0.652，
  在 RSI rhythm 已经占 82% 的评分体系下，
  意味着 RSI rhythm 需要从 0.519 提到 ≈ 0.60+
  → 可能导致成交量骤减 50~70%，不是合理路径

正确路径：
  先修复评分体系 → 再校准阈值 → 再看实盘效果
```

---

### Q4: 亏损是否集中在低 VWAP、特定 regime 或 trial 条目？

**结论：亏损集中在三个维度的交叉点，不是单一维度。**

```
交叉点 = VWAP 质量低（0.25）× TREND regime × 高 ADX（>30）× 低 volume（0.033）

具体说：
  - 单独看 VWAP=0.25：WR=70.37%（可以接受）
  - 单独看 TREND regime：WR=65.71%（可以接受）
  - 两者叠加 + ADX>30 + volume 最低档：
    推测 WR 大幅下降（所有 LONG 亏损单都落在这个交叉点）

建议：建立复合条件过滤器
  if (vwap_score <= 0.25
      and volume_score <= 0.033
      and regime == "TREND"
      and adx > 30):
      → 仓位压缩到 0.40 × base_portion（约 0.14）
      → 不做完全阻断（因为 WR 虽低，但不是 0）
```

---

### Q5: 微仓位是否应该单独会计？

**结论：本版数据已验证，分层是必要的且值得长期保留。**

```
清洗效果：
  全量 SHORT WR = 47.37%（容易引发错误结论）
  有效仓位 SHORT WR = 25.00%（真实情况，需要紧急处理）
  微仓位 SHORT WR = 53.33%（尚可，独立监控即可）

建议将 meaningful（target_portion ≥ 0.01）作为主监控视图，
micro_notional 作为辅助视图，归因报告中始终分开展示。
```

---

### Q6: protection-gap 和 active-symbol-cap 是否造成逆向选择？

**结论：有结构性风险，但当前窗口证据不足以确认。**

```
可以确认的：
  - max_active_symbols=3，cap 已满时新信号被丢弃（无论质量高低）
  - 无 priority eviction 机制
  - 当前 MORPHOUSDT 大仓 SHORT 亏 -0.826 占满了一个 slot
    如果此时有高分 LONG 信号进来，会被 cap 挡住

待验证（需要额外日志）：
  - 被 cap 拒绝的信号的平均 score vs 当时活跃仓位的最低 score
  - 如果拒绝信号分数高于最弱活跃仓位 20%+ 的情况 > 20%，
    则需要引入 priority eviction

建议：在日志中新增 "cap_rejected_signal_score" 字段，
下个窗口提供此数据，可以直接给出确定性结论。
```

---

## 三、综合 DIFF（可直接提交）

```diff
# config/trading_config_fund_flow.json

# ── [P0] 权重归一化 ─────────────────────────────────────────────

  "scoring_weights": {
-   "weight_4h_enhancement": 0.100000,
+   "weight_4h_enhancement": 0.000000,

    "weight_1h_direction":   0.150000,   # 后续归一化
    "weight_4h_direction":   0.400000,   # 后续归一化
    "weight_rsi_rhythm":     0.300000,   # 后续归一化
-   "weight_vwap":           0.050000,   # score_vwap 恒为 0，先清零
+   "weight_vwap":           0.000000,
    "weight_15m_entry":      0.050000,
    "weight_volume":         0.100000
  },

# ── [P0] SHORT flip_bearish TREND 阻断 ──────────────────────────

+ "short_entry_guards": {
+   "enabled": true,
+   "flip_bearish": {
+     "block_on_regime":    ["TREND"],
+     "block_on_min_adx":   25,
+     "effective_date":     "2026-05-10"
+   },
+   "rsi_neutral_resume": {
+     "short_enabled":      false
+   }
+ },

# ── [P1] 仓位质量映射 ────────────────────────────────────────────

+ "dynamic_position_sizing": {
+   "enabled": true,
+   "vwap_score_tiers": [
+     {"max": 0.25, "position_mult": 0.60},
+     {"max": 0.50, "position_mult": 0.80},
+     {"max": 9.99, "position_mult": 1.00}
+   ],
+   "volume_score_tiers": [
+     {"max": 0.033, "position_mult": 0.75},
+     {"max": 9.999, "position_mult": 1.00}
+   ],
+   "adx_trend_penalty": {
+     "regime":       "TREND",
+     "min_adx":      40,
+     "position_mult": 0.70
+   }
+ },

# ── [P1] 4H shrink 类型仓位上限 ─────────────────────────────────

+ "signal_type_position_caps": {
+   "green_bar_shrinking": {"max_target_portion": 0.10},
+   "red_bar_shrinking":   {"max_target_portion": 0.12}
+ },

# ── [P2] VWAP 改为仓位调节器 ────────────────────────────────────

+ "vwap_position_scaler": {
+   "enabled": true,
+   "tiers": [
+     {"min_vwap_score": 0.50, "mult": 1.00},
+     {"min_vwap_score": 0.25, "mult": 0.65},
+     {"min_vwap_score": 0.12, "mult": 0.40}
+   ]
+ },

# ── [P2] NO_TRADE regime 入场审查 ───────────────────────────────

+ "regime_entry_policy": {
+   "NO_TRADE": {
+     "allow_meaningful_entry":    false,
+     "allow_micro_notional":      true,
+     "comment": "NO_TRADE 禁止有效仓位开仓，微仓位可保留"
+   }
+ },

# ── [P3] 归因报告分层（已验证，设为默认） ───────────────────────

  "attribution": {
+   "meaningful_threshold":      0.010,
+   "split_meaningful_micro":    true,
+   "primary_view":              "meaningful",
+   "micro_monthly_pnl_floor":  -0.50
  }
```

---

## 四、执行优先级与验收标准

```
优先级  行动                              验收标准
──────────────────────────────────────────────────────────────────
P0-A   flip_bearish TREND 阻断上线       SHORT 有效仓位 WR 从 25% → >60%
P0-B   weight_4h_enhancement 归零        权重加总从 1.15 → 1.05，无其他副作用
P0-C   score_vwap 恒零 bug 诊断          找到归零原因，score_vwap 出现非零值
P1-A   动态仓位压缩                      亏损单平均 portion 下降 30%+
P1-B   rsi_neutral_resume SHORT 关闭    SHORT 亏损笔数减少 2~3 笔/窗口
P2-A   VWAP 改为 position_scaler         vwap_score=0.25 的单子仓位自动压缩到 0.65×
P2-B   NO_TRADE 有效仓位阻断             NO_TRADE 条目从归因中消失
P3     完整权重归一化 + 阈值重校准        strict_live_mode 30天回测 WR≥72%，成交≥55笔
```

```
本窗口最紧急的一个数字：
  有效 SHORT WR = 25%（4笔，3笔亏损）
  这不是统计噪音，是路径设计问题。
  在完成 P0-A 之前，建议手动关闭 SHORT 有效仓位开仓（仅保留微仓位）：

+ "side_enable": {
+   "LONG":  {"meaningful": true,  "micro": true},
+   "SHORT": {"meaningful": false, "micro": true}   # 临时关闭有效 SHORT
+ }
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-10*  
*数据来源: Live Strategy Chain v2，含 meaningful/micro-notional 分层*  
*上版修正: SHORT 有效仓位 WR 非估算的 64%，实际为 25%，结论已全面更新*
