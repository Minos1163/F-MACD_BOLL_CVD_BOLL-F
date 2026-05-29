# 2026-05-20 最新 36H 开仓方向亏损归因：方向指标权重如何把反弹/回抽误判成 final

审阅对象：Claude  
分析时间：2026-05-20  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
有效窗口：`2026-05-18 13:00:15 UTC` 到 `2026-05-20 01:00:15 UTC`，北京时间为 `2026-05-18 21:00:15` 到 `2026-05-20 09:00:15`。

窗口端点来自最新 `fund_flow_attribution.jsonl` 的最大时间戳 `2026-05-20T01:00:15.774453+00:00`，向前倒推 36H。

数据来源：

- `logs\2026-05\2026-05-18\fund_flow_attribution.jsonl(.gz)`
- `logs\2026-05\2026-05-19\fund_flow_attribution.jsonl(.gz)`
- `logs\2026-05\2026-05-20\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-18\trade_fills_utc.csv`
- `logs\2026-05\2026-05-19\trade_fills_utc.csv`
- `runtime.out.18.log / runtime.out.00.log / runtime.out.06.log / runtime.out.12.log / runtime.out.18.log`

说明：`trade_fills_utc.csv` 在不同日期文件里存在重叠成交行。本报告按 `订单ID + 成交ID + symbol + time + side + qty + price` 去重后统计。

## 结论摘要

最新 36H 去重后成交 `125` 条，已实现净 PnL 约 `-0.8249 USDT`。主要负贡献来自 `ETCUSDT -0.8829`、`BCHUSDT -0.8311`、`POLUSDT -0.3745`、`JSTUSDT -0.3534`、`ATOMUSDT -0.3253`、`VETUSDT -0.3246`。其中 `TON/ZRO/WLD` 有较大正贡献，说明不是执行系统完全失效，而是部分方向识别质量差。

方向亏损主因不是单一指标错误，而是评分结构过度依赖 `4H primary` 与 RSI rhythm/EMA 放大：4H 权重最高，且 `red_bar_growing/green_bar_growing/flip_bullish/flip_bearish` 可以直接给 `0.40` 或接近 `0.40` 的分；1H 同向只要增长就给 `0.1275`；RSI rhythm 在很多样本里继续给约 `0.30` 的隐含贡献；VWAP 只占 `0.05`，15M 只占 `0.05`，因此“价格仍在 VWAP 下方、15M 入场很弱、ADX 偏弱/NO_TRADE”的信号仍能过 final。

最明显的不合理现象：36H 内解析到的 `29` 笔 BUY 开仓中，`25` 笔是在 VWAP 下方开多；`16/29` 笔 BUY 的 `15M raw < 0.30`；`6/29` 笔 BUY 发生在 `ADX < 20` 或 `engine=NO_TRADE`。这说明我们此前加的 counter-trend long guard 没有把“VWAP 下方 + 弱 15M/弱趋势”的反弹多单降级到足够小或 block。

## 当前开仓方向指标与权重

live 配置与代码确认的 MACD V2 方向评分权重如下：

| 指标 | 配置权重/效果 | 说明 |
|---|---:|---|
| `4H primary direction` | `0.40` | 最主要方向来源；4H 同向 growing/flip 可给满分或接近满分 |
| `1H direction` | `0.15` | 同向 flip 给 `0.15`，同向 growing 给 `0.15 * 0.85 = 0.1275` |
| `RSI rhythm` | `0.30` | 节奏/反向/soft penalty 进入 weighted score；许多 final 样本靠它补足阈值 |
| `VWAP alpha` | `0.05` | `VWAPa = weight_vwap * location_score`，对方向只小幅加减 |
| `15M entry` | `0.05` | `raw_15m * 0.05`，即 raw=0.24 只给 `0.012` |
| `Volume` | `0.10` | `r<=1.0` 仍给 `0.033`，低成交量不是强否定 |
| `EMA/BOLL structure` | `0.60x / 1.00x / 1.20x` | 主要作用在 4H trend score 上，strong 可把 4H 分放大到上限 |

实际 scoring 近似为：

```text
total =
  score_1h
  + min((score_4h_base * EMA_multiplier) + folded_4h_bonus, 0.40)
  + score_rsi_rhythm_weighted
  + VWAP_alpha
  + score_15m
  + score_volume
  - overheat_penalty
  后续再乘 RSI/flip/cooling/neutral penalty
```

因此，若 `4H=0.40`、`1H=0.1275`、`RSI rhythm≈0.25~0.30`、`VOL=0.033`，即使 `VWAPa` 和 `15M` 很弱，也可以轻松超过 `0.68`。

## 36H 交易与亏损总览

去重成交：

| 项 | 数量/金额 |
|---|---:|
| fills | 125 |
| realized pnl | `-0.824888 USDT` |
| open decisions | 44 |
| BUY opens | 29 |
| SELL opens | 15 |

按 symbol 净 PnL 排序：

| symbol | realized pnl | fills |
|---|---:|---:|
| ETCUSDT | -0.88290 | 3 |
| BCHUSDT | -0.83106 | 6 |
| POLUSDT | -0.37446 | 4 |
| JSTUSDT | -0.35343 | 5 |
| ATOMUSDT | -0.32531 | 8 |
| VETUSDT | -0.32460 | 5 |
| AVAXUSDT | -0.21800 | 5 |
| ONDOUSDT | -0.19169 | 14 |
| ADAUSDT | -0.15210 | 2 |
| FETUSDT | -0.14220 | 6 |
| RENDERUSDT | -0.13420 | 5 |
| SUIUSDT | -0.10935 | 5 |
| TONUSDT | +1.17715 | 7 |
| ZROUSDT | +1.03675 | 11 |
| WLDUSDT | +0.79140 | 6 |

大额亏损成交：

| UTC | symbol | 平仓方向 | 对应仓位 | pnl | notional |
|---|---|---|---|---:|---:|
| 05-19 22:30 | ETCUSDT | 卖出 | LONG | -0.88290 | 72.16290 |
| 05-19 13:30 | BCHUSDT | 卖出 | LONG | -0.52920 | 39.97035 |
| 05-19 11:21 | POLUSDT | 卖出 | LONG | -0.37446 | 42.72162 |
| 05-19 14:20 | ALGOUSDT | 卖出 | LONG | -0.27000 | 50.62500 |
| 05-18 14:35 | TONUSDT | 卖出 | LONG | -0.26460 | 10.47330 |
| 05-18 13:37 | ONDOUSDT | 卖出 | LONG | -0.22300 | 15.21752 |
| 05-18 14:19 | ONDOUSDT | 卖出 | LONG | -0.21707 | 15.11959 |
| 05-19 16:14 | JSTUSDT | 买入 | SHORT | -0.18864 | 35.82588 |
| 05-18 14:18 | ZROUSDT | 卖出 | LONG | -0.18843 | 11.21032 |
| 05-18 14:18 | VETUSDT | 卖出 | LONG | -0.16844 | 16.50177 |

## 开仓方向模式统计

开仓 MACD 组合：

| 方向 | 4H + 1H 组合 | count | 主要问题 |
|---|---|---:|---|
| BUY | `red_bar_growing + red_bar_growing` | 13 | 局部多头反弹被当成 final 多头 |
| BUY | `red_bar_growing + red_bar_shrinking` | 9 | 1H 多头动能收缩仍开多 |
| BUY | `flip_bullish + red_bar_growing` | 6 | 反转早期信号过度乐观 |
| SELL | `red_bar_shrinking + green_bar_growing` | 7 | trial 空头，4H 仍偏多/收缩 |
| SELL | `green_bar_growing + green_bar_growing` | 5 | 顺空但 VWAP 低分/深偏离，追空风险 |

BUY 方向质量：

| 条件 | count |
|---|---:|
| BUY 总数 | 29 |
| BUY 且 VWAP dev < 0 | 25 |
| BUY 且 15M raw < 0.30 | 16 |
| BUY 且 ADX < 20 或 `NO_TRADE` | 6 |

SHORT 方向质量：

| 条件 | count |
|---|---:|
| SELL 总数 | 15 |
| SELL 且 VWAPq < 0.12 | 7 |
| SELL trial=True | 7 |

这说明方向错误有两条主线：

1. `LONG` 过度放行：大多数多单是在 VWAP 下方开，15M 确认很弱，仍由 4H/RSI/EMA 推过 final。
2. `SHORT` 试探空质量不稳定：部分短空来自 `red_bar_shrinking + green_bar_growing` 或低 VWAPq 深偏离，属于反弹/回抽阶段做空，容易被短线反弹打掉。

## 典型亏损开仓归因

### 1. ETCUSDT：最大亏损，多头 final 但 15M 很弱

开仓：

```text
2026-05-19 18:00 UTC
[ETCUSDT] BUY target=0.27, leverage=3
engine=TREND, adx=32.42
MACD_V2: stage=final, dir=long
4H=0.4000(red_bar_growing)
1H=0.1275(red_bar_growing)
VWAPq=0.6226, VWAPa=0.0311(dev=+0.01%)
15M=0.0120(raw=0.24)
VOL=0.0330
EMA=1.20x/strong
total=0.8436/0.6800
```

平仓亏损：

```text
2026-05-19 22:30 UTC ETCUSDT 卖出平多 pnl=-0.8829
```

归因：ETC 不是 VWAP 下方抢反弹，而是“1H/4H 同向 red_bar_growing + EMA strong”给了很高分，但 15M raw 只有 `0.24`，没有足够短周期确认。`EMA=1.20x` 把 4H 分推满，导致总分远高于阈值。这里的问题是大仓 `target=0.27` 建立在弱 15M 上，入场时机太粗。

### 2. BCHUSDT：flip_bullish/red_bar_growing 反转多单，15M 不确认

开仓：

```text
2026-05-19 13:00 UTC
[BCHUSDT] BUY target=0.17, leverage=3
engine=TREND, adx=22.33
MACD_V2: stage=final, dir=long
4H=0.4000(flip_bullish)
1H=0.1275(red_bar_growing)
VWAPq=0.8205, VWAPa=0.0410(dev=-0.91%)
15M=0.0090(raw=0.18)
VOL=0.0330
EMA=1.00x/normal
total=0.7905/0.6400
```

平仓亏损：

```text
2026-05-19 13:30 UTC BCHUSDT 卖出平多 pnl=-0.5292
```

归因：`flip_bullish + red_bar_growing` 被当作强反转确认，阈值仅 `0.64`，但价格仍低于 VWAP，15M raw 只有 `0.18`。这类信号应当是“反转待确认”，不是大仓 final。BCH 说明 flip_bullish 阈值和 15M 最小确认过松。

### 3. POLUSDT：弱趋势下 VWAP 下方开大多

开仓：

```text
2026-05-19 04:30 UTC
[POLUSDT] BUY target=0.17, leverage=3
engine=TREND, adx=17.29
MACD_V2: stage=final, dir=long
4H=0.4000(red_bar_growing)
1H=0.1275(red_bar_growing)
VWAPq=0.7969, VWAPa=0.0398(dev=-0.80%)
15M=0.0060(raw=0.12)
VOL=0.0330
EMA=1.00x/normal
total=0.7263/0.6800
```

平仓亏损：

```text
2026-05-19 11:21 UTC POLUSDT 卖出平多 pnl=-0.37446
```

归因：ADX `17.29` 是弱趋势/临界趋势，15M raw `0.12` 很弱，仍开到 `target=0.17`。这里不是方向完全没有多头信号，而是仓位与确认强度不匹配：弱趋势 + 15M 弱确认应 cap 到 probe，而不是接近 17% 保证金占比。

### 4. VETUSDT / ONDOUSDT：VWAP 下方深负偏离仍开多

VET 开仓：

```text
2026-05-18 18:00 UTC
BUY target=0.05
4H=0.4000(red_bar_growing), 1H=0.1275(red_bar_growing)
VWAP dev=-4.47%, 15M raw=0.27, total=0.8760/0.6800
```

ONDO 开仓：

```text
2026-05-18 13:15/14:00 UTC
BUY target=0.05
4H=0.4000(red_bar_growing), 1H=0.1275(red_bar_growing)
VWAP dev=-6.12% / -5.78%
15M raw=0.12
total=0.7191/0.6800
```

亏损：

```text
VET: -0.1684 / -0.1514
ONDO: -0.2230 / -0.2171
```

归因：这是最典型的“VWAP 下方抢反弹多单”。虽然 VWAPq 看起来不低，但 `dev=-4%~-6%` 对 LONG 是逆势风险。当前 VWAP 只用 `0.05` 的 alpha 分，无法约束方向；counter-trend long guard 没有对 `dev<-3%` 的高 ADX/TREND 多单做足够 block/cap。

### 5. ATOMUSDT / JSTUSDT：SHORT 方向的低 VWAP 分或反弹试探空

ATOM SHORT：

```text
2026-05-18 20:00 UTC
SELL target=0.09
4H=0.4000(green_bar_growing), 1H=0.0000(green_bar_shrinking)
VWAPq=0.7759(dev=+0.66%), 15M raw=0.27
total=0.7175/0.6900
```

后续：

```text
2026-05-18 22:26 UTC 买入平空 pnl=-0.1977
```

JST：

```text
2026-05-19 03:00 UTC 先 BUY 开多，之后亏损平多
2026-05-19 16:14 UTC 买入平空 pnl=-0.2203
```

归因：SHORT 亏损样本数量不如 LONG 多，但问题是 trial/回抽空容易在反弹段被打。尤其 `red_bar_shrinking + green_bar_growing` 这类 trial 空，本质是 4H 多头收缩或不明确、1H 局部转空，不是强空趋势。

## 为什么最终方向会错

### 1. 4H 权重过高，局部 4H red_bar_growing 被当作可靠多头趋势

4H 方向权重 `0.40` 是最大单项。`red_bar_growing`、`flip_bullish` 能给 `0.40`，配合 1H 同向 `0.1275`，未看 RSI/VWAP/15M 前已经有 `0.5275`。阈值多数是 `0.64~0.68`，剩余只需要 RSI rhythm/VWAP/Volume 补一点即可。

这会把“熊市或弱势中的局部反弹”误判为 final 多头。

### 2. VWAP 对方向的约束不够，尤其是 LONG 低于 VWAP

VWAP alpha 权重只有 `0.05`，日志中 `VWAPa` 常为 `0.03~0.04`。对 LONG 来说，`dev=-4%~-6%` 应该是逆势风险，但在当前评分里只要 `VWAPq` 不低，仍可能变成加分。

样本：ONDO `dev=-6.12%/-5.78%`、VET `dev=-4.47%`、FET `dev=-3.99%`、SUI `dev=-2.76%`，都能 final BUY。

### 3. 15M 入场确认权重太小，无法否决错误方向

15M 权重 `0.05`，raw=0.12 只贡献 `0.006`，raw=0.24 只贡献 `0.012`。亏损多单里大量 `entry_15m=-`，说明没有明确 15M 触发，但 final 仍通过。

这意味着 15M 当前只是小加分项，不是入场确认门槛。

### 4. EMA/BOLL strong 乘数会放大 4H 方向，但不验证方向是否是反弹

EMA strong 是 `1.20x`，会作用到 4H trend score。ETC、SUI、JST、TON 等样本里 strong 让总分更容易过阈值。问题是 EMA/BOLL 结构在反弹/均值回归阶段也可能显示 strong，不一定代表未来方向延续。

### 5. `NO_TRADE` 或弱 ADX 仍可开较大多单

TON 两次 `engine=NO_TRADE` 仍能 BUY；POL `ADX=17.29` 仍开 `target=0.17`；SUI `ADX=17.05` 仍 BUY。说明 regime/ADX 没有作为大仓方向准入门槛，只是上下文标签。

## 不合理门槛排序

### P0：LONG 在 VWAP 下方时缺少强制方向保护

证据：`25/29` 个 BUY 在 VWAP 下方。亏损样本 ONDO/VET/FET/SUI/BCH/POL 都符合“价格低于 VWAP，但 4H/1H 局部多头评分过线”。

建议 Claude 审查：`direction=long && vwap_dev < -1%` 是否至少要求 `15M raw >= 0.30`；`vwap_dev < -3%` 是否应直接 block，除非 15M spring/突破确认非常强。

### P0：15M 只是加分项，不是入场门

证据：`16/29` BUY 的 `15M raw < 0.30`。BCH `raw=0.18`、POL `raw=0.12`、SUI `raw=0.12`、ONDO `raw=0.12` 都开仓或加仓后亏损。

建议：对 LONG 反转/低于 VWAP/ADX<20 的场景，15M 应从 `0.05` 小权重变成硬门槛或仓位 cap。

### P0：flip_bullish 阈值过低且允许大仓

BCH `flip_bullish + red_bar_growing` 以 `0.7905/0.6400` 开 `target=0.17`，30 分钟后亏损平仓。flip_bullish 本质是反转早期，阈值不应低于普通 red_bar_growing，至少应要求 VWAP 上方或 15M 强确认。

### P1：弱 ADX / NO_TRADE 不应允许大仓 final

POL `ADX=17.29` 开 `0.17`，TON `NO_TRADE` 仍开多，SUI `ADX=17.05` 仍 BUY。建议 ADX<20 或 NO_TRADE 的 new entry 只允许 `0.04~0.06` probe。

### P1：SHORT trial 路径要区分“强空延续”与“反弹段试探空”

`red_bar_shrinking + green_bar_growing` 的 SHORT trial 有 7 笔。它可以贡献开仓数量，但方向质量波动大。若 VWAPq 低或 dev 深负，说明价格已在低位，继续追空更像追跌，建议 cap 或要求 15M 明确转弱。

## 给 Claude 的审阅问题

1. `4H red_bar_growing + 1H red_bar_growing` 在 `vwap_dev < 0` 时，是否应视为“反弹多”而不是“趋势多”？是否必须要求 `15M raw >= 0.30`？
2. `flip_bullish + red_bar_growing` 是否不应使用 `0.64` 低阈值？BCH 的亏损说明它更像早期反转试错。
3. `direction=long && vwap_dev < -3%` 是否应该 hard block？如果不 block，是否必须 cap 到 `0.04~0.06`？
4. `ADX < 20` 或 `engine=NO_TRADE` 的 new BUY 是否应该禁止大仓，只允许 probe？
5. 15M 权重 `0.05` 是否过低？在方向确认里它是否应从 score component 升级为 gate component？
6. EMA strong `1.20x` 是否应该只在 price/VWAP 同向且 15M 同向时放大 4H，否则会放大反弹假信号？
7. `red_bar_shrinking + green_bar_growing` SHORT trial 是否需要更严格的 VWAP/15M 条件，避免在低位追空后被反弹打掉？

## 单句归因

最新 36H 的亏损根因是：开仓方向由高权重 4H MACD 与 RSI/EMA 放大主导，VWAP 与 15M 只承担弱加分，导致系统把 VWAP 下方、15M 弱确认、弱 ADX/NO_TRADE 中的局部反弹误判为 final 多头；同时部分 SHORT trial 在低 VWAP 分或反弹初段追空，方向质量不稳定。

