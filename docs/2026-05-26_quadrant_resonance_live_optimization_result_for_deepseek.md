# EMA+MACD+RSI 四象限共振策略实盘优化与回测归因

日期：2026-05-26  
用途：给 DeepSeek 评审开仓象限、权重、风控、出场改造与 100U 实盘部署依据。

## 1. 本轮实盘改动摘要

本轮已将 `config/trading_config_fund_flow.json` 的实盘策略切到 `strategy_mode="quadrant_resonance"`，并按 100U 小资金口径收敛：

- 最大活跃 symbol：`5`
- quadrant 单笔最低名义：`8 USDT`
- 开仓保证金硬门槛：`>=1 USDT`
- quadrant 最大杠杆：`3x`
- 关闭旧小保证金 `9x` 提升对 quadrant 的影响
- VWAP 继续只作为日志/观察字段，不进入 entry、score、portion、risk、sort

重要修复：代码中 `target_portion_of_balance` 实际是保证金比例，因此 `8U` 最低名义必须按 `8 / leverage` 折算为保证金地板。本轮已修正 quadrant sizing 与 risk engine，避免把 8U 名义误当 8U 保证金。

## 2. 开仓象限与评分

允许象限：

| 象限 | 条件 | 方向 | 本轮成交 |
|---|---|---|---|
| Q1 | 4H EMA 多头排列 + MACD 正柱增强 | long | 100U: 96 笔，+21.12U |
| Q2 | 4H EMA 空头排列 + MACD 正柱增强 | 谨慎 long | 0 |
| Q3 | 4H EMA 空头排列 + MACD 负柱增强 | short | 100U: 23 笔，+2.91U |
| Q4 | 4H EMA 多头排列 + MACD 负柱增强 | 谨慎 short | 0 |
| DEFENSE | 4H EMA 无序 | 禁止开仓 | 0 |

评分权重：

| 因子 | 权重 |
|---|---:|
| 4H 象限 | Q1/Q3=0.50，Q2/Q4=0.20 |
| 1H EMA 方向 | 0.20 |
| 1H MACD 连续增强/走弱 | 0.15 |
| 15m 入场形态/MACD 交叉 | 0.10 |
| 15m RSI 健康区间 | 0.05 |
| RSI 背离加分 | 最多 0.10 |

本轮开仓过滤：

- Q1/Q3 标准阈值从 `0.80` 提升至 `0.85`
- `0.85-0.90` 中间分段要求 1H MACD 连续 3 根确认
- 必须有 15m 入场形态或 MACD 交叉
- 4H RSI 极端区对总分扣 `0.05`

结果：本轮优化后所有成交信号均落在 `0.95-1.01` 分桶，低质量 `0.85-0.90` 桶被完全过滤。

## 3. 出场与风控改造

出场改动：

- 止损从 intrabar 影线触发改为 15m 收盘确认，reason=`HARD_STOP_LOSS_CLOSE_CONFIRMED`
- ATR 初始止损从 `1.2 * ATR` 放宽到 `1.5 * ATR`
- TP1 改为 `1.2 * ATR` 平 30%，剩余进入 EMA20 trailing 阶段
- momentum reduce 首次减仓从 50% 降为 25%，二次恶化再减 50%
- 继续保留趋势失效、象限反转、审计字段

实盘风险：

- 单笔风险：权益 1%
- 最大杠杆：quadrant `3x`
- 总敞口：75%
- 日亏损熔断：5%
- 周亏损熔断：12%
- 回撤减仓：10% 触发，5% 恢复
- 新开仓保证金 `<1U` 硬阻断仍生效

## 4. 回测对比

数据实际覆盖：`2026-05-01 00:00:00` 至 `2026-05-24 14:00:00`，28 个 symbol。此前所谓 1y 命令实际只读到这段缓存数据，因此不能当作一年鲁棒性结论。

| 指标 | 旧 quadrant baseline 10000U | 优化后 10000U | 优化后 100U/5仓 |
|---|---:|---:|---:|
| 收益率 | +39.18% | +8.33% | +22.19% |
| Sharpe | 9.39 | 7.41 | 22.06 |
| Profit factor | 1.75 | 6.37 | 9.49 |
| 交易记录数 | 1082 | 216 | 119 |
| Expectancy | +4.96U | +4.25U | +0.202U |
| Exposure | 61.52% | 21.86% | 9.46% |
| 平均 MFE | 0.856% | 0.883% | 0.933% |
| 平均 MAE | -0.294% | -0.189% | -0.195% |
| 最差 5 笔 | -398/-393/-297/-274/-238U | -52/-45/-35/-22/-12U | -1.05/-0.75/-0.44/-0.36/-0.10U |

解释：

- 收益下降是预期内的，因为仓位口径从偏激进修正到 3x 实盘可执行。
- 风险质量显著改善：PF 从 1.75 到 6.37/9.49，MAE 降低，尾部亏损大幅收敛。
- 100U 版本最大回撤仅约 0.87%，比旧 baseline 的 8.32% 更适合小资金实盘试运行。

## 5. Exit Audit 归因

100U 出场统计：

| Exit reason | 笔数 | PnL | stopped_before_followthrough |
|---|---:|---:|---:|
| sim_light_take_profit | 56 | +16.89U | 50/56 |
| TP1_REDUCE_TO_EMA_TRAIL | 46 | +9.39U | 38/46 |
| HARD_STOP_LOSS_CLOSE_CONFIRMED | 7 | -2.74U | 4/7 |
| MOMENTUM_REDUCE | 5 | +0.15U | 2/5 |
| TREND_REDUCE | 5 | +0.34U | 5/5 |

归因：

- 止损亏损已经从 baseline `stop_loss_intrabar -5575U` 改为 100U 下 `close_confirm -2.74U`，假影线止损问题显著缓解。
- 仍有较高 stopped-before-followthrough，主要来自止盈和 TP1 后续仍有空间，说明“让利润奔跑”还有继续优化空间。
- 5-8 bar 和 9+ bar 持仓仍盈利，但单笔均值低于 0-4 bar，说明快速验证层方向正确。

## 6. 100U 实盘注意事项

- trades CSV 中出现少数 `margin < 1U` 记录，均为 `TP1_REDUCE_TO_EMA_TRAIL` 的部分减仓记录，不是新开仓。
- 新开仓仍经过 `min_entry_margin_usdt=1.0`，执行层 `<1U` 会阻断。
- 旧小保证金 9x 自动提升已对 `strategy_mode=quadrant_resonance` 禁用，quadrant 新单保持 3x。
- 顶层 `max_active_symbols=5` 已与 quadrant capacity 对齐。

## 7. 当前结论

本轮不追求最大回测收益，而是把策略从“高收益但仓位/出场假设偏激进”修正成“100U 实盘可执行、低回撤、可审计”的版本。  

可以用于 100U 小资金实盘试运行，但仍有两个限制：

1. 数据窗口只有 2026-05 的局部强趋势行情，不足以证明全年鲁棒。
2. 止盈后续空间仍大，下一轮应继续研究 EMA20 trailing 与 TP1 后 runner 的保留比例。

建议实盘首日严格观察：

- 是否存在新开仓保证金 `<1U`
- 是否有非 quadrant 旧逻辑误触发 9x
- 是否有大量 `TP1_REDUCE_TO_EMA_TRAIL` 后继续同向运行
- 是否触发容量满导致 Q1 高分信号丢失
