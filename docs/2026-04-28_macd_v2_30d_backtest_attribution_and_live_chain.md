# MACD V2 30天回测归因与实盘开仓链路审计

- 更新日期: `2026-04-29`
- 回测窗口: `2026-02-23 -> 2026-03-24T23:59:59`
- 回测命令:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --start 2026-02-23 --end 2026-03-24T23:59:59
```

- 最新工件:
  - `output/backtest/v2_summary_20260429_012003.json`
  - `output/backtest/v2_trades_20260429_012003.csv`
  - `output/backtest/v2_equity_curve_20260429_012003.csv`

## 1. 本轮结论

当前 HEAD 已经稳定脱离此前的 `0 笔交易` 塌缩态，也优于上一轮 `119 笔 / PF 3.48 / DD 10.20%` 的“修复但不精炼”状态。最新 30 天结果为:

| 指标 | 最新值 |
|---|---:|
| `total_trades` | `94` |
| `return_pct` | `+44.37%` |
| `win_rate_pct` | `87.23%` |
| `profit_factor` | `7.20` |
| `max_drawdown_pct` | `6.12%` |
| `signals_generated` | `766` |
| `candidate_entries` | `558` |
| `orders_submitted` | `224` |
| `orders_filled` | `94` |
| `orders_canceled` | `130` |
| `orders_filled / orders_submitted` | `41.96%` |

这轮结果已经满足:

- `total_trades` 维持在 `90-120`
- `win_rate_pct >= 80%`
- `profit_factor >= 4.0`
- `max_drawdown_pct <= 10.0%`

仍未满足的仅剩两项:

- `flip_bullish` 成交仅 `4` 笔，未达到 `>=10`
- `orders_filled / orders_submitted = 41.96%`，仍低于 `55%`

## 2. 回测结果归因

### 2.1 改善来自哪里

最新收益曲线改善，主要不是来自“更多交易”，而是来自“更干净的成交结构”:

| 信号族 | 笔数 | 胜率 | PnL |
|---|---:|---:|---:|
| `red_bar_growing` | `72` | `86.11%` | `+3187.85` |
| `flip_bearish` | `18` | `100.00%` | `+1555.09` |
| `flip_bullish` | `4` | `50.00%` | `-79.02` |

关键事实:

- 本轮没有任何成交的 `green_bar_growing`，因此上一轮对 PF 和回撤的主要拖累项已从成交结构里基本退出。
- 组合主收益来源已经转为 `red_bar_growing + flip_bearish`。
- `flip_bullish` 没有恢复为主引擎，它当前仍是薄弱环节，且最新窗口内为负收益。

### 2.2 漏斗已经恢复，但最后一公里仍然粗糙

最新执行漏斗为:

```text
signals_generated = 766
-> candidate_entries = 558
-> orders_submitted = 224
-> orders_filled = 94
```

这说明:

- 前端信号生成链路已经恢复，`analyze()` 不再静默。
- 候选生成能力充足，当前不再是“信号枯竭”问题。
- 当前瓶颈主要转移到:
  - `capacity_competition_dropped = 71`
  - `pending_cancel_reasons.ioc_no_fill = 130`

换言之，当前系统已经从“前端塌缩”阶段，进入“候选足够但成交转化仍不高”的阶段。

### 2.3 `flip_bullish` 的真实阻塞层

新增归因字段已经把 `flip_bullish` 的问题定位得很清楚:

| 归因字段 | 数值 |
|---|---:|
| `flip_bullish_seen` | `2652` |
| `flip_bullish_passed_threshold` | `6` |
| `flip_bullish_blocked_by_sniper` | `396` |
| `flip_bullish_blocked_by_cooling` | `0` |
| `flip_bullish_blocked_by_capacity` | `1` |
| `flip_bullish_ioc_canceled` | `1` |
| 实际成交 | `4` |

解读:

- `flip_bullish_seen -> passed_threshold` 的通过率只有 `0.23%`。
- `cooling` 不是当前主阻塞点，最新窗口里它没有挡掉任何一笔。
- `capacity` 和 `IOC` 也不是主阻塞点，分别只损失了 `1` 笔。
- 当前 `flip_bullish` 的真正问题在更上游:
  - 大量样本无法跨过总分阈值
  - 其中 `sniper` 仍挡掉了 `396` 次

因此，下一轮若继续追 `flip_bullish >= 10`，优先级应该是:

1. 审计 `sniper` 的 3 轴过滤和总分注入是否过于苛刻。
2. 审计 `flip_bullish` 在 RSI rhythm / spring bonus / sovereign path 中是否拿到足够分数。
3. 不是先去放宽 `cooling`，因为当前数据已经证明它并非主阻塞。

### 2.4 IOC 市价补单安全网本轮没有产生实际贡献

本轮已经把“标准 IOC -> 真市价补单”路径接入代码和回测近似，但最新 summary 显示:

| 字段 | 数值 |
|---|---:|
| `market_fallback_attempted` | `0` |
| `market_fallback_filled` | `0` |
| `market_fallback_slippage_blocked` | `0` |
| `market_fallback_disabled_by_policy` | `0` |

这说明:

- 代码路径已经接通。
- 但在 `2026-02-23` 到 `2026-03-24` 这一个窗口里，它没有实际参与成交。
- 当前 `94` 笔成绩不是 IOC safety net 带来的，而主要是信号漏斗恢复、阈值 profile 放松和成交结构优化带来的。

因此，不能把本轮结果误归因为“market fallback 已经显著提升了 fill ratio”。事实不是这样。

## 3. 当前实盘开仓链路

这里写的是当前代码真实链路，不是理想化设计。

### 3.1 策略信号生成

入口在 `src/fund_flow/macd_strategy_v2.py` 的 `analyze()` 主链。当前总分主干是:

```text
final_score
= score_4h_trend
+ score_1h
+ score_4h_enhancement
+ score_rsi_rhythm_weighted
+ score_vwap
+ score_volume
+ spring_override_score_bonus
+ rsi_launch_sovereign_score_bonus
+ other path-specific adjustments
```

核心层次:

1. `4H` 决定主方向与强弱。
2. `1H` 提供方向确认或健康度补分。
3. `RSI rhythm` 负责节奏、spring、neutral upgrade、conflict 处理。
4. `VWAP` 只保留轻权重与 `3%` 硬偏离否决。
5. `volume` 作为确认项而非主导项。

### 3.2 过滤与升级顺序

当前重要路径如下:

1. 先做 `VWAP hard block`、方向识别、RSI 节奏评分。
2. `flip_bullish` 仍保留:
   - `sniper`
   - `cooling`
   - 但 `strict_filter = false`
   - `cvd_context_filter = false`
3. `neutral_upgrade` 仍然开启:
   - `rsi >= 0.35` 可 full upgrade
   - `0.20 <= rsi < 0.35` 可 probe upgrade
4. `spring_override` 仍然开启:
   - 满足 spring 条件时给 bonus，并可降低局部阈值
5. `rsi_launch_sovereign_mode` 仍然开启:
   - 触发后可注入 bonus、改写阈值并强制 priority execution

### 3.3 决策引擎元数据

`src/fund_flow/decision_engine.py` 会把策略层细节统一写入 live/backtest 元数据，当前关键字段包括:

- `competition_score`
- `priority_execution_applied`
- `priority_execution_tier`
- `entry_market_fallback_enabled`
- `entry_market_fallback_timeout_ms`
- `entry_market_fallback_max_slippage_bps`
- `entry_execution_policy`
- `rsi_launch_sovereign_active`

这一步的意义是:

- 实盘和回测共享同一套执行路由语义。
- 后续归因时可以明确区分普通 IOC、priority execution、VIP、sovereign。

### 3.4 执行路由

`src/fund_flow/execution_router.py` 当前开仓路径分为三类:

1. 普通路径: `IOC`
2. 高分优先路径: `GTC + elastic_limit`
3. 主权/最高优先路径: `priority_execution_vip`

标准 IOC 的新增安全网规则是:

- 只有 `entry_execution_policy == "ioc_market_fallback"` 时才走这条路。
- 还必须同时满足:
  - 全局 `fund_flow.execution_degradation.open_market_fallback_enabled = true`
  - 本次 signal metadata 的 `entry_market_fallback_enabled = true`
  - 且 `disable_market_fallback != true`
- live 侧会先尝试 IOC，再在滑点保护范围内决定是否允许 `MARKET` 补单。

当前优先路径保持不变:

- `priority_exec_min_score = 0.90`
- `priority_exec_vip_min_score = 0.92`
- `VIP` 继续使用 `30s + retry`
- 本轮没有把 IOC 真市价补单混入 VIP / sovereign 路径

## 4. 当前真实权重与门槛

### 4.1 Base 默认权重

当前 base 默认权重是:

| 项 | 权重 |
|---|---:|
| `weight_4h_direction` | `0.40` |
| `weight_1h_direction` | `0.15` |
| `weight_4h_enhancement` | `0.10` |
| `weight_rsi_rhythm` | `0.30` |
| `weight_vwap` | `0.05` |
| `weight_15m_entry` | `0.00` |
| `weight_volume` | `0.10` |

结论很明确:

- `RSI rhythm` 已是主节奏层。
- `VWAP` 已被永久降级为轻权重。
- `15m` 不再有独立权重层，而是通过 RSI rhythm / spring / refine 并入。

### 4.2 Base 默认阈值

当前 base 默认阈值:

| 路径 | 阈值 |
|---|---:|
| `default` | `0.85` |
| `red_bar_growing` | `0.90` |
| `green_bar_growing` | `0.87` |
| `flip_bearish` | `0.84` |
| `flip_bullish` | `0.82` |
| `soft_long` | `0.85` |
| `stable_bear_continuation` | `0.85` |
| `stable_bull_continuation` | `0.85` |

### 4.3 本次回测实际生效的 profile 阈值

本轮不是直接用 base 跑的，而是使用 backtest 默认 profile `macd_v2_disable_short_filter`。该 profile 实际覆盖为:

| 路径 | 生效阈值 |
|---|---:|
| `default` | `0.68` |
| `soft_long` | `0.66` |
| `red_bar_growing` | `0.68` |
| `green_bar_growing` | `0.69` |
| `flip_bearish` | `0.66` |
| `flip_bullish` | `0.64` |
| `preflip_trial` | `0.66` |
| `trial_short_below_structure_promotion` | `0.68` |
| `stable_bear_continuation` | `0.68` |
| `stable_bull_continuation` | `0.68` |

同一个 profile 还放宽了:

- `min_vwap_score_for_entry = 0.0`
- `flip_bullish_min_vwap_score = 0.0`
- `stable_*_min_vwap_score = 0.0`
- `flip_bearish_retest_reject_min_vwap_score = 0.0`
- `volume_vwap_both_low_min_score_vol = 0.0`
- `volume_vwap_both_low_min_vwap_score = 0.0`
- `flip_bullish_cooling.reject_if_1h_rsi_above = 75`
- `flip_bullish_cooling.reject_if_15m_no_spring_and_rsi_high = false`

所以，任何对这轮回测的审阅，都必须建立在“profile 已放松”这一前提上。

### 4.4 `flip_bullish` 当前过滤链状态

当前 base 与 active profile 都已经关闭:

- `enable_flip_bullish_strict_filter = false`
- `enable_flip_bullish_cvd_context_filter = false`

当前仍保留:

- `enable_flip_bullish_sniper = true`
- `momentum_reset_max_bars_ago = 12`
- `spring_confirmation_bonus = 0.08`
- `no_momentum_reset_penalty = 0.06`
- `no_spring_penalty = 0.05`
- `require_trend_alignment = true`
- `cooling.reject_if_1h_rsi_above = 75` for active backtest profile
- `cooling.reject_if_15m_no_spring_and_rsi_high = false` for active backtest profile

这解释了为什么当前 `flip_bullish` 的主阻塞点仍然是“过不了上游评分和 sniper”，而不是 strict/cooling。

## 5. 仓位管理与杠杆

### 5.1 本轮回测实际仓位框架

profile 覆盖后的回测仓位上限为:

| 项 | 值 |
|---|---:|
| `default_target_portion` | `0.35` |
| `max_symbol_position_portion` | `0.35` |
| `max_active_symbols` | `3` |
| `reserve_pct` | `0.20` |
| `min_open_portion` | `0.06` |

含义:

- 单笔目标保证金基线是账户可部署资金的 `35%`。
- 每个 symbol 上限也是 `35%`。
- 账户最多同时持有 `3` 个 active symbols。
- 有 `20%` 资金保留，不参与新开仓。
- 任何最终仓位比例低于 `6%`，回测直接拒单。

### 5.2 评分到仓位乘数

当前 `calculate_portion_multiplier()` 逻辑是:

| score 区间 | 仓位乘数 |
|---|---:|
| `>= 0.90` | `1.20` |
| `>= 0.80` | `1.00` |
| `>= 0.65` | `0.80` |
| `>= 0.55` | `0.60` |
| `< 0.55` | `0.00` |

结合本轮 profile 的 `default_target_portion = 0.35`，未加其他修正前的大致基线是:

| score 区间 | 基础目标仓位 |
|---|---:|
| `>= 0.90` | `42%` |
| `>= 0.80` | `35%` |
| `>= 0.65` | `28%` |
| `>= 0.55` | `21%` |

之后还会继续乘以下列修正:

- `vwap_score_position_multiplier`
- `entry_scale` for trial entry
- `rsi_exposure_mult`
- `probe overlay`
- `session risk scale`
- `watchlist throttle`

### 5.3 杠杆逻辑

当前 `calculate_leverage()` 真实逻辑是:

| score 区间 | 基础杠杆 |
|---|---:|
| `>= 0.90` | `4x` |
| `>= 0.85` | `3x` |
| `>= 0.75` | `2x` |
| `< 0.75` | `0` |

随后再叠加:

- `ema_multiplier >= 1.2` 时，强趋势降杠杆
- `rsi_conflict` 会降一档
- `preflip_trial_max_leverage = 2`
- `green_bar_growing_probe_max_leverage = 2`
- `red_bar_growing_probe_max_leverage = 2`
- 全局回测再 clamp 到 `min=2 / default=3 / max=4`

### 5.4 `green_bar_growing` 微探针化

本轮没有新增新的抽象层，而是复用现有 overlay:

| 项 | 当前值 |
|---|---:|
| `enable_green_bar_growing_probe_overlay` | `true` |
| `green_bar_growing_probe_position_penalty` | `0.10` |
| `green_bar_growing_probe_max_leverage` | `2` |

真实效果:

- 若出现 `green_bar_growing`，最终仓位会被压到当前路径原始仓位的 `10%`
- 杠杆上限被压到 `2x`

但必须强调:

- 在最新 `v2_summary_20260429_005509.json` 中，`green_bar_growing` 没有任何成交单
- 所以本轮 PF 改善不能简单归因成“green probe 生效后减少了亏损”
- 更准确的说法是: 当前成交结构已经不再被 `green_bar_growing` 主导

## 6. 当前风控链

### 6.1 不变的核心硬风控

这些红线本轮没有被放松:

- `VWAP 3%` 硬偏离否决
- `max_active_symbols = 3`
- 止损 / 保本 / shrink exit 链
- 连续亏损冷却
- 账户级 circuit breaker

### 6.2 VWAP 风控

当前 `VWAP` 仍承担两个职责:

1. 轻权重评分: `weight_vwap = 0.05`
2. 结构性硬否决:
   - `optimal = 0.5%`
   - `warning = 1.5%`
   - `hard_block = 3.0%`

也就是说:

- `VWAP` 不再主导总分
- 但价格离价值区太远时仍会被直接 veto

### 6.3 止损与保本

当前回测执行层风险参数是:

| 项 | 当前值 |
|---|---:|
| `stop_loss_pct` floor | `0.5%` |
| `take_profit_pct` | `0.0` |
| `breakeven_enabled` | `true` |
| `breakeven_trigger_pnl_ratio` | `0.8%` |
| `breakeven_lock_ratio` | `0.2%` |
| `max_stop_loss_pct` | `2.5%` |

注意这里有两层:

- 回测开仓层有一个全局 `stop_loss_pct` floor，当前来自 `fund_flow.stop_loss_pct = 0.005`
- MACD V2 内部还有动态止损结构，`max_stop_loss_pct = 0.025`

实际开仓时:

1. 优先使用策略给出的 `suggested_stop_price`
2. 否则用 `ATR / 结构 + stop_loss_pct floor`
3. 最终不会放大到超过 `2.5%` 的最大容忍止损

### 6.4 趋势收缩退出

当前仍启用:

- `enable_priority_signal_shrink_exit = true`
- `priority_signal_shrink_exit_required_bars = 3`
- `priority_signal_shrink_exit_required_pct = 0.40`
- `enable_stable_continuation_slow_4h_shrink_exit = true`
- `stable_continuation_exit_4h_shrink_bars = 3`
- `stable_continuation_exit_4h_min_shrink_pct = 0.35`

这类规则的作用不是抢利润，而是防止高优先级和 continuation 类信号在 4H 动量明显衰减时继续持有。

### 6.5 连亏冷却与账户级保护

当前配置仍保留:

| 项 | 当前值 |
|---|---:|
| `max_consecutive_losses` | `2` |
| `consecutive_loss_cooldown_seconds` | `1800` |
| `account_circuit_enabled` | `true` |

回测 summary 也记录了:

- `execute_reject_reasons.entry_cooldown = 3`

这表明冷却链是实际触发过的，不是死配置。

## 7. 新增归因字段定义

### 7.1 `flip_bullish_*`

- `flip_bullish_seen`
  - 被识别为 `flip_bullish` 场景的总样本数
- `flip_bullish_passed_threshold`
  - 成功跨过阈值并进入候选竞争的次数
- `flip_bullish_blocked_by_sniper`
  - 被 sniper 质检链直接否决的次数
- `flip_bullish_blocked_by_cooling`
  - 被 cooling 直接否决的次数
- `flip_bullish_blocked_by_capacity`
  - 已进入候选后，被容量竞争淘汰的次数
- `flip_bullish_ioc_canceled`
  - 已下单但最终 IOC 未成交取消的次数

### 7.2 `market_fallback_*`

- `market_fallback_attempted`
  - 标准 IOC 路径触发市价补单尝试的次数
- `market_fallback_filled`
  - 市价补单成功成交的次数
- `market_fallback_slippage_blocked`
  - 因超出允许滑点而被阻止的次数
- `market_fallback_disabled_by_policy`
  - 因 metadata 或全局门控未满足而被禁用的次数

## 8. 当前状态判断

这轮代码已经把系统推进到一个更健康的位置:

- 不是 `0` 笔塌缩
- 也不是 `119` 笔但 `PF` 偏低、`DD` 偏高的粗放状态
- 而是 `94` 笔、`+44.37%`、`87.23%` 胜率、`PF 7.20`、`DD 6.12%` 的高质量状态

但当前还不能说“多头主引擎已修复”。

最新数据给出的精确结论是:

1. 漏斗已恢复，当前不缺候选。
2. `green_bar_growing` 已不再拖累成交结构。
3. `flip_bullish` 仍未恢复，它的主问题在阈值前和 sniper，而不是 cooling。
4. IOC 市价补单代码已接通，但本窗口里尚未产生实际成交贡献。

如果下一轮继续优化，最值得做的不是再动 `VWAP` 或 `cooling`，而是专项审计:

- `flip_bullish` 的上游得分注入
- `sniper` 的命中密度与误杀率
- 普通 IOC 未成交样本为什么没有进入 `market_fallback_attempted`

这是当前代码和本轮工件共同给出的真实结论。
