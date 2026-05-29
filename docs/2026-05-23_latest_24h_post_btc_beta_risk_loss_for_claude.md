# 2026-05-23 最新 24H：BTC Beta 风控上线后仍稳定小亏的归因

审阅对象：Claude  
分析时间：2026-05-23  
日志目录：`D:\AIDCA\AI2\logs\2026-05`  
有效窗口：`2026-05-22 03:00:15 UTC` 到 `2026-05-23 03:00:15 UTC`，北京时间为 `2026-05-22 11:00:15` 到 `2026-05-23 11:00:15`。

窗口端点来自最新 `fund_flow_attribution.jsonl` 的最大时间戳 `2026-05-23T03:00:15.232216+00:00`，向前倒推 24H。

数据来源：

- `logs\2026-05\2026-05-22\fund_flow_attribution.jsonl(.gz)`
- `logs\2026-05\2026-05-23\fund_flow_attribution.jsonl`
- `logs\2026-05\2026-05-22\trade_fills_utc.csv`
- `logs\2026-05\2026-05-23\trade_fills_utc.csv`
- `logs\2026-05\2026-05-22\runtime.out.*.log`
- `logs\2026-05\2026-05-23\runtime.out.*.log`
- `logs\2026-05\2026-05-23\order_rejects.log`
- 补充下载：`data\binance_klines_20260523\BTCUSDT_15m_1779418815_1779505215.csv`

说明：`trade_fills_utc.csv` 跨日期存在重叠行，本报告按 `订单ID + 成交ID + symbol + time + side + qty + price` 去重。

## 结论摘要

最新 24H 去重成交 `206` 条，已实现净 PnL 约 `+0.0773 USDT`，但 gross loss 为 `-2.9330 USDT`。因此“稳定亏钱”的体感是真实的：系统在频繁产生小额亏损，只是被 `ATOMUSDT +1.1395`、`ETCUSDT +0.3583`、`BCHUSDT +0.2110` 等少数盈利抵消，净值结果没有明显负数。

BTC 走势符合用户观察：补拉 Binance Futures 15M K 线后，BTC 在窗口内从约 `77675.4` 跌到 `75579.7`，全窗口约 `-2.70%`，高低点回撤约 `-3.44%`；`2026-05-22 12:00 UTC` 后下跌更明显，之后约 `-2.35%`。

核心问题不是 BTC beta 风控没有运行，而是：

1. **BTC beta 大部分时间没有使用 BTC 权重**：runtime 中 `[BETA_RISK]` 共 `255` 行，`use_btc=False` 为 `162` 行，`use_btc=True` 为 `93` 行。原因是滚动相关性需要样本，启动初期或低相关 symbol 自动退化为单币 15M 风控。
2. **入场层仍然在低质量条件下反复开仓**：窗口内 `49` 个实际 open pending 中，`25/49` 的 `vwap_score < 0.30`，`11/49` 是 `NO_TRADE/RANGE`，`5/49` 是 `ADX<20`。BTC beta 只能退出，不能阻止这些 entry。
3. **下跌后半段的短空也没有赚钱**：BTC 明显下跌阶段，实际开仓主要是 `SELL green_bar_growing`，但该阶段净 PnL 仍约 `-0.5373U`。说明短空进入点偏晚，容易在下跌后的 15M 反抽里被 beta/ExitGuard 小亏退出。
4. **beta 风控触发后执行质量不稳定**：beta close/reduce 决策 `64` 次，其中执行 `pending=37`、`success=24`、`error=3`；close 执行里有 `28` 次 ReduceOnly rejected/error 类日志，`14` 次 `promoted_to_full_close`。大量 partial close 在小仓位和精度约束下退化为 full-close/noop/交易所实时仓位已为 0，造成归因与实际成交不一致。

单句归因：  
**BTC beta 风控已经能在部分高相关、同步反向场景下加速退出，但它解决的是“亏损后更快止血”；当前亏损根因仍在 entry 层，尤其是低 VWAP/NO_TRADE/RANGE/弱 ADX 场景下反复开仓，以及 BTC 下跌趋势里追空过晚、被 15M 反抽切碎。**

## 24H 交易总览

| 项 | 数值 |
|---|---:|
| 去重 fills | 206 |
| realized net PnL | `+0.077337 USDT` |
| gross loss | `-2.932995 USDT` |
| gross win | `+3.010332 USDT` |
| attribution events | 5262 |
| execution events | 2631 |
| open pending | 56 |
| close executions | 70 |
| capacity noop | 21 |

按 symbol 净 PnL：

| symbol | PnL | fills | notional |
|---|---:|---:|---:|
| HYPEUSDT | -0.30342 | 4 | 66.815 |
| AAVEUSDT | -0.30200 | 13 | 148.625 |
| ALGOUSDT | -0.28331 | 9 | 95.065 |
| DOGEUSDT | -0.24752 | 14 | 110.444 |
| SUIUSDT | -0.23549 | 15 | 136.099 |
| ADAUSDT | -0.17910 | 13 | 331.780 |
| TRUMPUSDT | -0.13426 | 14 | 299.496 |
| VETUSDT | -0.08601 | 20 | 244.288 |
| PUMPUSDT | -0.06410 | 14 | 100.446 |
| ZROUSDT | -0.06393 | 12 | 102.380 |
| ATOMUSDT | +1.13946 | 1 | 56.810 |
| ETCUSDT | +0.35834 | 3 | 39.776 |
| BCHUSDT | +0.21101 | 6 | 61.725 |
| JSTUSDT | +0.13548 | 6 | 68.349 |

## BTC 阶段拆分

| 阶段 | UTC 时间 | BTC 状态 | fills | net PnL | gross loss | 主要亏损 symbol |
|---|---|---|---:|---:|---:|---|
| early_chop | 03:00-12:00 | 前期波动较小，未形成单边 | 80 | +1.11625 | -1.23051 | DOGE/VET/TRUMP/ADA/AAVE |
| btc_down_1 | 12:00-16:00 | BTC 开始明显下跌 | 34 | -0.50161 | -0.56720 | DOGE/AAVE/ZRO/XRP |
| btc_down_2 | 16:00-03:00 | BTC 下跌延续后反复抽动 | 92 | -0.53730 | -1.13529 | PUMP/POL/ALGO/AAVE/VET/ZRO/SUI/HYPE |

关键观察：

- 前期净盈利主要来自 `ATOM +1.1395` 这种单笔盈利，并不代表信号质量稳定。
- BTC 下跌后，策略方向逐步转向 short，但并没有产生趋势收益，反而继续小亏。
- 说明当前 short 入场更像“下跌后追空”，不是 BTC 领先确认后的早期顺势。

## 入场质量统计

窗口内 entry decision 为 `68` 个，实际 open pending 为 `49` 个。

| 质量条件 | entry decisions | open pending |
|---|---:|---:|
| 总数 | 68 | 49 |
| `vwap_score < 0.30` | 33 | 25 |
| `NO_TRADE/RANGE` | 16 | 11 |
| `ADX < 20` | 7 | 5 |
| `signal_score >= 0.80` | 10 | 9 |

按阶段看：

| 阶段 | 主要 open 结构 |
|---|---|
| early_chop | `BUY red_bar_growing TREND` 8 笔，`SELL green_bar_growing TREND` 4 笔 |
| btc_down_1 | `BUY red_bar_growing TREND` 4 笔 |
| btc_down_2 | `SELL green_bar_growing TREND` 17 笔，`SELL green_bar_growing NO_TRADE` 8 笔 |

这说明：

1. BTC 开始下跌后的第一段，系统仍然开了多单，例如 `ADA/XLM/AAVE/DOGE/VET` 的 `BUY red_bar_growing`。
2. 后半段虽然切到 short，但大量来自 `green_bar_growing`，其中不少是 `NO_TRADE/RANGE`，属于“趋势已经走出后追空”，容易被 15M 反弹打掉。
3. `vwap_score` 仍未成为强入场质量约束。`vwap_score=0.12~0.28` 的 long/short 仍然进入实际开仓队列。

典型 entry：

```text
2026-05-22 12:15 UTC ADA BUY target=0.252/exec=0.2142
signal_score=0.8267, signal_1h=red_bar_growing, vwap_score=0.2839

2026-05-22 12:15 UTC XLM BUY target=0.189/exec=0.16065
signal_score=0.8201, signal_1h=red_bar_growing, vwap_score=0.1524

2026-05-22 13:00 UTC DOGE BUY target=0.1512/exec=0.12852
signal_score=0.6976, signal_1h=red_bar_growing, vwap_score=0.2211

2026-05-22 16:30 UTC XRP SELL
signal_score=0.8156, signal_1h=green_bar_growing, vwap_score=0.0614
vol_vwap_warn=True, but final floor lift 后仍尝试开仓
```

## BTC Beta 风控表现

runtime 中 `[BETA_RISK]` 行为：

| 指标 | 数量 |
|---|---:|
| `[BETA_RISK]` lines | 255 |
| `use_btc=False` | 162 |
| `use_btc=True` | 93 |
| use_btc=True 且 HOLD | 65 |
| use_btc=True 且 REDUCE_50 | 20 |
| use_btc=True 且 CLOSE | 8 |
| use_btc=False 且 HOLD | 125 |
| use_btc=False 且 REDUCE_50 | 31 |
| use_btc=False 且 CLOSE | 6 |

attribution 中 beta close/reduce：

| 类型 | 数量 |
|---|---:|
| BETA_RISK decisions | 64 |
| BETA_RISK_REDUCE | 50 |
| BETA_RISK_CLOSE | 14 |
| beta execution pending | 37 |
| beta execution success | 24 |
| beta execution error | 3 |

BTC 权重实际参与的代表日志：

```text
DOGE score=6 CLOSE use_btc=True
alt_15m=-0.235%, alt_30m=-0.253%,
btc_15m=-0.238%, corr=0.64, btc_alt_30m_sync=-0.279%/-0.253%,
fast_fail(age=2bars,mfe=0.000%,mae=-0.282%)

ADA score=4 CLOSE use_btc=True
alt_15m=-0.472%, alt_30m=-0.472%,
btc_15m=-0.238%, corr=0.90, btc_alt_30m_sync=-0.279%/-0.472%

XLM score=4 CLOSE use_btc=True
alt_15m=-0.320%, alt_30m=-0.499%,
btc_15m=-0.238%, corr=0.67, btc_alt_30m_sync=-0.279%/-0.499%

TRUMP score=4 CLOSE use_btc=True
alt_15m=-0.888%, alt_30m=-0.469%,
btc_15m=-0.238%, corr=0.74, btc_alt_30m_sync=-0.279%/-0.469%
```

结论：

- BTC beta 在高相关、同步反向场景下确实触发了 CLOSE/REDUCE。
- 但在大部分时间里，`use_btc=False`，说明风控实际退化为“单币 15M/30M 反向检测”。
- 这符合设计的低相关保护，但也暴露冷启动问题：每次重启后相关性历史为空，BTC 权重需要至少 10 根样本才可能打开；在最关键的上线后早期阶段，BTC 不是有效权重来源。

## 为什么仍然亏损

### 1. 风控是退出层，无法阻止低质量 entry

BTC beta 的职责是“持仓后加速退出”。本窗口最大问题仍然是 entry 层不断给它喂低质量仓位：

- `25/49` 实际开仓 `vwap_score < 0.30`
- `11/49` 实际开仓在 `NO_TRADE/RANGE`
- BTC 下跌初段仍开 `BUY red_bar_growing`
- BTC 下跌后段大量 `SELL green_bar_growing`，但入场在下跌后，容易被反抽打掉

这会形成固定模式：

```text
低质量 entry → 15M 很快反向 → beta REDUCE/CLOSE → 小亏
下一轮 MACD/RSI 仍给 final → 再次 entry → 再次小亏
```

这不是 beta 参数单独能解决的问题。

### 2. beta 冷启动使 BTC 领先性前期没被充分利用

日志中 `use_btc=False` 为 `162/255`。`BtcBetaRiskScorer` 的相关性历史是内存态，未持久化；重启后每个 symbol 至少需要 10 次 15M 更新，才能计算相关性并启用 BTC 权重。

因此上线后早期，BTC 即使已经有领先信号，系统也可能只看单币 15M，直到相关性积累足够。

建议 Claude 审查：

- 是否应在启动时用最近 48 根 15M K 线预热 BTC/alt corr，而不是从空 deque 开始。
- 是否应在 corr 样本不足时，对主流币使用保守默认相关性，而不是 `use_btc=False`。

### 3. REDUCE_50 对小仓位经常退化为 full-close/noop/reject

close execution 中：

| 项 | 数量 |
|---|---:|
| close executions | 70 |
| status pending | 42 |
| status success | 25 |
| status error | 3 |
| ReduceOnly rejected/error 类日志 | 28 |
| `promoted_to_full_close` | 14 |

典型错误：

```text
ZROUSDT BETA_RISK_REDUCE
quantity=0.1
promoted_to_full_close=true
error: ReduceOnly Order is rejected

AAVEUSDT BETA_RISK_REDUCE
quantity=0.1
promoted_to_full_close=true
error: ReduceOnly Order is rejected

POLUSDT BETA_RISK_CLOSE
quantity=187
error: ReduceOnly Order is rejected
```

这说明：

- `REDUCE_50` 在小仓位上常常因为最小数量/精度变成 full close 或被交易所拒绝。
- 日志里的 `success: ReduceOnly rejected 后实时仓位为0` 不是标准成交成功，而是“发现仓位已经没了”的兜底。
- 风控动作的执行结果不稳定，会让策略表现更像反复被动止损，而不是可控分批退出。

### 4. 下跌趋势里追空过晚，beta 反而切碎仓位

BTC 下跌后半段实际 open pending 有 `29` 个，其中：

- `SELL green_bar_growing TREND`: 17
- `SELL green_bar_growing NO_TRADE`: 8
- `SELL green_bar_shrinking TREND`: 3
- `SELL green_bar_growing RANGE`: 1

如果短空是在 BTC 已经下跌一段后才出现，15M 反弹会很容易触发：

```text
short entry → alt 15M/30M 上涨 → beta 认为 against short → REDUCE/CLOSE
```

这不是 beta 错，而是 entry 太滞后。BTC beta 的正确用法应该是：

- BTC 领先转弱时，不是只在持仓后退出；
- 对新 short entry，也要判断是否已经进入“下跌后反抽风险段”。

当前规则没有“BTC 已经跌了 N 根后禁止追空”的 entry gate。

## 典型亏损路径

### AAVEUSDT：低 VWAP 多单，beta 快速止损但仍亏

```text
2026-05-22 13:00 UTC
AAVE BUY target=0.2016 / exec=0.17136
signal_score=0.7036
signal_1h=red_bar_growing
vwap_score=0.3423
regime=TREND, ADX=21.83

2026-05-22 13:30 UTC
BETA_RISK_CLOSE:
alt_15m_against=-0.548%
alt_30m_against=-0.414%
fast_fail age=2bars, mfe=0.101%, mae=-0.448%

fill loss: -0.056 / -0.112 等
```

归因：beta 起到了快速止损作用，但 entry 本身只有低 VWAP、弱趋势边缘确认。风控把亏损切小，但无法把这种信号变成正期望。

### DOGEUSDT：BTC 同步反向时可以触发 close，但后续仍有小亏

```text
2026-05-22 后段 runtime:
DOGE score=6 CLOSE use_btc=True
btc_15m_against=-0.238%, corr=0.64
btc_alt_30m_sync=-0.279%/-0.253%
fast_fail age=2bars
```

归因：BTC beta 在 DOGE 上后段确实参与了，但 DOGE 本窗口仍净亏 `-0.2475U`。说明亏损来自多次 entry/exit churn，而不是单次没有止损。

### HYPEUSDT：NO_TRADE short，被反抽打掉

```text
2026-05-22 17:00 UTC
HYPE SELL target=0.0188
regime=NO_TRADE
signal_1h=green_bar_growing
vwap_score=0.6863
signal_score=0.7208

2026-05-22 17:30 UTC
BETA_RISK_CLOSE:
alt_15m_against=+0.173%
alt_30m_against=+0.235%
fast_fail age=2bars, mae=-0.338%

后续 HYPE 净亏 -0.3034U
```

归因：下跌后追空在 NO_TRADE regime 中被 15M 反抽打掉。这里 beta close 是正确的止损，但 entry gate 不应允许 NO_TRADE 追空。

### SUIUSDT：BTC/alt 同步反向 close，但 symbol 仍净亏

```text
2026-05-22 23:15 UTC
SUI BETA_RISK_CLOSE:
alt_15m_against=+0.387%
alt_30m_against=+0.654%
btc_15m_against=+0.155%, corr=0.85
btc_alt_30m_sync=+0.269%/+0.654%
```

归因：短空遇到 BTC/alt 共同反弹时，beta 全平是合理的；但 SUI 本窗口仍净亏 `-0.2355U`，说明入场时机和重复开仓频率是更上游的问题。

## 当前最不合理的机制

### P0：BTC beta 没有冷启动预热

目前相关性历史是 runtime 内存态，启动后大量 `use_btc=False`。这导致用户希望的“BTC 领先山寨币”的逻辑在上线初期没有充分发挥。

建议：

```text
启动时拉取 BTCUSDT + watchlist symbols 最近 48 根 15M close
预填 BtcBetaRiskScorer._corr_history
样本不足时：
  major symbols 默认 use_btc=True，但只给 BTC 权重 0.5
  meme/低相关 symbol 仍保持 use_btc=False
```

### P0：entry 层仍未使用 BTC regime

BTC 下跌初段，系统仍开多；BTC 下跌后段，系统开始追空。说明 BTC 只进入退出层，没有进入 entry gate。

建议不是让 BTC 成为硬方向源，而是加 entry risk cap：

```text
BTC 30M/60M 单边下跌时：
  禁止新开低 VWAP 多单
  禁止 red_bar_growing 低 vwap long 大仓
  short 只能在 BTC 反弹后再次转弱时入场，禁止连续下跌后追空
```

### P0：低 VWAP entry 仍太多

实际开仓里 `25/49` 的 `vwap_score < 0.30`。之前 15M hard gate 修了方向质量，但 vwap_score 仍然没有成为足够强的仓位/准入门。

建议：

```text
new entry:
  vwap_score < 0.20 -> block
  0.20 <= vwap_score < 0.35 -> max target 0.042
  只有 score>=0.85 且 15M strong 才允许放宽到 0.06
```

### P1：NO_TRADE/RANGE 不应开新 short final

后半段 `SELL green_bar_growing NO_TRADE` 有 8 个实际开仓。NO_TRADE 里的 green_bar_growing 更像局部追空，不是趋势确认。

建议：

```text
regime in (NO_TRADE, RANGE):
  禁止 new entry final
  只允许 reduce existing / close / tiny probe
```

### P1：REDUCE_50 对小仓位不稳定

大量 `promoted_to_full_close` 和 `ReduceOnly rejected` 表明 50% 部分平仓不适合所有小仓。

建议：

```text
如果 reduce_qty < exchange_min_qty * 2 或 notional < 5U:
  REDUCE_50 直接改为 CLOSE
  不再先尝试 partial reduce
```

### P1：capacity 仍在影响信号选择

窗口内 `capacity noop=21`。这说明虽然总容量已经改为 9，但实际持仓桶/已有仓位仍导致部分开仓被跳过。容量本身不是亏损主因，但会造成“该开的没开，不该开的先占位”。

建议 Claude 检查：

- bucket 统计用的是 notional、margin 还是 position count；
- 小仓/大仓是否按当前保证金而不是名义价值分类；
- beta close 后仓位是否及时从 capacity 统计中释放。

## 给 Claude 的审阅问题

1. BTC beta scorer 是否应该启动时用最近 48 根 15M K 线预热 corr，而不是运行中从空历史开始？
2. 对 ADA/XLM/SOL/XRP 这类高相关主流币，在 corr 样本不足时是否应该使用默认 BTC 权重，而不是 `use_btc=False`？
3. BTC 作为退出加速器已经有效，是否需要进一步作为 entry risk cap：不硬否决方向，但限制“BTC 已单边下跌后追空”和“BTC 转弱时低 VWAP 开多”？
4. `vwap_score < 0.30` 的 new entry 是否应统一 cap/block？当前 25/49 实际开仓低于 0.30。
5. `NO_TRADE/RANGE + green_bar_growing short` 是否应禁止 final，只允许 probe 或不交易？
6. 对小仓位，`REDUCE_50` 是否应该直接升级为 `CLOSE`，避免 reduce qty 被精度/最小数量处理成 rejected/full-close/noop？
7. capacity noop 仍有 21 次，是否说明 beta close 后仓位释放/桶统计存在延迟，导致机会集被旧仓位污染？

## 单句归因

最新 24H 的问题不是 BTC beta 风控完全无效，而是它上线后主要承担了“亏损后退出”的职责；上游 entry 仍在低 VWAP、NO_TRADE/RANGE、弱趋势和 BTC 阶段错位的场景中反复开仓，导致 beta 频繁 REDUCE/CLOSE，把大亏压成小亏，但没有改变交易流的负期望。

