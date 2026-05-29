# MACD V2 / QuadrantResonance 策略评审建议

> **文档用途**：针对 `2026-05-27 20:00 BJT` 起未开仓路径排查报告，提供系统性评审意见与改造方案。
> **覆盖范围**：设计逻辑评审、BUG 定性、修改方案选型、回测设计、审计增强。

---

## 目录

1. [核心问题定性](#1-核心问题定性)
2. [require_15m_entry_pattern 评审](#2-require_15m_entry_pattern-评审)
3. [probe_floor_rescue 与策略层的冲突分析](#3-probe_floor_rescue-与策略层的冲突分析)
4. [对高分缺形态场景的三种处理方案](#4-对高分缺形态场景的三种处理方案)
5. [修改点选型建议](#5-修改点选型建议)
6. [审计字段增强方案](#6-审计字段增强方案)
7. [回测设计建议](#7-回测设计建议)
8. [配置参数评审清单](#8-配置参数评审清单)
9. [优先级与实施路线图](#9-优先级与实施路线图)
10. [附：评审问题逐条作答](#10-附评审问题逐条作答)

---

## 1. 核心问题定性

### 1.1 不是执行层 BUG，是策略设计决策问题

排查报告已经清晰排除了以下执行层干扰项：

| 排除项 | 证据 |
|---|---|
| 交易所拒单 | `execution.status` 全为 `noop`，无 API 错误日志 |
| 余额不足 | `order_nonnull=0`，从未进入下单路径 |
| signal_pool 阻断 | `signal_pool.enabled=false`，未出现在阻断原因分布 |
| min_open_portion 阻断 | 发生在 BUY/SELL 之后，当前决策已在上游变为 HOLD |
| 运行时异常 | 仅有 deprecated config warning，无 traceback |

因此，问题完全发生在 **策略决策层**，属于 `quadrant_resonance.py` 与 `decision_engine.py` 的逻辑设计问题，不是执行路径的工程 BUG。

### 1.2 问题的核心矛盾

系统存在两个相互冲突的设计意图，且二者都被"配置启用"，但在代码执行顺序上存在结构性矛盾：

```
意图 A（当前生效）：require_15m_entry_pattern=true
  → 15m 形态是硬门槛，任何信号缺失即 HOLD
  → 高分信号也不例外
  → probe_floor_rescue 永远无法介入

意图 B（配置存在但实际失效）：probe_floor_rescue.enabled=true
  → 低仓位 probe 应该在高分但形态不完整时作为兜底
  → 设计上用于捕捉"差一点就成立"的机会
  → shadow_mode=true 说明曾经刻意关闭实际影响
```

这两个意图在代码中无法同时生效，**当前是意图 A 完全压制意图 B**。这是一个需要团队评审的 **设计决策点**，而非单纯的代码错误。

### 1.3 数据佐证的严重程度

| 指标 | 数值 | 含义 |
|---|---|---|
| 窗口内总决策数 | 1400 | 全部为 hold |
| `score >= threshold` 但 hold | 212 条（pre_execution） | 高质量信号被硬拒 |
| `score >= 0.8` 且 missing_15m | 238 条（attribution） | 高分场景约占 17% |
| 最近成交时间 | 2026-05-25 13:15:15 UTC | 距排查窗口约 55 小时无成交 |

212 条高分被硬拒的记录，意味着系统在 13 小时内约有 **每小时 16 次** 高分信号被 15m 门槛提前终止。这不是偶发现象，是系统性的策略过滤。

---

## 2. `require_15m_entry_pattern` 评审

### 2.1 该参数的设计初衷（推断）

从配置结构和代码逻辑推断，`require_15m_entry_pattern` 的原始设计意图应为：

> 防止在 1h/4h 维度共振成立但 15m 尚未出现精确入场时机时过早进场，避免"方向对但时机差"的高滑点开仓。

这个设计意图本身是合理的。15m 维度的精确形态（MACD hist 金叉 + near_ema，或 pin bar）确实能显著改善入场点位，减少最大回撤和初始浮亏。

### 2.2 当前实现的问题

问题不在于该参数的 **存在**，而在于它的 **介入时机和介入方式**：

```python
# quadrant_resonance.py 第 219-233 行（当前逻辑）
if self.config.require_15m_entry_pattern and "entry_15m" not in factor_scores:
    return QuadrantSignal(
        allowed=False,
        reason="missing_15m_entry_pattern",
        ...
    )
```

**问题一：在分数计算完成后才判断，但判断结果无视分数**

代码在 `score = sum(factor_scores.values())` 之后才检查 `entry_15m`，但拒绝逻辑完全忽略了 `score` 的值。这意味着：
- `score=0.91`（远超 `threshold=0.85`）与 `score=0.86`（刚过门槛）在 15m 形态缺失时完全等价，都返回 `allowed=False`。
- 高分信号的额外信息价值被完全丢弃。

**问题二：`allowed=False` 语义过于强硬**

`allowed=False` 在 `decision_engine.py` 中被直接映射为 `operation=HOLD`，没有中间状态。这种二元设计使得任何"部分满足条件"的场景都无法被精细化处理。

**问题三：该检查阻断了所有后续机制**

`probe_floor_rescue`、最小仓位保护等机制都在 `BUY/SELL` 决策之后才介入。`allowed=False → HOLD` 的转换发生在最上游，导致这些兜底机制永远没有机会执行。

### 2.3 `_entry_pattern_ok()` 的条件窗口分析

```python
# 当前条件（简化）：
# LONG：15m MACD hist 由 <=0 穿越到 >0 AND near_ema
# SHORT：15m MACD hist 由 >=0 穿越到 <0 AND near_ema
# 其他：near_ema AND (方向 candle OR pin bar)
```

`near_ema` 的条件是 `|close - ema20| <= atr`，这在趋势行情中会长期不成立（价格远离均线）。MACD hist 穿越要求是严格的金叉/死叉，在震荡行情中频繁发生，但在单边趋势的中段往往很少出现。

**结论**：当前的 15m 形态条件在趋势行情中尤为严苛，恰恰是市场给出高 resonance score 的情形（因为 1h/4h 动量强），条件窗口反而最窄。

---

## 3. `probe_floor_rescue` 与策略层的冲突分析

### 3.1 设计意图的层次错位

`probe_floor_rescue` 的设计意图是作为 **执行层** 的兜底机制：当策略层给出 BUY/SELL 但计算出的 `target_portion_of_balance` 极小（低于 `min_open_portion`）时，将其提升到最小可执行仓位（`probe_portion=0.06`）。

但当前用户的预期似乎是：高分但缺 15m 形态时，probe 应该作为 **策略层** 的补偿机制，即"策略不确定但分数高，用小仓位试探"。

这两个用法存在 **概念层次的错位**：

| 维度 | probe_floor_rescue 当前设计 | 用户预期用法 |
|---|---|---|
| 触发层次 | 执行层（target 过小） | 策略层（形态不完整） |
| 前置条件 | decision 已经是 BUY/SELL | decision 仍然是 HOLD |
| 本质 | 仓位下限保护 | 形态替代方案 |

### 3.2 `shadow_mode=true` 的额外问题

当前 `probe_floor_rescue.shadow_mode=true`，即使进入该分支，也只记录日志、不实际修改 `target_portion_of_balance`。这意味着即使修复了策略层的拦截问题，probe 仍然不会实际开仓。

`shadow_mode` 的存在说明该功能曾被刻意设为"只观察不执行"的验证阶段。在评审中需要明确：
1. shadow_mode 的验证期是否结束？
2. 是否有足够的 shadow 日志来评估 probe 的效果？
3. 是否应在修复策略层拦截之前先分析已有的 shadow 记录？

### 3.3 小结

当前 `probe_floor_rescue` 对"高分缺形态"场景 **完全无效**，原因是双重失效：
1. 策略层提前返回 HOLD，probe 永远无法触发；
2. 即使触发，shadow_mode 也不会实际执行。

---

## 4. 对高分缺形态场景的三种处理方案

以下三种方案针对 `score >= threshold AND missing_15m_entry_pattern` 的场景，提供不同的设计选择。

---

### 方案 A：维持硬门槛，增加诊断细分（最保守）

**核心思路**：不改变交易逻辑，仅改善审计质量。

**改动点**：

1. 在 `_entry_pattern_ok()` 返回 `False` 时，同时返回失败子条件集合：

```python
def _entry_pattern_ok(self, direction, tf15) -> tuple[bool, dict]:
    detail = {
        "near_ema": near_ema,
        "hist_cross": hist_cross,
        "close": close,
        "ema20": ema20,
        "atr": atr,
        "bullish_candle": bullish,
        "pin_bar": pin_bar,
    }
    ok = (near_ema and hist_cross) or (near_ema and bullish) or (near_ema and pin_bar)
    return ok, detail
```

2. 在 `QuadrantSignal` 的 `metadata` 中写入 `entry_15m_detail`：

```python
return QuadrantSignal(
    allowed=False,
    reason="missing_15m_entry_pattern",
    metadata={
        **metadata,
        "entry_15m_detail": entry_detail,
        "score": score,
        "threshold": threshold,
    }
)
```

3. 在 `entry_exit_audit` 中将 `entry_15m_detail` 展开写入。

**优点**：零风险，不改变任何交易行为，仅改善排查能力。
**缺点**：不解决高分信号被浪费的问题。
**适用场景**：当前确实认为 15m 形态是必要条件，只是排查成本太高。

---

### 方案 B：分数分层宽松（推荐评审）

**核心思路**：对 `score` 超过高分门槛（如 `>= 0.90` 或超出 `threshold` 一定余量）的信号，降级为小仓位 BUY/SELL 而非 HOLD，同时在 reason 中标注来源。

**改动点**：在 `QuadrantResonanceEngine.analyze()` 中：

```python
if self.config.require_15m_entry_pattern and "entry_15m" not in factor_scores:
    # 新增：高分豁免路径
    high_score_override = (
        self.config.get("high_score_15m_override", False) and
        score >= self.config.get("high_score_15m_override_threshold", 0.92)
    )
    if not high_score_override:
        return QuadrantSignal(
            allowed=False,
            reason="missing_15m_entry_pattern",
            metadata=metadata,
        )
    else:
        # 允许通过，但标注为降级信号，由 DecisionEngine 压缩仓位
        metadata["signal_quality"] = "degraded_no_15m"
        metadata["override_reason"] = "high_score_override"
```

在 `DecisionEngine` 中：

```python
if signal.metadata.get("signal_quality") == "degraded_no_15m":
    # 使用 probe_portion 而非常规 target_portion
    decision.target_portion_of_balance = self.config.probe_floor_rescue.probe_portion
    decision.reason = "high_score_probe_no_15m"
```

**关键配置参数**（新增）：

```json
"high_score_15m_override": true,
"high_score_15m_override_threshold": 0.92,
"high_score_probe_portion": 0.04
```

**优点**：
- 保留大部分场景的 15m 硬门槛保护；
- 仅对极高分信号开放，减少过拟合风险；
- 语义清晰，审计中可区分常规开仓和 probe 开仓；
- 不需要改动 `probe_floor_rescue` 的执行层逻辑。

**缺点**：
- 引入新参数，增加调参复杂度；
- 需要回测验证 `0.92` 阈值的效果；
- `signal_quality=degraded` 的语义需要在所有下游消费方（风控、仓位管理）中同步处理。

---

### 方案 C：在 `DecisionEngine` 层拦截并转换（最小侵入）

**核心思路**：不修改 `QuadrantResonanceEngine`，在 `DecisionEngine` 接收到 `allowed=False AND reason=missing_15m_entry_pattern` 时，检查 `score`，决定是否将其转为 probe decision。

**改动点**：

```python
# decision_engine.py 第 5690 行附近
if not signal.allowed:
    # 新增：高分 missing_15m 转 probe
    if (
        signal.reason == "missing_15m_entry_pattern" and
        signal.metadata.get("score", 0) >= self.config.get("probe_missing_15m_score_floor", 0.92) and
        self.config.get("probe_missing_15m_enabled", False)
    ):
        decision = FundFlowDecision(
            operation=Operation.BUY if direction == "long" else Operation.SELL,
            target_portion_of_balance=self.config.probe_floor_rescue.probe_portion,
            reason="probe_missing_15m_high_score",
            metadata={**metadata, "probe_source": "missing_15m_override"},
        )
        return decision

    # 原有逻辑
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        reason=signal.reason,
        metadata=metadata,
    )
    return decision
```

**优点**：
- 改动集中，不触碰策略引擎；
- 可以精确控制转换条件；
- 回滚简单，只需 `probe_missing_15m_enabled=false`。

**缺点**：
- `DecisionEngine` 开始承载策略语义，职责边界模糊；
- 依赖 `signal.metadata["score"]` 已被正确传递（需验证）；
- 不如方案 B 在信号层面表达清晰。

---

## 5. 修改点选型建议

### 5.1 短期（本周内）

**建议优先执行方案 A**，无论最终选择 B 或 C，方案 A 的审计增强都应先行：

- 原因：当前审计不足使得任何方案的 A/B 测试都难以精确评估。
- 具体做法见 [第 6 节](#6-审计字段增强方案)。
- 代码改动量小，仅在 `_entry_pattern_ok` 和 `QuadrantSignal` 初始化处修改，不影响任何决策逻辑。

### 5.2 中期（本月内）

建议在以下前提下评审是否实施方案 B 或 C：

**前提 1**：确认 `probe_floor_rescue.shadow_mode` 已有足够积累的观察数据，可以评估 probe 的历史效果。

**前提 2**：对 `score >= 0.90 AND missing_15m_entry_pattern` 的 212 条记录进行 **事后回测**：
- 这些信号在进入时间点后的 K 线走势如何？
- 如果当时开了小仓位，平均回报如何？
- 这是评估 15m 门槛"价值"的最直接证据。

**前提 3**：明确 `require_15m_entry_pattern=true` 的原始设计意图，以及是否存在历史数据支持该参数有效的结论。

### 5.3 选型矩阵

| 方案 | 交易行为改变 | 代码改动量 | 回滚难度 | 推荐场景 |
|---|---|---|---|---|
| A | 无 | 小 | 极低 | 立即执行，与 B/C 并行 |
| B | 有（新增 probe 路径） | 中 | 低（配置关闭） | 已有历史 shadow 数据支持 |
| C | 有（新增 probe 路径） | 小 | 低（配置关闭） | 希望最小改动但快速验证 |

---

## 6. 审计字段增强方案

### 6.1 `entry_15m_detail` 字段设计

在 `fund_flow_entry_exit_audit.jsonl` 的 `pre_execution` 记录中，新增以下字段：

```json
{
  "ts": "2026-05-27T20:15:06+08:00",
  "stage": "pre_execution",
  "symbol": "ADAUSDT",
  "signal": {
    "score": 0.90,
    "threshold": 0.85,
    "direction": "long"
  },
  "reason": "missing_15m_entry_pattern",
  "entry_15m_detail": {
    "near_ema": false,
    "hist_cross": false,
    "close": 0.3821,
    "ema20": 0.3756,
    "atr": 0.0031,
    "ema_distance_atr_ratio": 2.10,
    "bullish_candle": true,
    "pin_bar": false,
    "hist_current": 0.00012,
    "hist_prev": 0.00008,
    "hist_cross_direction": "none"
  }
}
```

`ema_distance_atr_ratio` 尤为有价值：如果该值持续 > 1.5，说明市场处于趋势拉伸期，`near_ema` 条件的苛刻程度在此时远超震荡期。

### 6.2 `factor_scores` 完整展示

当前 `factor_scores` 不出现在 `runtime summary` 中。建议在 `attribution` 日志中，至少对 `operation=hold AND reason=missing_15m_entry_pattern` 的记录，写入：

```json
"factor_scores_partial": {
  "quadrant": 0.15,
  "direction_ema": 0.20,
  "macd_1h": 0.25,
  "volume_flow": 0.15,
  "entry_15m": null
}
```

这样可以判断分数高来自哪些因子，评估高分信号的质量结构。

### 6.3 `quadrant_defense` 子条件诊断

排查报告中 `quadrant_defense_no_entry` 有 627 条，是第二大阻断原因。建议对此也增加子条件写入，例如：

```json
"quadrant_defense_detail": {
  "defense_level": "strong",
  "opposing_volume_ratio": 1.45,
  "defense_threshold": 1.2
}
```

### 6.4 审计增强的实施原则

- **不改变任何决策逻辑**，仅在 `QuadrantSignal` metadata 和 audit writer 中增加字段；
- 对性能敏感路径（高频调用的 analyze()），新增字段的构造应在 `allowed=False` 分支内进行，不影响正常路径；
- 增强字段写入应有配置开关 `"audit_entry_15m_detail": true`，支持在生产中逐步启用。

---

## 7. 回测设计建议

### 7.1 回测目标

评估以下三种策略配置在相同历史数据上的表现差异：

| 配置 | `require_15m_entry_pattern` | 高分 probe | 说明 |
|---|---|---|---|
| Baseline（当前） | `true` | 无 | 完全硬门槛 |
| Treatment-1 | `true` | score >= 0.92 时 probe | 方案 B/C |
| Treatment-2 | `false` | 无 | 完全移除 15m 门槛 |

### 7.2 避免的常见错误

**错误一：使用同 bar 成交假设**

任何回测不得假设以信号产生 bar 的 open/close 价成交。最低要求是以 **下一 bar 的 open 价** 成交，并加入合理的滑点估计（根据标的流动性，建议 15-30 bps）。

**错误二：使用未来函数**

`_entry_pattern_ok()` 中的 MACD hist 穿越条件，在历史数据回测时必须确认使用的是 **已关闭 bar** 的数据。如果使用了当前未关闭 bar 的数据，会导致回测结果严重高估。

建议在回测框架中增加 `bar_finalized` 标志检查：

```python
assert tf15.bar_finalized, "回测不得使用未关闭 bar 的 MACD 数据"
```

**错误三：过拟合 `high_score_15m_override_threshold`**

如果选择方案 B 或 C，`0.92` 这个阈值不应通过在同一数据集上穷举来选取。建议：
1. 使用 2025 年全年数据作为训练集确定阈值；
2. 用 2026 年 1-4 月数据作为验证集；
3. 5 月后数据作为测试集（包含本次问题窗口）。

### 7.3 关键回测指标

| 指标 | 含义 | 目标方向 |
|---|---|---|
| 胜率（Win Rate） | 盈利交易 / 总交易 | 维持或提升 |
| 盈亏比（PnL Ratio） | 平均盈利 / 平均亏损 | 不显著下降 |
| 最大回撤（Max DD） | 峰值到谷值的最大跌幅 | 不显著上升 |
| 信号利用率 | 实际开仓 / 高分信号总数 | Treatment > Baseline |
| probe 成功率 | probe 开仓后盈利比例 | 需 > 50% 才有统计意义 |
| 持仓平均时长 | 入场到出场的 bar 数 | 监控是否改变持仓特性 |

### 7.4 对 212 条已有记录的事后分析

在实施任何修改之前，建议对排查窗口内的 212 条 `score >= threshold AND missing_15m_entry_pattern` 记录做 **被动事后分析**：

```python
# 伪代码：事后分析框架
for record in high_score_missing_15m_records:
    entry_price = record.close_at_signal_time
    future_bars = get_klines_after(record.symbol, record.ts, n=20)
    pnl_1h = (future_bars[4].close - entry_price) / entry_price * direction_sign
    pnl_4h = (future_bars[16].close - entry_price) / entry_price * direction_sign
    record["hypothetical_pnl_1h"] = pnl_1h
    record["hypothetical_pnl_4h"] = pnl_4h
```

这个分析不需要改动任何代码，只需要将已有的 audit 记录与后续行情数据 join 即可。结果将直接回答："如果当时开了小仓，结果怎样？"

---

## 8. 配置参数评审清单

### 8.1 需要明确意图的参数

| 参数 | 当前值 | 评审问题 |
|---|---|---|
| `require_15m_entry_pattern` | `true` | 是否应在高分时豁免？ |
| `probe_floor_rescue.shadow_mode` | `true` | shadow 期是否结束？ |
| `probe_floor_rescue.enabled` | `true` | 与 shadow_mode 并存的意义？ |
| `mid_score_requires_3bar_macd` | `true` | 中分场景是否也过于严格？ |
| `standard_threshold` | `0.85` | 是否因 15m 门槛而实际阈值虚高？ |
| `probe_portion` | `0.06` | probe 开仓比例是否合适？ |

### 8.2 `probe_floor_rescue.shadow_mode=true` 的处理建议

在明确修改方向之前，建议先 **提取现有 shadow 日志**，分析：
- shadow_mode 下 probe 的触发频率；
- 如果 probe 实际执行，预期的 target_portion 分布；
- shadow probe 与后续行情的假设 PnL。

这些数据将为是否关闭 shadow_mode 提供直接证据，而无需重新跑回测。

### 8.3 阈值一致性检查

注意到：

```json
"standard_threshold": 0.85,
"transition_threshold": 0.85,
"probe_floor_rescue.min_score_threshold": 0.80
```

`probe_floor_rescue` 的分数门槛（0.80）低于 `standard_threshold`（0.85），这意味着设计上 probe 可以在低于标准门槛的信号上触发。但由于当前 probe 只处理 BUY/SELL，而 0.80 分的信号也会因 `resonance_score_below_threshold` 被 HOLD（窗口内有 5 条此类记录），这个阈值设定目前也是无效的。

建议统一梳理所有阈值的层次关系：

```
resonance_score_below_threshold (0.85) → HOLD（完全排除）
score in [0.80, 0.85) → 应该是什么行为？
score in [0.85, 0.92) + missing_15m → 当前 HOLD，是否改为 probe？
score >= 0.92 + missing_15m → 是否 probe？
```

---

## 9. 优先级与实施路线图

### 阶段一：诊断增强（立即，1-2 天）

- [ ] 实施方案 A：`_entry_pattern_ok()` 返回子条件 detail
- [ ] 更新 `QuadrantSignal` metadata 包含 `entry_15m_detail`
- [ ] 更新 `entry_exit_audit` writer 展开 detail 字段
- [ ] 配置开关：`audit_entry_15m_detail: true`
- [ ] 提取现有 `probe_floor_rescue` shadow 日志，生成统计报告

### 阶段二：数据分析（1 周内）

- [ ] 对 212 条 `score >= threshold AND missing_15m` 记录做事后 PnL 分析
- [ ] 分析 `entry_15m_detail` 字段中失败子条件的分布（`near_ema` 失败 vs `hist_cross` 失败）
- [ ] 分析 `ema_distance_atr_ratio` 与 15m 形态成功率的相关性
- [ ] 评审 `quadrant_defense_no_entry`（627 条）的子条件分布

### 阶段三：方案选型与实施（2-3 周内）

- [ ] 基于阶段二数据，决策采用方案 B 或方案 C
- [ ] 设计回测框架，验证历史 2025 全年数据
- [ ] 实施代码修改，配置新参数，初始以 `shadow_mode` 运行
- [ ] 持续观察 2 周后评估是否关闭 shadow_mode

### 阶段四：参数优化（持续）

- [ ] 基于实盘 shadow 数据调整 `high_score_15m_override_threshold`
- [ ] 评估 `probe_portion` 是否需要与信号分数挂钩（越高分，probe 比例越大）
- [ ] 将 15m 形态细分条件纳入 factor_scores 计划（`near_ema_bonus`, `hist_cross_bonus`），使其成为加分项而非硬门槛

---

## 10. 附：评审问题逐条作答

### 问题 1：`require_15m_entry_pattern` 是否过于硬，是否与 `probe_floor_rescue` 设计目标冲突？

**是，存在设计层面的冲突。**

`require_15m_entry_pattern=true` 的"一票否决"语义，与 `probe_floor_rescue` 的"低仓位兜底"设计目标存在根本性冲突。前者在策略层完全终止信号传递，后者在执行层期望接收到 BUY/SELL 决策后才能介入。两者在代码执行顺序上无法同时生效。

建议重新定义 `require_15m_entry_pattern` 为"降级门槛"而非"拒绝门槛"：当 15m 形态缺失时，信号仍可通过，但 `target_portion_of_balance` 自动降至 probe 级别，而非直接变为 HOLD。

---

### 问题 2：高分缺 `entry_15m` 场景，应继续 HOLD 还是允许极小 probe？

**建议允许极小 probe，但需满足以下前提：**

1. 事后分析（第 7.4 节）显示这类信号的假设 PnL 为正；
2. `probe_floor_rescue.shadow_mode` 已积累足够 shadow 数据；
3. probe 比例不超过总余额的 6%（当前 `probe_portion` 配置值）；
4. 需配置独立的开关和阈值，不影响现有的正常信号路径。

如果事后分析显示这类信号的假设 PnL 为负或接近零，那么维持 HOLD 是合理的，问题只是排查成本过高（由方案 A 解决）。

---

### 问题 3：若允许 probe，应修改 `QuadrantResonanceEngine` 还是 `DecisionEngine`？

**推荐修改 `QuadrantResonanceEngine`（方案 B），理由如下：**

1. **语义清晰**：信号质量的降级应在信号生成层表达，`DecisionEngine` 应消费信号而非推断信号语义；
2. **可测试性**：`QuadrantResonanceEngine.analyze()` 有明确的输入输出，单元测试更容易覆盖；
3. **审计完整性**：在 `QuadrantSignal` 中直接携带 `signal_quality=degraded_no_15m`，下游所有消费方（审计、风控、仓位管理）都能感知；
4. **向后兼容**：通过 `high_score_15m_override: false` 默认关闭，不影响当前行为。

方案 C（在 `DecisionEngine` 拦截）适合快速验证，但长期维护成本较高，因为 `DecisionEngine` 已经很复杂（第 5680+ 行），继续在此添加策略语义会增加认知负担。

---

### 问题 4：不引入未来函数、同 bar 成交假设、过拟合参数，如何回测三种配置？

**回测设计建议（完整版见第 7 节），核心原则如下：**

**防止未来函数**：所有 `_entry_pattern_ok()` 中使用的 MACD hist 值，必须来自已关闭 bar。回测框架应在信号生成时记录 `bar_index` 和 `bar_finalized` 标志，并在事后审查时验证。

**防止同 bar 成交**：以 **信号产生 bar 的下一 bar open 价** 作为成交价，加入 15-30 bps 固定滑点。

**防止过拟合**：
- 时间分段：训练/验证/测试 = 2025 全年 / 2026 Q1 / 2026 Q2；
- 参数选取：`high_score_15m_override_threshold` 只在训练集上选取，在验证集上确认，测试集只跑一次；
- 对比基准：三种配置使用完全相同的回测框架、数据、成本假设，差异仅在配置参数。

**三种配置的比较重点**：
- Baseline vs Treatment-1：probe 的增量贡献是否正向；
- Treatment-1 vs Treatment-2：15m 门槛的保护价值有多少；
- 重点观察 Treatment-2 的最大回撤，这将定量说明 15m 门槛对风险的控制价值。

---

*本文档基于排查报告截至 `2026-05-28 09:15:15 BJT` 的日志数据，建议在实施任何修改前结合最新数据复核上述分析。*
