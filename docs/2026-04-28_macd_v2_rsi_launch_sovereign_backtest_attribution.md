# MACD V2 RSI 启动主权模式回测归因

- 评审对象：`macd_mtf_strategy_v2`
- 回测窗口：`2026-02-23 ~ 2026-03-24T23:59:59`
- 基线摘要：[`v2_summary_20260427_003311.json`](../output/backtest/v2_summary_20260427_003311.json)
- 本轮摘要：[`v2_summary_20260428_082355.json`](../output/backtest/v2_summary_20260428_082355.json)

## 结论

本轮实现把系统从“低吞吐高质量”推成了“高吞吐中高质量”。结果是：

- `total_trades` 从 `14` 提升到 `96`
- `candidate_entries` 从 `46` 提升到 `390`
- `orders_filled / orders_submitted` 从 `14 / 44` 提升到 `96 / 209`
- `return_pct` 从 `24.54%` 提升到 `82.17%`
- `max_drawdown_pct` 从 `5.93%` 上升到 `8.90%`
- `win_rate_pct` 从 `85.71%` 回落到 `79.17%`
- `profit_factor` 从 `25.09` 回落到 `6.09`

结论很明确：这轮的主贡献是**候选池扩容**，不是单一信号胜率提升。

## 归因拆解

### 1. 吞吐扩张来自候选池，而不是风控放松

最大变化发生在前端漏斗：

- `candidate_entries`: `46 -> 390`
- `orders_submitted`: `44 -> 209`
- `orders_filled`: `14 -> 96`

这说明系统现在不再卡在“几乎不出候选”的状态，而是能持续把信号推到执行层。

但这并不等于执行效率完全改善，因为：

- `blocked_neutral_signal` 仍然很高：`71222 -> 69126`
- `capacity_full_precheck_candidates` 变成 `114`
- `capacity_competition_dropped` 变成 `51`
- `pending_cancel_reasons` 仍然全部是 `ioc_no_fill=113`

所以这轮的真实瓶颈已经从“没信号”转成“候选太多、同 bar 竞争、IOC 未成交”。

### 2. 信号结构不再单点驱动

本轮成交分布如下：

- `red_bar_growing`: `36` 笔，胜率 `75%`，PnL `+2250.35`
- `flip_bullish`: `12` 笔，胜率 `66.67%`，PnL `+1843.45`
- `flip_bearish`: `8` 笔，胜率 `75%`，PnL `+1797.95`
- `green_bar_growing`: `8` 笔，胜率 `87.5%`，PnL `+1376.71`
- `red_bar_shrinking`: `19` 笔，胜率 `78.95%`，PnL `+1230.37`
- `green_bar_shrinking`: `13` 笔，胜率 `100%`，PnL `+252.92`

这说明本轮收益并不是只靠 `flip_bullish` 或 `flip_bearish` 单点释放，而是更广的信号面都在工作。

### 3. `flip_bullish` 恢复了，但还不是主引擎

`flip_bullish` 从基线 `3` 笔提升到 `12` 笔，说明主通道不再接近灭绝。

但它的胜率只有 `66.67%`，明显低于总胜率 `79.17%`，所以它目前更多是“恢复产能”，还不是“高胜率核心引擎”。

### 4. `WSR` 需要分口径看

如果按候选口径算：

- `WSR = 1 - orders_filled / candidate_entries`
- 基线：`69.57%`
- 本轮：`75.38%`

这个口径下，WSR 其实更差，因为候选池放大太快。

如果按挂单口径算：

- `WSR = orders_canceled / orders_submitted`
- 基线：`68.18%`
- 本轮：`54.07%`

这个口径下，执行转化是改善的。

结论：**候选质量稀释了，但提交后的成交效率提升了。**

## 风险变化

本轮不是纯收益升级，而是典型的“扩容换回报”：

- 收益显著上升
- 回撤略有抬高，但仍低于 `10%`
- 胜率和 PF 回落，但仍保持正向且稳定

这意味着下一轮如果继续追 90-120 笔，必须重点盯住：

1. `flip_bullish` 胜率能否继续抬升
2. `orders_filled / orders_submitted` 能否继续提高
3. `capacity_competition_dropped` 能否被压低
4. `ioc_no_fill` 能否继续下降

## 归因结论

这轮结果的核心不是“单个主权信号变强”，而是：

- 候选池显著扩大
- 同 bar 竞争更激烈
- 执行层成交率提高
- 但信号纯度被稀释，导致胜率从 `85.71%` 回落到 `79.17%`

换句话说，这轮已经证明系统可以从“静默”切到“放量”，但下一步要做的是：

- 继续保住吞吐
- 同时把 `flip_bullish` 的质量重新拉高
- 再把扩量的增量收益从 82% 的总收益里保住一部分

