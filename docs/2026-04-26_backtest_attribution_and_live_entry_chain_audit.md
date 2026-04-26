# 2026-04-26 MACD V2 回测归因与实盘开仓链路审计

## 0. 范围

- 代码范围: `src/fund_flow/decision_engine.py`, `src/fund_flow/macd_strategy_v2.py`, `scripts/backtest_macd_v2.py`
- 日志范围: `logs/2026-04/2026-04-25/*`
- 目的:
  - 记录当前实盘开仓链路的真实门槛和 veto
  - 归因 `weak_combo_veto` 对 30 天回测的影响
  - 给 DeepSeek 做下一轮评审时提供可核对的证据包
- 说明:
  - `2026-04-25` 的 market data 在本地 backtest cache 里缺失，所以“单日回放”无法用回测脚本重跑成完整交易序列。
  - 该日的实盘归因改用 `runtime.out.*`, `api_cycle_stats_utc.jsonl`, `trade_fills_utc.csv` 做证据。

## 1. 当前代码链路

### 1.1 方向治理

- `macd_4h_regime_state.side_override_mode` 是 MACD V2 的实际方向来源。
- `direction_lock` 现在镜像这个 effective mode，不再单独表达另一套判断。
- 返回开仓前会先过 `direction_gate_veto`，再进入 symbol side override。

### 1.2 过滤器状态

- `momentum_exhaustion_veto` 已从策略和配置解析中移除。
- 新增 `weak_combo_veto`:
  - `green_bar_shrinking + soft_short_*`
  - `red_bar_shrinking + soft_long_*`
- 该 veto 在 15m soft confirmation 后、总分阈值前生效。

### 1.3 当前核心阈值

- `min_signal_score = 0.82`
- `preflip_trial_min_signal_score = 0.75`
- `min_entry_score = 0.25`
- `min_vwap_score_for_entry = 0.10`
- `max_positions = 3`
- `leverage = 2x ~ 4x`
- `stop_loss_pct = 0.50%`
- `take_profit_pct = 0`

## 2. 30 天回测归因

时间窗: `2026-02-23 ~ 2026-03-24`

### 2.1 历史已确认结论

来自前一轮评审数据:

- 关闭 `momentum_exhaustion_veto` 后:
  - Return: `+212.14% -> +226.79%`
  - Max Drawdown: `16.95% -> 12.01%`

这说明 momentum 过滤器已经被证实是误伤项，当前代码已按这个结论移除。

### 2.2 当前代码回测

| 方案 | Return | Win Rate | Max DD | Trades | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| 当前代码 | `+167.43%` | `75.8%` | `8.01%` | `277` | 启用 `weak_combo_veto` |
| 禁用 `weak_combo_veto` 对照 | `+229.06%` | `78.5%` | `12.01%` | `265` | monkeypatch 对照 |

### 2.3 归因

- `weak_combo_veto` 在这段窗口里一共拦掉 `4331` 次信号。
- 真正影响到成交结果的是 `12` 笔实际成交。
- 关掉它后，收益和胜率明显更高，但最大回撤也回升到 `12.01%`。
- 结论:
  - 这个 veto 确实砍掉了尾段单
  - 但它是否应该保持“硬否决”还值得继续评审

## 3. 2026-04-25 实盘日志归因

### 3.1 14:15 UTC 的开仓漏斗

- `DOGEUSDT`
  - `signal_score = 0.7186`
  - `threshold = 0.7500`
  - `stage = threshold_check`
  - `signal_type_1h = green_bar_shrinking`
  - `entry_15m = soft_short_neutral`
  - `lock = SHORT_ONLY`
- 结论: 没开仓的直接原因是 `score < 0.75`，不是方向锁。

### 3.2 18:00 UTC 的 VET 样本

- `VETUSDT`
  - `signal_score = 0.7378`
  - `threshold = 0.7500`
  - `stage = threshold_check`
  - `signal_type_1h = green_bar_growing`
  - `entry_15m = green_bar_shrinking`
  - `lock = LONG_ONLY`
- 结论: 仍然是阈值不足，不是方向门先杀掉。

### 3.3 成交侧证据

- `trade_fills_utc.csv` 里 2026-04-25 的 VET / DOGE 记录是卖出侧为主。
- 该 CSV 当前仍不适合直接算净 PnL，因为手续费记账口径仍需单独修复。

## 4. 实盘开仓链路

1. 4H regime 决定 `side_override_mode`
2. `direction_lock` 镜像这个有效模式
3. 1H 方向信号生成
4. 15m soft confirmation / refinement
5. `threshold_check`
6. 仓位与杠杆计算
7. 风控与保护链
8. 下单

### 4.1 现在日志里会直接告诉你的东西

- 本次被哪个 stage 拦下
- 是 `threshold_check` 还是明确 veto
- `signal_type_1h`
- `entry_type_15m`
- `direction_lock`
- `direction_gate_source`

## 5. 给 DeepSeek 的结论

- `momentum_exhaustion_veto` 应继续保持删除状态。
- `weak_combo_veto` 已经证明能砍掉一部分尾段单，但当前窗口里它也显著压低了收益。
- 下一轮评审应优先判断:
  - `weak_combo_veto` 是保留硬否决，还是改成 score penalty
  - `preflip_trial_min_signal_score = 0.75` 是否才是 VET / DOGE 这类样本的主要瓶颈
  - 方向治理和执行侧 override 是否已经完全同源

