# 2026-05-17 北京时间 23:15 后开仓偏少归因：最新策略没有明显增加开仓

审阅对象：Claude  
分析时间：2026-05-17  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
主分析窗口：`2026-05-16 15:15:00 UTC` 到 `2026-05-17 02:45:03 UTC`。  
北京时间对应：`2026-05-16 23:15:00` 到 `2026-05-17 10:45:03`。

说明：用户口径是“北京时间昨晚 23:15 开始”，因此本报告以 `2026-05-16 15:15 UTC` 为起点。日志中后续也有 `2026-05-16 23:15:03 UTC`，那是北京时间 `2026-05-17 07:15:03`，不是本报告主起点。

## 结论摘要

本轮最新策略没有明显增加开仓，第一原因不是权限、API、IOC 未成交，而是策略和执行准入仍有三层错位。

第一层：绝大多数候选仍被 `4H无明确方向` 拦在 neutral upgrade 早期。窗口内 runtime 统计 `1308` 条 HOLD，其中 `4H无明确方向` 为 `1039` 条，占 `79.4%`。主要集中在 `green_bar_shrinking + red_bar_growing`、`green_bar_shrinking + red_bar_shrinking` 这两类 4H 熊力衰减组合。

第二层：RSI adaptive soft gate 有生效迹象，但没有转化成开仓。`green_bar_growing + green_bar_shrinking` 的部分信号已经出现 `rsi_soft_against_probe`，但后续被 `vwap_score_filter` 或 `threshold_check` 否定。也就是说，之前的 RSI hard veto 被松开后，新的瓶颈变成 VWAP score 下限、总分阈值和 15M/VOL 贡献过低。

第三层：真正到达 BUY/final 的信号被执行前校验挡掉。窗口内有 `3` 条 BUY 决策，全部 `status=error`，错误一致：

```text
decision 校验失败: target_portion_of_balance 越界: 0.0420, 要求 [0.06, 1.0]
```

这说明 dynamic min notional 修复只让 `0.042` probe 仓位通过了 Bot 层 notional 判断，但没有同步打通 `FundFlowRiskEngine.validate_decision()` 的最小开仓校验。策略确认开仓后，执行层仍按 `min_open_portion=0.06` 拒绝 `0.042`。

## 新策略版本确认

主窗口开始附近 fingerprint：

```text
[CONFIG_FINGERPRINT] hash=f19bfbda
vwap_gate_mode=directional_ablation
vwap_hard_block=0.0
probe_shadow=True
probe_min_open=0.042
pc_shadow=True
pc_enabled=True
exit_guard=True
```

窗口从：

```text
=== FUND_FLOW cycle 2 @ 2026-05-16 15:15:03 UTC ===
```

开始。该时间等于北京时间 `2026-05-16 23:15:03`。

## 数据总览

| 项 | 数量 |
|---|---:|
| cycles | 48 |
| runtime decision lines | 1311 |
| HOLD/noop | 1308 |
| BUY/error | 3 |
| SELL/pending | 0 |
| 新开仓 pending | 0 |
| 实际 fills after start | 1 |

唯一 fill：

| UTC | symbol | side | price | qty | notional |
|---|---|---|---:|---:|---:|
| 2026-05-16 16:34:43 | JSTUSDT | 卖出 | 0.09108 | 319 | 29.05452 |

注意：窗口开始时已有 JSTUSDT SHORT 持仓。`15:15:03 UTC` 第一轮日志显示 JST 当前占比约 `0.09`，原因是 `DCA未触发，保持观望`。因此这条 fill 不能证明本轮新增策略成功扩大了新开仓能力。

## HOLD 归因分布

| HOLD code | count | 占 HOLD |
|---|---:|---:|
| `4H无明确方向` | 1039 | 79.4% |
| `vwap_hard_block` | 142 | 10.9% |
| `rsi_1h_direction_against_veto` | 54 | 4.1% |
| `信号评分低于阈值` | 28 | 2.1% |
| `vwap_score_filter` | 19 | 1.5% |
| `rsi_15m_extreme_veto` | 17 | 1.3% |
| `rsi_1h_direction_flat_veto` | 6 | 0.5% |
| `flip_bullish_sniper_no_trend_alignment` | 2 | 0.2% |
| `-` | 1 | 0.1% |

stage 分布：

| stage | count |
|---|---:|
| `neutral_upgrade_gate` | 541 |
| `neutral_upgrade_mode` | 498 |
| `vwap` | 142 |
| `rsi_rhythm` | 77 |
| `threshold_check` | 28 |
| `vwap_score_filter` | 19 |
| `flip_bullish_sniper_gate` | 2 |
| `final` | 1 |

## MACD 组合与主要否定层

| 4H + 1H MACD 组合 | count | 主要否定 |
|---|---:|---|
| `green_bar_shrinking + red_bar_growing` | 556 | `4H无明确方向` 460、`vwap_hard_block` 62 |
| `green_bar_shrinking + red_bar_shrinking` | 507 | `4H无明确方向` 507 |
| `flip_bullish + red_bar_shrinking` | 45 | `vwap_hard_block` 32、RSI against 11 |
| `green_bar_shrinking + flip_bullish` | 42 | `4H无明确方向` 38 |
| `green_bar_shrinking + green_bar_shrinking` | 34 | `4H无明确方向` 34 |
| `red_bar_growing + red_bar_shrinking` | 28 | `vwap_hard_block` 17、低分 6 |
| `green_bar_growing + green_bar_shrinking` | 24 | `vwap_score_filter` 13、低分 6、15M extreme 4 |
| `green_bar_growing + green_bar_growing` | 16 | RSI against 11、低分 2、15M extreme 2 |

## 第一瓶颈：4H 无方向仍然接管大部分候选

`4H无明确方向=1039`，是本窗口绝对第一归因。典型模式：

```text
primary=4H green_bar_shrinking
1H=red_bar_growing / red_bar_shrinking / flip_bullish
stage=neutral_upgrade_gate 或 neutral_upgrade_mode
reason=4H无明确方向
```

其中 `green_bar_shrinking + red_bar_growing` 有 `556` 次，`green_bar_shrinking + red_bar_shrinking` 有 `507` 次。这说明市场主要处在 4H 熊力衰减后的反弹/收缩阶段，而当前策略仍将这类组合判为不可交易方向。

`PC_SHADOW` 也印证 partial confirm 没有贡献开仓：

| PC_SHADOW combo | count |
|---|---:|
| `green_bar_shrinking + red_bar_shrinking` | 507 |
| `green_bar_shrinking + red_bar_growing` | 492 |
| `green_bar_shrinking + flip_bullish` | 42 |

`PC_SHADOW` 总计 `1041` 条，全部 `would_pass=False`。其中 `951/1041` 是 `vwap_safe=False && vwap_aligned=False`。这意味着 partial confirm 目前主要产生审计日志，几乎不产生准入候选。

不合理点：如果目标是“增加开仓”，最新策略仍把最大样本池 `green_bar_shrinking` 相关组合挡在 early gate。这里不是 RSI adaptive 能解决的问题。

## 第二瓶颈：RSI soft gate 生效后被 VWAP score 和总分阈值接管

本轮确实看到了 `rsi_soft_against_probe`，例如：

```text
stage=vwap_score_filter
primary=4H green_bar_growing
1H=green_bar_shrinking
15M=rsi_soft_against_probe
VWAPq=0.0525
reason=vwap_score_filter(0.0525<0.0600)
```

以及：

```text
stage=threshold_check
primary=4H green_bar_growing
1H=green_bar_shrinking
15M=rsi_soft_against_probe
total=0.4705/0.6900
reason=信号评分低于阈值: 0.47 < 0.69
```

在统计中，`rsi_soft_against_probe` 后续被否定的分布：

| entry_15m | 后续否定 | count |
|---|---|---:|
| `rsi_soft_against_probe` | `vwap_score_filter` | 8 |
| `rsi_soft_against_probe` | `信号评分低于阈值` | 3 |

这说明 RSI soft 的修复方向正确，但 soft 后没有足够分数进入最终开仓：  
`4H=0.4`，`1H=0`，`15M=0`，`VOL=0.033`，VWAP 有时很低，导致总分常在 `0.42~0.47`，距离 `0.69` 很远。

不合理点：`green_bar_growing + green_bar_shrinking` 被设计为趋势回调 probe，但当前评分体系没有给 probe 足够的最低路径。它不再被 RSI hard veto，但仍自然死在 `vwap_score_filter` 或 `threshold_check`。

## 第三瓶颈：VWAP hard block 回升，但集中在非同向/反向路径

本窗口 `vwap_hard_block=142/1308`，占 `10.9%`。它不是第一瓶颈，但比上一轮 4H 报告中的 `28/443` 绝对数更高。

主要集中：

| combo | vwap_hard_block |
|---|---:|
| `green_bar_shrinking + red_bar_growing` | 62 |
| `flip_bullish + red_bar_shrinking` | 32 |
| `red_bar_growing + red_bar_shrinking` | 17 |
| `green_bar_growing + red_bar_shrinking` | 10 |

这大体符合 directional ablation 设计：同向趋势路径放宽，非同向/反向/收缩路径仍严格。但它也解释了为什么 partial confirm 很难通过：大部分 partial confirm 的 VWAP 安全条件不成立。

## 第四瓶颈：真正通过策略的 0.042 probe 被执行前风险校验拒绝

这是本窗口最明确的 bug/错位。

窗口内出现 3 条 BUY 决策：

| UTC | symbol | side | target | score | vwap_score | result |
|---|---|---|---:|---:|---:|---|
| 2026-05-16 19:45:14 | ATOMUSDT | BUY | 0.042 | 0.7292 | 0.8544 | error |
| 2026-05-16 20:15:15 | HYPEUSDT | BUY | 0.042 | 0.6884 | 0.8284 | error |
| 2026-05-17 00:00:15 | ATOMUSDT | BUY | 0.042 | 0.6926 | 0.7819 | error |

三条都被同一错误拒绝：

```text
decision 校验失败: target_portion_of_balance 越界: 0.0420, 要求 [0.06, 1.0]
```

代码侧对应路径：

```text
src/fund_flow/execution_router.py
  decision = self.risk.validate_decision(decision, position=position)

src/fund_flow/risk_engine.py
  validate_target_portion()
  if not (self.min_open_portion <= val <= self.max_open_portion):
      raise ValueError(...)
```

`risk_engine.py` 虽然有：

```python
def resolve_min_open_portion(self, decision):
    if decision.metadata.get("rsi_probe_mode", False):
        return min(base_min, self.probe_min_open_portion)
```

但这 3 条 BUY 的 metadata 没有可识别的 `rsi_probe_mode=True`，或者风险引擎没有拿到正确的 probe 配置，因此执行校验仍按 `min_open_portion=0.06`。

更隐蔽的问题：`FundFlowRiskEngine.__init__()` 读取的是：

```python
fund_flow_cfg.get("probe_min_open_portion", fund_flow_cfg.get("min_open_portion", 0.08))
```

而实盘配置里 `probe_min_open_portion=0.042` 位于：

```json
"probe_floor_rescue": {
  "probe_min_open_portion": 0.042
}
```

不是 `fund_flow.probe_min_open_portion` 顶层。也就是说，风险引擎很可能没有读到 0.042。

不合理点：dynamic min notional 已经解决了 `4.67U < 5U` 的误杀，但执行层最小比例校验仍要求 `0.06`，导致所有 `0.042` probe BUY 全部失败。上一轮“ATOM 4.67U 被 5U 误杀”的修复只打通了 Bot entry gate，没有打通 execution risk gate。

## 第五瓶颈：高分 final SHORT 仍被 probe_floor_rescue shadow 拦住

窗口内有 5 个 `ENTRY_GATE_BLOCK`，全部是 `min_open_portion`：

| UTC | symbol | side | score | target | notional | reason |
|---|---|---|---:|---:|---:|---|
| 2026-05-16 16:45 | HYPEUSDT | SHORT | 0.7876 | 0.0050 | 0.555U | below min/notional |
| 2026-05-17 01:30 | JSTUSDT | SHORT | 0.7181 | 0.00105 | 0.117U | below min/notional |
| 2026-05-17 02:00 | JSTUSDT | SHORT | 0.7510 | 0.0050 | 0.555U | below min/notional |
| 2026-05-17 02:15 | JSTUSDT | SHORT | 0.8778 | 0.001312 | 0.146U | probe eligible but shadow |
| 2026-05-17 02:30 | JSTUSDT | SHORT | 0.8765 | 0.001312 | 0.146U | probe eligible but shadow |

其中最后两条 JSTUSDT：

```json
"probe_floor_rescue": {
  "enabled": true,
  "applied": false,
  "shadow_mode": true,
  "original_target_portion": 0.001312,
  "reason": "eligible",
  "signal_score": 0.8778,
  "min_score_threshold": 0.8,
  "probe_portion": 0.042
}
```

这不是 bug，而是当前安全策略选择。但它解释了为什么“高分确认 SHORT 仍不开仓”：因为 probe_floor_rescue 仍是 shadow，且原始 target 被压到 `0.001312`，名义价值只有约 `0.146U`，低于 dynamic notional 的约 `4.43U`。

## 非主因排除

### 权限/API/账户

不是主因。没有发现 `permission_denied / account_blocked / api_error / Traceback` 类主错误。runtime.err 只有 deprecated config warning。

### IOC 未成交

不是本窗口主因。窗口内没有新开仓 pending；执行失败发生在下单前的 decision 校验，因此还没有走到 IOC 成交层。

### dynamic min notional

修复部分生效，但不完整。它让 `0.042` probe 能越过 Bot 层 notional gate；但 execution risk gate 仍要求 `0.06`，所以最终仍没有开仓。

### RSI adaptive direction gate

部分生效，但不是最终开仓增加的充分条件。它降低了部分 RSI hard veto，但释放出的信号大多被 VWAP score 或总分阈值否定。

## 不合理门槛排序

### 第一优先级：执行层 `min_open_portion=0.06` 与策略 probe `0.042` 冲突

证据：3 条 BUY 决策都 `target=0.042`，全部被校验错误拒绝。  
这是本轮最明确的“确认开仓被否定”。

需要 Claude 审查的问题：

1. 风险引擎是否应该识别 `target_portion=0.042` 为合法 probe？
2. `rsi_probe_mode` / `probe_floor_rescue` / `signal_combo_max_portion` 是否应该统一写入 metadata，供 `resolve_min_open_portion()` 使用？
3. `probe_min_open_portion` 是否应从 `fund_flow.probe_floor_rescue.probe_min_open_portion` 读取，而不是只读顶层 `fund_flow.probe_min_open_portion`？

### 第二优先级：4H shrink 组合仍被 neutral upgrade 早期清零

证据：`4H无明确方向=1039/1308`，其中 `green_bar_shrinking + red_bar_growing` 和 `green_bar_shrinking + red_bar_shrinking` 是最大池子。

这不是今天 RSI soft 能解决的问题。若目标是增加开仓，必须决定是否继续让 4H shrink 全部 shadow，还是允许极小 probe。

### 第三优先级：RSI soft 后缺少 probe 保底评分/路径

证据：`rsi_soft_against_probe` 出现后，8 次死于 `vwap_score_filter`，3 次死于 `threshold_check`。典型总分只有 `0.42~0.47`，距离 `0.69` 很远。

如果 `green_bar_growing + green_bar_shrinking` 被定义为趋势回调 probe，仅把 RSI veto 改成 soft 不够；还要决定 soft probe 是否应走独立阈值或 probe min path。

### 第四优先级：VWAP score filter 对 soft probe 仍过硬

证据：多条 `green_bar_growing + green_bar_shrinking + rsi_soft_against_probe` 被 `vwap_score_filter(0.0525<0.0600)`、`0.0599<0.0600` 这类极近阈值拒绝。

这不是 VWAP hard block，而是 VWAP score 下限对 soft probe 没有弹性。

### 第五优先级：probe_floor_rescue shadow 仍挡高分小 target

证据：JSTUSDT `score=0.8778/0.8765`，`probe_floor_rescue.reason=eligible`，但 `shadow_mode=true`，最终不开仓。

这项此前已有安全理由，不建议单独打开；但它确实是高分 final 后不落单的直接原因之一。

## 给 Claude 的审阅问题

1. `target_portion=0.042` 的 BUY 已被策略确认，但 execution risk gate 仍按 `[0.06, 1.0]` 拒绝。是否应优先修复 `FundFlowRiskEngine.resolve_min_open_portion()` 的 probe 识别和配置读取？
2. `probe_min_open_portion` 现在配置在 `probe_floor_rescue` 下，risk engine 只读顶层字段，这是否就是 0.042 被拒的根因？
3. RSI adaptive soft gate 已出现，但被 `vwap_score_filter` 与 `threshold_check` 接管。是否应该为 `rsi_soft_against_probe` 设置独立 probe 阈值，而不是继续用 `0.69` 主阈值？
4. `green_bar_shrinking + red_bar_growing` / `green_bar_shrinking + red_bar_shrinking` 占绝大多数 HOLD，是否继续保持 shadow，还是先只做观察？
5. 在执行层 probe 校验没打通前，继续调 RSI/VWAP 是否会误判策略效果？

## 单句归因

北京时间 2026-05-16 23:15 后开仓仍少的根因是：最大候选池仍被 `4H无明确方向` 和 partial-confirm shadow 挡在早期；RSI soft 释放出的少量趋势回调信号又被 VWAP score/总分阈值否定；真正通过策略产生的 `0.042` probe BUY 则被执行前 `min_open_portion=0.06` 风险校验拒绝，导致“策略确认开仓”没有转化为实际下单。
