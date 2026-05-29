# 2026-05-15 UTC 01:00 后开仓方向亏损归因

## 结论

这次不是执行层把 buy/sell 翻反，而是策略层把一批“方向语义正确但环境不成立”的 MACD_V2 多头信号放进了实盘。

我的严重错误是：昨天围绕“开仓方向/减少漏单”的优化，把注意力放在释放被门控挡住的候选上，却没有把“释放以后是否会在当前真实行情中反向亏损”作为硬验收条件。结果是配置和代码同时放宽了多个入场保护，今天 UTC 01:00 后一批 `macd_v2_long_1h_red_bar_*` / `flip_bearish` 路径被允许开多，市场继续下跌，ExitGuard/止损随后亏损平仓。

## 事实证据

日志范围：

- `logs/2026-05/2026-05-15/fund_flow_attribution.jsonl`
- `logs/2026-05/2026-05-15/runtime.out.*.log`
- `logs/2026-05/2026-05-15/trade_fills_utc.csv`

UTC `2026-05-15 01:00:00` 后成交汇总：

| UTC 时间 | 合约 | 动作 | 说明 | 实现盈亏 |
|---|---:|---:|---|---:|
| 01:00:13 | DOGEUSDT | 买入 | 早盘开多/已有策略窗口 | 0 |
| 01:00:13 | PUMPUSDT | 买入 | 早盘开多/已有策略窗口 | 0 |
| 01:30:28 | PUMPUSDT | 卖出 | 平 01:00 多仓 | -0.35658 |
| 01:45:15 | PUMPUSDT | 买入 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85` | 0 |
| 01:51:57 | DOGEUSDT | 卖出 | 平 01:00 多仓 | -0.39406 |
| 02:00:16 | RENDERUSDT | 卖出 | ExitGuard 平旧仓 | -0.51250 |
| 02:15:15 | RENDERUSDT | 买入 | `macd_v2_long_1h_flip_bearish_15m__vwap_0.96` | 0 |
| 02:30:15 | PUMPUSDT | 卖出 | 平 01:45 多仓 | -0.27143 |
| 03:00:16 | PUMPUSDT | 买入 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85` | 0 |
| 03:45:15 | BCHUSDT | 买入 | `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85` | 0 |
| 04:55:10 | PUMPUSDT | 卖出 | 平 03:00 多仓 | -0.21884 |
| 05:07:39 | RENDERUSDT | 卖出 | 平 02:15 多仓 | -0.61030 |
| 05:30:15 | MORPHOUSDT | 买入 | `macd_v2_long_1h_red_bar_growing_15m__vwap_0.94` | 0 |
| 06:15:15 | MORPHOUSDT | 卖出 | 平 05:30 多仓大部分 | -1.19061 |
| 06:25:24 | MORPHOUSDT | 卖出 | 平剩余 | -0.01098 |
| 08:25:13 | BCHUSDT | 卖出 | 平 03:45 多仓 | -0.21204 |
| 11:00:16 | AVAXUSDT | 卖出 | `macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.13` | 0 |

截至日志内已实现亏损合计约 `-4.337338 USDT`，不含 11:00 AVAXUSDT 新空单后续未实现/未平仓结果。

## 不是执行层方向翻转

`fund_flow_attribution.jsonl` 中非 HOLD 决策显示：

- 01:45 PUMPUSDT：decision `buy`，reason `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85`
- 02:15 RENDERUSDT：decision `buy`，reason `macd_v2_long_1h_flip_bearish_15m__vwap_0.96`
- 03:00 PUMPUSDT：decision `buy`，reason `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85`
- 03:45 BCHUSDT：decision `buy`，reason `macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85`
- 05:30 MORPHOUSDT：decision `buy`，reason `macd_v2_long_1h_red_bar_growing_15m__vwap_0.94`
- 11:00 AVAXUSDT：decision `sell`，reason `macd_v2_short_1h_green_bar_shrinking_15m__vwap_0.13`

成交方向与 decision 一致。因此问题不是 execution_router 把 LONG 下成 SHORT，或者把 SHORT 下成 LONG。

## 代码/配置层直接原因

### 1. 昨天一次性打开了多个“释放候选”的开关

当前 diff 显示配置改动包括：

- `probe_floor_rescue.shadow_mode: true -> false`
- 新增 `vwap_deviation_gate.mode = atr_normalized`
- 新增 `total_compression_floor`
- 新增 `partial_confirm`，但 runtime 指纹显示 `pc_shadow=True`，所以 partial_confirm 今天理论上仍是 shadow，不是主要 live 下单来源
- 新增/启用 `position_exit_signal_guard`

这违背了昨天文档 `docs/514-strict_exec_v3_20260514.md` 的强制顺序：A 部署可观测性、B ExitGuard、C 上游门控分步释放。实际风险是多个门控/仓位释放一起进入 live，无法隔离哪一个改动导致亏损。

### 2. VWAP ATR gate 把固定 hard block 放宽为 ATR 归一化 probe/pass

`src/fund_flow/macd_strategy_v2.py` 中新增 `_resolve_vwap_extension_gate()` 后，原来固定 `vwap_deviation_hard_block=0.03` 的阻断被替换成 ATR 倍数判断。

今天亏损单的 reason 均带高 `vwap_0.85/0.94/0.96`。这说明 VWAP 不再阻止这类多头入场，反而给了较高位置评分。对于下跌延续环境，这个评分没有起到“方向反证”的作用。

### 3. `total_compression_floor` 把原本应被压小或归零的仓位抬起来

`calculate_position_size()` 里新增：

```python
floor = self.resolve_total_compression_floor(score, base_default_portion)
if floor > 0:
    portion = max(portion, min(max_symbol_position_portion, floor))
```

这会把压缩后的仓位重新抬到 base portion 的一定比例。今天多笔实际 target portion 为 `0.12 / 0.252 / 0.315`，说明“探针/压缩”没有把错误方向控制在足够小的损失范围内。

### 4. 对 `red_bar_shrinking` / `flip_bearish` 的反向含义没有建立硬防线

项目既有语义里：

- `red_bar_growing` 是多头动能增强
- `green_bar_growing` 是空头动能增强
- `red_bar_shrinking` / `green_bar_shrinking` 是动能衰减，不等于确认方向
- `flip_bearish` 在项目中可作为某些多头反转/回踩路径的一部分，但风险很高

今天最糟糕的是：

- RENDERUSDT 02:15：`long + 1h_flip_bearish + vwap_0.96`，随后亏损平仓
- PUMPUSDT/BCHUSDT：`long + 1h_red_bar_shrinking + vwap_0.85`，随后亏损平仓

也就是说，策略没有强制要求“多头必须有 1H 多头确认或 15m 明确反转确认”，而是让“衰减/翻空附近的早期反转假设”进入 live。

## 深层归因：我为什么犯错

### 错误 1：把“开仓少/方向覆盖不足”误当成主问题

昨天的目标被我理解为“方向识别要更积极，别把 shrink+confirm 候选都归零”。这个方向本身不是完全错，但我没有同时建立反向验收：

- 释放后是否会在下跌延续日连续开多？
- `red_bar_shrinking` long 是否必须限制为 shadow/probe？
- `flip_bearish` long 是否必须要求更强 15m 反转确认？
- UTC 01:00-06:00 这种流动性/波动环境是否要单独黑名单或降仓？

### 错误 2：没有遵守“一个变量一个变量 live”的纪律

文档明确写了 C-1、C-2、C-3 分步释放，并且 partial_confirm 需要 12H shadow 验收后才 live。实际 diff 中多个风控开关和仓位释放逻辑同时变动。即使 partial_confirm 本身还是 shadow，VWAP gate、probe_floor_rescue、total_compression_floor 已经足够改变实盘行为。

这是流程错误，不是市场随机性。

### 错误 3：过度相信回测/历史语义，低估今天 regime shift

历史文档中 `red_bar_growing` 多头曾是收益来源，但今天亏损主要来自：

- `red_bar_shrinking` long
- `flip_bearish` long
- 高 VWAP 分但价格继续走弱

我没有把“历史上某信号有效”与“当前行情下该信号是否仍有效”分开验证，导致把统计优势错误外推到 live。

### 错误 4：缺少上线前的回放断言

上线前应该至少有以下断言：

- 在今天 01:00 前后的真实快照回放中，不允许出现 `long + 1h_flip_bearish` 大仓开仓。
- `long + 1h_red_bar_shrinking` 必须是 shadow 或极小 probe，不能达到 `0.12+` target portion。
- 同一 symbol 在刚被 ExitGuard/止损平仓后，不允许 1-2 个周期内再次按同类方向开仓。
- `total_compression_floor` 不能覆盖 probe/冲突/反向信号的仓位压缩。

这些断言没有写，导致错误直接进 live。

## 给 Claude 的评审问题

请重点评审：

1. `total_compression_floor` 是否应该完全禁止应用于 `is_trial_entry`、`vwap_probe_mode`、`rsi_probe_mode`、`red_bar_shrinking`、`flip_bearish` long。
2. `long + 1h_flip_bearish` 是否应该默认禁用，除非 15m/RSI/价格突破形成明确反转。
3. `long + 1h_red_bar_shrinking` 是否只能 shadow 或 max_portion <= 0.042。
4. VWAP ATR gate 是否把“价格相对价值区间有利”误当成“方向确认”，导致高 vwap_score 在下跌延续时放大亏损。
5. ExitGuard 平仓后是否需要 cooldown，禁止同 symbol 同方向短时间再入场。

## 立即建议

在 Claude 评审前，最保守的止血动作是：

1. 把 `probe_floor_rescue.shadow_mode` 改回 `true`。
2. 关闭 `total_compression_floor`。
3. 禁止 `long + signal_type_1h in {red_bar_shrinking, flip_bearish}` 进入 live，至少先 shadow。
4. 对 ExitGuard 刚平仓的 symbol 加 cooldown，避免刚亏损平仓又重新同方向进入。

