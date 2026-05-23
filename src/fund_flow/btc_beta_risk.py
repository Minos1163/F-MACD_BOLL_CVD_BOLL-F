from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Deque, Dict, List, Tuple


@dataclass
class BtcBetaRiskConfig:
    enabled: bool = True
    warmup_on_start: bool = True
    warmup_kline_limit: int = 50
    default_corr_major_symbols: float = 0.40
    min_corr_for_btc_weight: float = 0.20
    btc_against_long_pct: float = -0.0015
    btc_against_short_pct: float = 0.0015
    alt_against_15m_pct: float = -0.0010
    alt_against_30m_pct: float = -0.0015
    corr_window_bars: int = 48
    fast_fail_window_bars: int = 2
    fast_fail_mae_threshold: float = -0.002
    fast_fail_mfe_threshold: float = 0.002
    risk_score_reduce_threshold: int = 2
    risk_score_close_threshold: int = 4
    small_notional_close_threshold: float = 10.0


class BtcPriceCache:
    """Small closed-bar close-price cache for 15m/30m return calculations."""

    def __init__(self, max_bars: int = 6) -> None:
        self._prices: Deque[float] = deque(maxlen=max(3, int(max_bars)))

    def push(self, close_price: float) -> None:
        price = float(close_price)
        if price > 0:
            self._prices.append(price)

    def ret_15m(self) -> float:
        if len(self._prices) < 2 or self._prices[-2] <= 0:
            return 0.0
        return (self._prices[-1] - self._prices[-2]) / self._prices[-2]

    def ret_30m(self) -> float:
        if len(self._prices) < 3 or self._prices[-3] <= 0:
            return 0.0
        return (self._prices[-1] - self._prices[-3]) / self._prices[-3]


class BtcBetaRiskScorer:
    """Scores whether BTC beta plus local 15m movement should accelerate exits."""

    def __init__(self, config: BtcBetaRiskConfig | None = None) -> None:
        self.cfg = config or BtcBetaRiskConfig()
        self._corr_history: Dict[str, Deque[Tuple[float, float]]] = {}

    def update_corr_history(self, symbol: str, btc_ret_15m: float, alt_ret_15m: float) -> None:
        key = str(symbol or "").upper()
        if not key:
            return
        if key not in self._corr_history:
            self._corr_history[key] = deque(maxlen=max(10, int(self.cfg.corr_window_bars)))
        self._corr_history[key].append((float(btc_ret_15m), float(alt_ret_15m)))

    def warmup_from_klines(self, symbol: str, btc_closes: List[float], alt_closes: List[float]) -> None:
        key = str(symbol or "").upper()
        if not key:
            return
        n = min(len(btc_closes or []), len(alt_closes or []))
        if n < 2:
            return
        if key not in self._corr_history:
            self._corr_history[key] = deque(maxlen=max(10, int(self.cfg.corr_window_bars)))
        for i in range(1, n):
            btc_prev = float(btc_closes[i - 1] or 0.0)
            alt_prev = float(alt_closes[i - 1] or 0.0)
            btc_now = float(btc_closes[i] or 0.0)
            alt_now = float(alt_closes[i] or 0.0)
            if btc_prev <= 0 or alt_prev <= 0:
                continue
            self._corr_history[key].append(((btc_now - btc_prev) / btc_prev, (alt_now - alt_prev) / alt_prev))

    def get_btc_alt_corr(self, symbol: str) -> float:
        key = str(symbol or "").upper()
        hist = list(self._corr_history.get(key, ()))
        if len(hist) < 10:
            return self._get_default_corr(key)
        btc = [item[0] for item in hist]
        alt = [item[1] for item in hist]
        return _pearson_corr(btc, alt)

    def _get_default_corr(self, symbol: str) -> float:
        major_defaults = {
            "ETHUSDT": float(self.cfg.default_corr_major_symbols),
            "SOLUSDT": float(self.cfg.default_corr_major_symbols),
            "BNBUSDT": float(self.cfg.default_corr_major_symbols),
            "ADAUSDT": float(self.cfg.default_corr_major_symbols),
            "AVAXUSDT": float(self.cfg.default_corr_major_symbols),
            "XRPUSDT": 0.35,
            "DOGEUSDT": 0.35,
            "DOTUSDT": 0.35,
            "LINKUSDT": 0.35,
        }
        return float(major_defaults.get(str(symbol or "").upper(), 0.0))

    def score(
        self,
        *,
        symbol: str,
        direction: str,
        btc_ret_15m: float,
        btc_ret_30m: float,
        alt_ret_15m: float,
        alt_ret_30m: float,
        position_age_bars: int,
        mfe_pct: float,
        mae_pct: float,
        position_notional: float | None = None,
    ) -> Dict[str, object]:
        cfg = self.cfg
        if not cfg.enabled:
            return {"risk_score": 0, "action": "HOLD", "reason": "disabled", "use_btc": False}

        direction_norm = str(direction or "").strip().lower()
        corr = self.get_btc_alt_corr(symbol)
        use_btc = corr >= float(cfg.min_corr_for_btc_weight)
        risk_score = 0
        reasons: List[str] = []

        if direction_norm == "short":
            alt_against_15m = float(alt_ret_15m) >= abs(float(cfg.alt_against_15m_pct))
            alt_against_30m = float(alt_ret_30m) >= abs(float(cfg.alt_against_30m_pct))
            btc_against_15m = float(btc_ret_15m) >= float(cfg.btc_against_short_pct)
            btc_against_30m = float(btc_ret_30m) >= float(cfg.btc_against_short_pct) * 1.5
        else:
            alt_against_15m = float(alt_ret_15m) <= float(cfg.alt_against_15m_pct)
            alt_against_30m = float(alt_ret_30m) <= float(cfg.alt_against_30m_pct)
            btc_against_15m = float(btc_ret_15m) <= float(cfg.btc_against_long_pct)
            btc_against_30m = float(btc_ret_30m) <= float(cfg.btc_against_long_pct) * 1.5

        if alt_against_15m:
            risk_score += 1
            reasons.append(f"alt_15m_against({float(alt_ret_15m):.3%})")
        if alt_against_30m:
            risk_score += 1
            reasons.append(f"alt_30m_against({float(alt_ret_30m):.3%})")

        if use_btc:
            if btc_against_15m:
                risk_score += 1
                reasons.append(f"btc_15m_against({float(btc_ret_15m):.3%},corr={corr:.2f})")
            if btc_against_30m and alt_against_30m:
                risk_score += 1
                reasons.append(f"btc_alt_30m_sync({float(btc_ret_30m):.3%},{float(alt_ret_30m):.3%})")

        in_fast_fail = int(position_age_bars) <= int(cfg.fast_fail_window_bars)
        no_mfe_gain = float(mfe_pct) < float(cfg.fast_fail_mfe_threshold)
        has_mae = float(mae_pct) <= float(cfg.fast_fail_mae_threshold)
        if in_fast_fail and (alt_against_15m or (use_btc and btc_against_15m)):
            if no_mfe_gain and has_mae:
                risk_score += 2
                reasons.append(
                    f"fast_fail(age={int(position_age_bars)}bars,mfe={float(mfe_pct):.3%},mae={float(mae_pct):.3%})"
                )
            elif no_mfe_gain:
                risk_score += 1
                reasons.append(f"fast_fail_no_mfe(age={int(position_age_bars)}bars)")

        reason = " | ".join(reasons) if reasons else "no_risk"
        small_notional_close = False
        notional = None if position_notional is None else float(position_notional)
        if risk_score >= int(cfg.risk_score_close_threshold):
            action = "CLOSE"
        elif risk_score >= int(cfg.risk_score_reduce_threshold):
            if notional is not None and 0.0 <= notional < float(cfg.small_notional_close_threshold):
                action = "CLOSE"
                small_notional_close = True
                reasons.append(f"small_notional_close({notional:.2f}U)")
                reason = " | ".join(reasons) if reasons else reason
            else:
                action = "REDUCE_50"
        elif risk_score == 1 and in_fast_fail:
            if notional is not None and 0.0 <= notional < float(cfg.small_notional_close_threshold):
                action = "CLOSE"
                small_notional_close = True
                reason = f"{reason} | small_notional_close({notional:.2f}U) [fast_fail_window]"
            else:
                action = "REDUCE_50"
                reason = f"{reason} [fast_fail_window]"
        else:
            action = "HOLD"
        return {
            "risk_score": risk_score,
            "action": action,
            "reason": reason,
            "use_btc": use_btc,
            "corr": corr,
            "position_notional": notional,
            "small_notional_close": small_notional_close,
        }


def _pearson_corr(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denom_x = sum(x * x for x in dx)
    denom_y = sum(y * y for y in dy)
    if denom_x <= 0 or denom_y <= 0:
        return 0.0
    return float(sum(x * y for x, y in zip(dx, dy)) / sqrt(denom_x * denom_y))
