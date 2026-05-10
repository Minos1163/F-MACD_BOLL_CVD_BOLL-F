from __future__ import annotations

import sys
from typing import Any, Dict, List
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.attribution_engine import FundFlowAttributionEngine
from src.fund_flow.execution_router import FundFlowExecutionRouter
from src.fund_flow.models import FundFlowDecision, Operation
from src.fund_flow.risk_engine import FundFlowRiskEngine


class _Broker:
    def get_hedge_mode(self) -> bool:
        return True


class _Client:
    def __init__(self, position_amt: float, close_order: Dict[str, Any] | None = None) -> None:
        self.broker = _Broker()
        self.position_amt = position_amt
        self.close_order = close_order or {"status": "FILLED", "executedQty": str(abs(position_amt)), "origQty": str(abs(position_amt))}
        self.conditional_cancelled: List[str] = []
        self.open_cancelled: List[str] = []
        self.orders: List[Dict[str, Any]] = []

    def get_position(self, symbol: str, side: str | None = None) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "positionSide": side or "LONG",
            "positionAmt": str(self.position_amt),
        }

    def get_all_positions(self) -> List[Dict[str, Any]]:
        return []

    def format_quantity(self, symbol: str, quantity: float) -> str:
        return f"{float(quantity):.6f}"

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        return {"tick_size": 0.01, "price_precision": 2}

    def format_price(self, symbol: str, price: float) -> str:
        return f"{float(price):.2f}"

    def _execute_order_v2(self, params: Dict[str, Any], side: str, reduce_only: bool = False) -> Dict[str, Any]:
        self.orders.append({"params": dict(params), "side": side, "reduce_only": reduce_only})
        return dict(self.close_order)

    def cancel_all_conditional_orders(self, symbol: str) -> Dict[str, Any]:
        self.conditional_cancelled.append(symbol)
        return {"status": "success", "symbol": symbol}

    def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        self.open_cancelled.append(symbol)
        return {"status": "success", "symbol": symbol}


class _Attribution(FundFlowAttributionEngine):
    def __init__(self) -> None:
        self.executions: List[Dict[str, Any]] = []

    def log_execution(self, decision: FundFlowDecision, result: Dict[str, Any]) -> None:
        self.executions.append(result)


def _router(client: _Client) -> FundFlowExecutionRouter:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "execution_degradation": {
                    "close_ioc_retry_times": 1,
                    "close_gtc_fallback_enabled": False,
                    "close_market_fallback_enabled": False,
                }
            }
        },
        symbol_whitelist=["TESTUSDT"],
    )
    return FundFlowExecutionRouter(client, risk, _Attribution(), close_retry_times=1)


def _close_decision() -> FundFlowDecision:
    return FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="TESTUSDT",
        target_portion_of_balance=1.0,
        min_price=99.0,
    )


def test_close_noop_when_live_position_is_zero_still_cleans_symbol_orders() -> None:
    client = _Client(position_amt=0.0)
    result = _router(client).execute_decision(
        _close_decision(),
        account_state={"available_balance": 1000},
        current_price=100.0,
        position={"side": "LONG", "amount": 1.0},
    )

    assert result["status"] == "noop"
    assert client.conditional_cancelled == ["TESTUSDT"]
    assert client.open_cancelled == ["TESTUSDT"]
    assert result["cancel_conditional_orders"] == "ok"
    assert result["cancel_open_orders"] == "ok"


def test_full_close_completion_cleans_conditional_and_open_orders() -> None:
    client = _Client(position_amt=1.0)
    result = _router(client).execute_decision(
        _close_decision(),
        account_state={"available_balance": 1000},
        current_price=100.0,
        position={"side": "LONG", "amount": 1.0},
    )

    assert result["status"] == "success"
    assert result["full_close_completed"] is True
    assert client.conditional_cancelled == ["TESTUSDT"]
    assert client.open_cancelled == ["TESTUSDT"]
    assert result["cancel_conditional_orders"] == "ok"
    assert result["cancel_open_orders"] == "ok"
