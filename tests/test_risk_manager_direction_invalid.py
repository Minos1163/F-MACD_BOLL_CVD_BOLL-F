from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.risk_manager import RiskManager


def _manager() -> RiskManager:
    return RiskManager(
        {
            "risk": {
                "conflict_protection": {
                    "cooldown_sec": 0,
                    "direction_invalid_enabled": True,
                    "direction_invalid_no_trade_confirm_bars": 2,
                    "direction_invalid_reduce_pct": 1.0,
                    "direction_invalid_low_score": 0.11,
                    "direction_invalid_mfe_trigger": 0.008,
                    "direction_invalid_mae_trigger": -0.008,
                    "direction_invalid_breakeven_buffer": 0.0005,
                }
            }
        }
    )


def test_long_no_trade_with_weakening_1h_reduces_after_two_cycles() -> None:
    manager = _manager()

    first = manager.check_position_protection(
        symbol="ONDOUSDT",
        position_side="LONG",
        macd_hist_norm=0.0,
        cvd_norm=0.0,
        market_regime="NO_TRADE",
        signal_type_1h="red_bar_shrinking",
        signal_score=0.20,
        now_ts=1.0,
    )
    second = manager.check_position_protection(
        symbol="ONDOUSDT",
        position_side="LONG",
        macd_hist_norm=0.0,
        cvd_norm=0.0,
        market_regime="NO_TRADE",
        signal_type_1h="red_bar_shrinking",
        signal_score=0.20,
        now_ts=2.0,
    )

    assert first["risk_state"] == "HOLD"
    assert second["risk_state"] == "REDUCE"
    assert second["reduce_position_pct"] == 1.0
    assert second["force_break_even"] is False
    assert "direction_invalid_no_trade" in second["reason"]


def test_long_profit_giveback_forces_breakeven_before_hard_stop() -> None:
    protection = _manager().check_position_protection(
        symbol="ONDOUSDT",
        position_side="LONG",
        macd_hist_norm=0.0,
        cvd_norm=0.0,
        market_regime="NO_TRADE",
        signal_type_1h="red_bar_shrinking",
        signal_score=0.20,
        max_favorable_ratio=0.0091,
        max_adverse_ratio=-0.0091,
        current_pnl_ratio=-0.001,
        now_ts=1.0,
    )

    assert protection["risk_state"] == "REDUCE"
    assert protection["force_break_even"] is True
    assert protection["reduce_position_pct"] == 0.0
    assert protection["breakeven_mode"] == "emergency_tighten"
    assert protection["breakeven_fee_buffer"] == 0.0005
    assert "direction_invalid_giveback" in protection["reason"]


def test_long_low_score_1h_divergence_escalates_to_direction_invalid_protection() -> None:
    protection = _manager().check_position_protection(
        symbol="ONDOUSDT",
        position_side="LONG",
        macd_hist_norm=0.0,
        cvd_norm=0.0,
        market_regime="NO_TRADE",
        signal_type_1h="red_bar_shrinking",
        signal_score=0.073,
        now_ts=1.0,
    )

    assert protection["level"] == "conflict_hard"
    assert protection["risk_state"] == "REDUCE"
    assert protection["allow_add"] is False
    assert protection["reduce_position_pct"] == 1.0
    assert "direction_invalid_low_score" in protection["reason"]
