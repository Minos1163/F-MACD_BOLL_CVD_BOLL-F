# MACD_MTF_Strategy_V11_First_Batch_Validation

> 文档用途：记录 `V10 -> V11` 第一批优化验证结果。  
> 当前 live 基线：`V10`。  
> 本轮目标：先验证 `F1` 静态 watchlist 节流，以及 `F1a / F1+B1` 两个窄变体，判断是否值得进入下一轮候选。  
> 结论日期：`2026-03-21`。

---

## 一、结论先行

本轮第一批验证结论：`Reject F1`，`Reject F1+B1`，`Keep F1a only as implementation fallback, not as candidate`。

原因很直接：

- `F1` 虽然把 `watchlist` 暴露压下去了，但同时明显削弱总收益，并让回撤变差
- `F1+B1` 提高了 PF，但回撤进一步恶化，已经偏离“低风险修补”的目标
- `F1a` 只在高风险 session 对 watchlist 做二次缩仓，结果几乎与 `V10` 重合，没有形成可交易增量

因此：

- 第一批里，静态 watchlist 全局硬帽不应进入 live candidate
- `G1` 的“集中度控制”不能用这类粗颗粒静态节流替代
- 下一轮应优先转向更精细的仓位质量分层，而不是继续扩大 watchlist 静态压制

---

## 二、本轮实际实现

本轮已接入的底层能力：

- `symbol_risk_tiers.watchlist_symbols`
- `watchlist_max_position_portion`
- `watchlist_max_leverage`
- `watchlist_apply_session_scale_double`
- `watchlist_session_scale_multiplier`

接入位置：

- `src/fund_flow/macd_strategy_v2.py`
- `src/fund_flow/decision_engine.py`
- `scripts/backtest_macd_v2.py`

回归测试：

- `25 passed`

相关 profile：

- `macd_v2_v11_watchlist_throttle`
- `macd_v2_v11_watchlist_session_only`
- `macd_v2_v11_watchlist_throttle_preflip_symmetric`

说明：

- 当前 live `V10` 主配置没有启用这些新能力
- 这轮只作为 backtest candidate 验证，不触碰现有实盘参数

---

## 三、结果总表

| 版本 | Return | PF | MDD | Trades | 结论 |
| --- | --- | --- | --- | --- | --- |
| `V10` | `+99.39%` | `3.04` | `10.10%` | `498` | 基线 |
| `F1` watchlist 全局硬帽 | `+96.60%` | `3.12` | `11.47%` | `498` | Reject |
| `F1a` watchlist session-only | `+99.38%` | `3.04` | `10.10%` | `498` | Neutral |
| `F1+B1` watchlist 硬帽 + preflip 对称 | `+98.03%` | `3.16` | `12.70%` | `519` | Reject |

摘要文件：

- `V10`: `output/backtest/v2_summary_20260321_212230.json`
- `F1`: `output/backtest/v2_summary_20260321_224546.json`
- `F1a`: `output/backtest/v2_summary_20260321_225843.json`
- `F1+B1`: `output/backtest/v2_summary_20260321_224553.json`

---

## 四、为什么 F1 失败

### 4.1 归因里的“回吐币种”不是“绝对该压币种”

`V10` 下这 5 个 watchlist 币的绝对 PnL 是：

| 币种 | V10 PnL |
| --- | --- |
| `LINKUSDT` | `+366.24` |
| `ONDOUSDT` | `+345.26` |
| `LTCUSDT` | `+82.42` |
| `MORPHOUSDT` | `-97.23` |
| `TRUMPUSDT` | `+1439.21` |

也就是说：

- 它们相对 `V8/A` 的 delta 有回吐
- 但在 `V10` 绝对维度上，并不都是负资产
- 尤其 `TRUMPUSDT` 仍是高正贡献币

因此用“全局 40% + 2x”直接压这 5 个币，会先砍掉已有正收益，而不是只砍坏 pocket。

### 4.2 F1 的实际代价

`F1` 相对 `V10` 的 watchlist delta：

- `LINKUSDT`: `-53.46`
- `ONDOUSDT`: `-222.33`
- `LTCUSDT`: `-12.10`
- `MORPHOUSDT`: `+49.17`
- `TRUMPUSDT`: `-765.43`

watchlist 合计变化：

- `-1004.16`

最关键的问题不是 `LINK / ONDO / LTC`，而是：

- `TRUMPUSDT` 被过度限仓，直接丢掉了最大一块利润

### 4.3 集中度没有改善，反而更差

top 3 symbol pnl 占比：

- `V10`: `52.62%`
- `F1`: `59.54%`
- `F1+B1`: `58.13%`

说明：

- 静态 watchlist 硬帽没有解决组合集中度
- 反而因为削掉了一组中高贡献币，导致剩余利润更加集中

---

## 五、F1a 为什么只是 Neutral

`F1a` 的定义是：

- 不做全局 40%/2x 硬帽
- 只在已有高风险 session 内，对 watchlist 再乘一次 `0.8`

结果几乎和 `V10` 一致：

- Return：`99.39% -> 99.38%`
- PF：`3.04 -> 3.04`
- MDD：`10.10% -> 10.10%`
- Trades：`498 -> 498`

这说明：

- “只在 session 里再压 watchlist” 不会明显破坏骨架
- 但也没有形成统计上有意义的新优势

所以它更像一个：

- 已实现的安全 fallback 能力
- 而不是值得提升为候选版本的优化项

---

## 六、F1+B1 为什么也不能接受

`F1+B1` 在 `F1` 基础上再做：

- `preflip_trial_min_shrink_pct_long: 0.75 -> 0.60`
- `preflip_trial_min_shrink_pct_short: 0.30 -> 0.40`

结果：

- Return 低于 `V10`
- PF 提高到 `3.16`
- 但 MDD 恶化到 `12.70%`
- Trades 提高到 `519`

解释：

- 对称化放宽了交易参与
- 但它和 watchlist 硬帽叠加后，没有把风险压住
- 反而让组合重新进入“多做单 + 回撤抬头”的状态

因此本轮不能得出 “B1 应直接进入第二批” 的结论。  
至少在当前实现下：

- `B1` 不应和 `F1` 绑定验证

---

## 七、对 V11 路线的修正

本轮验证后，`V11_优化建议` 需要修正一条关键前提：

原假设：

- watchlist 5 币可以用静态全局节流先处理

修正后：

- 这 5 币更适合做“按时段/按信号/按滚动绩效”的精细节流
- 不适合先用全局硬帽一刀切

更准确地说：

- `F1` 不是方向完全错
- 错的是“节流颗粒度太粗”

---

## 八、下一步建议

基于本轮结果，下一轮优先级建议调整为：

1. `C1`：`vwap_score` 三档仓位乘数  
2. `G1`：组合级集中度控制，但必须做成真正的组合状态机，不能拿静态 watchlist 代替  
3. `B1`：单独 profile 重新验证，不再与 `F1` 绑定  
4. `F2`：动态 Z-score 节流，作为真正的“滚动绩效驱动” watchlist 版本

本轮明确暂缓：

- 不将 `F1` 或 `F1+B1` 提升为 live candidate
- 不修改当前 `V10` 实盘基线

---

*文档版本：V11 first-batch validation / 更新日期：2026-03-21*
