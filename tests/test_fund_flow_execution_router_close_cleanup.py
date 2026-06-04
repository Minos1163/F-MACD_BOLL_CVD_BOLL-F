from __future__ import annotations

import sys
from typing import Any, Dict, List
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.attribution_engine import FundFlowAttributionEngine
from src.fund_flow.execution_router import FundFlowExecutionRouter
from src.fund_flow.models import FundFlowDecision, Operation
from src.fund_flow.risk_engine import FundFlowRiskEngine


class _Broker:
    def get_hedge_mode(self) -> bool:
        return True


class _PositionGateway:
    def __init__(self, applied_leverage: int) -> None:
        self.applied_leverage = applied_leverage
        self.requests: List[Dict[str, Any]] = []

    def change_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        self.requests.append({"symbol": symbol, "leverage": leverage})
        return {"leverage": str(self.applied_leverage)}


class _Client:
    def __init__(
        self,
        position_amt: float,
        close_order: Dict[str, Any] | None = None,
        retry_position_amt: float | None = None,
        all_positions: List[Dict[str, Any]] | None = None,
        order_book: Dict[str, Any] | None = None,
        applied_leverage: int | None = None,
    ) -> None:
        self.broker = _Broker()
        if applied_leverage is not None:
            self.position_gateway = _PositionGateway(applied_leverage)
        self.position_amt = position_amt
        self.retry_position_amt = retry_position_amt
        self.all_positions = list(all_positions or [])
        self.close_order = close_order or {"status": "FILLED", "executedQty": str(abs(position_amt)), "origQty": str(abs(position_amt))}
        self.order_book = order_book or {"bids": [["9.99", "100"]], "asks": [["10.01", "100"]]}
        self.conditional_cancelled: List[str] = []
        self.open_cancelled: List[str] = []
        self.orders: List[Dict[str, Any]] = []

    def get_position(self, symbol: str, side: str | None = None) -> Dict[str, Any]:
        if self.retry_position_amt is not None and len(self.orders) >= 1:
            amt = self.retry_position_amt
        else:
            amt = self.position_amt
        return {
            "symbol": symbol,
            "positionSide": side or "LONG",
            "positionAmt": str(amt),
        }

    def get_all_positions(self) -> List[Dict[str, Any]]:
        return list(self.all_positions)

    def format_quantity(self, symbol: str, quantity: float) -> str:
        return f"{float(quantity):.6f}"

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        return {"tick_size": 0.01, "price_precision": 2}

    def get_order_book(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        return self.order_book

    def format_price(self, symbol: str, price: float) -> str:
        return f"{float(price):.2f}"

    def _execute_order_v2(self, params: Dict[str, Any], side: str, reduce_only: bool = False) -> Dict[str, Any]:
        self.orders.append({"params": dict(params), "side": side, "reduce_only": reduce_only})
        if len(self.orders) == 1 and self.close_order.get("raise_first"):
            raise Exception("Binance Error: {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}")
        if len(self.orders) == 1:
            return dict(self.close_order)
        return {"status": "FILLED", "executedQty": str(abs(self.retry_position_amt or self.position_amt)), "origQty": str(abs(self.retry_position_amt or self.position_amt))}

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


def _entry_router(client: _Client) -> FundFlowExecutionRouter:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_open_notional": {
                    "default_usdt": 0.1,
                    "btc_usdt": 5.0,
                    "major_symbols": ["BTCUSDT"],
                },
                "min_entry_margin_usdt": 1.0,
                "max_open_portion": 1.0,
                "execution_degradation": {
                    "open_ioc_retry_times": 0,
                    "open_gtc_fallback_enabled": False,
                    "open_market_fallback_enabled": False,
                },
                "position_count_limit_by_margin": {
                    "enabled": True,
                    "small_margin_threshold_usdt": 5.0,
                    "max_small_margin_positions": 5,
                    "max_large_margin_positions": 4,
                    "small_margin_leverage": 9,
                },
                "max_leverage": 9,
            }
        },
        symbol_whitelist=["ATOMUSDT"],
    )
    return FundFlowExecutionRouter(client, risk, _Attribution(), close_retry_times=1)


def _entry_router_without_margin_floor(client: _Client) -> FundFlowExecutionRouter:
    risk = FundFlowRiskEngine(
        {
            "fund_flow": {
                "min_open_notional": {"default_usdt": 0.0},
                "min_entry_margin_usdt": 0.0,
                "max_open_portion": 1.0,
                "execution_degradation": {
                    "open_ioc_retry_times": 0,
                    "open_gtc_fallback_enabled": False,
                    "open_market_fallback_enabled": False,
                },
                "position_count_limit_by_margin": {"enabled": False},
                "max_leverage": 9,
            }
        },
        symbol_whitelist=["ATOMUSDT"],
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


def test_exit_guard_full_close_retries_reduce_only_reject_with_live_close_position() -> None:
    client = _Client(
        position_amt=311.0,
        retry_position_amt=120.0,
        close_order={
            "status": "error",
            "message": "place_market_order exception: Binance Error: {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}",
        },
    )
    router = _router(client)
    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.CLOSE,
            symbol="TESTUSDT",
            target_portion_of_balance=1.0,
            min_price=99.0,
            reason="EXIT_SIGNAL_GUARD_CLOSE: reverse",
        ),
        account_state={"available_balance": 1000},
        current_price=100.0,
        position={"side": "LONG", "amount": 311.0},
    )

    assert result["status"] == "success"
    assert result["fallback"] == "exit_guard_close_position_retry"
    assert len(client.orders) == 2
    retry_order = client.orders[-1]
    assert retry_order["params"]["closePosition"] is True
    assert retry_order["params"]["positionSide"] == "LONG"
    assert "quantity" in retry_order["params"]
    assert retry_order["reduce_only"] is False


def test_entry_router_allows_atom_probe_below_legacy_six_percent_floor() -> None:
    client = _Client(position_amt=0.0)
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.042,
            leverage=4,
            max_price=10.0,
            metadata={"signal_score": 0.7292},
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] != "error" or "decision 校验失败" not in result["message"]
    assert client.orders


def test_entry_router_sizes_new_entries_from_equity_not_available_balance() -> None:
    client = _Client(position_amt=0.0)
    router = _entry_router_without_margin_floor(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.042,
            leverage=3,
            max_price=10.0,
        ),
        account_state={"equity": 100.0, "available_balance": 0.01},
        current_price=10.0,
        position=None,
    )

    assert result["status"] == "noop"
    assert result["message"] == "可用余额不足以执行目标仓位，跳过开仓"
    assert result["target_margin_usdt"] == pytest.approx(4.2)
    assert result["available_balance"] == pytest.approx(0.01)
    assert not client.orders


def _position(symbol: str, margin: float, leverage: int = 2, side: str = "LONG") -> Dict[str, Any]:
    entry_price = 10.0
    amount = margin * leverage / entry_price
    if side == "SHORT":
        amount = -amount
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(amount),
        "entryPrice": str(entry_price),
        "markPrice": str(entry_price),
        "leverage": str(leverage),
    }


def test_entry_router_blocks_sixth_small_margin_position() -> None:
    client = _Client(
        position_amt=0.0,
        all_positions=[_position(f"S{i}USDT", 4.99) for i in range(5)],
    )
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.04,
            leverage=2,
            max_price=10.0,
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] == "noop"
    assert result["message"] == "持仓数量限制，跳过开仓"
    assert result["position_count_limit"]["bucket"] == "small"
    assert result["position_count_limit"]["current_count"] == 5
    assert not client.orders


def test_entry_router_blocks_fifth_large_margin_position() -> None:
    client = _Client(
        position_amt=0.0,
        all_positions=[_position(f"L{i}USDT", 5.0) for i in range(4)],
    )
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.SELL,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.05,
            leverage=2,
            min_price=10.0,
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] == "noop"
    assert result["message"] == "持仓数量限制，跳过开仓"
    assert result["position_count_limit"]["bucket"] == "large"
    assert result["position_count_limit"]["current_count"] == 4
    assert not client.orders


def test_entry_router_allows_large_position_when_small_bucket_is_full() -> None:
    client = _Client(
        position_amt=0.0,
        all_positions=[_position(f"S{i}USDT", 4.99) for i in range(5)],
    )
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.06,
            leverage=2,
            max_price=10.0,
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] != "noop"
    assert client.orders


def test_entry_router_uses_nine_x_leverage_for_small_margin_entry() -> None:
    client = _Client(position_amt=0.0)
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.SELL,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.04,
            leverage=4,
            min_price=10.0,
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    margin = 111.18 * 0.04
    assert margin < 5.0
    assert result["status"] != "error"
    assert result["leverage"] == 9
    assert result["margin"] == pytest.approx(margin)
    assert result["position_value"] == pytest.approx(margin * 9)
    assert client.orders[-1]["params"]["quantity"] == pytest.approx(round((margin * 9) / 10.0, 10))
    assert result["small_margin_leverage_override"]["original_leverage"] == 4


def test_entry_router_preserves_requested_leverage_for_quadrant_small_margin_entry() -> None:
    client = _Client(position_amt=0.0)
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.SELL,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.04,
            leverage=3,
            min_price=10.0,
            metadata={
                "strategy_mode": "quadrant_resonance",
                "stage": "final",
                "signal_score": 0.90,
                "signal_score_threshold": 0.85,
            },
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    margin = 111.18 * 0.04
    assert margin < 5.0
    assert result["status"] != "error"
    assert result["leverage"] == 3
    assert result["margin"] == pytest.approx(margin)
    assert result["position_value"] == pytest.approx(margin * 3)
    assert result["small_margin_leverage_override"] is None


def test_entry_router_blocks_when_exchange_applies_different_leverage() -> None:
    client = _Client(position_amt=0.0, applied_leverage=9)
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.04,
            leverage=3,
            max_price=10.0,
            metadata={"strategy_mode": "quadrant_resonance"},
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] == "error"
    assert result["message"] == "交易所杠杆与策略请求不一致，已阻止开仓"
    assert result["leverage_sync"]["requested"] == 3
    assert result["leverage_sync"]["applied"] == 9
    assert not client.orders


def test_entry_router_uses_orderbook_touch_price_for_ioc_buy() -> None:
    client = _Client(
        position_amt=0.0,
        order_book={"bids": [["10.00", "100"]], "asks": [["10.10", "100"]]},
    )
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.04,
            leverage=3,
            max_price=10.0,
            metadata={
                "entry_use_orderbook_touch_price": True,
                "entry_orderbook_touch_offset_bps": 15,
            },
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] != "error"
    assert client.orders[-1]["params"]["price"] == pytest.approx(10.12)
    assert result["entry_orderbook_price_context"]["entry_original_limit_price"] == pytest.approx(10.0)
    assert result["entry_orderbook_price_context"]["entry_touch_best_ask"] == pytest.approx(10.10)
    assert result["entry_orderbook_price_context"]["entry_formatted_touch_price"] == pytest.approx(10.12)


def test_entry_router_blocks_entry_margin_below_one_usdt_before_leverage_override() -> None:
    client = _Client(position_amt=0.0)
    router = _entry_router(client)

    result = router.execute_decision(
        FundFlowDecision(
            operation=Operation.BUY,
            symbol="ATOMUSDT",
            target_portion_of_balance=0.008,
            leverage=4,
            max_price=10.0,
        ),
        account_state={"equity": 111.18, "available_balance": 111.18},
        current_price=10.0,
        position=None,
    )

    assert result["status"] == "noop"
    assert result["message"] == "开仓保证金低于最小阈值，跳过开仓"
    assert result["micro_margin_gate"]["reason"] == "micro_margin_block"
    assert result["micro_margin_gate"]["estimated_margin_usdt"] == pytest.approx(0.88944)
    assert not client.orders
