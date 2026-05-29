# 2026-05-18 北京时间 13:15-19:00 无开仓归因：SHORT floor 修复未真正释放交易

审阅对象：Claude  
分析时间：2026-05-18  
日志目录：`D:\AIDCA\AI2\logs\2026-05\2026-05-18`  
有效窗口：北京时间 `2026-05-18 13:15:00` 到 `19:00:59`，对应 UTC `2026-05-18 05:15:00` 到 `11:00:59`。

## 结论摘要

本窗口没有任何成交，`trade_fills_utc.csv` 在 UTC `05:15-11:00` 内为 `0` 条。`fund_flow_attribution.jsonl` 显示窗口内共有 `672` 个 decision event，其中 `667` 个 HOLD、`5` 个 SELL；但 `672` 个 execution event 全部是 `noop`，没有 pending、success 或 error。

上次优化的两个目标里，逆势多单保护生效了：窗口内没有 BUY decision，且 TON 这类高分但 VWAP 下方的多单被 `counter_trend_long_guard` 拦住。例如 TON `total=0.9153/0.6800`，但因为 `dev=-4.29%`、ADX 约 `12.5`、RANGE，被 `below_vwap_4.29%_adx=12.5_range_block` 拦截。这说明“熊市逆向开多”的亏损风险被压住了。

但开仓数量问题没有解决。窗口内确实出现了 `5` 个已经到 `stage=final` 且分数过阈值的 SHORT 候选，全部被执行前风控改成 `min_notional_below_floor` HOLD。新逻辑只是把原来的 `min_notional failed` execution error 变成了 execution noop，并没有把这些 SHORT 提升到可执行仓位。

根因是：策略层输出的 SHORT target 仍然极小，`POLUSDT target=0.000219`、`ATOMUSDT target=0.000437`。以账户权益约 `112 USDT` 估算，名义价值只有 `0.024U` 和 `0.049U`，距离普通品种 `2U` 最小开仓需要提升约 `82x` 和 `41x`。当前 `short_floor_max_lift_ratio=5.0` 因为提升倍数过大，选择 HOLD，而不是 lift 到 `2U`。所以“避免 error”做到了，“增加开仓”没有做到。

## 数据总览

| 项 | 数量 |
|---|---:|
| decision events | 672 |
| HOLD decisions | 667 |
| SELL decisions | 5 |
| BUY decisions | 0 |
| execution noop | 672 |
| execution pending | 0 |
| execution success | 0 |
| execution error | 0 |
| fills | 0 |

decision reason 粗分布：

| bucket | count |
|---|---:|
| zero_score_other | 364 |
| vwap_hard_block | 127 |
| threshold_low_score | 90 |
| vwap_score_filter | 86 |
| SELL decisions | 5 |

说明：本窗口没有 execution error，不代表微仓问题解决，而是因为风控把不够最小名义价值的 SELL 转成了 HOLD/noop。

## 5 个确认 SHORT 如何被否定

| UTC | BJT | symbol | stage | dir | score/th | target | 估算 notional | 需要 portion | lift ratio | execution |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| 07:15:15 | 15:15:15 | POLUSDT | final | short | 0.7694 / 0.6600 | 0.000219 | 0.024U | 0.01799 | 82.1x | HOLD |
| 07:45:15 | 15:45:15 | POLUSDT | final | short | 0.7708 / 0.6600 | 0.000219 | 0.024U | 0.01799 | 82.1x | HOLD |
| 08:00:15 | 16:00:15 | POLUSDT | final | short | 0.7927 / 0.6600 | 0.000219 | 0.024U | 0.01799 | 82.1x | HOLD |
| 10:00:15 | 18:00:15 | ATOMUSDT | final | short | 0.7267 / 0.6600 | 0.000437 | 0.049U | 0.01799 | 41.2x | HOLD |
| 10:30:15 | 18:30:15 | ATOMUSDT | final | short | 0.7269 / 0.6600 | 0.000437 | 0.049U | 0.01799 | 41.2x | HOLD |

execution attribution 对应原因均为：

```text
min_notional_below_floor | macd_v2_short_1h_green_bar_growing_15m__vwap_...
```

这说明信号已经不是被方向层否决，而是在策略输出和执行准入之间被最小名义价值挡住。

## 典型样本

### POLUSDT 15:15 BJT

runtime 显示：

```text
[POLUSDT] 决策=SELL | 状态=noop | 目标占比=0.00
MACD_V2评分: stage=final, dir=short,
primary=4H:0.3547(red_bar_shrinking),
1H=0.1275(green_bar_growing),
VWAPq=0.0432, VWAPa=0.0022(dev=-3.28%),
15M=0.0120(-/-, raw=0.24),
VOL=0.0330,
EMA=1.20x/strong,
total=0.7694/0.6600,
trial=True
```

attribution decision 保留了原始 target：

```text
operation=sell
target_portion_of_balance=0.000219
signal_score=0.7694
vol_vwap_warn_position_scaled=True
vol_vwap_warn_original_portion=0.000437
vol_vwap_warn_adjusted_portion=0.000219
```

attribution execution 则变成：

```text
operation=hold
target_portion_of_balance=0.0
reason=min_notional_below_floor | macd_v2_short_1h_green_bar_growing_15m__vwap_0.04
status=noop
```

不合理点：这是一个分数过线的 final SHORT，且原始仓位已经只有 `0.000437`，又被 `vol_vwap_warn_position_scale=0.5` 压到 `0.000219`。账户约 `112U` 时只有 `0.024U` 名义价值，远低于 `2U`。这不是普通风控压仓，而是仓位计算单位/缩放链路严重失真。

### ATOMUSDT 18:00 BJT

runtime 显示：

```text
[ATOMUSDT] 决策=SELL | 状态=noop | 目标占比=0.00
MACD_V2评分: stage=final, dir=short,
primary=4H:0.3439(red_bar_shrinking),
1H=0.1275(green_bar_growing),
VWAPq=0.6654, VWAPa=0.0333(dev=+0.18%),
15M=0.0090(-/-, raw=0.18),
VOL=0.0330,
EMA=1.00x/normal,
total=0.7267/0.6600,
trial=True
```

attribution decision：

```text
operation=sell
target_portion_of_balance=0.000437
signal_score=0.726703
vol_vwap_warn=False
```

attribution execution：

```text
operation=hold
reason=min_notional_below_floor | macd_v2_short_1h_green_bar_growing_15m__vwap_0.67
status=noop
```

不合理点：ATOM 没有 `vol_vwap_warn_position_scaled`，仍然只有 `target=0.000437`。这说明微仓不是单纯由 `vol_vwap_warn` 造成，原始 trial/final SHORT 仓位本身已经小到不可执行。

## 为什么 short floor 没有解决问题

上次修复设计是：

```text
若 SHORT target notional < min_notional:
  如果 lift_ratio <= short_floor_max_lift_ratio(5x)，提升到 min_notional
  如果 lift_ratio > 5x，策略层 HOLD，避免 execution error
```

本窗口的实际 target 太小：

| symbol | target | 2U 所需 target | lift ratio |
|---|---:|---:|---:|
| POLUSDT | 0.000219 | 0.01799 | 82.1x |
| ATOMUSDT | 0.000437 | 0.01799 | 41.2x |

因此它们全部走了 “too small to lift -> HOLD” 路径。这个逻辑确实避免了 `execution error`，但没有实现“SHORT 可执行化”。如果验收标准是 error 归零，它过了；如果验收标准是 `SHORT 实际成交数量 >= 5/12H`，它失败。

## 仓位压缩链路的可疑点

本窗口 final SHORT 都是 `trial=True`，形态是：

```text
4H red_bar_shrinking + 1H green_bar_growing
```

这类信号分数过线，但 target 被压成 `0.000219/0.000437`。按 `112U` 账户，正常 `2U` 最小仓位应约 `0.018`，当前 target 只有最低可执行仓位的 `1.2%` 到 `2.4%`。

可疑压缩来源：

1. `trial=True` 路径可能有固定微仓或额外 tiny multiplier。
2. `green_bar_growing_probe_position_penalty` 或 probe overlay 仍在某些路径上叠加。
3. `vol_vwap_warn_position_scale=0.5` 会把 POL 从 `0.000437` 进一步压到 `0.000219`，但 ATOM 没有这个缩放仍不可执行。
4. `short_floor_max_lift_ratio=5.0` 对当前微仓级别无效，因为真实需要提升 41x 到 82x。

结论：当前问题不再是执行层 `2U` 门槛过高，而是策略层 final SHORT 的 target 生成已经低到失真。需要从 target 生成处修，而不是只在 risk_engine 后面补 floor。

## 逆势多单保护效果

本窗口没有 BUY decision。高分 LONG 被 `counter_trend_long_guard` 拦住，典型 TON：

```text
MACD_V2评分: stage=counter_trend_long_guard,
dir=neutral,
primary=4H:0.4000(red_bar_growing),
1H=0.1275(red_bar_growing),
VWAPq=0.7968, VWAPa=0.0398(dev=-4.29%),
15M=0.0150(-/-, raw=0.30),
VOL=0.0330,
total=0.9153/0.6800
HOLD归因: reason=below_vwap_4.29%_adx=12.5_range_block
```

这和上次 TON 亏损多单高度相似，但这次被拦住了。说明 Bug A 的方向保护是有效的。

风险提醒：逆势多单保护有效后，开仓数量只能靠 SHORT 修复释放，不能继续放宽 LONG 来补数量。当前窗口的数据也支持这一点：BUY 为 0，SELL 有 5 个 final 候选但被微仓挡住。

## 不合理门槛排序

### P0：final SHORT 的 target 生成严重过小

证据：5 个 final SHORT 分数均过 `0.66`，但 target 只有 `0.000219/0.000437`，名义价值 `0.024U/0.049U`。这已经不是“谨慎 probe”，而是不可执行的灰尘仓位。

建议 Claude 重点审查：`trial=True` 的 SHORT 是否应该直接用 `max(proposed_target, min_executable_portion)`，或者在 target 生成处设置 `min_executable_notional_usdt=2.0` floor，而不是等到 risk_engine 再用 `5x lift ratio` 拦截。

### P0：`short_floor_max_lift_ratio=5.0` 与实际微仓量级冲突

证据：真实需要提升 `41x-82x`，所以 5x floor 对当前样本完全不会触发。若坚持 5x，就必须修上游 target 使其至少达到 `0.0036` 左右；否则所有 final SHORT 仍会 HOLD。

### P1：`vol_vwap_warn_position_scale=0.5` 在已经不可执行的 target 上继续压仓

证据：POL 原始 target `0.000437` 已经只有 `0.049U`，又被压到 `0.000219`。对不可执行 target 再缩放没有风险控制意义，只会让 lift ratio 更夸张。

### P1：vwap_score_filter 仍阻断大量 same-direction SHORT

证据：窗口内 `vwap_score_filter=86`，典型同向 SHORT `green_bar_growing + green_bar_shrinking` 因 `VWAPq=0.0389<0.0600` 被清零。这个不是本次“5 个 final 被拒”的直接原因，但会继续压低候选数量。

### P1：threshold_low_score 仍集中在 RSI soft SHORT

证据：`threshold_low_score=90`，大量 `green_bar_growing + green_bar_shrinking` 在 RSI soft 后总分约 `0.32/0.44/0.57 < 0.69`。这说明 RSI hard veto 虽然被部分软化，但 soft path 的分数/阈值仍不足以形成候选。

## 给 Claude 的审阅问题

1. 对已经 `stage=final` 且 `score > threshold` 的 SHORT，是否应该允许 risk_engine 将 target 从 `0.000437` 直接 lift 到 `2U/equity≈0.018`，即使 lift ratio 是 `41x`？
2. 如果不允许 41x/82x lift，是否说明上游 target 生成是 bug，必须在 `trial=True` 或 `green_bar_growing` SHORT 路径设置最低可执行 target？
3. `short_floor_max_lift_ratio=5.0` 在当前微仓量级下等于永不生效，是否应该取消 ratio 限制，改成 score gated floor，例如 `score>=0.72 && final && short -> min 2U`？
4. `vol_vwap_warn_position_scale=0.5` 是否应只作用于已经可执行的仓位？对 `notional<2U` 的 target 继续缩放是否应禁用？
5. 本窗口逆势 LONG guard 已经挡住 TON 类高分多单，后续增加开仓数量是否应只从 SHORT 可执行化入手，而不是放宽 LONG？
6. `vwap_score_filter(0.0389<0.0600)` 和 RSI soft 后 `0.32/0.44/0.57 < 0.69` 是否应作为第二阶段调参，不要和 P0 的 SHORT 微仓 floor 混在一起？

## 建议下一步

建议不要再把问题定义为 execution 层 `min_notional`。execution error 已经消失，但开仓也消失了。真正要修的是“final SHORT 生成了不可执行 target”。

建议优先方案：

```text
if direction == short
   and stage == final
   and score >= threshold
   and min_notional_usdt == 2U:
       target_portion = max(target_portion, 2U / account_equity)
       再应用 max_symbol_position_portion 和 leverage cap
```

若担心从 `0.000219` 提到 `0.018` 风险过大，则不应让这类信号进入 final，而应在策略层标为 shadow/probe_dust，不要显示为 `决策=SELL`。

## 单句归因

北京时间 13:15-19:00 没有开仓的直接原因是：逆势 LONG guard 生效后 BUY 被压住，而 5 个已经 final 且过阈值的 SHORT 仍被策略仓位链压成 `0.000219/0.000437` 的不可执行微仓；新 short floor 因 `short_floor_max_lift_ratio=5x` 拒绝把它们提升到 `2U`，于是 execution 从原来的 error 变成 `min_notional_below_floor` HOLD/noop，开仓数量问题没有真正解决。
