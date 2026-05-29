from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.exit_signal_guard import PositionExitSignalGuard


def test_exit_signal_guard_blocks_dca_on_first_reverse_bar() -> None:
    guard = PositionExitSignalGuard(
        {
            "enabled": True,
            "confirm_bars_required": 2,
            "mae_trigger_pct": -0.008,
            "block_dca_on_reverse": True,
        }
    )

    result = guard.evaluate(
        symbol="TRUMPUSDT",
        position={"side": "LONG", "unrealized_pnl_pct": -0.0137},
        signal_now={
            "signal_1h": "red_bar_shrinking",
            "veto_code": "rsi_1h_direction_against_veto",
        },
    )

    assert result["action"] == "BLOCK_DCA"
    assert result["block_dca"] is True
    assert result["reverse_bars"] == 1


def test_exit_signal_guard_reduces_then_closes_after_confirmed_reverse() -> None:
    guard = PositionExitSignalGuard(
        {
            "enabled": True,
            "confirm_bars_required": 2,
            "mae_trigger_pct": -0.008,
            "block_dca_on_reverse": True,
        }
    )
    position = {"side": "LONG", "unrealized_pnl_pct": -0.0137}
    signal = {"signal_1h": "red_bar_shrinking"}

    first = guard.evaluate("TRUMPUSDT", position, signal)
    second = guard.evaluate("TRUMPUSDT", position, signal)
    third = guard.evaluate("TRUMPUSDT", position, signal)

    assert first["action"] == "BLOCK_DCA"
    assert second["action"] == "REDUCE"
    assert second["reduce_pct"] == 0.50
    assert second["block_dca"] is True
    assert third["action"] == "CLOSE"
    assert third["reduce_pct"] == 1.00


def test_exit_signal_guard_resets_reverse_bars_when_signal_recovers() -> None:
    guard = PositionExitSignalGuard({"enabled": True, "confirm_bars_required": 2})

    guard.evaluate(
        "TRUMPUSDT",
        {"side": "LONG", "unrealized_pnl_pct": -0.02},
        {"signal_1h": "red_bar_shrinking"},
    )
    result = guard.evaluate(
        "TRUMPUSDT",
        {"side": "LONG", "unrealized_pnl_pct": -0.02},
        {"signal_1h": "red_bar_growing"},
    )

    assert result["action"] == "HOLD"
    assert result["reverse_bars"] == 0
