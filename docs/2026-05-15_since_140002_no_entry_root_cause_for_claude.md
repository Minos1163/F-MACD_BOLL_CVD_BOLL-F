# 2026-05-15 14:00:02 UTC 后未成交开仓归因

## 结论

从 `2026-05-15 14:00:02 UTC` 起，到本地已有 attribution 覆盖的 `2026-05-16 01:45:14 UTC`，没有实际成交开仓。

主因不是交易权限关闭，也不是交易所拒单。链路表现为：

1. 大多数标的在策略层被 HOLD，主要堵在 `vwap_hard_block`、`4H无明确方向`、以及低分/RSI 类前置门控。
2. 有 2 个开仓候选通过策略并提交 IOC 限价单，但 `executedQty=0`，成交 CSV 中该窗口后 0 笔 fill。
3. `runtime.out.*.log` 后续缺失是配置导致：`logging.runtime_file_enabled=false` 关闭了文件镜像。已恢复为 `true`。

## 证据范围

- 起点：`2026-05-15 14:00:02 UTC`
- attribution 记录范围：`2026-05-15 14:00:04 UTC` 到 `2026-05-16 01:45:14 UTC`
- 文件：
  - `logs/2026-05/2026-05-15/fund_flow_attribution.jsonl.gz`
  - `logs/2026-05/2026-05-16/fund_flow_attribution.jsonl`
  - `logs/2026-05/2026-05-15/runtime.out.18.log`
  - `logs/2026-05/2026-05-15/trade_fills_utc.csv`

## 量化统计

attribution after start:

| 指标 | 数量 |
|---|---:|
| total records | 2724 |
| decision events | 1362 |
| execution events | 1362 |
| HOLD decisions | 1360 |
| SELL candidates | 2 |
| BUY candidates | 0 |
| noop executions | 1360 |
| pending executions | 2 |
| fills after start | 0 |

decision reason Top:

| reason | count |
|---|---:|
| `macd_v2_hold_none_score_0.00` | 650 |
| `macd_v2_hold_vwap_hard_block_score_0.00` | 583 |
| `macd_v2_hold_vwap_score_filter_score_0.00` | 23 |
| `macd_v2_hold_none_score_0.24` | 23 |
| `macd_v2_hold_none_score_0.38` | 14 |

signal_score buckets:

| bucket | count |
|---|---:|
| `0` | 1241 |
| `0-0.68` | 90 |
| missing | 27 |
| `0.68-0.80` | 4 |
| `>=0.80` | 0 in attribution decisions |

## 14:00 UTC 首轮 runtime 细节

`runtime.out.18.log` 中 `cycle 2 @ 2026-05-15 14:00:03 UTC`：

- runtime decisions parsed: `HOLD=27`
- hold codes:
  - `vwap_hard_block`: 24
  - `4H无明确方向`: 2
  - `green_bar_growing_short_adx_1h_range_filter`: 1
- entry gate block:
  - `XRPUSDT` SHORT
  - `gate=min_open_portion`
  - `target=0.000394 < min_open=0.06`
  - `signal_score=0.8161`
  - `probe_floor_rescue.shadow_mode=true`, so eligible probe did not become live order.

样例：

```text
ENTRY_GATE_BLOCK XRPUSDT SHORT min_open_portion target=0.000394 threshold=0.06 signal_score=0.8161
```

## 唯二开仓候选为什么没成交

`2026-05-15 20:30:14 UTC` 有两个 SELL 候选：

| UTC | symbol | side | target | score | order status | executedQty |
|---|---|---|---:|---:|---|---:|
| 2026-05-15 20:30:14 | AVAXUSDT | SELL | 0.0867 | 0.715540 | NEW IOC LIMIT | 0 |
| 2026-05-15 20:30:14 | RENDERUSDT | SELL | 0.0867 | 0.715445 | NEW IOC LIMIT | 0 |

执行结果均为：

```text
status=pending, message=开仓委托已提交，待成交（非失败）, timeInForce=IOC, executedQty=0
```

随后 `trade_fills_utc.csv` 在该分析窗口内没有任何成交记录。因此这两个不是权限失败，而是限价 IOC 未成交。

## 配置/日志问题

当时 `runtime.out.*.log` 后续缺失的直接原因是当前配置曾包含：

```json
"logging": {
  "runtime_file_enabled": false,
  "api_cycle_stats_enabled": false
}
```

这会让 `_configure_runtime_log_sink()` 直接 return，不再创建 `runtime.out.*.log` 和 `runtime.err.*.log` 文件镜像。`logs/2026-05/2026-05-16/` 也确实没有 runtime 文件，只剩 attribution 与 risk state。

已改回：

```json
"logging": {
  "runtime_file_enabled": true,
  "api_cycle_stats_enabled": false
}
```

并同步更新 `scripts/verify_deployment.py`：部署校验现在要求 `runtime_file_enabled=true`，仍要求 `api_cycle_stats_enabled=false` 和 `market_storage_enabled=false`，保留 runtime 但不恢复更重的日志/数据库输出。

## 给 Claude 的问题

1. 是否认可“未开仓”第一归因是策略门控和订单未成交，而不是权限/执行层拒绝？
2. `vwap_hard_block` 在 14:00 首轮占 24/27，是否应从 hard block 改为 probe/penalty，或扩大 ATR normalized 的 live 放行范围？
3. `probe_floor_rescue.shadow_mode=true` 使 `XRPUSDT signal_score=0.8161` 仍被 `min_open_portion=0.06` 拦下。是否应该解除 shadow，或把 live probe 下限设为可成交的 0.042/0.06？
4. 两个通过策略的 IOC LIMIT 全部 `executedQty=0`。是否应对开仓单使用更宽的 slippage、二次 retry，或改为 market/limit-maker 分支？
