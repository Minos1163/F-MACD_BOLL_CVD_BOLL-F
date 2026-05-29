# 慢牛 Continuation Entry：市场广谱 + 单币动量 + VWAP 改仓位 Cap
**日期**: 2026-05-24  
**问题**: 27/28 标的上涨，涨幅前 10 开多覆盖 1/10；VWAP 低分把强势币归零  
**设计**: 不降阈值，而是新增 ContinuationLong 路径，绕过 4H/1H final 滞后性

---

## 核心设计思路

```
当前 entry 逻辑（滞后）：
  等 4H red_bar_growing → 等 1H 同向 → 等 RSI rhythm → 过阈值 → final
  平均滞后约 1~2H，慢牛早中段完全错过

新增路径（continuation）：
  BTC 上涨 + 多数 alt 同步上涨（广谱）
  + 单币 15M/30M 动量向上
  + RSI 未超买（50~72）
  → 允许极小 probe（0.020~0.042）进入持仓
  
  逻辑：不预测方向，而是"已经在涨了，跟上去"
  风控：仓位极小 + BTC beta 退出保护 + 15M 反向立即止损
```

---

## [命令-1] 市场广谱检测器

```python
# src/fund_flow/market_breadth.py（新文件）

from dataclasses import dataclass, field
from collections import deque

@dataclass
class MarketBreadthConfig:
    enabled:                    bool  = True
    # 广谱判断：多少比例的 tracked symbols 上涨
    slow_bull_breadth_ratio:   float = 0.60    # 60% 以上上涨 = 广谱
    slow_bull_btc_ret_30m:     float = 0.003   # BTC 30M 收益 >= 0.3%
    slow_bull_btc_ret_60m:     float = 0.005   # BTC 60M 收益 >= 0.5%
    slow_bull_alt_median_60m:  float = 0.004   # alt 中位数 60M >= 0.4%
    # 广谱需要持续 N 个 cycle 才确认（防止单根虚假上涨）
    confirm_cycles:            int   = 2
    # 广谱失效：任一条件持续 2 个 cycle 不满足
    invalidate_cycles:         int   = 2


class MarketBreadthDetector:

    def __init__(self, config: MarketBreadthConfig, tracked_symbols: list[str]):
        self.cfg             = config
        self.tracked         = tracked_symbols
        self._confirm_count  = 0
        self._invalid_count  = 0
        self._is_slow_bull   = False
        # symbol → deque of 4 根 15M 收益率
        self._alt_rets: dict[str, deque] = {
            s: deque(maxlen=4) for s in tracked_symbols
        }
        self._btc_rets: deque = deque(maxlen=4)

    def update(
        self,
        btc_ret_15m: float,
        alt_rets:    dict[str, float],   # symbol → 15M 收益率
    ) -> None:
        """每个 cycle 调用一次，更新收益率历史"""
        self._btc_rets.append(btc_ret_15m)
        for sym, ret in alt_rets.items():
            if sym in self._alt_rets:
                self._alt_rets[sym].append(ret)

    def detect(self) -> dict:
        """
        返回当前广谱状态：
          { "is_slow_bull": bool, "breadth_ratio": float,
            "btc_ret_30m": float, "btc_ret_60m": float,
            "alt_median_60m": float, "reason": str }
        """
        if not self.cfg.enabled or len(self._btc_rets) < 2:
            return {"is_slow_bull": False, "reason": "insufficient_data"}

        # BTC 30M/60M 累计收益
        btc_30m = sum(list(self._btc_rets)[-2:]) if len(self._btc_rets) >= 2 else 0
        btc_60m = sum(list(self._btc_rets)[-4:]) if len(self._btc_rets) >= 4 else btc_30m

        # alt 60M 收益分布
        alt_60m_rets = []
        for sym, dq in self._alt_rets.items():
            if len(dq) >= 4:
                alt_60m_rets.append(sum(list(dq)[-4:]))
            elif len(dq) >= 2:
                alt_60m_rets.append(sum(list(dq)[-2:]))

        if not alt_60m_rets:
            return {"is_slow_bull": False, "reason": "no_alt_data"}

        alt_60m_rets.sort()
        n = len(alt_60m_rets)
        alt_median_60m = alt_60m_rets[n // 2]
        breadth_ratio  = sum(1 for r in alt_60m_rets if r > 0) / n

        # 广谱判断
        conditions = {
            "btc_30m":      btc_30m >= self.cfg.slow_bull_btc_ret_30m,
            "btc_60m":      btc_60m >= self.cfg.slow_bull_btc_ret_60m,
            "breadth":      breadth_ratio >= self.cfg.slow_bull_breadth_ratio,
            "alt_median":   alt_median_60m >= self.cfg.slow_bull_alt_median_60m,
        }
        is_bull_candidate = sum(conditions.values()) >= 3   # 至少 3/4 条件满足

        # 持续确认
        if is_bull_candidate:
            self._confirm_count  = min(self._confirm_count + 1, self.cfg.confirm_cycles)
            self._invalid_count  = 0
        else:
            self._invalid_count  = min(self._invalid_count + 1, self.cfg.invalidate_cycles)
            self._confirm_count  = max(self._confirm_count - 1, 0)

        self._is_slow_bull = self._confirm_count >= self.cfg.confirm_cycles

        reason = " | ".join(
            f"{k}={'OK' if v else 'FAIL'}" for k, v in conditions.items()
        )

        return {
            "is_slow_bull":   self._is_slow_bull,
            "breadth_ratio":  breadth_ratio,
            "btc_ret_30m":    btc_30m,
            "btc_ret_60m":    btc_60m,
            "alt_median_60m": alt_median_60m,
            "confirm_count":  self._confirm_count,
            "reason":         reason,
        }
```

---

## [命令-2] 单币 Continuation Candidate 评估

```python
# src/fund_flow/macd_strategy_v2.py（新函数）

def _evaluate_continuation_long_candidate(
    self,
    symbol:          str,
    symbol_ret_30m:  float,
    symbol_ret_60m:  float,
    rsi_15m:         float,     # 15M RSI 当前值（0~100）
    ema_slope_15m:   float,     # 15M EMA 斜率（正 = 上升）
    close_15m:       float,     # 当前 15M 收盘价
    ema_fast_15m:    float,     # 15M 快速 EMA
    btc_ret_30m:     float,
    breadth_state:   dict,      # MarketBreadthDetector.detect() 的输出
    vwap_score:      float,
    corr_btc_alt:    float,     # BTC-alt 相关性
) -> dict:
    """
    慢牛 Continuation Long 候选评估
    返回：{ "allowed": bool, "max_portion": float, "reason": str }

    这是独立于 4H/1H MACD final 的路径：
    不要求 4H/1H red_bar_growing，而是要求 15M/30M 动量直接确认
    """
    if not breadth_state.get("is_slow_bull", False):
        return {"allowed": False, "reason": "not_slow_bull"}

    # ── 单币动量条件 ──────────────────────────────────────────
    MOMENTUM_CONDITIONS = {
        "ret_30m":     symbol_ret_30m >= 0.003,   # 30M 涨 0.3%+
        "ret_60m":     symbol_ret_60m >= 0.006,   # 60M 涨 0.6%+
        "rsi_range":   50 <= rsi_15m <= 72,        # RSI 50~72（强但未超买）
        "ema_slope":   ema_slope_15m > 0,          # EMA 向上
        "above_ema":   close_15m > ema_fast_15m,   # 价格在 EMA 上方
        "btc_not_down": btc_ret_30m >= -0.001,     # BTC 没有同步跌
    }

    met = sum(MOMENTUM_CONDITIONS.values())
    failed = [k for k, v in MOMENTUM_CONDITIONS.items() if not v]

    if met < 4:    # 至少 4/6 条件满足
        return {
            "allowed": False,
            "reason": f"momentum_insufficient ({met}/6) failed={failed}",
        }

    # ── BTC 相关性：低相关性 symbol 需要更强自身动量 ──────────
    if corr_btc_alt < 0.20:
        # 低相关：需要全部 6 个条件满足（更严格）
        if met < 6:
            return {
                "allowed": False,
                "reason": f"low_corr_symbol strict_check ({met}/6) failed={failed}",
            }

    # ── 计算 continuation probe 仓位 ─────────────────────────
    if met == 6:
        base_portion = 0.042   # 全部条件满足：probe 0.042
    elif met == 5:
        base_portion = 0.030   # 5/6：更小 probe
    else:
        base_portion = 0.020   # 4/6：最小 probe

    # VWAP score 影响最终仓位（不 block，只影响 size）
    if vwap_score < 0.12:
        base_portion = min(base_portion, 0.020)   # 极低 VWAP → 最小仓
    elif vwap_score < 0.30:
        base_portion = min(base_portion, 0.030)   # 低 VWAP → 压缩

    return {
        "allowed":     True,
        "max_portion": base_portion,
        "conditions_met": met,
        "reason": (
            f"slow_bull_continuation: {met}/6 met "
            f"ret30={symbol_ret_30m:.2%} ret60={symbol_ret_60m:.2%} "
            f"rsi={rsi_15m:.1f} vwap={vwap_score:.3f} "
            f"portion={base_portion:.3f}"
        ),
    }
```

---

## [命令-3] 慢牛中 VWAP 改仓位 Cap（不再 Hard Block）

```python
# src/fund_flow/macd_strategy_v2.py
# 替换 _apply_vwap_score_gate() 内的 hard block 逻辑

def _apply_vwap_score_gate_with_bull_override(
    self,
    vwap_score:       float,
    direction:        str,
    signal_type:      str,       # "probe" | "continuation" | "normal"
    is_slow_bull:     bool,
    current_portion:  float,
) -> dict:
    """
    慢牛模式下：VWAP 低分 → 仓位 cap，不 hard block
    正常模式下：维持原有逻辑
    """
    if direction == "long" and is_slow_bull:
        # 慢牛：VWAP 低分不阻断，只限仓位
        if vwap_score < 0.05:
            return {"action": "BLOCK",    # 极端低分仍 block
                    "reason": f"slow_bull_vwap_extreme_block {vwap_score:.3f}"}
        if vwap_score < 0.12:
            return {"action": "PROBE_CAP", "max_portion": 0.020,
                    "reason": f"slow_bull_low_vwap cap=0.020 vwap={vwap_score:.3f}"}
        if vwap_score < 0.30:
            return {"action": "PROBE_CAP", "max_portion": 0.030,
                    "reason": f"slow_bull_medium_vwap cap=0.030 vwap={vwap_score:.3f}"}
        # vwap >= 0.30：正常通过
        return {"action": "PASS", "max_portion": current_portion}

    # 非慢牛或 SHORT：维持原有逻辑
    if vwap_score < 0.12:
        return {"action": "BLOCK",
                "reason": f"vwap_hard_block {vwap_score:.3f}"}
    if vwap_score < 0.30:
        return {"action": "PROBE_CAP", "max_portion": 0.042,
                "reason": f"vwap_low_probe {vwap_score:.3f}"}
    return {"action": "PASS", "max_portion": current_portion}
```

---

## [命令-4] 慢牛中降低 Short Trial 优先级

```python
def _apply_slow_bull_short_guard(
    self,
    direction:      str,
    signal_1h:      str,
    vwap_score:     float,
    breadth_ratio:  float,
    is_slow_bull:   bool,
) -> dict:
    if direction != "short" or not is_slow_bull:
        return {"action": "PASS"}

    # 广谱 > 70%：极其不建议做空
    if breadth_ratio >= 0.70:
        if vwap_score < 0.50:
            return {"action": "BLOCK",
                    "reason": f"slow_bull_breadth_70pct_short_block vwap={vwap_score:.3f}"}
        return {"action": "PROBE_CAP", "max_portion": 0.020,
                "reason": "slow_bull_breadth_70pct_short_probe"}

    # 广谱 60%~70%：低 VWAP 空单 block
    if breadth_ratio >= 0.60:
        if vwap_score < 0.35:
            return {"action": "BLOCK",
                    "reason": f"slow_bull_short_low_vwap_block vwap={vwap_score:.3f}"}
        return {"action": "PROBE_CAP", "max_portion": 0.042,
                "reason": "slow_bull_short_probe"}

    return {"action": "PASS"}
```

---

## [命令-5] 集成到主决策流

```python
# src/fund_flow/macd_strategy_v2.py
# _evaluate_signal() 的 entry 路径，与现有 4H/1H final 并行

def _evaluate_signal(self, symbol: str, market_ctx: dict) -> FinalDecision:

    # ── 现有 4H/1H MACD 路径（不变）────────────────────────
    macd_result = self._evaluate_macd_final(symbol, market_ctx)

    # ── 新增：Continuation Long 路径（并行）─────────────────
    breadth_state = self.breadth_detector.detect()

    if breadth_state["is_slow_bull"] and macd_result.direction != "long":
        # MACD 还没给多头 final，但广谱已满足，评估 continuation
        cont_result = self._evaluate_continuation_long_candidate(
            symbol          = symbol,
            symbol_ret_30m  = market_ctx.get("ret_30m", 0),
            symbol_ret_60m  = market_ctx.get("ret_60m", 0),
            rsi_15m         = market_ctx.get("rsi_15m", 50),
            ema_slope_15m   = market_ctx.get("ema_slope_15m", 0),
            close_15m       = market_ctx.get("close", 0),
            ema_fast_15m    = market_ctx.get("ema_fast_15m", 0),
            btc_ret_30m     = breadth_state.get("btc_ret_30m", 0),
            breadth_state   = breadth_state,
            vwap_score      = market_ctx.get("vwap_score", 0),
            corr_btc_alt    = self.btc_beta_scorer.get_btc_alt_corr(symbol),
        )

        if cont_result["allowed"]:
            self._log_info(
                f"[SLOW_BULL_CANDIDATE] {symbol} "
                f"{cont_result['reason']}"
            )
            return FinalDecision(
                operation      = "BUY",
                target_portion = cont_result["max_portion"],
                signal_type    = "continuation_long",
                signal_score   = 0.60,   # 统一标识分，不参与阈值竞争
                leverage       = self.config.min_leverage,   # 固定最低杠杆（3x）
                is_probe       = True,
            )
        else:
            self._log_debug(
                f"[SLOW_BULL_HOLD] {symbol} "
                f"{cont_result['reason']}"
            )

    # ── 慢牛中的 SHORT 降权 ───────────────────────────────────
    if macd_result.direction == "short":
        short_guard = self._apply_slow_bull_short_guard(
            direction      = "short",
            signal_1h      = market_ctx.get("signal_1h", ""),
            vwap_score     = market_ctx.get("vwap_score", 0),
            breadth_ratio  = breadth_state.get("breadth_ratio", 0),
            is_slow_bull   = breadth_state.get("is_slow_bull", False),
        )
        if short_guard["action"] == "BLOCK":
            return self._neutral_signal(reason=short_guard["reason"])
        if short_guard["action"] == "PROBE_CAP":
            macd_result.target_portion = min(
                macd_result.target_portion, short_guard["max_portion"]
            )

    # ── VWAP gate 慢牛 override ─────────────────────────────
    vwap_gate = self._apply_vwap_score_gate_with_bull_override(
        vwap_score      = market_ctx.get("vwap_score", 0),
        direction       = macd_result.direction,
        signal_type     = "normal",
        is_slow_bull    = breadth_state.get("is_slow_bull", False),
        current_portion = macd_result.target_portion,
    )
    if vwap_gate["action"] == "BLOCK":
        return self._neutral_signal(reason=vwap_gate["reason"])
    if "max_portion" in vwap_gate:
        macd_result.target_portion = min(
            macd_result.target_portion, vwap_gate["max_portion"]
        )

    return macd_result
```

---

## [命令-6] 可观测性日志

```python
# 必须在每个 symbol 每个 cycle 打印，不允许省略

def _log_entry_gate_result(
    self, symbol: str, stage: str, action: str, reason: str
) -> None:
    self._log_info(
        f"[ENTRY_GATE] {symbol} stage={stage} action={action} {reason}"
    )

# 各 gate 打印点：
# BTC regime gate:
self._log_info(f"[BTC_REGIME] {symbol} regime={btc_regime} action={action} reason={reason}")

# Slow bull detection（每 cycle 只打印一次，不是每 symbol）：
self._log_info(
    f"[SLOW_BULL] is_bull={state['is_slow_bull']} "
    f"breadth={state['breadth_ratio']:.2f} "
    f"btc30={state['btc_ret_30m']:.3%} "
    f"alt_med60={state['alt_median_60m']:.3%} "
    f"confirm={state['confirm_count']}"
)

# Continuation candidate：
self._log_info(f"[SLOW_BULL_CANDIDATE] {symbol} {reason}")
# 或没通过：
self._log_debug(f"[SLOW_BULL_HOLD] {symbol} {reason}")

# VWAP gate with bull override：
self._log_info(f"[VWAP_GATE] {symbol} score={vwap_score:.3f} action={action} slow_bull={is_slow_bull}")
```

---

## 配置修改

```diff
# config/trading_config_fund_flow.json

+ "market_breadth": {
+   "enabled":                  true,
+   "slow_bull_breadth_ratio":  0.60,
+   "slow_bull_btc_ret_30m":    0.003,
+   "slow_bull_btc_ret_60m":    0.005,
+   "slow_bull_alt_median_60m": 0.004,
+   "confirm_cycles":           2,
+   "invalidate_cycles":        2
+ },

+ "continuation_long": {
+   "enabled":              true,
+   "min_conditions_met":   4,
+   "ret_30m_threshold":    0.003,
+   "ret_60m_threshold":    0.006,
+   "rsi_min":              50,
+   "rsi_max":              72,
+   "leverage":             3,
+   "max_portion_6of6":     0.042,
+   "max_portion_5of6":     0.030,
+   "max_portion_4of6":     0.020,
+   "low_corr_strict_mode": true,
+   "low_corr_threshold":   0.20
+ },

  "vwap_score_gate": {
+   "slow_bull_override":   true,
+   "slow_bull_min_block":  0.050,    # 极端低分仍 block
+   "slow_bull_cap_0_12":   0.020,
+   "slow_bull_cap_0_30":   0.030,
  },

+ "slow_bull_short_guard": {
+   "enabled":              true,
+   "breadth_70_block_vwap": 0.50,
+   "breadth_60_block_vwap": 0.35,
+   "probe_max_portion":    0.042
+ }
```

---

## 验收标准

```bash
# 今天上线后，使用 2026-05-23 17:30 BJ 到 05-24 12:15 BJ 的回放：
grep "SLOW_BULL_CANDIDATE" logs/... | wc -l
# 预期：WLD/MORPHO/RENDER/JUP/ONDO/FET 至少各出现 1 次

grep "is_bull=True" logs/... | wc -l
# 预期：慢牛窗口内 > 50（说明广谱检测在运行）

# 验收指标
# 涨幅前 10 symbol 开多覆盖：从 1/10 → >= 5/10
# 慢牛窗口净 PnL：从负 → 正（目标 > 0）
# SHORT 在 breadth>70% 时的开仓次数：从 N 降到 < 2
```

---

## 执行清单

```
今天：
□ market_breadth.py 新文件，MarketBreadthDetector 实现
□ _evaluate_continuation_long_candidate() 写入 macd_strategy_v2.py
□ _apply_vwap_score_gate_with_bull_override() 替换原有 VWAP gate
□ _apply_slow_bull_short_guard() 插入 SHORT 判断链
□ 集成到 _evaluate_signal() 的并行路径
□ 可观测日志：SLOW_BULL/SLOW_BULL_CANDIDATE/VWAP_GATE/BTC_REGIME 全部实现
□ config 添加 market_breadth / continuation_long 块
□ 重启，verify_deployment.py ✅

不动：
❌ 4H/1H MACD final 路径（continuation 是并行路径，不替代）
❌ ExitGuard + BTC beta（已有效，不改）
❌ BTC 硬方向源（continuation 仍以单币动量为主判据）
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-24*  
*核心：广谱检测 → 单币动量 → 极小 probe（0.020~0.042）；不降阈值，而是新开路径*
