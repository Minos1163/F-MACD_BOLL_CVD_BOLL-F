# 2026-05-16 最新 4H 开仓偏少归因：新策略后确认信号被哪些门槛否定

审阅对象：Claude  
分析时间：2026-05-16  
日志目录：`D:\AIDCA\AI2\logs\2026-05\2026-05-16`  
有效窗口：`2026-05-16 10:15:03 UTC` 到 `2026-05-16 14:00:15 UTC`。

说明：`runtime.out.18.log` 开头有一轮 `10:00:03 UTC` 的旧段，出现在新 `CONFIG_FINGERPRINT` 之前，因此本次统计从新策略 fingerprint 后第一个开仓窗口 `cycle 2 @ 10:15:03 UTC` 开始。严格说有效样本是 3H45M，不是完整 4H。

## 结论摘要

新策略确实生效，但开仓数量仍少：窗口内 `444` 个决策里只有 `1` 个 SELL，`443` 个 HOLD。唯一开仓是 `JSTUSDT` SHORT，`10:15:15 UTC` 提交，`trade_fills_utc.csv` 确认同一时刻实际卖出成交，名义约 `28.92 USDT`。

第一归因已经不再是 VWAP。`CONFIG_FINGERPRINT` 显示 `vwap_gate_mode=directional_ablation`，而 `vwap_hard_block` 从上一份 6H 报告里的 `210/667` 降到本窗口 `28/443`。VWAP 消融方向是有效的。

新的第一归因变成 RSI rhythm 硬否定：`rsi_1h_direction_against_veto` 有 `184` 次，`rsi_1h_direction_flat_veto` 有 `45` 次，二者合计 `229/443`，占 HOLD 的 `51.7%`。也就是说，MACD 给出大量 SHORT 候选后，被 1H RSI 方向反向或走平直接归零。

第二归因是 `4H无明确方向` 仍有 `151/443`。这些主要来自 `green_bar_shrinking + green_bar_shrinking`，说明 4H 熊力衰减阶段仍被判为不可交易方向，partial confirm 仍大多只是 shadow。

第三归因是 final 后仓位门槛仍过硬：`BCHUSDT` 和 `ATOMUSDT` 已到 `stage=final`，分数过线，但被 `min_open_portion=0.0600` 和 `min_open_notional_usdt=5.0` 拦住。尤其 `ATOMUSDT` 两次 `target=0.042`、分数 `0.7656/0.7669`，只差约 `0.33 USDT` 名义价值就能过 5U 门槛，属于当前样本里最明确的“门槛过紧导致少开仓”。

## 新策略已确认生效

`runtime.out.18.log` 中新 fingerprint：

```text
vwap_gate_mode=directional_ablation
vwap_hard_block=0.0
vwap_block_atr_multiplier=0.0
vwap_probe_max_portion=0.0
probe_shadow=True
probe_min_open=0.042
pc_shadow=True
pc_enabled=True
```

窗口内成交：

| UTC | symbol | side | price | qty | notional |
|---|---|---:|---:|---:|---:|
| 2026-05-16 10:15:15 | JSTUSDT | 卖出 | 0.09065 | 319 | 28.91735 |

这排除权限、账户、API、完全不能下单等问题。日志没有 `permission_denied / account_blocked / api_error / Traceback` 类证据，且 JST 实际成交。

## 数据总览

| 项 | 数量 |
|---|---:|
| cycles | 16 |
| decision events | 444 |
| HOLD | 443 |
| SELL | 1 |
| execution noop | 443 |
| pending order | 1 |
| confirmed fill | 1 |

HOLD code 分布：

| HOLD code | count | 占 HOLD |
|---|---:|---:|
| `rsi_1h_direction_against_veto` | 184 | 41.5% |
| `4H无明确方向` | 151 | 34.1% |
| `rsi_1h_direction_flat_veto` | 45 | 10.2% |
| `vwap_hard_block` | 28 | 6.3% |
| `rsi_15m_extreme_veto` | 12 | 2.7% |
| `信号评分低于阈值` | 11 | 2.5% |
| `vwap_score_filter` | 8 | 1.8% |
| `green_bar_growing_short_adx_1h_range_filter` | 2 | 0.5% |
| `rsi_neutral_resume_short_disabled` | 1 | 0.2% |
| `-` | 1 | 0.2% |

stage 分布：

| stage | count |
|---|---:|
| `rsi_rhythm` | 241 |
| `neutral_upgrade_gate` | 127 |
| `vwap` | 28 |
| `neutral_upgrade_mode` | 24 |
| `threshold_check` | 11 |
| `vwap_score_filter` | 8 |
| `green_bar_growing_short_adx_1h_range_filter` | 2 |
| `rsi_neutral_resume_short_disabled` | 1 |
| `final` | 1 |

## MACD 组合与否定层

窗口内几乎全是 SHORT 侧环境，没有真正的同向 LONG 大样本。

| 4H + 1H MACD 组合 | count | 主要否定 |
|---|---:|---|
| `green_bar_growing + green_bar_shrinking` | 170 | `rsi_1h_direction_against_veto` 147 |
| `green_bar_shrinking + green_bar_shrinking` | 123 | `4H无明确方向` 123 |
| `green_bar_growing + green_bar_growing` | 83 | RSI flat/against 74 |
| `green_bar_shrinking + red_bar_growing` | 31 | `vwap_hard_block` 15、`4H无明确方向` 12 |
| `green_bar_shrinking + flip_bullish` | 21 | `4H无明确方向` 12、`vwap_hard_block` 9 |
| 其他小样本 | 16 | 分散 |

### 1. 同向 SHORT 并不少，但被 RSI 硬 veto 接管

按 VWAP 消融设计里的同向 SHORT：

| same-direction pair | count | 结果 |
|---|---:|---|
| `green_bar_growing + green_bar_shrinking` | 170 | 147 次 RSI against，7 次低分，7 次 15M extreme，1 次 SELL |
| `green_bar_growing + green_bar_growing` | 83 | 41 次 RSI flat，33 次 RSI against，4 次 15M extreme |

这说明“4H/1H MACD 确认 SHORT”已经很多，但 RSI rhythm 并不是辅助评分，而是硬闸门。典型日志形态：

```text
primary=4H:0.0000(green_bar_growing), 1H=0.0000(green_bar_shrinking),
15M=0.0000(rsi_1h_direction_block/-), total=0.0000/0.6800
HOLD归因: reason=rsi_1h_direction_against_veto
```

不合理点：当 `4H=green_bar_growing` 已经是强空头背景、`1H=green_bar_shrinking` 只是空头动能收缩时，当前 RSI 规则把它大量归为 against，导致趋势中继/回抽后的 SHORT 机会被清零。这里需要 Claude 审查：`green_bar_growing + green_bar_shrinking` 是否应被 RSI 反向硬 veto，还是应改为 penalty/probe。

### 2. 4H 无方向仍集中在熊力衰减

`4H无明确方向` 共 151 次，其中 `green_bar_shrinking + green_bar_shrinking` 独占 123 次。

这不是传统意义上的完全无方向，而是“4H 熊力衰减、1H 也收缩”。如果目标是增加开仓，当前 neutral upgrade 对这一类仍太保守。`PC_SHADOW` 也印证这一点：

| PC_SHADOW combo | count |
|---|---:|
| `green_bar_shrinking + flip_bullish` | 21 |
| `green_bar_shrinking + red_bar_growing` | 20 |
| `green_bar_shrinking + red_bar_shrinking` | 4 |

所有 `PC_SHADOW` 都是 `would_pass=False`。其中 `44/45` 为 `vwap_safe=False && vwap_aligned=False`。partial confirm 当前主要在产生日志，不在产生交易。

### 3. VWAP 消融有效，但残余 block 集中在非同向/极端偏离

本窗口 `vwap_hard_block=28`，比上一轮大幅下降。残余主要是：

- `green_bar_shrinking + red_bar_growing`: 15 次
- `green_bar_shrinking + flip_bullish`: 9 次
- `green_bar_shrinking + green_bar_growing`: 4 次，主要是 `ICPUSDT`，dev 约 `-15.66%` 到 `-16.17%`

这符合“只消融 same-direction，不触碰对冲/反向/shrink 路径”的设计。VWAP 现在不是第一瓶颈。

### 4. final 后被仓位门槛否定的样本最值得审

窗口内有 3 个 `ENTRY_GATE_BLOCK`，全部是 final 后被 `min_open_portion` 拦住：

| UTC | symbol | side | score/th | target | notional | 否定 |
|---|---|---|---:|---:|---:|---|
| 12:00 | BCHUSDT | SHORT | 0.6919 / 0.6900 | 0.00063 | 0.070054 USDT | target 和 notional 都太小 |
| 12:45 | ATOMUSDT | LONG | 0.7656 / 0.6600 | 0.0420 | 4.671651 USDT | 低于 5U，probe shadow 不落地 |
| 13:00 | ATOMUSDT | LONG | 0.7669 / 0.6600 | 0.0420 | 4.670801 USDT | 同上 |

`BCHUSDT` 的 `target=0.00063` 很小，拦截合理。

`ATOMUSDT` 更值得审：`target=0.042` 正好等于 `probe_min_open`，分数高于阈值约 `0.106`，但账户 equity 约 `111.18 USDT`，所以名义价值只有 `4.67 USDT`，低于 `min_open_notional_usdt=5.0`。这意味着 5U 名义门槛在当前资金规模下等价于 `4.50%` 仓位，而 probe floor 是 `4.20%`，二者互相打架。

不合理点：如果 `probe_min_open=0.042` 是刻意设计的最小试探仓，那么 `min_open_notional_usdt=5.0` 在 111U 账户上会把它实际抬到约 `0.045`。当前配置写着允许 4.2% probe，但执行门要求约 4.5% 才能成交。

### 5. JST 后续高分 HOLD 不是新开仓失败

`JSTUSDT` 在 `10:15` 已开 SHORT。后续出现一次 `stage=final, score=0.8209/0.6900`，但日志原因是：

```text
DCA未触发，保持观望 drawdown=0.0006, next_stage=1
```

这不是确认方向被否定，而是已有持仓后的加仓/DCA 约束。它不应计入“新开仓少”的策略否决主因。

## 不合理门槛排序

### 第一优先级：RSI 1H direction hard veto

证据：`rsi_1h_direction_against_veto + rsi_1h_direction_flat_veto = 229/443`。

影响最大的是 `green_bar_growing + green_bar_shrinking`：170 个同向 SHORT 候选里 147 个被 RSI against 否定。这里很可能是“1H MACD 空头收缩”被 RSI 当成反向，而不是当成趋势回抽/中继。

给 Claude 的问题：对 `4H green_bar_growing + 1H green_bar_shrinking`，RSI against 是否应该从 hard veto 改为 penalty/probe？如果继续 hard veto，VWAP 消融释放出来的同向 SHORT 仍会被 RSI 全部吃掉。

### 第二优先级：neutral upgrade 对 shrink 组合仍过严

证据：`4H无明确方向=151`，其中 `green_bar_shrinking + green_bar_shrinking=123`。

这类不是完全无信息，而是 4H 和 1H 都处在空头衰减/收缩。若目标是增加开仓，至少应审查它是否能进入小 probe，而不是直接归零。但这里风险比 RSI hard veto 更高，因为它不是明确顺势加速。

### 第三优先级：probe floor 与 min notional 冲突

证据：`ATOMUSDT` 两次 `score>0.765`、`target=0.042`、`notional=4.67U`，被 `min_open_notional_usdt=5.0` 拦住。

这不是方向问题，而是资金规模下的执行门槛问题。若保留 `probe_min_open=0.042`，则 `min_open_notional_usdt` 应与账户规模联动，或把 `probe_min_open` 明确提高到能覆盖 5U。否则日志会持续出现“策略允许 probe，但执行层不允许下单”的错位。

### 第四优先级：green_bar_growing_short_adx_1h_range_filter

证据只有 2 次，影响小，但它拦的是 `green_bar_growing + green_bar_growing` 同向 SHORT，ADX 在 `[35,45)`。如果后续样本增加，需要审查这个区间过滤是否仍合理。

## 非主因排除

### 权限/账户/API

不是主因。JST 能下单并成交，`runtime.err.18.log` 只有 deprecated config warning。

### IOC 未成交

不是本窗口主因。JST attribution 中 `status=NEW, executedQty=0`，但 `trade_fills_utc.csv` 确认 `10:15:15` 已成交。

### VWAP

不再是第一主因。`vwap_hard_block` 降到 `28/443`，且主要集中在非同向/反向/极端偏离路径。

### 容量

不是第一主因。窗口内只有 JST 一笔持仓，未见 max active symbols 打满。

## 给 Claude 的审阅问题

1. `green_bar_growing + green_bar_shrinking` 被 `rsi_1h_direction_against_veto` 大量清零是否合理？这类是否应视为 SHORT 趋势中继，而不是 RSI 反向硬否定？
2. `green_bar_growing + green_bar_growing` 被 `rsi_1h_direction_flat/against` 否定 74 次，是否说明 RSI rhythm 对趋势确认过严？
3. `green_bar_shrinking + green_bar_shrinking` 123 次全归 `4H无明确方向`，是否应该允许小 probe，还是继续等 partial confirm 24H 胜率？
4. `probe_min_open=0.042` 与 `min_open_notional_usdt=5.0` 在 111U equity 下冲突，是否应把 5U 改为动态值，或把 probe floor 明确调到能覆盖 5U？
5. VWAP 消融后 `vwap_hard_block` 已不是瓶颈，下一步是否应先动 RSI hard veto，而不是继续调 VWAP？

## 单句归因

最新有效 4H 内开仓少的根因是：VWAP 消融已经释放了一部分同向 SHORT，但 RSI rhythm 的 1H direction hard veto 接管为最大否决层；同时 `green_bar_shrinking` 相关组合仍被 neutral upgrade 判为 4H 无方向，少数 final 高分信号又被 `min_open_portion / min_open_notional / probe_shadow` 挡住。
