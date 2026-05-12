from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.fund_flow_bot import TradingBot
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
