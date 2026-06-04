import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.execution_router import FundFlowExecutionRouter


def test_marketable_ioc_buy_price_crosses_best_ask_with_offset() -> None:
    router = object.__new__(FundFlowExecutionRouter)

    adjusted = router._marketable_ioc_entry_price(
        side="BUY",
        current_order_price=0.5237,
        best_bid=0.5240,
        best_ask=0.5246,
        offset_bps=15,
    )

    assert adjusted == 0.5246 * 1.0015


def test_marketable_ioc_sell_price_crosses_best_bid_with_offset() -> None:
    router = object.__new__(FundFlowExecutionRouter)

    adjusted = router._marketable_ioc_entry_price(
        side="SELL",
        current_order_price=1.2160,
        best_bid=1.2150,
        best_ask=1.2162,
        offset_bps=15,
    )

    assert adjusted == 1.2150 * 0.9985


def test_marketable_ioc_price_keeps_existing_more_aggressive_buy_price() -> None:
    router = object.__new__(FundFlowExecutionRouter)

    adjusted = router._marketable_ioc_entry_price(
        side="BUY",
        current_order_price=0.5300,
        best_bid=0.5240,
        best_ask=0.5246,
        offset_bps=15,
    )

    assert adjusted == 0.5300
