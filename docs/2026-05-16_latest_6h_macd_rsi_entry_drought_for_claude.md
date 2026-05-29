# 2026-05-16 最新 6H 开仓偏少归因：MACD/RSI 方向共振被谁否定

审阅对象：Claude  
分析时间：2026-05-16  
日志目录：`D:\AIDCA\AI2\logs\2026-05\2026-05-16`  
窗口：`2026-05-16 03:15:15 UTC` 到 `2026-05-16 09:15:15 UTC`，按 `fund_flow_attribution.jsonl` 最新事件倒推 6 小时。

## 结论摘要

这 6 小时不是完全无开仓：`XRPUSDT` 在 `03:45:15 UTC` 有一笔 SHORT 成交，`07:15:36 UTC` 买回平仓，盈利约 `+0.57888 USDT`。但开仓数量仍显著偏少：`668` 个 decision 里只有 `1` 个 SELL，`667` 个 HOLD。

第一归因不是权限、账户或 API 错误。日志里没有 `permission_denied / account_blocked / api_error` 类证据，且 XRP 订单能提交并实际成交。

开仓少的主因是策略门控仍在多层否定方向：

1. `4H无明确方向` 仍有 `238/667` 个 HOLD，占 HOLD 的 `35.7%`。
2. `vwap_hard_block` 有 `210/667` 个 HOLD，占 `31.5%`，大量 MACD 1H/4H 有方向感但价格偏离 VWAP 太大，直接归零。
3. RSI 节奏硬否定合计 `174/667` 个 HOLD，占 `26.1%`：
   - `rsi_1h_direction_flat_veto`: 72
   - `rsi_1h_direction_against_veto`: 67
   - `rsi_15m_extreme_veto`: 35
4. final 后还有仓位门否定：`JSTUSDT` 三次已到 `final` 且分数过线，但 `target_portion` 只有 `0.0010-0.0013`，低于 `min_open=0.0600`，被 `ENTRY_GATE_BLOCK/min_open_portion` 拦住。

所以，“4H 没方向”有改善但没有解决开仓少：部分信号已经能走到 `rsi_rhythm / threshold_check / final`，但是 RSI 共振、VWAP 和 min_open 又接管成为新的主要否定层。

## 数据概览

来源文件：

- `runtime.out.12.log`
- `runtime.out.06.log`
- `fund_flow_attribution.jsonl`
- `trade_fills_utc.csv`

窗口内 attribution：

| 项 | 数量 |
|---|---:|
| decision events | 668 |
| execution events | 668 |
| HOLD decisions | 667 |
| SELL decisions | 1 |
| execution noop | 667 |
| execution pending | 1 |
| trade fills | 2 |

成交记录：

| UTC | symbol | side | price | qty | realized |
|---|---|---:|---:|---:|---:|
| 2026-05-16 03:45:15 | XRPUSDT | 卖出 | 1.4332 | 20.1 | 0.0 |
| 2026-05-16 07:15:36 | XRPUSDT | 买入 | 1.4044 | 20.1 | +0.57888 |

说明：attribution 里的 XRP execution 仍显示 `pending / executedQty=0.0`，但 `trade_fills_utc.csv` 后续有真实成交记录，说明这次 IOC/订单链路不是主要问题。

## HOLD 主因分布

| HOLD code | count | 解释 |
|---|---:|---|
| `4H无明确方向` | 238 | neutral upgrade/partial confirm 未能把方向升级成可交易方向 |
| `vwap_hard_block` | 210 | VWAP 偏离过大，评分归零 |
| `rsi_1h_direction_flat_veto` | 72 | 1H RSI 方向太平，不能确认 MACD 方向 |
| `rsi_1h_direction_against_veto` | 67 | 1H RSI 方向与候选方向相反 |
| `rsi_15m_extreme_veto` | 35 | 15M RSI 已极端，阻止追单 |
| `信号评分低于阈值` | 23 | 方向有雏形但分数低于开仓阈值 |
| `combo_shadow` | 7 | combo 进入 shadow，不允许 live |
| `vwap_score_filter` | 6 | VWAP 质量分略低于门槛 |
| `rsi_neutral_resume_short_disabled` | 2 | SHORT 的 RSI neutral resume 被 short quality guard 禁用 |
| `flip_bullish_disabled` | 1 | flip_bullish 路径禁用 |

## MACD + RSI 方向共振分层

方向映射按代码口径：

- `green_* / flip_bearish` 对应 SHORT 侧。
- `red_* / flip_bullish` 对应 LONG 侧。

### 1. 4H 和 1H 同向 SHORT：有方向，但多数被 VWAP/RSI 否定

`same_short` 共 `336` 个样本，是窗口内最多的方向形态。

主要否定：

| 否定层 | count |
|---|---:|
| `vwap_hard_block` | 174 |
| RSI 相关 veto | 136 |
| `4H无明确方向` | 13 |
| `信号评分低于阈值` | 6 |
| final/HOLD/DCA 等 | 3 |
| `rsi_neutral_resume_short_disabled` | 2 |
| 实际 SELL | 1 |

结论：MACD 同向 SHORT 并不少，但不是直接转化为开仓。真正否定它的是 VWAP 偏离和 RSI 方向节奏。RSI 不是只做加分，而是硬门控。

典型样本：

- `DOGEUSDT 04:00 UTC`: `4H=green_bar_growing`, `1H=green_bar_shrinking`，但 `15M=rsi_1h_direction_block`，HOLD code=`rsi_1h_direction_against_veto`。
- `RENDERUSDT 09:15 UTC`: `4H=green_bar_growing`, `1H=green_bar_growing`，但 `15M=rsi_1h_direction_block`，HOLD code=`rsi_1h_direction_against_veto`。
- 多个 `ZEC/TRUMP/ALGO/VET/JUP/FET` 样本是 `green` 方向明确，但 `dev=-6%` 到 `-13%`，HOLD code=`vwap_hard_block`。

### 2. 4H SHORT、1H LONG 对冲：仍主要落回“4H无明确方向”

`opposed_4h_short_1h_long` 共 `301` 个样本。

主要否定：

| 否定层 | count |
|---|---:|
| `4H无明确方向` | 213 |
| `vwap_hard_block` | 36 |
| `信号评分低于阈值` | 14 |
| `rsi_15m_extreme_veto` | 13 |
| 其他 RSI veto | 11 |
| `combo_shadow` | 7 |
| `vwap_score_filter` | 6 |

结论：这正是“4H 没方向”的残留主体。最新策略尝试 partial confirm/neutral upgrade，但当 4H 绿色收缩、1H 红色增长这类对冲形态出现时，大多仍没有足够 RSI/VWAP 证据升级成开仓。

`PC_SHADOW` 也印证这一点：窗口内有 `231` 条 partial confirm shadow，其中：

| combo | count |
|---|---:|
| `green_bar_shrinking+red_bar_shrinking` | 127 |
| `green_bar_shrinking+red_bar_growing` | 100 |
| `red_bar_shrinking+green_bar_shrinking` | 4 |

大多数 `PC_SHADOW` 都是 `would_pass=False`，且 `vwap_safe=False / vwap_aligned=False`。也就是说，partial confirm 识别到了“可能方向”，但没有通过实时开仓条件。

### 3. 4H/1H 同向 LONG 很少

`same_long` 只有 `13` 个样本，且没有形成开仓：

- `4H无明确方向`: 8
- `rsi_1h_direction_against_veto`: 5

因此本窗口不是 LONG 方向被严重压制，而是 LONG 候选本来就少。

## 已确认开仓方向被什么否定

这里把“已确认”限定为 stage 已到 `final`，或分数已接近/超过阈值。

| UTC | symbol | side/dir | 4H | 1H | score/th | stage | 否定原因 |
|---|---|---|---|---|---:|---|---|
| 03:45 | XRPUSDT | SHORT | green_bar_growing | green_bar_shrinking | 0.7189 / 0.6900 | final | 通过，实际成交 |
| 04:30 | XRPUSDT | SHORT | green_bar_growing | green_bar_growing | 0.8838 / 0.6900 | final | 已有持仓，DCA 未触发 |
| 05:15 | XRPUSDT | SHORT | green_bar_growing | green_bar_growing | 0.7573 / 0.6900 | final | 已有持仓，DCA 未触发 |
| 05:30 | XRPUSDT | SHORT | green_bar_growing | green_bar_growing | 0.7571 / 0.6900 | final | 已有持仓，DCA 未触发 |
| 05:15 | JSTUSDT | SHORT | green_bar_growing | green_bar_growing | 0.8546 / 0.6900 | final | `ENTRY_GATE_BLOCK`: target=0.001312 < min_open=0.0600 |
| 05:45 | JSTUSDT | SHORT | green_bar_growing | green_bar_growing | 0.8557 / 0.6900 | final | `ENTRY_GATE_BLOCK`: target=0.001312 < min_open=0.0600 |
| 08:00 | JSTUSDT | SHORT | green_bar_growing | green_bar_growing | 0.7274 / 0.6900 | final | `ENTRY_GATE_BLOCK`: target=0.001050 < min_open=0.0600 |
| 05:00 | JSTUSDT | SHORT | green_bar_growing | green_bar_growing | 0.7936 / 0.6800 | rsi_neutral_resume_short_disabled | SHORT 的 `rsi_neutral_resume` 被 short quality guard 禁用 |
| 09:00 | JSTUSDT | SHORT | green_bar_growing | green_bar_shrinking | 0.6631 / 0.6800 | rsi_neutral_resume_short_disabled | 同上，且分数略低于阈值 |
| 05:45 | BCHUSDT | neutral/候选 | green_bar_growing | red_bar_shrinking | 0.6591 / 0.6800 | combo_hard_block | `combo_shadow` |
| 06:15 | BCHUSDT | neutral/候选 | green_bar_growing | red_bar_shrinking | 0.5014 / 0.6800 | combo_hard_block | `combo_shadow` |
| 06:30 | BCHUSDT | neutral/候选 | green_bar_growing | red_bar_shrinking | 0.5016 / 0.6800 | combo_hard_block | `combo_shadow` |

关键点：

- 真正过 final 且 open_new_entry 的 JST，不是被 MACD/RSI 否定，而是被仓位计算和 `min_open_portion` 否定。
- XRP 高分 follow-up 没有继续开，是因为已有持仓后走 DCA/加仓路径，`drawdown=0`，DCA 不触发；不是新开仓方向没确认。
- BCH 不是 final 后被执行层挡住，而是在 combo 阶段被 `combo_shadow` 停住。

## 为什么“4H 没方向”仍然明显

最新策略确实让一部分样本不再停在第一层 `4H无明确方向`，但效果被三件事抵消：

1. neutral/partial confirm 的候选多为 `green_bar_shrinking + red_bar_growing/red_bar_shrinking`，这类本质是 4H SHORT 侧衰减、1H LONG 或不稳，方向冲突仍高。
2. RSI rhythm 是硬确认：即使 MACD 有候选方向，只要 1H RSI 不是同向，或 15M 已极端，就直接 `hard_veto`。
3. VWAP 对强趋势末端非常严格：同向 SHORT 样本里大量价格已经偏离 VWAP，`vwap_hard_block` 把分数归零。

因此问题不是“MACD 没给方向”，而是“MACD 给出的方向需要 RSI 和 VWAP 同时背书；实盘 6H 里这两个背书大多没有出现”。

## 非主因排除

### 权限/账户/API

未见 `permission_denied / account_blocked / api_error / Traceback`。`runtime.err.06.log` 只有 deprecated config warning。

### IOC 未成交

本窗口内 XRP 的 attribution execution 记录显示 `pending / executedQty=0.0`，但 `trade_fills_utc.csv` 证明随后有真实成交。因此这 6H 的少开仓主因不是 IOC 未成交。

### capacity

窗口内只有 XRP 一笔持仓，后续也没有看到 max active symbols 容量打满的证据。capacity 不是第一归因。

## 给 Claude 的审阅问题

1. `same_short` 样本很多，但 `vwap_hard_block + RSI veto` 合计吃掉大多数机会。应先审 VWAP 偏离门槛，还是先审 RSI hard veto 的方向门槛？
2. JST 的 final 高分 SHORT 三次被 `min_open_portion` 拦住，且 `probe_floor_rescue.shadow_mode=true` 导致 rescue 不落地。这里是仓位公式过小，还是 min_open 对小资金账户过高？
3. `rsi_neutral_resume_short_disabled` 把 JST 的高分 SHORT 禁掉，这是否仍符合当前想增加开仓的目标？如果保留，需要确认它是事故防线还是过度保守。
4. `PC_SHADOW` 231 条且多数 `vwap_safe=false`，说明 partial confirm 当前主要在产生日志，不在产生交易。是否需要继续让 partial confirm 只 shadow，还是先用 24H 胜率验证后再调整？

## 单句归因

最新 6H 开仓少的根因是：4H 方向修复只把一部分信号推进到中后段门控，但 MACD/RSI 方向共振没有稳定成立；同向 SHORT 被 VWAP 和 RSI rhythm 大量否定，少数 final 高分信号又被 min_open/DCA/short quality guard 否定。
