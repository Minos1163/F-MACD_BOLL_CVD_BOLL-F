# MACD V2 — 开仓方向质量根因分析与修复方案

> **Date**: 2026-05-04
> **Scope**: 34H 亏损窗口 → 方向质量系统性缺陷诊断 + 完整修复 Pseudocode / DIFF
> **结论**: 方向问题 ≠ 单一参数问题，是"低质量信号准入 + 方向过滤链存在旁路 + 空单质量无独立门控"三重叠加

---

## 1. 根因摘要

| 层次 | 问题 | 影响 |
|---|---|---|
| **L1 VWAP 地板有旁路** | `preflip_trial`, `stable_bear_continuation`, `flip_bullish` 例外保持 `0.0` | 弱信号可绕过 `0.12` 地板进场 |
| **L2 空单无独立方向过滤** | `short_quality_filter.enabled=false`；`flip_bearish` 仅靠 VWAP 地板，无 OI/Funding 校验 | 4/4 空单 MFE 趋近 0，全输 |
| **L3 RANGE/NO_TRADE 进场未拦截** | #6 `BCHUSDT` RANGE、#10 `SOLUSDT` NO_TRADE 仍开多 | 非趋势 regime 叠加弱 VWAP = 双重劣化 |
| **L4 min_leverage=3 拉升探测单** | 策略评分低时 leverage 应为 0~1，被全局 clamp 提至 3 | 弱质量进场杠杆不降反升 |
| **L5 MFE 未锁利** | AAVE/AVAX/SOL 多头 MFE +0.6%~+0.76%，BE 触发门槛 0.8% 未能命中 | 盈利回吐 → 实现亏损 |
| **L6 stop=0.0000 状态盲区** | 保护 SLA 显示 repair 成功，但摘要仍打 `stop=0.0000` | 无法确认 exchange 止损是否真实挂出 |

---

## 2. 方向质量评分：闭仓 13 笔逐条诊断

```text
trade# | symbol       | side  | regime    | vwap   | dir_score | L1_pass | L2_pass | L3_pass | verdict
-------|--------------|-------|-----------|--------|-----------|---------|---------|---------|--------
1      | TRUMPUSDT    | long  | TREND     | 0.0425 | weak      | BYPASS* | N/A     | OK      | MARGINAL
2      | AVAXUSDT     | long  | TREND     | 0.0364 | weak      | BYPASS* | N/A     | OK      | MARGINAL
3      | XLMUSDT      | long  | TREND     | 0.0401 | weak      | BYPASS* | N/A     | OK      | LOSS
4      | AAVEUSDT     | long  | TREND     | 0.0457 | weak      | BYPASS* | N/A     | OK      | LOSS
5      | ICPUSDT      | short | TREND     | 0.0029 | FAIL      | BYPASS* | FAIL    | OK      | LOSS -0.53
6      | BCHUSDT      | long  | RANGE     | 0.0340 | weak      | BYPASS* | N/A     | FAIL    | LOSS
7      | AVAXUSDT     | long  | TREND     | 0.0374 | weak      | BYPASS* | N/A     | OK      | LOSS
8      | ATOMUSDT     | long  | RANGE     | 0.0428 | weak      | BYPASS* | N/A     | FAIL    | LOSS
9      | JUPUSDT      | long  | TREND     | 0.0446 | weak      | BYPASS* | N/A     | OK      | LOSS
10     | SOLUSDT      | long  | NO_TRADE  | 0.0232 | weak      | BYPASS* | N/A     | FAIL    | LOSS
11     | SUIUSDT      | short | TREND     | 0.0321 | FAIL      | BYPASS* | FAIL    | OK      | LOSS
12     | AVAXUSDT     | short | TREND     | 0.0144 | FAIL      | BYPASS* | FAIL    | OK      | LOSS
13     | SOLUSDT      | short | TREND     | 0.0250 | FAIL      | BYPASS* | FAIL    | OK      | LOSS

*BYPASS: 新 min_vwap_score_for_entry=0.12 在本窗口尚未生效，全部 vwap < 0.12 仍进场
```

---

## 3. 修复方案 Pseudocode + DIFF（共 ~550 行）

### 3.1 `macd_strategy_v2.py` — VWAP 地板旁路封堵

```diff
# FILE: src/fund_flow/macd_strategy_v2.py
# FUNCTION: MACDStrategyV2Engine._resolve_min_vwap_score_for_entry(...)

  def _resolve_min_vwap_score_for_entry(
      self,
      signal_type_1h: str,
      is_long: bool,
      is_trial: bool,
      entry_filters: MACDEntryFilters,
  ) -> float:
-     # --- ORIGINAL: multiple 0.0 exception paths ---
-     if is_trial:
-         return entry_filters.preflip_trial_min_vwap_score     # was 0.0
-
-     if is_long and entry_filters.flip_bullish_min_vwap_exemption:
-         return 0.0
-
-     if is_long:
-         return entry_filters.min_vwap_score_for_entry
-
-     if signal_type_1h == "flip_bearish":
-         return entry_filters.flip_bearish_short_min_vwap_score_for_entry
-
-     if not is_long:
-         return entry_filters.short_min_vwap_score_for_entry
-
-     return entry_filters.min_vwap_score_for_entry

+     # --- FIX: 所有旁路收敛到全局 floor，不再允许 0.0 豁免 ---
+     GLOBAL_HARD_FLOOR = entry_filters.min_vwap_score_for_entry   # 0.12
+
+     if is_trial:
+         # 试探单独立地板，但不得低于全局 floor
+         trial_floor = entry_filters.preflip_trial_min_vwap_score
+         return max(trial_floor, GLOBAL_HARD_FLOOR)
+
+     if is_long and entry_filters.flip_bullish_min_vwap_exemption:
+         # flip_bullish 多头豁免保留，但同样不得低于全局 floor
+         return GLOBAL_HARD_FLOOR
+
+     if is_long:
+         return entry_filters.min_vwap_score_for_entry
+
+     if signal_type_1h == "flip_bearish":
+         # flip_bearish 空单使用更严格专属地板
+         return max(
+             entry_filters.flip_bearish_short_min_vwap_score_for_entry,
+             GLOBAL_HARD_FLOOR,
+         )
+
+     if not is_long:
+         return max(
+             entry_filters.short_min_vwap_score_for_entry,
+             GLOBAL_HARD_FLOOR,
+         )
+
+     return GLOBAL_HARD_FLOOR
```

---

### 3.2 `macd_strategy_v2.py` — stable_bear_continuation VWAP 旁路

```diff
# FILE: src/fund_flow/macd_strategy_v2.py
# FUNCTION: MACDStrategyV2Engine._check_stable_bear_continuation_vwap(...)

  def _check_stable_bear_continuation_vwap(
      self,
      vwap_score: float,
      entry_filters: MACDEntryFilters,
  ) -> VetoResult | None:
-     # ORIGINAL: stable_bear_continuation_min_vwap_score defaults to 0.0
-     floor = entry_filters.stable_bear_continuation_min_vwap_score
-     if floor > 0 and vwap_score < floor:
-         return VetoResult(VetoType.VWAP_SCORE_FILTER, f"stable_bear vwap {vwap_score:.4f} < {floor}")
-     return None

+     # FIX: stable_bear continuation 不得低于 short 专属地板
+     floor = max(
+         entry_filters.stable_bear_continuation_min_vwap_score,
+         entry_filters.short_min_vwap_score_for_entry,   # 0.12
+     )
+     if vwap_score < floor:
+         return VetoResult(
+             VetoType.VWAP_SCORE_FILTER,
+             f"stable_bear_continuation vwap {vwap_score:.4f} < floor {floor:.4f}",
+         )
+     return None
```

---

### 3.3 `macd_strategy_v2.py` — Regime 门控：RANGE / NO_TRADE 不允许低质量多头开仓

```diff
# FILE: src/fund_flow/macd_strategy_v2.py
# FUNCTION: MACDStrategyV2Engine.analyze(...) — regime entry guard section

  def _check_regime_entry_permission(
      self,
      regime: str,
      is_long: bool,
      vwap_score: float,
      signal_score: float,
      entry_filters: MACDEntryFilters,
  ) -> VetoResult | None:
-     # ORIGINAL: RANGE/NO_TRADE 仅靠信号分数拦截，未检验方向质量
-     if regime == "NO_TRADE":
-         if not entry_filters.allow_no_trade_regime_entry:
-             return VetoResult(VetoType.REGIME_FILTER, "NO_TRADE regime blocked")
-     return None

+     # FIX: RANGE 和 NO_TRADE regime 的多头必须同时满足更高 VWAP 和信号分数门槛
+     RANGE_LONG_MIN_VWAP   = 0.20    # 远高于 TREND 下的 0.12
+     RANGE_LONG_MIN_SCORE  = 0.72    # 高于默认 0.68
+     NO_TRADE_LONG_BLOCKED = True    # NO_TRADE regime 多头直接否决，除非 allow 标志开启
+
+     if regime == "NO_TRADE":
+         if not entry_filters.allow_no_trade_regime_entry:
+             return VetoResult(VetoType.REGIME_FILTER, "NO_TRADE regime: long entry blocked")
+         # 即使 allow=true，仍需 VWAP > RANGE 标准
+         if is_long and vwap_score < RANGE_LONG_MIN_VWAP:
+             return VetoResult(
+                 VetoType.VWAP_SCORE_FILTER,
+                 f"NO_TRADE regime long: vwap {vwap_score:.4f} < {RANGE_LONG_MIN_VWAP}",
+             )
+
+     if regime == "RANGE":
+         if is_long:
+             if vwap_score < RANGE_LONG_MIN_VWAP:
+                 return VetoResult(
+                     VetoType.VWAP_SCORE_FILTER,
+                     f"RANGE regime long: vwap {vwap_score:.4f} < {RANGE_LONG_MIN_VWAP}",
+                 )
+             if signal_score < RANGE_LONG_MIN_SCORE:
+                 return VetoResult(
+                     VetoType.SIGNAL_SCORE_FILTER,
+                     f"RANGE regime long: score {signal_score:.4f} < {RANGE_LONG_MIN_SCORE}",
+                 )
+
+     return None
```

---

### 3.4 `decision_engine.py` — 空单质量过滤器 flip_bearish 专属开关

```diff
# FILE: src/fund_flow/decision_engine.py
# FUNCTION: FundFlowDecisionEngine._apply_short_quality_filter(...)

  def _apply_short_quality_filter(
      self,
      symbol: str,
      signal_type_1h: str,
      vwap_score: float,
      decision: Decision,
      market_data: MarketData,
      cfg: ShortQualityFilterConfig,
  ) -> Decision:
-     # ORIGINAL: 整个函数在 enabled=false 时直接跳过
-     if not cfg.enabled:
-         return decision

+     # FIX: flip_bearish 空单有独立开关，与全局 short_quality_filter.enabled 解耦
+     flip_bearish_filter_enabled = cfg.flip_bearish_independent_enabled  # 新字段，默认 true
+
+     is_flip_bearish = (signal_type_1h == "flip_bearish")
+
+     # 全局未开启且非 flip_bearish 独立过滤 → 原逻辑保留
+     if not cfg.enabled and not (is_flip_bearish and flip_bearish_filter_enabled):
+         return decision
+
+     # 非空单跳过
+     if decision.side != Side.SELL:
+         return decision
+
+     veto_reasons: list[str] = []
+
+     # --- 检验 1: Funding Rate 方向性 ---
+     if cfg.min_funding_rate > 0:
+         funding_rate = market_data.funding_rate or 0.0
+         if funding_rate < cfg.min_funding_rate:
+             veto_reasons.append(
+                 f"funding_rate {funding_rate:.6f} < min {cfg.min_funding_rate:.6f}"
+             )
+
+     # --- 检验 2: OI Delta 方向 ---
+     if cfg.max_oi_delta_ratio is not None:
+         oi_delta = market_data.oi_delta_ratio or 0.0
+         if oi_delta >= 0:
+             veto_reasons.append(f"oi_delta_ratio {oi_delta:.4f} >= 0 (no short pressure)")
+
+     # --- 检验 3: 价格相对 VWAP 位置 ---
+     if cfg.min_vwap_deviation > 0:
+         vwap_dev = market_data.vwap_deviation or 0.0
+         if vwap_dev < cfg.min_vwap_deviation:
+             veto_reasons.append(
+                 f"vwap_deviation {vwap_dev:.4f} < {cfg.min_vwap_deviation:.4f}"
+             )
+
+     # --- flip_bearish 附加：VWAP score 专属高门槛 ---
+     if is_flip_bearish:
+         fb_min_vwap = cfg.flip_bearish_min_vwap_score  # 建议 0.25
+         if vwap_score < fb_min_vwap:
+             veto_reasons.append(
+                 f"flip_bearish vwap_score {vwap_score:.4f} < {fb_min_vwap:.4f}"
+             )
+
+     if veto_reasons:
+         self._log_veto(symbol, "SHORT_QUALITY_FILTER", veto_reasons)
+         return Decision.neutral(VetoType.SHORT_QUALITY_FILTER, "; ".join(veto_reasons))
+
+     return decision
```

---

### 3.5 `decision_engine.py` — min_leverage clamp 不得拉升探测/弱质量单

```diff
# FILE: src/fund_flow/decision_engine.py
# FUNCTION: FundFlowDecisionEngine._clamp_leverage(...)

  def _clamp_leverage(
      self,
      leverage: int,
      signal_score: float,
      is_probe: bool,
      vol_vwap_warn: bool,
      regime_state: RegimeState,
      cfg: FundFlowConfig,
  ) -> int:
-     # ORIGINAL: 无论信号质量，全局 min_leverage 都会上调杠杆
-     leverage = min(leverage, regime_state.max_leverage)
-     leverage = max(cfg.min_leverage, min(cfg.max_leverage, leverage))
-     return leverage

+     # FIX: 弱质量信号不受 min_leverage 下限保护，避免杠杆反向拉升
+     is_weak_entry = (
+         is_probe
+         or vol_vwap_warn
+         or signal_score < 0.72   # 低于高质量阈值
+     )
+
+     # 上限永远有效
+     leverage = min(leverage, regime_state.max_leverage, cfg.max_leverage)
+
+     if is_weak_entry:
+         # 弱质量单：策略计算的 leverage 不得被 min_leverage 抬高
+         # 允许 leverage=1 或策略返回的原始值
+         return max(1, leverage)
+     else:
+         # 强质量单：正常 clamp，min_leverage 有效
+         return max(cfg.min_leverage, leverage)
```

---

### 3.6 `decision_engine.py` — vol_vwap_warn 缩放路径完整性校验

```diff
# FILE: src/fund_flow/decision_engine.py
# FUNCTION: FundFlowDecisionEngine._build_buy_decision(...)
#           FundFlowDecisionEngine._build_sell_decision(...)

  def _build_buy_decision(self, ...) -> Decision:
      ...
      portion = self._calculate_portion(signal, regime_state, cfg)
+
+     # FIX: 确保 vol_vwap_warn 缩放在 min_open_portion 检测之前执行
+     # 原始代码中缩放可能在部分路径下延迟
+     portion = self._apply_macd_v2_vol_vwap_warn_position_scale(
+         portion=portion,
+         signal=signal,
+         cfg=cfg,
+     )
+
+     # 同步更新 leverage：若 portion 被归零，leverage 也归零避免残留
+     if portion <= 0.0:
+         return Decision.neutral(
+             VetoType.VOL_VWAP_WARN_SCALE,
+             f"vol_vwap_warn scale zeroed portion for {signal.symbol}",
+         )
+
      if portion < cfg.min_open_portion:
          return Decision.neutral(VetoType.MIN_OPEN_PORTION, ...)
      ...

  def _build_sell_decision(self, ...) -> Decision:
      ...
      portion = self._calculate_portion(signal, regime_state, cfg)
+
+     # FIX: 空单同样需要在 min_open_portion 前执行 vol_vwap_warn 缩放
+     portion = self._apply_macd_v2_vol_vwap_warn_position_scale(
+         portion=portion,
+         signal=signal,
+         cfg=cfg,
+     )
+
+     if portion <= 0.0:
+         return Decision.neutral(
+             VetoType.VOL_VWAP_WARN_SCALE,
+             f"vol_vwap_warn scale zeroed short portion for {signal.symbol}",
+         )
+
      if portion < cfg.min_open_portion:
          return Decision.neutral(VetoType.MIN_OPEN_PORTION, ...)
      ...
```

---

### 3.7 `fund_flow_bot.py` — Protection stop=0.0000 状态映射修复

```diff
# FILE: src/app/fund_flow_bot.py
# FUNCTION: FundFlowBot._print_risk_summary(...)

  def _print_risk_summary(self, symbol: str, position: Position) -> None:
-     # ORIGINAL: 直接从 protection_plan 读取 stop_price，plan 可能未同步
-     stop_price = position.protection_plan.stop_price if position.protection_plan else 0.0
-     stop_pct   = position.protection_plan.stop_pct   if position.protection_plan else cfg.stop_loss_pct
-     logger.info(f"MACD_V2 stop: stop={stop_price:.4f}, stop_pct={stop_pct*100:.2f}%")

+     # FIX: 优先从 exchange open orders 中反查止损价，plan 仅作为 fallback
+     exchange_stop_price = self._resolve_stop_from_exchange_orders(symbol, position)
+     plan_stop_price     = (
+         position.protection_plan.stop_price
+         if position.protection_plan else 0.0
+     )
+
+     if exchange_stop_price and exchange_stop_price > 0:
+         stop_source = "exchange"
+         stop_price  = exchange_stop_price
+     elif plan_stop_price and plan_stop_price > 0:
+         stop_source = "plan"
+         stop_price  = plan_stop_price
+     else:
+         stop_source = "MISSING"
+         stop_price  = 0.0
+
+     stop_pct = (
+         abs(stop_price - position.entry_price) / position.entry_price
+         if stop_price > 0 and position.entry_price > 0 else 0.0
+     )
+
+     log_fn = logger.warning if stop_source == "MISSING" else logger.info
+     log_fn(
+         f"MACD_V2 stop: stop={stop_price:.4f} ({stop_source}), "
+         f"stop_pct={stop_pct*100:.2f}%"
+     )
+
+     # 若 exchange 侧无止损且 plan 显示应有止损 → 触发紧急 repair
+     if stop_source == "MISSING" and position.protection_plan:
+         logger.error(
+             f"{symbol}: exchange stop MISSING despite plan existing — "
+             f"triggering emergency repair"
+         )
+         self._repair_missing_protection(symbol, position, force=True)

+ def _resolve_stop_from_exchange_orders(
+     self,
+     symbol: str,
+     position: Position,
+ ) -> float | None:
+     """
+     从交易所当前挂单中反查止损价，返回找到的第一个止损触发价。
+     若无止损单返回 None。
+     """
+     open_orders = self._exchange_client.get_open_orders(symbol)
+     stop_orders = [
+         o for o in open_orders
+         if o.order_type in ("STOP_MARKET", "STOP", "STOP_LIMIT")
+         and o.side != position.side          # 止损单方向与持仓相反
+     ]
+     if not stop_orders:
+         return None
+     # 取最近入场价的止损单
+     return min(stop_orders, key=lambda o: abs(o.stop_price - position.entry_price)).stop_price
```

---

### 3.8 `fund_flow_bot.py` — BE / Trailing 触发后异步锁止盈

```diff
# FILE: src/app/fund_flow_bot.py
# FUNCTION: FundFlowBot._check_and_apply_be_trailing(...)

  def _check_and_apply_be_trailing(
      self,
      symbol: str,
      position: Position,
      current_price: float,
      mfe_ratio: float,
      engine_params: EngineParams,
  ) -> None:
      be_trigger  = engine_params.tp_break_even_trigger_pnl_ratio   # 0.0055
      be_lock     = engine_params.tp_break_even_lock_ratio           # 0.002
      trail_act   = engine_params.tp_trailing_activate_mfe_ratio     # 0.0075
      trail_dist  = engine_params.tp_trailing_distance_ratio         # 0.003

-     # ORIGINAL: 仅更新本地 plan，未验证 exchange 止损订单是否同步
-     if mfe_ratio >= be_trigger and not position.be_locked:
-         be_price = position.entry_price * (1 + be_lock) if position.is_long else \
-                    position.entry_price * (1 - be_lock)
-         position.protection_plan.stop_price = be_price
-         position.be_locked = True
-         logger.info(f"{symbol} BE locked at {be_price:.4f}")
-
-     if mfe_ratio >= trail_act:
-         trail_price = current_price * (1 - trail_dist) if position.is_long else \
-                       current_price * (1 + trail_dist)
-         if position.is_long and trail_price > position.protection_plan.stop_price:
-             position.protection_plan.stop_price = trail_price
-         elif not position.is_long and trail_price < position.protection_plan.stop_price:
-             position.protection_plan.stop_price = trail_price

+     # FIX: BE/Trailing 更新本地 plan 后，立即同步到 exchange 止损订单
+     def _push_stop_to_exchange(new_stop: float, reason: str) -> bool:
+         """取消旧止损单，挂新止损单，返回是否成功"""
+         try:
+             self._exchange_client.cancel_stop_orders(symbol)
+             self._exchange_client.place_stop_order(
+                 symbol=symbol,
+                 side=position.close_side,
+                 stop_price=new_stop,
+                 qty=position.qty,
+                 reason=reason,
+             )
+             logger.info(f"{symbol} stop pushed to exchange: {new_stop:.4f} ({reason})")
+             return True
+         except ExchangeException as e:
+             logger.error(f"{symbol} stop push failed ({reason}): {e}")
+             return False
+
+     if mfe_ratio >= be_trigger and not position.be_locked:
+         be_price = (
+             position.entry_price * (1 + be_lock)
+             if position.is_long
+             else position.entry_price * (1 - be_lock)
+         )
+         position.protection_plan.stop_price = be_price
+         position.be_locked = True
+         ok = _push_stop_to_exchange(be_price, "break_even")
+         if not ok:
+             # 推送失败 → 标记 protection dirty，下一个 cycle SLA 将 repair
+             position.protection_dirty = True
+
+     if mfe_ratio >= trail_act:
+         trail_price = (
+             current_price * (1 - trail_dist)
+             if position.is_long
+             else current_price * (1 + trail_dist)
+         )
+         plan_stop = position.protection_plan.stop_price
+         should_update = (
+             (position.is_long  and trail_price > plan_stop) or
+             (not position.is_long and trail_price < plan_stop)
+         )
+         if should_update:
+             position.protection_plan.stop_price = trail_price
+             ok = _push_stop_to_exchange(trail_price, "trailing")
+             if not ok:
+                 position.protection_dirty = True
```

---

### 3.9 Config DIFF — `trading_config_fund_flow.json` 完整参数变更

```diff
# FILE: config/trading_config_fund_flow.json

  "fund_flow": {
    "macd_mtf_strategy_v2": {
      "entry_filters": {
        "min_vwap_score_for_entry":                      0.12,  // unchanged
        "short_min_vwap_score_for_entry":                0.12,  // unchanged
        "flip_bearish_short_min_vwap_score_for_entry":   0.25,  // unchanged
-       "preflip_trial_min_vwap_score":                  0.0,
+       "preflip_trial_min_vwap_score":                  0.12,  // ← 消除旁路
-       "stable_bear_continuation_min_vwap_score":       0.0,
+       "stable_bear_continuation_min_vwap_score":       0.12,  // ← 消除旁路
-       "trial_short_below_structure_promotion_min_vwap_score": 0.0,
+       "trial_short_below_structure_promotion_min_vwap_score": 0.12,  // ← 消除旁路
        "flip_bullish_min_vwap_exemption":               true,  // 保留，但代码侧加 floor
        "vol_vwap_warn_min_score_vol":                   0.05,  // unchanged
        "vol_vwap_warn_min_vwap_score":                  0.12,  // unchanged
        "vol_vwap_warn_position_scale":                  0.0    // unchanged
      },
      "regime_entry": {
+       "range_long_min_vwap_score":                     0.20,  // NEW
+       "range_long_min_signal_score":                   0.72,  // NEW
+       "no_trade_long_blocked_unless_override":         true   // NEW
      },
      "position_management": {
        "vol_vwap_warn_position_scale":                  0.0    // unchanged
      }
    },
    "engine_params": {
      "TREND": {
        "tp_break_even_trigger_pnl_ratio":   0.0055,  // unchanged (lowered from 0.008)
        "tp_break_even_lock_ratio":          0.002,   // unchanged
        "tp_trailing_activate_mfe_ratio":    0.0075,  // unchanged (lowered from 0.02)
        "tp_trailing_distance_ratio":        0.003    // unchanged (lowered from 0.01)
      }
    },
    "short_quality_filter": {
-     "enabled":                              false,
+     "enabled":                              false,   // 全局仍关闭
+     "flip_bearish_independent_enabled":     true,    // NEW: flip_bearish 独立开启
      "min_funding_rate":                     0.0005,
      "max_oi_delta_ratio":                   0.0,
      "min_vwap_deviation":                   0.005,
+     "flip_bearish_min_vwap_score":          0.25    // NEW: flip_bearish 专属 VWAP 分
    },
-   "min_leverage":                           3,
+   "min_leverage":                           1,      // ← 弱质量单不再被拉升至 3x
    "max_leverage":                           5       // unchanged
  }
```

---

### 3.10 `macd_strategy_v2.py` — 方向综合质量评分（新增辅助函数）

```python
# FILE: src/fund_flow/macd_strategy_v2.py
# NEW FUNCTION: MACDStrategyV2Engine._compute_direction_quality_score(...)

def _compute_direction_quality_score(
    self,
    signal_type_1h: str,
    regime: str,
    vwap_score: float,
    score_volume: float,
    adx: float,
    mfe_historical: float | None,
    side: str,
) -> DirectionQualityScore:
    """
    综合方向质量评分，用于日志、告警、以及未来 ablation 分析。
    不直接阻断开仓，但为审计和过滤策略升级提供依据。

    评分维度:
      - vwap_quality       : vwap_score 相对门槛的裕量
      - volume_quality     : score_volume 相对 0.10 的裕量
      - regime_alignment   : 当前 regime 与方向的一致性
      - signal_type_risk   : 基于历史亏损率的信号类型风险系数
      - adx_quality        : ADX 对趋势强度的支撑
    """
    score = 0.0
    flags = []

    # 1. VWAP 质量 (0~30 分)
    vwap_min = 0.12
    if vwap_score >= 0.25:
        score += 30
    elif vwap_score >= 0.18:
        score += 20
    elif vwap_score >= 0.12:
        score += 10
    else:
        score += 0
        flags.append(f"LOW_VWAP:{vwap_score:.4f}")

    # 2. Volume 质量 (0~20 分)
    if score_volume >= 0.10:
        score += 20
    elif score_volume >= 0.067:
        score += 12
    else:
        score += 5
        flags.append(f"LOW_VOLUME:{score_volume:.3f}")

    # 3. Regime 对齐 (0~25 分)
    if regime == "TREND":
        score += 25
    elif regime == "RANGE":
        score += 8
        flags.append("RANGE_REGIME")
    elif regime == "NO_TRADE":
        score += 0
        flags.append("NO_TRADE_REGIME")
    else:
        score += 15

    # 4. 信号类型风险系数 (0~15 分)
    SIGNAL_RISK_MAP = {
        "flip_bearish":             0,   # 近期 4/4 亏损
        "flip_bullish":             8,
        "red_bar_growing":          12,
        "green_bar_growing":        12,
        "stable_bear_continuation": 10,
        "stable_bull_continuation": 10,
        "neutral_resume":           7,
    }
    score += SIGNAL_RISK_MAP.get(signal_type_1h, 10)
    if signal_type_1h == "flip_bearish" and side == "short":
        flags.append("FLIP_BEARISH_SHORT_HIGH_RISK")

    # 5. ADX 趋势强度 (0~10 分)
    if adx >= 40:
        score += 10
    elif adx >= 25:
        score += 6
    elif adx >= 15:
        score += 3
    else:
        score += 0
        flags.append(f"WEAK_ADX:{adx:.1f}")

    grade = (
        "A" if score >= 75 else
        "B" if score >= 55 else
        "C" if score >= 35 else
        "D"
    )

    return DirectionQualityScore(
        score=score,
        grade=grade,
        flags=flags,
    )
```

---

### 3.11 Instrumentation — 执行单完整分数记录（新增）

```python
# FILE: src/fund_flow/decision_engine.py
# NEW FUNCTION: FundFlowDecisionEngine._log_executed_score_breakdown(...)

def _log_executed_score_breakdown(
    self,
    symbol: str,
    decision: Decision,
    signal: MACDSignal,
    portion_before_warn: float,
    portion_after_warn: float,
    final_leverage: int,
    block_reason: str | None,
) -> None:
    """
    仅在 decision 为 BUY/SELL 或被 min_open_portion/finalization 拦截时记录。
    避免无关 HOLD/NEUTRAL 的日志噪音。
    解决：attribution 包中大量 _omitted_keys，无法事后重建评分链。
    """
    if decision.action not in (Action.BUY, Action.SELL) and block_reason is None:
        return

    breakdown = {
        "ts":                         _utcnow_iso(),
        "symbol":                     symbol,
        "action":                     decision.action.value,
        "signal_type_1h":             signal.details.signal_type_1h,
        "regime":                     signal.details.regime,
        "regime_adx":                 signal.details.regime_adx,
        "score_1h":                   signal.details.score_1h,
        "score_4h":                   signal.details.score_4h,
        "score_rsi_rhythm_weighted":  signal.details.score_rsi_rhythm_weighted,
        "score_vwap":                 signal.details.score_vwap,
        "score_15m":                  signal.details.score_15m,
        "score_volume":               signal.details.score_volume,
        "total_score":                signal.score,
        "signal_score_threshold":     signal.details.signal_score_threshold,
        "min_vwap_score_for_entry":   signal.details.min_vwap_score_for_entry,
        "vwap_score_raw":             signal.details.vwap_score,
        "vol_vwap_warn":              signal.details.vol_vwap_warn,
        "portion_before_warn_scale":  portion_before_warn,
        "portion_after_warn_scale":   portion_after_warn,
        "final_leverage":             final_leverage,
        "direction_quality_grade":    signal.details.direction_quality.grade,
        "direction_quality_flags":    signal.details.direction_quality.flags,
        "block_or_execute_reason":    block_reason or "EXECUTE",
    }

    self._attribution_logger.log_jsonl("executed_score_breakdown", breakdown)
    logger.debug(f"{symbol} score_breakdown: {breakdown}")
```

---

## 4. 修复优先级与部署序列

```text
PHASE 1 — 立即可部署（纯配置，零代码风险）
  ✅ preflip_trial_min_vwap_score          0.0  → 0.12
  ✅ stable_bear_continuation_min_vwap_score 0.0 → 0.12
  ✅ trial_short_below_structure_promotion_min_vwap_score 0.0 → 0.12
  ✅ flip_bearish_independent_enabled = true（配合代码 3.4）
  ✅ min_leverage = 1（替代 3）

PHASE 2 — 低风险代码变更（仅日志/状态映射）
  ✅ 3.7 stop=0.0000 映射修复 + 紧急 repair 触发
  ✅ 3.11 执行单 score breakdown 记录

PHASE 3 — 中风险（过滤逻辑变更，需回测验证）
  ✅ 3.1 VWAP 地板旁路封堵（全局 floor max）
  ✅ 3.2 stable_bear_continuation VWAP 旁路
  ✅ 3.3 RANGE/NO_TRADE 多头额外门控
  ✅ 3.4 flip_bearish 独立空单质量过滤

PHASE 4 — 高风险（需 ablation + 至少 7 日 live read）
  ✅ 3.5 min_leverage clamp 弱质量绕过
  ✅ 3.8 BE/Trailing 同步推送 exchange 止损

PHASE 5 — 观察窗口（Phase 1~3 稳定后再评估）
  ⏸  short_quality_filter.enabled = true（全局开启）
  ⏸  pretrade_risk_gate.enabled = true
  ⏸  进一步调整 trailing_distance_ratio
```

---

## 5. 回测验证检查单

```python
# 在执行任何 PHASE 2+ 变更前，必须通过以下回测对比

ABLATION_DIRECTION_FIX = [
    # (名称, 配置说明)
    ("baseline_current",         "当前 live 配置，作为对照基线"),
    ("fix_vwap_bypass",          "封堵 preflip/stable_bear/trial VWAP 旁路"),
    ("fix_regime_gate",          "RANGE/NO_TRADE 多头额外 VWAP 0.20 门控"),
    ("fix_flip_bearish_filter",  "flip_bearish 独立空单质量过滤 enabled"),
    ("fix_min_leverage_1",       "min_leverage=1 不拉升弱质量单"),
    ("all_combined",             "以上全部合并"),
]

# 通过标准（每项 ablation 必须满足）:
# - win_rate   >= 0.72  （基线如为 0.70，目标 0.75，中间过渡可接受 0.72）
# - trade_count >= 300/30d  （不可过度稀释信号）
# - max_drawdown <= 0.15
# - profit_factor >= 1.30
```

---

## 6. 预期效果估算

| 修复项 | 在 34H 窗口中命中的问题笔数 | 预计可避免的亏损 |
|---|---:|---:|
| VWAP 旁路封堵 (Phase 1) | 13/13 | 大部分（全量进场的前提条件） |
| flip_bearish 空单质量过滤 | 4/4 | ≈ -0.866 PnL |
| RANGE/NO_TRADE 多头拦截 | 3 笔 (#6 #8 #10) | ≈ -0.653 PnL |
| BE/Trailing exchange 同步 | 3 笔 MFE>0.6% (#2 #4 #10) | ≈ 减少回吐 0.3+ |
| min_leverage=1 | 全量 | 减少弱质量单的单笔亏损幅度 |

> **注**: 以上为方向性估算，不是精确数字。最终效果以回测和 7 日 live 窗口为准。

---

## 7. 遗留审计项（需人工 + 代码确认）

```text
[ ] 确认 _apply_symbol_side_override() 在所有 BUY/SELL 构建路径均被调用
[ ] 确认 vol_vwap_warn_position_scale 缩放在 min_open_portion 之前执行（见 3.6）
[ ] 确认 preflip_trial 路径的 signal.details.vol_vwap_warn 字段是否正确传播
[ ] 确认 SOLUSDT vwap_score=0.0092, vol_vwap_warn=false 边缘案例：
    - score_volume=0.1 不触发 vol_vwap_warn，但 vwap_score=0.0092 < 0.12
    - 新 min_vwap_score_for_entry=0.12 应直接通过 VetoType.VWAP_SCORE_FILTER 拦截
    - 需代码走读确认 _resolve_min_vwap_score_for_entry 在此路径被调用
[ ] protection summary stop=0.0000 在哪个路径打印 —— 修复见 3.7，但需确认 log source
[ ] 新 BE/Trailing 阈值（0.0055/0.0075/0.003）是否过紧：
    - 若下个 live 窗口出现止损出局后续涨 > 1% 的案例，应放宽 trail_dist 至 0.004
```

---

*文档生成：2026-05-04 | 基于 34H 亏损包 + 入场评分链审查包*
