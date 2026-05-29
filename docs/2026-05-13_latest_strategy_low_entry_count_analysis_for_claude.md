# 2026-05-13 最新策略开仓偏少日志分析包

## 结论摘要

分析窗口：北京时间 `2026-05-12 22:00` 至 `2026-05-13 14:20` 左右，即 UTC `2026-05-12 14:00` 至 `2026-05-13 06:20`。日志来源：

- `logs/2026-05/2026-05-12-2`
- `logs/2026-05/2026-05-13`

核心结论：开仓数量少的主因不是调度/API 未运行，也不是单纯分数阈值太高，而是最新策略的大多数候选在进入最终分数阈值前已经被方向/节奏/VWAP 门控归零。具体表现为：

1. `4H无明确方向` 是最大 HOLD 原因。
2. `rsi_1h_direction_against_veto` / `rsi_1h_direction_flat_veto` 是第二层主要拦截。
3. `vwap_hard_block` 也占很大比例。
4. 纯粹因为 `signal_score < entry_threshold` 的 HOLD 只有约一成。
5. 另有少量信号已达 final，但被 `min_open_portion=0.06` 拦截；这是次要原因，不是根因。

## 运行与成交概况

窗口内 `api_cycle_stats_utc.jsonl` 显示调度正常：

- 周期数：`67`
- 扫描模式：`65` 次 `MIXED_AI_REVIEW`，`1` 次 `WAIT_POSITION_AI`，`1` 次 `OPEN_WINDOW_AI_TOP2`
- `allow_new_entries=True`：`66/67`
- 每轮处理标的：主要为 `28/29`
- API 状态：主要为 `200`

窗口内 `fund_flow_attribution.jsonl` 决策统计：

| 类型 | 次数 |
|---|---:|
| HOLD | 1875 |
| BUY | 3 |
| SELL | 1 |
| 总策略决策 | 1879 |

执行结果统计：

| 执行状态 | 次数 |
|---|---:|
| noop | 1834 |
| error | 41 |
| pending | 4 |

实际成交去重后共 `8` 条 fill，涉及 `POLUSDT`、`SUIUSDT`、`DOGEUSDT`。其中窗口内真正由当前策略输出的非 HOLD 决策只有：

| UTC 时间 | 北京时间 | Symbol | 方向 | 目标占比 | runtime 状态 |
|---|---|---|---|---:|---|
| 2026-05-12 21:45 | 2026-05-13 05:45 | SUIUSDT | SELL | 0.09 | pending |
| 2026-05-13 01:00 | 2026-05-13 09:00 | DOGEUSDT | BUY | 0.17 | pending |
| 2026-05-13 02:00 | 2026-05-13 10:00 | DOGEUSDT | BUY | 0.17 | pending |
| 2026-05-13 06:15 | 2026-05-13 14:15 | TRUMPUSDT | BUY | 0.10 | pending |

## HOLD 归因排序

按 runtime 中 `HOLD归因` 统计，窗口内 `1875` 次 HOLD 的主要原因如下：

| 排名 | HOLD code/reason | 次数 | 占 HOLD 比例 | 判断 |
|---:|---|---:|---:|---|
| 1 | `4H无明确方向` | 788 | 42.0% | 主因，方向门控 |
| 2 | `rsi_1h_direction_against_veto` | 362 | 19.3% | 主因，1H/RSI 节奏否决 |
| 3 | `vwap_hard_block` | 360 | 19.2% | 主因，VWAP 结构硬否决 |
| 4 | `信号评分低于阈值` | 178 | 9.5% | 次因，才是常规分数门槛 |
| 5 | `rsi_15m_extreme_veto` | 73 | 3.9% | 次因 |
| 6 | `rsi_1h_direction_flat_veto` | 61 | 3.3% | 次因 |

按 `stage` 统计：

| stage | 次数 | 含义 |
|---|---:|---|
| `rsi_rhythm` | 496 | 方向虽有雏形，但 RSI/1H 节奏未通过 |
| `neutral_upgrade_mode` | 484 | 方向不明确后尝试 neutral upgrade，但未成功 |
| `vwap` | 360 | VWAP 硬否决 |
| `neutral_upgrade_gate` | 304 | 方向不明确，且没有可升级方向 |
| `threshold_check` | 178 | 已进入最终阈值检查但分数不足 |

这说明最新策略的主要瓶颈在“候选进入最终评分前被方向/结构门提前杀掉”，而不是最终 `0.68/0.69/0.66/0.64` 阈值单独过高。

## 方向不确定是主因

日志中大量样例形态类似：

```text
MACD_V2评分: stage=neutral_upgrade_gate, dir=neutral, primary=4H:0.0000(...), 1H=0.0000(...), total=0.0000/0.6800
HOLD归因: stage=neutral_upgrade_gate, reason=4H无明确方向
```

以及：

```text
MACD_V2评分: stage=rsi_rhythm, dir=neutral, ... 15M=0.0000(rsi_1h_direction_block/-, raw=0.00), total=0.0000/0.6800
HOLD归因: reason=rsi_1h_direction_against_veto
```

对应代码链路在 `src/fund_flow/macd_strategy_v2.py`：

- `trade_direction is None` 后进入 `neutral_upgrade_gate`：约 `3644-3654`
- 有候选方向时用 RSI 节奏尝试升级：约 `3655-3699`
- 升级失败直接 `_neutral_signal(reason=neutral_original_reason)`：约 `3708-3732`
- 无候选方向也直接中性信号：约 `3733-3745`

配置上当前主方向设置偏 4H：

```json
"primary_direction_timeframe": "4h",
"require_1h_confirmation_when_4h_primary": true,
"allow_neutral_1h_confirmation": true,
"light_1h_confirmation_when_4h_primary": true,
"enable_neutral_upgrade": true,
"neutral_upgrade_min_rsi_score": 0.35,
"neutral_upgrade_probe_rsi_score": 0.2,
"neutral_upgrade_probe_threshold_score": 0.82,
"neutral_upgrade_penalty_mult": 0.9
```

解释：策略虽然打开了 `neutral_upgrade`，但实际日志显示大量候选仍停在 `neutral_upgrade_gate/mode`，说明升级条件对当前行情仍偏保守，尤其在 4H 主方向不明确、1H/15M 节奏未同步时。

## 分数门槛不是第一主因

最终阈值配置：

```json
"entry_thresholds": {
  "default": 0.68,
  "red_bar_growing": 0.68,
  "green_bar_growing": 0.69,
  "flip_bearish": 0.66,
  "flip_bullish": 0.64
}
```

窗口内只有 `178/1875 = 9.5%` 的 HOLD 到达 `threshold_check` 后因为分数不足失败。

这些 `threshold_check` 的分布：

| 距离阈值 | 次数 |
|---|---:|
| 差距 `<= 0.05` | 11 |
| 差距 `0.05 - 0.15` | 14 |
| 差距 `> 0.15` | 153 |

接近阈值的代表：

| UTC 时间 | Symbol | score/threshold | gap | threshold source |
|---|---|---:|---:|---|
| 2026-05-13 00:00 | ZECUSDT | 0.6584 / 0.66 | 0.0016 | preflip_trial |
| 2026-05-12 15:15 | BTCUSDT | 0.6811 / 0.69 | 0.0089 | primary_4h_green_bar_growing |
| 2026-05-12 23:15 | ADAUSDT | 0.6635 / 0.69 | 0.0265 | primary_4h_green_bar_growing |
| 2026-05-12 23:30 | SUIUSDT | 0.6605 / 0.69 | 0.0295 | primary_4h_green_bar_growing |

结论：如果只把最终阈值整体下调，理论上最多释放少数接近阈值候选，但解决不了 `4H无明确方向`、`rsi_1h_direction_against_veto`、`vwap_hard_block` 这三类主拦截。

## VWAP 硬否决是重要次主因

窗口内 `vwap_hard_block` 出现 `360` 次，占 HOLD `19.2%`。配置中：

```json
"vwap_deviation_hard_block": 0.03
```

代码在 `src/fund_flow/macd_strategy_v2.py` 约 `3893-3905`：

```python
if vwap_veto == VetoType.VWAP_HARD_BLOCK:
    return self._neutral_signal(reason='vwap_hard_block', ...)
```

这属于硬否决，不会进入最终阈值竞争。日志里不少标的在 `primary=4H` 有潜在方向，但由于偏离 VWAP 超限直接归零。

## min_open_portion 是次要但真实的开仓门槛

窗口内发现 `10` 次 `ENTRY_GATE_BLOCK`：

```text
gate=min_open_portion
reason=target_below_min_open
threshold=0.06
```

涉及：

| Symbol | 次数 |
|---|---:|
| ZECUSDT | 4 |
| ATOMUSDT | 2 |
| ETHUSDT | 1 |
| ALGOUSDT | 1 |
| DOGEUSDT | 1 |
| SOLUSDT | 1 |

典型样例：

| UTC 时间 | Symbol | side | target | min_open | signal_score | signal_threshold |
|---|---|---|---:|---:|---:|---:|
| 2026-05-12 14:45 | ALGOUSDT | LONG | 0.042 | 0.06 | 0.8365 | 0.66 |
| 2026-05-13 00:30 | ZECUSDT | LONG | 0.042 | 0.06 | 0.7224 | 0.66 |
| 2026-05-13 02:30 | ZECUSDT | LONG | 0.042 | 0.06 | 0.6838 | 0.66 |
| 2026-05-12 23:30 | SOLUSDT | SHORT | 0.005 | 0.06 | 0.7857 | 0.69 |

配置：

```json
"min_open_portion": 0.06,
"probe_floor_rescue": {
  "enabled": true,
  "shadow_mode": true,
  "min_score_threshold": 0.8,
  "probe_portion": 0.06,
  "probe_leverage_cap": 2
}
```

关键点：`probe_floor_rescue` 当前是 `shadow_mode=true`，所以即使 ALGOUSDT 这种 `signal_score=0.8365` 且标记 `eligible` 的候选，也只是记录 shadow，不会真的把 `target=0.042` 提升到 `0.06` 下单。

代码位置：

- `src/app/fund_flow_bot.py` 约 `3038-3118`：`_apply_probe_floor_rescue`
- `src/app/fund_flow_bot.py` 约 `9015-9043`：小于 `min_open_portion` 时记录 `ENTRY_GATE_BLOCK` 并跳过

结论：`min_open_portion` 确实减少了少量开仓，但只有 `10` 次，不是开仓少的第一主因。若希望增加试探单数量，可以优先评审 `probe_floor_rescue.shadow_mode` 是否应关闭，或者设置更小的 probe 专用最小下单比例，但这会直接改变风险暴露行为。

## 非主因排除

### 不是 API 或调度问题

证据：

- `api_cycle_stats_utc.jsonl` 在窗口内持续输出。
- `processed` 主要为 `28/29`。
- `allow_new_entries=True` 占 `66/67`。
- runtime 每 15 分钟稳定打印 `本轮扫描完成`。

### 不是完全没有交易信号

证据：

- 有 `4` 次非 HOLD 策略决策。
- 有 `10` 次 final 后被 `min_open_portion` 拦截的候选。
- 有若干 `threshold_check` 接近通过，例如 ZECUSDT `0.6584/0.66`。

问题是多数候选没有走到 final，而是在前置方向/节奏/结构门控中归零。

### 不是单一白名单问题

窗口内存在 `41` 次 execution error，典型信息包括配置外持仓 `BTCUSDT` 白名单校验失败。但这主要影响已有/配置外 BTC 相关处理，不解释全局开仓少。主决策层仍然是 `1875/1879` HOLD。

## 建议 Claude 重点评审的问题

1. 当前 `primary_direction_timeframe=4h` + `require_1h_confirmation_when_4h_primary=true` 的组合是否过度延迟新趋势/反转早期入场？
2. `neutral_upgrade` 的设计是否达成目标？日志显示大量候选停在 `neutral_upgrade_gate/mode`，是否应该放宽 `neutral_upgrade_min_rsi_score`、降低 probe 条件，或者给 `4H shrinking + 1H growing` 单独路径？
3. `rsi_1h_direction_against_veto` 是否过硬？它在窗口内有 `362` 次，占 HOLD `19.3%`，可能错过 1H 尚未确认但 15M 已转强/转弱的机会。
4. `vwap_deviation_hard_block=3%` 对高波动标的是否过硬？是否应该区分趋势延伸与追高追空风险，而不是统一硬否决？
5. `probe_floor_rescue.shadow_mode=true` 是否符合最新策略目标？当前它证明有候选可救，但不会实际开仓。
6. 若目标是提高开仓数量，优先级应是方向/节奏门控评审，其次才是最终分数阈值和 `min_open_portion`。

## 建议的调整优先级

不建议第一步直接大幅降低 `entry_thresholds.default`。更合理的顺序：

1. 先决定是否允许更多“方向未完全确认但有局部优势”的 probe 单。
2. 若允许，优先评审 `neutral_upgrade` 与 `rsi_1h_direction_*_veto` 的放行条件。
3. 再评审 `probe_floor_rescue.shadow_mode` 是否转 live，避免高分但小 target 候选被 `min_open_portion` 丢掉。
4. 最后才微调 `entry_thresholds`，因为当前只有约一成 HOLD 真正死在最终阈值。

一句话判断：当前策略像是“宁可错过，不愿早进”的新版本。开仓少主要是方向确认与硬性结构过滤导致的，而不是扫描没跑或单个门槛参数过高。
