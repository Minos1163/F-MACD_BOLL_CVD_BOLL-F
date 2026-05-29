# 2026-05-27 最新 8H 四象限策略无开仓 BUG 归因报告

**评审对象**：实盘 `quadrant_resonance` 最新 8 小时日志  
**分析时间**：北京时间 `2026-05-27 19:08`  
**最新日志时间**：UTC `2026-05-27 11:00:15` / 北京时间 `2026-05-27 19:00:15`  
**分析窗口**：UTC `2026-05-27 03:00:15` 至 `2026-05-27 11:00:15`  
**北京时间窗口**：`2026-05-27 11:00:15` 至 `2026-05-27 19:00:15`  
**日志来源**：

- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\runtime.out.06.log`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\runtime.out.12.log`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\runtime.out.18.log`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow\fund_flow_entry_exit_audit.jsonl`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\trade_fills_utc.csv`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow\fund_flow_risk_state.json`

---

## 1. 结论先行

最新 8 小时仍然没有任何开仓，直接原因不是策略阈值太高，也不是执行层拒单，而是一个明确的**指标供给/字段契约 BUG**：

```text
quadrant_resonance 需要 4H ema20 / ema50 / ema200 判断四象限；
实盘传入的 4H timeframes 中 ema20_4h = 0、ema50_4h = 0；
ema200_4h 和 macd_hist_4h 有值；
因此每个 symbol 都被标记为 missing_indicators；
最终全部 quadrant_defense_no_entry。
```

这意味着四象限策略不是“判断市场不该开仓”，而是**拿不到必要的 4H EMA20/EMA50 输入，所以永远无法成立 Q1/Q2/Q3/Q4**。

本轮应优先修复指标上下文字段映射/计算链路，再谈慢牛旁路、Q0 或放宽阈值。否则继续优化策略参数没有意义。

---

## 2. Runtime 统计

窗口：UTC `2026-05-27 03:00:15` 起。

| 指标 | 结果 |
|---|---:|
| FUND_FLOW cycles | 33 |
| 首个周期 | `2026-05-27T03:01:20Z` |
| 最新周期 | `2026-05-27T11:00:03Z` |
| `logic=quadrant_resonance` | 896 |
| `决策=HOLD` | 896 |
| `状态=noop` | 896 |
| `决策原因=quadrant_defense_no_entry` | 896 |
| `HOLD归因=waiting_rule_confirmation` | 896 |
| BUY/SELL/CLOSE 行数 | 0 |

慢牛检测：

| `SLOW_BULL` | cycles |
|---|---:|
| `is_bull=True` | 8 |
| `is_bull=False` | 25 |

说明：即使有 8 个周期慢牛成立，开仓仍没有进入候选层，因为四象限第一关已经被 `missing_indicators` 阻断。

---

## 3. 主审计统计

文件：

```text
D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow\fund_flow_entry_exit_audit.jsonl
```

统计结果：

| 指标 | 结果 |
|---|---:|
| 审计记录总数 | 1792 |
| `pre_execution` | 896 |
| `post_execution` | 896 |
| 覆盖 symbol | 28 |
| `operation=hold` | 1792 |
| `execution.status=noop` | 896 |
| `reason=quadrant_defense_no_entry` | 1792 |
| `strategy.blocked_reason_detail=missing_indicators` | 1792 |
| `signal.quadrant_debug.quadrant_4h=DEFENSE` | 1792 |

4H EMA 缺失统计：

| 字段状态 | 记录数 |
|---|---:|
| `ema20_4h == 0` | 1792 |
| `ema50_4h == 0` | 1792 |
| `ema200_4h == 0` | 0 |
| `ema20_4h == 0 && ema50_4h == 0 && ema200_4h != 0` | 1792 |

这个模式非常关键：不是整个 4H 数据缺失，也不是 MACD 缺失，而是短/中 EMA 字段缺失。

---

## 4. 样本证据

### 4.1 HYPEUSDT

时间：UTC `2026-05-27T03:15:04Z`

```json
{
  "symbol": "HYPEUSDT",
  "operation": "hold",
  "reason": "quadrant_defense_no_entry",
  "strategy": {
    "blocked_reason_detail": "missing_indicators"
  },
  "signal": {
    "quadrant_debug": {
      "quadrant_4h": "DEFENSE",
      "ema20_4h": 0.0,
      "ema50_4h": 0.0,
      "ema200_4h": 48.751655992703505,
      "close_4h": 61.062,
      "ema_state_4h": 0,
      "macd_hist_4h_last3": [-0.484512363025193, -0.571382419357937, -0.5164777107435203],
      "macd_pos_strength_4h": false,
      "macd_neg_strength_4h": false,
      "blocked_reason_detail": "missing_indicators"
    }
  }
}
```

### 4.2 XRPUSDT

```json
{
  "symbol": "XRPUSDT",
  "blocked_reason_detail": "missing_indicators",
  "quadrant_4h": "DEFENSE",
  "ema20_4h": 0.0,
  "ema50_4h": 0.0,
  "ema200_4h": 1.3967265528236363,
  "macd_hist_4h_last3": [-0.00058437057449174, -0.00130768415878966, -0.001458079959532275],
  "macd_neg_strength_4h": true
}
```

XRP 的样本尤其说明问题：`macd_neg_strength_4h=true`，但因为 EMA20/EMA50 缺失，仍然无法进入 Q3/Q4，只能 DEFENSE。

### 4.3 BCHUSDT

```json
{
  "symbol": "BCHUSDT",
  "blocked_reason_detail": "missing_indicators",
  "ema20_4h": 0.0,
  "ema50_4h": 0.0,
  "ema200_4h": 411.84,
  "macd_hist_4h_last3": [1.04166503191957, 0.706865384177062, 0.5715709683220]
}
```

所有样本都有相同模式：`ema20_4h` 和 `ema50_4h` 为 0，`ema200_4h` 与 MACD 有值。

---

## 5. 排除项

### 5.1 不是执行层拒单

日志内没有 `BUY` / `SELL` 开仓动作。所有执行结果都是：

```text
operation=hold
execution.status=noop
```

所以订单没有进入执行层。

### 5.2 不是保证金、最小名义价值、容量阻断

审计中以下字段均为空或未触发：

```text
min_open_notional_gate = null
micro_notional_gate = null
micro_margin_gate = null
gate_cap_applied = null
```

`estimated_notional_usdt` 全部为 `0.0`，因为上游信号已经 HOLD。

### 5.3 不是风控熔断

风险状态：

```json
{
  "consecutive_losses": 0,
  "daily_open_equity": 98.40509958,
  "peak_equity": 98.41062978,
  "updated_at": "2026-05-27T11:45:04.208768"
}
```

没有连续亏损熔断、日亏损熔断或全局冷却证据。

### 5.4 不是实盘没加载新审计代码

`fund_flow_entry_exit_audit.jsonl` 已经出现：

```text
strategy.blocked_reason_detail
signal.quadrant_debug
```

说明上一轮审计增强已在实盘日志中生效，进程已经加载了新代码。

### 5.5 没有 2026-05-27 成交

`trade_fills_utc.csv` 最新成交仍停留在 UTC `2026-05-25 13:15:15`。这与 runtime/audit 的“无开仓”一致。

---

## 6. 代码路径归因

### 6.1 四象限策略要求的字段

文件：

```text
src\fund_flow\quadrant_resonance.py
```

四象限判定读取：

```python
e20 = tf4h.get("ema20")
e50 = tf4h.get("ema50")
e200 = tf4h.get("ema200")
```

若 `ema20` 或 `ema50` 为 0，则：

```text
ema_state_4h = 0
blocked_reason_detail = missing_indicators
quadrant_4h = DEFENSE
```

### 6.2 实盘上下文构建路径

实盘市场上下文来自：

```text
src\app\fund_flow_bot.py
get_market_data_for_symbol()
  -> market_data.get_trend_filter_metrics(symbol, interval=timeframe)
  -> trend_filters_by_timeframe
  -> _build_fund_flow_context()
  -> _materialize_flow_snapshot()
  -> _apply_timeframe_context()
  -> flow_context["timeframes"]
  -> FundFlowDecisionEngine._decide_quadrant_resonance_strategy()
  -> QuadrantResonanceEngine.analyze()
```

当前日志说明这条链路中，4H 上下文有：

```text
close_4h
ema200_4h
macd_hist_4h_last3
```

但没有有效：

```text
ema20_4h
ema50_4h
```

### 6.3 字段契约不一致

回测路径中，四象限使用的是完整字段：

```text
scripts\backtest_macd_v2.py
ema20
ema50
ema200
```

但实盘 trend filter 历史上更常见字段是：

```text
ema_fast / ema_slow
ema21 / ema55
bb_middle
ema200
```

因此当前最可能的 BUG 是：

```text
回测侧给 quadrant_resonance 提供 ema20/ema50；
实盘侧 trend_filter 没有把 ema_fast/ema_slow 或 ema21/ema55 映射为 ema20/ema50；
导致实盘四象限永远 missing_indicators。
```

这属于回测-实盘字段契约不一致，不属于市场状态判断或参数问题。

---

## 7. BUG 影响

当前 BUG 的影响是全局性的：

- 28 个 symbol 全部受影响。
- 33 个扫描周期全部受影响。
- 1792 条审计全部同一阻断。
- `ema20_4h`、`ema50_4h` 缺失率为 100%。
- 只要这个字段缺失存在，`quadrant_resonance` 无法产生任何 Q1/Q2/Q3/Q4 entry。

换句话说，当前实盘四象限策略处于“永久 DEFENSE”状态。

---

## 8. 建议修复方向

### 8.1 第一优先级：修复实盘 timeframes 字段契约

需要在实盘构建 `flow_context["timeframes"]` 时，确保每个周期至少包含：

```json
{
  "ema20": 0.0,
  "ema50": 0.0,
  "ema200": 0.0,
  "macd_hist_series": [],
  "rsi": 0.0,
  "atr": 0.0,
  "close": 0.0
}
```

如果上游只有旧字段，应做明确映射：

```text
ema20 <- ema20 或 ema_20 或 ema_fast 或 ema21
ema50 <- ema50 或 ema_50 或 ema_slow 或 ema55
ema200 <- ema200 或 ema_200
```

注意：这只是字段映射修复，不是策略放宽。

### 8.2 第二优先级：补测试防回归

必须增加集成测试，构造实盘 `trend_filters_by_timeframe["4h"]` 只有 `ema_fast/ema_slow/ema200` 的情况，断言进入四象限前会映射成：

```text
timeframes["4h"]["ema20"] > 0
timeframes["4h"]["ema50"] > 0
timeframes["4h"]["ema200"] > 0
```

同时断言不再出现：

```text
blocked_reason_detail = missing_indicators
```

除非真的缺少所有可映射字段。

### 8.3 第三优先级：修复后继续观察 2-4 个周期

修复后不要立刻调参。先观察：

```text
missing_indicators 是否从 100% 降到 0%
blocked_reason_detail 是否变成 ema_disorder 或 macd_not_strengthening
是否开始出现 Q1/Q2/Q3/Q4 但因 score/rsi/entry pattern 被拒
```

只有当字段修复后仍长期不开仓，才进入策略优化阶段。

---

## 9. 给 DeepSeek 的评审问题

请优先评审以下问题：

1. 是否同意本次无开仓根因是实盘 4H EMA20/EMA50 指标缺失，而非策略阈值问题？
2. `ema_fast/ema_slow` 映射为 `ema20/ema50` 是否安全，还是必须从 K 线重新计算严格 EMA20/EMA50？
3. 如果实盘 `trend_filter_metrics` 只有 EMA21/EMA55，四象限策略是否应接受近似映射，还是必须改成 EMA21/55/200 版本？
4. 修复字段后，是否应该先跑 24H shadow/audit，再开放任何慢牛 Q0 旁路？
5. 是否需要将 `missing_indicators` 设为运维告警，因为它代表策略不可交易，而不是普通 HOLD？

---

## 10. 最终归因

最新 8 小时没有开仓的根因是：

```text
实盘 quadrant_resonance 的 4H 指标上下文缺少 ema20 / ema50，
导致 4H EMA 排列无法计算，
所有 symbol 被判定为 missing_indicators，
进而全部 quadrant_defense_no_entry。
```

这应归类为**实盘指标字段映射 BUG / 回测实盘输入契约不一致**。

当前不建议先优化策略参数。正确顺序是：

```text
先修复 4H ema20/ema50 指标输入
再观察 missing_indicators 是否归零
再分析真实阻断门槛
最后再讨论 Q0、慢牛旁路或阈值优化
```
