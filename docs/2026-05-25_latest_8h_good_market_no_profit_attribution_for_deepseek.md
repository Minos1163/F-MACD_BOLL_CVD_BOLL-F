# 2026-05-25 最新 8H 市场较好但策略未赚钱归因（给 DeepSeek 评审）

**生成时间**: 2026-05-25 19:15 BJT  
**分析窗口**: 2026-05-25 11:15-19:15 BJT（UTC 03:15-11:15）  
**日志范围**:

- `logs/2026-05/2026-05-25/runtime.out.12.log`
- `logs/2026-05/2026-05-25/runtime.out.18.log`
- `logs/2026-05/2026-05-25/fund_flow/fund_flow_entry_exit_audit.jsonl`
- `logs/2026-05/2026-05-25/trade_fills_utc.csv`
- `logs/2026-05/2026-05-25/fund_flow/fund_flow_risk_state.json`

> 注意：本地 `data/backtest_cache/*_20260524.parquet` 只到 2026-05-24 14:00 UTC，不能用于证明 2026-05-25 最新 8H 行情。本报告只引用实盘日志、audit、成交记录。

---

## 结论摘要

最新 8H 策略没有明显赚钱，不是因为完全没有行情，而是因为：

1. **慢牛识别有阶段性生效，但强势币捕捉失败**：窗口早段出现广谱慢牛，`is_slow_bull=True` 在 UTC 04:45-06:15（BJT 12:45-14:15）持续出现；但 ICP 这类强势标的在慢牛窗口内基本一直 HOLD。
2. **ICP 典型漏单原因是 15M RSI/1H 方向 gate 把强趋势当作过热/方向冲突处理**：ICP 在慢牛窗口内多次 `rsi_extreme_block`、随后大量 `rsi_1h_direction_block`，导致 score 归零。
3. **后来 ICP 通过一次 final BUY，但执行层没有成交**：BJT 14:45（UTC 06:45）ICP 出现 BUY，但执行结果为 noop；BJT 19:00（UTC 11:00）再次 BUY，IOC 订单提交但 `executedQty=0`，没有实际成交。
4. **实际成交层面几乎被手续费吃光**：窗口内 92 条成交，已实现 PnL 合计约 `+0.8562U`，但 USDT 手续费约 `-0.8183U`，仅按 USDT 手续费净值只剩 `+0.0378U`，还没有折算 8 条 BNB 手续费。
5. **Beta 风控仍在频繁提前收尾，减少大亏但也造成收益截断和交易碎片化**：audit 中 26 次 close，全部是不同形式的 `BETA_RISK_REDUCE/CLOSE`；多个仓位持仓 15-30 分钟就被 fast-fail 或 15M against 打掉。

因此，本窗口问题不是“慢牛 detector 完全失效”，而是：

> 慢牛行情来了以后，系统仍然把强势延续币识别成 RSI 极端/1H 方向冲突；真正进入的仓位又被 beta fast-fail 和碎片化执行快速切掉，最后毛利润被手续费吞掉。

---

## 关键量化结果

### 1. Audit 决策分布

来自 `fund_flow_entry_exit_audit.jsonl`，窗口内：

| 类型 | 数量 |
|---|---:|
| pre_execution | 851 |
| post_execution | 851 |
| post HOLD | 785 |
| post BUY | 33 |
| post SELL | 7 |
| post CLOSE | 26 |

执行状态：

| operation/status | 数量 |
|---|---:|
| hold/noop | 785 |
| buy/pending | 22 |
| close/pending | 17 |
| buy/noop | 11 |
| close/success | 9 |
| sell/pending | 7 |

这说明策略大量时间在 HOLD，且实际开仓里也有一部分是 pending/noop，不是稳定成交。

### 2. 成交与 PnL

来自 `trade_fills_utc.csv`，窗口内：

- 成交条数：`92`
- 已实现 PnL 合计：`+0.856192U`
- USDT 手续费合计：`-0.818347U`
- 仅扣 USDT 手续费后的净值：`+0.037845U`
- BNB 手续费成交条数：`8`（未折算进上面净值）

换句话说，本窗口**账面毛盈利基本被手续费吞掉**。

按 symbol 粗分（PnL + USDT fee，未折算 BNB fee）：

| Symbol | fills | realized PnL | USDT fee | net after USDT fee |
|---|---:|---:|---:|---:|
| XLMUSDT | 3 | +0.9790 | -0.0499 | +0.9291 |
| RENDERUSDT | 6 | +0.4597 | -0.0441 | +0.4156 |
| POLUSDT | 6 | +0.2881 | -0.0414 | +0.2467 |
| WLDUSDT | 3 | +0.0408 | -0.0310 | +0.0098 |
| SOLUSDT | 6 | +0.0408 | -0.0656 | -0.0248 |
| AVAXUSDT | 12 | +0.0340 | -0.0836 | -0.0496 |
| ADAUSDT | 14 | +0.0334 | -0.1791 | -0.1457 |
| FETUSDT | 5 | -0.1034 | -0.0327 | -0.1361 |
| PUMPUSDT | 7 | -0.1672 | -0.0548 | -0.2219 |
| XRPUSDT | 2 | -0.1785 | -0.0484 | -0.2269 |
| ZECUSDT | 2 | -0.1984 | -0.0179 | -0.2164 |

正收益主要来自 XLM/RENDER/POL，亏损和手续费分散在大量小仓中。

---

## 慢牛检测：不是完全没识别，而是识别后没有抓住关键币

market breadth 状态在窗口内出现明显慢牛段：

| UTC | BJT | is_slow_bull | mode | breadth | BTC 30M | alt median 60M |
|---|---|---:|---|---:|---:|---:|
| 04:30 | 12:30 | False | - | 0.93 | +0.198% | +0.384% |
| 04:45 | 12:45 | True | alt_breadth_led | 1.00 | +0.287% | +0.630% |
| 05:00 | 13:00 | True | alt_breadth_led | 0.96 | +0.273% | +0.923% |
| 05:15 | 13:15 | True | alt_breadth_led | 0.96 | +0.210% | +1.312% |
| 05:30 | 13:30 | True | alt_breadth_led | 0.96 | +0.004% | +0.887% |
| 06:00 | 14:00 | True | alt_breadth_led | 0.86 | -0.057% | +0.385% |
| 06:15 | 14:15 | True/decaying | - | 0.57 | -0.169% | +0.034% |

这说明慢牛 detector 对早段广谱上涨有感知。但真正的问题是：**检测到慢牛之后，候选/入场层没有把 ICP 等强势币转化为有效持仓。**

---

## ICP 作为典型漏单案例

用户举 ICP 是合理的，因为 audit 显示 ICP 在窗口内长期有 1H `red_bar_growing`，但策略基本没有成交。

ICP audit 摘要：

| UTC | BJT | operation | result | reason / blocker | breadth |
|---|---|---|---|---|---:|
| 04:45 | 12:45 | HOLD | noop | `macd_v2_hold_none_score_0.00` | 1.00 slow_bull=True |
| 05:00 | 13:00 | HOLD | noop | `macd_v2_hold_none_score_0.00` | 0.96 slow_bull=True |
| 05:15 | 13:15 | HOLD | noop | `rsi_extreme_block` | 0.96 slow_bull=True |
| 05:30 | 13:30 | HOLD | noop | `rsi_extreme_block`, 1H `flip_bullish` | 0.96 slow_bull=True |
| 05:45 | 13:45 | HOLD | noop | `rsi_extreme_block`, 1H `flip_bullish` | 0.93 slow_bull=True |
| 06:00 | 14:00 | HOLD | noop | `rsi_1h_direction_block`, 1H `red_bar_growing` | 0.86 slow_bull=True |
| 06:45 | 14:45 | BUY | noop | score 0.8125, 但执行层 noop | 0.32 |
| 07:00-10:45 | 15:00-18:45 | HOLD | noop | 大量 `rsi_1h_direction_block` | 0.39-0.89 |
| 11:00 | 19:00 | BUY | pending | IOC `executedQty=0`，未成交 | 0.86 confirm=1 |

### ICP 两个关键失败点

#### 失败点 A：慢牛窗口内 RSI gate 把强趋势当成禁止信号

慢牛初期 ICP 的阻断主要是：

- `rsi_extreme_block`
- `rsi_1h_direction_block`
- `macd_v2_hold_none_score_0.00`

这与慢牛 continuation 的目标冲突：

> 慢牛里强势币本来就容易 RSI 高、1H 快速切换；如果 RSI extreme 直接把 score 归零，系统会错过最该跟的延续段。

#### 失败点 B：通过 final 的时候已经不在最好的广谱窗口，且执行没有成交

ICP 在 UTC 06:45（BJT 14:45）出现一次 BUY：

```json
{
  "symbol": "ICPUSDT",
  "operation": "buy",
  "target_portion_of_balance": 0.26775,
  "leverage": 3,
  "estimated_notional_usdt": 27.06,
  "current_price": 2.582,
  "reason": "macd_v2_long_1h_red_bar_growing_15m__vwap_0.61",
  "signal_score": 0.8125,
  "execution.status": "noop"
}
```

该次不是信号分不够，而是执行结果为 noop。日志文字为乱码，但结合执行路径和当时状态，符合“持仓数量限制/执行层跳过开仓”的表现。

UTC 11:00（BJT 19:00）又出现一次 ICP BUY：

```json
{
  "symbol": "ICPUSDT",
  "operation": "buy",
  "target_portion_of_balance": 0.12852,
  "estimated_notional_usdt": 13.08,
  "current_price": 2.661,
  "reason": "macd_v2_long_1h_red_bar_growing_15m__vwap_0.25",
  "execution.status": "pending",
  "order.status": "NEW",
  "executedQty": "0",
  "origQty": "13",
  "price": "2.665000"
}
```

也就是说，到窗口末尾才尝试挂 ICP，但没有实际成交。因此 `trade_fills_utc.csv` 中 **ICPUSDT 没有成交记录**。

---

## 入场层问题：Continuation 没有覆盖 ICP，普通 final 又太滞后

窗口内 continuation 有候选，但不是 ICP：

runtime 中能看到：

- `SLOW_BULL_CANDIDATE SOLUSDT ... ret30=0.32% ret60=0.68% rsi=98.3 ... portion=0.030`
- `SLOW_BULL_CANDIDATE ADAUSDT ... ret30=0.41% ret60=0.66% rsi=100.0 ... portion=0.030`
- `SLOW_BULL_CANDIDATE XRPUSDT ... ret30=0.26% ret60=0.69% rsi=100.0 ... portion=0.020`
- `SLOW_BULL_CANDIDATE DOGEUSDT ... ret30=0.15% ret60=0.66% rsi=98.6 ... portion=0.020`
- `SLOW_BULL_CANDIDATE AVAXUSDT ... ret30=0.30% ret60=0.93% rsi=98.9 ... portion=0.030`

但 ICP 在慢牛窗口内没有出现 `SLOW_BULL_CANDIDATE`，而是被普通 MACD/RSI gate 处理为 HOLD。

这说明当前 continuation 入口仍有覆盖盲区：

1. **单币强势但 RSI extreme 时，continuation 没有接管**。
2. **普通 final 依赖 1H/15M 配合，等它通过时，可能已经错过慢牛早段**。
3. **如果通过时 capacity 已满或执行未成交，最终仍然没有持仓。**

---

## 退出层问题：Beta 风控减少大亏，但也切碎收益

窗口内 26 次 close，close reason 基本都来自 beta 风控：

典型日志：

- ADA：`BETA_RISK_CLOSE ... fast_fail(age=2bars,mfe=0.042%,mae=-0.249%)`
- AVAX：`BETA_RISK_CLOSE ... small_notional_close(9.19U)`
- JUP：`BETA_RISK_CLOSE ... fast_fail(age=2bars,mfe=0.000%,mae=-0.852%)`
- FET：`BETA_RISK_CLOSE ... small_notional_close(0.21U)`
- PUMP：`BETA_RISK_CLOSE ... small_notional_close(0.00U)`

Beta 风控在坏仓位上是必要的，但本窗口副作用明显：

1. **开仓后 15-30 分钟内快速 reduce/close**，导致很多仓位没有时间参与慢牛延续。
2. **频繁进出导致手续费占比极高**，即使毛 PnL 为正，净值也接近 0。
3. **fast-fail 对强趋势中的正常回踩可能过敏**，尤其是 continuation 小仓如果刚入场就遇到 1 根 15M 回踩，会被提前处理。

---

## 费用/碎片化问题：毛利润被手续费吞噬

本窗口并非完全没赚钱：

- realized PnL：`+0.8562U`
- USDT fee：`-0.8183U`
- net after USDT fee：`+0.0378U`
- 还有 8 条 BNB fee 未折算

这说明策略当前的问题之一是**交易过碎**：

- ADA 14 条 fills，扣 USDT fee 后反而 `-0.1457U`
- AVAX 12 条 fills，扣 USDT fee 后 `-0.0496U`
- DOGE 9 条 fills，扣 USDT fee 后 `-0.1362U`
- PUMP 7 条 fills，扣 USDT fee 后 `-0.2219U`

少数好单（XLM/RENDER/POL）贡献了收益，但被大量小亏/手续费抵消。

---

## 和“市场很好”的矛盾如何解释

市场表现好，不等于策略一定赚钱。这个窗口中，策略没有赚钱的直接原因是：

1. **真正强势/高弹性标的没有及时持有**：ICP 是典型例子，慢牛早段基本没进。
2. **进入的部分标的并不是收益贡献最大的标的**：XLM、RENDER、POL赚钱，但仓位和持有不足以覆盖其他碎片亏损。
3. **Beta 快速退出使亏损变小，但也让策略变成高频碎片化交易**：毛 PnL 约 +0.86U，手续费约 -0.82U，净值自然不明显。
4. **capacity / execution 限制导致好信号未必成交**：ICP 14:45 BUY noop，19:00 BUY pending 未成交。

---

## 根因分层

### 根因 1：慢牛 continuation 没有覆盖“RSI 极端但趋势仍延续”的强势币

证据：ICP 在 slow_bull=True 期间多次 `rsi_extreme_block`，没有进入 continuation candidate。

建议评审点：

- 慢牛模式下 RSI 是否应该从 hard block 改为仓位 cap / trailing 风控？
- 对 `breadth >= 0.90` 且单币 30M/60M 正动量的 symbol，`rsi_extreme_block` 是否应降级为 `probe_cap`？
- 是否需要记录每个 symbol 的 `SLOW_BULL_HOLD` 失败条件，目前 runtime 对 ICP 的 continuation 失败原因不够直接。

### 根因 2：1H/15M 方向 gate 对强趋势回踩过敏

证据：ICP 后半段大量 `rsi_1h_direction_block`，即使 1H 是 `red_bar_growing`，15M/rsi gate 仍把 score 打到 0。

建议评审点：

- `rsi_1h_direction_block` 是否适合慢牛环境？
- 慢牛环境下是否应要求“单币 30M/60M 动量 + breadth”优先于 RSI rhythm？

### 根因 3：执行层 capacity / pending 导致通过信号不等于成交

证据：ICP 06:45 BUY 为 noop；11:00 BUY 为 pending，order `executedQty=0`。

建议评审点：

- capacity 满时是否应替换低质量持仓，而不是简单拒绝新强势币？
- IOC 未成交时是否需要记录“未成交后 N 秒价格表现”，区分执行问题和信号问题？

### 根因 4：fast-fail/beta exit 让策略收益结构过碎

证据：26 次 close 几乎全部来自 beta risk；多个仓位 15-30 分钟内被 reduce/close。

建议评审点：

- continuation probe 是否应该有独立 fast-fail 阈值？
- slow_bull=True 时，fast-fail 是否需要要求更强的反向证据？
- 当前 `MFE < 0.2% + MAE < -0.2%` 对高噪声山寨 15M 是否过敏？

### 根因 5：费用吞噬

证据：毛 PnL `+0.8562U`，USDT fee `-0.8183U`，净值约 `+0.0378U`，未折算 BNB fee。

建议评审点：

- 小仓 continuation 是否应该有最低期望收益/最低持仓时间过滤？
- 是否应该减少半仓 reduce 的碎片成交？
- 是否应对 15-30 分钟内多次开平的 symbol 加冷却？

---

## 对 DeepSeek 的问题清单

1. 在 slow_bull=True 且 breadth >= 0.90 时，`rsi_extreme_block` 是否应该仍然 hard block？还是改为仓位 cap + 更紧 trailing？
2. 对 ICP 这种在强势窗口内 `rsi_extreme_block -> rsi_1h_direction_block -> final BUY too late` 的路径，应如何重构 continuation 优先级？
3. Beta fast-fail 是否应区分普通 MACD final 和 slow-bull continuation？
4. 当 capacity 满时，是否应允许高 momentum / 高 breadth / 高 ranking score 的新币替换低 MFE 或横盘持仓？
5. 当前交易频率下手续费已经吃掉几乎全部毛利润，应该优先调 exit、entry、还是 capacity replacement？

---

## 初步建议（非直接上线方案）

本报告不建议直接改参数上线，只建议下一轮做以下可验证实验：

1. **慢牛 RSI hard block 消融实验**：只在 slow_bull=True 下，把 `rsi_extreme_block` 从 hard block 改为 `max_portion=0.015/0.020`，回放本窗口和 2026-05-23 慢牛窗口。
2. **Continuation 覆盖审计**：强制每个 symbol 每 cycle 打印 `SLOW_BULL_HOLD`，包括 ICP 的 failed conditions，确认是否是 RSI、EMA、ret30/60、BTC not down 哪一项失败。
3. **Capacity replacement shadow test**：不实盘替换，先 shadow 统计如果 ICP 06:45 替换掉低 MFE 持仓，后续收益会怎样。
4. **Beta fast-fail 分层回测**：普通 entry 维持现有 fast-fail，continuation entry 放宽到 3-4 bars 或要求 BTC+alt 双反向，再比较 MFE/MAE 和 fee drag。
5. **费用约束回测**：统计每笔成交扣 fee 后净 PnL，屏蔽 15-30 分钟内高频反复开平的 symbol。

---

## 最终判断

最新 8H 的核心不是“行情不好”，而是：

> 策略在慢牛早段识别到了广谱上涨，但 entry gate 没有把 ICP 这类强趋势币纳入 continuation；后续普通 final 进入过晚且执行不稳定；已有仓位又被 beta fast-fail 快速切碎，最终毛利润被手续费吞掉。

如果只继续微调 VWAP 或 BTC 权重，无法解决这个问题。下一步应聚焦：**慢牛模式下 RSI/1H gate 的 hard block 消融、capacity replacement、continuation 专属 exit**。
