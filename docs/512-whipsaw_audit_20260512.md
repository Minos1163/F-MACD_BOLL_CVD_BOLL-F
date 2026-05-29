# 05-12 Whipsaw 归因审阅与修复建议
**审阅窗口**: 2026-05-11 19:00 BJ → 2026-05-12 19:00 BJ  
**核心问题**: 上升段过度保守 / 下跌段对冲滞后 / shrink cap 覆盖错层 / 高分信号被 min_open 过滤  
**对照**: 05-08 同口径 fill PnL +12.18 vs 本窗口 +0.66

---

## 事件还原

```
市场路径（BTC 主线）：
  22:30 BJ  BTC=80710（起点）
  02:30 BJ  BTC=81992（+1.59%，日高）
  09:00 BJ  BTC≈81030（开始回落）
  09:36 BJ  BTC LONG 止损出场 -0.868
  19:00 BJ  BTC=80631（收盘）

策略行为 vs 市场：
  上升段（22:30~02:30）：
    只开了 BTC LONG(00:15) + DOGE LONG(00:45)
    → 162 笔高分 SHORT 候选被 min_open_portion 过滤（平均 score=0.774）
    → 大量 LONG 候选被 rsi_1h_direction_block 过滤（1935 次）

  下跌段（08:00~14:00）：
    08:00~09:36 无新 SHORT 开仓（双腿对冲 dual_leg_allowed=0）
    14:00 后 SOL/VET/XLM/AAVE 才集中出现 SHORT
    → 主跌段全程没有有效 SHORT 对冲

副作用量化（P0 修复后遗症）：
  新增阻断 162 笔 min_open_portion（含 score=0.919 的 WLDUSDT SHORT）
  BTCUSDT SHORT score=0.878 被压到 target=0.000175 < min_open=0.06
  → 本次最有价值的信号被自己的仓位压缩逻辑挡在门外
```

---

## ⚠️ FINDINGS

---

### [CRITICAL-1] shrink cap 仅覆盖 signal_4h，1H shrink 大仓仍然通过

**回答 Q1**

```python
# 当前错误行为（伪代码还原）
def apply_signal_type_cap(signal: dict, base_portion: float) -> float:
    # 当前只看 signal_4h
    signal_type = signal.get("signal_type_4h", "")   # ← 问题所在

    if signal_type in ["red_bar_shrinking", "green_bar_shrinking"]:
        return min(base_portion, 0.10)   # cap 生效

    return base_portion   # 其余不 cap

# 本窗口实际成交族：
# macd_v2_short_1h_green_bar_shrinking_15m__vwap_*
# signal_1h = green_bar_shrinking，但 signal_4h = green_bar_growing / flip_bearish
# → 4H cap 条件 False → base_portion=0.2142/0.2856 全部通过
# → 设计意图（shrink 是弱方向信号，应限仓）完全落空

# 本窗口最大的两笔 shrink SHORT 亏损：
shrink_losses = [
    {"symbol": "ONDOUSDT", "side": "SHORT", "portion": 0.2142,
     "signal_1h": "green_bar_shrinking", "signal_4h": "???",
     "pnl": -0.701910},
    {"symbol": "SOLUSDT", "side": "SHORT", "portion": 0.2142,
     "signal_1h": "green_bar_shrinking", "signal_4h": "???",
     "pnl": -0.222000},
]
# 如果 1H shrink cap = 0.10：
# ONDOUSDT: -0.701910 × (0.10/0.2142) ≈ -0.328（节省 -0.374）
# SOLUSDT:  -0.222000 × (0.10/0.2142) ≈ -0.104（节省 -0.118）
```

**DIFF：同时支持 1H 和 4H shrink cap**

```diff
# config/trading_config_fund_flow.json

  "signal_type_position_caps": {
-   "red_bar_shrinking":   {"max_target_portion": 0.10, "apply_to": "signal_4h"},
-   "green_bar_shrinking": {"max_target_portion": 0.10, "apply_to": "signal_4h"},

+   "red_bar_shrinking": {
+     "max_target_portion": 0.10,
+     "apply_to": ["signal_1h", "signal_4h"],   # 同时检查两个周期
+     "logic":    "any"                          # 任一周期为 shrink 即触发 cap
+   },
+   "green_bar_shrinking": {
+     "max_target_portion": 0.10,
+     "apply_to": ["signal_1h", "signal_4h"],
+     "logic":    "any"
+   }
  }
```

```python
# macd_strategy_v2.py — 修复 apply_signal_type_cap

def apply_signal_type_cap(
    signal: dict,
    base_portion: float,
    caps_config: dict,
) -> float:
    """
    同时检查 signal_1h 和 signal_4h，任一命中即触发 cap
    """
    signal_1h = signal.get("signal_type_1h", "")
    signal_4h = signal.get("signal_type_4h", "")

    for cap_key, cap_cfg in caps_config.items():
        apply_to = cap_cfg.get("apply_to", ["signal_4h"])
        max_cap  = cap_cfg.get("max_target_portion", 1.0)

        hit_1h = ("signal_1h" in apply_to) and (signal_1h == cap_key)
        hit_4h = ("signal_4h" in apply_to) and (signal_4h == cap_key)

        if hit_1h or hit_4h:
            capped = min(base_portion, max_cap)
            if capped < base_portion:
                log_debug(
                    f"shrink_cap: {cap_key} hit on "
                    f"{'1H' if hit_1h else '4H'}, "
                    f"portion {base_portion:.3f} → {capped:.3f}"
                )
            return capped

    return base_portion
```

---

### [CRITICAL-2] score≥0.80 的信号被 dynamic sizing 压到 min_open 以下 — 高分漏单

**回答 Q2**

```python
# 当前问题的完整链路
def current_broken_chain(signal, market_ctx):
    base = config.default_target_portion   # 0.35

    # Step 1: dynamic sizing 连续压缩
    if signal.vwap_score <= 0.25:
        base *= 0.60   # → 0.210
    if signal.volume_score <= 0.033:
        base *= 0.75   # → 0.1575
    if market_ctx.adx > 40 and market_ctx.regime == "TREND":
        base *= 0.70   # → 0.1103

    # Step 2: 结果低于 min_open_portion
    if base < config.min_open_portion:    # 0.06
        # ← 当前行为：丢弃信号，不生成 entry
        return None   # 信号消失！

# 失血量化（本窗口）：
# 162 笔 min_open_portion blocked
# avg_score = 0.774
# 最高: WLDUSDT SHORT score=0.919
#       SUIUSDT SHORT score=0.918
#       BTCUSDT SHORT score=0.878

# 这些 score>0.80 的信号本应是最优质的机会
# 但被 dynamic sizing 压到 < 0.06 后静默丢弃
# 结果：系统在最好的信号上不开仓，在中等信号上开大仓

# 正确行为：
# score >= 0.80 → 无论 dynamic sizing 压到多少，至少开一个 probe
# probe 大小 = max(compressed_target, probe_floor)

PROBE_FLOOR_SCORE_THRESHOLD = 0.80
PROBE_FLOOR_PORTION = 0.06   # = min_open_portion

def resolve_final_portion(
    signal_score: float,
    compressed_target: float,
    min_open: float,
) -> float:
    """
    对高分信号保证最小 probe 仓位，不允许静默丢弃
    """
    if compressed_target >= min_open:
        return compressed_target   # 正常路径

    if signal_score >= PROBE_FLOOR_SCORE_THRESHOLD:
        # 高分信号：提升到 probe floor，而不是丢弃
        log_info(
            f"probe_floor_rescue: score={signal_score:.3f} >= {PROBE_FLOOR_SCORE_THRESHOLD}, "
            f"target {compressed_target:.4f} → probe_floor {PROBE_FLOOR_PORTION:.3f}"
        )
        return PROBE_FLOOR_PORTION

    # 低分信号：dynamic sizing 说不行就不行，丢弃
    return None   # 仍然丢弃低分小仓
```

**DIFF：probe floor rescue**

```diff
# config/trading_config_fund_flow.json

+ "probe_floor_rescue": {
+   "enabled":              true,
+   "min_score_threshold":  0.800,    # score >= 0.80 触发 rescue
+   "probe_portion":        0.060,    # 保底 probe = min_open_portion
+   "probe_leverage_cap":   2,        # probe 杠杆不超过 2x
+   "comment": "高分信号不允许被 dynamic sizing 静默丢弃"
+ }

# macd_strategy_v2.py / fund_flow_bot.py
# 在 _calculate_target_portion 末尾插入

  def _calculate_target_portion(self, signal, market_ctx):
      # ... dynamic sizing 逻辑 ...
      target = self._apply_dynamic_sizing(signal, market_ctx)

+     # probe floor rescue
+     if target < self.config.min_open_portion:
+         rescue_cfg = self.config.probe_floor_rescue
+         if rescue_cfg.enabled and signal.total_score >= rescue_cfg.min_score_threshold:
+             self._log_info(
+                 f"probe_rescue: score={signal.total_score:.3f} "
+                 f"target={target:.4f} → probe={rescue_cfg.probe_portion:.3f}"
+             )
+             return rescue_cfg.probe_portion, {"forced_probe": True, "leverage_cap": rescue_cfg.probe_leverage_cap}
+         return None, {}   # 低分小仓：丢弃

      return target, {}
```

---

### [CRITICAL-3] BTC/ETH 作为可交易品导致大亏损，应降级为 context-only

**回答 Q3**

```python
# 本窗口 BTC LONG 开仓分析：
btc_long_entry = {
    "time":      "00:15 BJ",
    "portion":   0.2016,
    "signal_1h": "red_bar_growing",
    "vwap":      0.169,           # 极低 VWAP（上版建议 block vwap<0.12）
    "regime":    "TREND",
    "adx":       19.54,           # 低 ADX，不是强趋势
    "atr_pct":   0.49%,
    "pnl":       -0.868,          # 最大单笔亏损
}

# 问题：
# 1. BTC vwap=0.169 应该触发 position_scaler 压仓
#    但 BTC 的 vwap 计算可能与 alt 不同（BTC 价格大，偏移计算逻辑差异）
# 2. BTC LONG 在上升初期低 ADX(19.5) 环境下开仓
#    → 不是确定的趋势，是模糊信号
# 3. 后续 09:36 BTC 止损 -0.868，是本窗口最大单笔亏损

# BTC 独立参数的必要性：
# - BTC 波动率比 alt 小（atr=0.49% vs alt 平均 1~2%）
# - BTC 的 VWAP 偏离含义与 alt 不同
# - BTC 的 MACD 评分可能需要独立权重（1H direction weight 应更低，4H 更高）
# - 在这些参数验证完成前，BTC 不应该用 alt 的参数体系交易

# 建议：BTC/ETH/BNB → context_only（直到独立参数回测通过）
alt_vs_btc_param_gap = {
    "vwap_scale":      "BTC 日内波动小，VWAP 偏离 0.17 对 BTC 含义完全不同",
    "atr_stop":        "BTC atr=0.49% 导致止损距离极窄，容易被扫",
    "score_weights":   "alt 评分体系直接用于 BTC 的合理性未验证",
    "30D_backtest":    "没有 BTC 独立参数的回测数据，不可上实盘",
}
```

**DIFF：BTC/ETH/BNB 降级 context-only**

```diff
# config/trading_config_fund_flow.json

- "trading_symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", ...(alt list)...],
+ "trading_symbols": [...(alt list only, 不含 BTC/ETH/BNB)...],

+ "market_context_symbols": {
+   "BTCUSDT": {
+     "role":              "shock_detector",
+     "tradable":          false,
+     "data_fields":       ["price", "volume", "return_5m", "return_15m"],
+     "beta_update_hours": 24
+   },
+   "ETHUSDT": {
+     "role":     "secondary_context",
+     "tradable": false,
+     "data_fields": ["price", "return_15m"]
+   },
+   "BNBUSDT": {
+     "role":     "context_only",
+     "tradable": false
+   }
+ },

+ "btc_tradable_re_enable_conditions": {
+   "require_backtest_days":      30,
+   "require_wr":                 0.72,
+   "require_independent_params": true,
+   "comment": "BTC 独立参数 30D 回测通过后才可重新启用交易"
+ }
```

---

### [HIGH-1] 双腿对冲未触发根因 — ATR 单轨检测无法捕捉 BTC 主导的联动冲击初期

**回答 Q4**

```python
# 当前对冲触发条件（本窗口未命中）
current_hedge_gates = {
    "unrealized_loss_pct":  -0.020,   # 亏 2% 才触发
    "signal_score":          0.720,
    "regime_atr_pct":        0.012,   # 个股 ATR 1.2%
}

# 本次 08:00 BJ 冲击时的实际状态：
# BTC LONG 持仓，atr_pct=0.49%（< 1.2%）
# → ATR gate 未触发
# → 双腿对冲未启动
# → 等到 09:36 才止损出场

# BTC 主导冲击的时序特征：
btc_shock_timeline = {
    "08:00": "BTC 开始下跌（BTC 5m return ≈ -1.0%）",
    "08:15": "alt 开始联动下跌（alt ATR 仍低）",
    "08:30": "alt ATR 开始升高（滞后 30 分钟）",
    "09:00": "alt portfolio 低点",
    "09:36": "BTC LONG 止损出场",
}
# 问题：等 alt_atr > 1.2% 时，损失已经实现了 70%

# 修复：BTC return 作为第一触发轨，ATR 作为第二确认轨
def should_trigger_hedge(
    current_position: dict,
    btc_returns: dict,
    symbol_atr_pct: float,
    signal: dict,
) -> tuple[bool, str]:
    """
    双触发轨：BTC return（领先）OR 个股 ATR（滞后）
    """
    btc_5m  = btc_returns.get("5m",  0)
    btc_15m = btc_returns.get("15m", 0)

    # ── 触发轨 1: BTC 领先信号 ─────────────────────────────
    btc_shock = (btc_5m < -0.015) or (btc_15m < -0.020)

    # ── 触发轨 2: 个股 ATR（确认信号）─────────────────────
    atr_shock = symbol_atr_pct >= 0.012

    shock_detected = btc_shock or atr_shock

    if not shock_detected:
        return False, "无冲击检测"

    # ── 仓位方向一致性检查 ─────────────────────────────────
    # 只有当持有 LONG 且 BTC 在跌时，才考虑做空对冲
    if current_position["side"] == "LONG" and btc_15m < -0.010:
        loss_pct = current_position.get("unrealized_pnl_pct", 0)
        if loss_pct < -0.015:   # 浮亏 1.5%（比原提案 2% 更宽松）
            if signal.get("total_score", 0) >= 0.72:
                return True, (
                    f"对冲触发: btc_5m={btc_5m:.2%} "
                    f"atr={symbol_atr_pct:.3f} "
                    f"loss={loss_pct:.2%}"
                )

    return False, "条件不足"
```

**DIFF：BTC return 触发轨**

```diff
# config/trading_config_fund_flow.json

  "dual_leg_hedge": {
    "enabled": true,
-   "trigger_unrealized_loss_pct": -0.020,
+   "trigger_unrealized_loss_pct": -0.015,   # 放宽，更快响应

-   "shock_detector": {
-     "type":             "atr_only",
-     "min_atr_pct":      0.012
-   },

+   "shock_detector": {
+     "type":             "btc_or_atr",       # 双轨，任一触发
+     "btc_5m_threshold":  -0.015,            # BTC 5m 跌 1.5% 触发
+     "btc_15m_threshold": -0.020,            # BTC 15m 跌 2.0% 触发
+     "min_atr_pct":       0.012,             # OR 个股 ATR 1.2%
+     "require_btc_context": true             # 需要 BTC context 数据
+   },

    "min_signal_score":  0.720,
    "max_hedge_exposure": 0.080,
    "hedge_leverage_cap": 2
  }
```

---

### [HIGH-2] 4H-primary + RSI hard veto 在趋势初期和反转初期均明显滞后

**回答 Q5**

```python
# 当前 rsi_1h_direction_block 触发次数：1935
# rsi_1h_direction_against_veto：773
# 两者合计约 2708 次阻断，占 decision_events=2699 的几乎全部

# 问题：RSI(4) 的极短周期特性决定了它在趋势转向初期必然
# 出现"方向刚转，但 4H 确认未到"的窗口
# 在这个窗口里，每一笔可能盈利的反转入场都被 hard veto 挡住

# 证据（上升段）：
# 22:30 BJ BTC/SOL 开始上涨
# RSI 方向从 "down" 翻转为 "up"，但 4H MACD 仍是 shrink
# → rsi_1h_direction_against_veto 大量触发
# → 策略只开了 2 笔 LONG（00:15, 00:45），错过了大部分上升

# 提案：在特定条件下，把 hard veto 降级为 soft penalty
def rsi_direction_gate_adaptive(
    rsi_dir_1h: str,
    rsi_dir_4h: str,
    signal_score: float,
    btc_shock_level: str,
    regime: str,
    adx: float,
) -> tuple[str, float]:
    """
    返回 (gate_mode, penalty_mult)
    gate_mode: "VETO" | "PENALTY" | "PASS"
    """

    # 标准模式：4H 和 1H 方向一致，直接通过
    if rsi_dir_1h == rsi_dir_4h:
        return "PASS", 1.0

    # 冲击/反转 regime：降级为 soft penalty
    in_shock = btc_shock_level in ("MEDIUM", "SEVERE")
    in_reversal = (regime == "TREND" and adx < 20)   # 趋势弱化，可能在反转

    if in_shock or in_reversal:
        if signal_score >= 0.75:   # 高分信号豁免 hard veto
            penalty = 0.85 if in_shock else 0.90
            return "PENALTY", penalty   # 打折但不阻断

    # 默认：hard veto（原有逻辑）
    return "VETO", 0.0
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

  "rsi_rhythm": {
    "enable_hard_veto":            true,
+   "hard_veto_adaptive_mode":     true,        # 允许条件性降级
+   "adaptive_veto_conditions": {
+     "btc_shock_levels":          ["MEDIUM", "SEVERE"],
+     "low_adx_threshold":          20,
+     "min_score_for_soft_mode":    0.75,
+     "soft_penalty_mult_shock":    0.85,
+     "soft_penalty_mult_reversal": 0.90
+   }
  }
```

---

### [HIGH-3] 恢复 05-08 风格趋势跟随 LONG 通道

**回答 Q6**

```python
# 05-08 vs 05-12 核心差异：
comparison = {
    "05-08": {
        "buy_entries":  19,
        "sell_entries": 5,
        "fill_pnl":     12.18,
        "main_family":  "LONG + red_bar_growing + vwap=0.25 大仓",
        "mode":         "顺风高 beta 追涨",
    },
    "05-12": {
        "buy_entries":  2,
        "sell_entries": 12,
        "fill_pnl":     0.66,
        "main_family":  "SHORT + green_bar_shrinking",
        "mode":         "滞后追跌，上升段几乎空手",
    },
}

# 05-08 那套"高 beta LONG"赚钱的条件：
# 1. BTC 整体上涨（上下文同向）
# 2. VWAP score 低（0.25），但市场正在上涨，追高是对的
# 3. 大仓（0.336）配合高 leverage

# 当前 P0 修复砍掉了这条路：
# vwap=0.25 → dynamic sizing 压仓 × 0.60 = 0.14
# + volume=0.033 → × 0.75 = 0.105
# 低于 min_open → 静默丢弃

# 但 05-08 那条路为什么会亏损（05-11 事件）：
# 当 BTC 下跌时，同样的 LONG 策略变成逆势追高
# → 需要条件门控，而不是全面禁止

# 建议：恢复 LONG 通道，但加 BTC 上下文同向门控
def btc_context_long_guard(
    btc_return_4h: float,       # BTC 4H 收益率（方向确认）
    btc_return_1h: float,       # BTC 1H 收益率（近期动量）
    account_day_profit_pct: float,
) -> dict:
    """
    BTC 同向 + 未触发利润锁定 = 允许较大仓位 LONG
    BTC 反向 / 已触发利润锁定 = 压仓或禁止 LONG
    """
    btc_bullish = btc_return_4h > 0.005 and btc_return_1h > 0.002

    # 利润锁定检查
    profit_locked = account_day_profit_pct >= 0.03

    if btc_bullish and not profit_locked:
        return {
            "long_allowed":       True,
            "vwap_floor_relaxed": True,     # 允许 vwap=0.25 入场
            "dynamic_sizing_mult": 1.0,     # 不额外压仓
            "reason": "BTC 同向 + 未锁仓，恢复趋势 LONG",
        }

    elif btc_bullish and profit_locked:
        return {
            "long_allowed":        True,
            "dynamic_sizing_mult": 0.50,    # 利润锁定 → 半仓
            "reason": "BTC 同向但利润锁定，半仓 LONG",
        }

    else:
        return {
            "long_allowed":        True,
            "dynamic_sizing_mult": 0.40,    # BTC 反向 → 大幅压仓
            "vwap_min_override":   0.35,    # 要求更高 VWAP 质量
            "reason": "BTC 反向，LONG 降权",
        }
```

**DIFF**

```diff
# config/trading_config_fund_flow.json

+ "btc_context_long_lane": {
+   "enabled":                       true,
+   "btc_4h_return_bull_threshold":  0.005,   # BTC 4H 涨幅 > 0.5% = 顺风
+   "btc_1h_return_bull_threshold":  0.002,
+   "allow_low_vwap_in_bull":        true,    # 顺风时放行 vwap=0.25
+   "low_vwap_bull_sizing_mult":     1.00,    # 不额外压仓
+   "profit_lock_sizing_mult":       0.50,    # 触发利润锁定后减半
+   "btc_bear_sizing_mult":          0.40,    # BTC 反向时大幅降权
+   "btc_bear_vwap_min":             0.35     # BTC 反向时要求更高 VWAP
+ }
```

---

## 三、实验方案评估

```python
# 六个实验方案的预期效果评估

experiments = {
    "A_baseline_current_patched": {
        "changes":  "无额外修改",
        "expected": "保持现状，上升段偏弱，下跌段 14:00 后才发力",
        "verdict":  "基准对照，不部署",
    },

    "B_shrink_cap_apply_to_1h": {
        "changes":  "signal_type_caps 同时检查 signal_1h",
        "expected": "shrink 仓位从 0.21 压到 0.10，损失减少约 40%",
        "risk":     "成交量可能下降 10~15%（shrink 信号是主力族）",
        "verdict":  "优先部署（P0 落地）",
        "priority": 1,
    },

    "C_min_open_probe_floor": {
        "changes":  "score≥0.80 的信号保底 probe = 0.06",
        "expected": "162 笔高分信号不再静默丢弃，WLDUSDT SHORT 0.919 能开仓",
        "risk":     "probe 数量增加，需要观察 probe 胜率（建议 shadow 1 天）",
        "verdict":  "优先部署，建议先 shadow_mode 确认 probe 质量",
        "priority": 1,
    },

    "D_btc_shock_detector_hedge_shadow": {
        "changes":  "BTC context 接入 + 对冲 shadow orders",
        "expected": "捕捉 08:00 类冲击，shadow 日志验证对冲质量",
        "risk":     "对冲误触发（BTC 短暂波动误判为冲击）",
        "verdict":  "shadow_mode 运行 3~5 天，确认 trigger_rate 在合理范围",
        "priority": 2,
    },

    "E_disable_btc_eth_bnb_tradable": {
        "changes":  "BTC/ETH/BNB 改为 context_only",
        "expected": "避免 BTC LONG -0.868 类亏损，capacity slot 释放给 alt",
        "risk":     "放弃大币直接交易机会",
        "verdict":  "立即部署（不需要回测，降低风险优先）",
        "priority": 1,
    },

    "F_restore_trend_long_with_btc_guard": {
        "changes":  "BTC 同向时恢复低 VWAP 趋势 LONG 通道",
        "expected": "恢复类 05-08 的上涨段捕捉能力",
        "risk":     "在 BTC 下跌开始时可能多开 LONG（如果 btc_return 滞后）",
        "verdict":  "需要 30D strict_live_mode 回测，不立即部署",
        "priority": 3,
    },
}
```

---

## 四、综合 DIFF（可执行优先级排序）

```diff
# config/trading_config_fund_flow.json
# ── [P0-立即部署] ──────────────────────────────────────────────────

# 1. shrink cap 覆盖修复
  "signal_type_position_caps": {
-   "red_bar_shrinking":   {"max_target_portion": 0.10},
-   "green_bar_shrinking": {"max_target_portion": 0.10},
+   "red_bar_shrinking":   {"max_target_portion": 0.10, "apply_to": ["signal_1h","signal_4h"]},
+   "green_bar_shrinking": {"max_target_portion": 0.10, "apply_to": ["signal_1h","signal_4h"]},
  },

# 2. BTC/ETH/BNB 降级 context-only
- "trading_symbols": ["BTCUSDT","ETHUSDT","BNBUSDT", ...alts...],
+ "trading_symbols": [...alts only...],
+ "market_context_symbols": {
+   "BTCUSDT": {"role":"shock_detector","tradable":false},
+   "ETHUSDT": {"role":"secondary_context","tradable":false},
+   "BNBUSDT": {"role":"context_only","tradable":false}
+ },

# 3. probe floor rescue
+ "probe_floor_rescue": {
+   "enabled":             true,
+   "min_score_threshold": 0.800,
+   "probe_portion":       0.060,
+   "probe_leverage_cap":  2,
+   "shadow_mode":         true    # 先 shadow 1 天确认 probe 质量
+ },

# ── [P1-本周内] ────────────────────────────────────────────────────

# 4. BTC return 双轨冲击触发
  "dual_leg_hedge": {
-   "trigger_unrealized_loss_pct": -0.020,
+   "trigger_unrealized_loss_pct": -0.015,
+   "shock_detector": {
+     "type":              "btc_or_atr",
+     "btc_5m_threshold":  -0.015,
+     "btc_15m_threshold": -0.020,
+     "min_atr_pct":        0.012
+   },
+   "shadow_mode": true    # 先 shadow 3 天
  },

# 5. RSI direction veto 自适应降级
  "rsi_rhythm": {
    "enable_hard_veto": true,
+   "hard_veto_adaptive": {
+     "enabled":               true,
+     "btc_shock_soft_levels": ["MEDIUM","SEVERE"],
+     "low_adx_soft_threshold": 20,
+     "min_score_soft_mode":    0.75,
+     "soft_penalty_mult":      0.87
+   }
  },

# ── [P2-回测验证后] ────────────────────────────────────────────────

# 6. BTC 同向 LONG 通道恢复
+ "btc_context_long_lane": {
+   "enabled":                      false,    # 等 30D 回测通过后启用
+   "btc_4h_return_bull_threshold": 0.005,
+   "allow_low_vwap_in_bull":       true,
+   "profit_lock_sizing_mult":      0.50,
+   "btc_bear_sizing_mult":         0.40
+ }
```

---

## 五、执行路线图

```
优先级  行动                              验收标准
─────────────────────────────────────────────────────────────────────
P0-A   shrink cap 覆盖 signal_1h         1H shrink 成交仓位 ≤ 0.10
P0-B   BTC/ETH/BNB → context_only        BTC LONG 类亏损消失
P0-C   probe floor rescue（shadow先）    162 类高分信号能开 probe，shadow WR ≥ 65%
P1-A   BTC return 双轨对冲触发（shadow） dual_leg_allowed 在冲击 cycle 出现
P1-B   RSI veto 自适应降级               上升初期 LONG 成交数增加，DD 不恶化
P2    BTC 同向 LONG 通道（回测后）        strict_live_mode 30D WR≥72% DD≤8%

本窗口关键教训：
  过度限制（P0 修复）→ 上升段空手（2 笔 LONG）
  过度放开（P0 前）→ 下跌段损失（shrink 大仓）
  正确平衡 = 信号质量高时保底 probe + BTC 同向时放开 LONG + 冲击时双轨对冲
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-12*  
*本版核心结论: P0 修复产生 2 个副作用（shrink cap 错层 + 高分信号被 min_open 过滤），需立即打补丁；BTC 改 context-only 可立即部署，无需回测*
