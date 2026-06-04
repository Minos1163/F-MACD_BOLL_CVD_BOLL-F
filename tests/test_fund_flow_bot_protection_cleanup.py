from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.fund_flow_bot import TradingBot
from src.fund_flow.models import FundFlowDecision, Operation
from src.trading.intents import PositionSide


class _Broker:
    def get_hedge_mode(self) -> bool:
        return True


class _PositionData:
    def __init__(self, position: Dict[str, Any] | None) -> None:
        self.position = position

    def get_current_position(self, symbol: str) -> Dict[str, Any] | None:
        return self.position


class _Client:
    def __init__(self, positions: List[Dict[str, Any]], conditional_orders: List[Dict[str, Any]]) -> None:
        self.broker = _Broker()
        self.positions = positions
        self.conditional_orders = conditional_orders
        self.cancel_existing_calls: List[Dict[str, Any]] = []

    def get_all_positions(self) -> List[Dict[str, Any]]:
        return self.positions

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return []

    def get_open_conditional_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self.conditional_orders

    def _cancel_existing_protection_orders(
        self,
        *,
        symbol: str,
        side: PositionSide,
        cancel_tp: bool,
        cancel_sl: bool,
    ) -> Dict[str, Any]:
        self.cancel_existing_calls.append(
            {
                "symbol": symbol,
                "side": side,
                "cancel_tp": cancel_tp,
                "cancel_sl": cancel_sl,
            }
        )
        return {"status": "success", "checked": 2, "cancelled": 2, "failed": 0}


def _bot(client: _Client, position: Dict[str, Any] | None) -> TradingBot:
    bot = TradingBot.__new__(TradingBot)
    bot.config = {"fund_flow": {"stale_protection_cleanup_enabled": True, "stale_protection_cleanup_delay_seconds": 0}}
    bot.client = client
    bot.position_data = _PositionData(position)
    bot._opened_symbols_this_cycle = set()
    bot._has_pending_entry_order = lambda symbol: False
    return bot


def test_stale_cleanup_cancels_opposite_side_protection_when_single_position_side() -> None:
    client = _Client(
        positions=[
            {
                "symbol": "TESTUSDT",
                "positionSide": "LONG",
                "positionAmt": "1.0",
                "entryPrice": "100",
                "markPrice": "101",
                "leverage": "1",
            }
        ],
        conditional_orders=[
            {"orderId": 11, "type": "STOP_MARKET", "side": "SELL", "positionSide": "LONG", "status": "NEW"},
            {"orderId": 12, "type": "TAKE_PROFIT_MARKET", "side": "SELL", "positionSide": "LONG", "status": "NEW"},
            {"orderId": 21, "type": "STOP_MARKET", "side": "BUY", "positionSide": "SHORT", "status": "NEW"},
            {"orderId": 22, "type": "TAKE_PROFIT_MARKET", "side": "BUY", "positionSide": "SHORT", "status": "NEW"},
        ],
    )
    bot = _bot(client, {"side": "LONG", "amount": 1.0})

    bot._cleanup_stale_protection_orders(["TESTUSDT"])

    assert client.cancel_existing_calls == [
        {
            "symbol": "TESTUSDT",
            "side": PositionSide.SHORT,
            "cancel_tp": True,
            "cancel_sl": True,
        }
    ]


def test_stale_cleanup_does_not_cancel_opposite_side_when_both_legs_exist() -> None:
    client = _Client(
        positions=[
            {
                "symbol": "TESTUSDT",
                "positionSide": "LONG",
                "positionAmt": "1.0",
                "entryPrice": "100",
                "markPrice": "101",
                "leverage": "1",
            },
            {
                "symbol": "TESTUSDT",
                "positionSide": "SHORT",
                "positionAmt": "-1.0",
                "entryPrice": "102",
                "markPrice": "101",
                "leverage": "1",
            },
        ],
        conditional_orders=[
            {"orderId": 21, "type": "STOP_MARKET", "side": "BUY", "positionSide": "SHORT", "status": "NEW"},
        ],
    )
    bot = _bot(client, {"side": "LONG", "amount": 1.0})

    bot._cleanup_stale_protection_orders(["TESTUSDT"])

    assert client.cancel_existing_calls == []


def test_pending_entry_with_visible_fills_repairs_protection_immediately() -> None:
    bot = TradingBot.__new__(TradingBot)
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = {"side": "LONG", "amount": 0.5, "entry_price": 62.46}
    bot._fetch_order_trade_fills = Mock(return_value=[{"orderId": 8172959957, "qty": "0.5", "price": "62.4637"}])
    bot._protection_coverage = Mock(side_effect=[
        {"has_tp": False, "has_sl": False},
        {"has_tp": True, "has_sl": True},
    ])
    bot._protection_is_covered = Mock(side_effect=[False, True])
    bot._repair_missing_protection = Mock(return_value={"status": "success", "orders": [{"type": "STOP_MARKET", "orderId": 1}]})
    bot._repair_result_satisfies_protection_requirements = Mock(return_value=True)

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="HYPEUSDT",
        target_portion_of_balance=0.042,
        leverage=9,
        reason="quadrant_resonance_probe_no_15m",
    )
    result = bot._post_execution_protection_hook(
        symbol="HYPEUSDT",
        decision=decision,
        execution_result={
            "status": "pending",
            "order": {"orderId": 8172959957, "status": "NEW", "executedQty": "0.00"},
            "protection": {"status": "pending", "message": "entry not filled yet"},
        },
    )

    assert result["status"] == "repaired"
    assert result["message"] == "protection_repaired"
    bot._repair_missing_protection.assert_called_once()
