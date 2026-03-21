# MACD_MTF_Strategy_V5 改进建议

> 文档用途：基于当前回测结果的策略迭代建议，供专家组讨论  
> 基线版本：`v2_summary_20260320_161501`  
> 当前总收益率：`+2.39%`，最大回撤：`10.63%`

---

## 一、问题诊断

### 1.1 核心矛盾：高胜率 ≠ 正收益

当前 `short_retest_reject` 的根本问题不是胜率低，而是**盈亏不对称**：

| VWAP 状态 | 交易数 | 胜率 | 总盈亏 | 单笔均盈亏 |
| --- | --- | --- | --- | --- |
| `short_dual_pressure` | 41 | 73.2% | +$603.76 | **+$14.72** |
| `short_retest_reject` | 41 | 80.5% | -$109.05 | **-$2.66** |

- `short_retest_reject` 胜率高达 80.5%，但仍是净负贡献
- 说明少数几笔亏损单的绝对亏损金额，超过了全部盈利单的累计盈利
- 这是典型的**尾部风险敞口**问题，不是信号质量问题

### 1.2 问题单特征归纳

从典型亏损样本中可以提取以下规律：

| 特征维度 | 观察结果 |
| --- | --- |
| `signal_score` | 全部 ≥ 0.91，最高 0.9867 |
| `vwap_score` | 集中在 `0.18 ~ 0.19`，属于刚过 `min_vwap_score_for_entry=0.12` 不久 |
| `exit_reason` | 全部为 `stop_loss_intrabar` |
| `BOLL multiplier` | 全部为 `1.2x` |
| 亏损时间段 | 集中在 `2026-02-08 ~ 2026-02-12` |

关键观察：

- **这些单子并非边缘信号被错误放行**，综合分数非常高
- **`vwap_score` 却集中在接近下限的区间（0.18~0.19）**，说明 VWAP 位置并不理想，但综合分被其他高权重项拉高了
- 止损全部触发于 bar 内，说明止损位与 bar 波动幅度不匹配

---

## 二、根本原因分析

### 2.1 `signal_score` 稀释了 `vwap_score` 的否决权

当前权重配置：

```text
weight_1h_direction = 0.50
weight_vwap         = 0.20
weight_15m_entry    = 0.15
weight_volume       = 0.15
```

`1H` 方向占 50%，只要 MACD 方向强，即使 `vwap_score` 只有 0.18（接近最低门槛），综合分仍可轻松过 `0.84` 的 `flip_bearish` 阈值。

**这意味着 VWAP 位置的过滤功能在强方向下实际上是失效的。**

### 2.2 `BOLL=1.2x` 下的 `short_retest_reject` 是结构性假信号

在强趋势（`BOLL=1.2x`）环境中：

- 价格更倾向于**在 VWAP 附近震荡后继续上行**，而不是形成持续空头
- `short_retest_reject` 的逻辑是"回踩 VWAP 失败后空"，但在强结构下，"失败"可能只是短暂假突破，随后价格依然回头上扬
- 这类环境中，VWAP 作为空头压力参考的可靠性显著下降

### 2.3 止损模型未做状态区分

当前止损统一使用：

```text
use_dynamic_stop = true
boll_stop_atr_multiplier = 0.5
max_stop_loss_pct = 2.5%
```

`BOLL=1.2x` 环境下，ATR 本身较大，`0.5x ATR` 的止损可能远小于该环境的正常波动幅度，导致被轻易打出。

---

## 三、改进建议

### 建议 A：对 `short_retest_reject` 实施状态级独立管理（优先级：最高）

**核心思路**：将 `short_retest_reject` 与 `short_dual_pressure` 彻底分开管理，不再共用入场阈值和风控参数。

#### A1：提升 `short_retest_reject` 的入场门槛

```json
"flip_bearish_retest_reject_min_signal_score": 0.93,
"flip_bearish_retest_reject_min_vwap_score": 0.25
```

- 当前 `min_vwap_score_for_entry = 0.12`，亏损单的 `vwap_score` 集中在 0.18~0.19
- 将 `short_retest_reject` 子类的 `vwap_score` 下限单独提高到 `0.25`
- 这将直接过滤掉全部 5 笔典型亏损单，且不影响 `short_dual_pressure`

#### A2：调整评分权重或引入子类否决机制

方案一（权重调整）：

```json
// 仅对 short_retest_reject 生效的子权重
"retest_reject_weight_vwap": 0.35,
"retest_reject_weight_1h_direction": 0.35
```

- 降低方向权重，提高 VWAP 位置的话语权
- 使 VWAP 位置差时综合分更难通过门槛

方案二（硬否决）：

```python
if vwap_state == "short_retest_reject" and vwap_score < 0.25:
    return blocked  # 直接否决，不进入综合评分
```

- 更简洁，逻辑更清晰
- 推荐作为首选实现方式

---

### 建议 B：限制 `BOLL=1.2x + short_retest_reject` 组合（优先级：高）

**核心思路**：在强趋势结构下，禁止或严格限制 `short_retest_reject` 类型信号。

#### B1：直接禁止该组合

```json
"block_strong_boll_retest_reject": true
```

- 逻辑：`BOLL=1.2x` 说明趋势偏强，此时做空"回踩失败"本质上是逆强趋势
- 实测中 78 笔 `BOLL=1.2x` 交易，盈亏结构的核心拖累正是这个组合
- 禁止后预计保留全部 `short_dual_pressure` 收益，剔除大部分 `short_retest_reject` 问题单

#### B2：如不想直接禁止，至少降低杠杆

```json
"flip_bearish_retest_reject_boll_12_max_leverage": 2
```

- 现有杠杆 3x，建议降至 2x
- 单笔最大止损从约 $104 级别降至约 $69

---

### 建议 C：止损模型状态化（优先级：中）

**核心思路**：根据 VWAP 状态使用不同的止损策略，而不是统一的 ATR 模型。

#### C1：`short_retest_reject` 使用更紧的固定止损上限

```json
"retest_reject_max_stop_loss_pct": 0.015
```

- 当前最大止损 2.5%，建议 `short_retest_reject` 单独设为 1.5%
- 与其用宽止损等待结构恢复，不如用窄止损快速止损再找机会

#### C2：提高 break-even 触发速度

```json
"retest_reject_breakeven_trigger_pct": 0.20,
"retest_reject_breakeven_lock_pct": 0.08
```

- 当前 break-even 触发 0.30%，可对 `short_retest_reject` 收紧至 0.20%
- 使一旦有盈利就更快锁定，减少被反转吃掉的概率

---

### 建议 D：增加 `short_dual_pressure` 仓位弹性（优先级：中）

当前问题是"拖累项"和"贡献项"用了相同的仓位规则。

```json
"dual_pressure_target_portion_bonus": 0.15,
"dual_pressure_max_leverage": 4
```

- `short_dual_pressure` 表现更稳定（+$603.76），应允许更大的仓位暴露
- 在总仓位上限不变的前提下，优先向 `dual_pressure` 信号倾斜
- 可通过信号评分 -> 仓位映射表实现，而不是固定比例

---

### 建议 E：增加时段过滤（优先级：低，可作为验证项）

从亏损样本的时间戳观察：

```text
2026-02-08 15:30 ~ 16:15（多笔）
2026-02-12 15:15
2026-02-10 18:30
```

- 集中在 UTC 15:00 ~ 19:00，对应美股盘前/开盘初期
- 该时段流动性剧烈，VWAP 参考稳定性下降
- 建议验证：是否应对 `short_retest_reject` 信号在 UTC 14:30 ~ 16:30 设置冷却窗口

---

## 四、建议执行优先级

| 优先级 | 建议 | 预期影响 | 实现难度 |
| --- | --- | --- | --- |
| 🔴 最高 | A2：对 `short_retest_reject` 引入 `vwap_score` 硬否决（≥0.25） | 直接过滤 5 笔大亏单 | 低 |
| 🔴 最高 | B1：禁止 `BOLL=1.2x + short_retest_reject` | 大幅改善 `short_retest_reject` 贡献 | 低 |
| 🟠 高 | C1：`short_retest_reject` 独立止损上限（1.5%） | 控制单笔最大亏损 | 低 |
| 🟠 高 | C2：提高 break-even 触发速度 | 减少反转损失 | 低 |
| 🟡 中 | D：`short_dual_pressure` 仓位弹性提升 | 放大盈利贡献 | 中 |
| 🟢 低 | E：时段冷却窗口验证 | 辅助过滤，待验证 | 低 |

---

## 五、预期效果估算

以当前基线为参考：

| 场景 | 操作 | 预计总盈亏变化 |
| --- | --- | --- |
| 仅执行 A2 | 过滤 `vwap_score < 0.25` 的 `retest_reject` 单 | `short_retest_reject` 净亏 $109 -> 预计转正或接近 0 |
| A2 + B1 | 强结构下彻底禁止 `retest_reject` | 损失部分 `retest_reject` 盈利单，但净效果大概率为正 |
| A2 + B1 + C1 | 加止损收紧 | 进一步降低回撤，总收益率预计提升至 3%~5% |
| 全部执行 | A + B + C + D | 总收益率目标 4%~7%，回撤有望控制在 8% 以内 |

> 注：以上为基于历史回测的方向性估算，实际回测结果需跑完后确认。

---

## 六、不建议做的方向

| 方向 | 原因 |
| --- | --- |
| 统一收紧 `short_retest_reject` 回踩定义 | 已验证无效（只删除了 `BOLL=1.0` 盈利单） |
| 替换 BOLL -> EMA 或其他结构层 | 切换后整体已从负转正，框架本身方向正确 |
| 大幅调整 `flip_bearish` 全局阈值 | 问题集中在子状态，全局调整会误伤 `dual_pressure` |
| 增加更多信号类型（`flip_bullish` 等） | 当前规模下问题未解决前不应扩展 |

---

## 七、建议下一步回测验证顺序

1. **先单独验证 A2**（`vwap_score` 硬否决）：观察 `short_retest_reject` 净盈亏变化，交易数损失是否可接受
2. **再验证 B1**（禁止强结构 `retest_reject`）：比较禁止前后的信号数量和盈亏结构
3. **同步验证 C1 + C2**：在保留的 `short_retest_reject` 上验证止损状态化效果
4. **最后验证 D**：在以上稳定后，再测试 `dual_pressure` 仓位弹性的增益

---

*文档版本：V5-建议稿 / 日期：2026-03-20*
