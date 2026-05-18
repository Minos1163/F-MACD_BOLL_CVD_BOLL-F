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
                "max_open_portion": 1.0,
                "min_open_notional": {
                    "default_usdt": 2.0,
                    "btc_usdt": 5.0,
                    "major_usdt": 2.0,
                    "major_symbols": ["BTCUSDT", "SOLUSDT"],
                },
                "macd_mtf_strategy_v2": {
                    "position_management": {
                        "short_floor_max_lift_ratio": 5.0,
                    }
                },
            }
        },
        symbol_whitelist=list(symbols),
    )


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


def test_risk_engine_lifts_short_to_executable_notional_floor_when_ratio_reasonable() -> None:
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.010,
        leverage=3,
        metadata={"account_equity": 111.18, "signal_score": 0.75},
    )

    validated = _risk_with_symbols("ATOMUSDT").validate_decision(decision)

    assert validated.operation is Operation.SELL
    assert validated.target_portion_of_balance == pytest.approx(2.0 / 111.18)
    assert validated.metadata["short_executable_floor_applied"] is True


def test_risk_engine_holds_short_micro_position_when_lift_ratio_is_too_large() -> None:
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
    assert validated.metadata["min_notional_lift_ratio"] > 5.0


def test_risk_engine_uses_two_usdt_for_major_symbols_except_btc() -> None:
    risk = _risk_with_symbols("SOLUSDT", "BTCUSDT")

    assert risk._get_min_notional("SOLUSDT") == pytest.approx(2.0)
    assert risk._get_min_notional("BTCUSDT") == pytest.approx(5.0)


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
                "macd_mtf_strategy_v2": {
                    "position_management": {"short_floor_max_lift_ratio": 5.0}
                },
            }
        },
        symbol_whitelist=["ATOMUSDT"],
    )
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.020,
        leverage=3,
        metadata={"account_equity": 111.18, "signal_score": 0.75},
    )

    validated = risk.validate_decision(decision)

    assert validated.operation is Operation.SELL
    assert validated.target_portion_of_balance == pytest.approx(2.0 / 111.18)
    assert validated.metadata["min_notional_post_account_risk_revalidated"] is True
