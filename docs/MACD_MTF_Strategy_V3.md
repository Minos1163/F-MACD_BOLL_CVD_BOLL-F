# MACD_MTF_Strategy_V3

Version: V3  
Date: 2026-03-19  
Scope: `fund_flow.strategy_mode = macd_mtf_strategy_v2` 的当前实盘推荐版本

---

## 1. Strategy Summary

`MACD_MTF_Strategy_V3` 是一套基于多时间框架 MACD、VWAP、EMA 结构过滤和统一风控执行约束的趋势跟随策略。

当前 V3 不是原始 V2 的简单延续，而是经过以下三轮修正后的可部署版本：

1. 修复统一时间轴回测中的执行顺序错误。
2. 去除历史上显著拖累收益的 `green_bar_growing` 空头延续入场。
3. 去除历史上显著拖累收益的 `flip_bullish` 多头翻红入场。

当前 V3 的交易核心可概括为：

- 1H MACD 决定大方向
- 4H MACD 做趋势增强，而不是绝对否决
- 15M MACD 负责寻找跟随入场
- 1H VWAP 决定位置质量
- 1H/4H EMA 结构决定是否顺势，以及是否应降杠杆
- 风控主要依赖动态止损、保本、反向信号离场，而非固定止盈

当前启用后的有效入场信号只剩两类：

- `red_bar_growing`：1H 多头延续
- `flip_bearish`：1H 空头翻绿

---

## 2. Design Goals

V3 的目标不是“高频抓所有波动”，而是：

- 优先保留可重复的趋势延续交易
- 减少高分但位置过热的追涨杀跌单
- 通过更少但更干净的交易，提高实盘容忍度
- 让执行链与回测链尽量共享同一套规则和参数

这套策略更接近“中低频趋势轮动系统”，不是纯短线 scalp。

---

## 3. Multi-Timeframe Architecture

### 3.1 Timeframes

- 主方向周期：`1H`
- 趋势增强周期：`4H`
- 入场执行周期：`15M`
- 扫描周期：`15M`

### 3.2 Layer Responsibilities

1. `MACD_1H`
   - 定方向
   - 给出 `long / short / neutral`
   - 给出方向信号类型

2. `EMA Structure`
   - 判断当前是否顺势
   - 给出 `strong / normal / weak / against`
   - 影响评分和杠杆

3. `VWAP`
   - 判断当前价格相对于 1H VWAP 的位置质量
   - 对过热位置降分或直接 veto

4. `MACD_4H`
   - 作为增强确认
   - 不做绝对方向裁决

5. `MACD_15M`
   - 跟随 1H 方向寻找入场节奏
   - 配合 15M EMA21 做 pullback 精化

6. `Risk / Execution`
   - 统一用 IOC + 滑点约束 + 动态止损 + 保本 + 反向离场

---

## 4. Current Live Parameter Set

以下是当前推荐上线参数，来源于 [trading_config_fund_flow.json](/d:/AIDCA/AI2/config/trading_config_fund_flow.json#L180) 一带配置。

### 4.1 Portfolio / Position Limits

- `max_active_symbols = 3`
- `default_target_portion = 0.6`
- `max_symbol_position_portion = 0.6`
- `min_open_portion = 0.06`
- `reserve_pct = 0.20`

解释：

- 组合同时最多持有 3 个币
- 单币目标仓位按评分乘数计算，基础目标为余额的 60%
- 留 20% 现金作为缓冲

### 4.2 Leverage

- `min_leverage = 2`
- `default_leverage = 3`
- `max_leverage = 4`
- `high_signal_leverage_cap = 3`
- `ema_strong_trend_leverage_mult = 0.8`

说明：

- 策略引擎根据评分输出杠杆，最终受 `2x~4x` 约束
- 当 EMA 结构处于强趋势状态时，不是加杠杆，而是乘以 `0.8` 降杠杆
- 当前实盘推荐保留动态杠杆，不建议手动强制 `5x`

### 4.3 Stop / TP / Breakeven

- `stop_loss_pct = 0.004`
- `take_profit_pct = 0.0`
- `breakeven_enabled = true`
- `breakeven_trigger_pnl_ratio = 0.003`
- `breakeven_lock_ratio = 0.001`

解释：

- 固定 TP 关闭
- 主要靠动态止损、保本和反向信号出场
- 这套策略本质上是“让盈利单通过反向信号跑出更大段”，不是固定止盈系统

### 4.4 Execution

- `entry_slippage = 0.0015`
- `time_in_force = IOC`
- `decision_timeframe = 15m`

说明：

- 开仓按限价近似撮合
- IOC 未成交则撤单
- 回测也已按此逻辑做近似

---

## 5. Core Signal Logic

### 5.1 MACD 1H Direction Engine

1H MACD 负责决定大方向。

支持的原始信号类型：

- `flip_bullish`
- `flip_bearish`
- `red_bar_growing`
- `green_bar_growing`
- `red_bar_shrinking`
- `green_bar_shrinking`

逻辑摘要：

- `flip_bullish`
  - 上一根 histogram `<= 0`
  - 当前根 histogram `> 0`
  - 方向：`long`

- `flip_bearish`
  - 上一根 histogram `>= 0`
  - 当前根 histogram `< 0`
  - 方向：`short`

- `red_bar_growing`
  - 两根都大于 0
  - 当前红柱大于上一根红柱
  - 方向：`long`

- `green_bar_growing`
  - 两根都小于 0
  - 当前绿柱绝对值继续扩大
  - 方向：`short`

- 两类 shrinking
  - 不作为有效开仓方向

当前 V3 经过筛选后，**最终允许入场的 1H 信号只保留**：

- `red_bar_growing`
- `flip_bearish`

### 5.2 Why `flip_bullish` Is Disabled

`flip_bullish` 在多轮统一时间轴回测中持续表现为负贡献，属于“看起来像启动，但大量落在不够干净的多头反弹早期”的信号。

最终处理方式：

- 保留代码层配置能力
- 当前配置中直接关闭：`disable_flip_bullish_entries = true`

### 5.3 Why `green_bar_growing` Is Disabled

`green_bar_growing` 空头延续在修正回测后仍然是最明显的拖累项，说明在当前市场样本里：

- 它经常发生在空头动能已经走得太远的位置
- 它的顺势评分较高，但位置质量不够好
- 它更像追跌而不是优质继续下行

最终处理方式：

- 当前配置中直接关闭：`disable_green_bar_growing_entries = true`

---

## 6. MACD 15M Entry Logic

15M 不决定方向，只负责跟随 1H 方向做入场节奏。

### 6.1 Long Entry Types

- `flip_bullish`
- `red_bar_growing`
- `red_bar_stable`
- `red_bar_shrinking`

### 6.2 Short Entry Types

- `flip_bearish`
- `green_bar_growing`
- `green_bar_stable`
- `green_bar_shrinking`

### 6.3 Entry Score Baseline

- 翻色跟随：`1.0`
- growing：`0.85`
- stable：`0.6`
- shrinking：`0.3`

### 6.4 EMA21 15M Refinement

如果有 15M EMA21：

- 多头：
  - 价格回踩 EMA21 后反弹：`pullback_bounce`
  - 入场评分增强
  - 若价格在 EMA21 下方，则入场评分乘以 `0.7`

- 空头：
  - 价格反弹至 EMA21 后回落：`pullback_drop`
  - 入场评分增强
  - 若价格在 EMA21 上方，则入场评分乘以 `0.7`

这一步的意义是：

- 让“趋势中的二次确认”优先于“单纯 MACD 触发”
- 减少离均线太远的追单

---

## 7. EMA Structure Logic

EMA 结构是这套策略最重要的环境过滤器之一。

### 7.1 Long Structure

- `strong`
  - `close_1h > ema55_1h`
  - `ema21_1h > ema55_1h`
  - `ema21_4h > ema55_4h > ema200_4h`

- `normal`
  - `close_1h > ema21_1h`

- `weak`
  - 部分站上均线，但结构不完整

- `against`
  - 与多头方向不一致

### 7.2 Short Structure

与 long 对称：

- `strong`
  - `close_1h < ema55_1h`
  - `ema21_1h < ema55_1h`
  - `ema21_4h < ema55_4h < ema200_4h`

### 7.3 EMA Multiplier

- `strong = 1.2`
- `normal = 1.0`
- `weak = 0.6`

注意：这里的 `1.2` 会增强评分，但实盘杠杆又会被 `ema_strong_trend_leverage_mult = 0.8` 压回来。所以它代表“趋势质量更高”，不代表“应该更重仓”。

---

## 8. VWAP Logic

VWAP 使用 1H 上下文中的 VWAP 数据。

### 8.1 VWAP Scores

对于 long：

- 偏离过热：直接 veto
- 偏离较高：`0.10`
- 接近中枢：`0.12`
- 略低于中枢、位置更优：`0.15`

对于 short：

- 对称处理

### 8.2 Current VWAP Parameters

- `vwap_deviation_optimal = 0.005`
- `vwap_deviation_warning = 0.015`
- `vwap_deviation_hard_block = 0.030`

这套逻辑的核心不是找最强突破，而是避免在价值中枢过度偏离后继续追。

---

## 9. Scoring Model

### 9.1 Weight Allocation

- `weight_1h_direction = 0.35`
- `weight_4h_enhancement = 0.15`
- `weight_vwap = 0.15`
- `weight_15m_entry = 0.20`
- `weight_volume = 0.15`

总分满分为 `1.0`。

### 9.2 Thresholds

- `min_entry_score = 0.25`
- `min_signal_score = 0.85`

只有当综合评分达到 `0.85` 以上，才会输出有效交易方向。

### 9.3 Overheat Penalty

V3 新增过热惩罚：

- `overheat_growing_penalty = 0.12`
- `overheat_ema_multiplier_threshold = 1.2`
- `overheat_vwap_score_threshold = 0.10`

触发条件：

- EMA 结构强
- VWAP 位置一般或偏热（`<= 0.10`）
- 信号或 15M 入场属于 `growing`

含义：

- 这是“趋势看起来很强，但位置已经不便宜”的典型追单场景
- 在 V2 里，这类单经常被打出高分
- V3 对其主动减分，降低入场概率

### 9.4 Fixed Veto Repair

此前策略里有一条几乎不会触发的 veto：

- `score_vol < 0.05 and vwap_score < 0.10`

由于非 veto 情况下 `vwap_score` 最低通常就是 `0.10`，所以这条条件基本失效。

V3 已修正为：

- `score_vol < 0.05 and vwap_score <= 0.10`

---

## 10. V3 Hard Filters

### 10.1 `flip_bullish` Strict Filter

虽然当前已直接禁用 `flip_bullish`，但仍保留严格过滤逻辑，便于未来恢复测试。

参数：

- `enable_flip_bullish_strict_filter = true`
- `flip_bullish_min_vwap_score = 0.12`
- `flip_bullish_require_pullback_bounce = true`
- `flip_bullish_require_15m_growing = true`

含义：

如果未来重新打开 `flip_bullish`，则必须满足：

- 15M 入场形态是 `red_bar_growing`
- 15M refine 是 `pullback_bounce`
- VWAP 至少达到 `0.12`

### 10.2 Disabled Signals in Current Live Set

当前配置直接禁用：

- `flip_bullish`
- `green_bar_growing`

因此当前 V3 实际 live signal universe 为：

- `red_bar_growing`
- `flip_bearish`

---

## 11. Risk and Exit Logic

### 11.1 Dynamic Stop

动态止损锚点：

- Long：
  - 优先参考 `EMA21_1H - ATR * ema_stop_atr_multiplier`
  - 否则退回到 `EMA55_1H`

- Short：
  - 对称处理

参数：

- `ema_stop_atr_multiplier = 0.5`
- `max_stop_loss_pct = 0.025`
- 外层 fund-flow 默认止损口径：`0.004`

说明：

- 信号层给出 `suggested_stop_price`
- 执行层优先使用该建议止损
- 若无效，再回退到 fund-flow 默认止损

### 11.2 Breakeven

- 开启：`true`
- 触发盈利：`0.3%`
- 锁盈：`0.1%`

### 11.3 Take Profit

- `take_profit_pct = 0.0`

这意味着：

- 没有固定止盈
- 盈利主要来自：
  - 保本后继续运行
  - 反向信号出场
  - 回测结束平仓

### 11.4 Reverse Exit

V3 的一个重要特征是：

- `signal_reverse` 对整体盈利贡献很大

说明这套策略真正的 edge 不是“小盈快跑”，而是“在对的趋势单上尽量留住”。

---

## 12. Backtest Methodology

V3 的结论基于当前已修正的统一时间轴回测：

- 全市场共享 `15m` 时间轴
- 多币种同时间推进
- 同时考虑组合级仓位上限
- 支持 IOC 开仓近似
- 支持 `entry_slippage`
- 支持 intrabar `high/low` 止损触发
- 已修复“刚成交同 bar 就立刻被 stop”这一错误

这点非常重要。早期版本曾因回测顺序错误，严重夸大了 stop-out。

---

## 13. Current Baseline Backtest

来源：

- [v2_summary_20260319_125906.json](/d:/AIDCA/AI2/output/backtest/v2_summary_20260319_125906.json)
- [v2_trades_20260319_125906.csv](/d:/AIDCA/AI2/output/backtest/v2_trades_20260319_125906.csv)

结果：

- 初始资金：`$10,000`
- 最终权益：`$14,467.33`
- 收益率：`+44.67%`
- 总交易：`156`
- 胜率：`69.9%`
- 盈利因子：`3.01`

按信号拆分：

- `red_bar_growing`：`+4736.48`
- `flip_bearish`：`+213.78`

这说明：

- 多头主收益来自 `red_bar_growing`
- 空头主要依赖 `flip_bearish`
- 被禁用的两类信号在历史样本中确实是拖累项

---

## 14. Stress Test and Tolerance

### 14.1 Portfolio-Level Stress

基于最新回测结果：

- 组合最大回撤：`-8.20%`
- 最差单笔：`-$712.05`
- 最长连续亏损：`7`
- 最差单日：`-$700.54`
- 最差 3 笔滚动亏损：`-$712.73`
- 最差 5 笔滚动亏损：`-$707.03`
- 最差 10 笔滚动亏损：`-$714.79`

### 14.2 Interaction With Current Account Risk Controls

当前账户级风控配置：

- `risk.max_daily_loss_percent = 5`
- `risk.max_consecutive_losses = 2`

解释：

- 历史最差日达到约 `-7.0%`
- 因此如果未来实盘再出现类似日，账户级日损熔断会被触发
- 这是合理的，不应关闭

### 14.3 Symbol-Level Risk Concentration

当前最值得关注的弱币种：

- `UNIUSDT`
  - total pnl `-724.94`
  - symbol max drawdown `-7.41%`

- `HBARUSDT`
  - total pnl `-478.79`
  - symbol max drawdown `-4.88%`
  - max loss streak `5`

- `FILUSDT`
  - total pnl `-272.69`

- `DOGEUSDT`
  - total pnl `-206.77`

这意味着：

- V3 虽然组合正收益明显，但并非所有币都适配
- 后续如果要继续提高稳定性，优先考虑 symbol blacklist，而不是先破坏主逻辑

---

## 15. Practical Deployment Guidance

### 15.1 Recommended Live Start

建议上线时直接使用当前 V3 推荐集，不再打开被禁用信号：

- `max_active_symbols = 3`
- 保留动态杠杆 `2x~4x`
- 保留 `flip_bullish` 关闭
- 保留 `green_bar_growing` 关闭

### 15.2 What To Watch in First Live Batch

必须重点盯以下三类日志：

1. 决策日志
   - 是否只出现预期的 `red_bar_growing` 与 `flip_bearish`

2. 执行日志
   - 是否 IOC 挂单与保护单下发成功

3. 风控日志
   - 是否日损熔断、连续亏损熔断按预期触发

### 15.3 First Escalation Path

如果首批实盘发现 cluster stop-out：

1. 先把 `max_active_symbols` 从 `3` 降到 `2`
2. 不要先改杠杆上限
3. 再观察 `UNIUSDT` / `HBARUSDT`
4. 必要时做 symbol blacklist

---

## 16. Current Strategy Character

从交易统计上看，V3 现在的性格很明确：

- 它不是对称型 long/short 策略
- 它偏向：
  - 做多只做更稳定的 `red_bar_growing`
  - 做空只做更干净的 `flip_bearish`
- 它不是靠高胜率小止盈，而是靠：
  - 少做差交易
  - 留住盈利段
  - 让 `signal_reverse` 出现时再大段离场

这也是它在当前参数下能把 profit factor 拉到 `3.01` 的主要原因。

---

## 17. Key Open Questions For Expert Review

这份文档适合给虚拟货币投资专家组讨论的核心问题如下：

1. `red_bar_growing` 多头延续是否需要进一步拆分：
   - 强趋势 continuation
   - 末端动能追高

2. `flip_bearish` 是否应进一步加入：
   - funding filter
   - OI / basis / market regime filter

3. 当前 `take_profit_pct = 0.0` 是否应保持纯 runner 模式，还是加入分层减仓

4. `UNIUSDT`、`HBARUSDT` 是否应做 symbol-level 风险开关

5. 动态杠杆是否要更保守：
   - 当前 `2x~4x`
   - 是否应进一步收缩至 `2x~3x`

6. `max_active_symbols = 3` 是否已是组合层最优，还是需要做“相关性去重”而不仅仅是数量限制

---

## 18. Final Assessment

V3 不是理论最完整的版本，而是目前在：

- 统一时间轴回测
- 统一执行口径
- 风控约束
- 实盘可部署性

之间达到相对平衡的一版。

如果目标是“马上实盘部署并接受专家组复盘”，当前建议是：

- 用 V3 作为讨论母版
- 不再恢复 `flip_bullish`
- 不再恢复 `green_bar_growing`
- 先用当前参数跑 live
- 再基于实盘日志做第二轮 symbol-level 与 regime-level 精细化

