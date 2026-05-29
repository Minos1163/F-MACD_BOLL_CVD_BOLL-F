# 2026-05-14 14:00-19:00 新策略无开仓根因分析包

## 结论摘要

分析窗口：北京时间 `2026-05-14 14:00` 至 `2026-05-14 19:00`，即 UTC `2026-05-14 06:00` 至 `2026-05-14 11:00`。日志目录：

- `logs/2026-05/2026-05-14/runtime.out.12.log`
- `logs/2026-05/2026-05-14/runtime.out.18.log`
- `logs/2026-05/2026-05-14/fund_flow_attribution.jsonl`
- `logs/2026-05/2026-05-14/api_cycle_stats_utc.jsonl`

核心结论：这 5 小时没有开仓，不是 API、调度、min-open、probe_floor_rescue 或最终 threshold 的问题。关键 BUG 是：**我们想消融的最大门槛是 `4H shrinking + 1H confirm` 这类早期方向，但代码里根本没有实现 MACD V2 的 partial-confirm 路径；现有 neutral_upgrade 仍只依赖 RSI raw_score/hard_veto，所以大量候选继续在 `neutral_upgrade_gate/mode` 被归零。**

另一个观测 BUG：`CONFIG_FINGERPRINT` 的 `neutral_upg_rsi` 字段读取路径错了，日志显示 `neutral_upg_rsi=0.0`，但真实配置在 `entry_filters.neutral_upgrade_min_rsi_score=0.35`。这会误导部署判断，但不是无开仓的直接原因。

## 部署与运行状态

配置指纹已经出现，说明这段日志确实来自重启后的新策略：

```text
[CONFIG_FINGERPRINT] hash=c4d84105 | config_path=/root/AIBOT/config/trading_config_fund_flow.json | probe_shadow=False | probe_min_open=0.042 | weight_rsi=0.3 | weight_4h=0.4 | weight_4h_enh=0.1 | vwap_gate_mode=atr_normalized | vwap_hard_block=0.0 | vwap_block_atr_multiplier=4.0 | vwap_probe_max_portion=0.06 | neutral_upg_rsi=0.0 | exit_guard=True | exit_guard_bars=2 | shrink_cap_1h=True
```

窗口内 `api_cycle_stats_utc.jsonl`：

| 项目 | 数值 |
|---|---:|
| cycle 数 | 21 |
| allow_new_entries=True | 20 |
| ingestion_only=True | 1 |
| 每轮处理标的 | 28/28 |
| API 状态 | 正常，主要 200 |

窗口内 `fund_flow_attribution.jsonl`：

| 类型 | 次数 |
|---|---:|
| HOLD decision | 553 |
| BUY | 0 |
| SELL | 0 |
| CLOSE | 0 |
| execution noop | 553 |

结论：调度与扫描正常，策略层没有输出任何开仓决策。

## HOLD 漏斗统计

按 runtime `HOLD归因` 统计，窗口内主要 HOLD 原因：

| 排名 | HOLD code/reason | 次数 | 占比 |
|---:|---|---:|---:|
| 1 | `4H无明确方向` | 387 | 70.4% |
| 2 | `信号评分低于阈值` | 102 | 18.5% |
| 3 | `rsi_1h_direction_against_veto` | 34 | 6.2% |
| 4 | `vwap_score_filter` | 8 | 1.5% |
| 5 | `vwap_hard_block` | 8 | 1.5% |
| 6 | `rsi_15m_extreme_veto` | 5 | 0.9% |
| 7 | `flip_bullish_sniper_no_trend_alignment` | 4 | 0.7% |
| 8 | `rsi_1h_direction_flat_veto` | 2 | 0.4% |

按 `stage` 统计：

| stage | 次数 | 含义 |
|---|---:|---|
| `neutral_upgrade_mode` | 200 | 有候选方向但 neutral_upgrade 未通过，直接 HOLD |
| `neutral_upgrade_gate` | 187 | 无可用主方向/无候选升级方向，直接 HOLD |
| `threshold_check` | 102 | 进入最终分数检查但分数不足 |
| `rsi_rhythm` | 41 | RSI 节奏 hard veto |
| `vwap_score_filter` | 8 | VWAP 分数过滤 |
| `vwap` | 8 | VWAP hard block |

结论：新策略消融后仍没有开仓，主因仍是上游方向门控。`threshold_check` 只占 18.5%，而且没有任何候选接近阈值。

## 关键 BUG 1：partial-confirm 没有落地

窗口内 `4H shrinking + 1H confirm` 组合非常多：

| 4H signal | 1H signal | 次数 | 应有解释 |
|---|---|---:|---|
| `green_bar_shrinking` | `red_bar_growing` | 187 | 4H 下跌动能收缩 + 1H 反弹，多头 partial-confirm 候选 |
| `green_bar_shrinking` | `red_bar_shrinking` | 145 | 4H 收缩 + 1H 仍弱，谨慎观察合理 |
| `green_bar_shrinking` | `green_bar_shrinking` | 42 | 空头延续/收缩，谨慎观察合理 |
| `green_bar_shrinking` | `flip_bullish` | 5 | 更强的多头 partial-confirm 候选 |
| `red_bar_shrinking` | `flip_bearish` | 4 | 4H 上涨动能收缩 + 1H 转空，空头 partial-confirm 候选 |
| `red_bar_shrinking` | `green_bar_growing` | 4 | 空头 partial-confirm 候选 |

`partial_confirm` 在日志中出现次数：`0`。

典型样例：

```text
HYPEUSDT 2026-05-14 14:00 BJ
MACD_V2评分: stage=neutral_upgrade_mode, primary=4H:0.0000(green_bar_shrinking), 1H=0.0000(red_bar_growing), total=0.0000/0.6800
HOLD归因: stage=neutral_upgrade_mode, reason=4H无明确方向
```

类似样例在 14:00 同一轮出现于 `HYPEUSDT/XRPUSDT/SOLUSDT/BCHUSDT/XLMUSDT/AVAXUSDT/ZECUSDT/AAVEUSDT` 等多个标的。

### 代码证据

`src/fund_flow/macd_strategy_v2.py` 的 neutral 逻辑在约 `3735-3850`：

1. `resolve_primary_direction()` 在 `direction_4h is None` 时返回 `None, "4H无明确方向"`。
2. 随后进入 `if trade_direction is None`。
3. `neutral_upgrade_candidate = next((d for d in (direction_4h, direction_1h) if d in {"long", "short"}), None)`。
4. `_evaluate_neutral_upgrade()` 只接受 `neutral_upgrade_candidate + neutral_upgrade_raw + hard_veto`。
5. `_evaluate_neutral_upgrade()` 的判断只看：
   - `neutral_upgrade_raw >= neutral_upgrade_min_rsi_score`
   - 或 `neutral_upgrade_raw >= neutral_upgrade_probe_rsi_score`
   - 或 hard_veto 直接 reject。

代码里没有任何逻辑处理：

```text
4H green_bar_shrinking + 1H red_bar_growing => long probe
4H green_bar_shrinking + 1H flip_bullish => long probe
4H red_bar_shrinking + 1H green_bar_growing/flip_bearish => short probe
```

所以我们之前讨论的 `partial_confirm_path` 并没有在 MACD V2 方向门控中落地。配置文件里其他模块有 `trend_capture.partial_confirm_enabled`，但那是 trend_capture 路径，不是 MACD V2 neutral_upgrade 路径，不能承接这里的 `neutral_upgrade_gate/mode`。

## 关键 BUG 2：fingerprint 读取 neutral_upgrade 路径错误

日志指纹显示：

```text
neutral_upg_rsi=0.0
```

但真实配置位于：

```json
"entry_filters": {
  "enable_neutral_upgrade": true,
  "neutral_upgrade_min_rsi_score": 0.35,
  "neutral_upgrade_probe_rsi_score": 0.2,
  "neutral_upgrade_probe_threshold_score": 0.82,
  "neutral_upgrade_penalty_mult": 0.9
}
```

`src/app/fund_flow_bot.py` 约 `367-390`：

```python
neutral = v2_cfg.get("neutral_upgrade", {})
"neutral_upg_rsi": self._to_float(neutral.get("neutral_upgrade_min_rsi_score"), 0.0)
```

这条路径是错的。应该读：

```python
entry_filters = v2_cfg.get("entry_filters", {})
entry_filters.get("neutral_upgrade_min_rsi_score")
```

影响：运维会以为 neutral upgrade 已降到 0 或缺失，实际运行仍然是 `0.35/0.20/0.82`。这会继续制造“配置到底有没有生效”的歧义。

## VWAP ATR gate 不是本窗口不开仓主因

本窗口 `vwap_hard_block` 只有 8 次，占 HOLD 约 1.5%。而 `4H无明确方向` 是 387 次，占 70.4%。

VWAP hard block 样例：

| 时间 BJ | Symbol | dev | ATR pct | dev/ATR 估算 | 判断 |
|---|---|---:|---:|---:|---|
| 15:15 | POLUSDT | -6.22% | 0.85% | 7.3x | 仍应 hard block |
| 15:30 | POLUSDT | -6.18% | 0.86% | 7.2x | 仍应 hard block |
| 16:00 | SUIUSDT | -5.30% | 1.06% | 5.0x | 仍应 hard block |
| 17:45 | AVAXUSDT | -3.31% | 0.74% | 4.5x | 仍应 hard block |
| 18:00 | AVAXUSDT | -3.16% | 0.69% | 4.6x | 仍应 hard block |

结论：ATR normalized VWAP gate 在这 5 小时没有产生大量释放空间。继续调 VWAP 不会解决本窗口无开仓问题。

## threshold 也不是第一主因

`threshold_check` 有 102 次，但没有一个 gap 小于 0.10。最高分样例：

| 时间 BJ | Symbol | score / threshold | gap | 形态 |
|---|---|---:|---:|---|
| 16:45 | ATOMUSDT | 0.5651 / 0.69 | 0.1249 | 4H green growing，但 1H green shrinking |
| 16:15 | ATOMUSDT | 0.5647 / 0.69 | 0.1253 | 同上 |
| 16:00 | ATOMUSDT | 0.5645 / 0.69 | 0.1255 | 同上 |
| 14:00 | ADAUSDT | 0.5265 / 0.68 | 0.1535 | 4H shrink + 1H red growing |
| 18:00 | TRUMPUSDT | 0.4673 / 0.68 | 0.2127 | 4H shrink + 1H red growing |

解释：如果只降阈值到 0.64/0.66，仍然无法释放这些候选；如果降到 0.55 以下，会把很多没有完整方向确认的低质量信号直接放进来，风险过高。正确路径是先修方向候选的打分/路径，而不是硬降阈值。

## 关键 BUG 3：4H shrinking 在主方向分上仍等于 0

大量样例里：

```text
primary=4H:0.0000(green_bar_shrinking)
1H=0.1275(red_bar_growing)
VWAPq≈0.85
VOL=0.033~0.10
total≈0.46~0.53
```

这说明 `green_bar_shrinking` 被当成“无主方向”，4H 主分为 0。即使 1H 已经 `red_bar_growing`，候选也只能靠 1H/VWAP/volume 凑分，通常停在 0.46~0.53。

如果 partial-confirm 设计目标是“4H 动能收缩 + 1H 已确认 = 小仓早期 probe”，那么必须给这类路径：

1. 明确方向：`long` 或 `short`。
2. 小额方向分/bonus，而不是 4H 分恒为 0。
3. 独立阈值或 probe 阈值，而不是继续用默认 `0.68/0.69`。
4. 仓位封顶，例如 `max_portion=0.06~0.10`。

否则它最多进入 `threshold_check` 后以 0.46/0.68 被拒，开仓数量不会增加。

## 对“增加开仓/消融门槛”的判断

本窗口证明：上次上线的修复主要打通了部署可观测性、ExitGuard 和 VWAP probe cap，但没有触及本窗口最大漏斗。`4H无明确方向` 比例从之前高位继续维持在 70% 左右，说明真正的方向门控仍未消融。

需要修的是一个具体代码 BUG/缺失功能，不是再加一堆参数：

```text
在 MACDStrategyV2Engine 的 trade_direction is None 分支里，
在 RSI neutral_upgrade 之前，插入 partial_confirm 解析：

if signal_4h in {green_bar_shrinking, red_bar_shrinking}
   and signal_1h in directional confirm set:
       trade_direction = inferred side
       neutral_upgrade_applied = True
       neutral_upgrade_mode = "partial_confirm"
       neutral_upgrade_penalty_mult = 0.85
       neutral_upgrade_threshold_override = 0.58~0.62  # 需要回测确认
       max_portion_override = 0.06~0.10
       continue scoring, not neutral_signal
```

最低限度应该先 shadow/log：

```text
partial_confirm_candidate=true
partial_confirm_side=long/short
partial_confirm_reason=4h_shrink_1h_confirm
would_score_before_threshold=...
would_target_portion=...
```

这样 12 小时后可以直接评估该路径胜率与潜在成交数。

## 建议 Claude 重点评审的问题

1. 是否同意本窗口的最大 bug 是 partial-confirm 未落地，而不是 VWAP、min-open 或 threshold？
2. `green_bar_shrinking + red_bar_growing` 是否应定义为 long partial-confirm？如果不是，当前策略在 4H shrinking 大行情下就天然不会开仓。
3. partial-confirm 应该走独立阈值，还是只给 score_bonus？本窗口数据看，仅 score_bonus 0.02 不够，很多候选只有 0.46~0.53。
4. partial-confirm 是否应跳过 RSI hard veto，还是 RSI hard veto 只作为仓位压缩？本窗口 `rsi_1h_direction_against_veto` 只有 34 次，不是最大主因，但会影响 ATOM/JST 这类候选。
5. fingerprint 的 neutral 路径是否必须立即修正？建议必须修，否则继续误导部署判断。
6. 是否需要把 `neutral_upgrade_min_rsi_score/probe_rsi_score/threshold_override` 加入 runtime 评分日志，而不是只在 debug details 内部存在？

## 建议优先级

P0：修 `CONFIG_FINGERPRINT.neutral_upg_rsi` 读取路径，改为读取 `entry_filters`。这是观测修复。

P0：在 MACD V2 `trade_direction is None` 分支加入 partial-confirm candidate shadow 日志，至少先统计 would-pass 数量。

P1：实装 partial-confirm live，但必须小仓：`max_portion=0.06~0.10`，并单独标记 `neutral_upgrade_mode=partial_confirm`。

P1：给 partial-confirm 独立 threshold 或 score floor。仅加 `score_bonus=0.02` 不够，本窗口代表候选分数多数在 `0.46~0.53`。

P2：再评估 `rsi_1h_direction_against_veto` soft penalty。它本窗口只占 6.2%，不是本轮无开仓核心。

P3：不要继续优先调 VWAP ATR。本窗口 VWAP hard block 只有 8 次，且大多 dev/ATR > 4，按规则本来就该 block。

一句话结论：**我们一直在修 min-open、VWAP、ExitGuard，但本窗口 70% 的候选死在 partial-confirm 缺失导致的 `4H无明确方向`。要增加开仓，必须把 4H shrinking + 1H confirm 从“无方向”变成“可控小仓 probe”，否则继续等 12H 也只是在重复收集同一个瓶颈。**
