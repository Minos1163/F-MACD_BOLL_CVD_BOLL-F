# 最近 7 天实盘亏损归因与开仓链路审计（给 DeepSeek 评审）

日期：2026-05-26  
范围：`D:\AIDCA\AI2\logs\2026-05\2026-05-20` 至 `2026-05-26`  
目的：解释最近七天持续亏损的主要来源，并把实盘开仓方向、链路、门槛分数、权重评分、风控逻辑展开，供 DeepSeek 评审。

---

## 0. 统计口径与限制

1. `trade_fills_utc.csv` 不是严格日增量文件，后续日期文件会包含历史成交。本文合并 7 天目录后，按 `订单ID + 成交ID` 去重，并按真实 `时间(UTC)` 过滤到 `2026-05-20 00:00:00` 至 `2026-05-26 23:59:59`。
2. PnL 使用成交 CSV 的 `已实现盈亏` 字段。手续费字段存在 BNB 与 USDT 混合结算，本文先单列，不强行折算。
3. 近 7 天成交与 `fund_flow_attribution.jsonl(.gz)` 按 symbol 与时间近邻匹配时，仍有一部分亏损成交无法匹配到完整 execution reason。这说明旧日志归因链路仍不完整。
4. `fund_flow_entry_exit_audit.jsonl` 只在 2026-05-25/26 后段较完整，因此开仓详单样例主要来自这两天。

---

## 1. 总览结论

### 1.1 7 天结果

去重后，近 7 天成交 fill 约 779-790 笔，已实现 PnL 合计约 `-6.09 USDT`。按交易账户 100U 量级看，7 天实盘回撤约 6% 级别，且亏损不是单一异常订单造成，而是多个机制叠加：

- 入场方向追随 1H/4H MACD，但在震荡/慢牛切换中方向滞后。
- 出场主要由 `BETA_RISK_CLOSE/REDUCE` 与 `EXIT_SIGNAL_GUARD_CLOSE/REDUCE` 兑现亏损。
- 部分强势行情窗口里，旧 VWAP gate、RSI/1H direction、容量限制、daily loss cooldown 造成错失或延迟。
- 最近上线的 continuation long 虽能开多，但多为 0.02-0.042 小 probe，收益贡献不足以覆盖此前亏损与频繁退出。

### 1.2 每日成交与 PnL

| 日期 | 成交数 | 开仓笔数 | 平仓笔数 | realized PnL(USDT) | 手续费(BNB) | 手续费(USDT) | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-05-20 | 54 | 10 | 25 | -0.6752 | 0.00063495 | 0 | 容量限制明显 |
| 2026-05-21 | 61 | 30 | 31 | -1.8211 | 0.00066819 | 0 | FET/ICP 等亏损集中 |
| 2026-05-22 | 185 | 51 | 124 | -0.0938 | 0.00163253 | 0 | 高频成交但基本打平 |
| 2026-05-23 | 127 | 30 | 76 | +0.0904 | 0.00099428 | 0 | 唯一小幅正收益日之一 |
| 2026-05-24 | 167 | 49 | 102 | -2.8790 | 0.00125901 | 0.29004170 | 最大亏损日，慢牛窗口处理失败 |
| 2026-05-25 | 129 | 40 | 74 | +0.3098 | 0.00000779 | 1.10666497 | PnL 为正但 USDT 手续费很高 |
| 2026-05-26 | 56 | 21 | 35 | -0.9635 | 0.00055703 | 0 | 仍由退出兑现亏损 |

---

## 2. 亏损集中度

### 2.1 按 symbol 的亏损集中

| Symbol | 亏损额(USDT) | 占总亏损比重 | 亏损成交笔数 | 观察 |
|---|---:|---:|---:|---|
| ICPUSDT | -2.0860 | 11.63% | 24 | 多次被举例为强势币，但实际出入场/退出节奏亏损 |
| FETUSDT | -1.4807 | 8.26% | 10 | 单笔 FET 反向信号平仓亏损较大 |
| TRUMPUSDT | -1.3580 | 7.57% | 23 | 碎片化交易与方向切换亏损 |
| ADAUSDT | -1.2230 | 6.82% | 17 | 慢牛多头/普通多头均未形成足够净贡献 |
| SUIUSDT | -1.1082 | 6.18% | 9 | beta fast-fail 单笔亏损明显 |
| DOGEUSDT | -1.0594 | 5.91% | 27 | 交易频繁，净值拖累 |
| SOLUSDT | -0.9886 | 5.51% | 20 | 慢牛窗口多头开出但退出/持仓管理不足 |
| XRPUSDT | -0.9196 | 5.13% | 18 | 方向信号频繁，收益不稳定 |
| PUMPUSDT | -0.8006 | 4.47% | 23 | 小仓/短线碎片化明显 |
| ETCUSDT | -0.7259 | 4.05% | 13 | 反复开平导致亏损累积 |

盈利较好的 symbol：`ATOMUSDT +1.5561`、`XLMUSDT +1.0556`、`BCHUSDT +0.4559`、`POLUSDT +0.4402`、`SUIUSDT +0.3418`（按本地去重统计中正贡献项）。

### 2.2 按成交方向

| 成交方向 | 亏损额(USDT) | 占比 | 亏损成交笔数 | 解释 |
|---|---:|---:|---:|---|
| 卖出 | -11.5255 | 64.29% | 167 | 大量卖出是多单平仓/止损，也包含空单开仓成交；说明多头退出兑现亏损占比较高 |
| 买入 | -6.4032 | 35.71% | 136 | 多为空单平仓/止损，也有多单开仓成交 |

### 2.3 按 exit reason

可匹配归因的亏损主要落在：

| 类别 | 证据 |
|---|---|
| `BETA_RISK_CLOSE` | 典型 reason 包含 `fast_fail(age=2bars,mfe=0.000%,mae=-1.664%)`，说明开仓后 2 根 15M 内未给 MFE，触发 beta/fast-fail 平仓 |
| `BETA_RISK_REDUCE` | 7 天 runtime 中约 240 次 beta reduce 相关日志，频繁半仓/减仓会增加碎片化与手续费压力 |
| `EXIT_SIGNAL_GUARD_CLOSE` | 反向信号确认后 full close，单笔大亏包括 FET `mae=-1.03%` 后 full close |
| 未匹配归因 | 约 81 笔成交未稳定匹配到 execution reason，约 38% 亏损落在 empty/close? 桶，说明审计日志仍需持续完善 |

---

## 3. 最近 7 天主要亏损归因

### 3.1 根因一：趋势入口滞后，震荡/慢牛窗口里容易“买后即反向”

实盘主入口仍以 MACD V2 的 1H/4H 状态为核心：

- 多头常见：`macd_v2_long_1h_red_bar_growing_...`
- 空头常见：`macd_v2_short_1h_green_bar_growing_...`
- 1H 信号分布：`red_bar_growing` 约 131、`green_bar_growing` 约 118、`red_bar_shrinking` 约 51、`green_bar_shrinking` 约 41。
- 大量开仓分数在 0.66-0.80 桶：`0.66-0.70` 约 96，`0.70-0.80` 约 151。

问题：这些信号不是纯早期动量信号，而是 1H/4H 聚合后的状态信号，慢牛早段容易晚，震荡段容易反复。

### 3.2 根因二：出场系统把亏损兑现得很勤，但没有证明“晚一点会更差”

7 天内 close reason 分布：

| Exit 类别 | 次数 |
|---|---:|
| `BETA_RISK_REDUCE` | 187 次 execution close reason 统计；runtime 中 beta reduce 约 240 次 |
| `BETA_RISK_CLOSE` | 96 次 execution close reason 统计；runtime 中 beta close 约 136 次 |
| `EXIT_SIGNAL_GUARD_CLOSE` | 25 次 |
| `RISK_PROTECT` | 12 次 |
| `EXIT_SIGNAL_GUARD_REDUCE` | 9 次 |

典型亏损证据：

- `2026-05-21 10:30:16 FETUSDT`：`EXIT_SIGNAL_GUARD_CLOSE: reverse signal confirmed 6 bars, mae=-1.03%, full close`，单笔 `-0.7425U`。
- `2026-05-23 21:30:15 SUIUSDT`：`BETA_RISK_CLOSE ... fast_fail(age=2bars,mfe=0.000%,mae=-1.664%)`，单笔 `-0.6864U`。
- `2026-05-24 12:30:15 RENDERUSDT`：`BETA_RISK_CLOSE: alt_15m_against(-1.064%) ...`，单笔 `-0.3565U`。

当前日志里 MFE/MAE 后验字段只有 5/25 之后逐步完善；因此还不能证明这些 fast-fail 是“避免更大亏损”，还是“止在起涨前”。这是需要 DeepSeek 特别审阅的关键点。

### 3.3 根因三：容量限制把高分候选挡掉，已持仓未必是更优资产

7 天 `ENTRY_GATE_BLOCK` 合计约 289 次：

| Gate | 次数 | 说明 |
|---|---:|---|
| `account_cooldown` | 131 | 日亏损触发 8 小时冷却，主要集中 5/25 晚至 5/26 早 |
| `active_symbol_capacity` | 94 | 仓位数达到上限后，高分候选被丢弃 |
| `micro_notional` | 51 | 小于微仓/保证金阈值 |
| `exit_cooldown` | 12 | 刚退出后同向/同币种冷却 |
| `pending_entry_order` | 1 | 已有挂单 |

容量阻断样例：

```text
2026-05-20 runtime.out.00.log:239 BCHUSDT SHORT score=0.6971 threshold=0.69 gate=active_symbol_capacity value=5
2026-05-21 runtime.out.00.log:1396 POLUSDT LONG score=0.8374 threshold=0.68 gate=active_symbol_capacity value=9
2026-05-22 runtime.out.06.log:4563 DOGEUSDT LONG score=0.9025 threshold=0.68 gate=active_symbol_capacity value=9
```

问题：容量满时只是拒绝新候选，没有做“已持仓质量 vs 新候选质量”的替换。若已持仓 MFE 低、质量低，新高分动量币会被错过。

### 3.4 根因四：旧 VWAP gate 在 7 天前半段仍大量阻断，且与动量策略冲突

虽然当前配置中 `weight_vwap=0.0` 且 `vwap_score_hard_block.enabled=false`，但 7 天日志里仍出现：

| HOLD/Veto | 次数 |
|---|---:|
| `vwap_hard_block` | 856 |
| `vwap_score_filter` | 588 |

典型 HOLD 归因：

```text
stage=vwap, reason=vwap_hard_block, veto=vwap_hard_block
stage=vwap_score_filter, reason=vwap_score_filter(0.0906<0.1200), veto=vwap_score_filter
```

结论：近 7 天前半段仍受旧 VWAP gate 影响。VWAP 作为均值回归指标，在强趋势里会把“涨远了的强势币”挡掉，是慢牛错失的重要原因之一。当前已经消融，但评审时应关注：是否所有入口、BTC regime、position cap 都不再隐性使用 VWAP。

### 3.5 根因五：微仓/碎片化造成交易噪声，且 5/25 前存在保证金语义 bug

5/25 后审计样例显示，有大量 0.005、0.02、0.03、0.042 的仓位：

```text
PUMPUSDT SHORT target=0.005 equity=101.47 estimated_notional=0.507U
SOLUSDT LONG continuation target=0.03 equity=101.14 estimated_notional=3.03U
DOGEUSDT LONG continuation target=0.02 equity=100.09 estimated_notional=2.00U
ONDOUSDT LONG continuation target=0.042 equity=100.38 estimated_notional=4.216U
```

问题：

1. 0.005 target 在 100U 账户下只有约 0.5U 保证金，按用户要求应阻挡低于 1U 的订单。
2. 此前实盘预检查把 `target_portion_of_balance` 错当作杠杆后名义价值比例，又除以 leverage，造成 1U 保证金门槛误放大 3-9 倍。该 bug 已在 `src/app/fund_flow_bot.py` 修复，但 7 天历史表现中仍包含该影响。
3. 过多小 probe 即使方向对，也难以覆盖频繁退出和手续费。

### 3.6 根因六：慢牛 continuation 开出来了，但排序/出场仍未证明有效

5/25-5/26 审计显示 continuation long 已生效：

```text
ONDOUSDT continuation_long score=0.6 competition_score=0.7693 conditions=6/6 target=0.042
SOLUSDT continuation_long score=0.6 competition_score=0.7975 conditions=4/6 target=0.02
ADAUSDT continuation_long score=0.6 competition_score=0.7987 conditions=4/6 target=0.02
MORPHOUSDT continuation_long score=0.6 competition_score=0.7710 conditions=6/6 target=0.042
```

慢牛 detector 样例：

```text
mode=alt_breadth_led breadth=0.9286 btc_ret_30m=0.0926% alt_median_60m=0.8406% confirm=2
```

但 continuation 当前存在两个问题：

1. `signal_score` 固定 0.60，真实排序依赖 `competition_score` 但是否进入容量竞争需确认。
2. continuation 是小仓 probe，若 beta/exit guard 仍按普通仓位快速退出，就会变成“小仓频繁试错”。

---

## 4. 实盘开仓链路展开

### 4.1 总调用链

```text
fund_flow_bot 主循环
  -> _execute_symbol_signal_decision()
    -> DecisionEngine / MACDStrategyV2Engine 生成 FundFlowDecision
      -> MACD V2 score_aggregation / threshold_check
      -> continuation_long 并行路径（慢牛）
      -> btc_entry_regime_gate
      -> regime_entry_gate
      -> vwap observation-only gate（当前应只记录）
      -> slow_bull_short_guard
      -> min_open_portion / min_open_notional / micro_notional / micro_margin
      -> capacity / active symbol / pending order / cooldown gates
    -> _execute_and_log_decision()
      -> execution_router.execute_decision()
        -> risk_engine.validate_decision()
        -> account_risk_scaler
        -> min_entry_margin_usdt check
        -> position_count_limit_by_margin
        -> place limit/market order
```

关键代码位置：

| 模块 | 关键函数/配置 | 位置 |
|---|---|---|
| 实盘调度与 gate 日志 | `_execute_symbol_signal_decision`, `_log_entry_gate_block`, `_execute_and_log_decision` | `src/app/fund_flow_bot.py:8468`, `7078`, `7303` |
| 微仓/保证金阻断 | `_allows_entry_above_micro_notional` | `src/app/fund_flow_bot.py:3764` |
| MACD V2 权重评分 | `score_aggregation`, `threshold_check` | `src/fund_flow/macd_strategy_v2.py:5899-6047`, `6451` |
| continuation long | `_evaluate_continuation_long_candidate` | `src/fund_flow/macd_strategy_v2.py:1758` |
| BTC entry gate | `BtcEntryRegimeGate.check_entry` 调用 | `src/fund_flow/decision_engine.py:2365-2389` |
| 风控校验 | `validate_decision`, `_apply_account_risk_scaler` | `src/fund_flow/risk_engine.py:352`, `266` |
| 执行器保证金检查 | `_check_min_entry_margin`, `execute_decision` | `src/fund_flow/execution_router.py:537`, `1156` |

### 4.2 MACD V2 评分权重

当前配置：`config/trading_config_fund_flow.json:599`

| 因子 | 权重 | 说明 |
|---|---:|---|
| 1H direction | 0.15 | 1H 信号方向健康度 |
| 4H direction | 0.40 | 主趋势方向，最大权重 |
| 4H enhancement | 0.10 | 运行时折叠进 4H 主方向 |
| RSI rhythm | 0.30 | RSI 节奏与极端/反向 veto 影响大 |
| VWAP | 0.00 | 当前应完全消融，不参与 score |
| 15M entry | 0.05 | 15M 入场确认权重较小 |
| Volume | 0.10 | 成交量确认 |

代码聚合位置：`src/fund_flow/macd_strategy_v2.py:5899-6047`。

### 4.3 普通 MACD final 门槛

配置：

| 参数 | 值 |
|---|---:|
| `long_open_threshold` | 0.09（fund_flow 外层） |
| `short_open_threshold` | 0.07（fund_flow 外层） |
| MACD V2 常见实盘 threshold | long 约 0.68，short 约 0.66-0.69（日志字段 `signal_threshold`） |
| `stop_loss_pct` | 0.005 |
| `take_profit_pct` | 0.02 |
| `reverse_close_confirm_bars` | 2 |

实盘日志样例：

```text
ATOMUSDT LONG final score=0.6865 threshold=0.68 target=0.1512
JSTUSDT LONG final score=0.7165 threshold=0.64 target=0.042
PUMPUSDT LONG final score=0.8125 threshold=0.64 target=0.06 gate_cap=0.06
```

### 4.4 continuation long 门槛

配置：`config/trading_config_fund_flow.json:917`

| 条件 | 阈值 |
|---|---:|
| `min_conditions_met` | 4/6 |
| `ret_30m_threshold` | 0.003 |
| `ret_60m_threshold` | 0.006 |
| `rsi_min` / `rsi_max` | 50 / 72 |
| `leverage` | 3 |
| 6/6 portion | 0.042 |
| 5/6 portion | 0.030 |
| 4/6 portion | 0.020 |
| low corr strict | corr < 0.20 需更严格 |

实盘样例：

```text
ONDOUSDT: 6/6 ret30=0.77% ret60=0.77% rsi=69.0 portion=0.042
SOLUSDT: 4/6 ret30=-0.11% ret60=0.18% rsi=63.2 portion=0.020
DOGEUSDT: 4/6 ret30=0.40% ret60=0.51% rsi=100.0 portion=0.020
```

注意：DOGE RSI=100 仍通过，说明 slow bull live 的 `rsi_extreme_mode=cap_not_block` 已生效，但极端 RSI 只 cap 仓位，不再 hard block。

### 4.5 market breadth 慢牛 detector

配置：`config/trading_config_fund_flow.json:387`

| 模式 | 条件 |
|---|---|
| `alt_breadth_led` | breadth >= 0.80，alt median 60m >= 0.25%，BTC 30m >= -0.10% |
| `btc_led` | BTC 30m >= 0.20%，breadth >= 0.60，alt median 60m >= 0.30% |
| `extreme_breadth` | breadth >= 0.90，alt median 60m >= 0.10% |
| 确认 | `confirm_cycles=2` |

实盘样例：

```text
is_slow_bull=True mode=alt_breadth_led breadth=0.9286 btc30=0.0926% alt_med60=0.8406% confirm=2
```

### 4.6 风控与仓位执行门槛

| 风控 | 配置 | 实盘含义 |
|---|---|---|
| `min_entry_notional_usdt` | 0.1 | 低于 0.1U 名义/保证金观测值阻挡 |
| `min_entry_margin_usdt` | 1.0 | 低于 1U 保证金阻挡，当前已按 `target * equity` 语义修正 |
| `max_active_symbols` | 9 | 超过则 `active_symbol_capacity` 阻挡 |
| small margin position limit | <5U 最多 5 个，大仓最多 4 个 | 防止全是小碎仓 |
| account risk scaler | exposure 0.85，leverage 0.85，min leverage 3 | 所有开仓经过账户风险缩放 |
| daily loss circuit | 5% 日亏损，冷却 28800 秒 | 触发后 8 小时不开新仓 |
| BTC beta risk | reduce score>=2，close score>=4，fast_fail_window=2 bars | 加速退出与减仓 |
| exit cooldown | 1800 秒 | 平仓后冷却，避免立刻反复开 |

---

## 5. 风控阻断统计

7 天 `ENTRY_GATE_BLOCK`：

| Gate | 次数 | 归因 |
|---|---:|---|
| `account_cooldown` | 131 | 5/25 晚至 5/26 早触发 daily loss，挡住大量多头候选 |
| `active_symbol_capacity` | 94 | 仓位满导致高分候选不能进入 |
| `micro_notional` | 51 | 微仓/保证金不足 |
| `exit_cooldown` | 12 | 退出后冷却 |
| `pending_entry_order` | 1 | 已有挂单 |

HOLD/Veto 统计：

| HOLD/Veto 原因 | 次数 | 说明 |
|---|---:|---|
| 4H 无明确方向 | 5636 | 主趋势不明确时大量 HOLD |
| `rsi_1h_direction_against_veto` | 4274 | RSI 与 1H 方向冲突阻断 |
| `rsi_15m_extreme_veto` | 2004 | 15M RSI 极端阻断，慢牛更新前影响明显 |
| `vwap_hard_block` | 856 | 旧 VWAP hard block |
| `rsi_1h_direction_flat_veto` | 804 | RSI/1H 方向偏平阻断 |
| `vwap_score_filter` | 588 | 旧 VWAP score filter |
| `combo_hard_block` | 48 | signal combo 阻断 |

---

## 6. DeepSeek 需要重点评审的问题

1. **出场是否过早**  
   `BETA_RISK_CLOSE/REDUCE` 与 `EXIT_SIGNAL_GUARD_CLOSE/REDUCE` 是已匹配亏损的主因。需要用 MFE/MAE 证明：这些仓位如果不退出，是更亏还是能反弹。

2. **容量是否应该替换而不是拒绝**  
   `active_symbol_capacity` 阻挡 94 次，其中有 DOGE 0.9025、POL 0.8374 等高分候选。当前没有“低质量持仓换高质量候选”的机制。

3. **普通 final 与 continuation 的排序是否混乱**  
   continuation `signal_score=0.60`，但 `competition_score` 可到 0.80+。需要确认容量竞争实际使用哪个分数，否则强 continuation 可能排序吃亏。

4. **慢牛下 RSI extreme cap 是否足够**  
   RSI=100 的 DOGE 仍可用 0.02 开仓，这满足“cap not block”，但如果这种极端 RSI 后回撤高，应增加 trailing 或要求更强 ret60/EMA。

5. **VWAP 是否已完全从所有入口消融**  
   当前配置看是消融，但 7 天历史有大量旧 VWAP block。需要检查所有入口是否仍有隐性 `vwap_score_tiers` 或 `vwap_score_entry_gate max_portion` 在改变仓位。

6. **微仓阈值与 probe 仓位是否一致**  
   用户要求低于 1U 保证金全部阻挡。历史中存在 0.5U 左右开仓；当前修复后应该阻挡。DeepSeek 应评审：0.02/0.03/0.042 是否足够覆盖手续费与滑点。

---

## 7. 初步修复建议（不直接上线，仅供评审）

1. **先做 MFE/MAE 后验审计再改 exit**  
   对所有 `BETA_RISK_*` 和 `EXIT_SIGNAL_GUARD_*` 平仓，统计平仓后 2/4/8 根 15M 的最大反弹与最大继续亏损。若 `stopped_before_followthrough` 占比高，再放宽 continuation fast-fail。

2. **容量替换 shadow 必须纳入实盘日志**  
   当 `active_symbol_capacity` 触发时，记录当前持仓的 MFE、score、age，与新候选 score/ret30/ret60 对比，输出 shadow replacement。

3. **按 symbol 做临时降权而不是全局调参**  
   ICP/FET/TRUMP/ADA/DOGE 是主要亏损集中区，建议先要求更高 entry score 或更强 15M 确认，而不是全局提高阈值。

4. **continuation long 的退出应与普通 final 隔离**  
   continuation 是慢牛小仓跟随，不应完全共享普通 beta fast-fail 的 2 bar 逻辑。建议先 shadow：前 4 根只在 BTC 与 alt 同时反向且 MAE 达阈值时退出。

5. **统一手续费口径**  
   将 BNB/USDT 手续费统一折算为 USDT，否则 5/24、5/25 的真实净收益对比会失真。

---

## 8. 使用文件

- `D:\AIDCA\AI2\logs\2026-05\2026-05-20..26\trade_fills_utc.csv`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-20..26\fund_flow_attribution.jsonl(.gz)`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-20..26\runtime.out.*.log`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-25\fund_flow\fund_flow_entry_exit_audit.jsonl`
- `D:\AIDCA\AI2\logs\2026-05\2026-05-26\fund_flow\fund_flow_entry_exit_audit.jsonl`
- `D:\AIDCA\AI2\config\trading_config_fund_flow.json`
- `D:\AIDCA\AI2\src\app\fund_flow_bot.py`
- `D:\AIDCA\AI2\src\fund_flow\macd_strategy_v2.py`
- `D:\AIDCA\AI2\src\fund_flow\decision_engine.py`
- `D:\AIDCA\AI2\src\fund_flow\risk_engine.py`
- `D:\AIDCA\AI2\src\fund_flow\execution_router.py`
