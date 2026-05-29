from __future__ import annotations

from typing import Any, Dict


class PositionExitSignalGuard:
    """Convert in-position reverse strategy signals into DCA blocks and exits."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        cfg = config if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.bearish_1h_signals = set(
            cfg.get(
                "bearish_1h_signals",
                ["flip_bearish", "green_bar_growing", "green_bar_shrinking", "red_bar_shrinking"],
            )
        )
        self.bullish_1h_signals = set(
            cfg.get(
                "bullish_1h_signals",
                ["flip_bullish", "red_bar_growing", "red_bar_shrinking", "green_bar_shrinking"],
            )
        )
        self.confirm_bars_required = max(1, int(cfg.get("confirm_bars_required", 2) or 2))
        self.mae_trigger_pct = float(cfg.get("mae_trigger_pct", -0.008) or -0.008)
        self.block_dca_on_reverse = bool(cfg.get("block_dca_on_reverse", True))
        self.reduce_pct = max(0.0, min(1.0, float(cfg.get("reduce_pct", 0.50) or 0.50)))
        self._reverse_bars: Dict[str, int] = {}

    def evaluate(self, symbol: str, position: Dict[str, Any], signal_now: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {"action": "HOLD", "block_dca": False, "reason": "guard disabled"}

        symbol_key = str(symbol or "").upper()
        side = str(position.get("side", "")).upper()
        signal_1h = str(signal_now.get("signal_1h") or signal_now.get("signal_type_1h") or "").strip()
        veto_code = str(signal_now.get("veto_code") or signal_now.get("reject_code") or signal_now.get("hold_code") or "")
        mae_pct = float(position.get("unrealized_pnl_pct", position.get("pnl_ratio", 0.0)) or 0.0)

        is_reverse = False
        if side == "LONG" and signal_1h in self.bearish_1h_signals:
            is_reverse = True
        elif side == "SHORT" and signal_1h in self.bullish_1h_signals:
            is_reverse = True
        if "rsi_1h_direction_against_veto" in veto_code:
            is_reverse = True

        if is_reverse:
            bars = int(self._reverse_bars.get(symbol_key, 0) or 0) + 1
            self._reverse_bars[symbol_key] = bars
        else:
            bars = 0
            self._reverse_bars[symbol_key] = 0

        block_dca = bool(is_reverse and self.block_dca_on_reverse)
        if not is_reverse:
            return {
                "action": "HOLD",
                "block_dca": False,
                "reverse_bars": bars,
                "reason": f"no reverse signal ({signal_1h})",
            }

        if bars >= self.confirm_bars_required and mae_pct <= self.mae_trigger_pct:
            if bars >= self.confirm_bars_required + 1:
                return {
                    "action": "CLOSE",
                    "reduce_pct": 1.0,
                    "block_dca": block_dca,
                    "reverse_bars": bars,
                    "reason": f"reverse signal confirmed {bars} bars, mae={mae_pct:.2%}, full close",
                }
            return {
                "action": "REDUCE",
                "reduce_pct": self.reduce_pct,
                "block_dca": block_dca,
                "reverse_bars": bars,
                "reason": f"reverse signal confirmed {bars} bars, mae={mae_pct:.2%}, reduce {self.reduce_pct:.0%}",
            }

        if block_dca:
            return {
                "action": "BLOCK_DCA",
                "reduce_pct": 0.0,
                "block_dca": True,
                "reverse_bars": bars,
                "reason": f"reverse signal detected ({signal_1h or veto_code}), DCA blocked",
            }

        return {
            "action": "HOLD",
            "block_dca": False,
            "reverse_bars": bars,
            "reason": f"reverse signal waiting confirmation (bars={bars}, mae={mae_pct:.2%})",
        }

