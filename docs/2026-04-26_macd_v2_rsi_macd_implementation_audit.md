# MACD V2 RSI-MACD 共振实现审计

## 0. 文档范围

这份文档只记录当前代码里**已经真实落地**的门槛、权重和分数链路，不混入未实现假设。

审计目标只有 4 个：

1. 说明 live/backtest 共用的真实门槛和打分口径。
2. 说明 `VWAP` 为什么已经不是回测结果的主决定因子。
3. 说明 `RSI` 如何补 `MACD` 的滞后，但为什么还没有被用得足够灵活。
4. 给 DeepSeek 一份和当前代码一致的评审口径，方便下一轮专门提升胜率。

---

## 1. 当前真实配置口径

### 1.1 门槛

- `min_signal_score = 0.85`
- `flip_bullish_min_signal_score = 0.82`
- `flip_bearish_min_signal_score = 0.84`
- `green_bar_growing_min_signal_score = 0.87`
- `red_bar_growing_min_signal_score = 0.90`
- `min_vwap_score_for_entry = 0.10`
- `priority_exec_min_score = 0.90`
- `priority_exec_vip_min_score = 0.92`
- `priority_exec_expire_seconds = 15`
- `priority_exec_vip_expire_seconds = 30`
- `neutral_upgrade_min_rsi_score = 0.35`
- `neutral_upgrade_probe_rsi_score = 0.20`
- `neutral_upgrade_penalty_mult = 0.90`
- `rsi_conflict_threshold = 0.20`
- `rsi_conflict_penalty_mult = 0.95`
- `spring_override_min_signal_score = 0.82`
- `spring_override_score_bonus = 0.10`
- `rsi_rhythm_block_score = -0.30`
- `rsi_probe_exposure_mult = 0.20`
- `rsi_probe_portion_scale = 0.25`
- `rsi_probe_forced_leverage = 2`

### 1.2 权重

| 层 | 权重 | 当前职责 |
| --- | ---: | --- |
| `weight_4h_direction` | `0.40` | 4H 主方向与结构主分 |
| `weight_1h_direction` | `0.15` | 1H 趋势健康与一致性 |
| `weight_rsi_rhythm` | `0.30` | RSI 节奏、启动、衰减、冲突修正 |
| `weight_vwap` | `0.05` | 轻量位置背景 |
| `weight_volume` | `0.10` | 成交量质量确认 |
| `weight_15m_entry` | `0.00` | 已退役，15m 已并入 RSI rhythm |

说明：

- `weight_4h_enhancement` 仍保留兼容读取，但运行时已经折叠进 4H direction。
- `VWAP` 已从早期中权重降到 `0.05`，只保留轻量打分和硬偏离否决。
- 当前进一步把 `VWAP` 降到 `0.00~0.05` 的思路是合理的，因为它已经不再是收益分层主因。

---

## 2. 当前真实分数计算

### 2.1 基础总分

当前代码实际使用的是五层加总：

```text
total_score =
  score_4h_trend
  + score_1h_direction
  + score_rsi_rhythm
  + score_vwap
  + score_volume
  - overheat_penalty
  + flip_bullish_sniper_bonus
```

其中：

- `score_4h_trend` 上限由 `0.40` 钳制。
- `score_1h_direction` 上限由 `0.15` 钳制。
- `score_rsi_rhythm = rsi_raw * 0.30`。
- `score_vwap` 当前上限只有 `0.05`。
- `score_volume` 当前上限 `0.10`。

### 2.2 二次调节链路

基础总分之后，还会继续经过四个调节器：

1. `neutral_upgrade`
2. `RSI-MACD tiered conflict`
3. `15m spring threshold override`
4. `probe / leverage / portion overlay`

顺序是：

```text
1. 先算基础总分
2. 如果是 neutral_upgrade，总分先乘 0.90
3. 如果命中 RSI-MACD 冲突，再按冲突类型处理
4. 如果命中 15m spring override，再加 0.10，并把门槛降到 min(原门槛, 0.82)
5. 再做最终阈值判断
6. 阈值通过后，再做杠杆/仓位执行层缩放
```

### 2.3 RSI-MACD 冲突处理

当前真实实现不是“一刀切总分 *0.85”，而是分层：

| 类型 | 总分 | 杠杆 | 仓位 |
| --- | --- | --- | --- |
| `leading` | `*1.00` | 降一档 | `*0.80` |
| `divergence` | `*0.95` | 降一档 | `*0.85` |
| `extreme_oppose` | 不直接砍总分 | 强制 `probe` | 强制 `probe` |

这一步已经比旧版灵活，但还不够。

当前 `RSI` 仍主要在 `MACD` 已经给方向以后再做放行/惩罚，而不是直接作为“节奏前导器”去释放启动。

---

## 3. `flip_bullish` 当前真实专项逻辑

### 3.1 `flip_bullish_sniper`

`flip_bullish` 会做 3 轴质量检查：

1. `momentum_reset_found`
   - 最近 12 根 1H RSI 里，最低值是否 `< 40`
2. `spring_confirmed`
   - `rsi_spring` / `rsi_neutral_resume` 都可作为 spring-like 启动结构
3. `trend_aligned`
   - 当前 4H MACD histogram 是否仍在零轴上方

当前不是“只有 3/3 才能活”。

- `3/3` 命中：`perfect_launch`，加分 `+0.08`
- `2/3` 命中：`qualified_launch`，加分 `+0.04`
- `<2/3`：`weak_launch_profile`，不参与开仓

这次修正的关键点是：

- `rsi_neutral_resume` 现在被视为有效的 spring-like 启动结构
- 不再因为“不是极端 spring”就把 `flip_bullish` 整类清空

### 3.2 `flip_bullish_cooling`

`cooling` 只拦截真正过热、且缺少 spring-like 结构的多头启动：

- `1H RSI > 72` 且不是 `rsi_spring / rsi_neutral_resume`
- 或者 `15m RSI > 65` 且没有 spring-like 结构

也就是说：

- 高 RSI 但有 spring-like 结构的启动，当前允许继续竞争
- 只有“高 RSI + 没有节奏确认”的启动才会被直接打掉

### 3.3 `flip_bullish_strict_filter`

当前它仍然存在，但已经不再是用来把 `flip_bullish` 直接压死的重门槛。

当前更像：

- 作为轻量质量修正
- 保护 `flip_bullish` 不被低质量 15m 结构拖坏
- 但不负责主导吞吐

---

## 4. 为什么 `VWAP` 已经不再决定回测结果

### 4.1 当前实现事实

`VWAP` 现在主要只剩 3 个职责：

1. `vwap_deviation_hard_block = 3%`
2. `vwap_state` 作为结构描述
3. `weight_vwap = 0.05` 的轻量打分

同时：

- `flip_bullish / flip_bearish` 已经豁免 `min_vwap_score_for_entry`
- 真正成交的单子，`vwap_score` 事实上全部集中在低位区间

### 4.2 回测证据

最新 30 天成交单中，`VWAP` 分布如下：

| 区间 | 笔数 | 胜率 | 累计PnL |
| --- | ---: | ---: | ---: |
| `[0.00, 0.05)` | `14` | `85.71%` | `2513.20` |
| `[0.05, 0.10)` | `0` | - | `0` |
| `[0.10, 0.15)` | `0` | - | `0` |
| `[0.15, 1.00)` | `0` | - | `0` |

这说明：

- 本轮回测的所有成交都落在低 `VWAP` 区间
- `VWAP` 的细分得分没有真正决定成交去向
- 真正决定盈亏分层的，是 `信号家族 + RSI 节奏 + 执行路由`

### 4.3 当前结论

`weight_vwap = 0.05` 已经足够低。

如果下一轮继续评审，`VWAP` 最合理的实验范围就是 `0.00~0.05`。

继续把 `VWAP` 抬回 `0.10+`，大概率只会稀释 `RSI + MACD` 的主导作用，不会明显改善胜率。

---

## 5. 为什么 RSI 还没有把 MACD 的滞后补得足够好

### 5.1 现在的问题

`RSI` 已经不是单纯惩罚器了，但它还没有完全变成一个“独立节奏层”。

当前 `RSI` 的问题有 3 个：

1. 它仍然主要依附在 `MACD` 的方向之后做修正。
2. 当 `RSI` 和 `MACD` 方向相异时，当前多半只是在仓位/杠杆上降级，而不是在入口节奏上形成更灵活的放行。
3. `15m` spring 已经并入 `RSI rhythm`，但它的作用仍然偏像“加分/扣分”，而不是独立的节奏确认器。

### 5.2 这为什么会伤到胜率

如果 RSI 只是附属修正器，那么两类高质量形态会被压缩：

- `RSI` 先启动、`MACD` 后确认的反转单
- `RSI` 与 `MACD` 略有分歧，但实盘里反而更早给出胜率的单

这会导致：

- 核心多头节奏（尤其 `flip_bullish`）不够灵活
- 真正好的启动被过度压缩
- 为了保胜率而失去吞吐

### 5.3 现在的 resonance 还没用好

当前共振的使用方式更接近：

- `MACD` 决定能不能进
- `RSI` 决定要不要降仓、降杠杆、或者 probe

但更合理的方式应该是：

- `RSI` 提供早启动和节奏前导
- `MACD` 提供中周期确认
- 两者一致时给更高质量
- 两者轻微冲突时只降风险，不要直接抹掉 RSI 的敏捷性

这正是当前策略还不够灵活的地方。

---

## 6. 最新 30 天回测归因

### 6.1 当前基线

- `return_pct = 24.54%`
- `win_rate_pct = 85.71%`
- `profit_factor = 25.09`
- `max_drawdown_pct = 5.93%`
- `total_trades = 14`

### 6.2 信号家族

- `flip_bearish`: `11` 笔，`10` 胜，胜率 `90.91%`
- `flip_bullish`: `3` 笔，`2` 胜，胜率 `66.67%`

### 6.3 执行漏斗

- `candidate_entries = 46`
- `orders_submitted = 44`
- `orders_filled = 14`
- `orders_canceled = 30`
- `WSR = 65.22%`

### 6.4 归因结论

这轮结果说明：

1. **`VWAP` 不是主因。**
   所有成交都落在低 `VWAP` 区间，VWAP 只能当背景过滤器，不能当胜率主引擎。

2. **胜率主要由信号家族分布决定。**
   当前收益几乎由 `flip_bearish` 和少量 `flip_bullish` 支撑，`flip_bullish` 仍然是最需要修正的多头主通道。

3. **RSI 共振还不够灵活。**
   它已经比旧版好，但还没有把“RSI 先行、MACD 后确认”的典型高胜率节奏充分释放出来。

4. **如果下一轮放量，最先被伤到的会是胜率。**
   所以真正的下一步不是再加 `VWAP` 权重，而是让 RSI 成为更独立的节奏层，同时保持冲突分层，不要把 RSI 再次压回附属地位。

---

## 7. DeepSeek 评审重点

请重点评审以下三点：

1. `VWAP` 权重是否应继续维持在 `0.00~0.05`，而不是恢复到 `0.10+`。
2. `RSI` 是否应从“MACD 的附属修正器”升级为“独立节奏决策器”。
3. `RSI` 和 `MACD` 方向不一致时，是否应该更多地影响仓位和杠杆，而不是直接牺牲 RSI 的敏捷性。

---

## 8. 一句话结论

**当前系统的瓶颈不是 `VWAP`，而是 `RSI-MACD` 共振没有被做成足够灵活的节奏层；`VWAP` 应继续保持低权重，真正要修的是让 RSI 在和 MACD 有轻微分歧时，仍然保留敏捷性而不是被压成附属惩罚器。**
