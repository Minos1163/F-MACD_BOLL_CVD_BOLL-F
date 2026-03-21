# MACD_MTF_Strategy V10 → V11 优化建议

> 文档用途：基于 V10 当前 live 参数与归因复核结果，提出下一轮可执行优化方向  
> 当前 live 基线：V10（V9.2A）`+99.39%`，PF `3.04`，MDD `10.10%`，胜率 `70.88%`  
> 原则：不破坏当前正收益骨架，优先处理已归因的负向残留

---

## 一、当前策略健康度评估

| 维度 | 当前值 | 评级 | 说明 |
| --- | --- | --- | --- |
| 月收益率 | `+99.39%` | ✅ 优秀 | 接近翻倍，V8→V10 持续改善 |
| 盈利因子 | `3.04` | ✅ 优秀 | 首次突破 3.0，结构质量扎实 |
| 胜率 | `70.88%` | ✅ 良好 | 相比 V8/A 微降 0.55pp，属正常交换 |
| 最大回撤 | `10.10%` | 🟡 可改善 | 仍在同一 stress window，尚有压缩空间 |
| 交易数 | `498` | ✅ 健康 | 相比 V8/A 减少 13 笔，精化方向正确 |
| 增量集中度 | top 3 币占 92.82% | 🔴 需关注 | 不够分散，鲁棒性仍有隐患 |

**整体判断：** V10 已进入高质量运行区间，当前最主要的问题不是"策略框架不对"，而是：

1. **已知回吐币种（LINK/ONDO/LTC/MORPHO/TRUMP）尚未处理**
2. **增量集中度过高，分散性不足**
3. **`flip_bullish` long side 在 session 风控下出现弹性损失**
4. **试仓多空门槛不对称（0.75 vs 0.30）可能导致多空质量差异**

---

## 二、优化全景

```
V10 当前架构
├── 方向层（4H 主 + 1H 轻确认）             → 【优化 A】4H histogram 强弱分档
├── 入场层（15M 时机 + pre-flip 试仓）       → 【优化 B】试仓门槛对称化 + 自动升仓
├── 结构层（BOLL + VWAP）                   → 【优化 C】vwap_score 仓位乘数
├── 过滤层（ADX pocket + CVD context）       → 【优化 D】过滤器精化（叠加二次确认）
├── 离场层（shrink exit + breakeven）        → 【优化 E】shrink exit 条件扩展
├── 风控层（session 降仓 + 连亏冷却）        → 【优化 F】watchlist 币种节流
└── 组合层（多币种同时持仓）                 → 【优化 G】增量分散化
```

---

## 三、优化建议详情

### 优先级 🔴：有归因支持，低改动风险，建议第一批验证

---

#### 优化 F：watchlist 币种单独节流（最高优先级）

**问题来源：**

归因复核已明确以下币种在 V9.2A 相对 V8/A 存在显著回吐：

| 币种 | Delta |
| --- | --- |
| `LINKUSDT` | `-287.99` |
| `ONDOUSDT` | `-123.80` |
| `LTCUSDT` | `-81.09` |
| `MORPHOUSDT` | `-63.09` |
| `TRUMPUSDT` | `-35.75` |

这不是随机噪声，归因文档已明确指出需要做 symbol 级节流，"而不是先动策略骨架"。

**建议方案 F1：watchlist 币种仓位节流**

```json
"symbol_risk_tiers": {
  "watchlist_symbols": [
    "LINKUSDT", "ONDOUSDT", "LTCUSDT", "MORPHOUSDT", "TRUMPUSDT"
  ],
  "watchlist_max_position_portion": 0.40,
  "watchlist_max_leverage": 2,
  "watchlist_apply_session_scale_double": true
}
```

- 对以上 5 个币种单独限制仓位和杠杆
- 在 session 高风险窗口内，对 watchlist 币种做双重缩仓（session scale × 0.8）
- 不禁止开仓，保留信号参与资格

**建议方案 F2：动态 watchlist（实盘监控版）**

在 live 实盘中，建立滚动 14 天的币种级盈亏 Z-score 监控：

```json
"dynamic_symbol_throttle": {
  "enabled": true,
  "rolling_window_days": 14,
  "trigger_pnl_zscore": -1.5,
  "throttle_position_scale": 0.5,
  "recovery_pnl_zscore": -0.5
}
```

- 当某币种 14 日盈亏 Z-score 低于 -1.5 时，自动降到半仓
- 当恢复到 -0.5 以上时，恢复正常仓位
- 不需要人工维护 watchlist，自动跟踪实盘表现

---

#### 优化 G：增量分散化（针对集中度风险）

**问题来源：**

归因复核显示：top 3 symbol delta 占总增量 92.82%，这意味着：

- V10 的超额收益目前高度依赖 `SOLUSDT / TAOUSDT / ICPUSDT` 三个币种
- 如果这三个币种后续行情反转，V10 的优势可能被大幅侵蚀

**建议方案 G1：单币盈亏贡献上限**

```json
"portfolio_concentration_control": {
  "enabled": true,
  "max_single_symbol_pnl_contribution_pct": 0.25,
  "rebalance_check_period_days": 7
}
```

- 任意单币种累计盈亏贡献不超过总盈亏的 25%
- 超过后该币种在下一个检查周期内仓位自动缩减至 50%
- 本质是"让好币种不要占满所有弹药"

**建议方案 G2：coin sector 分组约束**

将 36 个标的按市值/流动性分组，约束同组最大同时持仓数：

```json
"sector_position_limit": {
  "large_cap": { "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], "max_positions": 2 },
  "mid_cap": { "max_positions": 2 },
  "small_cap": { "max_positions": 1 }
}
```

- 防止同一市值层级的资金过度集中
- 尤其是避免 `SOLUSDT + AAVEUSDT + ICPUSDT` 同时满仓持有

---

### 优先级 🟠：中价值，中风险，建议第二批验证

---

#### 优化 C：vwap_score 仓位乘数（精化 D 加仓逻辑）

**问题来源：**

V10 的 session 风控已经解决了"时段级"的仓位问题，但"信号级"的仓位质量分层仍未实现。当前 `short_dual_pressure` 的强弱信号拿的是相同仓位。

**建议方案 C1：vwap_score 三档仓位乘数**

```json
"vwap_score_position_tiers": {
  "apply_to_states": ["short_dual_pressure", "flip_bullish"],
  "tiers": [
    { "min": 0.12, "max": 0.20, "position_mult": 0.80 },
    { "min": 0.20, "max": 0.30, "position_mult": 1.00 },
    { "min": 0.30, "max": 1.00, "position_mult": 1.15 }
  ]
}
```

- VWAP 位置差（0.12~0.20）时，降到 80% 仓位
- VWAP 位置好（≥0.30）时，允许 115% 仓位（在上限范围内）
- 这直接解决"高信号分稀释低 VWAP 分"导致的入场质量问题

**建议方案 C2：signal_score 分档加仓**

```json
"signal_score_position_tiers": {
  "apply_to_states": ["short_dual_pressure"],
  "tiers": [
    { "min": 0.84, "max": 0.90, "position_bonus": 0.00 },
    { "min": 0.90, "max": 0.95, "position_bonus": 0.05 },
    { "min": 0.95, "max": 1.00, "position_bonus": 0.10 }
  ]
}
```

- 低分段（0.84~0.90）不给加仓 bonus
- 高分段（≥0.95）才允许加仓至 110% 基础仓位

---

#### 优化 B：试仓参数对称化

**问题来源：**

当前试仓参数多空不对称：

```
preflip_trial_min_shrink_pct_long  = 0.75   ← 偏保守
preflip_trial_min_shrink_pct_short = 0.30   ← 偏宽松
```

这可能导致：多头试仓条件过严（错过机会），空头试仓条件过松（误入偏弱信号）。

**建议方案 B1：多空对称化**

```json
"preflip_trial_min_shrink_pct_long": 0.60,
"preflip_trial_min_shrink_pct_short": 0.40
```

- 多头从 0.75 降至 0.60（小幅放宽，不过度保守）
- 空头从 0.30 提至 0.40（略微收紧，减少弱信号误入）

**建议方案 B2：试仓自动升正仓**

当试仓开出后，若 2~3 根 4H bar 内方向明确确认翻转：

```json
"trial_to_full_upgrade": {
  "enabled": true,
  "upgrade_after_4h_bars": 2,
  "require_4h_flip_confirmed": true,
  "upgrade_position_scale": 0.65
}
```

- 不等下一个完整信号周期，自动补仓
- 补仓尺寸为正常仓位的 65%（而不是直接满仓）

---

#### 优化 D：过滤器叠加二次确认

**问题来源：**

V8/A 的两条定向过滤器（ADX pocket + CVD context）当前只有单层条件，存在轻微误杀风险。

**建议方案 D1：ADX 过滤叠加 BOLL 中轨斜率**

```json
"green_bar_growing_short_filter_v2": {
  "adx_1h_range": [25.0, 30.0],
  "require_bb_middle_slope_1h_lte": 0.0,
  "bb_slope_lookback_1h": 3
}
```

- 在 ADX 区间过滤的基础上，额外要求 1H BOLL 中轨斜率 ≤ 0
- 双重条件才否决，减少强趋势段被误杀

**建议方案 D2：CVD 过滤叠加 4H 方向确认**

```json
"flip_bullish_cvd_filter_v2": {
  "max_cvd_upper_wick_ratio": 0.20,
  "min_cvd_1h_delta_ratio": 0.03,
  "require_4h_histogram_bearish": true
}
```

- 翻多否决条件叠加"4H histogram 仍为负"
- 避免在 4H 已明确翻多加速段误杀 `flip_bullish` 信号

---

### 优先级 🟢：结构性扩展，建议第三批验证

---

#### 优化 E：shrink exit 条件扩展

V10 保留了 `exit_4h_require_profit = true`，不接受弱亏离场。当前观察仍有 `stop_loss_intrabar` 发生，说明这个问题还没有完全解决。

建议在**第三批**验证以下方案，不建议提前：

```json
"exit_4h_require_profit": false,
"exit_4h_min_shrink_pct": 0.30,
"exit_4h_weak_loss_max_pct": -0.001
```

- 只有在亏损 < 0.1% 且 shrink ≥ 30% 时才允许小亏离场
- `shrink_bars = 2` 保持不变
- 这个方案上一轮因担心"回撤恶化"而未采用，需要单独 profile 验证后再切

---

#### 优化 A：4H 方向强弱分档

在 4H 作为主方向时，当前只做方向判断，不区分强弱。建议第三批验证：

```json
"4h_direction_tiers": {
  "weak_threshold": 0.0001,
  "weak_position_scale": 0.70,
  "weak_require_1h_strong_confirmation": true
}
```

- 弱 4H histogram 时，仓位缩至 70% 且要求 1H 给出明确确认
- 强 4H 时保持当前逻辑不变

---

## 四、优化优先级汇总

| 优先级 | 优化项 | 预期改善维度 | 实现难度 | 建议批次 |
| --- | --- | --- | --- | --- |
| 🔴 最高 | F1：watchlist 5 币静态节流 | 减少已归因的回吐 | 低 | 第 1 批 |
| 🔴 最高 | F2：动态 Z-score 节流 | 实盘自适应风控 | 中 | 第 1 批 |
| 🔴 最高 | G1：单币盈亏贡献上限 | 降集中度风险 | 中 | 第 1 批 |
| 🟠 高 | C1：vwap_score 三档仓位乘数 | 提入场质量 | 中 | 第 2 批 |
| 🟠 高 | C2：signal_score 分档加仓 | 提盈利因子 | 中 | 第 2 批 |
| 🟠 高 | B1：试仓门槛对称化 | 多空平衡 | 低 | 第 2 批 |
| 🟠 中 | D1：ADX + BOLL 斜率二次确认 | 减少误杀 | 低 | 第 2 批 |
| 🟠 中 | D2：CVD + 4H histogram 确认 | 减少翻多误杀 | 低 | 第 2 批 |
| 🟠 中 | G2：sector 分组持仓约束 | 降集中度风险 | 中 | 第 2 批 |
| 🟢 低 | B2：试仓自动升正仓 | 提收益弹性 | 高 | 第 3 批 |
| 🟢 低 | E：弱亏损 shrink exit | 减 stop_loss_intrabar | 中 | 第 3 批 |
| 🟢 低 | A：4H 强弱分档 | 降弱趋势暴露 | 中 | 第 3 批 |

---

## 五、建议验证顺序

**第 1 批（风控补全）：** F1 + F2 + G1

- 全部只影响仓位大小，不改任何信号逻辑
- 目标：将 watchlist 币种回吐收窄，集中度从 92.82% 降至 70% 以内
- 若 MDD 进一步从 10.10% 降至 8% 以内且收益保持 90%+，第 1 批成立

**第 2 批（质量精化）：** C1 + C2 + B1 + D1 + D2

- 在第 1 批稳定后再验证
- 目标：PF 从 3.04 提升至 3.3+，胜率回升至 72%+

**第 3 批（结构扩展）：** B2 + E + A

- 工程难度较高，只在前两批验证稳定后再推进
- E（弱亏离场）需要单独 profile 谨慎验证，避免重演回撤恶化

---

## 六、明确不建议做的方向

| 方向 | 原因 |
| --- | --- |
| 重新引入 `short_retest_reject` | 历史归因已确认为净负贡献，永久关闭 |
| 重新启用 `short_quality_filter` | 与当前 4H 主方向架构重叠且精度低于定向过滤器 |
| 全面扩展信号类型 | 当前 498 笔交易结构已足够，先优化质量再扩展规模 |
| 将 session 风控扩展到全信号类型 | V10 归因已显示过度 session 限制会损害 `flip_bullish` 盈利弹性 |
| 降低 `exit_4h_shrink_bars` 至 1 | 单根 bar 收缩不可靠，误触率过高 |
| 放开连亏冷却至 90min | 当前 30min 已够用，90min 会显著减少后续有效信号参与 |

---

## 七、实盘观察要点（V10 live 阶段）

在等待第 1 批优化验证期间，实盘需要持续监控以下指标：

**币种级：**
- `LINKUSDT / ONDOUSDT / LTCUSDT / MORPHOUSDT / TRUMPUSDT` 的单币盈亏是否与回测一致
- `SOLUSDT / TAOUSDT / ICPUSDT` 的贡献集中度是否持续

**时段级：**
- `03:00~05:30 UTC` 时段的 `short_dual_pressure` 止损率是否下降
- `14:30~16:00 UTC` 时段的 `flip_bullish` 盈利弹性是否被过度压缩

**信号级：**
- `red_bar_growing` 当前贡献最高（+$5275.84），需要确认实盘中该信号的胜率与回测一致
- `flip_bearish` 胜率最高（86.84%），关注是否在实盘中持续

---

*文档版本：V10→V11 优化建议 / 日期：2026-03-21*
