import math
from pathlib import Path

import pytest

from src.fund_flow.attribution_engine import FundFlowAttributionEngine
from src.fund_flow.execution_router import FundFlowExecutionRouter
from src.fund_flow.models import FundFlowDecision, Operation, TimeInForce
from src.fund_flow.risk_engine import FundFlowRiskEngine


class _DummyBroker:
    @staticmethod
    def get_hedge_mode():
        return True


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.protection_calls = []
        self.cancel_calls = []
        self.leverage_calls = []
        self.broker = _DummyBroker()
        self.position_gateway = self

    def format_quantity(self, _symbol, qty):
        return round(float(qty), 6)

    def change_leverage(self, symbol, leverage):
        self.leverage_calls.append({"symbol": symbol, "leverage": int(leverage)})
        return {"leverage": int(leverage)}

    def _execute_order_v2(self, params, side, reduce_only):
        self.calls.append({"params": dict(params), "side": side, "reduce_only": reduce_only})
        if not self.responses:
            return {"status": "error", "message": "no fake response"}
        return self.responses.pop(0)

    def _execute_protection_v2(self, symbol, side, tp, sl):
        self.protection_calls.append({"symbol": symbol, "side": side.value, "tp": tp, "sl": sl})
        return {"status": "success", "orders": []}

    def cancel_all_open_orders(self, symbol):
        self.cancel_calls.append(symbol)
        return {"status": "success"}


class _FloorQtyClient(_FakeClient):
    def format_quantity(self, _symbol, qty):
        step = 0.001
        val = math.floor(float(qty) / step) * step
        return round(val, 3)


def _risk_cfg():
    return {
        "trading": {"default_leverage": 2, "max_leverage": 5},
        "fund_flow": {"min_open_portion": 0.1, "max_open_portion": 1.0},
    }


def _account_risk_cfg():
    cfg = _risk_cfg()
    cfg["fund_flow"].update(
        {
            "min_leverage": 1,
            "default_leverage": 3,
            "max_leverage": 4,
            "account_risk": {
                "enabled": True,
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


def test_open_ioc_fallback_to_gtc(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"orderId": 123, "status": "NEW"},
        ]
    )
    risk = FundFlowRiskEngine(_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "pending"
    assert len(client.calls) == 2
    assert client.calls[0]["params"]["timeInForce"] == "IOC"
    assert client.calls[1]["params"]["timeInForce"] == "GTC"
    assert len(client.protection_calls) == 0


def test_close_ioc_retry_then_success(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "NEW", "executedQty": "0"},
            {"status": "NEW", "executedQty": "0"},
            {"status": "FILLED", "executedQty": "1", "orderId": 888},
        ]
    )
    risk = FundFlowRiskEngine(_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr, close_retry_times=4)

    decision = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="BTCUSDT",
        target_portion_of_balance=1.0,
        leverage=2,
        min_price=99.0,
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position={"side": "LONG", "amount": 1.0},
    )

    assert result["status"] == "success"
    assert result["retry_index"] == 2
    assert len(client.calls) == 3
    assert client.calls[0]["reduce_only"] is True


def test_close_partial_qty_rounded_to_zero_promotes_to_full_close(tmp_path: Path):
    client = _FloorQtyClient(
        responses=[
            {"status": "FILLED", "executedQty": "0.002", "orderId": 777},
        ]
    )
    risk = FundFlowRiskEngine(_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr, close_retry_times=2)

    decision = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="BTCUSDT",
        target_portion_of_balance=0.25,
        leverage=2,
        min_price=99.0,
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position={"side": "LONG", "amount": 0.002},
    )

    assert result["status"] == "success"
    assert result["quantity"] == 0.002
    assert result["quantity_info"]["promoted_to_full_close"] is True
    assert result["quantity_info"]["promotion_reason"] == "partial_qty_rounded_to_zero"
    assert len(client.calls) == 1
    assert client.calls[0]["params"]["quantity"] == 0.002


def test_open_respects_entry_tif_override_gtc(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"orderId": 321, "status": "NEW"},
        ]
    )
    risk = FundFlowRiskEngine(_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={"entry_tif_override": "GTC"},
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "pending"
    assert len(client.calls) == 1
    assert client.calls[0]["params"]["timeInForce"] == "GTC"


def test_open_execution_uses_account_risk_scaled_portion_and_leverage(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "FILLED", "executedQty": "8.925", "orderId": 456},
        ]
    )
    risk = FundFlowRiskEngine(_account_risk_cfg(), symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=3,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
    )
    risk.validate_decision(decision)
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1500.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "success"
    assert result["margin"] == pytest.approx(446.25, rel=1e-9)
    assert result["position_value"] == pytest.approx(892.5, rel=1e-9)
    assert result["quantity"] == pytest.approx(8.925, rel=1e-9)
    assert result["leverage"] == 2
    assert client.leverage_calls == [{"symbol": "BTCUSDT", "leverage": 2}]


def test_open_market_fallback_requires_double_gate_and_skips_gtc_for_ioc_policy(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "FILLED", "executedQty": "4", "orderId": 999},
        ]
    )
    cfg = _risk_cfg()
    cfg["fund_flow"]["execution_degradation"] = {
        "open_gtc_fallback_enabled": True,
        "open_market_fallback_enabled": True,
    }
    risk = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={
            "entry_execution_policy": "ioc_market_fallback",
            "entry_market_fallback_enabled": True,
            "entry_market_fallback_max_slippage_bps": 5,
            "entry_reference_price": 100.0,
        },
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "success"
    assert [call["params"]["type"] for call in client.calls] == ["LIMIT", "MARKET"]
    assert client.calls[0]["params"]["timeInForce"] == "IOC"


def test_open_market_fallback_respects_disable_flag(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
        ]
    )
    cfg = _risk_cfg()
    cfg["fund_flow"]["execution_degradation"] = {
        "open_gtc_fallback_enabled": True,
        "open_market_fallback_enabled": True,
    }
    risk = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={
            "entry_execution_policy": "ioc_market_fallback",
            "entry_market_fallback_enabled": True,
            "entry_market_fallback_max_slippage_bps": 5,
            "entry_reference_price": 100.0,
            "disable_market_fallback": True,
        },
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "error"
    assert [call["params"]["type"] for call in client.calls] == ["LIMIT"]


def test_force_market_fallback_on_ioc_remainder_uses_market_without_metadata_double_gate(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "FILLED", "executedQty": "4", "orderId": 999},
        ]
    )
    cfg = _risk_cfg()
    cfg["fund_flow"]["execution_degradation"] = {
        "open_ioc_retry_times": 2,
        "open_ioc_retry_step_bps": 15,
        "open_gtc_fallback_enabled": True,
        "open_market_fallback_enabled": True,
        "open_market_fallback_max_slippage_bps": 8,
        "force_market_fallback_on_ioc_remainder": True,
    }
    risk = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={
            "entry_execution_policy": "ioc",
            "entry_reference_price": 100.0,
        },
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "success"
    assert [call["params"]["type"] for call in client.calls] == ["LIMIT", "LIMIT", "MARKET"]
    assert result["order"]["degradation_path"][-1]["step"] == "market_fallback"
    assert result["order"]["degradation_path"][-1]["forced"] is True


def test_force_market_fallback_on_ioc_remainder_still_respects_disable_flag(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
        ]
    )
    cfg = _risk_cfg()
    cfg["fund_flow"]["execution_degradation"] = {
        "open_ioc_retry_times": 2,
        "open_gtc_fallback_enabled": False,
        "open_market_fallback_enabled": True,
        "force_market_fallback_on_ioc_remainder": True,
    }
    risk = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={
            "entry_execution_policy": "ioc",
            "disable_market_fallback": True,
        },
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "error"
    assert [call["params"]["type"] for call in client.calls] == ["LIMIT", "LIMIT"]


def test_open_ioc_dynamic_retry_caps_total_slippage_and_records_path(tmp_path: Path):
    client = _FakeClient(
        responses=[
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
            {"status": "error", "code": -2010, "msg": "Order would immediately match and take"},
        ]
    )
    cfg = _risk_cfg()
    cfg["fund_flow"]["execution_degradation"] = {
        "open_ioc_retry_times": 6,
        "open_ioc_retry_step_bps": 15,
        "open_ioc_dynamic_step_enabled": True,
        "open_ioc_max_total_slippage_bps": 60,
        "open_gtc_fallback_enabled": False,
        "open_market_fallback_enabled": False,
    }
    risk = FundFlowRiskEngine(cfg, symbol_whitelist=["BTCUSDT"])
    attr = FundFlowAttributionEngine(str(tmp_path))
    router = FundFlowExecutionRouter(client, risk, attr)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.2,
        leverage=2,
        max_price=100.0,
        take_profit_price=110.0,
        stop_loss_price=95.0,
        time_in_force=TimeInForce.IOC,
        metadata={
            "signal_score": 0.95,
            "competition_score": 0.95,
        },
    )
    result = router.execute_decision(
        decision=decision,
        account_state={"available_balance": 1000.0},
        current_price=100.0,
        position=None,
    )

    assert result["status"] == "error"
    assert len(client.calls) == 3
    path = result["order"]["degradation_path"]
    retry_steps = [step for step in path if step.get("step") == "limit_ioc_retry"]
    assert len(retry_steps) == 2
    assert retry_steps[0]["step_bps"] == 30.0
    assert retry_steps[-1]["total_slippage_bps"] <= 60
