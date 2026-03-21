# MACD_MTF_Strategy_V10

> 文档用途：将 `V9.2A` 正式提升为当前实盘版本 `V10`，汇总当前 live 参数、止损结构、session 风控、全样本正式回测与后续观察项，供专家组继续讨论。  
> 生效范围：基础配置 `fund_flow.macd_mtf_strategy_v2` 已切换到 `V10` 实盘参数。  
> 对照基线：`V8/A`。  
> 配套归因复核：`docs/MACD_MTF_Strategy_V9_2A_Attribution_Review.md`。

---

## 一、版本结论

`V10` 不是新起一套结构，而是把已经完成归因复核的 `V9.2A` 正式部署到 live。

核心结论：

- 保留 `4H 主方向 + 1H light confirmation`
- 保留 `4H pre-flip 试仓`
- 保留 `A` 的两条定向亏损 pocket 过滤
- 保留 `4H shrink exit`，且仍要求盈利保护
- 正式加入双时段 `session_risk_control`
- 不启用旧的 `short_quality_filter`

因此 `V10` 的真实含义不是“推翻 V8”，而是：

- 延续 `V8/A` 的正收益骨架
- 继续只压已识别的高风险时段亏损 pocket
- 将 `V9.2A` 从 candidate 提升为当前实盘版本

---

## 二、当前实盘参数

### 2.1 方向与入场框架

当前基础配置：

| 模块 | 参数 | 当前值 |
| --- | --- | --- |
| 主方向 | `primary_direction_timeframe` | `4h` |
| 1H 确认 | `require_1h_confirmation_when_4h_primary` | `true` |
| 1H 轻确认 | `light_1h_confirmation_when_4h_primary` | `true` |
| 允许 1H 中性 | `allow_neutral_1h_confirmation` | `false` |
| 4H pre-flip 试仓 | `enable_4h_preflip_trial_entries` | `true` |
| 试仓 long shrink 阈值 | `preflip_trial_min_shrink_pct_long` | `0.75` |
| 试仓 short shrink 阈值 | `preflip_trial_min_shrink_pct_short` | `0.30` |
| 试仓最低分数 | `preflip_trial_min_signal_score` | `0.77` |
| 试仓最低 VWAP 分 | `preflip_trial_min_vwap_score` | `0.06` |
| 试仓仓位缩放 | `preflip_trial_entry_scale` | `0.35` |
| 试仓最大杠杆 | `preflip_trial_max_leverage` | `2` |

### 2.2 保留的 V8/A 定向过滤器

#### A1. short green_bar_growing ADX pocket 过滤

只针对：

- 非 `trial entry`
- `trade_direction == short`
- `signal_type_1h == green_bar_growing`

| 参数 | 当前值 |
| --- | --- |
| `enable_green_bar_growing_short_adx_1h_range_filter` | `true` |
| `green_bar_growing_short_min_adx_1h` | `25.0` |
| `green_bar_growing_short_max_adx_1h` | `30.0` |

#### A2. long flip_bullish CVD context 过滤

只针对：

- 非 `trial entry`
- `trade_direction == long`
- `signal_type_1h == flip_bullish`

| 参数 | 当前值 |
| --- | --- |
| `enable_flip_bullish_cvd_context_filter` | `true` |
| `flip_bullish_max_cvd_upper_wick_ratio` | `0.20` |
| `flip_bullish_min_cvd_1h_delta_ratio` | `0.03` |

解释：

- `V10` 没有放宽 `flip_bullish`
- 也没有放开 weak-loss shrink
- 它只是把 `V8/A` 的盈利骨架，叠加到已验证有效的双时段风险去杠杆上

### 2.3 新增的 V10 session 风控

这是 `V10` 相对 `V8/A` 的唯一实质新增结构：

```json
"session_risk_control": {
  "enabled": true,
  "high_risk_sessions": [
    { "utc_start": "03:00", "utc_end": "05:30", "position_scale": 0.70 },
    { "utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65 }
  ],
  "apply_to_states": ["short_dual_pressure", "flip_bullish"]
}
```

实盘含义：

- 亚洲薄流动性段 `03:00~05:30 UTC`：相关 setup 仓位降到 `70%`
- 美股盘前 `14:30~16:00 UTC`：相关 setup 仓位降到 `65%`
- 只作用于已知高风险状态，不对全策略做普遍缩仓

### 2.4 4H shrink exit

| 参数 | 当前值 |
| --- | --- |
| `enable_4h_shrink_exit` | `true` |
| `exit_4h_shrink_bars` | `2` |
| `exit_4h_min_shrink_pct` | `0.20` |
| `exit_4h_require_profit` | `true` |

这点保持 `V8/A` 不变。  
`V10` 不接受“弱亏也提前走”的版本分支，避免重演上一轮回撤恶化。

### 2.5 关闭的旧过滤器

| 参数 | 当前值 |
| --- | --- |
| `short_quality_filter.enabled` | `false` |

---

## 三、止损与执行层风控

这里仍然分成两层。

### 3.1 策略层建议止损

来自 `macd_mtf_strategy_v2.stop_loss_config`：

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `use_dynamic_stop` | `true` | 使用策略输出止损 |
| `boll_stop_atr_multiplier` | `0.5` | 以 1H ATR 动态推导止损 |
| `max_stop_loss_pct` | `0.025` | 策略层建议止损上限 2.5% |
| `vwap_alert_deviation` | `0.005` | VWAP 偏离预警 |
| `enable_4h_shrink_exit` | `true` | 4H 动能收缩提前离场 |

### 3.2 执行层实际风控

来自外层执行/回测配置：

| 参数 | 当前值 |
| --- | --- |
| `stop_loss_pct` | `0.004` |
| `take_profit_pct` | `0.0` |
| `breakeven_enabled` | `true` |
| `breakeven_trigger_pnl_ratio` | `0.003` |
| `breakeven_lock_ratio` | `0.001` |
| `default_target_portion` | `0.60` |
| `max_symbol_position_portion` | `0.60` |
| `reserve_pct` | `0.20` |
| `max_positions` | `3` |
| `min_leverage / default_leverage / max_leverage` | `2 / 3 / 4` |

实盘含义：

- 固定止盈仍关闭
- 收益保护主要靠 `breakeven + 4H shrink exit + session 降仓`
- 执行层基础止损仍为 `0.4%`
- `session_risk_control` 影响的是开仓尺寸，不是扩大止损容忍

### 3.3 连亏冷却

| 参数 | 当前值 |
| --- | --- |
| `max_consecutive_losses` | `2` |
| `consecutive_loss_cooldown_seconds` | `1800` |
| `max_daily_loss_percent` | `5` |
| `daily_loss_cooldown_seconds` | `28800` |

`V10` 继续保留 `30min` 连亏冷却，不回退到 `90min`。

---

## 四、全样本正式回测

### 4.1 V10 对照 V8/A

| 版本 | Return | PF | MDD | Win Rate | Trades |
| --- | --- | --- | --- | --- | --- |
| V8/A | `+92.38%` | `2.74` | `10.69%` | `71.43%` | `511` |
| V10 (`V9.2A`) | `+99.39%` | `3.04` | `10.10%` | `70.88%` | `498` |

关键变化：

- Return：`+7.01pp`
- PF：`+0.31`
- MDD：`-0.59pp`
- Trades：`-13`

### 4.2 正式结果文件

| 版本 | 摘要文件 |
| --- | --- |
| V8/A | `output/backtest/v2_summary_20260321_184125.json` |
| V10 | `output/backtest/v2_summary_20260321_212230.json` |

### 4.3 V10 的 signal breakdown

`V10` 全样本下：

| Signal | Count | Win Rate | PnL |
| --- | --- | --- | --- |
| `flip_bearish` | `76` | `86.84%` | `+1723.92` |
| `flip_bullish` | `48` | `70.83%` | `+2458.99` |
| `green_bar_growing` | `226` | `66.81%` | `+1926.88` |
| `red_bar_growing` | `148` | `68.92%` | `+5275.84` |

### 4.4 最大回撤窗口

`V10` 最大回撤区间：

- start: `2026-03-01 03:15:00`
- trough: `2026-03-04 17:15:00`
- recovery: `2026-03-06 12:00:00`
- max drawdown: `10.10%`

与 `V8/A` 对比：

- 两版发生在同一段 stress window
- `V10` 没有靠“换行情”获胜
- `V10` 是在同一段坏行情里把回撤压浅，并将恢复时间提前 `2.25h`

---

## 五、为什么可以从 Candidate 提升到 Live

本次提升不是只看收益更高，而是同时满足了三点：

1. `V9.2A` 相对 `V8/A`，收益、PF、MDD 三项同时更优  
2. 归因结果可解释，改善集中在目标 loss pocket：`short_dual_pressure + 高风险 session`  
3. 负向副作用已经定位，而不是随机漂移

对应归因文档结论：

- `V9.2A` 先前被定义为 `Accept as Candidate`
- 现在升级为 `V10`，不是因为“再跑出一份更漂亮数字”
- 而是因为已有全样本表现和按币种/按回撤区间复核，足够支持 live 切换

---

## 六、实盘观察项

虽然 `V10` 已部署 live，但观察重点不能省。

### 6.1 重点 watchlist 币种

根据归因复核，优先盯：

- `LINKUSDT`
- `ONDOUSDT`
- `LTCUSDT`
- `MORPHOUSDT`
- `TRUMPUSDT`

原因：

- 这些币在 `V9.2A` 相对 `V8/A` 的 symbol delta 里仍有明确回吐
- 如果实盘也复现同样特征，优先考虑做 symbol 级节流，而不是先动策略骨架

### 6.2 重点 watchlist 时段

- `03:00~05:30 UTC`
- `14:30~16:00 UTC`

需要确认：

- session 降仓是否确实减少 cluster stop-outs
- 降仓后是否仍能保留 `red_bar_growing / flip_bearish` 主盈利能力

---

## 七、执行状态

已完成：

- `V9.2A` 已写入基础 live 配置
- 当前正式实盘版本定义为 `V10`
- `V10` 保留 `V8/A` 止损与 entry/exit 骨架
- `V10` 新增双时段 `session_risk_control`
- 专家组配套归因材料保留为 `docs/MACD_MTF_Strategy_V9_2A_Attribution_Review.md`

当前实盘配置文件：

- `config/trading_config_fund_flow.json`

相关参考文件：

- `config/candidates/trading_config_fund_flow_v9_2a_candidate.json`
- `docs/MACD_MTF_Strategy_V9_2A_Attribution_Review.md`
- `output/backtest/v2_summary_20260321_212230.json`
- `output/backtest/v2_summary_20260321_184125.json`

---

*文档版本：V10 live rollout / 更新日期：2026-03-21*
