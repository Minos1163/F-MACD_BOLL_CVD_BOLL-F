# MACD V2 实施后复盘与 Claude 评审材料

## 0. 2026-05-01 外科修正复测追加结论

本次按复盘路线执行了“回退容量与竞争 + 关闭 gate + 修复 IOC market fallback”的外科修正，并生成了新的 30 天 strict-live 回测产物。

已落地的修正：

- `max_active_symbols: 4 -> 3`
- `dynamic_max_active_symbols.max_active_symbols: 4 -> 3`
- `competition_ranking.enabled: true -> false`
- `pretrade_risk_gate.enabled: true -> false`
- `execution_degradation.force_market_fallback_on_ioc_remainder: true`（外科修正阶段启用；归核化阶段已改为默认 `false`）
- `execution_degradation.open_market_fallback_max_slippage_bps: 8`
- 修复 backtest pending order metadata 默认不传播 market fallback 的问题
- 修复 backtest pending IOC 在 fallback 前被“后续信号低于阈值 / 信号反向”早退取消的问题
- 修复 live router 中非 `ioc_market_fallback` market fallback 路径不尊重 `disable_market_fallback` 的问题

新的验证结果：

- 单测：`125 passed`
- 30 天 strict-live：没有 `0 开仓 / 0 收益`
- `flip_bullish` 成交仍为 `0`
- IOC fallback 链已真实进入：`market_fallback_attempted=109`
- market fallback 实际成交：`market_fallback_filled=42`
- 剩余取消均为滑点保护：`market_fallback_slippage_blocked=67`

但验收失败，不能 sign-off：

- 收益率只有 `+27.13%`，低于目标 `+48.8%`
- MDD `9.10%`，高于目标 `<=7.0%`
- PF `2.54`，低于目标 `>=6.0`
- WR `74.77%`，低于原系统稳定区间
- 强制补单虽然把 IOC cancel rate 降到 `37.64%`，但新增成交质量显著劣化

结论：

- `capacity=3 / ranking=false / gate=false` 的回退方向是正确的，回撤相对 `capacity=4` 从 `10.37%` 降到 `9.10%`，但仍未回到旧基线 `6.12%`。
- IOC market fallback 的技术链路已修通，不再是 `attempted=0`。
- “强制 IOC 剩余市价补单”不是可上线收益改进；它把执行问题转化成了信号质量问题，新增 42 笔 fallback 成交拉低了 WR/PF/收益。
- 归核化阶段已把 `force_market_fallback_on_ioc_remainder` 改成消融项并默认关闭；30 天 strict-live 结果恢复到 `+41.58% / WR 87.78% / PF 6.15 / MDD 8.23%`，但仍未达到新验收线。

## 1. 本轮结论

- 已按批准计划把 `P0 flip_bullish -> P1 补充退出 -> P2 IOC 动态退化 -> P3 capacity=4 / competition ranking -> P4 pretrade_risk_gate phase1` 并入主链。
- 已完成代码、配置、测试、30 天 strict-live 回测、30 天 profile 回测、IOC 诊断产物和评审文档产物。
- 已确认没有重新引入旧的 `strict-live = 0 开仓 / 0 收益` 问题。
- 已把 `flip_bullish` 在主链中真实禁用到 `0 成交`，不再只是“配置写成 true 但 4H-primary/light-confirm 旁路仍能放行”。
- 但本轮并没有达到全部性能验收目标：
  - 30 天收益从旧基线 `+44.37%` 降到 `+40.93%`
  - `capacity=4` 后最大回撤升到 `10.37%`，略高于 `<=10%`
  - IOC 取消率从旧的 `58.0%` 升到 `58.17%`，没有下降
  - 因本地缓存窗口仍只覆盖同样的 `2831` 个 15m 时间点，所谓 `2026-01-01 ~ 2026-03-31` 扩展窗口没有形成额外样本，结果与 30 天 strict-live rerun 相同，不能当成真正 3 个月验证

## 2. 本轮实现落点

代码主改动：

- [src/fund_flow/macd_strategy_v2.py](/D:/AIDCA/AI2/src/fund_flow/macd_strategy_v2.py)
- [src/fund_flow/decision_engine.py](/D:/AIDCA/AI2/src/fund_flow/decision_engine.py)
- [src/fund_flow/execution_router.py](/D:/AIDCA/AI2/src/fund_flow/execution_router.py)
- [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py)
- [scripts/backtest_macd_v2.py](/D:/AIDCA/AI2/scripts/backtest_macd_v2.py)

配置主改动：

- [config/trading_config_fund_flow.json](/D:/AIDCA/AI2/config/trading_config_fund_flow.json)

新增验证/诊断脚本：

- [scripts/validate_live_backtest_alignment.py](/D:/AIDCA/AI2/scripts/validate_live_backtest_alignment.py)
- [scripts/diagnose_ioc_fallback.py](/D:/AIDCA/AI2/scripts/diagnose_ioc_fallback.py)
- [scripts/analyze_backtest_trades.py](/D:/AIDCA/AI2/scripts/analyze_backtest_trades.py)

核心实现点：

1. `flip_bullish` 主链禁用
- live 默认配置 `disable_flip_bullish_entries=true`
- 修复了原先只在 `strict_1h_filters_enabled` 生效的问题
- 现在 4H-primary + light-confirm 路径也会统一拦截 `flip_bullish`

2. 补充退出已并入现有链
- `macd_1h_flip_exit`
- `rsi_overheat_exit`
- `holding_time_exit`

3. IOC 动态退化已落地
- `open_ioc_dynamic_step_enabled`
- `open_ioc_max_total_slippage_bps`
- 高分信号动态加大 step
- 保留原双门 market fallback 语义

4. 容量扩展已落地
- `max_active_symbols=4`
- `competition_ranking.enabled=true`
- cluster bonus map 已接入 live/backtest 共用竞争排序

5. `pretrade_risk_gate` 已进入主链 Phase 1
- `enabled=true`
- `force_exit_on_gate=false`
- `phase1_entry_only=true`
- `shadow_mode=false`

## 3. 测试与验证

通过的核心 pytest 批次：

```bash
pytest tests/test_backtest_profiles.py tests/test_fund_flow_decision_engine.py tests/test_backtest_review_followup.py tests/test_pretrade_risk_gate_exit_logic.py tests/test_finalize_entries_close_priority.py tests/test_bot_like_replay_selection.py -q
```

结果：

- `129 passed`

额外复跑：

```bash
pytest tests/test_macd_strategy_v2_4h_scoring.py tests/test_backtest_profiles.py tests/test_fund_flow_decision_engine.py tests/test_backtest_review_followup.py -q
```

结果：

- `166 passed`

`execution_router` 用例：

- pytest 本身在当前 Windows 环境的临时目录清理阶段持续出现 `PermissionError`
- 已改用同目录手工 harness 逐条执行 [tests/test_fund_flow_execution_router.py](/D:/AIDCA/AI2/tests/test_fund_flow_execution_router.py) 中的 7 个用例
- 7/7 通过

关键补测覆盖：

- `flip_bullish` 在 4H-primary/light-confirm 路径下也必须被禁用
- 补充退出三条链各自触发
- `pretrade_risk_gate phase1_entry_only + shadow_mode`
- IOC 动态重试与总滑点上限
- approved-difference 对齐校验
- IOC fallback 诊断脚本

## 4. 30 天回测结果

### 4.1 旧基线

来源：

- [output/backtest/v2_live_equiv_20260430_summary.json](/D:/AIDCA/AI2/output/backtest/v2_live_equiv_20260430_summary.json)

窗口：

- `2026-02-23` 到 `2026-03-24T23:59:59`

指标：

- 收益率 `+44.3736%`
- 胜率 `87.2340%`
- 总成交 `94`
- PF `7.2038`
- MDD `6.1150%`
- 提交订单 `224`
- 成交订单 `94`
- 取消订单 `130`
- `flip_bullish: 4 笔 / -79.02`

### 4.2 本轮 strict-live rerun

来源：

- [output/backtest/v2_strict_live_20260501_rerun_summary.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_summary.json)
- [output/backtest/v2_strict_live_20260501_rerun_trades_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_trades_analysis_summary.json)
- [output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json)

窗口：

- `2026-02-23` 到 `2026-03-24T23:59:59`

指标：

- 收益率 `+40.9342%`
- 胜率 `86.6667%`
- 总成交 `105`
- PF `5.4807`
- MDD `10.3696%`
- 提交订单 `251`
- 成交订单 `105`
- 取消订单 `146`

按信号类型归因：

- `red_bar_growing: 85 笔 / WR 83.53% / PnL +2669.26`
- `flip_bearish: 20 笔 / WR 100% / PnL +1660.16`
- `flip_bullish: 0 笔`

按执行漏斗归因：

- `flip_bullish_seen = 2652`
- `flip_bullish_passed_threshold = 0`
- `flip_bullish_blocked_by_sniper = 396`
- `flip_bullish_ioc_canceled = 0`
- `capacity_full_precheck_candidates = 63`
- `capacity_competition_dropped = 49`

按币种归因：

- 最强 `ICPUSDT: 7 笔 / 100% / +1111.95`
- 最弱 `ALGOUSDT: 3 笔 / 66.67% / -244.10`

回撤归因：

- 真最大回撤 `10.3696%`
- 区间 `2026-02-28 10:00:00 -> 2026-03-04 00:30:00`
- 恢复 `2026-03-15 01:00:00`

### 4.3 30 天对比结论

与旧基线相比：

- `strict-live 0 开仓 / 0 收益` 问题已持续修复
- `flip_bullish` 真实清零，负 alpha 路径已退出主链
- 交易数从 `94 -> 105`
- 胜率从 `87.23% -> 86.67%`
- 收益从 `44.37% -> 40.93%`
- PF 从 `7.20 -> 5.48`
- MDD 从 `6.12% -> 10.37%`

这说明：

- P0 确实把负收益簇清掉了
- 但 P1/P2/P3/P4 的全集成默认组合没有把收益推高，反而把仓位吞吐和回撤一起抬上去了

## 5. 验收项结果

### 5.1 已通过

- `strict-live rerun` 没有出现 `0 开仓 / 0 收益`
- `flip_bullish` 成交已为 `0`
- 30 天 strict-live 与 profile rerun 结果一致
- `pretrade_risk_gate phase1` 没有把主链打死

### 5.2 未通过

- `IOC cancel rate` 未下降
  - 旧基线：`130 / 224 = 58.04%`
  - 新 rerun：`146 / 251 = 58.17%`

- `capacity=4` 验收未通过
  - 目标：`MDD <= 10%`
  - 实际：`10.37%`

- 收益提升目标未通过
  - 目标：至少高于旧基线 `44.37%` 的 `10%`
  - 目标线约：`48.81%`
  - 实际：`40.93%`

## 6. IOC fallback 诊断

来源：

- [output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json)

结论：

- `ioc_no_fill_total = 146`
- `market_fallback_attempted = 0`
- `market_fallback_filled = 0`
- `market_fallback_disabled_by_policy = 0`
- `fallback_not_reached_after_ioc_cancel = 146`

补充统计：

- 取消单平均分 `0.6649`
- 成交单平均分 `0.6651`

这说明：

- 当前瓶颈不是“fallback 进入后被滑点拦截”
- 而是绝大部分 IOC cancel 根本没有进入 `market fallback`
- 现状仍需要进一步检查：
  - `entry_execution_policy`
  - `entry_market_fallback_enabled`
  - 哪些 live/backtest 路由分支没有稳定挂上这两个 metadata

## 7. 扩展窗口验证说明

计划要求：

- `2026-01-01 ~ 2026-03-31` 跑 gate phase1

实际执行：

- 已运行 `--start 2026-01-01 --end 2026-03-31T23:59:59`
- 产物：
  - [output/backtest/v2_extended_gate_phase1_20260501_rerun_summary.json](/D:/AIDCA/AI2/output/backtest/v2_extended_gate_phase1_20260501_rerun_summary.json)
  - [output/backtest/v2_extended_gate_phase1_20260501_rerun_trades_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_extended_gate_phase1_20260501_rerun_trades_analysis_summary.json)

必须明确的限制：

- 本地缓存实际仍只回放了 `2831` 个 15m 时间点
- 输出与 30 天 strict-live rerun 完全相同
- 因此这份“扩展窗口”不能被解释成真正新增市场状态验证

结论：

- 命令已执行
- 但数据覆盖不足，无法把“回撤不恶化、收益降幅不超过 10%”当成已经被严格证明

## 7A. 外科修正复测结果

### 7A.1 配置修正 strict-live 复测

来源：

- [output/backtest/v2_surgical_fix_20260501_force_market_audit_summary.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_summary.json)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_ioc_diagnosis.json)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_analysis_summary.json)

窗口：

- `2026-02-23` 到 `2026-03-24T23:59:59`

指标：

- 收益率 `+27.1269%`
- 胜率 `74.7748%`
- 总成交 `111`
- PF `2.5434`
- MDD `9.0979%`
- 提交订单 `178`
- 成交订单 `111`
- 取消订单 `67`

执行漏斗：

- `market_fallback_attempted = 109`
- `market_fallback_filled = 42`
- `market_fallback_slippage_blocked = 67`
- `market_fallback_disabled_by_policy = 0`
- `fallback_not_reached_after_ioc_cancel = 0`

按信号类型归因：

- `red_bar_growing: 87 笔 / WR 74% / PnL +1718.11`
- `flip_bearish: 24 笔 / WR 79% / PnL +1227.77`
- `flip_bullish: 0 笔`

验收对比：

- 收益目标：`>= +48.8%`，实际 `+27.13%`，失败
- MDD 目标：`<= 7.0%`，实际 `9.10%`，失败
- PF 目标：`>= 6.0`，实际 `2.54`，失败
- IOC cancel rate 目标：`< 50%`，实际 `67 / 178 = 37.64%`，通过
- fallback 目标：`attempted > 0` 且新增成交 `>=10`，实际 `109 / 42`，通过

### 7A.2 对比表

| 版本 | Return | WR | Trades | PF | MDD | Submitted | Filled | Canceled | Market attempted | Market filled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 旧基线 `20260430` | `+44.37%` | `87.23%` | `94` | `7.20` | `6.12%` | `224` | `94` | `130` | `0` | `0` |
| P0-P4 全集成 | `+40.93%` | `86.67%` | `105` | `5.48` | `10.37%` | `251` | `105` | `146` | `0` | `0` |
| 外科修正 + 强制 fallback | `+27.13%` | `74.77%` | `111` | `2.54` | `9.10%` | `178` | `111` | `67` | `109` | `42` |

### 7A.3 评审结论

技术层面：

- IOC market fallback 路径已修通，`attempted=0` 的实现缺陷已被消除。
- 回测审计现在能区分“未进入 fallback”和“进入 fallback 但被滑点保护阻断”。
- `disable_market_fallback` 继续被 live router 尊重。

策略层面：

- 强制 fallback 新增的成交没有带来收益改善，反而把 PF 从 `5.48` 进一步压到 `2.54`。
- fallback 填充的订单多来自原本会被取消或信号反向的挂单，边际质量不足。
- 继续默认开启 `force_market_fallback_on_ioc_remainder=true` 不符合当前验收目标。

建议：

- 保留代码能力和测试，但把 `force_market_fallback_on_ioc_remainder` 作为实验开关，不建议直接 live 默认开启。
- 若继续测试 fallback，应增加门槛，例如 `signal_score >= 0.88`、禁止后续信号反向后补单、或仅允许 `flip_bearish` 高质量簇补单。
- 当前最稳的回滚基线仍是：`capacity=3`、`competition_ranking=false`、`pretrade_risk_gate.enabled=false`、`disable_flip_bullish_entries=true`，但不要强制补单。

## 7B. 归核化复测结果

### 7B.1 配置归核化 strict-live 复测

来源：

- [output/backtest/v2_core_reset_20260501_summary.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_summary.json)
- [output/backtest/v2_core_reset_20260501_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_ioc_diagnosis.json)
- [output/backtest/v2_core_reset_20260501_analysis_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_analysis_analysis_summary.json)

窗口：

- `2026-02-23` 到 `2026-03-24T23:59:59`

归核化配置：

- `max_active_symbols = 3`
- `competition_ranking.enabled = false`
- `pretrade_risk_gate.enabled = false`
- `disable_flip_bullish_entries = true`
- `force_market_fallback_on_ioc_remainder = false`
- `open_ioc_dynamic_step_enabled = true`
- `open_ioc_max_total_slippage_bps = 60`

指标：

- 收益率 `+41.5841%`
- 胜率 `87.7778%`
- 总成交 `90`
- PF `6.1471`
- MDD `8.2305%`
- 提交订单 `217`
- 成交订单 `90`
- 取消订单 `127`

执行漏斗：

- `market_fallback_attempted = 0`
- `market_fallback_filled = 0`
- `market_fallback_slippage_blocked = 0`
- `pending_cancel_reasons = {"ioc_no_fill": 127}`

按信号类型归因：

- `red_bar_growing: 73 笔 / WR 84.93% / PnL +2748.27`
- `flip_bearish: 17 笔 / WR 100% / PnL +1626.64`
- `flip_bullish: 0 笔`

验收对比：

- 收益目标：`>= +45.00%`，实际 `+41.58%`，失败
- WR 目标：`>= 85.00%`，实际 `87.78%`，通过
- PF 目标：`>= 9.00`，实际 `6.15`，失败
- MDD 目标：`<= 6.00%`，实际 `8.23%`，失败
- Trades 目标：`80-100`，实际 `90`，通过
- `flip_bullish` 成交目标：`0`，实际 `0`，通过
- 全局强制 fallback 目标：不应触发，实际 `market_fallback_attempted=0`，通过

### 7B.2 对比表

| 版本 | Return | WR | Trades | PF | MDD | Submitted | Filled | Canceled | Market attempted | Market filled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 旧基线 `20260430` | `+44.37%` | `87.23%` | `94` | `7.20` | `6.12%` | `224` | `94` | `130` | `0` | `0` |
| P0-P4 全集成 | `+40.93%` | `86.67%` | `105` | `5.48` | `10.37%` | `251` | `105` | `146` | `0` | `0` |
| 外科修正 + 强制 fallback | `+27.13%` | `74.77%` | `111` | `2.54` | `9.10%` | `178` | `111` | `67` | `109` | `42` |
| 归核化 + 关闭强制 fallback | `+41.58%` | `87.78%` | `90` | `6.15` | `8.23%` | `217` | `90` | `127` | `0` | `0` |

### 7B.3 评审结论

- 关闭强制 fallback 是正确减法：WR 从 `74.77%` 恢复到 `87.78%`，PF 从 `2.54` 恢复到 `6.15`。
- 归核化仍未超越旧基线：收益低于 `44.37%`，PF 低于 `7.20`，MDD 高于 `6.12%`。
- `flip_bullish` 禁用仍保持有效，但单独禁用它并没有自动带来 PF `>=9` 的结构性提升。
- 本轮不应继续叠加新调参；下一轮应单独定位 MDD `8.23%` 的来源，优先从退出路径或仓位暴露归因入手，而不是恢复强制补单。

## 8. 当前实盘开仓链路

主链路：

1. `src/main.py`
2. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `TradingBot._init_fund_flow_modules()`
3. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `TradingBot.run_cycle()`
4. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `TradingBot._run_cycle_impl()`
5. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `TradingBot._process_symbol_core()`
6. [src/fund_flow/decision_engine.py](/D:/AIDCA/AI2/src/fund_flow/decision_engine.py) `FundFlowDecisionEngine`
7. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `TradingBot._apply_pretrade_risk_gate()`
8. [src/fund_flow/execution_router.py](/D:/AIDCA/AI2/src/fund_flow/execution_router.py) `FundFlowExecutionRouter.execute_decision()`
9. [src/app/fund_flow_bot.py](/D:/AIDCA/AI2/src/app/fund_flow_bot.py) `_post_execution_protection_hook()`

当前 live 默认：

- `max_active_symbols = 3`
- `reserve_pct = 0.20`
- `disable_flip_bullish_entries = true`
- `priority_exec_expire_seconds = 25`
- `priority_exec_vip_expire_seconds = 45`
- `open_ioc_retry_times = 4`
- `open_ioc_dynamic_step_enabled = true`
- `open_ioc_max_total_slippage_bps = 60`
- `open_market_fallback_max_slippage_bps = 8`
- `force_market_fallback_on_ioc_remainder = false`
- `pretrade_risk_gate.enabled = false`
- `pretrade_risk_gate.phase1_entry_only = true`
- `competition_ranking.enabled = false`

## 9. 建议 Claude 重点审查的问题

1. `capacity=4 + competition_ranking + gate phase1 + supplemental exits` 的全集成默认组合，为什么把交易数抬高后没有转化成更高收益，反而把 MDD 推到 `10%+`。
2. `IOC dynamic retry` 已经落地，但 `market_fallback_attempted` 仍为 `0`，到底是 metadata 路由问题，还是策略对 market fallback 的启用面过窄。
3. `pretrade_risk_gate phase1` 当前默认开启，但在现有数据覆盖下没有证明它改善了回撤收益比。
4. `capacity=4` 是否应该保留为 live 默认，还是先退回 `3`，把 `competition_ranking` 和 IOC 链路单独做消融。
5. 本轮扩展窗口验证受数据覆盖限制，是否需要先补足真实 3 个月缓存再做最终 sign-off。

## 10. 产物索引

本轮关键产物：

- [output/backtest/v2_strict_live_20260501_rerun_summary.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_summary.json)
- [output/backtest/v2_strict_live_20260501_rerun_trades.csv](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_trades.csv)
- [output/backtest/v2_strict_live_20260501_rerun_trades_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_trades_analysis_summary.json)
- [output/backtest/v2_strict_live_20260501_rerun_trades_cancel_quality_summary.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_trades_cancel_quality_summary.json)
- [output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_strict_live_20260501_rerun_ioc_diagnosis.json)
- [output/backtest/v2_profile_after_change_20260501_rerun_summary.json](/D:/AIDCA/AI2/output/backtest/v2_profile_after_change_20260501_rerun_summary.json)
- [output/backtest/v2_extended_gate_phase1_20260501_rerun_summary.json](/D:/AIDCA/AI2/output/backtest/v2_extended_gate_phase1_20260501_rerun_summary.json)
- [output/backtest/v2_extended_gate_phase1_20260501_rerun_trades_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_extended_gate_phase1_20260501_rerun_trades_analysis_summary.json)

外科修正复测产物：

- [output/backtest/v2_surgical_fix_20260501_force_market_audit_summary.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_summary.json)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_trades.csv](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_trades.csv)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_equity_curve.csv](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_equity_curve.csv)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_pending_cancels.csv](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_pending_cancels.csv)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_ioc_diagnosis.json)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_analysis_summary.json)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_symbol_breakdown.csv](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_symbol_breakdown.csv)
- [output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_true_drawdown_breakdown.csv](/D:/AIDCA/AI2/output/backtest/v2_surgical_fix_20260501_force_market_audit_analysis_true_drawdown_breakdown.csv)

归核化复测产物：

- [output/backtest/v2_core_reset_20260501_summary.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_summary.json)
- [output/backtest/v2_core_reset_20260501_trades.csv](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_trades.csv)
- [output/backtest/v2_core_reset_20260501_equity_curve.csv](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_equity_curve.csv)
- [output/backtest/v2_core_reset_20260501_pending_cancels.csv](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_pending_cancels.csv)
- [output/backtest/v2_core_reset_20260501_ioc_diagnosis.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_ioc_diagnosis.json)
- [output/backtest/v2_core_reset_20260501_analysis_analysis_summary.json](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_analysis_analysis_summary.json)
- [output/backtest/v2_core_reset_20260501_analysis_symbol_breakdown.csv](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_analysis_symbol_breakdown.csv)
- [output/backtest/v2_core_reset_20260501_analysis_true_drawdown_breakdown.csv](/D:/AIDCA/AI2/output/backtest/v2_core_reset_20260501_analysis_true_drawdown_breakdown.csv)

旧基线对比产物：

- [output/backtest/v2_live_equiv_20260430_summary.json](/D:/AIDCA/AI2/output/backtest/v2_live_equiv_20260430_summary.json)
