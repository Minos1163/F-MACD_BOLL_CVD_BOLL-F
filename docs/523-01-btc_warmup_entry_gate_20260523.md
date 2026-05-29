# BTC Beta 冷启动预热 + Entry 层 BTC Regime Gate + 小仓 Reduce 修复
**日期**: 2026-05-23  
**问题**: Beta 退出有效，但 entry 仍喂低质量仓位；BTC 下跌时仍追多/追空  
**今天三件事**: 预热冷启动 → Entry 加 BTC regime gate → 小仓 REDUCE 直接改 CLOSE

---

## 根因确认

```
Beta 风控的工作正常：
  DOGE score=6 CLOSE use_btc=True ✓
  ADA score=4 CLOSE use_btc=True ✓
  XLM score=4 CLOSE use_btc=True ✓

但入场层持续喂入负期望信号：
  25/49 实际开仓 vwap_score < 0.30
  11/49 在 NO_TRADE/RANGE
  BTC 下跌初段：系统仍开 BUY red_bar_growing
  BTC 下跌后段：系统追空，容易被 15M 反抽打掉

结论：
  Beta 把大亏变小亏（正确）
  但不能把负期望 entry 变成正期望
  必须在 entry 层加 BTC regime 感知
```

---

## [命令-1] BTC Beta 冷启动预热

### 问题

```python
# 当前：deque(maxlen=48) 从空开始
# 重启后前 10~20 根 15M K 线内 use_btc=False
# BTC 下跌早期（最需要 BTC 权重的时候）无法使用

# 本窗口证据：
# use_btc=False: 162/255 = 63.5%
# 这是冷启动 + 低相关 symbol 的综合结果
```

### 修复

```python
# src/fund_flow/btc_beta_risk.py

class BtcBetaRiskScorer:

    def warmup_from_klines(
        self,
        symbol:     str,
        btc_closes: list[float],    # BTCUSDT 最近 48 根 15M 收盘价
        alt_closes: list[float],    # symbol 最近 48 根 15M 收盘价
    ) -> None:
        """
        启动时从历史 K 线预填相关性历史。
        在 bot 启动时对 watchlist 所有 symbol 调用一次。
        """
        if len(btc_closes) < 2 or len(alt_closes) < 2:
            return

        n = min(len(btc_closes), len(alt_closes))
        btc_rets = [(btc_closes[i] - btc_closes[i-1]) / btc_closes[i-1]
                    for i in range(1, n)]
        alt_rets = [(alt_closes[i] - alt_closes[i-1]) / alt_closes[i-1]
                    for i in range(1, n)]

        if symbol not in self._corr_history:
            self._corr_history[symbol] = deque(maxlen=self.cfg.corr_window_bars)

        for btc_r, alt_r in zip(btc_rets, alt_rets):
            self._corr_history[symbol].append((btc_r, alt_r))

        corr = self.get_btc_alt_corr(symbol)
        self._log_info(
            f"[BETA_WARMUP] {symbol} filled {len(btc_rets)} bars, "
            f"corr={corr:.3f}"
        )

    def get_btc_alt_corr(self, symbol: str) -> float:
        hist = self._corr_history.get(symbol, [])
        if len(hist) < 10:
            # 样本不足：使用默认保守相关性
            return self._get_default_corr(symbol)
        btc = [h[0] for h in hist]
        alt = [h[1] for h in hist]
        try:
            return float(np.corrcoef(btc, alt)[0, 1])
        except Exception:
            return 0.0

    def _get_default_corr(self, symbol: str) -> float:
        """
        样本不足时的默认相关性（冷启动保守假设）。
        主流大市值：默认 0.40（低于真实相关性，保守使用 BTC）
        其他：0.0（不使用 BTC 权重）
        """
        MAJOR_SYMBOLS_DEFAULT_CORR = {
            "ETHUSDT": 0.40, "SOLUSDT": 0.40, "BNBUSDT": 0.40,
            "ADAUSDT": 0.40, "XRPUSDT": 0.35, "DOGEUSDT": 0.35,
            "AVAXUSDT": 0.40, "DOTUSDT": 0.35, "LINKUSDT": 0.35,
        }
        return MAJOR_SYMBOLS_DEFAULT_CORR.get(symbol, 0.0)
```

```python
# src/app/fund_flow_bot.py
# TradingBot._init_fund_flow_modules() 末尾插入

def _warmup_btc_beta_scorer(self) -> None:
    """
    启动时预热 BTC beta 相关性历史。
    从 Binance 拉取 watchlist symbols 最近 48 根 15M K 线。
    """
    self._log_info("[BETA_WARMUP] Starting corr warmup...")

    btc_klines = self.market_ingestion.get_klines(
        symbol="BTCUSDT", interval="15m", limit=50
    )
    if not btc_klines or len(btc_klines) < 10:
        self._log_warning("[BETA_WARMUP] BTC klines unavailable, skipping warmup")
        return

    btc_closes = [k["close"] for k in btc_klines]

    warmed = 0
    for symbol in self.config.trading_symbols:
        try:
            alt_klines = self.market_ingestion.get_klines(
                symbol=symbol, interval="15m", limit=50
            )
            if alt_klines and len(alt_klines) >= 10:
                alt_closes = [k["close"] for k in alt_klines]
                self.btc_beta_scorer.warmup_from_klines(
                    symbol, btc_closes, alt_closes
                )
                warmed += 1
        except Exception as e:
            self._log_debug(f"[BETA_WARMUP] {symbol} failed: {e}")

    self._log_info(f"[BETA_WARMUP] Done: {warmed}/{len(self.config.trading_symbols)} symbols warmed")
```

---

## [命令-2] Entry 层 BTC Regime Gate

### 设计原则

```
BTC 不替代单币方向（已确认）
BTC 作为"市场环境"约束：

  BTC 下跌趋势中（最近 4 根 15M 平均 < -0.1%/根）：
    → 禁止低 VWAP 多单（容易是熊市反弹）
    → 禁止连续下跌后追空（容易被反抽）

  BTC 上涨趋势中：
    → 禁止低 VWAP 空单
    → 不阻碍多头

  BTC 横盘/无趋势：
    → 不施加额外限制
```

```python
# src/fund_flow/btc_entry_regime.py（新文件）

from enum import Enum

class BtcRegime(Enum):
    RISING   = "rising"       # BTC 上涨趋势
    FALLING  = "falling"      # BTC 下跌趋势
    CHOPPY   = "choppy"       # BTC 横盘

class BtcEntryRegimeGate:

    def __init__(self, config: dict):
        self.enabled          = config.get("enabled", True)
        # BTC regime 判断阈值
        self.falling_avg_ret  = config.get("falling_avg_ret", -0.001)  # 4根均值<-0.1%
        self.rising_avg_ret   = config.get("rising_avg_ret",  +0.001)
        # 追空禁止：BTC 已连续下跌多少根
        self.chase_short_block_bars = config.get("chase_short_block_bars", 4)
        self.chase_short_ret_threshold = config.get("chase_short_ret_threshold", -0.015)

    def detect_btc_regime(
        self,
        btc_rets_4bar: list[float],   # 最近 4 根 15M BTC 收益率
    ) -> BtcRegime:
        if len(btc_rets_4bar) < 4:
            return BtcRegime.CHOPPY
        avg = sum(btc_rets_4bar) / len(btc_rets_4bar)
        if avg < self.falling_avg_ret:
            return BtcRegime.FALLING
        if avg > self.rising_avg_ret:
            return BtcRegime.RISING
        return BtcRegime.CHOPPY

    def check_entry(
        self,
        direction:     str,         # "long" or "short"
        btc_regime:    BtcRegime,
        vwap_score:    float,
        vwap_dev_pct:  float,
        signal_4h:     str,
        btc_cumret_4bar: float,     # BTC 最近 4 根 15M 累计收益率
    ) -> dict:
        """
        返回：{ "action": "PASS"|"BLOCK"|"PROBE_CAP", "reason": str }
        """
        if not self.enabled:
            return {"action": "PASS", "reason": "btc_gate_disabled"}

        # ── BTC 下跌时的多头约束 ─────────────────────────────
        if btc_regime == BtcRegime.FALLING and direction == "long":

            # 低 VWAP 多单在 BTC 下跌时 = 熊市反弹，风险高
            if vwap_score < 0.30:
                return {
                    "action": "BLOCK",
                    "reason": f"btc_falling+low_vwap_long_block vwap={vwap_score:.3f}",
                }

            # 中等 VWAP 但价格低于 VWAP = 在均价下方抢反弹
            if vwap_dev_pct < -0.005 and vwap_score < 0.60:
                return {
                    "action": "PROBE_CAP",
                    "max_portion": 0.042,
                    "reason": (
                        f"btc_falling+below_vwap_long_probe "
                        f"dev={vwap_dev_pct:.2%} vwap={vwap_score:.3f}"
                    ),
                }

        # ── BTC 连续下跌后追空约束 ───────────────────────────
        # "下跌 N 根后追空" 容易被 15M 反抽打掉
        if direction == "short":
            btc_already_down = btc_cumret_4bar <= self.chase_short_ret_threshold
            if btc_already_down:
                # BTC 已经跌了，现在追空 = 追跌，高风险
                if vwap_score < 0.50:
                    return {
                        "action": "BLOCK",
                        "reason": (
                            f"btc_chase_short_block: "
                            f"btc_cum4={btc_cumret_4bar:.2%} vwap={vwap_score:.3f}"
                        ),
                    }
                return {
                    "action": "PROBE_CAP",
                    "max_portion": 0.042,
                    "reason": (
                        f"btc_chase_short_probe: "
                        f"btc_cum4={btc_cumret_4bar:.2%} vwap={vwap_score:.3f}"
                    ),
                }

        # ── BTC 上涨时的空头约束 ─────────────────────────────
        if btc_regime == BtcRegime.RISING and direction == "short":
            if vwap_score < 0.40:
                return {
                    "action": "BLOCK",
                    "reason": f"btc_rising+low_vwap_short_block vwap={vwap_score:.3f}",
                }

        return {"action": "PASS", "reason": "btc_regime_gate_pass"}
```

```python
# 插入位置：macd_strategy_v2.py，threshold_check 通过后，15m_entry_gate 之前

btc_regime = self.btc_entry_regime_gate.detect_btc_regime(self._btc_rets_4bar)

regime_result = self.btc_entry_regime_gate.check_entry(
    direction          = direction,
    btc_regime         = btc_regime,
    vwap_score         = vwap_score,
    vwap_dev_pct       = vwap_dev_pct,
    signal_4h          = signal_4h,
    btc_cumret_4bar    = sum(self._btc_rets_4bar),
)

if regime_result["action"] == "BLOCK":
    return self._neutral_signal(
        reason=regime_result["reason"],
        code="btc_entry_regime_block"
    )

if regime_result["action"] == "PROBE_CAP":
    target_portion = min(target_portion, regime_result["max_portion"])
    self._log_info(f"[BTC_REGIME] {symbol} probe capped: {regime_result['reason']}")
```

---

## [命令-3] NO_TRADE/RANGE 禁止 Final Entry

```python
# 补充上次修复的遗漏：NO_TRADE + SHORT 已经有 guard，
# 但 NO_TRADE + LONG 和 RANGE 仍能进入 final

def _check_regime_entry_block(
    self,
    regime:          str,
    direction:       str,
    signal_score:    float,
) -> dict:
    """
    NO_TRADE/RANGE 下的新仓准入
    """
    if regime not in ("NO_TRADE", "RANGE"):
        return {"action": "PASS"}

    # NO_TRADE 完全禁止新开仓（含多空）
    if regime == "NO_TRADE":
        if signal_score >= 0.85:
            # 高分允许极小 probe（不完全禁止，避免漏掉强信号）
            return {"action": "PROBE_CAP", "max_portion": 0.042,
                    "reason": "no_trade_high_score_probe"}
        return {"action": "BLOCK",
                "reason": f"no_trade_block score={signal_score:.3f}"}

    # RANGE 只允许高分 probe
    if regime == "RANGE":
        if signal_score >= 0.80:
            return {"action": "PROBE_CAP", "max_portion": 0.060,
                    "reason": "range_high_score_probe"}
        return {"action": "BLOCK",
                "reason": f"range_block score={signal_score:.3f}"}

    return {"action": "PASS"}
```

---

## [命令-4] 小仓位 REDUCE_50 直接改 CLOSE

```python
# src/fund_flow/btc_beta_risk.py
# BtcBetaRiskScorer.score() 末尾修改

# 当前：risk_score >= 2 → REDUCE_50
# 问题：小仓位的 50% 量小于交易所最小下单量 → ReduceOnly rejected

def _resolve_reduce_action(
    self,
    risk_score:         int,
    position_notional:  float,   # 当前持仓名义价值（USDT）
    direction:          str,
) -> str:
    """
    判断 REDUCE_50 是否应该直接升级为 CLOSE
    """
    SMALL_NOTIONAL_THRESHOLD = 10.0   # 名义 < 10U 直接 close

    if risk_score >= 4:
        return "CLOSE"

    if risk_score >= 2:
        if position_notional < SMALL_NOTIONAL_THRESHOLD:
            # 小仓位：50% 减仓通常不可执行，直接 close
            return "CLOSE"
        return "REDUCE_50"

    return "HOLD"


# 在 score() 末尾替换原有决策映射：
action = self._resolve_reduce_action(
    risk_score, position_notional, direction
)

return {
    "risk_score":      risk_score,
    "action":          action,
    "reason":          reason_str,
    "use_btc":         use_btc,
    "position_notional": position_notional,
}
```

---

## 配置修改

```diff
# config/trading_config_fund_flow.json

  "btc_beta_risk": {
    "enabled":                    true,
+   "warmup_on_start":            true,
+   "warmup_kline_limit":         50,
+   "default_corr_major_symbols": 0.40,    # 冷启动默认相关性
    "min_corr_for_btc_weight":    0.20,
    "fast_fail_window_bars":      2,
    "fast_fail_mae_threshold":   -0.002,
+   "small_notional_close_threshold": 10.0  # < 10U 仓位直接 CLOSE
  },

+ "btc_entry_regime_gate": {
+   "enabled":                    true,
+   "falling_avg_ret":           -0.001,
+   "rising_avg_ret":            +0.001,
+   "chase_short_ret_threshold": -0.015,
+   "chase_short_block_vwap":     0.50,
+   "btc_falling_low_vwap_block": 0.30,
+   "btc_falling_below_vwap_probe_max": 0.042
+ },

  "entry_quality_gates": {
    "15m_hard_gate": {
      "enabled": true,
      "vwap_below_threshold": -0.005,
    },
+   "vwap_score_hard_block": {
+     "below_block":    0.12,    # vwap < 0.12 → block
+     "below_probe":    0.30,    # 0.12~0.30 → max 0.042
+     "probe_max":      0.042
+   },
+   "no_trade_gate": {
+     "block_below_score":  0.85,
+     "probe_max":          0.042
+   },
+   "range_gate": {
+     "block_below_score":  0.80,
+     "probe_max":          0.060
+   }
  }
```

---

## 执行清单

```
今天：
□ BtcBetaRiskScorer.warmup_from_klines() 实现
□ TradingBot._warmup_btc_beta_scorer() 在 init 末尾调用
□ BtcEntryRegimeGate 新文件写入
□ _check_regime_entry_block() 加到 threshold_check 后
□ _resolve_reduce_action() 替换小仓 REDUCE_50
□ vwap_score < 0.12 → block；0.12~0.30 → probe 0.042
□ config 三个新 gate 块添加
□ pre_live_assertions: assert_btc_warmup + assert_regime_gate
□ 重启，verify_deployment.py ✅

验收（12H 后）：
□ BETA_WARMUP 日志出现，use_btc=False 从 63% 降到 < 30%
□ btc_entry_regime_block/probe 出现在 entry 拦截里
□ vwap < 0.30 实际开仓比例：从 51% 降到 < 20%
□ ReduceOnly rejected 数量：从 28 降到 < 3

不动：
❌ ExitGuard confirm_bars（两层协同，不改）
❌ 4H/1H 方向权重（已有 15M gate 限制影响）
❌ 已通过 final floor lift 的 ATOM 类盈利信号（不压制盈利）
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-23*  
*三件事：预热 corr → BTC regime gate entry → 小仓 REDUCE 直接 CLOSE*
