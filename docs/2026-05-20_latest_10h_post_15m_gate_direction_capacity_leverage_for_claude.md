# 2026-05-20 最新 10H 方向门控复盘：15M 门控后仍亏损、总持仓仍被 5 卡住、杠杆未体现 3/4/5

审阅对象：Claude  
分析时间：2026-05-20  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
有效窗口：`2026-05-20 03:45:15 UTC` 到 `2026-05-20 13:45:15 UTC`，北京时间为 `2026-05-20 11:45:15` 到 `2026-05-20 21:45:15`。

窗口端点来自最新 `fund_flow_attribution.jsonl` 的最大时间戳 `2026-05-20T13:45:15.332060+00:00`，向前倒推 10H。

数据来源：

- `logs\2026-05\2026-05-20\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-20\trade_fills_utc.csv`
- `logs\2026-05\2026-05-20\runtime.out.12.log`
- `logs\2026-05\2026-05-20\runtime.out.18.log`
- `config\trading_config_fund_flow.json`
- `src\app\fund_flow_bot.py`
- `src\fund_flow\decision_engine.py`
- `src\fund_flow\macd_strategy_v2.py`

说明：`trade_fills_utc.csv` 按 `订单ID + 成交ID + symbol + time + side + qty + price` 去重后统计。

## 结论摘要

上次优化后的最新 10H 结果仍不好：去重成交 `32` 条，已实现净 PnL 约 `-1.215535 USDT`。亏损主要来自 `ICPUSDT -0.3360`、`ADAUSDT -0.3052`、`SOLUSDT -0.1984`、`PUMPUSDT -0.194895`、`AVAXUSDT -0.1110`。这些亏损几乎都来自 LONG，且共同特征仍是：`4H red_bar_growing + 1H red_bar_growing` 把分数推过 final，但价格仍在 VWAP 下方，15M 没有明确触发。

这说明 15M gate / flip guard / ADX cap 的方向是对的，但当前 live 表现没有真正阻断核心亏损路径。尤其是 `ICP/SOL/ADA/PUMP/AVAX` 都是 `entry_15m=-`、`raw_15m=0.12~0.24`，却仍然开了 `0.10~0.18` 的 LONG。换句话说，15M 仍然没有成为“硬门槛”，而是被 4H/1H/RSI 总分结构绕过。

开仓数量问题这次不是 `min_notional` 失败。窗口内 execution error 为 `0`，ATOM SHORT 还出现了执行层数量提升日志：`notional=3.9636 -> 5.2111`。真正的数量瓶颈变成了总持仓 cap：日志反复出现 `active_symbol_capacity threshold=5 value=5` 和 `持仓交易对已满(5/5)`。虽然配置已经有“小仓位 <5U 最多 5 个、大仓位 >=5U 最多 4 个”的 bucket，但顶层 `fund_flow.max_active_symbols` 仍是 `5`，所以 bucket 规则没有实现总容量 `5+4=9`。

动态杠杆也没有达到预期。配置顶层已有 `min=3/default=4/max=5`，但本窗口所有开仓请求/实际杠杆都是 `3x/3x`。代码和配置里仍有多个 `*_max_leverage=2` 的 cap，最终被 `min_leverage=3` 抬成 3x，导致实际只使用 3x，没有体现 4x/5x 分层。

## 10H 数据总览

| 项 | 数量 |
|---|---:|
| attribution rows | 2158 |
| decision events | 1079 |
| execution events | 1079 |
| HOLD decisions | 1067 |
| BUY decisions | 7 |
| SELL decisions | 1 |
| CLOSE decisions | 4 |
| execution noop | 1069 |
| execution pending | 7 |
| execution success | 3 |
| execution error | 0 |

开仓决策：

| UTC | symbol | 方向 | target | lev | score | regime | 1H | VWAPq | execution |
|---|---|---|---:|---:|---:|---|---|---:|---|
| 05:15 | AVAXUSDT | BUY | 0.120 | 3 | 0.8551 | TREND | red_bar_growing | 0.8515 | pending |
| 05:45 | ICPUSDT | BUY | 0.120 | 3 | 0.7251 | TREND | red_bar_growing | 0.7728 | pending |
| 06:00 | SOLUSDT | BUY | 0.120 | 3 | 0.8507 | TREND | red_bar_growing | 0.7649 | pending |
| 06:00 | ADAUSDT | BUY | 0.120 | 3 | 0.8501 | TREND | red_bar_growing | 0.7519 | pending |
| 08:45 | JUPUSDT | BUY | 0.1512 | 3 | 0.6941 | TREND | red_bar_growing | 0.1528 | noop |
| 09:00 | ATOMUSDT | SELL | 0.005 | 3 | 0.7714 | TREND | green_bar_shrinking | 0.4670 | pending |
| 11:45 | PUMPUSDT | BUY | 0.180 | 3 | 0.7243 | TREND | red_bar_growing | 0.7564 | pending |
| 13:15 | AVAXUSDT | BUY | 0.042 | 3 | 0.6859 | TREND | red_bar_shrinking | 0.6474 | pending |

## 成交与盈亏

| symbol | fills | realized pnl | notional |
|---|---:|---:|---:|
| ICPUSDT | 8 | -0.336000 | 120.3360 |
| ADAUSDT | 4 | -0.305200 | 108.6512 |
| SOLUSDT | 4 | -0.198400 | 108.4352 |
| PUMPUSDT | 4 | -0.194895 | 148.7482 |
| AVAXUSDT | 5 | -0.111000 | 119.6090 |
| ZROUSDT | 2 | -0.058800 | 5.3572 |
| FETUSDT | 1 | -0.056000 | 5.3396 |
| WLDUSDT | 1 | -0.044000 | 5.2866 |
| ATOMUSDT | 2 | +0.020720 | 10.4066 |
| XLMUSDT | 1 | +0.068040 | 5.1541 |

净值：`-1.215535 USDT`。

最大亏损成交：

| UTC | symbol | 平仓方向 | notional | pnl |
|---|---|---|---:|---:|
| 12:01:26 | ADAUSDT | 卖出平多 | 27.0865 | -0.1962 |
| 12:34:14 | PUMPUSDT | 卖出平多 | 37.3332 | -0.194895 |
| 11:27:03 | ICPUSDT | 卖出平多 | 30.0000 | -0.1920 |
| 12:33:50 | AVAXUSDT | 卖出平多 | 27.7050 | -0.1380 |
| 12:34:14 | SOLUSDT | 卖出平多 | 27.1936 | -0.1344 |
| 12:47:34 | ADAUSDT | 卖出平多 | 27.1955 | -0.1090 |
| 12:00:40 | SOLUSDT | 卖出平多 | 27.0592 | -0.0640 |
| 11:43:58 | ICPUSDT | 卖出平多 | 12.5600 | -0.0600 |

## 亏损方向归因

### 1. 核心亏损模式没有变化：VWAP 下方 + 弱 15M 仍开 LONG

典型亏损 LONG 的开仓评分：

| symbol | UTC | 方向 | 4H | 1H | VWAP dev | 15M raw | entry_15m | target | 后续 PnL |
|---|---|---|---|---|---:|---:|---|---:|---:|
| AVAXUSDT | 05:15 | LONG | red_bar_growing | red_bar_growing | -1.14% | 0.24 | `-` | 0.10/0.12 | -0.1110 |
| ICPUSDT | 05:45 | LONG | red_bar_growing | red_bar_growing | -2.82% | 0.12 | `-` | 0.10/0.12 | -0.3360 |
| SOLUSDT | 06:00 | LONG | red_bar_growing | red_bar_growing | -1.87% | 0.24 | `-` | 0.10/0.12 | -0.1984 |
| ADAUSDT | 06:00 | LONG | red_bar_growing | red_bar_growing | -1.32% | 0.24 | `-` | 0.10/0.12 | -0.3052 |
| PUMPUSDT | 11:45 | LONG | red_bar_growing | red_bar_growing | -0.63% | 0.12 | `-` | 0.15/0.18 | -0.194895 |
| AVAXUSDT | 13:15 | LONG | red_bar_growing | red_bar_shrinking | -0.11% | 0.21 | `-` | 0.04/0.042 | 未完全验收 |

这些样本说明：新门控没有把 `entry_15m=-` 当成强约束。即使 15M raw 只有 `0.12~0.24`，只要 4H/1H 同向、VWAPq 不低、总分超过 `0.68`，仍能进入 final。

### 2. 15M gate 的问题：路径存在，但单风险场景约束太弱或 cap 未落到 final sizing

runtime 的 HOLD 归因里能看到路径包含：

```text
score_aggregation > combo_hard_block > counter_trend_long_guard > threshold_check
> flip_bullish_size_guard > 15m_entry_gate > adx_regime_size_cap > final
```

这说明 15M gate 的代码路径至少已经接入。但实际开仓仍显示：

```text
ICPUSDT:
stage=final, dir=long
4H=0.4000(red_bar_growing), 1H=0.1275(red_bar_growing)
VWAP dev=-2.82%
15M=0.0060(-/-, raw=0.12)
total=0.7251/0.6800
target=0.10/0.12

PUMPUSDT:
stage=final, dir=long
VWAP dev=-0.63%
15M=0.0060(-/-, raw=0.12)
total=0.7243/0.6800
target=0.15/0.18
```

按上次设计，`direction=long && below_vwap && raw_15m<0.30` 应该至少降到 probe，尤其 `ICP dev=-2.82%` 不应该仍开 `0.10~0.12`。因此这里有两个可能根因，建议 Claude 重点看代码：

1. `15m_entry_gate` 只在多重风险 `risk_count>=2/3` 时强约束，而 `TREND + ADX>20 + red_bar_growing` 被算作单风险，导致 below-VWAP LONG 仍被放行。
2. gate 计算了 cap，但最终 `target_portion` 可能被后续 stable continuation / final floor / attribution target 覆盖，导致 cap 没真正落到执行 sizing。

### 3. 4H/1H 仍然过度主导方向

亏损 LONG 的评分结构仍是：

```text
4H red_bar_growing = 0.4000
1H red_bar_growing = 0.1275
VWAPa ~= 0.038
15M ~= 0.006~0.012
VOL = 0.0330
RSI rhythm/节奏补分后 total = 0.72~0.85
threshold = 0.68
```

也就是说，15M 和 VWAP 仍只是辅助项，不是方向否决项。`4H + 1H + RSI rhythm` 仍可以把“VWAP 下方的反弹多单”推成 final。

### 4. VOL 弱但仍加分

亏损 LONG 中成交量很弱：

- AVAX `VOL=0.0330(r=0.05)`
- ICP `VOL=0.0330(r=0.01)`
- SOL `VOL=0.0330(r=0.02)`
- ADA `VOL=0.0330(r=0.01)`
- PUMP `VOL=0.0330(r=0.00)`

当前低成交量不是 veto，甚至仍给 `0.0330`。这会帮助弱 15M 反弹多单过线。若保留 15M 硬门槛，VOL 可以不改；若 15M 继续只是 cap，则低 VOL 应该参与更严格的风险计数。

## 上次优化后哪些地方有效

### min_notional / 微仓问题基本不是本窗口瓶颈

本窗口 execution error 为 `0`。ATOM SHORT 出现了数量提升：

```text
[INFO] Adjusted quantity for min_notional:
1.97 -> 2.59 (price=2.012, notional=3.9636->5.2111)
```

这说明小于 2U/5U 导致无法开仓的问题，在最新窗口不再是主要阻塞。唯一 SELL 也成功进入 pending 并最终小幅盈利 `+0.02072`。

### flip_bullish 保护有一定效果

日志里可以看到部分 `flip_bullish` 或深 VWAP 偏离样本被 `vwap_hard_block` / `rsi_extreme_block` / `rsi_1h_direction_block` 拦下。当前最大亏损不再集中在 `flip_bullish`，而是集中在更常见的 `red_bar_growing + red_bar_growing`。

## 上次优化后仍失败的地方

### P0：below-VWAP LONG 的 15M 硬门槛不够硬

证据：`ICP/SOL/ADA/AVAX` 都是 `vwap_dev<-1%` 且 `entry_15m=-`，但仍开 `0.10~0.12` 的 LONG，并随后亏损。建议审查：

```text
direction=long
vwap_dev < -0.5% 或 -1.0%
entry_15m == "-"
raw_15m < 0.30
```

是否应直接 `BLOCK` 或至少 `max_portion=0.042~0.060`，而不是只在 `risk_count>=2` 时限制。

### P0：red_bar_growing + red_bar_growing 需要独立保护

上次主要保护了 `flip_bullish`，但最新亏损主线变成：

```text
4H red_bar_growing + 1H red_bar_growing
```

这个组合在 VWAP 下方并不一定是顺势多头，更可能是下跌后的局部反弹。建议 Claude 评审是否新增：

```text
LONG red_bar_growing + red_bar_growing
且 vwap_dev < 0
且 entry_15m == "-"
=> 不允许 target > 0.06
```

### P1：PUMP 说明 -0.5% 到 -1.0% 的轻中度 VWAP 下方也会亏

PUMP 的 `dev=-0.63%` 看起来不深，但 `raw_15m=0.12`、`VOL r=0.00`，仍开 `0.15/0.18`，后续亏损 `-0.194895`。这说明只用 `vwap_dev<-1%` 做风险因子太宽松。建议把 below-VWAP LONG 风险阈值降到 `-0.5%`，并叠加 `raw_15m` 与 volume。

### P1：JUP 低 VWAPq 高仓位候选仍出现

JUP 在 `08:45` 出现：

```text
VWAPq=0.1528, dev=+1.94%
15M raw=0.12, entry_15m=-
EMA=1.20x/strong
total=0.6941/0.6800
target=0.13/0.1512
execution=noop
```

虽然没有成交，但它说明另一个方向质量问题：价格在 VWAP 上方但 VWAPq 很低、15M 很弱时，仍可能成为较大 LONG 候选。这里不是逆 VWAP，而是追高/位置差，建议不要让 `EMA strong` 独自放大通过。

## 持仓数量问题：bucket 已配置，但总 cap 仍是 5

用户期望：

```text
margin < 5U   -> 小仓位桶，最多 5 个
margin >= 5U  -> 大仓位桶，最多 4 个
总容量应为 9
```

当前配置证据：

```json
"max_active_symbols": 5,
"position_count_limit_by_margin": {
  "enabled": true,
  "small_margin_threshold_usdt": 5.0,
  "max_small_margin_positions": 5,
  "max_large_margin_positions": 4
},
"dynamic_max_active_symbols": {
  "enabled": false,
  "max_active_symbols": 5
}
```

runtime 证据：

```text
候选开仓被跳过：持仓交易对已满(5/5)
ENTRY_GATE_BLOCK gate=active_symbol_capacity threshold=5 value=5
```

典型被总 cap 拦截的 final 候选：

```text
PUMPUSDT rank=3 score=0.7258 stage=final
FETUSDT  rank=4 score=0.7257 stage=final
VETUSDT  rank=5 score=0.7252 stage=final
JUPUSDT  rank=6 score=0.7180 stage=final
POLUSDT  rank=7 score=0.7172 stage=final
RENDER   rank=8 score=0.6949 stage=final
```

归因：bucket 规则没有失败在自身配置，而是先被总 `max_active_symbols=5` 截断。若目标是小仓 5 + 大仓 4，总 cap 必须至少为 `9`，并且 active capacity guard 应在 bucket 维度判定，而不是只看总 symbol 数。

## 动态杠杆问题：配置有 3/4/5，但实盘只出现 3x

用户期望：

```text
动态杠杆修改为 3x / 4x / 5x
```

当前顶层配置已经是：

```json
"min_leverage": 3,
"default_leverage": 4,
"max_leverage": 5
```

但最新 10H 所有开仓日志都是：

```text
杠杆(请求/实际)=3x/3x
```

包括高分样本：

- AVAX `score=0.8551` -> `3x/3x`
- SOL `score=0.8507` -> `3x/3x`
- ADA `score=0.8501` -> `3x/3x`
- ATOM SHORT `score=0.7714` -> `3x/3x`
- PUMP `score=0.7243` -> `3x/3x`

代码/配置中仍有多个 2x cap：

```text
probe_leverage_cap = 2
preflip_trial_max_leverage = 2
red_bar_growing_probe_max_leverage = 2
green_bar_growing_probe_max_leverage = 2
flip_bearish_normal_boll_max_leverage = 2
macd_strategy_v2.calculate_leverage 内部仍有 4/3/2 基础阶梯和 cap 逻辑
decision_engine 最后再 clamp 到 min_leverage=3
```

归因：当前“动态杠杆”实际被各种 2x cap 与最终 min clamp 合并成固定 3x。要实现 3/4/5，不能只改顶层 `min/default/max`，需要统一 MACD V2 内部 leverage ladder 和 probe/trial cap 的语义。

## 给 Claude 的审阅问题

1. 对 `direction=long && vwap_dev < -0.5% && entry_15m=="-" && raw_15m<0.30`，是否应直接 block，还是只允许 `0.042~0.060` probe？
2. `4H red_bar_growing + 1H red_bar_growing` 在 VWAP 下方时是否应独立降级？最新亏损主要不再是 flip_bullish，而是这个组合。
3. 15M gate 当前是否只在 `risk_count>=2` 时足够强？如果 `TREND + ADX>20` 但价格低于 VWAP，是否仍应强制 15M 确认？
4. gate cap 是否真的写回了最终 `target_portion`？PUMP 的 `raw_15m=0.12`、`dev=-0.63%` 仍开 `0.15/0.18`，疑似 cap 未落地或后续被覆盖。
5. `VOL r=0.00~0.05` 仍给 `0.0330` 是否合理？低 volume 是否应在 below-VWAP LONG 中增加 risk_count？
6. 总持仓是否应从 `5` 改为 `9`，并让 bucket 规则先判定“小仓位 <5U 最多 5、大仓位 >=5U 最多 4”？
7. 动态杠杆若目标为 `3/4/5`，是否应把 MACD V2 内部基础阶梯和 `*_max_leverage=2` cap 全部改成与 3/4/5 体系一致，而不是依赖最后的 min clamp？

## 建议的下一步修改方向（待 Claude 评审）

本报告只归因，不改代码。建议评审后统一处理：

1. 把 below-VWAP LONG 的 15M 门槛升级为真正 hard gate：`vwap_dev<-0.5% && raw_15m<0.30` 至少 probe；`vwap_dev<-1% && entry_15m=="-"` 优先 block。
2. 新增 `red_bar_growing + red_bar_growing` 的 below-VWAP 专项保护，不只保护 `flip_bullish`。
3. 检查 `15m_entry_gate` / `adx_regime_size_cap` 的 cap 是否最终写回执行层 target，避免被后续 sizing/floor 覆盖。
4. 把 `fund_flow.max_active_symbols` 改为 `9`，并同步 dynamic cap / engine override / pre-live assertions，保证不再出现 `threshold=5 value=5`。
5. 统一动态杠杆为 `3/4/5`：高分 final 用 5x，中等 final 用 4x，probe/trial/低分用 3x；移除或上调残留 `2x` cap，避免全部被 clamp 成 3x。

## 单句归因

最新 10H 的亏损根因是：上次新增的 15M/flip/ADX 门控没有真正限制主亏损路径，系统仍把 VWAP 下方、`entry_15m=-`、15M raw 很弱的 `4H red_bar_growing + 1H red_bar_growing` 反弹信号开成 final LONG；同时持仓数量仍被总 `max_active_symbols=5` 截断，bucket 容量没有生效，动态杠杆配置虽然写成 3/4/5，但实盘因内部 cap 和最终 clamp 只表现为固定 3x。
