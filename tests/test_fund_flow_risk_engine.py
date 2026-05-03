import pytest

from src.fund_flow.models import FundFlowDecision, Operation
from src.fund_flow.risk_engine import FundFlowRiskEngine


def _cfg():
    return {
        "trading": {"max_leverage": 10, "default_leverage": 3},
        "fund_flow": {
            "min_open_portion": 0.1,
            "max_open_portion": 1.0,
            "price_deviation_limit_percent": 1.0,
        },
    }


def _account_risk_cfg():
    cfg = _cfg()
    cfg["fund_flow"].update(
        {
            "min_leverage": 1,
            "default_leverage": 3,
            "max_leverage": 4,
            "account_risk": {
                "enabled": True,
                "target_max_drawdown_pct": 7.0,
                "strategy_reference_mdd_pct": 8.23,
                "exposure_scaler_enabled": True,
                "exposure_scaler_value": 0.85,
                "leverage_scaler_enabled": True,
                "leverage_scaler_value": 0.85,
                "leverage_rounding": "floor",
                "min_scaled_leverage": 1,
                "metadata_enabled": True,
            },
        }
    )
    return cfg


def test_clamp_leverage_out_of_range_fallback():
    engine = FundFlowRiskEngine(_cfg(), symbol_whitelist=["BTCUSDT"])
    assert engine.clamp_leverage(999) == 10
    assert engine.clamp_leverage(0) == 3


def test_validate_open_portion_range():
    engine = FundFlowRiskEngine(_cfg(), symbol_whitelist=["BTCUSDT"])
    with pytest.raises(ValueError):
        engine.validate_target_portion(0.05, Operation.BUY)
    assert engine.validate_target_portion(0.2, Operation.BUY) == 0.2


def test_enforce_price_bounds():
    engine = FundFlowRiskEngine(_cfg(), symbol_whitelist=["BTCUSDT"])
    bounded = engine.enforce_price_bounds(price=102.5, oracle_price=100.0)
    assert bounded == pytest.approx(101.0)


def test_validate_decision_symbol_whitelist():
    engine = FundFlowRiskEngine(_cfg(), symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(operation=Operation.BUY, symbol="ETHUSDT", target_portion_of_balance=0.2)
    with pytest.raises(ValueError):
        engine.validate_decision(decision)


@pytest.mark.parametrize(
    ("input_leverage", "expected_leverage"),
    [
        (3, 2),
        (4, 3),
        (2, 1),
    ],
)
def test_account_risk_scaler_scales_open_portion_and_integer_leverage(input_leverage, expected_leverage):
    engine = FundFlowRiskEngine(_account_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=input_leverage,
    )

    result = engine.validate_decision(decision)

    assert result.target_portion_of_balance == pytest.approx(0.2975, rel=1e-9)
    assert result.leverage == expected_leverage


def test_account_risk_scaler_keeps_close_portion_exact():
    engine = FundFlowRiskEngine(_account_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=4,
    )

    result = engine.validate_decision(decision)

    assert result.target_portion_of_balance == pytest.approx(0.35, rel=1e-9)
    assert result.leverage == 4
    assert result.metadata is None


def test_account_risk_scaler_rejects_scaled_portion_above_max_open_portion():
    cfg = _account_risk_cfg()
    cfg["fund_flow"]["max_open_portion"] = 0.4
    cfg["fund_flow"]["account_risk"]["exposure_scaler_value"] = 1.20
    engine = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=3,
    )

    with pytest.raises(ValueError, match="account_risk scaled target_portion_of_balance"):
        engine.validate_decision(decision)


def test_account_risk_scaler_allows_default_min_open_portion_after_scaling():
    cfg = _account_risk_cfg()
    cfg["fund_flow"]["min_open_portion"] = 0.06
    engine = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.065,
        leverage=3,
    )

    result = engine.validate_decision(decision)

    assert result.target_portion_of_balance == pytest.approx(0.05525, rel=1e-9)
    assert result.metadata["account_risk_scaler_applied"] is True


def test_account_risk_scaler_is_idempotent_when_metadata_output_disabled():
    cfg = _account_risk_cfg()
    cfg["fund_flow"]["account_risk"]["metadata_enabled"] = False
    engine = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=3,
    )

    first = engine.validate_decision(decision)
    second = engine.validate_decision(first)

    assert first.target_portion_of_balance == pytest.approx(0.2975, rel=1e-9)
    assert second.target_portion_of_balance == pytest.approx(0.2975, rel=1e-9)
    assert first.leverage == 2
    assert second.leverage == 2
    assert second.metadata is not None
    assert second.metadata["account_risk_scaler_applied"] is True


def test_account_risk_scaler_records_metadata_values():
    engine = FundFlowRiskEngine(_account_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=3,
        metadata={"existing": "kept"},
    )

    result = engine.validate_decision(decision)

    assert result.metadata["existing"] == "kept"
    assert result.metadata["account_risk_scaler_applied"] is True
    assert result.metadata["original_target_portion_of_balance"] == pytest.approx(0.35, rel=1e-9)
    assert result.metadata["scaled_target_portion_of_balance"] == pytest.approx(0.2975, rel=1e-9)
    assert result.metadata["original_leverage"] == 3
    assert result.metadata["scaled_leverage"] == 2
    assert result.metadata["exposure_scaler_value"] == pytest.approx(0.85, rel=1e-9)
    assert result.metadata["leverage_scaler_value"] == pytest.approx(0.85, rel=1e-9)
    assert result.metadata["leverage_rounding"] == "floor"
