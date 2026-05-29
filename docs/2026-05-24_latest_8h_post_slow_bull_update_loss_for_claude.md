# 2026-05-24 最新 8H 慢牛策略更新后亏损归因：Continuation 未触发，资金仍在旧 MACD 滞后路径里磨损

审阅对象：Claude  
分析时间：2026-05-24  
日志目录：`D:\AIDCA\AI2\logs\2026-05\2026-05-24`

## 分析窗口

策略更新时间：北京时间 `2026-05-24 13:30`，即 UTC `2026-05-24 05:30`。

本次日志最大时间戳来自 `fund_flow_attribution.jsonl`：

- UTC：`2026-05-24T13:30:15.777932+00:00`
- 北京时间：`2026-05-24 21:30:15`

因此最新 8H 窗口为：

- UTC：`2026-05-24 05:30:15` 到 `2026-05-24 13:30:16`
- 北京时间：`2026-05-24 13:30:15` 到 `2026-05-24 21:30:16`

数据来源：

- `fund_flow_attribution.jsonl`
- `trade_fills_utc.csv`
- `runtime.out.12.log`
- `runtime.out.18.log`

成交统计按 `订单ID + 成交ID + symbol + time + side + qty + price` 去重。价格涨跌来自 attribution 的 `context.price` 快照，不使用未来 K 线。

---

## 结论摘要

13:30 慢牛策略更新后，系统不是没有运行新代码：日志中出现了 `[SLOW_BULL]`。但核心慢牛入口没有真正生效：

- `[SLOW_BULL]` 出现 `34` 次。
- `is_bull=True` 出现 `0` 次。
- `[SLOW_BULL_CANDIDATE]` 出现 `0` 次。
- `slow_bull_continuation_long` 开仓出现 `0` 次。
- attribution 中 `slow_bull_continuation / market_breadth / vwap_score_entry_gate` 元数据均为 `0`。

这意味着 13:30 的更新没有让资金进入新增的 continuation long 路径。系统仍然主要依赖旧的 `macd_v2_long_1h_red_bar_shrinking / red_bar_growing` 路径开仓。这个旧路径在慢牛里有两个问题：

1. 强势币早中段多数被 `NO_TRADE`、低 VWAP、4H/1H 滞后信号挡住，没有买到。
2. 真正开仓的多数是普通/偏弱标的，开仓后被 BTC beta fast-fail 快速止损，形成“小亏很多次”。

窗口内去重成交 `66` 条，已实现净 PnL `-1.2141 USDT`。亏损主要来自：

| Symbol | 已实现 PnL | 成交条数 | 成交额 |
|---|---:|---:|---:|
| RENDERUSDT | -0.3565 | 2 | 60.84 |
| PUMPUSDT | -0.2347 | 2 | 59.36 |
| ADAUSDT | -0.1830 | 4 | 129.65 |
| XRPUSDT | -0.1734 | 7 | 99.52 |
| ICPUSDT | -0.1150 | 7 | 88.45 |
| JUPUSDT | -0.1112 | 5 | 88.06 |
| AVAXUSDT | -0.1110 | 2 | 56.07 |
| SUIUSDT | -0.1008 | 3 | 61.11 |
| VETUSDT | -0.0933 | 2 | 57.06 |
| DOGEUSDT | -0.0678 | 6 | 132.29 |
| ATOMUSDT | +0.0669 | 7 | 95.05 |
| POLUSDT | +0.0710 | 11 | 126.15 |
| ETCUSDT | +0.1947 | 4 | 59.73 |

---

## 市场背景：确实存在强势慢牛，但系统没有覆盖

按 attribution 快照，窗口内涨幅前 10：

| Symbol | 起点(BJ) | 终点(BJ) | 起价 | 终价 | 涨跌 |
|---|---:|---:|---:|---:|---:|
| HYPEUSDT | 13:45 | 21:30 | 60.943 | 63.840 | +4.75% |
| ZECUSDT | 13:45 | 21:30 | 633.77 | 659.25 | +4.02% |
| ONDOUSDT | 13:45 | 21:30 | 0.4236 | 0.4391 | +3.66% |
| MORPHOUSDT | 13:45 | 21:30 | 2.1431 | 2.1987 | +2.59% |
| WLDUSDT | 13:45 | 21:30 | 0.2969 | 0.3034 | +2.19% |
| ETCUSDT | 13:45 | 21:30 | 8.937 | 9.014 | +0.86% |
| AAVEUSDT | 13:45 | 21:30 | 85.95 | 86.68 | +0.85% |
| PUMPUSDT | 13:45 | 21:30 | 0.001743 | 0.001756 | +0.75% |
| TRUMPUSDT | 13:45 | 21:30 | 2.077 | 2.092 | +0.72% |
| RENDERUSDT | 13:45 | 21:30 | 1.945 | 1.957 | +0.62% |

涨幅前 10 中，系统实际开多覆盖约 `3/10`：`ETCUSDT / PUMPUSDT / RENDERUSDT`。涨幅前 5 的 `HYPE/ZEC/ONDO/MORPHO/WLD` 全部没有开多。

这说明用户观察到的“多数山寨币从北京时间 17:30 附近慢牛上涨”是成立的，策略亏损不是因为市场没有机会，而是 opportunity selection 失败。

---

## 开仓行为：21 次开仓，0 次来自 continuation

窗口内 attribution 决策：

- decision：`877`
- hold：`835`
- close：`21`
- buy：`19`
- sell：`2`

实际开仓决策 `21` 次：

| BJ 时间 | Symbol | 方向 | target | lev | score | vwap | 1H signal | reason |
|---|---|---:|---:|---:|---:|---:|---|---|
| 14:00 | ADAUSDT | BUY | 0.042000 | 4 | 0.8192 | 0.7447 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:00 | DOGEUSDT | BUY | 0.042000 | 4 | 0.7832 | 0.7030 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:00 | XRPUSDT | BUY | 0.042000 | 3 | 0.7763 | 0.4860 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:00 | POLUSDT | BUY | 0.042000 | 3 | 0.7673 | 0.3863 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:00 | AVAXUSDT | BUY | 0.042000 | 3 | 0.7665 | 0.3690 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:30 | VETUSDT | BUY | 0.042000 | 3 | 0.7567 | 0.1734 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:30 | JUPUSDT | BUY | 0.042000 | 3 | 0.6435 | 0.4303 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:45 | POLUSDT | BUY | 0.042000 | 3 | 0.7690 | 0.4200 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:45 | PUMPUSDT | BUY | 0.042000 | 4 | 0.7673 | 0.3866 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 15:45 | AVAXUSDT | BUY | 0.042000 | 3 | 0.7077 | 0.4540 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 16:45 | ATOMUSDT | BUY | 0.042000 | 4 | 0.8836 | 0.1625 | red_bar_growing | macd_v2_long_1h_red_bar_growing |
| 17:00 | ICPUSDT | BUY | 0.042000 | 3 | 0.7617 | 0.2748 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 17:15 | ETCUSDT | BUY | 0.042000 | 3 | 0.7441 | 0.5527 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 17:45 | PUMPUSDT | BUY | 0.042000 | 3 | 0.7580 | 0.1695 | red_bar_growing | macd_v2_long_1h_red_bar_growing |
| 19:00 | DOGEUSDT | BUY | 0.042000 | 4 | 0.7835 | 0.7103 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 19:15 | ADAUSDT | BUY | 0.042000 | 4 | 0.8182 | 0.7234 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 19:30 | RENDERUSDT | BUY | 0.042000 | 3 | 0.7541 | 0.1227 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 19:30 | SUIUSDT | BUY | 0.042000 | 3 | 0.7132 | 0.8248 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 20:00 | JSTUSDT | BUY | 0.042000 | 3 | 0.7580 | 0.2001 | red_bar_shrinking | macd_v2_long_1h_red_bar_shrinking |
| 20:15 | ATOMUSDT | SELL | 0.000437 | 3 | 0.8867 | 0.8649 | green_bar_growing | macd_v2_short_1h_green_bar_growing |
| 20:15 | JUPUSDT | SELL | 0.000437 | 3 | 0.7962 | 0.3514 | green_bar_growing | macd_v2_short_1h_green_bar_growing |

关键点：

- `slow_bull_continuation_long`：`0` 次。
- 所有 BUY 都来自旧 MACD final/recovery 路径。
- `red_bar_shrinking` BUY 很多，本质仍是等 1H/4H 已经给出旧结构后再进，容易落后于慢牛早中段。
- 两笔 SHORT 出现在 20:15，且不是 slow-bull short guard 的结果；因为 `is_slow_bull` 一直 false，慢牛空头保护也没有机会触发。

---

## 根因 1：MarketBreadth 慢牛状态从未进入 true

运行日志中：

```text
[SLOW_BULL] is_bull=False breadth=0.96 btc30=-0.040% alt_med60=0.605% confirm=0
[SLOW_BULL] is_bull=False breadth=0.93 btc30=0.332% alt_med60=0.527% confirm=1
[SLOW_BULL] is_bull=False breadth=0.86 btc30=-0.116% alt_med60=0.415% confirm=0
[SLOW_BULL] is_bull=False breadth=0.93 btc30=0.128% alt_med60=0.528% confirm=0
[SLOW_BULL] is_bull=False breadth=0.86 btc30=0.157% alt_med60=0.266% confirm=0
```

统计：

- `[SLOW_BULL]` 解析到 `34` 条。
- `breadth >= 0.60`：`14` 条。
- `breadth >= 0.80`：`7` 条。
- `is_bull=True`：`0` 条。

代码原因在 `src/fund_flow/market_breadth.py`：

```python
conditions = {
    "btc_30m": btc_30m >= 0.003,
    "btc_60m": btc_60m >= 0.005,
    "breadth": breadth_ratio >= 0.60,
    "alt_median": alt_median_60m >= 0.004,
}
is_bull_candidate = sum(conditions.values()) >= 3
```

实际市场是“BTC 微涨/震荡 + 山寨广谱上涨”。这种 regime 下，`breadth` 很强，但 BTC 30M/60M 经常达不到 `+0.3% / +0.5%`，alt median 也经常略低于 `+0.4%`。所以 `3/4` 条件很难连续满足两次，`confirm_count` 经常从 1 回到 0。

结论：慢牛 detector 当前更像“BTC 强拉 + alt 普涨 detector”，而不是“山寨广谱慢牛 detector”。这与本窗口真实行情不匹配。

---

## 根因 2：强势币被旧 VWAP/NO_TRADE 逻辑挡住，慢牛 override 没机会生效

涨幅前 5 的处理：

| Symbol | 窗口涨跌 | 决策表现 | 主要 hold 原因 |
|---|---:|---|---|
| HYPEUSDT | +4.75% | 0 次 BUY | `macd_v2_hold_none_score_0.00`，2 次 `vwap_hard_block`，多次 `NO_TRADE` |
| ZECUSDT | +4.02% | 0 次 BUY | 29 次 `macd_v2_hold_none_score_0.00` |
| ONDOUSDT | +3.66% | 0 次 BUY | 10 次 `vwap_score_filter`，多次 `NO_TRADE` |
| MORPHOUSDT | +2.59% | 0 次 BUY | 4 次 `vwap_score_filter`，其余 score=0 |
| WLDUSDT | +2.19% | 0 次 BUY | 14 次 `vwap_hard_block`，3 次 `vwap_score_filter` |

典型样本：

```text
HYPE 14:45 price=61.754 score=0.0 vwap=0.0 signal=red_bar_growing regime=NO_TRADE -> vwap_hard_block
ONDO 16:30 price=0.4413 score=0.0 vwap=0.0265 signal=red_bar_growing regime=NO_TRADE -> vwap_score_filter
MORPHO 19:15 price=2.2032 score=0.0 vwap=0.0210 signal=red_bar_shrinking regime=TREND -> vwap_score_filter
WLD 21:15 price=0.3062 score=0.0 vwap=0.0 signal=green_bar_shrinking regime=TREND -> vwap_hard_block
```

我们上次设计“慢牛里 VWAP 低分不 hard block，只 cap 仓位”，但这个 override 的前提是 `is_slow_bull=True`。由于根因 1 中 `is_slow_bull` 从未 true，VWAP override 实际没有发挥作用。

---

## 根因 3：Beta 风控在工作，但它只能止血，不能补救负期望 entry

窗口内 close decision：

- `BETA_RISK_CLOSE`：`10`
- `BETA_RISK_REDUCE`：`11`

典型亏损退出：

```text
ADA 14:30 CLOSE: alt_15m_against(-0.244%) | alt_30m_against(-0.163%) | fast_fail(age=2bars,mfe=0.081%,mae=-0.203%)
AVAX 15:45 CLOSE: alt_15m_against(-0.150%) | alt_30m_against(-0.331%) | fast_fail(age=2bars,mfe=0.000%,mae=-0.406%)
JUP 16:00 CLOSE: alt_15m_against(-0.241%) | alt_30m_against(-0.624%) | fast_fail(age=2bars,mfe=0.000%,mae=-0.576%)
PUMP 18:15 CLOSE: alt_15m_against(-0.564%) | alt_30m_against(-0.787%) | fast_fail(age=2bars,mfe=0.000%,mae=-0.732%)
RENDER 20:30 CLOSE: alt_15m_against(-1.064%) | alt_30m_against(-1.064%) | btc_15m_against(-0.178%,corr=0.63)
```

这说明 BTC beta/fast-fail 不是完全失效。它确实把错误仓位快速减掉或平掉。

但策略仍亏的原因是：entry 层持续喂入 0.042 target 的普通旧路径开仓，而真正应该捕捉的强势慢牛标的没有被 continuation 选中。Beta 风控只能减少单笔损失，不能把负期望开仓变成正期望。

---

## 根因 4：慢牛相关集成存在明显实现/可观测性问题

### 4.1 attribution 没有记录新 gate 元数据

本窗口 attribution 决策中：

```text
slow_bull_continuation metadata: 0
market_breadth metadata: 0
btc_entry_regime_gate metadata: 0
vwap_score_entry_gate metadata: 0
slow_bull_short_guard metadata: 0
```

但 runtime 里确实有 `[SLOW_BULL]` 和 `[BTC_REGIME]`。这说明新 gate 的运行状态没有稳定进入 attribution 决策日志。Claude 审代码时需要重点确认：

- `market_flow_context["market_breadth"]` 是否每个 symbol 都传进 `DecisionEngine`。
- `metadata` 是否在 hold/open/close 的所有路径里被完整保留。
- 当 continuation 不允许时，是否应该记录 `[SLOW_BULL_HOLD] reason=not_slow_bull/momentum_insufficient`，否则无法知道候选失败原因。

### 4.2 正常 BUY 分支错误调用 short guard

在 `src/fund_flow/decision_engine.py` 的正常开多分支中，存在如下调用：

```python
short_guard = macd_v2_engine._apply_slow_bull_short_guard(
    direction="short",
    ...
)
```

这段代码位于 BUY 分支内。它不会直接解释本窗口所有亏损，因为 `is_slow_bull=False` 时 guard 直接 PASS；但它说明慢牛 guard 的接入点和参数存在污染。正确逻辑应是：

- BUY 分支不调用 short guard。
- SHORT 分支才调用 `_apply_slow_bull_short_guard(direction="short", ...)`。
- BUY 分支应只走 BTC regime / VWAP score / 15M gate / continuation path。

### 4.3 没有 `[SLOW_BULL_HOLD]`，无法观察 continuation 为什么失败

当前日志：

```text
SLOW_BULL: 34
SLOW_BULL_CANDIDATE: 0
SLOW_BULL_HOLD: 0
VWAP_GATE: 0
```

当 `is_slow_bull=False` 时 `_build_continuation_long_decision()` 直接 `return None`，没有打印候选失败原因。结果是我们只能从 `[SLOW_BULL]` 推断根因，无法逐 symbol 确认 HYPE/ZEC/ONDO/MORPHO/WLD 是否满足 ret30/ret60/RSI/EMA 条件。

---

## 亏损链路复盘

### 链路 A：强势币没买

1. HYPE/ZEC/ONDO/MORPHO/WLD 进入明显强势。
2. MarketBreadth 因 BTC 30M/60M 阈值和 confirm 规则没有进入 `is_slow_bull=True`。
3. continuation long 路径完全不触发。
4. 旧 MACD final 对这些币大多给 `score=0` 或 VWAP block。
5. 强势机会被错过。

### 链路 B：普通币被旧路径买入后快止损

1. ADA/DOGE/XRP/POL/AVAX/PUMP/JUP 等按旧 MACD 1H red_bar_shrinking/red_bar_growing 开多。
2. 多数 target 固定为 `0.042`，不是 continuation 的 0.020/0.030/0.042 分层。
3. 入场后 1~2 根 15M 方向没有兑现，触发 beta fast-fail。
4. 多笔小亏累积，窗口净 PnL 为负。

### 链路 C：慢牛 short guard 也没工作

1. 20:15 出现 ATOM/JUP 两笔 SHORT。
2. 当时 broader alt 并非完全崩盘，但 `is_slow_bull=False`，short guard 不会生效。
3. 两笔 SHORT target 很小，但说明“慢牛里降低 short 优先级”的逻辑没有在本窗口形成有效约束。

---

## 给 Claude 的评审重点

### 必须先修的不是继续加指标，而是让慢牛状态能进入 true

建议 Claude 重点评审 `MarketBreadthDetector.detect()` 的慢牛定义：

当前规则：

```text
btc_30m >= +0.30%
btc_60m >= +0.50%
breadth >= 60%
alt_median_60m >= +0.40%
至少 3/4 满足，且连续 2 cycle
```

本窗口证明这个规则漏掉了“BTC 微涨/震荡 + alt 广谱上行”的慢牛。更合理的方向：

```text
强广谱优先：
  breadth >= 0.80 且 alt_median_60m >= 0.25% 且 BTC 30M > -0.10%
  -> 允许 slow_bull_candidate

普通广谱：
  breadth >= 0.60 且 alt_median_60m >= 0.40% 且 BTC 60M > 0
  -> 允许 slow_bull_candidate

BTC 强拉：
  BTC 30M >= 0.30% 或 BTC 60M >= 0.50%
  + breadth >= 0.60
  -> 允许 slow_bull_candidate
```

关键不是放松所有条件，而是把慢牛分成：

- `btc_led_slow_bull`
- `alt_breadth_slow_bull`
- `mixed_slow_bull`

否则一旦 BTC 只是轻微上涨，山寨广谱行情就会被漏掉。

### continuation 失败原因必须逐 symbol 打印

需要新增/确认日志：

```text
[SLOW_BULL_HOLD] HYPEUSDT not_slow_bull breadth=... btc30=... alt_med60=...
[SLOW_BULL_HOLD] ZECUSDT momentum_insufficient ret30=... ret60=... rsi=... ema=...
[SLOW_BULL_CANDIDATE] ONDOUSDT allowed ...
```

验收标准不是只看 `[SLOW_BULL]`，而是：

```bash
grep "SLOW_BULL_CANDIDATE\|SLOW_BULL_HOLD" logs/... | wc -l
# 每个 cycle 至少能看到候选失败原因
```

### VWAP 在慢牛里的语义要从“价格位置过滤”改成“仓位 cap”

本窗口强势币 WLD/MORPHO/ONDO 多次因为 vwap_score 极低被挡住。但慢牛中强势突破经常会让传统 VWAP score 出现极端值。建议：

- 非慢牛：维持 `vwap_score < 0.12 block`。
- 慢牛强广谱：`vwap_score < 0.05` 不一定 block，除非 15M/30M 动量也弱。
- 慢牛中 `vwap_score` 应作为 cap：0.020 / 0.030 / 0.042，而不是直接归零。

### short guard 必须只挂在 SHORT 分支

需要修正/确认：

- BUY 分支不要调用 `_apply_slow_bull_short_guard(direction="short")`。
- SHORT 分支在 `breadth>=0.70` 时低 VWAP 直接 block，高 VWAP 也只允许 0.020 probe。
- attribution 必须记录 `slow_bull_short_guard` 的 action/reason。

---

## 建议验收标准

上线后 4H 内：

```bash
grep "SLOW_BULL" logs/... | wc -l
# > 0

grep "is_bull=True" logs/... | wc -l
# 在 breadth>=0.8 的广谱上涨窗口中必须 > 0

grep "SLOW_BULL_CANDIDATE" logs/... | wc -l
# > 0，至少覆盖 HYPE/ZEC/ONDO/MORPHO/WLD 这类强势币

grep "slow_bull_continuation_long" logs/... | wc -l
# > 0，但不能爆量，建议 4H 内 3~10 笔

grep "SLOW_BULL_HOLD" logs/... | wc -l
# > 0，候选失败原因必须可见
```

24H 后：

- 涨幅前 10 开多覆盖率：从本窗口 `3/10` 提升到 `>=5/10`。
- 涨幅前 5 不应再出现 `0/5` 覆盖。
- continuation long 的平均 target 不超过 `0.030`，避免新路径变成重仓追涨。
- `BETA_RISK_CLOSE` 不应成为主要退出原因；如果仍然高，说明 continuation 入场仍然太晚或过滤不够。
- 慢牛窗口内 SHORT 次数应接近 0，除非 BTC/alt breadth 同时转弱。

---

## 本次归因一句话

13:30 的慢牛更新没有真正捕捉慢牛。新代码有 `[SLOW_BULL]` 日志，但 `is_bull` 从未为 true，`SLOW_BULL_CANDIDATE` 和 `slow_bull_continuation_long` 为 0；结果资金仍在旧 MACD 滞后路径中交易普通标的，强势币大多被 NO_TRADE/VWAP/score=0 过滤掉，最终由 beta fast-fail 把一串低质量 entry 切成连续小亏。

---

*审阅人：Codex | 2026-05-24*  
*核心：慢牛 detector 阈值错配 + continuation 0 触发 + VWAP override 没生效 + short guard 集成位置异常*
