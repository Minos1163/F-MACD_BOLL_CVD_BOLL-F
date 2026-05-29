# 2026-05-24 最新 24H 慢牛行情亏损归因：风控在止血，入场层没有识别广谱上涨

审阅对象：Claude  
分析时间：2026-05-24  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
有效窗口：`2026-05-23 04:15:15 UTC` 到 `2026-05-24 04:15:15 UTC`，北京时间为 `2026-05-23 12:15:15` 到 `2026-05-24 12:15:15`。  
慢牛观察窗口：北京时间 `2026-05-23 17:30` 到 `2026-05-24 12:15`。

窗口端点来自最新 `fund_flow_attribution.jsonl` 的最大时间戳 `2026-05-24T04:15:15.139342+00:00`，向前倒推 24H。

数据来源：

- `logs\2026-05\2026-05-23\fund_flow_attribution.jsonl(.gz)`
- `logs\2026-05\2026-05-24\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-23\trade_fills_utc.csv`
- `logs\2026-05\2026-05-24\trade_fills_utc.csv`
- `runtime.out.12.log / runtime.out.18.log / runtime.out.00.log / runtime.out.06.log / runtime.out.12.log`
- Binance `BTCUSDT` 15M K 线，通过代理 `127.0.0.1:12334` 下载。
- GitHub/Freqtrade 参考，通过代理 `127.0.0.1:12334` 访问。

说明：`trade_fills_utc.csv` 在不同日期文件里存在重叠成交行。本报告按 `订单ID + 成交ID + symbol + time + side + qty + price` 去重后统计。

## 结论摘要

最新 24H 去重后成交 `128` 条，已实现净 PnL 约 `-0.3040 USDT`。这不是一次大止损造成的亏损，而是典型的“慢牛行情中错过主升、少量晚入和反向仓被风控反复止血”的小亏累积。

用户关于慢牛的观察成立：北京时间 `2026-05-23 17:30` 后，日志中有价格记录的 `28` 个山寨币里 `27` 个上涨，涨幅中位数约 `+5.19%`。涨幅最大的 WLD `+13.93%`、MORPHO `+12.45%`、RENDER `+9.52%`、JUP `+8.91%`、ONDO `+8.55%`、FET `+8.02%`，系统全部没有开多。

策略亏钱的核心原因不是 BTC beta 风控完全无效。相反，`BETA_RISK=188`、`BETA_REDUCE=22`、`BETA_CLOSE=10`，说明退出层确实在止血。问题在于：上次优化主要加在风控/退出层，entry 层仍然依赖 4H/1H MACD final、VWAP score、NO_TRADE/RANGE gate。慢牛早期大量强势币的 `signal_score` 仍是 `0.00` 或被 `vwap_score_filter / vwap_hard_block` 卡住，系统没有“BTC/山寨广谱慢牛 + 单币 15M/30M continuation”的正向开仓路径。

一句话归因：**风控只会减少错误仓的亏损，但不会自动捕捉慢牛机会；当前 entry 仍是滞后的 4H/1H final 逻辑，强势币上涨时被 score=0/VWAP 低分过滤，等少数币 finally 触发时已经偏晚，又被 15M 回撤和 beta 风控打掉。**

## 交易与亏损总览

| 项 | 数量/金额 |
|---|---:|
| attribution records | 5314 |
| decisions | 2657 |
| executions | 2657 |
| dedup fills | 128 |
| open decisions | 38 |
| BUY opens | 22 |
| SELL opens | 16 |
| realized pnl | `-0.304024 USDT` |

按 symbol 净 PnL 排序：

| symbol | realized pnl | fills | notional |
|---|---:|---:|---:|
| SUIUSDT | -0.68640 | 2 | 62.21 |
| TRUMPUSDT | -0.44268 | 11 | 194.94 |
| ETCUSDT | -0.24553 | 7 | 129.30 |
| VETUSDT | -0.12788 | 14 | 91.36 |
| XRPUSDT | -0.08048 | 9 | 130.91 |
| PUMPUSDT | -0.03103 | 6 | 35.33 |
| HYPEUSDT | -0.03001 | 7 | 35.64 |
| JSTUSDT | -0.02756 | 9 | 102.01 |
| ADAUSDT | -0.00160 | 4 | 89.10 |
| XLMUSDT | +0.05163 | 14 | 195.94 |
| ALGOUSDT | +0.06432 | 2 | 17.91 |
| SOLUSDT | +0.20180 | 13 | 184.68 |
| POLUSDT | +0.21190 | 12 | 156.82 |
| ATOMUSDT | +0.38250 | 5 | 34.94 |
| ICPUSDT | +0.45700 | 13 | 252.22 |

大额亏损成交：

| 北京时间 | symbol | 平仓方向 | 对应仓位 | pnl | notional |
|---|---|---|---|---:|---:|
| 05-24 05:30 | SUIUSDT | 卖出 | LONG | -0.68640 | 30.76 |
| 05-23 21:00 | TRUMPUSDT | 买入 | SHORT | -0.32357 | 34.33 |
| 05-24 10:30 | ETCUSDT | 卖出 | LONG | -0.15007 | 31.35 |
| 05-24 10:30 | ICPUSDT | 卖出 | LONG | -0.11900 | 18.08 |
| 05-24 10:30 | XLMUSDT | 卖出 | LONG | -0.11880 | 16.25 |
| 05-24 03:15 | XRPUSDT | 卖出 | LONG | -0.07776 | 32.65 |
| 05-23 14:00 | ETCUSDT | 买入 | SHORT | -0.05725 | 20.26 |
| 05-24 10:30 | ICPUSDT | 卖出 | LONG | -0.05100 | 7.75 |
| 05-24 11:45 | TRUMPUSDT | 卖出 | LONG | -0.04356 | 15.19 |
| 05-23 14:00 | VETUSDT | 买入 | SHORT | -0.04122 | 8.87 |

## 慢牛行情证据

北京时间 `05-23 17:30` 到 `05-24 12:15`，有价格记录的 28 个 symbol 中 27 个上涨，涨幅中位数 `+5.19%`。BTC 同期也上涨，Binance `BTCUSDT` 15M 数据显示：

| 标的 | 窗口收益 |
|---|---:|
| BTCUSDT 24H | +1.652% |
| BTCUSDT 17:30 后 | +2.710% |
| BTC 4根15M最大上涨 | +1.716% |
| BTC 4根15M最大下跌 | -1.117% |

山寨币涨幅前列：

| symbol | 17:30 后收益 | 最大回撤 | 开多次数 |
|---|---:|---:|---:|
| WLDUSDT | +13.93% | -3.60% | 0 |
| MORPHOUSDT | +12.45% | -1.57% | 0 |
| RENDERUSDT | +9.52% | -2.62% | 0 |
| JUPUSDT | +8.91% | -3.00% | 0 |
| ONDOUSDT | +8.55% | -3.62% | 0 |
| FETUSDT | +8.02% | -3.07% | 0 |
| PUMPUSDT | +7.80% | -4.35% | 0 |
| ZECUSDT | +7.33% | -5.65% | 0 |
| HYPEUSDT | +7.20% | -3.46% | 0 |
| SUIUSDT | +6.52% | -3.52% | 1 |
| ICPUSDT | +6.30% | -2.09% | 5 |
| ZROUSDT | +5.83% | -2.96% | 0 |

这张表说明问题很直接：系统不是没有慢牛行情，而是没有捕捉慢牛里的强势标的。它买了 ICP、XLM、XRP、SOL、POL 等少数币，但错过了涨幅更大的 WLD/MORPHO/RENDER/JUP/ONDO/FET/ZEC/HYPE/ZRO。

## 开仓方向时序

窗口前半段，北京时间 `12:15~17:30`，系统开仓全是空：

| 阶段 | opens | BUY | SELL |
|---|---:|---:|---:|
| 12:15~17:30 | 13 | 0 | 13 |
| 17:30~12:15 | 25 | 22 | 3 |

这说明系统在慢牛前已经带着一批空头或试探空进入行情，后续慢牛确认后才逐步转多。问题不是完全不转向，而是转向太慢、覆盖 symbol 太少、强势币没有进入正向候选。

慢牛后实际 BUY symbols 只有：

```text
ADA, ATOM, ETC, ICP, POL, SOL, SUI, TRUMP, VET, XLM, XRP
```

慢牛后仍有 SELL：

```text
TRUMP, JST
```

## Hold/阻断结构

全窗口 decision reason 排名：

| reason | count |
|---|---:|
| `macd_v2_hold_none_score_0.00` | 1786 |
| `macd_v2_hold_none_score_0.44` | 209 |
| `macd_v2_hold_vwap_score_filter_score_0.00` | 184 |
| `macd_v2_hold_vwap_hard_block_score_0.00` | 52 |
| `macd_v2_hold_none_score_0.57` | 46 |
| `same_side_add_disabled_without_winner_pyramiding` | 19 |

慢牛观察窗口内 reason 排名：

| reason | count |
|---|---:|
| `macd_v2_hold_none_score_0.00` | 1477 |
| `macd_v2_hold_none_score_0.44` | 175 |
| `macd_v2_hold_vwap_score_filter_score_0.00` | 122 |
| `macd_v2_hold_vwap_hard_block_score_0.00` | 47 |
| `same_side_add_disabled_without_winner_pyramiding` | 13 |

VWAP score 分布：

| vwap score bucket | decision count |
|---|---:|
| `<0.12` | 1757 |
| `0.12~0.30` | 324 |
| `0.30~0.50` | 148 |
| `0.50~0.70` | 173 |
| `>=0.70` | 255 |

这说明慢牛错过不是容量限制导致：`active_symbol_capacity/small_bucket_cap/large_bucket_cap/total_cap` 在 runtime grep 中均为 `0`。主要阻断来自两个地方：

1. MACD V2 输出 `signal_score=0.00`，没有形成可交易方向。
2. `vwap_score` 大量低于 `0.12/0.30`，被 hard block 或 probe/filter。

## 强势币为什么没买

慢牛涨幅前列的 symbol 细分：

| symbol | 收益 | opens | avg score | avg vwap | 主阻断 |
|---|---:|---:|---:|---:|---|
| WLDUSDT | +13.93% | 0 | 0.090 | 0.199 | `NO_TRADE` 多，`score=0`，VWAP block/filter |
| MORPHOUSDT | +12.45% | 0 | 0.114 | 0.198 | `score=0`，VWAP hard block |
| RENDERUSDT | +9.52% | 0 | 0.045 | 0.067 | `score=0`，VWAP score 过低 |
| JUPUSDT | +8.91% | 0 | 0.098 | 0.108 | `score=0/0.44`，VWAP 低分 |
| ONDOUSDT | +8.55% | 0 | 0.023 | 0.055 | `NO_TRADE` 多，`score=0` |
| FETUSDT | +8.02% | 0 | 0.079 | 0.115 | `score=0`，VWAP filter |
| PUMPUSDT | +7.80% | 0 | 0.140 | 0.093 | `score=0/0.44/0.57`，未达 final |
| ZECUSDT | +7.33% | 0 | 0.068 | 0.162 | `score=0`，NO_TRADE/TREND 混合 |
| HYPEUSDT | +7.20% | 0 | 0.049 | 0.241 | `score=0`，少量 VWAP hard block |
| ZROUSDT | +5.83% | 0 | 0.075 | 0.086 | `score=0/0.44` |

这里最危险的不是单个参数过严，而是逻辑方向错位：慢牛行情中，强势币经常先表现为 15M/30M 连续抬升、BTC 同步走强、价格离短线均值偏离变大。当前逻辑却把这类状态解释成：

- 4H/1H 还没给 final，`score=0`。
- VWAP 偏离或 VWAP score 低，直接 filter/hard block。
- NO_TRADE/RANGE 标签下，即使价格趋势已经走出来，也没有慢牛恢复入口。

结果就是：真正强的币被判成“不可入场”，系统只能买到少数后续才满足 1H/4H 条件的币。

## 风控层表现：有效止血，但制造小亏噪音

runtime grep 结果：

| marker | count |
|---|---:|
| `BETA_RISK` | 188 |
| `BETA_REDUCE` | 22 |
| `BETA_CLOSE` | 10 |
| `BETA_WARMUP` | 1 |
| `15m_entry_gate` | 19 |
| `vwap_hard_block` | 266 |
| `vwap_score_filter` | 1496 |
| `same_side_add_disabled / winner_pyramiding` | 19 |
| `active_symbol_capacity` | 0 |
| `ReduceOnly/rejected/promoted_to_full_close` | 0 |

典型 beta 退出：

```text
BETA_CLOSE SUIUSDT:
alt_15m_against(-0.690%) | alt_30m_against(-1.676%)
btc_15m_against(-0.292%,corr=0.80)
btc_alt_30m_sync(-0.688%,-1.676%)
fast_fail(age=2bars,mfe=0.000%,mae=-1.664%)
```

```text
BETA_CLOSE ETCUSDT:
alt_15m_against(-0.543%) | alt_30m_against(-0.543%)
btc_15m_against(-0.220%,corr=0.84)
fast_fail(age=2bars,mfe=0.000%,mae=-0.543%)
```

这类退出逻辑本身是合理的：当晚入多单刚开仓就遇到 BTC/单币 15M 同步回撤，beta 快速止损能减少更大亏损。但它不能解决“为什么没有在慢牛早段买入强势币”的问题。

更准确地说：beta 风控让亏损变小，但 entry 层持续错过正期望机会，所以系统仍然稳定小亏。

## BTC entry regime gate 的可观测性问题

配置中已有：

```json
"btc_entry_regime_gate": {
  "enabled": true,
  "falling_avg_ret": -0.001,
  "rising_avg_ret": 0.001,
  "chase_short_ret_threshold": -0.015,
  "btc_falling_low_vwap_block": 0.3
}
```

代码中也有 `BtcEntryRegimeGate` 和 `_apply_entry_quality_pretrade_gates()`。但是本窗口 runtime grep：

| marker | count |
|---|---:|
| `BTC_REGIME` | 0 |
| `btc_entry_regime` | 0 |
| `REGIME_CAP_APPLIED` | 0 |
| `VWAP_SCORE_CAP_APPLIED` | 0 |
| `15M_CAP_APPLIED` | 0 |

同时 attribution 的 compact metadata 没有保留 `btc_entry_regime_gate` / `vwap_score_entry_gate` / `regime_entry_gate` 详情。因此现在无法从日志证明：

- BTC regime gate 在每个 symbol 上计算出的 regime 是 `rising/falling/choppy`。
- 哪些 entry 被 BTC gate block/probe/pass。
- BTC 从下跌转上涨后，entry 层是否有任何“恢复做多”的正向效果。

这不是说代码一定没运行，而是说可观测性不足。对实盘策略来说，这会导致审计困难：我们只能看到最终 `hold score=0`，看不到“为什么 BTC 上涨 + 山寨慢牛没有转成候选多单”。

## 亏损根因排序

### P0：没有慢牛 continuation entry，导致强势币全部漏掉

证据：

- 17:30 后 28 个 symbol 中 27 个上涨，中位数 `+5.19%`。
- 涨幅前 9 个 symbol 里面，系统开多次数为 `0`。
- 这些 symbol 的平均 `signal_score` 多数低于 `0.15`，大量 `macd_v2_hold_none_score_0.00`。

当前 MACD V2 仍是 4H/1H final 思维，适合确认趋势后入场，但不适合“BTC 先转强、山寨 15M/30M 广谱慢牛”的早中段捕捉。

### P0：VWAP score 被当作硬否决，错杀慢牛强势币

证据：

- 全窗口 `vwap_score < 0.12` 的 decision 达 `1757`。
- 慢牛窗口内 `vwap_score_filter/hard_block` 仍有 `169` 次。
- RENDER/ONDO/FET/ZRO/SUI 等慢牛币 avg vwap 很低，但价格最终大涨。

VWAP 低分不一定代表不能做多。在慢牛里，它可能代表“已经脱离均值/短线过热”，应该影响仓位和追高方式，而不是直接让所有 continuation 多单归零。

### P0：BTC 只用于退出加速，没有形成 entry 层正向市场状态

证据：

- BTC 17:30 后 `+2.710%`。
- beta 风控日志大量出现，说明 BTC 数据可用。
- 但 `BTC_REGIME/btc_entry_regime` 可观测日志为 `0`，且没有 BTC rising -> long candidate 的正向机制。

上次优化把 BTC 放进风控权重是正确方向，但只解决“错了快点跑”。它没有解决“BTC 领先上涨时，哪些山寨应优先开多”。

### P1：前半段空头惯性与慢牛反转冲突

证据：

- 12:15~17:30 开仓 13 笔，全部 SELL。
- 慢牛后仍有 TRUMP/JST SELL。
- TRUMP 最大负贡献之一来自 21:00 平空 `-0.32357`。

策略在慢牛开始前后仍持有或尝试空头，beta 可以止损，但无法把这部分亏损变成收益。需要在 BTC/alt breadth 转强时降低 short trial 的优先级。

### P1：晚入多单被 15M 回撤打掉，说明入场时点滞后

证据：

- SUI 在慢牛中总体 `+6.52%`，但实际开多后被 fast-fail，单笔 `-0.6864`。
- ETC/ICP/XLM 在 10:30 附近多单被 beta/15M 回撤打出亏损。

这类亏损不是“做多方向完全错”，而是追在局部回撤前。若 entry 层没有更早的 continuation 入口，后续 final BUY 往往变成慢牛后段追高。

### P2：same-side add 禁止阻止了少数盈利方向扩展，但不是主因

`same_side_add_disabled_without_winner_pyramiding` 出现 19 次。它会影响已有赢家的加仓，但容量限制没有触发，因此不是本窗口亏损主因。真正的问题是很多强势币根本没有首仓。

## GitHub/Freqtrade 参考

通过代理访问 GitHub/Freqtrade：

- Freqtrade 主仓库：`https://github.com/freqtrade/freqtrade`
- Freqtrade strategy customization 文档：`https://github.com/freqtrade/freqtrade/blob/develop/docs/strategy-customization.md`
- Freqtrade strategies 仓库：`https://github.com/freqtrade/freqtrade-strategies`

参考结论：

1. Freqtrade 支持 `informative_pairs()`，即把 BTC/ETH 等参考交易对作为额外 OHLCV 数据输入策略，而这些参考对不会自动变成交易标的。
2. 文档建议 informative pairs 列表保持短，避免过度请求交易所；这与我们只使用 BTC 15M/30M/1H regime，而不是对所有 symbol 做复杂外部依赖一致。
3. 成熟做法不是“BTC 硬替代单币方向”，而是把 BTC/ETH 作为 market regime / informative context，再由单币自己的 momentum/RSI/MACD/volume 决定是否入场。
4. 必须避免未来函数：BTC/单币 regime 只能使用已收盘 15M K 线，不能用当前未收盘 candle 或未来收益验证。

GitHub 未认证 code search 返回 401，因此本报告没有引用随机策略代码参数，也不建议照搬外部阈值。外部参考只用于确认架构方向：BTC 应作为 informative regime，而不是硬方向源。

## 给 Claude 的修复建议

### 命令 1：新增 Market Breadth / BTC Rising 的慢牛候选池

目标：当 BTC 与多数 tracked alt 同步转强时，不等待 4H/1H final 才允许做多。

建议逻辑：

```python
slow_bull_regime = (
    btc_ret_30m > 0
    and btc_ret_60m > 0.003
    and alt_breadth_30m_positive_ratio >= 0.60
    and alt_median_ret_60m > 0.004
)
```

进入 slow bull 后，允许单币满足以下条件时进入 `CONTINUATION_LONG_CANDIDATE`：

```python
symbol_ret_30m > 0.003
and symbol_ret_60m > 0.006
and rsi_15m between 50 and 72
and ema_15m_slope > 0
and last_15m_close > ema_15m_fast
and not btc_15m_against_long
```

这不是直接开大仓，而是给强势币一个小仓 probe 入口，例如 `0.02~0.042`。后续若 1H/4H final 也确认，再允许扩大仓位。

### 命令 2：VWAP score 对慢牛 continuation 改成仓位 cap，而不是硬 block

当前：

```text
vwap_score < 0.12 -> hard block
0.12~0.30 -> probe/filter
```

建议在 slow bull regime 中改为：

```python
if slow_bull_regime and direction == "long":
    if vwap_score < 0.12:
        # 不直接 block，要求更强 15M/30M continuation，且仓位极小
        require symbol_ret_30m > 0.004 and btc_ret_30m >= 0
        max_portion = 0.020
    elif vwap_score < 0.30:
        max_portion = 0.030
```

这样能防止追高大仓，同时不会把 WLD/MORPHO/RENDER/ONDO 这类强势慢牛币完全归零。

### 命令 3：BTC rising 只做正向 candidate boost，不做硬方向替代

原则：

```text
BTC rising + alt own momentum rising -> 允许 continuation long probe
BTC rising + alt own momentum flat/down -> 不开
BTC falling + alt own momentum rising -> 低相关/独立强势才允许小 probe
```

避免把 BTC 变成硬方向源。仍然保留滚动相关性：`corr < 0.20` 的 symbol 不使用 BTC boost，只看单币。

### 命令 4：慢牛中降低 short trial 优先级

如果出现：

```python
slow_bull_regime
and direction == "short"
and signal_1h in ("green_bar_shrinking", "green_bar_growing")
```

建议：

- `vwap_score < 0.50` 直接 block。
- `vwap_score >= 0.50` 只允许极小 probe。
- 若 alt breadth > 70%，禁止新增 short trial，除非单币 15M/30M 明确弱于市场。

### 命令 5：补齐可观测性

必须在 attribution 或 runtime 中打印：

```text
[BTC_ENTRY_REGIME] symbol regime=RISING/FALLING/CHOPPY action=PASS/BLOCK/PROBE btc4=... vwap=... reason=...
[SLOW_BULL_CANDIDATE] symbol ret30=... ret60=... breadth=... action=...
[VWAP_ENTRY_GATE] symbol score=... action=... slow_bull_override=true/false
[MISSED_UPTREND] symbol hold_reason=... next_60m_ret=... next_180m_ret=...
```

没有这些日志，下一次仍然只能看到 `hold_none_score_0.00`，无法判断到底是 MACD、VWAP、BTC gate、regime gate 还是组合逻辑错过机会。

## 回放验收标准

用本窗口做非未来函数回放，要求使用已收盘 K 线：

```text
窗口：2026-05-23 17:30 BJ -> 2026-05-24 12:15 BJ
数据：15M closed candles only
费用/滑点：保留现有 live 假设
```

验收指标：

| 指标 | 当前 | 目标 |
|---|---:|---:|
| 涨幅前 10 symbol 开多覆盖 | 1/10 | >= 5/10 |
| 慢牛窗口净 PnL | 负 | 正 |
| vwap_score < 0.30 的 long | 大量 hold/block | 小仓 probe 且有 15M/30M momentum |
| slow bull 下新增 short trial | 仍存在 | 显著减少 |
| `BTC_ENTRY_REGIME` 可观测日志 | 0 | 每次候选都有 |
| `MISSED_UPTREND` 诊断 | 无 | 可统计 |

## 不建议立刻做的事

1. 不建议简单降低 4H/1H MACD final 阈值。这样会增加震荡行情误入场。
2. 不建议把 BTC 变成硬方向源。低相关 symbol 会误伤。
3. 不建议直接关闭 VWAP gate。VWAP 应该从 hard block 改成 slow bull 下的 size cap，而不是完全删除。
4. 不建议再只优化 exit。当前问题主要在 entry 机会识别。

## Claude 审阅问题

请 Claude 重点审查：

1. `BtcEntryRegimeGate` 是否只做负向限制，缺少 `BTC rising + alt momentum` 的正向 continuation candidate。
2. `vwap_score_hard_block` 在 slow bull 中是否应该降级为仓位上限。
3. `macd_v2_hold_none_score_0.00` 是否来自 4H/1H final 依赖过强，导致 15M/30M 慢牛完全不能进入候选池。
4. 是否需要新增 `alt breadth` 或 `market breadth` 作为 regime，而不是只看单币 MACD。
5. 是否应给 `same_side_add_disabled_without_winner_pyramiding` 增加赢家扩展条件，但优先级低于首仓捕捉。

---

审阅核心：**本窗口亏损不是因为 BTC beta 风控完全失败，而是 entry 层没有慢牛 continuation 入口；强势山寨在 15M/30M 已经上涨时仍被 MACD score=0/VWAP 低分挡住，系统只在少数币晚入，随后被 beta 快速止血，最终稳定小亏。**
