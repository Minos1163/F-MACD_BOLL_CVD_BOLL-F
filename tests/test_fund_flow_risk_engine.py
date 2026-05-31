from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.models import FundFlowDecision, Operation
from src.fund_flow.risk_engine import FundFlowRiskEngine


def _risk() -> FundFlowRiskEngine:
    return FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_open_portion": 0.06,
                "max_open_portion": 1.0,
                "min_open_notional": {
                    "default_usdt": 2.0,
                    "btc_usdt": 5.0,
                    "major_symbols": ["BTCUSDT"],
                },
                "probe_floor_rescue": {
                    "probe_min_open_portion": 0.042,
                    "min_score_threshold": 0.80,
                },
            }
        },
        symbol_whitelist=["ATOMUSDT", "BTCUSDT"],
    )


def _risk_with_symbols(*symbols: str) -> FundFlowRiskEngine:
    return FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 5,
                "max_open_portion": 1.0,
                "min_open_notional": {
                    "default_usdt": 2.0,
                    "btc_usdt": 5.0,
                    "major_usdt": 2.0,
                    "major_symbols": ["BTCUSDT", "SOLUSDT"],
                },
                "final_signal_notional_floor": {"enabled": True, "apply_to_final_only": True},
            }
        },
        symbol_whitelist=list(symbols),
    )


def test_risk_engine_caps_entry_portion_by_max_single_position_notional() -> None:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 3,
                "max_open_portion": 1.0,
                "max_single_position_notional": 40.0,
                "min_open_notional": {"default_usdt": 0.0},
                "final_signal_notional_floor": {"enabled": False},
            }
        },
        symbol_whitelist=["ATOMUSDT"],
    )
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.50,
        leverage=3,
        metadata={"account_equity": 100.0},
    )

    validated = risk.validate_decision(decision)

    assert validated.target_portion_of_balance == pytest.approx(40.0 / (100.0 * 3.0))
    assert validated.metadata["max_single_position_notional_cap_applied"] is True
    assert validated.metadata["max_single_position_notional"] == pytest.approx(40.0)


def test_risk_engine_allows_atom_probe_when_notional_exceeds_default_minimum() -> None:
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.042,
        leverage=4,
        metadata={"account_equity": 111.18, "signal_score": 0.7292},
    )

    validated = _risk().validate_decision(decision)

    assert validated.target_portion_of_balance == pytest.approx(0.042)


def test_risk_engine_blocks_btc_probe_below_btc_minimum_notional() -> None:
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.042,
        leverage=4,
        metadata={"account_equity": 111.18, "signal_score": 0.7292},
    )

    validated = _risk().validate_decision(decision)

    assert validated.operation is Operation.HOLD
    assert validated.target_portion_of_balance == pytest.approx(0.0)
    assert "min_notional_below_floor" in validated.reason


def test_risk_engine_reads_probe_floor_rescue_nested_probe_portion() -> None:
    assert _risk().probe_min_open_portion == pytest.approx(0.042)


def test_risk_engine_lifts_final_passed_short_to_executable_notional_floor() -> None:
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.010,
        leverage=3,
        metadata={
            "account_equity": 111.18,
            "signal_score": 0.75,
            "signal_score_threshold": 0.66,
            "stage": "final",
        },
    )

    validated = _risk_with_symbols("ATOMUSDT").validate_decision(decision)

    assert validated.operation is Operation.SELL
    assert validated.target_portion_of_balance == pytest.approx(2.0 / 111.18)
    assert validated.metadata["short_executable_floor_applied"] is True


def test_risk_engine_lifts_final_passed_short_micro_position_without_ratio_cap() -> None:
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="JSTUSDT",
        target_portion_of_balance=0.000315,
        leverage=3,
        metadata={
            "account_equity": 111.18,
            "signal_score": 0.70,
            "signal_score_threshold": 0.66,
            "stage": "final",
        },
    )

    validated = _risk_with_symbols("JSTUSDT").validate_decision(decision)

    assert validated.operation is Operation.SELL
    assert validated.target_portion_of_balance == pytest.approx(2.0 / 111.18)
    assert validated.leverage == 3
    assert validated.metadata["final_signal_notional_floor_applied"] is True
    assert validated.metadata["min_notional_lift_ratio"] > 5.0


@pytest.mark.parametrize(
    ("operation", "symbol", "expected_notional"),
    [
        (Operation.BUY, "ATOMUSDT", 2.0),
        (Operation.SELL, "ATOMUSDT", 2.0),
        (Operation.BUY, "BTCUSDT", 5.0),
        (Operation.SELL, "BTCUSDT", 5.0),
    ],
)
def test_risk_engine_lifts_final_passed_buy_and_sell_to_symbol_min_notional(
    operation: Operation,
    symbol: str,
    expected_notional: float,
) -> None:
    decision = FundFlowDecision(
        operation=operation,
        symbol=symbol,
        target_portion_of_balance=0.000315,
        leverage=3,
        metadata={
            "account_equity": 111.18,
            "signal_score": 0.70,
            "signal_score_threshold": 0.66,
            "stage": "final",
        },
    )

    validated = _risk_with_symbols("ATOMUSDT", "BTCUSDT").validate_decision(decision)

    assert validated.operation is operation
    assert validated.target_portion_of_balance == pytest.approx(expected_notional / 111.18)
    assert validated.leverage == 3
    assert validated.metadata["final_signal_notional_floor_applied"] is True
    assert validated.metadata["min_notional_usdt"] == pytest.approx(expected_notional)


def test_risk_engine_final_floor_does_not_exceed_gate_cap() -> None:
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.000315,
        leverage=3,
        metadata={
            "account_equity": 111.18,
            "signal_score": 0.70,
            "signal_score_threshold": 0.66,
            "stage": "final",
            "gate_cap_applied": True,
            "gate_cap_portion": 0.042,
        },
    )

    validated = _risk_with_symbols("BTCUSDT").validate_decision(decision)

    assert validated.operation is Operation.BUY
    assert validated.target_portion_of_balance == pytest.approx(0.042)
    assert validated.metadata["final_signal_notional_floor_applied"] is True
    assert validated.metadata["gate_cap_applied"] is True
    assert validated.metadata["gate_cap_portion"] == pytest.approx(0.042)


def test_risk_engine_holds_non_final_short_micro_position_below_notional_floor() -> None:
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="JSTUSDT",
        target_portion_of_balance=0.000315,
        leverage=3,
        metadata={"account_equity": 111.18, "signal_score": 0.70},
    )

    validated = _risk_with_symbols("JSTUSDT").validate_decision(decision)

    assert validated.operation is Operation.HOLD
    assert validated.target_portion_of_balance == pytest.approx(0.0)
    assert "min_notional_below_floor" in validated.reason
    assert validated.metadata["final_signal_notional_floor_applied"] is False


def test_risk_engine_uses_two_usdt_for_major_symbols_except_btc() -> None:
    risk = _risk_with_symbols("SOLUSDT", "BTCUSDT")

    assert risk._get_min_notional("SOLUSDT") == pytest.approx(2.0)
    assert risk._get_min_notional("BTCUSDT") == pytest.approx(5.0)


def test_risk_engine_uses_leverage_adjusted_notional_floor_for_quadrant_resonance_entries() -> None:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 5,
                "max_open_portion": 1.0,
                "min_open_notional": {"default_usdt": 2.0, "btc_usdt": 5.0, "major_usdt": 2.0},
                "final_signal_notional_floor": {"enabled": True, "apply_to_final_only": True},
                "quadrant_resonance": {"risk": {"min_entry_notional_usdt": 12.0, "min_entry_margin_usdt": 1.0}},
            }
        },
        symbol_whitelist=["ICPUSDT"],
    )
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ICPUSDT",
        target_portion_of_balance=0.01,
        leverage=3,
        metadata={
            "strategy_mode": "quadrant_resonance",
            "account_equity": 100.0,
            "signal_score": 0.85,
            "signal_score_threshold": 0.80,
            "stage": "final",
        },
    )

    validated = risk.validate_decision(decision)

    assert validated.operation is Operation.BUY
    assert validated.target_portion_of_balance == pytest.approx(0.04)
    assert validated.metadata["min_notional_usdt"] == pytest.approx(12.0)
    assert validated.metadata["min_entry_margin_usdt"] == pytest.approx(1.0)


def test_risk_engine_revalidates_min_notional_after_account_risk_scaler() -> None:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "max_open_portion": 1.0,
                "min_open_notional": {"default_usdt": 2.0, "btc_usdt": 5.0, "major_usdt": 2.0},
                "account_risk": {
                    "enabled": True,
                    "exposure_scaler_enabled": True,
                    "exposure_scaler_value": 0.85,
                    "leverage_scaler_enabled": False,
                    },
                    "final_signal_notional_floor": {"enabled": True, "apply_to_final_only": True},
                }
            },
            symbol_whitelist=["ATOMUSDT"],
        )
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.020,
        leverage=3,
        metadata={
            "account_equity": 111.18,
            "signal_score": 0.75,
            "signal_score_threshold": 0.66,
            "stage": "final",
        },
    )

    validated = risk.validate_decision(decision)

    assert validated.operation is Operation.SELL
    assert validated.target_portion_of_balance == pytest.approx(2.0 / 111.18)
    assert validated.metadata["min_notional_post_account_risk_revalidated"] is True
