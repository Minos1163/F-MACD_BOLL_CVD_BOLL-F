# 2026-05-22 最新 48H 亏损归因：BTC 15M 领先性与当前交易对方向反转

审阅对象：Claude
分析时间：2026-05-22
日志目录：`D:\AIDCA\AI2\logs\2026-05`
有效窗口：`2026-05-20 00:45:15 UTC` 到 `2026-05-22 00:45:15 UTC`，北京时间 `2026-05-20 08:45:15` 到 `2026-05-22 08:45:15`。
BTC 15M K线窗口：`2026-05-19 00:45:15 UTC` 到 `2026-05-22 00:45:15 UTC`，来源 Binance USD-M Futures `/fapi/v1/klines`。

数据来源：
- `fund_flow_attribution.jsonl(.gz)`
- `trade_fills_utc.csv`
- `runtime.out.00/06/12/18.log`
- Binance Futures 15m klines（已缓存到 `data/binance_klines_20260522`）

## 结论摘要

最新 48H 去重成交 `126` 条，已实现净 PnL 约 `-2.550829 USDT`。匹配到开仓决策的亏损 entry `23` 个，亏损 entry 合计 `-5.109974 USDT`；亏损主要来自 `ICP/ADA/FET/TRUMP/ETC/ONDO/DOGE`。

这轮亏损不是单纯“开仓方向完全没信号”，而是开仓后 15M 到 30M 的方向变化没有足够快地进入风控。多数亏损 LONG 在 4H/1H 仍显示 `red_bar_growing` 或 `red_bar_shrinking` 时开仓，但 15M 入场字段仍是 `-`，raw 多在 `0.12~0.30`，说明短周期只给弱确认。亏损发生后，ExitGuard 往往需要 4 到 18 根 15M 才 full close，晚于目标里的 15M-30M 两根周期。

BTC 相关性验证显示，亏损 entry 的 30M 早期信号分布为：前30M未给明确反向: 16；BTC/交易对30M同步反向: 2；BTC反向但交易对暂未跟随: 2；交易对独立反向，BTC未确认: 1；BTC先反向，交易对30M内跟随: 1；BTC开仓前一根已反向，交易对30M内跟随: 1。BTC 不能硬替代单币 15M，但可以作为加速退出/降仓的高权重 beta 风险项。

单句归因：当前 MACD+RSI 方向入场仍由 4H/1H 结构主导，15M 只在入场时提供小分数或弱门槛；开仓后若 BTC 15M 已经反向、且交易对 15M/30M 跟随，风控没有在两根 15M 内快速减仓/止损，导致小亏拖成多 bars 后确认亏损。

## 48H 数据总览

|项|数量/金额|
|---|---|
|decision events|6679|
|open decisions|86|
|BUY opens|72|
|SELL opens|14|
|fills dedup|126|
|net realized pnl|-2.550829 USDT|
|negative fill rows|42|
|matched loss entries|23|

按 symbol 净 PnL 排序：

|symbol|pnl|fills|
|---|---|---|
|ICPUSDT|-0.888000|17|
|ADAUSDT|-0.772000|10|
|FETUSDT|-0.687500|9|
|TRUMPUSDT|-0.594760|15|
|ETCUSDT|-0.388430|7|
|ONDOUSDT|-0.316790|2|
|DOGEUSDT|-0.293820|2|
|PUMPUSDT|-0.194895|4|
|VETUSDT|-0.099324|4|
|POLUSDT|-0.064020|10|
|ZROUSDT|-0.058800|2|
|XLMUSDT|-0.046210|7|
|XRPUSDT|-0.046000|4|
|WLDUSDT|-0.044000|1|
|ALGOUSDT|+0.000000|1|

按开仓方向匹配统计：

|side|entries|loss entries|matched pnl|
|---|---|---|---|
|LONG|72|18|-0.773274|
|SHORT|14|5|-1.070780|

## BTC 与交易对 15M/30M 反向证据

定义：以开仓所在 15M K 线 close 为基准，计算 BTC 与交易对开仓后 15M、30M 的收益率。LONG 的反向为收益率 `< -0.10%`，SHORT 的反向为收益率 `> +0.10%`。相关性使用开仓前 12H 的 15M return，分别计算 BTC 同步、BTC 领先 15M、BTC 领先 30M。

|UTC|symbol|side|pnl|BTC15|ALT15|BTC30|ALT30|best lag|归类|
|---|---|---|---|---|---|---|---|---|---|
|05-21 02:45|FETUSDT|LONG|-0.7425|+0.00%|+0.10%|+0.11%|+0.47%|0(0.75)|前30M未给明确反向|
|05-21 08:30|ICPUSDT|LONG|-0.4900|-0.02%|+0.08%|+0.00%|+0.35%|0(0.45)|前30M未给明确反向|
|05-21 18:00|TRUMPUSDT|LONG|-0.3304|+0.03%|+0.48%|+0.05%|+1.00%|0(0.84)|前30M未给明确反向|
|05-21 12:30|ONDOUSDT|SHORT|-0.3168|+0.05%|-0.62%|+0.02%|-0.42%|0(0.15)|前30M未给明确反向|
|05-20 15:30|FETUSDT|LONG|-0.2958|+0.02%|+0.16%|+0.06%|+0.21%|0(0.71)|前30M未给明确反向|
|05-21 08:45|DOGEUSDT|LONG|-0.2938|+0.02%|-0.09%|+0.01%|-0.20%|0(0.73)|交易对独立反向，BTC未确认|
|05-21 17:00|ICPUSDT|SHORT|-0.2580|+0.59%|+1.43%|+0.48%|+1.23%|0(0.67)|BTC先反向，交易对30M内跟随|
|05-21 02:15|ADAUSDT|LONG|-0.2448|-0.03%|+0.08%|-0.11%|-0.16%|0(0.84)|BTC/交易对30M同步反向|
|05-21 18:15|XLMUSDT|LONG|-0.2238|+0.02%|+0.27%|-0.44%|-0.50%|0(0.85)|BTC/交易对30M同步反向|
|05-21 02:30|BCHUSDT|LONG|-0.2079|-0.09%|+0.04%|-0.08%|+0.51%|0(0.62)|前30M未给明确反向|
|05-20 06:00|ADAUSDT|LONG|-0.1962|+0.07%|-0.04%|+0.10%|+0.16%|0(0.92)|前30M未给明确反向|
|05-20 15:15|ETCUSDT|LONG|-0.1952|-0.15%|+0.11%|-0.13%|+0.06%|0(0.71)|BTC反向但交易对暂未跟随|
|05-21 10:30|ETCUSDT|SHORT|-0.1932|-0.19%|-0.25%|-0.06%|-0.13%|0(0.73)|前30M未给明确反向|
|05-20 05:45|ICPUSDT|LONG|-0.1920|+0.04%|+0.16%|+0.11%|+0.20%|0(0.74)|前30M未给明确反向|
|05-21 13:45|POLUSDT|SHORT|-0.1827|-0.04%|-0.22%|-0.09%|-0.25%|0(0.71)|前30M未给明确反向|
|05-21 02:45|TRUMPUSDT|LONG|-0.1564|+0.00%|+0.10%|+0.11%|+0.49%|0(0.79)|前30M未给明确反向|
|05-21 11:15|ADAUSDT|SHORT|-0.1408|-0.08%|-0.20%|-0.17%|-0.32%|0(0.74)|前30M未给明确反向|
|05-20 17:00|TRUMPUSDT|LONG|-0.1079|+0.22%|+0.10%|+0.35%|-0.10%|0(0.79)|前30M未给明确反向|

观察：

- `BTC先反向，交易对30M内跟随`：这类亏损本可以在第一根 15M 后进入快速风控观察，第二根 15M 若交易对也反向，应减仓或止损。
- `BTC/交易对30M同步反向`：不一定体现 BTC 领先，但体现市场 beta 同步反转；风控应允许 BTC 与本币同向反向时触发更短确认 bars。
- `交易对独立反向，BTC未确认`：说明不能把 BTC 做成硬方向源，否则会漏掉单币异动；需要保留单币 15M MACD/RSI 的主触发权。

## 亏损开仓质量归因

|条件|数量|
|---|---|
|亏损 entry 总数|23|
|LONG 亏损 entry|18|
|SHORT 亏损 entry|5|
|15M raw<0.30 或 entry15=-|22|
|ADX<20/RANGE/NO_TRADE 亏损 entry|9|
|开仓后30M交易对已反向|5|
|开仓后30M BTC也反向|5|

典型问题不是 4H/1H 完全错，而是它们太慢：

- `red_bar_growing` / `red_bar_shrinking` 在 4H/1H 上仍能给方向分，但单币 15M 经常没有强触发，`entry15=-`。
- 开仓后 15M/30M 内 BTC 或交易对已经反向时，当前 ExitGuard 仍按多根确认推进；日志里 XRP 需要 18 bars，FET 需要 10 bars，TRUMP 需要 4 bars，XLM 需要 5 bars，这与“两根 15M 内发现方向变了就止损”的目标不一致。
- 9x 小仓设置会放大同样 5U 以下保证金的名义波动，后续风控对小仓更需要敏捷，否则“小仓”会因为杠杆提高变成更快的净值波动源。

## 典型亏损样本

### FETUSDT LONG：pnl -0.7425，持仓约 465.0 min

```text
entry UTC=2026-05-21 02:45:15, BJ=2026-05-21 10:45:15
target=0.252000, leverage=3, regime=TREND, adx=24.20, score=0.8353, vwap_score=0.4565
MACD: primary=red_bar_growing, 1H=red_bar_growing, 15M raw=0.24, entry15=-, total=0.8353/0.6800
BTC returns: pre15=-0.09%, +15m=+0.00%, +30m=+0.11%
ALT returns: pre15=-0.26%, +15m=+0.10%, +30m=+0.47%
corr_12h: lag0=0.75, BTC_lead15=-0.25, BTC_lead30=0.04
classification=前30M未给明确反向
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

### ICPUSDT LONG：pnl -0.4900，持仓约 85.0 min

```text
entry UTC=2026-05-21 08:30:15, BJ=2026-05-21 16:30:15
target=0.201600, leverage=3, regime=TREND, adx=33.55, score=0.7100, vwap_score=0.4698
MACD: primary=red_bar_growing, 1H=red_bar_growing, 15M raw=0.12, entry15=-, total=0.7100/0.6800
BTC returns: pre15=-0.15%, +15m=-0.02%, +30m=+0.00%
ALT returns: pre15=-0.27%, +15m=+0.08%, +30m=+0.35%
corr_12h: lag0=0.45, BTC_lead15=0.13, BTC_lead30=-0.19
classification=前30M未给明确反向
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

### TRUMPUSDT LONG：pnl -0.3304，持仓约 300.0 min

```text
entry UTC=2026-05-21 18:00:15, BJ=2026-05-22 02:00:15
target=0.042000, leverage=3, regime=TREND, adx=19.19, score=0.6947, vwap_score=0.1640
MACD: primary=red_bar_growing, 1H=red_bar_growing, 15M raw=0.12, entry15=-, total=0.6947/0.6800
BTC returns: pre15=-0.20%, +15m=+0.03%, +30m=+0.05%
ALT returns: pre15=+0.29%, +15m=+0.48%, +30m=+1.00%
corr_12h: lag0=0.84, BTC_lead15=0.04, BTC_lead30=0.09
classification=前30M未给明确反向
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

### ONDOUSDT SHORT：pnl -0.3168，持仓约 172.4 min

```text
entry UTC=2026-05-21 12:30:15, BJ=2026-05-21 20:30:15
target=0.000437, leverage=3, regime=NO_TRADE, adx=47.33, score=0.7949, vwap_score=0.8022
MACD: primary=red_bar_shrinking, 1H=green_bar_growing, 15M raw=0.30, entry15=-, total=0.7949/0.6600
BTC returns: pre15=+0.17%, +15m=+0.05%, +30m=+0.02%
ALT returns: pre15=+1.20%, +15m=-0.62%, +30m=-0.42%
corr_12h: lag0=0.15, BTC_lead15=-0.08, BTC_lead30=0.14
classification=前30M未给明确反向
```

归因：SHORT 开仓后如果 BTC 或交易对 15M/30M 转涨，说明追空/试探空被短线反弹否定，应快速撤退或减仓。

### FETUSDT LONG：pnl -0.2958，持仓约 435.0 min

```text
entry UTC=2026-05-20 15:30:15, BJ=2026-05-20 23:30:15
target=0.200000, leverage=4, regime=TREND, adx=20.24, score=0.8453, vwap_score=0.6558
MACD: primary=red_bar_growing, 1H=red_bar_growing, 15M raw=0.24, entry15=-, total=0.8453/0.6800
BTC returns: pre15=-0.15%, +15m=+0.02%, +30m=+0.06%
ALT returns: pre15=-0.26%, +15m=+0.16%, +30m=+0.21%
corr_12h: lag0=0.71, BTC_lead15=-0.13, BTC_lead30=0.02
classification=前30M未给明确反向
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

### DOGEUSDT LONG：pnl -0.2938，持仓约 101.7 min

```text
entry UTC=2026-05-21 08:45:15, BJ=2026-05-21 16:45:15
target=0.042000, leverage=4, regime=TREND, adx=18.36, score=0.7504, vwap_score=0.6787
MACD: primary=red_bar_growing, 1H=red_bar_shrinking, 15M raw=0.27, entry15=-, total=0.7504/0.6800
BTC returns: pre15=-0.02%, +15m=+0.02%, +30m=+0.01%
ALT returns: pre15=+0.02%, +15m=-0.09%, +30m=-0.20%
corr_12h: lag0=0.73, BTC_lead15=0.15, BTC_lead30=-0.05
classification=交易对独立反向，BTC未确认
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

### ICPUSDT SHORT：pnl -0.2580，持仓约 30.0 min

```text
entry UTC=2026-05-21 17:00:15, BJ=2026-05-22 01:00:15
target=0.000437, leverage=3, regime=TREND, adx=24.97, score=0.7675, vwap_score=0.1713
MACD: primary=red_bar_shrinking, 1H=green_bar_growing, 15M raw=0.24, entry15=-, total=0.7675/0.6600
BTC returns: pre15=+0.41%, +15m=+0.59%, +30m=+0.48%
ALT returns: pre15=+0.36%, +15m=+1.43%, +30m=+1.23%
corr_12h: lag0=0.67, BTC_lead15=-0.30, BTC_lead30=0.04
classification=BTC先反向，交易对30M内跟随
```

归因：SHORT 开仓后如果 BTC 或交易对 15M/30M 转涨，说明追空/试探空被短线反弹否定，应快速撤退或减仓。

### ADAUSDT LONG：pnl -0.2448，持仓约 213.4 min

```text
entry UTC=2026-05-21 02:15:15, BJ=2026-05-21 10:15:15
target=0.080000, leverage=5, regime=TREND, adx=17.29, score=0.9094, vwap_score=0.6783
MACD: primary=red_bar_growing, 1H=red_bar_growing, 15M raw=0.30, entry15=rsi_neutral_resume, total=0.9094/0.6800
BTC returns: pre15=+0.21%, +15m=-0.03%, +30m=-0.11%
ALT returns: pre15=+0.36%, +15m=+0.08%, +30m=-0.16%
corr_12h: lag0=0.84, BTC_lead15=-0.32, BTC_lead30=0.11
classification=BTC/交易对30M同步反向
```

归因：LONG 开仓后如果 BTC 或交易对 15M/30M 转跌，应把 15M 反向作为快速风控主证据，而不是继续等待 1H/4H 退化。

## 建议给 Claude 审查的修复方向

### P0：新增 BTC 15M Beta 风控，不替代单币方向，只加速退出

```python
btc_against = (direction == "long"  and btc_ret_15m <= -0.0015) or \
              (direction == "short" and btc_ret_15m >=  0.0015)
alt_against = (direction == "long"  and alt_ret_15m <= -0.0010) or \
              (direction == "short" and alt_ret_15m >=  0.0010)

if btc_against and alt_against:
    reduce_or_close(confirm_bars=1, reason="btc_alt_15m_sync_reverse")
elif btc_against and alt_ret_30m_against:
    reduce_or_close(confirm_bars=2, reason="btc_lead_alt_follow_30m")
```

解释：BTC 不是开仓方向的硬门槛，但当持仓方向与 BTC 15M 反向、且交易对 15M/30M 也跟随反向时，应把 ExitGuard 的确认从 4~18 bars 缩到 1~2 bars。

### P0：15M 在风控中权重大于入场评分

当前 15M 在入场评分里仍像小分项；风控阶段应该反过来，15M 是“方向是否已经变了”的主证据：

- 单币 15M MACD/RSI 与持仓方向相反：基础 risk score +1。
- BTC 15M 与持仓方向相反：beta risk score +1。
- 单币 30M 累计反向且 BTC 领先相关性 `corr(BTC lead 15m) > 0.35`：再 +1。
- risk score >=2：减仓 50%；risk score >=3 或 MAE <= -0.6%：全平。

### P1：开仓后前两根 15M 设为 fast-fail 窗口

```text
entry_age <= 30m:
  如果 BTC + ALT 同步反向，并且 MFE < 0.2%，说明开仓后没有兑现方向优势。
  -> 直接 full close 或至少 reduce 50%，不要等 1H/4H 信号退化。
```

### P1：BTC 领先相关性要动态计算，避免误伤不跟随 BTC 的单币

建议每个 symbol 维护滚动 12H/24H 相关性：

- `corr_lag0`: 同步 beta。
- `corr_btc_lead_15m`: BTC 领先 1 根 15M。
- `corr_btc_lead_30m`: BTC 领先 2 根 15M。
- 只有 `max(corr) >= 0.35` 时，BTC 反向信号才提高风控权重；否则只看单币 15M，避免“某些山寨不跟 BTC”时误平。

## 给 Claude 的审阅问题

1. BTC 15M 反向 + 单币 15M 反向时，ExitGuard 是否应从现有多 bars 确认改为 1 bar full close 或 50% reduce？
2. 若 BTC 先反向、单币 30M 内跟随反向，是否应视为 BTC lead beta 风险，而不是普通 reverse signal？
3. 15M raw/entry 在入场中可以只是门槛，但风控中是否应该成为高权重否决项？
4. 对 `corr_btc_lead_15m < 0.20` 的单币，是否应该关闭 BTC 风控加权，只保留单币 15M？
5. 9x 小仓上线后，小仓 fast-fail 是否应更严格，例如 MAE -0.35% 且 BTC/ALT 反向即平？

## 单句归因

最新 48H 的亏损核心是：系统开仓仍依赖 4H/1H MACD+RSI 的慢周期确认，而持仓后 15M/30M 内 BTC 与交易对已经反向时，风控没有把 BTC beta 领先与单币 15M 反向提升为快速止损主证据，导致本可在两根 15M 内处理的小亏，拖到多 bars ExitGuard 后才确认平仓。

*审阅人: Codex | 2026-05-22*