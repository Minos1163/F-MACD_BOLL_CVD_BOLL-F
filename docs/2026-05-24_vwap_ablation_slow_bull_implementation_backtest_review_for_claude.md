# 2026-05-24 VWAP 消融 + 慢牛修复实施与回测复盘

## 结论

本次实现已完成计划中的工程项：开平仓详单 JSONL 日志、0.1U 微仓阻断、VWAP 对 entry 完全消融、三模式慢牛 detector、continuation long 路径、slow bull short guard 仅在 SHORT 分支生效，以及部署断言更新。

但慢牛窗口收益验收未通过：北京时间 2026-05-23 17:00 后，回测开出了 70 笔多仓，涨幅前 10 标的覆盖 7/10，交易数量和覆盖率达标；窗口收益为 -0.2887%，未达到 +7%。不要把这次策略当作盈利版本上线，当前版本只能说明“VWAP 阻断和慢牛未触发的问题被修掉了”，不能说明 continuation entry 有正期望。

## 实施内容

### 1. 开平仓详单日志

在 `src/app/fund_flow_bot.py` 增加结构化 JSONL 审计日志：

- 文件名：`fund_flow_entry_exit_audit.jsonl`
- 开仓前/执行后记录 BUY/SELL 的 symbol、方向、target、leverage、估算 notional、策略来源、signal score、1H/4H/15M 信号、gate action/reason、metadata。
- CLOSE/REDUCE 记录触发来源、平仓比例、持仓时长、MFE/MAE、开仓来源摘要、执行/拒单信息。
- 保留现有 attribution，不替换，只新增复盘用详单。

### 2. 微仓阻断

在实盘执行入口增加 `min_entry_notional_usdt=0.10` 硬阻断：

- BUY/SELL 开仓若 `target_portion_of_balance * account_equity < 0.10`，直接 HOLD。
- CLOSE/REDUCE 不受该阻断影响，避免小仓无法退出。
- 阻断 metadata 写入 `micro_notional_block`，包含 target、equity、estimated_notional、threshold。
- 在 AI review 后最终执行前再次 revalidation，防止缩放后产生 0.1U 以下微仓。

### 3. VWAP 完全消融

已禁用/移除 entry 路径里的 VWAP veto/cap：

- `vwap_score_filter` 不再 HOLD。
- `entry_quality_gates.vwap_score_hard_block.enabled=false`。
- `vwap_deviation_gate.enabled=false`，mode 为 `observation_only`。
- `weight_vwap=0.0`。
- BTC entry regime gate 不再用 `vwap_score` 决定 block/probe。
- backtest 和 live config builder 中 VWAP hard block 默认改为 `0.0`。
- VWAP 只作为日志字段保留，用于事后分析。

### 4. 慢牛 detector + continuation long

`MarketBreadthDetector.detect()` 改为三模式，任一满足且连续确认后进入 slow bull：

- `alt_breadth_led`: breadth >= 0.80，alt median 60M >= 0.25%，BTC 30M >= -0.10%。
- `btc_led`: BTC 30M >= 0.20%，breadth >= 0.60，alt median 60M >= 0.30%。
- `extreme_breadth`: breadth >= 0.90，alt median 60M >= 0.10%。

Continuation long 在 slow bull 中按单币 30M/60M 动量、RSI、EMA、BTC not down 判断，开极小 probe。未触发时打印 `[SLOW_BULL_HOLD]`，触发时打印 `[SLOW_BULL_CANDIDATE]`。

### 5. 回测框架修复

发现原 strict-live 回测有一个验收偏差：先把数据裁到 `--start` 之后，再要求 `idx_15m >= 50`，导致北京时间 2026-05-23 17:00 起的前 12.5 小时完全不能交易。

已修复为：

- 保留 start 前 60 根 15M 作为 warmup。
- warmup bars 只用于指标、breadth、状态预热。
- 交易、统计、equity curve 只在 `window_start_iso <= current_ts <= window_end_iso` 内发生。

这不是调参，是让 backtest 与 live “已有历史状态后开始执行”的假设一致。

## 验证命令

```bash
python -m pytest tests/test_market_breadth.py tests/test_btc_entry_regime.py tests/test_btc_entry_regime_integration.py tests/test_fund_flow_bot_dual_leg_guard.py tests/test_pre_live_assertions.py tests/test_verify_deployment_config.py tests/test_macd_v2_position_sizing.py tests/test_backtest_review_followup.py::test_time_range_filter_can_preserve_start_history_for_strict_live_warmup -q
```

结果：`88 passed`

```bash
python scripts/pre_live_assertions.py --config config/trading_config_fund_flow.json
python scripts/verify_deployment.py --config config/trading_config_fund_flow.json
python -m py_compile src/app/fund_flow_bot.py src/fund_flow/market_breadth.py src/fund_flow/btc_entry_regime.py src/fund_flow/decision_engine.py src/fund_flow/macd_strategy_v2.py scripts/backtest_macd_v2.py scripts/pre_live_assertions.py scripts/verify_deployment.py
```

结果：全部 exit 0。

## 慢牛窗口回测

命令：

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2026-05-23T09:00:00 --end 2026-05-24T13:30:00 --output-prefix output/backtest/20260523_1700_slow_bull_vwap_ablation
```

窗口：

- 北京时间：2026-05-23 17:00 到 2026-05-24 21:30
- UTC：2026-05-23T09:00:00 到 2026-05-24T13:30:00
- 数据：28/28 symbols available
- 时间轴：175 个 15M 点
- 假设：strict live mode，entry slippage 0.15%，fee rate 0.04%，IOC，simulate live close layers。

指标：

| 指标 | 结果 |
|---|---:|
| total return | -0.2887% |
| final capital | 9971.13 |
| total trades | 70 |
| long trades | 70 |
| win rate | 54.29% |
| profit factor | 0.6009 |
| max drawdown | 0.4863% |
| expectancy | -0.3203 USDT/trade |
| exposure 近似 | 79.21% equity points active |
| orders submitted | 60 |
| orders filled | 51 |
| orders canceled | 9 |
| candidate entries | 439 |
| signals generated | 593 |
| Sharpe | 未输出 |
| MFE/MAE | 当前 trades CSV 未输出 |
| tail risk | worst 5 pnl = -4.12, -3.84, -3.36, -3.32, -3.11 USDT |

验收对照：

| 验收项 | 要求 | 实际 | 结论 |
|---|---:|---:|---|
| 多仓数量 | >=20 | 70 | 通过 |
| 窗口收益 | >=7% | -0.2887% | 失败 |
| 涨幅前 10 多仓覆盖 | >=5/10 | 7/10 | 通过 |
| VWAP hard block | 0 | 回测 veto 中无 VWAP block | 通过 |

涨幅前 10 覆盖：

| symbol | 窗口涨幅 | 有多仓 |
|---|---:|---|
| WLDUSDT | 17.93% | 是 |
| MORPHOUSDT | 15.36% | 是 |
| HYPEUSDT | 14.51% | 是 |
| ONDOUSDT | 14.01% | 是 |
| ZECUSDT | 11.30% | 是 |
| RENDERUSDT | 10.11% | 是 |
| FETUSDT | 9.05% | 是 |
| PUMPUSDT | 7.58% | 否 |
| JUPUSDT | 7.03% | 否 |
| TAOUSDT | 7.03% | 否 |

## 亏损归因

### 1. 入口数量修好了，但 entry 质量没有修好

warmup 修复后，交易数从上一轮 17 增加到 70，说明 detector/continuation 能触发，也能覆盖强势币。但 PnL 仍为负，说明之前“没买到慢牛”只是问题之一，不是全部根因。

### 2. 盈亏比结构是负的

本窗口胜率 54.29%，但 profit factor 只有 0.6009：

- 平均盈利：0.8882 USDT
- 平均亏损：-1.7553 USDT
- expectancy：-0.3203 USDT/trade

胜率过半仍亏钱，说明轻止盈/止损组合让盈利被切得太小，亏损单的尾部更大。

### 3. 退出原因显示 stop_loss_intrabar 仍是最大亏损来源

退出原因：

- `stop_loss_intrabar`: 38
- `sim_light_take_profit`: 19
- `take_profit_intrabar`: 11
- `stop_loss_intrabar_both_hit`: 2

最差亏损集中在 FET、MORPHO、WLD、ONDO、HYPE，很多是入场后 15M 内被止损。这说明 continuation 经常在局部拉升后追入，遇到正常回踩就被打掉。

### 4. 容量竞争仍在丢弃候选

执行漏斗：

- candidate entries: 439
- orders submitted: 60
- orders filled: 51
- capacity competition dropped: 233
- entry_cooldown reject: 93
- ioc_no_fill: 9

当前 continuation 的排序分几乎统一为 0.60，导致容量竞争时无法优先选择“最强且最不容易回撤”的币。强势覆盖虽然达到 7/10，但仓位分配与入场时间仍不够好。

### 5. 回测仍缺 MFE/MAE 字段，无法精确判断“早止盈 vs 早止损”

当前 summary/trades 没有 Sharpe 和 MFE/MAE。需要在 backtest trades 中补充 MFE/MAE，才能判断这些亏损单是：

- 入场后从未给过优势；
- 给过优势但 light TP/exit 管理不合理；
- 正常趋势回踩被 0.5% stop 过早洗出；
- 还是 intrabar 同 bar 假设造成的悲观/乐观偏差。

## 给 Claude 的重点审阅问题

1. VWAP 消融是否彻底：entry 中是否还有任何 VWAP veto/cap/score 影响方向、准入、仓位或 BTC regime gate？
2. strict-live 回测的 warmup 修复是否正确：start 前历史只用于指标预热，不允许 start 前交易/统计，是否仍有 lookahead 风险？
3. continuation long 的排序是否应该从固定 0.60 改为动量质量排序：ret30/ret60、RSI 位置、EMA slope、breadth mode、BTC not down、近期回撤幅度。
4. 是否应先补 MFE/MAE 与 Sharpe，再讨论止盈止损调整；当前不建议直接堆参数追求 +7%。
5. 是否需要把 `sim_light_take_profit` 与 `stop_loss_intrabar` 的同 bar 顺序和手续费/slippage 再审一遍，避免回测执行假设和实盘不一致。

## 下一步建议

不要为了达到 +7% 继续加参数。下一步应先做两个低风险研究改动：

1. 在 trades CSV 中补 MFE/MAE、entry 后前 2/4/8 根 15M 的最大回撤/最大浮盈。
2. 用这些字段复盘 continuation 亏损单，判断应改 entry timing、candidate ranking，还是 exit/payoff 结构。

只有在确认亏损来自可执行且稳定的模式后，再改策略规则。
