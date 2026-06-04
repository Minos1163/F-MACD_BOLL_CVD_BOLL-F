from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List


@dataclass
class MarketBreadthConfig:
    enabled: bool = True
    slow_bull_breadth_ratio: float = 0.60
    slow_bull_btc_ret_30m: float = 0.003
    slow_bull_btc_ret_60m: float = 0.005
    slow_bull_alt_median_60m: float = 0.004
    slow_bear_breadth_ratio_max: float = 0.30
    slow_bear_btc_ret_30m: float = -0.003
    slow_bear_btc_ret_60m: float = -0.005
    slow_bear_alt_median_60m: float = -0.004
    mode_a_breadth_min: float = 0.80
    mode_a_alt_median_min: float = 0.0025
    mode_a_btc_min: float = -0.001
    mode_b_btc_30m_min: float = 0.002
    mode_b_breadth_min: float = 0.60
    mode_b_alt_median_min: float = 0.003
    mode_c_breadth_min: float = 0.90
    mode_c_alt_median_min: float = 0.001
    confirm_cycles: int = 2
    invalidate_cycles: int = 2


class MarketBreadthDetector:
    def __init__(self, config: MarketBreadthConfig | None, tracked_symbols: List[str]) -> None:
        self.cfg = config or MarketBreadthConfig()
        self.tracked = [str(s).upper() for s in tracked_symbols if str(s).strip()]
        self._confirm_count = 0
        self._invalid_count = 0
        self._is_slow_bull = False
        self._bear_confirm_count = 0
        self._bear_invalid_count = 0
        self._is_slow_bear = False
        self._alt_rets: Dict[str, Deque[float]] = {
            symbol: deque(maxlen=4) for symbol in self.tracked
        }
        self._btc_rets: Deque[float] = deque(maxlen=4)

    def update(self, btc_ret_15m: float, alt_rets: Dict[str, float]) -> None:
        self._btc_rets.append(float(btc_ret_15m or 0.0))
        if not isinstance(alt_rets, dict):
            return
        for raw_symbol, raw_ret in alt_rets.items():
            symbol = str(raw_symbol).upper()
            if symbol in self._alt_rets:
                self._alt_rets[symbol].append(float(raw_ret or 0.0))

    def detect(self) -> Dict[str, object]:
        if not self.cfg.enabled or len(self._btc_rets) < 2:
            return {"is_slow_bull": False, "is_slow_bear": False, "reason": "insufficient_data"}

        btc_values = list(self._btc_rets)
        btc_30m = sum(btc_values[-2:])
        btc_60m = sum(btc_values[-4:]) if len(btc_values) >= 4 else btc_30m

        alt_60m_rets: List[float] = []
        for ret_queue in self._alt_rets.values():
            values = list(ret_queue)
            if len(values) >= 4:
                alt_60m_rets.append(sum(values[-4:]))
            elif len(values) >= 2:
                alt_60m_rets.append(sum(values[-2:]))

        if not alt_60m_rets:
            return {"is_slow_bull": False, "is_slow_bear": False, "reason": "no_alt_data"}

        alt_60m_rets.sort()
        n = len(alt_60m_rets)
        midpoint = n // 2
        if n % 2:
            alt_median_60m = alt_60m_rets[midpoint]
        else:
            alt_median_60m = (alt_60m_rets[midpoint - 1] + alt_60m_rets[midpoint]) / 2.0
        breadth_ratio = sum(1 for ret in alt_60m_rets if ret > 0.0) / float(n)

        legacy_conditions = {
            "btc_30m": btc_30m >= float(self.cfg.slow_bull_btc_ret_30m),
            "btc_60m": btc_60m >= float(self.cfg.slow_bull_btc_ret_60m),
            "breadth": breadth_ratio >= float(self.cfg.slow_bull_breadth_ratio),
            "alt_median": alt_median_60m >= float(self.cfg.slow_bull_alt_median_60m),
        }
        mode_a = (
            breadth_ratio >= float(self.cfg.mode_a_breadth_min)
            and alt_median_60m >= float(self.cfg.mode_a_alt_median_min)
            and btc_30m >= float(self.cfg.mode_a_btc_min)
        )
        mode_b = (
            btc_30m >= float(self.cfg.mode_b_btc_30m_min)
            and breadth_ratio >= float(self.cfg.mode_b_breadth_min)
            and alt_median_60m >= float(self.cfg.mode_b_alt_median_min)
        )
        mode_c = (
            breadth_ratio >= float(self.cfg.mode_c_breadth_min)
            and alt_median_60m >= float(self.cfg.mode_c_alt_median_min)
        )
        is_bull_candidate = mode_a or mode_b or mode_c
        is_bear_candidate = (
            btc_30m <= float(self.cfg.slow_bear_btc_ret_30m)
            and btc_60m <= float(self.cfg.slow_bear_btc_ret_60m)
            and breadth_ratio <= float(self.cfg.slow_bear_breadth_ratio_max)
            and alt_median_60m <= float(self.cfg.slow_bear_alt_median_60m)
        )

        if is_bull_candidate:
            self._confirm_count = min(self._confirm_count + 1, int(self.cfg.confirm_cycles))
            self._invalid_count = 0
        else:
            self._invalid_count = min(self._invalid_count + 1, int(self.cfg.invalidate_cycles))
            self._confirm_count = max(self._confirm_count - 1, 0)

        if self._confirm_count >= int(self.cfg.confirm_cycles):
            self._is_slow_bull = True
        if self._invalid_count >= int(self.cfg.invalidate_cycles):
            self._is_slow_bull = False

        if is_bear_candidate:
            self._bear_confirm_count = min(self._bear_confirm_count + 1, int(self.cfg.confirm_cycles))
            self._bear_invalid_count = 0
        else:
            self._bear_invalid_count = min(self._bear_invalid_count + 1, int(self.cfg.invalidate_cycles))
            self._bear_confirm_count = max(self._bear_confirm_count - 1, 0)

        if self._bear_confirm_count >= int(self.cfg.confirm_cycles):
            self._is_slow_bear = True
            self._is_slow_bull = False
        if self._bear_invalid_count >= int(self.cfg.invalidate_cycles):
            self._is_slow_bear = False

        mode = "alt_breadth_led" if mode_a else "btc_led" if mode_b else "extreme_breadth" if mode_c else None
        reason = (
            f"mode_a={'OK' if mode_a else 'FAIL'} "
            f"mode_b={'OK' if mode_b else 'FAIL'} "
            f"mode_c={'OK' if mode_c else 'FAIL'} | "
            + " | ".join(f"{key}={'OK' if value else 'FAIL'}" for key, value in legacy_conditions.items())
        )
        return {
            "is_slow_bull": self._is_slow_bull,
            "is_slow_bear": self._is_slow_bear,
            "mode": mode if self._is_slow_bull else None,
            "slow_bear_mode": "bear_breadth_led" if self._is_slow_bear else None,
            "breadth_ratio": breadth_ratio,
            "btc_ret_30m": btc_30m,
            "btc_ret_60m": btc_60m,
            "alt_median_60m": alt_median_60m,
            "confirm_count": self._confirm_count,
            "invalid_count": self._invalid_count,
            "bear_confirm_count": self._bear_confirm_count,
            "bear_invalid_count": self._bear_invalid_count,
            "reason": reason,
        }
