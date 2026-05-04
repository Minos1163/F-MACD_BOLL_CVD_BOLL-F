# MACD V2 — 消融实验结果解读与下一步行动计划

> 更新日期: 2026-05-03 (消融结果已产出)
> 状态: 候选配置已验证, 等待部署决策
> 上一版建议中的多项假设已被数据否定, 本文以实测结果为准

---

## 目录

1. [消融结果总结与假设修正](#1-消融结果总结与假设修正)
2. [已验证候选配置解读](#2-已验证候选配置解读)
3. [部署方案 — ADA+FET 黑名单](#3-部署方案--adafet-黑名单)
4. [下一波消融计划 — 符号范围止损](#4-下一波消融计划--符号范围止损)
5. [下一波消融计划 — Light TP 精细化](#5-下一波消融计划--light-tp-精细化)
6. [不应再测试的方向](#6-不应再测试的方向)
7. [Config DIFF](#7-config-diff)
8. [执行脚本伪代码](#8-执行脚本伪代码)
9. [决策树与路线图](#9-决策树与路线图)

---

## 1. 消融结果总结与假设修正

### 1.1 实测结果全表

```text
┌──────────────────────────────┬─────────┬────────┬───────┬───────┬───────┐
│ Case                         │ Return  │ WinRate│  PF   │  MDD  │Trades │
├──────────────────────────────┼─────────┼────────┼───────┼───────┼───────┤
│ 00_baseline                  │ +26.23% │ 91.36% │  3.55 │ 5.01% │  162  │
├──────────────────────────────┼─────────┼────────┼───────┼───────┼───────┤
│ B1_disable_light_tp          │ +24.76% │ 85.11% │  2.90 │ 6.55% │   94  │ ✗
│ B3_light_tp_only_low_adx     │ +26.76% │ 88.14% │  3.27 │ 5.07% │  118  │ △
├──────────────────────────────┼─────────┼────────┼───────┼───────┼───────┤
│ D1_max_symbols_4             │ +26.29% │ 90.80% │  3.44 │ 4.71% │  174  │ △
│ D2_max_symbols_5             │ +26.11% │ 89.78% │  3.36 │ 5.04% │  186  │ ✗
├──────────────────────────────┼─────────┼────────┼───────┼───────┼───────┤
│ F1_blacklist_adausdt         │ +29.69% │ 93.04% │  4.72 │ 4.13% │  158  │ ✓
│ F2_blacklist_ada_fet         │ +35.23% │ 94.12% │ 13.58 │ 3.22% │  153  │ ✓✓ ← 最优
├──────────────────────────────┼─────────┼────────┼───────┼───────┼───────┤
│ S1_max_stop_2pct             │ +23.13% │ 90.68% │  2.94 │ 5.70% │  161  │ ✗
│ S2_max_stop_1_5pct           │ +22.23% │ 89.94% │  2.83 │ 5.79% │  159  │ ✗
│ S3_max_stop_1pct             │ +15.87% │ 85.71% │  2.16 │ 7.36% │  154  │ ✗✗
│ S4_hard_stop_2pct            │ +19.93% │ 89.31% │  2.41 │ 7.80% │  159  │ ✗✗
│ S5_hard_stop_1_5pct          │ +18.48% │ 87.18% │  2.27 │ 8.43% │  156  │ ✗✗
│ S6_hard_stop_1pct            │ +15.71% │ 84.21% │  2.01 │ 6.04% │  152  │ ✗✗
└──────────────────────────────┴─────────┴────────┴───────┴───────┴───────┘

图例: ✓✓=强烈推荐  ✓=推荐  △=中性  ✗=不推荐  ✗✗=明确有害
```

### 1.2 被数据否定的假设 (停止追踪)

```text
❌ 假设A: 全局硬止损可以压制大亏损
   实测: S4/S5 硬止损后 亏损笔数 14→20, 总亏损 -1141→-1685, MDD 5%→8.4%
   结论: 全局硬止损在此策略上产生反效果, 不再推进

❌ 假设B1: 完全禁用 light_tp 可以提升回报
   实测: 回报-1.47%, 胜率-6.25%, 交易数-68笔 (94 vs 162)
   结论: light_tp 是当前胜率结构的核心支撑, 不能全禁

❌ 假设C/D: max_active_symbols 扩容可以提升回报
   实测: 4→+26.29%(无改善), 5→+26.11%(甚至略降)
   结论: 容量不是当前瓶颈, 维持 max_active_symbols=3

❌ 假设E: IOC改GTC可以大幅提升成交率进而提升回报
   现有证据表明更多成交(D1/D2 trade count更多)并未改善回报
   结论: 暂缓IOC/GTC改造, 当前信号质量决定了更多成交不等于更高回报
```

### 1.3 得到数据支持的结论

```text
✅ 符号选择是当前最大的可操作杠杆
   F2 (ADA+FET blacklist):
     回报:  +26.23% → +35.23%  (+9.00 ppt)
     胜率:  91.36%  → 94.12%   (+2.76 ppt)
     PF:    3.55    → 13.58    (+10.03 ← 最显著改善)
     MDD:   5.01%   → 3.22%    (-1.79 ppt, 更安全)
     交易数: 162     → 153      (仅减少9笔)

   ADAUSDT 和 FETUSDT 是尾部风险的主要来源:
     两个符号合计贡献 -525.24 亏损 (占总亏损 1141 的 46%)
     移除后 PF 从 3.55 跳到 13.58 — 结构性改善而非统计噪音

✅ 止损问题是符号特异性问题, 不是全局机制问题
   全局硬止损: 所有变体都变差
   符号范围止损: 下一步测试方向 (尚未测试)
   结论: 止损工作应聚焦于 ADAUSDT, FETUSDT, XLMUSDT 三个符号

✅ light_tp 条件化 (ADX门控) 是中性的
   B3 小幅改善回报(+0.53ppt)但损失胜率(-3.22ppt)和PF(-0.28)
   结论: 可以继续实验更精细的条件, 但不是当前优先级
```

---

## 2. 已验证候选配置解读

### 2.1 候选配置关键指标

```text
配置文件: config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json
验证命令: python scripts/backtest_macd_v2.py \
            --config config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json \
            --strict-live-mode --simulate-live-close-layers \
            --output-prefix output/backtest/candidate_blacklist_ada_fet_20260503 \
            --initial-capital 10000

指标对比:
  Return:        +26.23% → +35.23%  ← +34.3% 相对提升
  Win rate:      91.36%  → 94.12%   ← 更健康的信号质量
  Profit factor: 3.55    → 13.58    ← 意味着亏损已极度压缩
  Max drawdown:  5.01%   → 3.22%    ← 风险降低
  Trades:        162     → 153      ← 损失9笔但质量大幅提升
  Orders filled: 95      → 88
```

### 2.2 PF=13.58 的含义与风险提示

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: interpret_pf_spike.py
# PF=13.58 是真实改善还是过拟合信号?
# ════════════════════════════════════════════════════════════════

function interpret_extreme_pf(baseline_pf, candidate_pf, period_days):
    """
    PF 从 3.55 跳到 13.58 需要谨慎解读
    主要风险: 30d 窗口内 ADA/FET 恰好处于特别不利状态
              这可能是时间段特异性, 不一定在所有市场周期都成立
    """

    # 检查: gross_loss 在候选配置中是多少?
    # baseline gross_loss = -1141.99
    # candidate gross_loss ≈ -1141.99 + 525.24 (ADA+FET losses removed) = ~-616.75
    # candidate gross_win  ≈ 4058.57 - (ADA+FET wins)

    # PF = gross_win / |gross_loss|
    # PF 13.58 意味着: gross_win / gross_loss ≈ 13.58
    # 如果 gross_loss ≈ 260 (仅剩12笔亏损), gross_win ≈ 3530
    # 这是合理的: 移除了两个最大亏损源

    print("验证 PF=13.58 的稳健性需要:")
    print("  1. 在 60d / 90d 窗口重跑候选配置")
    print("  2. 确认 ADA/FET 在其他时间段也是净亏损")
    print("  3. 在不同市场状态 (熊市/震荡市) 测试")
    print("  如果3个测试都支持 → 黑名单是稳健的")
    print("  如果仅在当前30d有效 → 改用风险分层而非硬黑名单")


function check_adafet_performance_other_periods():
    """
    建议在部署前运行的验证查询
    """
    periods = [
        ("2025-10-01", "2025-11-30", "Q4_2025_bear"),
        ("2025-12-01", "2026-01-31", "Q1_2026_recovery"),
        ("2026-02-01", "2026-03-31", "Q1_2026_recent"),  # 当前测试窗口
    ]

    for start, end, label in periods:
        result = run_backtest_with_symbols(
            symbols=["ADAUSDT", "FETUSDT"],
            start=start, end=end
        )
        print(f"{label}: ADA={result.ADA.net_pnl:+.2f}, "
              f"FET={result.FET.net_pnl:+.2f}, "
              f"combined_wr={result.combined_win_rate:.2%}")

    # 决策规则:
    # 如果 ADA+FET 在 3 个时间段中 ≥2 个都是净亏损 → 硬黑名单
    # 如果仅当前30d亏损 → 使用动态风险分层 (不永久黑名单)
```

---

## 3. 部署方案 — ADA+FET 黑名单

### 3.1 部署前检查清单

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: pre_deploy_checklist.py
# 部署候选配置前的必要验证
# ════════════════════════════════════════════════════════════════

DEPLOY_CHECKLIST = [
    # ── 回测验证 ─────────────────────────────────────────────────
    CheckItem(
        id       = "BT-01",
        name     = "候选配置验证回测已完成",
        verify   = lambda: file_exists(
            "output/backtest/candidate_blacklist_ada_fet_20260503_summary.json"),
        status   = "DONE",   # 已完成
        note     = "Return=+35.23%, WR=94.12%, PF=13.58, MDD=3.22%"
    ),

    CheckItem(
        id       = "BT-02",
        name     = "60d 扩展窗口验证 (防止30d过拟合)",
        verify   = lambda: check_backtest_exists("60d_blacklist_ada_fet"),
        status   = "PENDING",
        note     = "运行: python scripts/backtest_macd_v2.py --days 60 "
                   "--config config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json"
    ),

    CheckItem(
        id       = "BT-03",
        name     = "ADA+FET 历史净PnL跨期验证 (≥2个时间段)",
        verify   = lambda: check_historical_symbol_pnl(["ADAUSDT","FETUSDT"], n_periods=3),
        status   = "PENDING",
        note     = "确认ADA/FET不只是在此30d表现差"
    ),

    # ── 配置验证 ──────────────────────────────────────────────────
    CheckItem(
        id       = "CF-01",
        name     = "候选配置与生产配置 diff 审查",
        verify   = lambda: run_config_diff(
            "config/trading_config_fund_flow.json",
            "config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json"),
        status   = "PENDING",
        note     = "确认只有 symbol_blacklist 字段变化, 其他参数不变"
    ),

    CheckItem(
        id       = "CF-02",
        name     = "live bot 黑名单逻辑验证",
        verify   = lambda: grep_code(
            "src/app/fund_flow_bot.py",
            pattern="symbol_blacklist"),
        status   = "PENDING",
        note     = "确认 fund_flow_bot 在入场前检查 symbol_blacklist"
    ),

    # ── 风险验证 ──────────────────────────────────────────────────
    CheckItem(
        id       = "RK-01",
        name     = "现有仓位检查 (不能有ADA/FET活跃仓位)",
        verify   = lambda: check_live_positions(["ADAUSDT","FETUSDT"]) == [],
        status   = "RUNTIME",
        note     = "部署前确认这两个符号当前无持仓"
    ),

    CheckItem(
        id       = "RK-02",
        name     = "MDD 监控告警已设置 ≤5%",
        verify   = lambda: check_alert_config("max_drawdown_alert") <= 0.05,
        status   = "PENDING",
        note     = "候选配置 MDD=3.22%, 告警设置为5%留有缓冲"
    ),
]


function run_checklist():
    pending_items = [c for c in DEPLOY_CHECKLIST if c.status == "PENDING"]
    if len(pending_items) > 0:
        print(f"⚠️ {len(pending_items)} 项检查未完成, 不建议立即部署")
        for item in pending_items:
            print(f"  [{item.id}] {item.name}")
            print(f"    → {item.note}")
    else:
        print("✅ 所有检查通过, 可以部署候选配置")
```

### 3.2 黑名单在 fund_flow_bot 中的实现

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: fund_flow_bot.py — 黑名单集成
# 确认 bot 正确读取并执行黑名单逻辑
# ════════════════════════════════════════════════════════════════

class FundFlowBot:

    def __init__(self, config_path):
        self.config         = load_config(config_path)
        # 黑名单从配置读取, 支持热重载
        self.symbol_blacklist = set(
            self.config.get("risk", {}).get("symbol_blacklist", [])
        )
        logger.info(f"[BLACKLIST] Active blacklist: {self.symbol_blacklist}")

    def should_enter_position(self, signal) -> tuple[bool, str]:
        """
        入场前检查: 黑名单过滤是第一道门
        优先级高于信号质量检查
        """

        # ── 第一道: 黑名单检查 ─────────────────────────────────────
        if signal.symbol in self.symbol_blacklist:
            logger.debug(f"[BLACKLIST_REJECT] {signal.symbol} is blacklisted, skip")
            self.metrics.blacklist_rejected += 1
            return False, "blacklist"

        # ── 第二道: 信号质量检查 ───────────────────────────────────
        if signal.score < self.config.long_open_threshold:
            return False, "score_below_threshold"

        # ── 第三道: 容量检查 ───────────────────────────────────────
        capacity_ok, reason = self._check_capacity(signal.symbol)
        if not capacity_ok:
            return False, reason

        # ── 第四道: 预交易风险门控 ─────────────────────────────────
        risk_ok, reason = self.pretrade_risk_gate.check(signal)
        if not risk_ok:
            return False, reason

        return True, "accepted"

    def reload_blacklist(self):
        """
        支持热重载: 在不重启 bot 的情况下更新黑名单
        可以由运维脚本触发
        """
        fresh_config = load_config(self.config_path)
        new_blacklist = set(
            fresh_config.get("risk", {}).get("symbol_blacklist", [])
        )

        added   = new_blacklist - self.symbol_blacklist
        removed = self.symbol_blacklist - new_blacklist

        if added or removed:
            logger.warning(f"[BLACKLIST_RELOAD] "
                           f"Added: {added}, Removed: {removed}")
            self.symbol_blacklist = new_blacklist

        return {"added": list(added), "removed": list(removed)}


    def emit_blacklist_metrics(self):
        """
        将黑名单指标写入监控系统
        用于追踪: 有多少候选被黑名单拦截, 这些候选如果成交会如何
        """
        return {
            "blacklist_symbols":  list(self.symbol_blacklist),
            "blacklist_rejected": self.metrics.blacklist_rejected,
            # 注意: 不追踪被拒绝后的假设收益 (look-ahead bias 风险)
        }
```

### 3.3 候选配置与生产配置对比验证

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: validate_candidate_config.py
# 确认候选配置相比生产配置只有预期的改动
# ════════════════════════════════════════════════════════════════

function validate_candidate_config(prod_path, candidate_path):
    prod      = load_json(prod_path)
    candidate = load_json(candidate_path)

    diffs = deep_diff(prod, candidate)

    EXPECTED_DIFFS = {
        "risk.symbol_blacklist": {
            "before": [],
            "after":  ["ADAUSDT", "FETUSDT"],
        }
    }

    unexpected_diffs = {}
    for key, change in diffs.items():
        if key not in EXPECTED_DIFFS:
            unexpected_diffs[key] = change
        elif change != EXPECTED_DIFFS[key]:
            unexpected_diffs[key] = {
                "expected": EXPECTED_DIFFS[key],
                "actual":   change
            }

    if unexpected_diffs:
        print("❌ 候选配置包含非预期改动:")
        for key, change in unexpected_diffs.items():
            print(f"  {key}: {change}")
        return False

    print("✅ 候选配置仅包含预期的 symbol_blacklist 改动")
    return True


# 运行验证
validate_candidate_config(
    prod_path      = "config/trading_config_fund_flow.json",
    candidate_path = "config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json"
)
```

---

## 4. 下一波消融计划 — 符号范围止损

### 4.1 设计原则 (基于全局止损失败的教训)

```text
全局止损收紧实验的核心失败原因:

  S5_hard_stop_1.5pct 案例分析:
    亏损笔数:   14 → 20  (+6 笔新增亏损)
    总亏损:    -1141 → -1685  (+544)
    MDD:        5.01% → 8.43%  (+3.42 ppt)

  为什么更紧的止损反而亏更多?
    原因1: 1.5% 硬止损在正常波动中被噪音触发
           本来会在 TP 退出的交易, 被提前止损
    原因2: 大亏损集中在 ADA/FET 两个符号
           这两个符号的波动特征与其他符号不同
           全局硬止损无法区分"好波动"和"坏波动"
    原因3: S2_max_stop_1.5pct 仍有 -2.82% 最大亏损
           说明填充滑点问题是符号特异性的, 不是全局机制问题

  结论: 止损工作必须在符号层面进行, 不能全局操作
```

### 4.2 剩余尾险符号的止损实验设计

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: symbol_scoped_stop_ablation.py
# 前提: ADA+FET 已黑名单, 以候选配置为新基准
# 目标: 进一步压制 XLMUSDT, SOLUSDT, ALGOUSDT 的尾部亏损
# ════════════════════════════════════════════════════════════════

# 新基准 (ADA+FET 黑名单后的结果)
NEW_BASELINE = {
    "return":         0.3523,
    "win_rate":       0.9412,
    "profit_factor":  13.58,
    "max_drawdown":   0.0322,
    "total_trades":   153,
}

# 剩余问题符号 (ADA+FET 移除后仍然有大亏损的)
REMAINING_RISK_SYMBOLS = {
    "XLMUSDT":  {"worst_loss_pct": -0.0112, "net_pnl": -59.79,  "trades": 3,  "wr": 0.667},
    "SOLUSDT":  {"worst_loss_pct": -0.0275, "net_pnl": +5.12,   "trades": 8,  "wr": 0.750},
    "ALGOUSDT": {"worst_loss_pct": -0.0294, "net_pnl": +22.10,  "trades": 6,  "wr": 0.833},
    "JSTUSDT":  {"worst_loss_pct": -0.0234, "net_pnl": None,    "trades": None, "wr": None},
}

# 下一波消融套件 (以候选配置为基准)
SYMBOL_STOP_ABLATIONS = [
    # ── SS组: 符号范围止损测试 ─────────────────────────────────
    {
        "name":   "SS0_new_baseline",
        "config": CANDIDATE_CONFIG,     # ADA+FET 黑名单, 其他不变
        "notes":  "新基准线 (ADA+FET blacklist)"
    },
    {
        "name":   "SS1_xlm_tight_stop_1pct",
        "config": CANDIDATE_CONFIG.with_override({
            "symbol_risk_overrides": {
                "XLMUSDT": {"max_stop_loss_pct": 0.010}
            }
        }),
        "notes":  "仅 XLMUSDT 止损收紧至1%, 其他符号不变"
    },
    {
        "name":   "SS2_sol_tight_stop_1_5pct",
        "config": CANDIDATE_CONFIG.with_override({
            "symbol_risk_overrides": {
                "SOLUSDT": {"max_stop_loss_pct": 0.015}
            }
        }),
        "notes":  "仅 SOLUSDT 止损收紧至1.5%"
    },
    {
        "name":   "SS3_algo_jst_tight_stop",
        "config": CANDIDATE_CONFIG.with_override({
            "symbol_risk_overrides": {
                "ALGOUSDT": {"max_stop_loss_pct": 0.015},
                "JSTUSDT":  {"max_stop_loss_pct": 0.015},
            }
        }),
        "notes":  "ALGOUSDT + JSTUSDT 止损收紧至1.5%"
    },
    {
        "name":   "SS4_all_tail_risk_tight",
        "config": CANDIDATE_CONFIG.with_override({
            "symbol_risk_overrides": {
                "XLMUSDT":  {"max_stop_loss_pct": 0.010},
                "SOLUSDT":  {"max_stop_loss_pct": 0.015},
                "ALGOUSDT": {"max_stop_loss_pct": 0.015},
                "JSTUSDT":  {"max_stop_loss_pct": 0.015},
            }
        }),
        "notes":  "全部剩余尾险符号同时收紧止损"
    },
    {
        "name":   "SS5_tier3_blacklist_xlm",
        "config": CANDIDATE_CONFIG.with_override({
            "risk": {"symbol_blacklist": ["ADAUSDT", "FETUSDT", "XLMUSDT"]}
        }),
        "notes":  "扩大黑名单: 追加 XLMUSDT"
    },
]


function run_symbol_stop_ablation_suite():
    print("新基准 (ADA+FET 黑名单):")
    print(f"  Return={NEW_BASELINE['return']:+.2%}, "
          f"WR={NEW_BASELINE['win_rate']:.2%}, "
          f"PF={NEW_BASELINE['profit_factor']:.2f}, "
          f"MDD={NEW_BASELINE['max_drawdown']:.2%}")
    print()

    for ablation in SYMBOL_STOP_ABLATIONS:
        result = run_backtest(ablation["config"])

        # 相对新基准的变化
        return_delta = result.total_return - NEW_BASELINE["return"]
        wr_delta     = result.win_rate     - NEW_BASELINE["win_rate"]
        mdd_delta    = result.max_drawdown - NEW_BASELINE["max_drawdown"]

        flag = ""
        if result.win_rate < 0.90:              flag += " ⚠WR_DROP"
        if result.max_drawdown > 0.05:          flag += " ⚠MDD_HIGH"
        if result.profit_factor < 5.0:          flag += " ⚠PF_DROP"
        if result.total_trades < 140:           flag += " ⚠FEW_TRADES"

        print(f"{ablation['name']:<30} "
              f"ret={result.total_return:>+7.2%}({return_delta:>+6.2%}) "
              f"wr={result.win_rate:.2%}({wr_delta:>+5.2%}) "
              f"pf={result.profit_factor:>6.2f} "
              f"mdd={result.max_drawdown:.2%}({mdd_delta:>+5.2%}) "
              f"n={result.total_trades}"
              f"{flag}")
```

### 4.3 符号范围止损的代码实现

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: macd_strategy_v2.py — 符号范围止损覆盖
# 在全局止损参数之外, 允许针对特定符号设置更严格的止损
# ════════════════════════════════════════════════════════════════

class SymbolRiskOverrideManager:
    """
    管理符号级别的风险参数覆盖
    覆盖项只能比全局参数"更严格", 不允许放松
    """

    def __init__(self, global_config, symbol_overrides: dict):
        self.global_config    = global_config
        self.symbol_overrides = symbol_overrides  # 来自配置文件

    def get_effective_stop_pct(self, symbol: str) -> float:
        """
        获取指定符号的有效止损百分比
        符号覆盖只允许收紧, 不允许放松全局设置
        """
        global_stop = self.global_config.max_stop_loss_pct

        if symbol in self.symbol_overrides:
            override_stop = self.symbol_overrides[symbol].get("max_stop_loss_pct")
            if override_stop is not None:
                # 取两者中更严格(更小)的值
                effective_stop = min(global_stop, override_stop)
                if effective_stop < global_stop:
                    logger.debug(f"[SYMBOL_OVERRIDE] {symbol}: "
                                 f"stop {global_stop:.3f} → {effective_stop:.3f}")
                return effective_stop

        return global_stop

    def get_effective_position_size_ratio(self, symbol: str) -> float:
        """
        获取指定符号的仓位大小倍数
        1.0 = 正常仓位, < 1.0 = 缩仓
        """
        if symbol in self.symbol_overrides:
            return self.symbol_overrides[symbol].get("position_size_ratio", 1.0)
        return 1.0


class PositionExitManager:

    def __init__(self, config, symbol_risk_manager: SymbolRiskOverrideManager):
        self.config              = config
        self.symbol_risk_manager = symbol_risk_manager

    def compute_stop_price(self, position) -> float:
        """
        计算有效止损价: 考虑符号级别覆盖
        """
        # 获取该符号的有效最大止损
        effective_max_stop = self.symbol_risk_manager.get_effective_stop_pct(
            position.symbol
        )

        # 基础动态止损 (ATR based)
        atr_stop_distance = position.entry_atr * self.config.atr_stop_multiplier
        atr_stop_pct      = atr_stop_distance / position.entry_price

        # 限制在 [min_stop, symbol_effective_max_stop] 区间
        clamped_stop_pct = clip(
            atr_stop_pct,
            min_val = self.config.stop_loss_pct,       # 0.5% 最小止损
            max_val = effective_max_stop,               # 符号特定上限
        )

        stop_price = position.entry_price * (1 - clamped_stop_pct)
        return stop_price

    def check_exit(self, position, bar) -> Optional[ExitSignal]:
        stop_price = self.compute_stop_price(position)

        if bar.low <= stop_price:
            # 以止损价填充 (不是 bar.close)
            fill_price = max(stop_price, bar.low)
            return ExitSignal(
                reason     = "stop_loss_intrabar",
                fill_price = fill_price,
                stop_price = stop_price,  # 记录用于审计
            )
        return None
```

---

## 5. 下一波消融计划 — Light TP 精细化

### 5.1 从实测结果重新理解 light_tp

```text
实测对比:
  baseline        (+26.23%): light_tp=67笔, 正常TP=24笔, 总162笔
  B1_disable_ltp  (+24.76%): 仅24+α笔正常TP, 总94笔 ← 交易数崩塌

B1 失败的根本原因:
  禁用 light_tp 后, 交易数从 162 降到 94 (-42%)
  这说明很多交易的信号结构本来就只支持 light_tp 类型的退出
  强行让这些交易跑到 intrabar_tp 会导致: 更多被 stop_loss 出局

B3 的中性结果 (+26.76% vs +26.23%):
  ADX<20 门控后, light_tp 交易减少
  但整体回报提升很小, 说明被移除的 light_tp 交易质量本来就一般

当前结论:
  light_tp 不是 "坏机制", 它是策略的一部分
  问题不是"禁用 light_tp"
  问题是"哪些 light_tp 交易可以被升级为更长的持仓"
```

### 5.2 Light TP 分类实验

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: light_tp_classification_ablation.py
# 目标: 找到 light_tp 中可以安全转为 tiered_tp 的子集
# 前提: ADA+FET 已黑名单
# ════════════════════════════════════════════════════════════════

LIGHT_TP_ABLATIONS = [
    # ── LT组: 基于不同维度的 light_tp 条件化 ──────────────────
    {
        "name":   "LT0_new_baseline",
        "config": CANDIDATE_CONFIG,
        "notes":  "新基准 (ADA+FET 黑名单, light_tp 默认)"
    },
    {
        "name":   "LT1_adx_gate_25",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_adx": 25   # ADX>25 不用 light_tp (vs B3 的 ADX>20)
        }),
        "notes":  "ADX>25 禁用 light_tp (比B3更保守)"
    },
    {
        "name":   "LT2_adx_gate_30",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_adx": 30
        }),
        "notes":  "ADX>30 禁用 light_tp (强趋势不早退)"
    },
    {
        "name":   "LT3_score_gate_072",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_score": 0.720   # score>0.72 不用 light_tp
        }),
        "notes":  "高分信号不用 light_tp"
    },
    {
        "name":   "LT4_combined_adx30_score072",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_adx":   30,
            "sim_light_tp_max_score": 0.720,
            "sim_light_tp_mode":      "AND",  # 两个条件同时满足才禁用
        }),
        "notes":  "ADX>30 且 score>0.72 才禁用 light_tp (最保守)"
    },
    {
        "name":   "LT5_combined_adx25_score070_OR",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_adx":   25,
            "sim_light_tp_max_score": 0.700,
            "sim_light_tp_mode":      "OR",   # 任一条件满足即禁用
        }),
        "notes":  "ADX>25 或 score>0.70 禁用 light_tp (激进版)"
    },
    {
        "name":   "LT6_tiered_tp_for_high_adx",
        "config": CANDIDATE_CONFIG.with_override({
            "sim_light_tp_max_adx": 30,      # ADX>30 不用 light_tp
            "tiered_tp_enabled":    True,     # 改用分层止盈
            "tiered_tp_trigger_adx": 30,      # 触发条件与 light_tp 禁用一致
            "tiered_tp_layers": [             # 分层配置
                {"pct": 0.006, "ratio": 0.50},
                {"pct": 0.015, "ratio": 0.30},
                {"pct": 0.025, "ratio": 0.20},
            ]
        }),
        "notes":  "ADX>30 时用分层止盈替代 light_tp (关键实验)"
    },
]


function analyze_light_tp_upgrade_candidates(trades_csv):
    """
    分析哪些 light_tp 交易是"可升级"的
    即: 如果不提前退出, 后续走势是否支持更大收益
    """
    light_tp_trades = load_trades(trades_csv).filter(
        exit_reason == "sim_light_take_profit"
    )

    for trade in light_tp_trades:
        # 检查退出后的走势
        bars_after = get_subsequent_bars(trade.symbol, trade.exit_time, n=12)
        max_subsequent_gain = max(
            (b.high - trade.exit_price) / trade.exit_price
            for b in bars_after
        )

        trade.upgrade_potential = max_subsequent_gain
        trade.is_upgradeable    = (max_subsequent_gain > 0.015)  # 如果持有会有>1.5%收益
        trade.adx_at_exit       = bars_after[0].adx if bars_after else None

    # 分析可升级比例
    upgradeable = [t for t in light_tp_trades if t.is_upgradeable]
    print(f"可升级 light_tp 交易: {len(upgradeable)}/{len(light_tp_trades)} "
          f"= {len(upgradeable)/len(light_tp_trades):.1%}")

    # 高ADX中的可升级比例
    high_adx = [t for t in light_tp_trades if t.adx_at_exit and t.adx_at_exit > 30]
    high_adx_upgradeable = [t for t in high_adx if t.is_upgradeable]
    print(f"ADX>30 中可升级比例: {len(high_adx_upgradeable)}/{len(high_adx):.1%}")
    # 如果这个比例 > 50%, LT6 (tiered_tp for high ADX) 值得推进
```

---

## 6. 不应再测试的方向

```text
基于已完成的消融实验, 以下方向已被数据否定:

════════════════════════════════════════════════════════════════
 CLOSED: 不再测试, 不要在代码/配置中实现
════════════════════════════════════════════════════════════════

[CLOSED-1] 全局 hard_stop_loss_pct
  原因: S4/S5 明确显示全局硬止损降低总回报, 增加亏损笔数和MDD
  替代: 符号范围止损 (SS组) 仍可测试

[CLOSED-2] 全局 max_stop_loss_pct 收紧 (从 2.5% 向下)
  原因: S1/S2 明确显示全局止损收紧适得其反
  替代: 符号范围覆盖 (SS组)

[CLOSED-3] 完全禁用 sim_light_take_profit
  原因: B1 交易数-42%, 回报-1.47%, 胜率-6%
  替代: 条件化使用 (LT组)

[CLOSED-4] max_active_symbols 扩容 (D1/D2)
  原因: 更多交易数未改善回报, 容量不是当前瓶颈
  替代: 不需要替代方向, 维持 max_active_symbols=3

[CLOSED-5] IOC → GTC 改造 (在现有信号质量下)
  原因: D1/D2 显示更多成交量不等于更高回报
         当前问题是信号结构, 不是执行填充率
  替代: 仅在信号结构改善后重新评估

════════════════════════════════════════════════════════════════
 OPEN: 仍然值得测试的方向
════════════════════════════════════════════════════════════════

[OPEN-1] 符号范围止损 (SS组) — 当前最高优先级
[OPEN-2] Light TP 条件化精细化 (LT组) — 次优先级
[OPEN-3] 扩展黑名单到 XLMUSDT (SS5) — 与 SS 组一起测试
[OPEN-4] 60d/90d 扩展回测 — 验证候选配置稳健性
[OPEN-5] 做空/反转路径审查 — 低优先级 (当前 30d 看涨期内收益有限)
```

---

## 7. Config DIFF

```diff
# ════════════════════════════════════════════════════════════════
# DIFF 1: 立即可部署
# 生产配置 → 候选配置 (ADA+FET 黑名单)
# 文件: config/trading_config_fund_flow.json
# 候选: config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json
# ════════════════════════════════════════════════════════════════

--- a/config/trading_config_fund_flow.json
+++ b/config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json
@@ -1,5 +1,5 @@
 {
+  "_candidate_note": "blacklist ADA+FET, validated 2026-05-03, return +35.23% WR 94.12%",
   "strategy": {
     "stop_loss_pct": 0.005,
     "max_stop_loss_pct": 0.025,
@@ -30,7 +30,10 @@
   "risk": {
     "equity_usage_block": 0.85,
     "dd_exit_threshold": 0.10,
-    "symbol_blacklist": []
+    "symbol_blacklist": [
+      "ADAUSDT",
+      "FETUSDT"
+    ]
   }
 }
```

```diff
# ════════════════════════════════════════════════════════════════
# DIFF 2: 下一步实验准备 (未部署, 消融测试用)
# 添加符号范围止损覆盖支持
# 文件: config/trading_config_fund_flow.json
# ════════════════════════════════════════════════════════════════

--- a/config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json
+++ b/config/candidates/trading_config_fund_flow_symbol_stop_ss4_20260503.json
@@ -30,8 +30,23 @@
   "risk": {
     "equity_usage_block": 0.85,
     "dd_exit_threshold": 0.10,
     "symbol_blacklist": [
       "ADAUSDT",
       "FETUSDT"
-    ]
+    ],
+    "symbol_risk_overrides": {
+      "XLMUSDT": {
+        "max_stop_loss_pct": 0.010,
+        "note": "SS1: tight stop test, worst_loss was -1.12%"
+      },
+      "SOLUSDT": {
+        "max_stop_loss_pct": 0.015,
+        "note": "SS2: stop cap, worst_loss was -2.75%"
+      },
+      "ALGOUSDT": {
+        "max_stop_loss_pct": 0.015,
+        "note": "SS3: stop cap, worst_loss was -2.94%"
+      },
+      "JSTUSDT": {
+        "max_stop_loss_pct": 0.015,
+        "note": "SS3: stop cap, worst_loss was -2.34%"
+      }
+    }
   }
 }
```

```diff
# ════════════════════════════════════════════════════════════════
# DIFF 3: 代码层 — 符号范围止损覆盖支持
# 文件: src/fund_flow/macd_strategy_v2.py
# 注意: 仅在 SS 消融测试通过后合并
# ════════════════════════════════════════════════════════════════

--- a/src/fund_flow/macd_strategy_v2.py
+++ b/src/fund_flow/macd_strategy_v2.py
@@ -[CONFIG_INIT] @@
 class MACDStrategyV2Engine:
     def __init__(self, config):
         self.config = config
+        # 符号范围风险覆盖 (可选配置项)
+        self.symbol_risk_overrides = config.get("risk", {}).get(
+            "symbol_risk_overrides", {}
+        )
+        if self.symbol_risk_overrides:
+            logger.info(f"[SYMBOL_RISK] Loaded overrides for: "
+                        f"{list(self.symbol_risk_overrides.keys())}")

@@ -[STOP_PRICE_CALC] @@
-    def _compute_effective_stop_pct(self, symbol: str) -> float:
-        """使用全局 max_stop_loss_pct"""
-        return self.config.max_stop_loss_pct

+    def _compute_effective_stop_pct(self, symbol: str) -> float:
+        """
+        获取符号的有效最大止损
+        符号级覆盖只允许收紧, 不允许放松全局配置
+        """
+        global_max = self.config.max_stop_loss_pct   # 全局上限 (e.g. 2.5%)
+
+        if symbol in self.symbol_risk_overrides:
+            override = self.symbol_risk_overrides[symbol]
+            symbol_max = override.get("max_stop_loss_pct")
+            if symbol_max is not None:
+                effective = min(global_max, symbol_max)  # 只能收紧
+                logger.debug(f"[SYMBOL_STOP] {symbol}: "
+                             f"global={global_max:.3f} → effective={effective:.3f}")
+                return effective
+
+        return global_max

@@ -[STOP_LOSS_CHECK] @@
     def _check_stop_loss(self, position, bar):
-        stop_price = position.stop_price
+        # 每次检查时重新计算有效止损 (支持符号覆盖)
+        effective_max_stop = self._compute_effective_stop_pct(position.symbol)
+        current_stop_pct   = (position.entry_price - position.stop_price) / position.entry_price
+
+        # 如果当前动态止损已超过符号上限, 强制收紧
+        if current_stop_pct > effective_max_stop:
+            position.stop_price = position.entry_price * (1 - effective_max_stop)
+            logger.info(f"[STOP_CLAMP] {position.symbol}: "
+                        f"stop clamped from {current_stop_pct:.3f} "
+                        f"to {effective_max_stop:.3f}")
+
+        stop_price = position.stop_price
         if bar.low <= stop_price:
             fill_price = stop_price    # 以止损价填充 (非 bar.close)
             return ExitSignal("stop_loss_intrabar", fill_price)
         return None

@@ -[BLACKLIST_CHECK] @@
     def should_enter(self, signal) -> tuple[bool, str]:
         """入场前检查"""
+        # 黑名单是最高优先级检查
+        blacklist = self.config.get("risk", {}).get("symbol_blacklist", [])
+        if signal.symbol in blacklist:
+            return False, "blacklist"
+
         if signal.score < self.config.long_open_threshold:
             return False, "score_threshold"
         # ... 其余检查
```

```diff
# ════════════════════════════════════════════════════════════════
# DIFF 4: 消融框架扩展 — 支持新基准和SS组
# 文件: scripts/run_ablation.py (或对应文件名)
# ════════════════════════════════════════════════════════════════

--- a/scripts/run_ablation.py
+++ b/scripts/run_ablation.py
@@ -[ABLATION_CONFIGS] @@
-BASELINE_CONFIG = "config/trading_config_fund_flow.json"

+# 第一阶段基准 (原生产配置)
+BASELINE_V1_CONFIG = "config/trading_config_fund_flow.json"
+# 第二阶段基准 (ADA+FET 黑名单后, SS/LT 实验的起点)
+BASELINE_V2_CONFIG = "config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json"

+# 消融输出目录分阶段管理
+ABLATION_OUTPUT_DIRS = {
+    "v1": "output/backtest/ablation_20260503_phase1/",
+    "v2": "output/backtest/ablation_20260503_phase2/",  # SS/LT 组
+}

@@ -[RESULT_COMPARISON] @@
 def print_results(results, baseline):
+    # 同时显示相对 v1 基准和 v2 基准的变化
+    v1_baseline = load_result("00_baseline")         # +26.23%
+    v2_baseline = load_result("SS0_new_baseline")    # +35.23%
+
     for r in results:
-        delta = r.total_return - baseline.total_return
-        print(f"{r.name:<30} ret={r.total_return:>+7.2%}({delta:>+5.2%}) ...")
+        delta_v1 = r.total_return - v1_baseline.total_return
+        delta_v2 = r.total_return - v2_baseline.total_return if v2_baseline else 0
+        print(f"{r.name:<30} "
+              f"ret={r.total_return:>+7.2%} "
+              f"(vs_v1:{delta_v1:>+5.2%} vs_v2:{delta_v2:>+5.2%}) "
+              f"wr={r.win_rate:.2%} pf={r.profit_factor:.2f} "
+              f"mdd={r.max_drawdown:.2%} n={r.total_trades}")
```

---

## 8. 执行脚本伪代码

### 8.1 候选配置 60d 验证

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: validate_candidate_60d.py
# 用更长窗口验证 ADA+FET 黑名单的稳健性
# ════════════════════════════════════════════════════════════════

function validate_candidate_extended():
    """
    在 30d 验证通过后, 运行 60d 扩展验证
    命令:
      python scripts/backtest_macd_v2.py \
        --config config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json \
        --strict-live-mode \
        --simulate-live-close-layers \
        --start-date 2026-01-03 \
        --end-date 2026-05-03 \
        --output-prefix output/backtest/candidate_60d_blacklist_ada_fet_20260503 \
        --initial-capital 10000
    """

    ACCEPT_CRITERIA = {
        "win_rate":       (">=", 0.90),   # 60d 目标略低于30d (更多样本)
        "total_return":   (">=", 0.60),   # 60d 目标: +60%+
        "profit_factor":  (">=", 4.00),   # PF 可以不及30d的13, 但需>4
        "max_drawdown":   ("<=", 0.07),   # 60d 允许略高于30d
        "total_trades":   (">=", 250),    # 足够样本量
    }

    result = load_backtest_result("output/backtest/candidate_60d_blacklist_ada_fet_20260503_summary.json")

    all_pass = True
    for metric, (op, threshold) in ACCEPT_CRITERIA.items():
        value = getattr(result, metric)
        passes = eval(f"{value} {op} {threshold}")
        status = "✅" if passes else "❌"
        print(f"  {status} {metric}: {value:.4f} {op} {threshold}")
        if not passes:
            all_pass = False

    if all_pass:
        print("\n✅ 60d 验证通过 → 建议推进到 staging 部署")
    else:
        print("\n❌ 60d 验证未通过 → 不部署, 需要进一步分析")
        print("   可能原因: 30d 窗口对 ADA/FET 表现特别差")
        print("   替代方案: 改用风险分层而非永久黑名单")

    return all_pass
```

### 8.2 停止测试决策函数

```python
# ════════════════════════════════════════════════════════════════
# PSEUDOCODE: ablation_decision_engine.py
# 自动判断每个消融结果是否值得继续追踪
# ════════════════════════════════════════════════════════════════

@dataclass
class AblationDecision:
    name:       str
    verdict:    str    # "PROMOTE" / "CONTINUE" / "ABANDON"
    reason:     str
    next_step:  str


def evaluate_ablation(result, baseline, thresholds):
    """
    评估一个消融实验的结果, 给出继续/放弃建议
    """
    # ── 硬性否决条件 ───────────────────────────────────────────
    if result.win_rate < thresholds.min_win_rate:
        return AblationDecision(
            name      = result.name,
            verdict   = "ABANDON",
            reason    = f"win_rate {result.win_rate:.2%} < floor {thresholds.min_win_rate:.2%}",
            next_step = "不继续此方向"
        )

    if result.max_drawdown > thresholds.max_mdd:
        return AblationDecision(
            name      = result.name,
            verdict   = "ABANDON",
            reason    = f"MDD {result.max_drawdown:.2%} > ceiling {thresholds.max_mdd:.2%}",
            next_step = "不继续此方向"
        )

    if result.profit_factor < thresholds.min_pf:
        return AblationDecision(
            name      = result.name,
            verdict   = "ABANDON",
            reason    = f"PF {result.profit_factor:.2f} < floor {thresholds.min_pf:.2f}",
            next_step = "不继续此方向"
        )

    # ── 促进条件 ───────────────────────────────────────────────
    return_improvement = result.total_return - baseline.total_return
    wr_improvement     = result.win_rate     - baseline.win_rate
    mdd_improvement    = baseline.max_drawdown - result.max_drawdown  # 正数=改善

    all_improved = (return_improvement > 0 and wr_improvement >= 0 and mdd_improvement >= 0)
    significant  = (return_improvement > 0.03 or wr_improvement > 0.01)

    if all_improved and significant:
        return AblationDecision(
            name      = result.name,
            verdict   = "PROMOTE",
            reason    = f"ret+{return_improvement:.2%}, wr+{wr_improvement:.2%}, "
                        f"mdd-{mdd_improvement:.2%}",
            next_step = "更新基准, 继续下一组实验"
        )

    # ── 中性: 继续实验但不提升 ─────────────────────────────────
    return AblationDecision(
        name      = result.name,
        verdict   = "CONTINUE",
        reason    = "改善不显著或指标有取舍",
        next_step = "尝试该方向的下一个变体"
    )


# 全局阈值 (基于新基准 F2 候选配置)
THRESHOLDS_PHASE2 = AblationThresholds(
    min_win_rate = 0.90,    # 不低于新基准 94% 的 90%
    max_mdd      = 0.055,   # 不超过新基准 3.22% 的 1.7x
    min_pf       = 5.00,    # 不低于新基准 13.58 的 ~37%
)
```

---

## 9. 决策树与路线图

```text
════════════════════════════════════════════════════════════════
 MACD V2 当前状态 (2026-05-03 消融后)
════════════════════════════════════════════════════════════════

 已完成:
   ✅ 初始消融 (B, D, F 组)
   ✅ 止损消融 (S 组)
   ✅ 候选配置验证 (ADA+FET blacklist)

 结论确认:
   ✅ 符号黑名单是最优单一杠杆
   ✅ 全局止损收紧有害
   ✅ 容量扩容无益 (在当前信号质量下)

════════════════════════════════════════════════════════════════
 立即行动 (本周)
════════════════════════════════════════════════════════════════

 Step 1: 运行 60d 扩展验证 (BT-02)
   目的: 确认候选配置非30d过拟合
   命令: backtest --days 60 --config candidate_blacklist_ada_fet
   通过条件: WR≥90%, Return≥+60%, PF≥4, MDD≤7%

 Step 2: 验证 ADA/FET 历史净PnL跨期 (BT-03)
   目的: 确认这两个符号在其他时期也是净亏损
   方法: 回测 Q4_2025 和 Q1_2026 两个分段

 Step 3 (If BT-02 & BT-03 通过): 部署候选配置
   方法: 复制候选配置为新生产配置
   监控: MDD告警 ≤5%, 异常亏损告警 单笔 ≤ -100

════════════════════════════════════════════════════════════════
 下一波实验 (BT-02通过后)
════════════════════════════════════════════════════════════════

 以候选配置为新基准, 运行 SS 组 (符号范围止损):
   SS1: XLMUSDT 止损 → 1.0%
   SS2: SOLUSDT 止损 → 1.5%
   SS3: ALGOUSDT+JSTUSDT 止损 → 1.5%
   SS4: 全部剩余尾险符号同时收紧
   SS5: 扩大黑名单追加 XLMUSDT

 之后 (SS 组稳定后): LT 组 (light_tp 精细化)
   LT2: ADX>30 不用 light_tp
   LT6: ADX>30 时改用分层止盈

════════════════════════════════════════════════════════════════
 预期目标 (候选 + SS + LT 组优化后)
════════════════════════════════════════════════════════════════

 短期 (候选配置部署后):
   Return: +35.23%  MDD: 3.22%  WR: 94.12%  PF: 13.58

 中期 (SS 组最优后):
   Return 目标: +40%~+45%  MDD 目标: ≤4%  WR 目标: ≥93%

 长期 (LT 组优化后):
   Return 目标: +50%~+60%  MDD 目标: ≤5%  WR 目标: ≥92%

 注: 所有目标均为 30d strict-live 回测, $10,000 初始资本
     实际表现取决于市场状态是否延续当前特征
════════════════════════════════════════════════════════════════
```
