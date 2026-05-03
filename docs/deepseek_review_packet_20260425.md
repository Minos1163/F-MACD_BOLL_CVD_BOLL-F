# DeepSeek 评审包: 30 天回测归因与当前实盘开仓/风控链路

- 生成日期: `2026-04-25`
- 目标: 给 DeepSeek 做一次针对 `fund_flow bot / macd_mtf_strategy_v2` 的结构化评审
- 代码/配置基线:
  - `config/trading_config_fund_flow.json`
  - `src/fund_flow/decision_engine.py`
  - `src/fund_flow/macd_strategy_v2.py`
  - `src/app/fund_flow_bot.py`
- 既有参考文档:
  - `docs/strategy_diagnostic_20260325.md`
  - `docs/open_entry_logic_chain_audit_20260325.md`
  - `reports/2026-03-22_strategy_optimization_backtest_followup.md`
  - `reports/2026-03-22_threshold_compare_backtest.md`

---

## 1. 范围说明

这份文档分清三件事，避免把不同口径混在一起：

1. `30 天归因`
   - 主归因窗口以 `2026-02-23 ~ 2026-03-24` 为准，来自 `docs/strategy_diagnostic_20260325.md`
2. `参数敏感性补充`
   - `2026-02-22 ~ 2026-03-21` 的阈值/配置 profile 对比，来自 `reports/2026-03-22_*.md`
3. `当前实盘代码链路`
   - 以当前仓库里的 `config + code` 为准，不把历史 profile 当成默认 live 行为

关键结论先写在前面：

- `v2（策略级，无外层链）` 有明显 alpha，30 天收益 `+229.06%`
- `bot-like（含外层链）` 收益只有 `+36.15%`
- 主要问题不是“信号天生差”，而是“执行结构错配”
- 当前 live 代码里，外层 `signal_pool / pretrade_risk_gate / ma10_macd_confluence / ai_review` 都是关闭的
- 当前实盘核心其实已经主要回到 `MACD V2 主策略 + 账户/持仓级风控`，DeepSeek 需要重点审的是:
  - V2 内部评分与阈值结构是否合理
  - 出场/保护链是否与 alpha 形态一致
  - 配置与代码是否存在口径漂移

---

## 2. 30 天回测归因

### 2.1 主对比结果

数据窗口: `2026-02-23 ~ 2026-03-24`

| 版本 | 收益率 | 胜率 | PF | 最大回撤 | 交易数 |
|---|---:|---:|---:|---:|---:|
| `v2（策略级，无外层链）` | `+229.06%` | `78.49%` | `4.19` | `12.01%` | `265` |
| `bot-like（含外层链）` | `+36.15%` | `61.87%` | `1.33` | `24.54%` | `278` |

结论:

- 收益差距约 `6.3x`
- `bot-like` 不仅收益低，回撤还更大
- 这不是“少交易更稳”，而是“结构更差”

### 2.2 退出机制归因

| 退出方式 | bot-like 次数 | bot-like PnL | v2 次数 | v2 PnL |
|---|---:|---:|---:|---:|
| `stop_loss` | `93` | `-11,322` | `216` | `-4,100` |
| `take_profit_intrabar` | `145` | `+17,112` | `0` | `-` |
| `4h_shrink_exit` | `15` | `+289` | `39` | `+26,519` |
| 信号反转退出 | `0` | `-` | `8` | `-224` |

归因判断:

1. `4h_shrink_exit` 是 v2 的主 alpha 兑现器
   - `39` 笔贡献 `+26,519 PnL`
2. bot-like 用固定小止盈把趋势单提前截断
   - `145` 笔固定 TP 虽然赚钱，但总盈利质量远弱于趋势退出
3. bot-like 的止损更少，但单次更伤
   - 这是典型的“大亏小赚”结构

### 2.3 单笔结构归因

| 指标 | bot-like | v2 |
|---|---:|---:|
| 平均盈利单笔 PnL | `+103.16` | `+152.24` |
| 平均亏损单笔 PnL | `-126.06` | `-132.52` |
| 盈亏比 R | `0.82` | `1.15` |
| 平均仓位规模 | `2437.55` | `4063.60` |
| 平均单笔 PnL | `15.76` | `90.99` |

归因判断:

- bot-like 的 `R < 1`
- bot-like 的平均仓位比 v2 小约 `40%`
- 说明外层链不只是没改善质量，还压缩了有效风险暴露

### 2.4 信号类型退化归因

| 信号类型 | bot-like 胜率 | bot-like PnL | v2 胜率 | v2 PnL |
|---|---:|---:|---:|---:|
| `flip_bearish` | `50.0%` | `-739` | `100.0%` | `+3,081` |
| `red_bar_shrinking` | `45.5%` | `-206` | `81.8%` | `+3,697` |
| `green_bar_shrinking` | `63.6%` | `+564` | `95.7%` | `+4,804` |
| `green_bar_growing` | `63.4%` | `+1,115` | `80.8%` | `+4,604` |
| `red_bar_growing` | `67.0%` | `+3,393` | `70.8%` | `+7,024` |
| `flip_bullish` | `53.3%` | `+255` | `81.8%` | `+900` |

归因判断:

- `flip_bearish` 在策略级是优质信号，在 bot-like 退化成亏损信号
- `shrinking` 系列同样明显退化
- 这更像“执行链把高质量信号做坏了”，而不是“信号本身没有 edge”

### 2.5 参数敏感性补充

补充窗口: `2026-02-22 ~ 2026-03-21`

1. 阈值对比

| 主阈值 | Return | Trades | Win Rate | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| `0.75` | `76.96%` | `404` | `68.32%` | `3.48` | `8.98%` |
| `0.80` | `70.24%` | `397` | `68.26%` | `3.15` | `8.80%` |
| `0.85` | `84.68%` | `326` | `71.78%` | `4.08` | `8.81%` |

结论:

- 这组样本里，`0.85` 优于 `0.80` 和 `0.75`
- 当前主阈值没有证据需要简单下调

2. profile 对比

| Variant | Return | Trades | PF | Max DD |
|---|---:|---:|---:|---:|
| Baseline | `84.68%` | `326` | `4.08` | `8.81%` |
| `VWAP Score Tiers` | `82.90%` | `326` | `4.23` | `7.55%` |
| `Structural Candidate` | `69.11%` | `279` | `3.68` | `8.67%` |
| `Structural + VWAP Tiers` | `70.67%` | `279` | `4.01` | `7.38%` |

结论:

- `VWAP Score Tiers` 更像风险质量优化，不像 alpha 增强
- `strict 1H + 4H enhancement + 放开部分禁用信号` 这组结构改动，在该样本里明显不优

---

## 3. 当前实盘配置快照

配置来源: `config/trading_config_fund_flow.json`

### 3.1 当前策略模式

- `fund_flow.strategy_mode = macd_mtf_strategy_v2`
- `fund_flow.default_target_portion = 0.60`
- `fund_flow.max_symbol_position_portion = 0.60`
- `fund_flow.max_active_symbols = 3`
- `fund_flow.stop_loss_pct = 0.005`
- `fund_flow.take_profit_pct = 0.0`
- `fund_flow.breakeven_enabled = true`
- `fund_flow.breakeven_trigger_pnl_ratio = 0.008`
- `fund_flow.breakeven_lock_ratio = 0.002`

### 3.2 当前外层门控开关

这些是“当前 live 主配置”，不是历史 baseline：

| 模块 | 当前状态 | 说明 |
|---|---|---|
| `signal_pool` | `disabled` | 不在当前 live 开仓漏斗里起硬过滤作用 |
| `pretrade_risk_gate` | `disabled` | 外层风险门现在旁路 |
| `ma10_macd_confluence` | `disabled` | 5m MA10/MACD 共振不做当前 live 硬门 |
| `ai_review` | `disabled` | 不做当前 live AI 终审 |
| `major_symbol_signal_pool` | `enabled` | 但这是 pool 配置资源，不等于当前 base `signal_pool` 已启用 |

直接结论:

- 当前 live 不是“全外层链开启”
- 当前 live 主开仓逻辑主要由 `MACD V2 内部链路` 决定
- 外层仍然保留的，主要是:
  - 时间窗过滤
  - regime side block
  - 账户级熔断
  - 保护单完整性约束
  - 极端波动冷却
  - 持仓保护收紧

### 3.3 当前评分权重

`fund_flow.macd_mtf_strategy_v2.scoring_weights`

| 评分项 | 权重 |
|---|---:|
| `weight_1h_direction` | `0.00` |
| `weight_4h_direction` | `0.55` |
| `weight_4h_enhancement` | `0.10` |
| `weight_vwap` | `0.20` |
| `weight_15m_entry` | `0.05` |
| `weight_volume` | `0.20` |

备注:

- 当前实际运行权重以 `decision_engine.py` 装载值为准
- `decision_engine.py` 里的注释文本和当前实际权重口径并不完全一致，评审时应以配置和装载代码为准，不要以旧注释为准

### 3.4 当前阈值

`fund_flow.macd_mtf_strategy_v2.entry_thresholds`

| 阈值项 | 值 |
|---|---:|
| `default` | `0.820` |
| `min_entry_score` | `0.25` |
| `min_signal_score` | `0.850` |
| `stable_bear_continuation_min_signal_score` | `0.820` |
| `stable_bull_continuation_min_signal_score` | `0.820` |
| `red_bar_growing` | `0.820` |
| `flip_bearish` | `0.810` |
| `flip_bullish` | `0.810` |

### 3.5 当前关键入场过滤参数

`fund_flow.macd_mtf_strategy_v2.entry_filters`

| 参数 | 值 |
|---|---:|
| `primary_direction_timeframe` | `4h` |
| `require_1h_confirmation_when_4h_primary` | `true` |
| `allow_neutral_1h_confirmation` | `true` |
| `light_1h_confirmation_when_4h_primary` | `true` |
| `enable_soft_15m_confirmation_when_4h_primary` | `true` |
| `soft_15m_entry_score` | `0.28` |
| `soft_15m_neutral_hist_multiple` | `3.0` |
| `soft_15m_max_adverse_hist_multiple` | `8.0` |
| `enable_4h_preflip_trial_entries` | `true` |
| `preflip_trial_min_shrink_pct_long` | `0.60` |
| `preflip_trial_min_shrink_pct_short` | `0.30` |
| `preflip_trial_min_signal_score` | `0.75` |
| `preflip_trial_min_vwap_score` | `0.06` |
| `preflip_trial_entry_scale` | `0.35` |
| `preflip_trial_max_leverage` | `2` |
| `enable_trial_short_below_structure_continuation_promotion` | `true` |
| `trial_short_below_structure_promotion_min_signal_score` | `0.79` |
| `trial_short_below_structure_promotion_min_vwap_score` | `0.075` |
| `trial_short_below_structure_promotion_min_adx_1h` | `30.0` |
| `trial_short_below_structure_promotion_min_4h_shrink_pct` | `0.80` |
| `trial_short_below_structure_promotion_min_4h_shrink_bars` | `6` |
| `enable_stable_bear_continuation` | `true` |
| `stable_bear_continuation_min_vwap_score` | `0.10` |
| `stable_bear_continuation_min_adx_1h` | `30.0` |
| `stable_bear_continuation_min_4h_bars` | `2` |
| `enable_stable_bull_continuation` | `false` |
| `flip_bullish_min_vwap_score` | `0.12` |
| `flip_bullish_require_pullback_bounce` | `true` |
| `flip_bullish_require_15m_growing` | `true` |
| `flip_bearish_min_adx_1h` | `30.0` |
| `flip_bearish_retest_reject_min_vwap_score` | `0.25` |
| `flip_bearish_max_bb_middle_slope_1h` | `0.0` |
| `flip_bearish_max_bb_middle_slope_4h` | `0.0005` |
| `disable_green_bar_shrinking_short_dual_pressure_entries` | `true` |
| `disable_red_bar_shrinking_long_dual_support_entries` | `true` |
| `min_vwap_score_for_entry` | `0.10` |

---

## 4. 当前实盘开仓链路

下面按真实代码路径写，不按历史文档假设。

### 4.1 决策入口

入口函数:

- `src/fund_flow/decision_engine.py:3391` `_decide_macd_v2_strategy`

主链路:

1. 读取 `15m / 1h / 4h` 多周期数据
2. 时间窗过滤
3. 调用 `macd_v2_engine.analyze(...)`
4. 构造 metadata
5. 叠加 `4h regime state`
6. 根据信号方向生成 `BUY / SELL / CLOSE / HOLD`
7. 之后再经过 bot 外层统一入口处理

### 4.2 第一层: 时间窗和数据完整性

如果下列任一条件不满足，直接 `HOLD`:

1. 缺少 `15m/1h/4h` 任一周期数据
2. `time_window_filter.should_allow_entry(...)` 返回 false

这一步是 live 第一层硬门。

### 4.3 第二层: V2 内部评分链

核心分析函数:

- `src/fund_flow/macd_strategy_v2.py:1920` `analyze`

它做的不是单一信号，而是一个串行漏斗:

1. `4h` 主方向识别
2. `1h` 信号类型识别
3. `15m` 入场时机软确认
4. `VWAP` 价值位置评分
5. `BOLL` 结构过滤与趋势状态
6. `ADX / slope / CVD / volume` 等附加过滤
7. 连续趋势 / 试探单 / 试探单升级逻辑
8. 最终阈值判定
9. 动态止损计算

### 4.4 评分构成

当前总分可理解为:

`4h主方向 + 4h增强 + VWAP + 15m入场 + volume - 过热惩罚`

其中:

- `4h` 是主评分核心，占 `55%`
- `VWAP + volume` 合计占 `40%`
- `15m` 只占 `5%`，当前是软确认
- `1h_direction` 权重当前为 `0.00`

这意味着当前 live 的结构本质是:

- `4h` 决定主方向
- `1h` 更像信号类型/过滤层
- `15m` 更像 timing refine

### 4.5 阈值决策逻辑

阈值解析函数:

- `src/fund_flow/macd_strategy_v2.py:210` `resolve_signal_score_threshold`

规则:

1. 若判定为 `stable_continuation short/long`，优先用 continuation 阈值
2. 否则按 `signal_type_1h` 取专属阈值:
   - `red_bar_growing -> 0.82`
   - `flip_bearish -> 0.81`
   - `flip_bullish -> 0.81`
3. 若无专属阈值，回退到 `min_signal_score = 0.85`
4. 若是 `trial entry`，阈值强制改为 `preflip_trial_min_signal_score = 0.75`

### 4.6 连续趋势与试探单逻辑

#### A. stable bear continuation

函数:

- `src/fund_flow/macd_strategy_v2.py:819` `_evaluate_stable_continuation`

短侧连续趋势激活条件:

1. `primary_mode == 4h`
2. `trade_direction == short`
3. 不是 `trial entry`
4. `enable_stable_bear_continuation = true`
5. `4h` 负 hist 持续 bars `>= 2`
6. `1h signal_type` 在 `{flip_bearish, green_bar_growing}`
7. `15m entry_type` 为 `green_bar_growing`
8. `adx_1h >= 30`
9. `vwap_score >= 0.10`
10. `vwap_state` 在:
   - `short_dual_pressure`
   - `short_retest_reject`
   - `short_below_session_above_structure`

#### B. 4h preflip trial entry

trial 相关关键门槛:

- `preflip_trial_min_shrink_pct_long = 0.60`
- `preflip_trial_min_shrink_pct_short = 0.30`
- `preflip_trial_min_signal_score = 0.75`
- `preflip_trial_min_vwap_score = 0.06`
- `preflip_trial_entry_scale = 0.35`
- `preflip_trial_max_leverage = 2`

含义:

- 试探单是低杠杆、低仓位版本，不是完整主仓位

#### C. 试探空单升级为连续趋势

函数:

- `src/fund_flow/macd_strategy_v2.py:910`

激活条件:

1. 当前是 `trial entry`
2. `primary_mode == 4h`
3. 交易方向为 `short`
4. `1h signal_type == green_bar_growing`
5. `15m entry_type` 在 `{flip_bearish, green_bar_growing}`
6. `vwap_state == short_below_session_above_structure`
7. `signal_score >= 0.79`
8. `vwap_score >= 0.075`
9. `adx_1h >= 30`
10. `4h_shrink_pct >= 0.80`
11. `4h_shrink_bars >= 6`

含义:

- 这是把“弱确认试探空”提升为“可按连续趋势处理的短侧机会”

### 4.7 VWAP 位置评分

函数:

- `src/fund_flow/macd_strategy_v2.py:1384` `calculate_vwap_score`

当前 VWAP 结构不是简单阈值，而是“状态 + 连续分数”：

短侧状态示例:

- `short_retest_reject`
- `short_dual_pressure`
- `short_below_session_above_structure`
- `short_above_both`

长侧状态示例:

- `long_reclaim_confirmed`
- `long_dual_support`
- `long_above_session_below_structure`
- `long_below_both`

硬否决:

- 若沿交易方向偏离 `VWAP` 超过 `3%`，触发 `VWAP_HARD_BLOCK`

当前配置:

- `vwap_deviation_optimal = 0.5%`
- `vwap_deviation_warning = 1.5%`
- `vwap_deviation_hard_block = 3.0%`
- `vwap_retest_tolerance = 0.3%`

### 4.8 动态止损逻辑

函数:

- `src/fund_flow/macd_strategy_v2.py:1852` `calculate_dynamic_stop`

多头:

1. 若 `close_1h >= bb_middle_1h`
   - `stop = bb_middle_1h - atr_1h * 0.5`
2. 否则若 `bb_lower_1h > 0`
   - `stop = bb_lower_1h - atr_1h * 0.2`
3. 否则
   - `stop = entry_price * (1 - 0.025)`
4. 最终再套一层最大止损保护:
   - `stop >= entry_price * (1 - 0.025)`

空头对称:

1. 若 `close_1h <= bb_middle_1h`
   - `stop = bb_middle_1h + atr_1h * 0.5`
2. 否则若 `bb_upper_1h > 0`
   - `stop = bb_upper_1h + atr_1h * 0.2`
3. 否则
   - `stop = entry_price * (1 + 0.025)`
4. 最终再套最大止损保护:
   - `stop <= entry_price * (1 + 0.025)`

补充:

- 还会生成 `vwap_alert_price`
- 当前 `max_stop_loss_pct = 0.025`

### 4.9 4H shrink exit 逻辑

函数:

- `src/fund_flow/macd_strategy_v2.py:996` `resolve_4h_shrink_exit_policy`
- `src/fund_flow/decision_engine.py:3651`

默认模式:

- `exit_4h_shrink_bars = 2`
- `exit_4h_min_shrink_pct = 0.20`
- `exit_4h_require_profit = true`

若持仓被标记为 `stable_continuation_active`:

- `stable_continuation_exit_4h_shrink_bars = 3`
- `stable_continuation_exit_4h_min_shrink_pct = 0.35`

含义:

- 普通单: 4h 缩量达到 `2 bars + 20%` 且有盈利时退出
- 连续趋势单: 退出更慢，要求 `3 bars + 35%`
- 这是当前 live 最关键的趋势盈利保留器

### 4.10 regime block 和反向平仓

在 `decision_engine.py` 里，V2 signal 生成后还会叠加 `4h regime state`：

1. 若 regime 只允许单边，反向开仓直接 `HOLD`
2. 若当前有反向持仓，会优先 `CLOSE`
3. 若无明确信号但 regime 反转，也可能触发 `regime_reverse_close`

这一步是 live 链路里的第二个硬结构层。

---

## 5. 当前详细门槛分数与权重评分

### 5.1 需要 DeepSeek 直接看的评分结构

当前真正决定是否开仓的，不是单个参数，而是以下组合：

1. `4h 主评分 0.55`
2. `4h 增强评分 0.10`
3. `VWAP 评分 0.20`
4. `15m timing 评分 0.05`
5. `volume 评分 0.20`
6. `信号类型阈值`
7. `VWAP 最低分`
8. `ADX / slope / state / trial / continuation` 条件

### 5.2 当前最重要的分数门槛

| 场景 | 门槛 |
|---|---:|
| 通用主阈值 | `0.85` |
| `red_bar_growing` | `0.82` |
| `flip_bearish` | `0.81` |
| `flip_bullish` | `0.81` |
| `trial entry` | `0.75` |
| `stable_bear_continuation` | `0.82` |
| 全局最小 `entry_score_15m` | `0.25` |
| `soft_15m_entry_score` | `0.28` |
| 全局 `min_vwap_score_for_entry` | `0.10` |

### 5.3 当前疑似“应重点复核”的评分点

1. `weight_1h_direction = 0.00`
   - 现在 1h 不参与显式加分，只参与过滤/类型判断
2. `weight_4h_direction = 0.55`
   - 4h 权重非常重
3. `weight_4h_enhancement = 0.10`
   - 已启用，不再是零
4. `flip_*` 阈值比通用阈值更低
   - `0.81 < 0.85`
5. `trial entry` 阈值更低，但靠低杠杆和低仓位约束
6. `stable_bear_continuation` 当前是开启的，而 `stable_bull_continuation` 关闭

---

## 6. 当前仓位管理

### 6.1 基础仓位参数

| 参数 | 当前值 |
|---|---:|
| `default_target_portion` | `0.60` |
| `max_symbol_position_portion` | `0.60` |
| `max_active_symbols` | `3` |
| `min_open_portion` | `0.06` |
| `max_open_portion` | `1.00` |

### 6.2 杠杆梯度

真实使用函数:

- `src/fund_flow/macd_strategy_v2.py:3185` `calculate_leverage`

实际代码梯度:

| signal_score | leverage |
|---|---:|
| `>= 0.90` | `4x` |
| `>= 0.85` | `3x` |
| `>= 0.75` | `2x` |
| `< 0.75` | `0` |

后续再叠加 3 个上限:

1. 强趋势降杠杆
   - `ema_multiplier >= 1.2` 时乘 `0.8`
2. `trial entry`
   - `max_leverage = 2`
3. watchlist symbol
   - 若启用 watchlist throttle，则再 cap

### 6.3 仓位比例梯度

真实使用函数:

- `src/fund_flow/macd_strategy_v2.py:3242` `calculate_position_portion`

分数乘数:

| signal_score | portion multiplier |
|---|---:|
| `>= 0.90` | `1.2` |
| `>= 0.85` | `1.0` |
| `>= 0.75` | `0.8` |
| `< 0.75` | `0.0` |

计算顺序:

1. 从 `base_default_portion` 起算
2. 若 `vwap_state == short_dual_pressure`
   - 额外加 `dual_pressure_target_portion_bonus = 0.08`
   - 且单币种上限可抬到 `0.68`
3. 乘以分数仓位梯度
4. 再乘 `VWAP position multiplier`
   - 当前 base config 未启用该 tier 配置
5. 若是 `trial entry`
   - 再乘 `entry_scale = 0.35`
6. 再乘 `session_scale`
7. 若 watchlist throttle 启用
   - 再受 watchlist cap 和 session double-scale 影响

### 6.4 当前会话风险缩放

函数:

- `src/fund_flow/macd_strategy_v2.py:497` `resolve_session_position_scale`

当前高风险时段:

| UTC 时间段 | `position_scale` |
|---|---:|
| `03:00 ~ 05:30` | `0.70` |
| `14:30 ~ 16:00` | `0.65` |

只应用于:

- `short_dual_pressure`
- `flip_bullish`

### 6.5 当前 watchlist / VWAP tier 是否启用

当前 base 配置中:

- `symbol_risk_tiers` 未在主配置里直接启用
- `vwap_score_position_tiers` 未在主配置里直接启用

它们存在于 `backtest.profile` 的候选 profile 里，例如:

- `macd_v2_v11_watchlist_throttle`
- `macd_v2_v11_watchlist_session_only`
- `macd_v2_v11_vwap_score_tiers`

所以当前 live 主链里，不应假设 watchlist throttle 和 VWAP tier 一定在生效，除非运行时明确应用了这些 profile 覆盖。

---

## 7. 当前详细风控逻辑

### 7.1 账户级熔断

`risk`

| 参数 | 当前值 |
|---|---:|
| `account_circuit_enabled` | `true` |
| `max_daily_loss_percent` | `5` |
| `max_consecutive_losses` | `2` |
| `daily_loss_cooldown_seconds` | `28800` |
| `consecutive_loss_cooldown_seconds` | `1800` |

含义:

- 日内亏损达到 `5%` 触发冷却 `8h`
- 连续亏损 `2` 次触发冷却 `30min`

### 7.2 基础出场结构

`fund_flow`

| 参数 | 当前值 |
|---|---:|
| `stop_loss_pct` | `0.005` |
| `take_profit_pct` | `0.0` |
| `breakeven_enabled` | `true` |
| `breakeven_trigger_pnl_ratio` | `0.008` |
| `breakeven_lock_ratio` | `0.002` |

含义:

- 当前主结构已经不再是固定小 TP
- 这与 30 天归因里“恢复趋势退出”方向是一致的

### 7.3 保护单 SLA

`fund_flow`

| 参数 | 当前值 |
|---|---:|
| `protection_sla_enabled` | `true` |
| `protection_sla_seconds` | `45` |
| `protection_sla_force_flatten` | `true` |

含义:

- 若保护单缺失且超时，系统可强制平仓
- 这是一条 live 安全边界，不是 alpha 逻辑

### 7.4 极端波动冷却

`fund_flow`

| 参数 | 当前值 |
|---|---:|
| `extreme_volatility_cooldown_enabled` | `true` |
| `timeframe` | `5m` |
| `atr_pct_threshold` | `0.02` |
| `consecutive_bars` | `2` |
| `cooldown_seconds` | `1800` |

逻辑位置:

- `src/app/fund_flow_bot.py:2693`

含义:

- 若 `5m atr_pct >= 2%` 连续 `2` 根，触发 `30min` 冷却

### 7.5 冲突保护与止损收紧

主要函数:

- `src/app/fund_flow_bot.py:5199` `_tighten_protection_for_conflict`

关键参数:

| 参数 | 当前值 |
|---|---:|
| `cooldown_sec` | `180` |
| `tighten_min_atr_multiple` | `2.2` |
| `light_confirm_bars` | `2` |
| `hard_confirm_bars` | `5` |
| `light_tighten_min_hold_seconds` | `600` |
| `light_tighten_min_mfe` | `0.0025` |
| `light_take_profit_enabled` | `true` |
| `light_take_profit_min_hold_seconds` | `180` |
| `light_take_profit_min_mfe` | `0.0025` |
| `light_take_profit_min_pnl` | `0.001` |
| `light_take_profit_pct` | `0.75` |
| `breakeven_fee_buffer` | `0.0008` |
| `breakeven_arm_buffer` | `0.0003` |
| `state_reduce_pct` | `0.35` |

逻辑含义:

1. 冲突保护会尝试“收紧 SL”而不是立刻砍掉全部仓位
2. 收紧后的 SL 仍需满足 ATR 最小距离保护
3. 可以进入 break-even 模式
4. 也可以触发轻量止盈
5. 同时有 cooldown，避免频繁撤改保护单

### 7.6 当前未启用但代码仍保留的外层风险门

#### A. pretrade_risk_gate

函数:

- `src/app/fund_flow_bot.py:2936`

当前状态:

- `enabled = false`

如果启用，它会综合:

- `trend_weight = 0.45`
- `momentum_weight = 0.30`
- `volatility_weight = 0.20`
- `drawdown_weight = 0.35`
- `entry_threshold = 0.06`
- `entry_threshold_capture = 0.05`
- `volatility_cap = 0.012`
- `volatility_cap_capture = 0.014`

并可执行:

- `BLOCK / HOLD / EXIT / AVOID`
- 缩仓
- 限制杠杆
- 强制部分平仓

#### B. MA10/MACD confluence

函数:

- `src/app/fund_flow_bot.py:2641`

当前状态:

- `enabled = false`
- `entry_hard_filter = false`

即:

- 当前 live 不会因为 5m MA10/MACD 共振不足而硬挡住 V2 开仓

#### C. AI final review

函数:

- `src/app/fund_flow_bot.py:8154`

当前状态:

- `ai_review.enabled = false`
- `flat_top_n = 3`

即:

- 当前 live 不会进入 AI 终审
- `flat_top_n = 3` 只是保留配置，不会在 disabled 状态下生效

### 7.7 保护单缺口导致禁止新开仓

函数:

- `src/app/fund_flow_bot.py:8154`

即使 AI review 关闭，当前 bot 仍会在下列情况下清空本轮新开仓候选:

1. 检测到现有持仓缺保护单
2. `block_new_entries_due_to_protection_gap = true`

这条逻辑非常重要，因为它是当前 live 的真实“硬阻断门”之一。

---

## 8. 需要 DeepSeek 重点审的疑点

### 8.1 配置与代码是否存在口径漂移

1. `leverage_config` 里写的是:
   - `score_0.75_plus = 5`
   - `score_0.60_plus = 4`
   - `score_0.50_plus = 3`
2. 但当前真实下单函数 `calculate_leverage()` 用的是硬编码:
   - `>=0.90 -> 4x`
   - `>=0.85 -> 3x`
   - `>=0.75 -> 2x`

这个差异说明:

- `leverage_config` 里的部分字段很可能是死配置，或者至少不是当前实际杠杆来源

### 8.2 注释与实际权重口径不一致

例如 `decision_engine.py` 顶部注释仍有旧版口径描述，但当前运行权重来自:

- `0.55 / 0.10 / 0.20 / 0.05 / 0.20`

需要 DeepSeek 判断:

- 是否应该把注释、配置、代码装载三者统一

### 8.3 当前是“短侧连续趋势开启，长侧关闭”

当前:

- `enable_stable_bear_continuation = true`
- `enable_stable_bull_continuation = false`

需要判断:

- 这是样本驱动后的合理非对称，还是潜在过拟合

### 8.4 4H 权重过重是否导致结构过于单边

当前 `4h_direction = 0.55`，且 `1h_direction = 0.00`

需要判断:

- 这是否让系统过度依赖 4h 主方向，而把 1h 仅退化为 veto/type 层

### 8.5 trial / continuation / promotion 是否过于复杂

当前链里同时存在:

1. `trial entry`
2. `stable continuation`
3. `trial short promotion`
4. `4h shrink exit slow mode`

需要判断:

- 这套结构是否真的在提升净值结构
- 还是在制造更多“隐式状态机复杂度”

### 8.6 当前 live 已关闭外层 gate，后续评审要避免误诊

当前:

- `signal_pool = false`
- `pretrade_risk_gate = false`
- `ma10_macd_confluence = false`
- `ai_review = false`

因此:

- 如果 DeepSeek 继续把当前实盘问题归因为“外层 gate 太多”，需要先区分“历史 30 天 bot-like 回放”与“当前 live 主配置”
- 当前更值得审的是 `V2 内部结构` 与 `持仓保护链`

---

## 9. 我给 DeepSeek 的建议评审题目

建议直接让 DeepSeek 围绕以下问题评：

1. 当前 `MACD V2` 的评分权重 `0.55/0.10/0.20/0.05/0.20` 是否结构合理，是否存在重复计分或漏计分
2. `trial entry -> promotion -> stable continuation -> slow shrink exit` 这套状态机是否必要，还是过于复杂
3. 当前 `flip_bearish / flip_bullish / red_bar_growing` 的差异化阈值是否合理
4. `4h_shrink_exit` 是否仍然是当前 alpha 兑现主来源，如果是，现有保护链是否会过早干扰它
5. `1h_direction = 0.00` 但保留大量 1h 过滤逻辑，这种结构是否一致
6. 当前 `leverage_config` 与 `calculate_leverage()` 的脱节，是否应清理或统一
7. 当前“短侧连续趋势开启、长侧关闭”的非对称性，是否只是样本内优化结果
8. 当前 `fund_flow.stop_loss_pct = 0.005`、`take_profit_pct = 0.0`、`breakeven_trigger = 0.008` 是否已经与 30 天归因方向对齐，是否还需进一步调整

---

## 10. 最终给你的简版结论

如果只保留三句话给 DeepSeek：

1. `30 天回测说明策略 alpha 在，主要问题在执行结构，而不是信号先天无效`
2. `当前 live 已经不是“全外层门都开着”的状态，主链其实是 MACD V2 内部评分 + 持仓保护链`
3. `最值得审的是：评分结构、状态机复杂度、4h shrink exit 保真度、以及配置/代码口径漂移`
