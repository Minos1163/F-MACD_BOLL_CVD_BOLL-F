# 2026-05-01 14:00 UTC 至 2026-05-02 02:09 UTC 实盘无开仓分析

## 结论

本窗口内没有开仓不是执行层下单失败，也不是交易时间窗口关闭导致。日志显示策略层没有产生任何 `BUY` / `SELL` 决策：`fund_flow_attribution.jsonl` 内 1247 次 decision 全部为 `hold`，对应 1247 次 execution 全部为 `noop`。

主要根因是 MACD V2 入场漏斗过严，尤其是 `volume_vwap_both_low` 组合否决发生在阈值检查之前，导致部分分数已经超过 `0.68` 入场阈值的候选仍被中性化。次要原因是大量标的被 4H 无明确方向、VWAP 硬阻断、15M RSI 极端和短线 ADX 区间过滤挡住。

## 时间窗口与数据源

- 分析窗口：`2026-05-01 14:00:00 UTC` 到 `2026-05-02 02:09:51 UTC`
- 有效实盘周期：cycle 2 到 cycle 49，约 48 个 15m 周期；cycle 1 在 `2026-05-01 14:14:37 UTC` 为 `WAIT_OPEN_AI`。
- 主要日志：
  - `logs/2026-05/2026-05-01/fund_flow_attribution.jsonl`
  - `logs/2026-05/2026-05-02/fund_flow_attribution.jsonl`
  - `logs/2026-05/2026-05-01/runtime.out.12.log`
  - `logs/2026-05/2026-05-01/runtime.out.18.log`
  - `logs/2026-05/2026-05-02/runtime.out.00.log`

## 运行事实

| 项目 | 数量 |
| --- | ---: |
| decision 事件 | 1247 |
| execution 事件 | 1247 |
| `hold` 决策 | 1247 |
| `noop` 执行 | 1247 |
| `BUY` / `SELL` / `CLOSE` | 0 |
| 覆盖标的 | 26 |

按 regime 看，绝大多数标的并非处于 `NO_TRADE`：

| regime | 次数 |
| --- | ---: |
| TREND | 1133 |
| RANGE | 62 |
| NO_TRADE | 52 |

因此“没有开仓”的直接原因不是整体市场状态被判为 `NO_TRADE`，而是 MACD V2 信号阶段被逐层中性化。

## HOLD 原因分布

| HOLD code | 次数 | 占比 | 解释 |
| --- | ---: | ---: | --- |
| `volume_vwap_both_low` | 589 | 47.2% | 成交量评分低且 VWAP 评分低，组合否决 |
| `4H无明确方向` | 391 | 31.4% | 4H 主方向无法给出可交易方向 |
| `vwap_hard_block` | 169 | 13.6% | VWAP 偏离超过硬阻断范围 |
| `rsi_15m_extreme_veto` | 50 | 4.0% | 15M RSI 极端，入场被否决 |
| `green_bar_growing_short_adx_1h_range_filter` | 21 | 1.7% | 1H ADX 落在配置的短空过滤区间 |
| `信号评分低于阈值` | 16 | 1.3% | 到达 threshold_check，但分数不足 |
| `flip_bullish_disabled` | 10 | 0.8% | flip_bullish 被配置或逻辑禁用 |
| `flip_bullish_sniper_no_trend_alignment` | 1 | 0.1% | 狙击路径缺少趋势对齐 |

最重要的观察：只有 16 次真正死在 `threshold_check` 的“分数低于阈值”。更多候选在到达阈值检查前就被 veto。

## 关键证据：高分信号也被 veto

MACD_V2 runtime 评分行共解析出 1247 条，全部 `dir=neutral`。其中：

| 指标 | 数值 |
| --- | ---: |
| 最高 score | 0.824 |
| 平均 score | 0.222 |
| `score >= 0.68` | 32 |
| `score >= 0.60` | 59 |
| `score >= 0.55` | 135 |
| `score >= 0.50` | 190 |

32 次 `score >= threshold` 的记录全部是 `veto=volume_vwap_both_low`，也就是分数已经达到入场阈值，仍被组合否决中性化。例如：

| cycle | UTC | symbol | score/threshold | veto | 备注 |
| ---: | --- | --- | --- | --- | --- |
| 4 | 2026-05-01 14:45:03 | ZROUSDT | 0.824 / 0.680 | `volume_vwap_both_low` | 高分 trial 信号被否决 |
| 25 | 2026-05-01 20:00:03 | RENDERUSDT | 0.749 / 0.680 | `volume_vwap_both_low` | 高分非 trial 信号被否决 |
| 47 | 2026-05-02 01:30:03 | DOGEUSDT | 0.742 / 0.680 | `volume_vwap_both_low` | 高分 trial 信号被否决 |
| 2 | 2026-05-01 14:15:03 | ICPUSDT | 0.719 / 0.680 | `volume_vwap_both_low` | flip_bullish 背景仍被否决 |

这说明“阈值太高”不是唯一问题。更准确地说，`volume_vwap_both_low` 组合 veto 是当前无开仓的最大硬闸门。

## 代码与配置对应

当前 live 配置启用 MACD V2，核心权重如下：

- `config/trading_config_fund_flow.json:377-384`
  - `weight_4h_direction = 0.40`
  - `weight_rsi_rhythm = 0.30`
  - `weight_1h_direction = 0.15`
  - `weight_vwap = 0.05`
  - `weight_15m_entry = 0.00`
  - `weight_volume = 0.10`

入场阈值：

- `config/trading_config_fund_flow.json:386-396`
  - default / min_signal_score = `0.680`
  - soft_long = `0.660`
  - flip_bearish = `0.660`
  - flip_bullish = `0.640`

`volume_vwap_both_low` 默认阈值来自：

- `src/fund_flow/decision_engine.py:716-722`
  - `volume_vwap_both_low_min_score_vol` 默认 `0.05`
  - `volume_vwap_both_low_min_vwap_score` 默认 `0.10`
- `src/fund_flow/macd_strategy_v2.py:4566-4576`
  - 条件为 `score_vol < min_score_vol` 且 `vwap_score <= min_vwap_score`，满足即返回 `_neutral_signal(...)`

这段组合否决位于 `threshold_check` 之前：

- `src/fund_flow/macd_strategy_v2.py:4566-4583`：先做 `volume_vwap_both_low` veto
- `src/fund_flow/macd_strategy_v2.py:4639-4679`：之后才解析入场阈值并检查 `score < threshold`

决策层如果收到 neutral signal，会直接返回 HOLD：

- `src/fund_flow/decision_engine.py:4387-4391`
  - `operation=Operation.HOLD`
  - reason 为 `macd_v2_hold_{veto_type}_score_{score}`

## 根因判断

1. 最大直接原因：`volume_vwap_both_low` 组合 veto 过强。

   它拦截了 589/1247 次 HOLD，占 47.2%。更关键的是，32 次已经达到入场阈值的候选也全部被它挡住。当前实现中该 veto 不区分普通低分候选和高分/试探/4H 主方向较强候选，只要 `VOL < 0.05` 且 `VWAP <= 0.10` 就中性化。

2. 4H 主方向门槛导致大量 neutral。

   `4H无明确方向` 有 391 次，占 31.4%。当前配置 `primary_direction_timeframe = 4h`，并且 4H direction 权重最高。实盘里许多 1H 有红/绿柱变化，但 4H 不给方向时仍进入 neutral upgrade 路径，最后没有形成可交易方向。

3. VWAP 相关逻辑形成双重约束。

   `vwap_hard_block` 有 169 次，占 13.6%；同时 `volume_vwap_both_low` 又依赖低 VWAP 评分。也就是说 VWAP 一方面可硬阻断偏离过大的机会，另一方面在偏离不大但 VWAP score 低时仍会与低 volume 组合阻断。当前窗口内 VWAP 相关拦截合计 758 次，占 60.8%。

4. 15M 入场确认在评分上几乎不提供正向贡献。

   配置 `weight_15m_entry = 0.00`，日志中 `entry_15m=-` 有 1132 次，`rsi_extreme_block` 有 50 次。15M 当前更多表现为否决/阻断，而不是帮助形成入场方向。

5. 不是风控冷却、交易时间窗口或下单失败。

   attribution 里 `entry_window_filter.enabled=false` 且 `allowed=true`；execution 全部是 `noop/hold`，没有订单拒绝、滑点失败或交易所返回错误的证据。

## 给 Claude 审核的问题

1. `volume_vwap_both_low` 是否应在高分候选上降级为 position scale / trial，而不是直接 neutral？
2. 对 `score >= threshold` 且 4H/1H 至少一侧明确的候选，是否应放行极小仓试探，或者要求额外确认后进入 watcher？
3. `weight_15m_entry = 0.00` 是否符合当前策略目标？如果 15M 只负责否决、不负责加分，开仓频率会天然偏低。
4. VWAP 现在同时承担硬阻断和低分组合 veto，是否需要拆分为“位置风险降仓”和“绝对禁入”两类？
5. `primary_direction_timeframe=4h` 在低波动/盘整窗口是否过慢？是否允许 1H 明确方向 + 4H 非反向时轻仓试探？

## 建议的下一步验证

先不要直接改 live 参数。建议对最近 30 天回测做三组最小 A/B：

1. 仅放松 `volume_vwap_both_low`：
   - 将 `volume_vwap_both_low_min_score_vol` 从 `0.05` 改为 `0.0`，或
   - 将该 veto 改为只在 `score < threshold` 时生效。

2. 仅恢复 15M 正向入场权重：
   - `weight_15m_entry` 从 `0.00` 调到 `0.05` 或 `0.10`，对应下调其他权重保持总分预算。

3. 仅调整 4H 主方向约束：
   - 保持 4H-primary，但允许 1H 明确方向且 4H 非反向时进入 trial。

验收指标不应只看开仓数，还要看：

- trade count 是否恢复到预期区间；
- 亏损集中是否来自被放开的 `volume_vwap_both_low` 样本；
- `score >= threshold` 但原先被 veto 的 32 类样本在回测中的真实表现；
- live watcher / trial 是否能避免低 VWAP 低成交量的追单损失。
