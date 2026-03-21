# MACD_MTF_Strategy V8 → V9 优化建议

> 文档用途：基于 V8 当前回测结果（月收益 +92.38%，胜率 71.43%，MDD 10.69%），提出下一轮可执行优化方向  
> 当前基线：`v2_summary_20260321_184125.json`  
> 原则：**不破坏当前正收益骨架，只做局部增益或风险收窄**

---

## 一、当前策略健康度评估

| 维度 | 当前值 | 评级 | 说明 |
| --- | --- | --- | --- |
| 月收益率 | `+92.38%` | ✅ 优秀 | 相比基线提升 `+15.48pp` |
| 盈利因子 | `2.74` | ✅ 优秀 | 每亏 1 元盈利 2.74 元 |
| 胜率 | `71.43%` | ✅ 良好 | 高于基线 `+2.35pp` |
| 最大回撤 | `10.69%` | 🟡 可改善 | 回撤簇仍集中，有压缩空间 |
| 单笔最大亏损 | 未披露 | 🟡 待观察 | 历史上曾出现 $352 单笔亏损 |
| 交易笔数 | `511` | ✅ 健康 | 过滤后笔数反升，释放效果验证 |

**整体判断：** V8 已进入"收益结构稳定，但尾部风险仍有敞口"阶段，下一步优化重心应从"提收益"转移到"压回撤 + 增加策略鲁棒性"。

---

## 二、可优化方向全景

```
V8 当前架构
├── 方向层（4H 主 + 1H 轻确认）          → 【可优化 A】4H 方向质量分级
├── 入场层（15M 时机 + pre-flip 试仓）    → 【可优化 B】试仓参数精化
├── 结构层（BOLL + VWAP）                → 【可优化 C】VWAP 状态分档加仓
├── 过滤层（ADX pocket + CVD context）    → 【可优化 D】过滤器二次确认
├── 离场层（shrink exit + breakeven）     → 【可优化 E】shrink exit 提前条件
└── 风控层（止损 + 仓位）                → 【可优化 F】时间段/币种分级风控
```

---

## 三、优化建议详情

### 优先级 🔴：高价值，低风险，建议优先验证

---

#### 优化 F：时间段与币种分级风控（针对回撤簇）

**问题来源：**

V8 文档明确指出：
> 当前最大回撤仍集中在 `2026-03-01 ~ 2026-03-04`，回撤簇仍存在"时间聚集"特征

历史大亏单同样呈现时间聚集（2026-02-08、02-11、02-20、02-24 集中爆发），且跨多个品种同时发生。

这说明当前风控层对**系统性行情冲击**（例如突发大波动、特定市场时段）没有隔离机制。

**建议方案 F1：日内时段降权**

回测中亏损集中时段多次出现在 `UTC 15:00~16:30`（美股盘前）和 `UTC 03:00~05:00`（亚洲薄流动性段）。

```json
"session_risk_control": {
  "enabled": true,
  "high_risk_sessions": [
    { "utc_start": "14:30", "utc_end": "16:30", "position_scale": 0.6 },
    { "utc_start": "03:00", "utc_end": "05:30", "position_scale": 0.7 }
  ],
  "apply_to_states": ["short_dual_pressure", "flip_bullish"]
}
```

作用：不减少交易机会，只在高风险时段缩小仓位，降低单次冲击的最大亏损。

**建议方案 F2：高波动币种单独仓位上限**

历史最大亏损品种：KASUSDT、FILUSDT、TAOUSDT（均为中小市值高波动标的）。

```json
"symbol_risk_tiers": {
  "high_vol_symbols": ["KASUSDT", "TAOUSDT", "APTUSDT", "ZECUSDT"],
  "high_vol_max_position_portion": 0.40,
  "high_vol_max_leverage": 2
}
```

作用：对高波动品种单独限制仓位和杠杆，其他品种保持当前配置不变。

**建议方案 F3：回撤触发降仓（动态风控）**

当组合账户从峰值回撤超过阈值时，自动降低新开仓的仓位比例：

```json
"drawdown_throttle": {
  "enabled": true,
  "trigger_drawdown_pct": 0.05,
  "position_scale_at_trigger": 0.7,
  "hard_stop_drawdown_pct": 0.10,
  "reset_after_recovery_pct": 0.02
}
```

作用：回撤 5% 时开始降仓，10% 时停止新开仓。这直接压缩 MDD 的最坏场景。

---

#### 优化 E：4H shrink exit 扩展条件

**问题来源：**

当前 `4H shrink exit` 只在盈利状态下触发（`exit_4h_require_profit = true`）。

这意味着：如果价格进入横盘或弱反弹但尚未盈利，策略会继续持有并等待止损。这是当前止损 `stop_loss_intrabar` 的主要来源。

**建议方案 E1：弱盈利 + 明显 shrink 也允许提前离场**

```json
"exit_4h_require_profit": false,
"exit_4h_weak_profit_threshold": -0.001,
"exit_4h_min_shrink_pct": 0.35
```

解释：当仓位处于轻微亏损（< -0.1%）但 4H histogram 已明显收缩（≥35%），允许以小亏代替大止损离场。

**建议方案 E2：时间衰减离场（Time Decay Exit）**

对于持仓超过 N 根 4H bar 且浮盈未增长的仓位，主动触发离场：

```json
"time_decay_exit": {
  "enabled": true,
  "max_holding_bars_4h": 6,
  "min_profit_to_hold_pct": 0.003,
  "exit_if_stagnant": true
}
```

作用：避免持仓过久被市场结构转变吃掉浮盈甚至倒扑。

---

### 优先级 🟠：中价值，中风险，建议第二轮验证

---

#### 优化 D：过滤器二次确认

**问题来源：**

V8 新增的两个定向过滤器已验证有效，但目前条件仍较单一：

- `ADX pocket filter`：只看 ADX 区间，没有结合方向
- `CVD context filter`：只看上影线 + CVD delta，没有看 4H 层级确认

**建议方案 D1：ADX pocket 叠加 BOLL 中轨斜率**

```json
"green_bar_growing_short_filter_v2": {
  "adx_1h_range": [25.0, 30.0],
  "require_bb_middle_slope_1h_negative": true,
  "bb_slope_lookback_1h": 3
}
```

解释：在当前 ADX 区间过滤的基础上，额外要求 1H BOLL 中轨斜率为负（确认结构下行趋势），双重确认才否决，减少误杀概率。

**建议方案 D2：CVD context filter 叠加 4H histogram 方向**

```json
"flip_bullish_cvd_filter_v2": {
  "max_cvd_upper_wick_ratio": 0.20,
  "min_cvd_1h_delta_ratio": 0.03,
  "require_4h_histogram_positive": true
}
```

解释：翻多信号的 CVD 否决，需要同时满足"4H histogram 为负（大级别尚未明确翻多）"才生效，避免在真实翻多加速段误杀。

---

#### 优化 C：VWAP 状态分档加仓（精化版 D）

**问题来源：**

V8 文档继承了 V6 的讨论问题：
> D 应该怎么做得更精细？是否应该把 `short_dual_pressure` 按 `signal_score` 分成 2~3 档？

当前温和 D 仍是固定 `+0.08` 的静态 bonus，没有利用信号质量差异。

**建议方案 C1：signal_score 分档仓位映射**

```json
"dual_pressure_position_tiers": [
  { "min_score": 0.84, "max_score": 0.89, "position_bonus": 0.00 },
  { "min_score": 0.90, "max_score": 0.94, "position_bonus": 0.05 },
  { "min_score": 0.95, "max_score": 1.00, "position_bonus": 0.12 }
]
```

解释：只对高置信度信号（≥0.95）给更大仓位加成，低分段不加成。当前固定 0.08 会让边缘信号也过度持仓。

**建议方案 C2：vwap_score 作为仓位乘数**

```json
"dual_pressure_vwap_position_mult": {
  "vwap_score_threshold_high": 0.30,
  "vwap_score_threshold_mid": 0.20,
  "mult_high": 1.15,
  "mult_mid": 1.00,
  "mult_low": 0.80
}
```

解释：VWAP 位置越好（分越高），仓位乘数越大；VWAP 位置差（分低）时反而缩仓，与当前"高信号分稀释低VWAP分"的问题形成对冲。

---

#### 优化 B：试仓（pre-flip trial）参数精化

**问题来源：**

当前试仓参数是：

```
preflip_trial_min_shrink_pct_long  = 0.75
preflip_trial_min_shrink_pct_short = 0.30
```

多空的 shrink 阈值不对称非常明显（0.75 vs 0.30），可能导致多空试仓质量差异较大。

**建议方案 B1：对称化 + 分信号质量分档**

```json
"preflip_trial_conditions": {
  "long": {
    "min_shrink_pct": 0.60,
    "high_score_min_shrink_pct": 0.50
  },
  "short": {
    "min_shrink_pct": 0.40,
    "high_score_min_shrink_pct": 0.30
  }
}
```

解释：将多头试仓门槛从 0.75 降低到 0.60（当前可能过于保守），将空头试仓略提高到 0.40（当前可能过于宽松），同时对高质量信号保留宽松通道。

**建议方案 B2：试仓转正仓的自动升级逻辑**

当试仓开出后，如果 4H histogram 方向在 2~3 bar 内明确翻转确认，允许自动补仓到正常仓位：

```json
"trial_to_full_upgrade": {
  "enabled": true,
  "upgrade_after_4h_bars": 2,
  "require_4h_flip_confirmed": true,
  "upgrade_position_scale": 0.65
}
```

作用：试仓捕捉到方向后自动加仓，不需要等下一个完整信号周期。

---

### 优先级 🟢：低风险辅助优化，可作为附加验证

---

#### 优化 A：4H 方向质量分级

**问题来源：**

当前 4H 作为主方向时，只做简单方向判断，没有对 4H histogram 的强弱做分档处理。强趋势和弱趋势下同等对待，可能导致弱趋势时的入场过于激进。

**建议方案 A1：4H histogram 强度分档**

```json
"4h_direction_strength_tiers": {
  "strong": { "4h_hist_min": 0.001, "allow_full_position": true },
  "normal": { "4h_hist_min": 0.0003, "allow_full_position": true },
  "weak":   { "4h_hist_min": 0.0001, "max_position_scale": 0.7, "require_1h_strong": true }
}
```

作用：弱 4H 方向时，强制要求 1H 层有更强确认，同时仓位缩至 70%。

---

## 四、优化优先级汇总

| 优先级 | 优化项 | 预期改善维度 | 实现难度 | 建议顺序 |
| --- | --- | --- | --- | --- |
| 🔴 最高 | F1：日内时段降权 | 降回撤 | 低 | 第 1 批 |
| 🔴 最高 | F2：高波动币种限仓 | 降单笔大亏 | 低 | 第 1 批 |
| 🔴 最高 | F3：动态回撤触发降仓 | 压 MDD | 中 | 第 1 批 |
| 🔴 最高 | E1：弱盈利 shrink exit | 减少 stop_loss_intrabar | 低 | 第 1 批 |
| 🟠 高 | C1：signal_score 分档加仓 | 提盈利因子 | 中 | 第 2 批 |
| 🟠 高 | C2：vwap_score 仓位乘数 | 提质量 / 降误入 | 中 | 第 2 批 |
| 🟠 高 | D2：CVD filter + 4H 确认 | 减少多头误杀 | 中 | 第 2 批 |
| 🟠 中 | B1：试仓门槛对称化 | 多空平衡 | 低 | 第 2 批 |
| 🟠 中 | B2：试仓转正仓升级 | 提收益 | 高 | 第 3 批 |
| 🟠 中 | D1：ADX filter + BOLL 斜率 | 减少误杀 | 低 | 第 2 批 |
| 🟢 低 | E2：时间衰减离场 | 降持仓风险 | 中 | 第 3 批 |
| 🟢 低 | A1：4H 强度分档 | 弱趋势降暴露 | 中 | 第 3 批 |

---

## 五、下一步建议的回测验证顺序

**第 1 批：** 只验证风控层（F1 + F2 + F3 + E1），不改任何信号逻辑

- 这批变动不影响入场判断，只影响仓位和离场
- 若回撤从 10.69% 降至 8% 以内，且收益保持 80%+，则第 1 批成立

**第 2 批：** 在第 1 批稳定后，验证分档加仓（C1 + C2）

- 目标是盈利因子从 2.74 进一步提升到 3.0+

**第 3 批：** 过滤器精化（D1 + D2 + B1）

- 微调过滤器，避免当前版本边缘误杀

**第 4 批：** 结构性功能扩展（B2 + E2 + A1）

- 难度较高，只在前几批验证稳定后再考虑

---

## 六、明确不建议做的方向

| 方向 | 原因 |
| --- | --- |
| 重新引入 `short_retest_reject` | 历史已验证为净负贡献，禁止回退 |
| 重新启用 `short_quality_filter` | 与当前 4H 主方向架构重叠，且精度不如 A1/A2 定向过滤器 |
| 扩展信号类型（new signal_type_1h） | 当前交易笔数 511，结构已足够，扩展前应先优化已有质量 |
| 大幅收紧 ADX 过滤范围 | B 方案已证明过度过滤会损害主盈利结构，需谨慎 |
| 去掉 4H shrink exit | 当前文档已明确：这是降回撤的核心正贡献模块 |

---

*文档版本：V8→V9 优化建议 / 日期：2026-03-21*
