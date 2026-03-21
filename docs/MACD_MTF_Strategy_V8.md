# MACD_MTF_Strategy_V8

> 文档用途：将 A 方案固化为当前实盘基线，并汇总逻辑修正、止损结构与最新全样本回测结果，供专家组继续讨论。  
> 生效范围：基础配置 `fund_flow.macd_mtf_strategy_v2` 已切换到 V8 实盘参数。  
> 对照基线：`macd_v2_4h_preflip_trial_exit`

---

## 一、版本结论

V8 采用的是此前 A 方案，不再只存在于 backtest profile 中，而是已经写入基础策略配置。

核心结论：

- 保留 `4H pre-flip 试仓 + 4H shrink exit`
- 保留 `4H 主方向 + 1H light confirmation`
- 新增两条只打亏损 pocket 的过滤器
- 不启用旧的 `short_quality_filter`

这版的目标不是“重做结构”，而是在不破坏当前正收益骨架的前提下，精准切掉：

- `short green_bar_growing` 的高频止损 pocket
- `long flip_bullish` 的弱 CVD/上影线失真 pocket

---

## 二、当前实盘参数

### 2.1 方向与入场框架

当前基础配置已经切换为：

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

### 2.2 新增的 V8 定向过滤器

#### A1. short green_bar_growing ADX pocket 过滤

只针对：

- 非 `trial entry`
- `trade_direction == short`
- `signal_type_1h == green_bar_growing`

过滤条件：

| 参数 | 当前值 |
| --- | --- |
| `enable_green_bar_growing_short_adx_1h_range_filter` | `true` |
| `green_bar_growing_short_min_adx_1h` | `25.0` |
| `green_bar_growing_short_max_adx_1h` | `30.0` |

解释：

- 不禁用整个 `green_bar_growing short`
- 只拦 `1H ADX ∈ [25, 30)` 这个回测里最差的震荡 pocket

#### A2. long flip_bullish CVD context 过滤

只针对：

- 非 `trial entry`
- `trade_direction == long`
- `signal_type_1h == flip_bullish`

过滤条件：

| 参数 | 当前值 |
| --- | --- |
| `enable_flip_bullish_cvd_context_filter` | `true` |
| `flip_bullish_max_cvd_upper_wick_ratio` | `0.20` |
| `flip_bullish_min_cvd_1h_delta_ratio` | `0.03` |

解释：

- 当 `15M upper wick >= 0.20` 且 `1H CVD delta < 0.03` 时，直接否决
- 含义是：价格翻多，但上影线重且 1H 主动买盘确认不足，不做全尺寸翻多

### 2.3 4H 缩短离场

| 参数 | 当前值 |
| --- | --- |
| `enable_4h_shrink_exit` | `true` |
| `exit_4h_shrink_bars` | `2` |
| `exit_4h_min_shrink_pct` | `0.20` |
| `exit_4h_require_profit` | `true` |

这是当前策略降低回撤的核心正贡献模块，不建议关闭。

### 2.4 关闭的旧过滤器

| 参数 | 当前值 |
| --- | --- |
| `short_quality_filter.enabled` | `false` |

原因：

- 当前历史样本下，V8 的定向过滤器比旧的空头质量过滤器更精准
- 旧过滤器会引入额外误杀，且和当前 4H 主方向架构重叠度较高

---

## 三、止损与执行层风控

这里必须区分两层，不要混淆。

### 3.1 策略层建议止损

来自 `macd_mtf_strategy_v2.stop_loss_config`：

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `use_dynamic_stop` | `true` | 使用策略输出止损 |
| `boll_stop_atr_multiplier` | `0.5` | 以 1H ATR 动态推导止损 |
| `max_stop_loss_pct` | `0.025` | 策略层建议止损上限 2.5% |
| `vwap_alert_deviation` | `0.005` | VWAP 偏离预警 |

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

实盘含义：

- 固定止盈关闭，主要靠 `breakeven + 4H shrink exit` 完成收益保护
- 风险不是“放任大亏”，因为执行层有 `0.4%` 的基础止损约束
- `max_stop_loss_pct=2.5%` 是策略建议上限，不等于最终实盘裸暴露

---

## 四、逻辑 BUG 检查结果

### 4.1 已发现并修复的 BUG

#### Bug 1：新过滤器最初不会在 A 架构下生效

问题：

- 新增的两个定向过滤器，最初挂在 `strict_1h_filters_enabled` 分支下
- 但 A/V8 架构使用 `light_1h_confirmation_when_4h_primary = true`
- 在这个模式下，`strict_1h_filters_enabled = false`
- 结果就是过滤器被完全跳过

影响：

- profile A/B 第一次正式回测结果与基线完全一致
- 不是参数无效，而是代码路径根本没执行

修复：

- 将这两个过滤器从 `strict_1h_filters_enabled` 中解耦
- 改为：
  - 仍然只对非 `trial entry` 生效
  - 但在 `light confirmation` 模式下也照常执行

结论：

- 这是一个真实逻辑 bug，已修复
- 修复后 A/B 正式回测结果才出现分化

#### Bug 2：CVD/上影线上下文未完整接入新过滤器

问题：

- 新过滤器依赖 `cvd_upper_wick_ratio` 与 `cvd_1h_delta_ratio`
- 这些值最初没有完整传入策略引擎的所有调用链

修复：

- 已在 backtest 和 live decision path 中补齐传参

结论：

- 过滤器现在不是“空跑”
- 所有命中都基于真实上下文字段

### 4.2 复查后未发现的阻断级问题

当前复查后，没有再发现以下问题：

- trial entry 被新过滤器误伤
- 4H shrink exit 与新过滤器互相覆盖冲突
- base config 与 backtest loader / decision engine 配置不一致
- live decision path 与 backtest path 参数不一致

### 4.3 仍需持续观察的风险

1. `A` 过滤后交易数从 `498` 增到 `511`
说明过滤器不是简单“少做单”，而是通过减少 stop cluster 释放了资本占用，带来了额外交易机会。这是合理现象，但需要继续监控实盘是否稳定复现。

2. 当前最大回撤仍集中在 `2026-03-01 ~ 2026-03-04`
说明大亏 pocket 被削弱了，但回撤簇仍然存在“时间聚集”特征，后续仍建议做滚动窗口复核。

---

## 五、全样本正式回测对比

### 5.1 对比对象

| 版本 | 说明 |
| --- | --- |
| `macd_v2_4h_preflip_trial_exit` | 4H pre-flip + shrink exit 基线 |
| `macd_v2_4h_preflip_trial_exit_filter_a` | V8 候选 A |
| `macd_v2_4h_preflip_trial_exit_filter_b` | 更激进的 B |

### 5.2 结果总表

| 版本 | Return | PF | MDD | Win Rate | Trades |
| --- | --- | --- | --- | --- | --- |
| 基线 | `+76.90%` | `2.26` | `13.15%` | `69.08%` | `498` |
| A / V8 | `+92.38%` | `2.74` | `10.69%` | `71.43%` | `511` |
| B | `+73.29%` | `2.35` | `13.82%` | `69.88%` | `508` |

### 5.3 摘要文件

| 版本 | 摘要文件 |
| --- | --- |
| 基线 | `output/backtest/v2_summary_20260321_180637.json` |
| A / V8 | `output/backtest/v2_summary_20260321_184125.json` |
| B | `output/backtest/v2_summary_20260321_185222.json` |

### 5.4 解释

`A` 的表现是明确提升，不是边际波动：

- Return：`76.90% -> 92.38%`
- PF：`2.26 -> 2.74`
- MDD：`13.15% -> 10.69%`
- Win rate：`69.08% -> 71.43%`

`B` 说明“广谱切坏 pocket”不可行：

- 虽然 PF 略高于基线，但 return 掉了
- MDD 反而升到 `13.82%`
- 说明 B 已经开始误伤主盈利结构

结论：

- A 是有效的精准过滤
- B 是过度过滤

---

## 六、当前策略结构（给专家组的简版）

V8 当前结构可以概括为：

1. `4H MACD` 决定主方向
2. `1H` 只做同向轻确认，不再做满套 1H 严格否决
3. `15M` 负责时机入场
4. `VWAP + BOLL` 提供位置与结构过滤
5. `4H pre-flip` 允许提前小仓试错
6. `4H shrink exit` 负责利润保护与缩短离场
7. 新增两条定向 pocket filter 只打最主要亏损段

这不是一个推倒重来的版本，而是在已有正收益框架上做了“局部去毒”。

---

## 七、建议给专家组重点讨论的问题

1. `A` 是否直接作为新实盘基线，还是先做滚动窗口/分阶段 OOS 验证？
2. `short green_bar_growing` 的 ADX pocket 是否还要继续细分到 symbol bucket？
3. `long flip_bullish` 的 CVD 上下文过滤是否应该进一步加入 `bb_middle_slope_1h <= 0` 的二次确认？
4. `4H shrink exit` 是否要从“仅盈利时触发”扩展到“弱盈利 + 明显 shrink”也允许提前离场？
5. 当前回撤簇仍集中在少数日期，是否需要增加 session/time bucket 级别风控？

---

## 八、最终建议

当前建议是：

- **实盘基线切到 V8 / A**
- 保留 B 仅作为反例 profile，不进入实盘
- 下一轮专家讨论不要再泛化讨论“是否重做结构”，而应围绕：
  - A 是否足够稳
  - 是否需要再做一层时间段/币种级局部风控
  - shrink exit 是否还能再提前一点

---

*版本：V8 / 日期：2026-03-21*
