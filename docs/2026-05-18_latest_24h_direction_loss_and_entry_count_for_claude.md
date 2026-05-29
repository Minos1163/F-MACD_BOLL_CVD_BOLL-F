# 2026-05-18 最新 24H 方向亏损与开仓数量归因

审阅对象：Claude  
分析时间：2026-05-18  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
有效窗口：`2026-05-17 04:15:15 UTC` 到 `2026-05-18 04:15:15 UTC`，北京时间为 `2026-05-17 12:15:15` 到 `2026-05-18 12:15:15`。

数据来源：

- `logs\2026-05\2026-05-17\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-17\fund_flow_attribution.jsonl.gz`
- `logs\2026-05\2026-05-18\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-17\trade_fills_utc.csv`
- `logs\2026-05\2026-05-18\trade_fills_utc.csv`
- `runtime.out.12.log / runtime.out.18.log / runtime.out.00.log / runtime.out.06.log / runtime.out.12.log`

## 结论摘要

最新 24H 的亏损方向问题集中在多单：系统在下跌/偏空环境里，把局部 `red_bar_growing`、`flip_bullish` 或 `1H red_bar_growing` 当成多头确认，但没有要求“价格重新站回 VWAP 上方”、没有要求 15M 给出足够强确认，也没有把低 ADX/RANGE 下的反弹多单降级为 probe。因此 TON、RENDER、ETC 这几笔亏损多单本质上都是“反弹做多”，不是强趋势做多。

最后两个亏损成交需要先统一口径：`2026-05-18 03:00:15 UTC` 和 `03:15:15 UTC` 的亏损成交都来自同一笔 `TONUSDT LONG`，不是两笔独立策略。TON 在 `02:15:15 UTC` 开多，45 分钟内被 ExitGuard 因反向信号确认平掉，合计亏损约 `-1.24008 USDT`。开仓时价格已经低于 VWAP `-4.57%`，ADX 只有 `17.38`，15M 只给了 `0.0135` 分，但总分仍达到 `0.8834/0.6800` 并以 `26.775%` 目标占比开多。

开单数量稍显不足不是因为没有信号。窗口内有 `58` 次开仓尝试，其中 `48` 次是 SELL，`10` 次是 BUY；但 `47` 次 SELL 全部被执行层 `min_notional` 拒绝。更关键的是这些 SHORT 候选的目标仓位被策略层压到 `0.000087 ~ 0.005`，对应名义价值多为 `0.01U ~ 0.56U`，远低于当前普通品种 `2U` 最小开仓。也就是说，方向上想做空的信号不少，但仓位压缩过度，导致“确认开仓方向到达执行层后被最小名义价值否定”。

## 24H 数据总览

| 项 | 数量 |
|---|---:|
| decision events | 2679 |
| HOLD | 2614 |
| SELL decisions | 48 |
| BUY decisions | 10 |
| CLOSE decisions | 7 |
| execution noop | 2614 |
| execution error | 47 |
| execution pending | 16 |
| execution success | 2 |

开仓尝试执行结果：

| 方向 | 状态 | 数量 |
|---|---|---:|
| SELL | error | 47 |
| SELL | pending | 1 |
| BUY | pending | 10 |

`47` 个 error 全部是 `min_notional failed`。这说明开仓数量不足的第一执行层瓶颈是：SHORT 候选通过策略后，仓位小到无法达到最小可交易金额。

## 成交与盈亏

24H 内成交 `38` 条，已实现净盈亏约 `+2.32927 USDT`。净盈利主要来自 ZEC，亏损主要来自 TON、RENDER、ETC。

| symbol | realized pnl |
|---|---:|
| ZECUSDT | +2.90831 |
| HYPEUSDT | +0.23510 |
| JSTUSDT | +0.04296 |
| TONUSDT | +0.03012 |
| MORPHOUSDT | 0.00000 |
| ATOMUSDT | -0.10602 |
| ETCUSDT | -0.15300 |
| RENDERUSDT | -0.62820 |

说明：TONUSDT 24H 净值为正，是因为前面有一笔 TON 盈利抵消了最后亏损。最后一笔 TON 独立多单本身亏损约 `-1.24008 USDT`。

亏损成交明细：

| UTC | symbol | side | price | qty | notional | pnl |
|---|---|---|---:|---:|---:|---:|
| 2026-05-17 05:45:15 | ATOMUSDT | 卖出平多 | 2.0370 | 2.79 + 2.79 | 11.36646 | -0.10602 |
| 2026-05-17 14:15:15 | RENDERUSDT | 卖出平多 | 1.8240 | 34.7 + 0.2 | 63.65760 | -0.62820 |
| 2026-05-17 14:45:15 | ETCUSDT | 卖出平多 | 9.0100 | 2.25 | 20.27250 | -0.15300 |
| 2026-05-18 03:00:15 | TONUSDT | 卖出平多 | 1.9331 | 23.3 + 23.3 | 90.08246 | -1.23490 |
| 2026-05-18 03:15:15 | TONUSDT | 卖出平多 | 1.9337 | 0.2 | 0.38674 | -0.00518 |

## 最后亏损仓位：TONUSDT 为什么逆向开多

开仓日志：

```text
2026-05-18 02:15:15 UTC
[TONUSDT] 决策=BUY | 状态=pending | 目标占比=0.27
engine=TREND, direction=BOTH, adx=17.38, atr_pct=0.0188
MACD_V2评分: stage=final, dir=long,
primary=4H:0.4000(red_bar_growing),
1H=0.1275(red_bar_growing),
VWAPq=0.7882, VWAPa=0.0394(dev=-4.57%),
15M=0.0135(-/-, raw=0.27),
VOL=0.0330, EMA=1.00x/normal,
total=0.8834/0.6800
```

平仓日志：

```text
2026-05-18 03:00:15 UTC
EXIT_SIGNAL_GUARD_REDUCE: reverse signal confirmed 2 bars, mae=-1.41%, reduce 50%
primary=4H:0.2940(red_bar_growing), 1H=0.0000(red_bar_shrinking),
VWAP dev=-5.84%, EMA=0.60x/weak, total=0.3058/0.6800

2026-05-18 03:15:15 UTC
EXIT_SIGNAL_GUARD_CLOSE: reverse signal confirmed 3 bars, mae=-1.44%, full close
primary=4H:0.2940(red_bar_growing), 1H=0.0000(flip_bearish),
VWAP dev=-5.80%, EMA=0.60x/weak, total=0.4570/0.6800
```

TON 的问题不是执行误差，而是开仓方向质量：

1. `4H red_bar_growing + 1H red_bar_growing` 被当成强多头确认，但价格仍低于 VWAP `-4.57%`。在偏空/下跌环境里，做多时价格低于 VWAP 不是顺势优势，而是“从均价下方抢反弹”。
2. ADX 只有 `17.38`，趋势强度并不高。日志虽然写 `engine=TREND`，但这个 ADX 更像弱趋势/临界趋势，不足以支撑 `0.26775` 这种目标占比。
3. 15M 只贡献 `0.0135`，`entry_15m=-`，说明短周期没有强入场确认。总分主要来自 4H/1H 与 VWAPq，而不是入场触发本身。
4. 开仓后 30 到 45 分钟内，1H 从 `red_bar_growing` 退化到 `red_bar_shrinking` 再到 `flip_bearish`，ExitGuard 正确识别反向，但入场阶段没有提前要求更严格的多头确认。

单句归因：TON 是“价格低于 VWAP 的弱趋势反弹多单”，被 MACD 局部多头评分放大为 final 高分。

## 其他亏损多单方向归因

### RENDERUSDT：RANGE 低 ADX 反弹多单被当成 final

开仓：

```text
2026-05-17 09:15:15 UTC
[RENDERUSDT] 决策=BUY | 目标占比=0.27
engine=RANGE, adx=12.76
primary=4H:0.4000(flip_bullish), 1H=0.1275(red_bar_growing),
VWAPq=0.8120, VWAP dev=-1.48%,
15M=0.0135(-/-, raw=0.27),
total=0.8846/0.6400
```

平仓：

```text
2026-05-17 14:15:15 UTC
ExitGuard CLOSE: reverse signal confirmed 13 bars, mae=-0.81%, full close
engine=RANGE, adx=8.63
primary=4H red_bar_growing, 1H red_bar_shrinking,
EMA=0.60x/weak, rsi_1h_direction_block
```

RENDER 的不合理点：

- `engine=RANGE` 且 ADX `12.76`，不应给低周期反弹多单 `0.26775` 目标占比。
- `flip_bullish + red_bar_growing` 在 RANGE 里更像反弹确认，而不是趋势反转确认。
- 价格仍低于 VWAP `-1.48%`，15M 也没有强确认，但最终总分很高。

### ETCUSDT：4H 熊力收缩 + 1H 反弹，被 trial path 开成长单

开仓：

```text
2026-05-17 05:15:15 UTC
[ETCUSDT] 决策=BUY | 目标占比=0.04
engine=TREND, adx=25.42
primary=4H:0.3487(green_bar_shrinking),
1H=0.1275(red_bar_growing),
VWAP dev=-1.96%,
15M=0.0120(-/-, raw=0.24),
total=0.7962/0.6600,
trial=True
```

平仓：

```text
2026-05-17 14:45:15 UTC
ExitGuard CLOSE: reverse signal confirmed 7 bars, mae=-0.82%, full close
```

ETC 是最典型的“熊市逆向开多”样本：`4H green_bar_shrinking` 不是明确多头，只是空头动能衰减；`1H red_bar_growing` 是短线反弹。这个组合在偏空市场里应是 partial/probe/shadow，而不是以 `final` 通过。

## 为什么会在熊市逆向开多

### 1. 方向模型缺少市场/候选池级别的 bearish guard

当前方向判断更偏单标的本地 MACD 组合：只要某个币的 `4H/1H` 出现 `red_bar_growing` 或 `flip_bullish`，就可能被当作多头确认。它没有把“全局候选池偏空”作为做多降级条件。

窗口内实际现象是：

- 开仓尝试里 SELL 有 `48` 次，BUY 有 `10` 次。
- 47 个 SELL 不是被方向否定，而是到执行层后 `min_notional failed`。
- 同时最后几个亏损仓位全是 LONG，说明系统在偏空环境里没有禁止局部反弹多单。

### 2. 做多低于 VWAP 没有被视为逆势风险

亏损多单开仓时都在 VWAP 下方：

| symbol | 开仓方向 | VWAP dev | 结果 |
|---|---|---:|---|
| TONUSDT | LONG | -4.57% | 45 分钟内止损式退出 |
| RENDERUSDT | LONG | -1.48% | 亏损退出 |
| ETCUSDT | LONG | -1.96% | 亏损退出 |

这和之前 SHORT 的 VWAP 消融逻辑不同。做空时价格低于 VWAP 是顺势偏离；做多时价格低于 VWAP 是从均价下方抢反弹。在熊市/偏空环境里，这应该至少 penalty/probe，而不是继续给高 VWAPq 后通过 final。

### 3. 15M 入场确认权重太弱

三笔亏损多单 15M 分数都很低：

| symbol | 15M score | entry_15m | raw |
|---|---:|---|---:|
| TONUSDT | 0.0135 | `-` | 0.27 |
| RENDERUSDT | 0.0135 | `-` | 0.27 |
| ETCUSDT | 0.0120 | `-` | 0.24 |

这说明 final 通过几乎不依赖 15M 明确入场。对于逆环境多单，15M 应该是必需确认，而不是很小的加分项。

### 4. RANGE / 弱趋势场景没有限制多单仓位

RENDER 在 `RANGE, ADX=12.76` 下开了 `0.26775`，TON 在 `ADX=17.38` 下也开了 `0.26775`。这两个都不是强趋势条件。若继续允许这些多单，至少应降为小 probe 或要求更强 15M/成交量确认。

### 5. `green_bar_shrinking + red_bar_growing` 被过度乐观解释

ETC 的 `4H green_bar_shrinking + 1H red_bar_growing` 被 `trial=True` 放进 final。这个组合在空头背景中更像“空头衰减后的短反弹”，不是多头趋势确认。它应该由 partial confirm/shadow 管理，而不是正常 long final。

## 开仓数量不足的真正瓶颈

开单少不是因为策略没有产生开仓方向，而是已确认的 SHORT 仓位被压得太小。

执行层拒绝分布：

| symbol | min_notional error |
|---|---:|
| JSTUSDT | 10 |
| ATOMUSDT | 6 |
| VETUSDT | 6 |
| POLUSDT | 5 |
| AAVEUSDT | 5 |
| AVAXUSDT | 4 |
| SOLUSDT | 3 |
| ETCUSDT | 2 |
| XRPUSDT | 2 |
| DOGEUSDT | 1 |
| RENDERUSDT | 1 |
| ALGOUSDT | 1 |
| XLMUSDT | 1 |

被拒目标仓位分布：

| target_portion | count |
|---:|---:|
| 0.000315 | 20 |
| 0.000630 | 6 |
| 0.000175 | 6 |
| 0.000787 | 5 |
| 0.000087 | 5 |
| 0.000840 | 2 |
| 0.001312 | 2 |
| 0.005000 | 1 |

典型拒单：

```text
JSTUSDT target=0.000630, signal_score=0.7569, short, min_notional failed: 0.07U < 2.00U
ATOMUSDT target=0.000175, signal_score=0.7463, short, min_notional failed: 0.02U < 2.00U
AVAXUSDT target=0.000787, signal_score=0.8181, short, min_notional failed: 0.09U < 2.00U
DOGEUSDT target=0.000315, signal_score=0.6965, short, min_notional failed: 0.04U < 2.00U
```

当前配置已经有：

```json
"min_open_notional": {
  "default_usdt": 2.0,
  "btc_usdt": 5.0,
  "major_usdt": 5.0
}
```

所以问题不是 `2U` 太高，而是策略仓位计算输出了不可执行的微仓。按账户权益约 `111U` 粗算，普通品种 `2U` 对应 target portion 约 `0.018`。当前大量 SHORT 输出 `0.000315`，只有最低可执行仓位的约 `1.7%`。

可疑来源是 `green_bar_growing_probe_position_penalty=0.1` 以及多层仓位缩放叠加。代码里 `green_bar_growing` probe overlay 会继续乘以 `0.1`，如果叠加 VWAP/vol/rsi/session 缩放，就会把本来可以交易的 SHORT 压成 `0.01U ~ 0.10U`。

## 不合理门槛排序

### P0：LONG 方向准入缺少“低于 VWAP + 弱趋势/熊市”的保护

证据：TON、RENDER、ETC 亏损多单全部是在 VWAP 下方开多，且 15M 确认很弱。建议 Claude 重点审查：做多时 `dev < 0` 是否应该在 bearish/weak trend/range 场景下变成 hard block 或至少 probe cap。

### P0：`4H green_bar_shrinking + 1H red_bar_growing` 不应直接 final 开多

证据：ETC 以 `trial=True`、`4H green_bar_shrinking`、`1H red_bar_growing` 开 LONG 并亏损。这个组合更像空头回抽，不是多头趋势确认。

### P1：15M 对逆环境多单约束过弱

证据：TON/RENDER/ETC 的 15M 分数均约 `0.012 ~ 0.0135`，但仍然 final。建议逆环境 LONG 必须要求 `15M raw >= 0.30` 或明确 `entry_15m` 非空，否则只能 shadow/probe。

### P1：RANGE/低 ADX 多单仓位过大

证据：RENDER `engine=RANGE, adx=12.76` 仍开 `0.26775`；TON `adx=17.38` 也开 `0.26775`。建议 RANGE 或 ADX < 18 的 LONG 上限降到 `0.04 ~ 0.06`，除非价格在 VWAP 上方且 15M/volume 同向。

### P0/P1：SHORT 候选仓位压缩到不可执行

证据：47 个 SELL 全部 `min_notional failed`，且多数目标仓位 `0.000315`。建议不要降低普通品种 `2U` 最小金额，而是让已经通过方向和分数的 SHORT 至少提升到可执行的 `2U` notional，或在策略层提前标记为 shadow，避免执行层 error。

## 给 Claude 的审阅问题

1. 做多时价格低于 VWAP，且市场/候选池偏空时，是否应该判为 counter-trend long？TON 的 `dev=-4.57%` 是否应直接 block，还是只允许 `0.04~0.06` probe？
2. `4H red_bar_growing + 1H red_bar_growing` 在 ADX 仅 `17.38` 且 15M 无确认时，是否足以支持 `0.26775` 多单？
3. `4H flip_bullish + 1H red_bar_growing` 在 `RANGE, ADX=12.76` 下是否应该 final，还是必须等待突破 VWAP/15M 强确认？
4. `4H green_bar_shrinking + 1H red_bar_growing` 是否应从 LONG final 改为 partial confirm shadow/probe？ETC 亏损说明它可能只是熊市反弹。
5. `green_bar_growing_probe_position_penalty=0.1` 是否过度压缩 SHORT，导致大量 bearish short 候选到执行层后变成 `0.01U~0.10U` 微仓？是否应对通过分数的 SHORT 设置 `min_executable_notional=2U` floor？
6. 当前 `major_usdt=5.0` 会让 SOL/XRP 等也按 5U 最小名义价值处理。如果设计意图是“只有 BTC 5U，其余 2U”，是否应把 `major_usdt` 降为 `2.0` 或从 major_symbols 移除非 BTC？

## 建议的下一步消融

本报告只归因，不改代码。建议下一步按以下顺序审：

1. 先加 LONG 逆势保护：`direction=long && vwap_dev < 0 && (market_bias=bearish or adx<18 or regime=RANGE)` 时，final 改为 probe 或 block。
2. 把 `4H green_bar_shrinking + 1H red_bar_growing` 从 LONG final 移出，保留 shadow/probe。
3. 对逆环境 LONG 增加 15M 最小确认，不满足则不允许大仓。
4. 修 SHORT 仓位 floor：已通过方向和阈值的 SHORT，若 target notional < 2U，则提升到 2U 对应 portion；若不愿提升，则在策略层 HOLD，不要进入 execution error。
5. 开仓数量提升优先来自 SHORT 可执行化，而不是继续放宽 LONG。当前亏损样本说明放宽 LONG 会增加逆势风险。

## 单句归因

最新 24H 的方向亏损根因是：策略把局部多头反弹信号当成 final 多头确认，在价格仍低于 VWAP、ADX 偏弱或 RANGE、15M 无强确认时逆偏空环境开多；同时开仓数量不足的主因不是信号缺失，而是大量确认 SHORT 被仓位缩放压成低于 `2U` 的不可执行微仓，最终被 `min_notional` 否定。
