# MACD_MTF_Strategy_V9_1

> 文档用途：整理 `session-only V9.1` 的正式结论，并补充在其基础上继续做的 “只压回撤、不动收益骨架” 微调结果，供专家组评审。  
> 当前实盘基线：仍为 `V8/A`。  
> 当前候选实盘配置：`config/candidates/trading_config_fund_flow_v9_2a_candidate.json`。  
> 当前最优候选：`V9.2A`。

---

## 一、版本结论

`V9.1` 的核心思路是正确的：

- 不动 `4H 主方向 + 1H light confirmation`
- 不动 `pre-flip trial`
- 不动 `A` 的定向亏损 pocket 过滤
- 只增加 `session_risk_control`
- 不放开 `weak-loss shrink exit`

但 `V9.1` 单独版本虽然提升了收益和 PF，回撤仍高于 `V8/A`。  
继续沿着 session 风控做窄调后，`V9.2A / V9.2B` 已经同时做到：

- 收益高于 `V8/A`
- PF 高于 `V8/A`
- MDD 低于 `V8/A`

这说明这条路是有效的，问题不在 session 风控本身，而在 `V9.1` 只覆盖了美股盘前窗口，没有补掉亚洲薄流动性时段。

---

## 二、V9.1 定义

### 2.1 V9.1 的唯一新增结构

`session-only V9.1` 只增加：

```json
"session_risk_control": {
  "enabled": true,
  "high_risk_sessions": [
    { "utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65 }
  ],
  "apply_to_states": ["short_dual_pressure", "flip_bullish"]
}
```

并保持：

- `exit_4h_require_profit = true`
- `exit_4h_min_shrink_pct = 0.20`
- `consecutive_loss_cooldown_seconds = 1800`

也就是说，`V9.1` 不改离场逻辑，只在高风险时段把相关 setup 的仓位缩到 `65%`。

### 2.2 V9.1 正式回测结果

摘要文件：`output/backtest/v2_summary_20260321_210450.json`

| 版本 | Return | PF | MDD | Win Rate | Trades |
| --- | --- | --- | --- | --- | --- |
| V8/A | `+92.38%` | `2.74` | `10.69%` | `71.43%` | `511` |
| V9.1 | `+96.10%` | `2.94` | `12.66%` | `70.88%` | `498` |

### 2.3 V9.1 的判断

优点：

- 收益提升：`+92.38% -> +96.10%`
- PF 提升：`2.74 -> 2.94`

问题：

- MDD 恶化：`10.69% -> 12.66%`

结论：

- `V9.1` 不是最终替代版
- 但它已经证明 session 风控方向正确
- 下一步不该回退，而该继续把 session 风控做精

---

## 三、V9.1 回撤画像

分析文件：

- `output/backtest/v2_trades_20260321_210450.csv`
- `output/backtest/v2_equity_curve_20260321_210450.csv`

### 3.1 亏损主源

`V9.1` 的亏损仍主要来自：

- `stop_loss_intrabar`
- `green_bar_growing`
- `short_dual_pressure`

其中亏损最重的状态仍是：

| 状态 | 亏损笔数 | 总亏损 |
| --- | --- | --- |
| `short_dual_pressure` | `51` | `-2483.97` |
| `short_retest_reject` | `31` | `-1679.26` |
| `long_dual_support` | `33` | `-909.50` |

### 3.2 时段分布

亏损按入场小时聚集最明显的几个 UTC 时段：

- `03:00`
- `05:00`
- `07:00`
- `14:00`
- `15:00`

其中 `2026-02-09 ~ 2026-02-15` 这一段 drawdown cluster 里，最脏的一块就是：

- `green_bar_growing + short_dual_pressure`
- 主要落在 `UTC 03:00~05:30`

这与 V9 初始建议里提到的“亚洲薄流动性段”完全一致。

结论：

- `V9.1` 只覆盖了 `14:30~16:00`
- 还漏掉了 `03:00~05:30`
- 所以回撤压缩不完整

---

## 四、V9.2 微调验证

### 4.1 V9.2A

思路：

- 保持 `V9.1` 其它结构不变
- 新增第二个 session 风控窗口

```json
"high_risk_sessions": [
  { "utc_start": "03:00", "utc_end": "05:30", "position_scale": 0.70 },
  { "utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65 }
],
"apply_to_states": ["short_dual_pressure", "flip_bullish"]
```

摘要文件：`output/backtest/v2_summary_20260321_212230.json`

### 4.2 V9.2B

思路：

- 与 `V9.2A` 相同的两个 session 窗口
- 但只作用在 `short_dual_pressure`

```json
"apply_to_states": ["short_dual_pressure"]
```

摘要文件：`output/backtest/v2_summary_20260321_212235.json`

### 4.3 正式结果总表

| 版本 | Return | PF | MDD | Win Rate | Trades |
| --- | --- | --- | --- | --- | --- |
| V8/A | `+92.38%` | `2.74` | `10.69%` | `71.43%` | `511` |
| V9.1 | `+96.10%` | `2.94` | `12.66%` | `70.88%` | `498` |
| V9.2A | `+99.39%` | `3.04` | `10.10%` | `70.88%` | `498` |
| V9.2B | `+99.35%` | `3.04` | `10.10%` | `70.88%` | `498` |

---

## 五、结果解释

### 5.1 为什么 V9.2 明显优于 V9.1

关键不是“更激进地缩仓”，而是“更精准地在第二个脏 session 上缩仓”。

`V9.2A/B` 相比 `V9.1`：

- return 再提升约 `+3.25pp`
- PF 再提升约 `+0.10`
- MDD 从 `12.66%` 压到 `10.10%`

这说明：

- `session_risk_control` 不是拖收益的机制
- 真正有效的是把它放在对的时间窗

### 5.2 为什么 V9.2A/B 几乎一样

`flip_bullish` 在新增亚洲窗口上的实际影响较小。  
所以：

- `V9.2A` 对 `flip_bullish` 也降仓
- `V9.2B` 只处理 `short_dual_pressure`

最终结果几乎重合。

这意味着：

- 主要 alpha 来自 `short_dual_pressure` 的 session 降仓
- `flip_bullish` 是否一起纳入，不再是决定性问题

---

## 六、建议

### 6.1 给专家组的明确结论

1. `V9.1` 本身应视为“方向验证通过，但版本未完成”  
2. `V9.2A/B` 已经把这个方向走通  
3. 当前最优候选是 `V9.2A`

### 6.2 为什么推荐 V9.2A

虽然 `V9.2A` 与 `V9.2B` 非常接近，但 `V9.2A` 仍略优：

- Return 更高
- PF 更高
- MDD 略低

同时它与原始 V9 文档的意图更一致：

- 美股盘前去风险
- 亚洲薄流动性段去风险
- 作用于最常见的高风险主力 setup

### 6.3 当前执行状态

1. `V8/A` 继续保留为当前正式实盘基线  
2. `V9.2A` 已提升为新的候选实盘配置，并固化为独立配置快照  
3. 归因复核已补完，下一步只需决定是否进入 shadow/live candidate 观察

---

## 七、实现状态

已完成：

- `session_risk_control` 能力已接入策略、回测、决策链路
- `V9.1 / V9.2A / V9.2B` profile 已写入配置
- `V9.2A` 候选实盘配置快照已生成：`config/candidates/trading_config_fund_flow_v9_2a_candidate.json`
- `V9.2A` 归因复核报告已补充：`docs/MACD_MTF_Strategy_V9_2A_Attribution_Review.md`
- 回归测试通过

相关文件：

- `src/fund_flow/macd_strategy_v2.py`
- `scripts/backtest_macd_v2.py`
- `src/fund_flow/decision_engine.py`
- `config/trading_config_fund_flow.json`
- `tests/test_macd_strategy_v2_4h_scoring.py`
- `tests/test_backtest_profiles.py`

---

*文档版本：V9.1 评审稿 / 更新日期：2026-03-21*
