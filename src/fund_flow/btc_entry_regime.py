from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List


class BtcRegime(Enum):
    RISING = "rising"
    FALLING = "falling"
    CHOPPY = "choppy"


class BtcEntryRegimeGate:
    """Entry-layer BTC regime guard using closed 15m BTC returns."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.falling_avg_ret = float(cfg.get("falling_avg_ret", -0.001))
        self.rising_avg_ret = float(cfg.get("rising_avg_ret", 0.001))
        self.chase_short_block_bars = int(float(cfg.get("chase_short_block_bars", 4)))
        self.chase_short_ret_threshold = float(cfg.get("chase_short_ret_threshold", -0.015))
        self.chase_short_block_vwap = float(cfg.get("chase_short_block_vwap", 0.50))
        self.btc_falling_low_vwap_block = float(cfg.get("btc_falling_low_vwap_block", 0.30))
        self.btc_falling_below_vwap_probe_max = float(cfg.get("btc_falling_below_vwap_probe_max", 0.042))

    def detect_btc_regime(self, btc_rets_4bar: List[float]) -> BtcRegime:
        values = [float(x) for x in (btc_rets_4bar or []) if x is not None]
        if len(values) < 4:
            return BtcRegime.CHOPPY
        window = values[-4:]
        avg = sum(window) / float(len(window))
        if avg < self.falling_avg_ret:
            return BtcRegime.FALLING
        if avg > self.rising_avg_ret:
            return BtcRegime.RISING
        return BtcRegime.CHOPPY

    def check_entry(
        self,
        *,
        direction: str,
        btc_regime: BtcRegime,
        vwap_score: float,
        vwap_dev_pct: float,
        signal_4h: str,
        btc_cumret_4bar: float,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"action": "PASS", "reason": "btc_gate_disabled"}

        direction_norm = str(direction or "").strip().lower()
        vwap = float(vwap_score or 0.0)
        dev = float(vwap_dev_pct or 0.0)
        cum4 = float(btc_cumret_4bar or 0.0)

        if btc_regime == BtcRegime.FALLING and direction_norm == "long":
            if vwap < self.btc_falling_low_vwap_block:
                return {
                    "action": "BLOCK",
                    "reason": f"btc_falling+low_vwap_long_block vwap={vwap:.3f}",
                }
            if dev < -0.005 and vwap < 0.60:
                return {
                    "action": "PROBE_CAP",
                    "max_portion": self.btc_falling_below_vwap_probe_max,
                    "reason": f"btc_falling+below_vwap_long_probe dev={dev:.2%} vwap={vwap:.3f}",
                }

        if direction_norm == "short" and cum4 <= self.chase_short_ret_threshold:
            if vwap < self.chase_short_block_vwap:
                return {
                    "action": "BLOCK",
                    "reason": f"btc_chase_short_block: btc_cum4={cum4:.2%} vwap={vwap:.3f}",
                }
            return {
                "action": "PROBE_CAP",
                "max_portion": self.btc_falling_below_vwap_probe_max,
                "reason": f"btc_chase_short_probe: btc_cum4={cum4:.2%} vwap={vwap:.3f}",
            }

        if btc_regime == BtcRegime.RISING and direction_norm == "short":
            if vwap < 0.40:
                return {
                    "action": "BLOCK",
                    "reason": f"btc_rising+low_vwap_short_block vwap={vwap:.3f}",
                }

        return {"action": "PASS", "reason": "btc_regime_gate_pass"}
