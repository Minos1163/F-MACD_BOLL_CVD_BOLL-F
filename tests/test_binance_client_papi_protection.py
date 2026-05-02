from types import SimpleNamespace

from src.api.binance_client import BinanceClient
from src.trading.intents import PositionSide


def test_execute_protection_accepts_papi_algo_id_as_success(monkeypatch):
    client = BinanceClient.__new__(BinanceClient)
    client.broker = SimpleNamespace(dry_run=False, is_papi_only=lambda: True, um_base=lambda: "https://papi.binance.com")
    client.get_position = lambda symbol, side=None: {"positionAmt": "10.5", "entryPrice": "1.33"}
    client._cancel_existing_protection_orders = lambda **kwargs: {"status": "success", "checked": 0}

    class _Manager:
        def __init__(self, broker):
            pass

        def place_tp_sl(self, cfg):
            return [{"algoId": 12345, "algoStatus": "NEW", "algoType": "CONDITIONAL", "type": "STOP_MARKET"}]

    monkeypatch.setattr("src.api.binance_client.PapiTpSlManager", _Manager)

    result = client._execute_protection_v2(
        symbol="TONUSDT",
        side=PositionSide.LONG,
        tp=None,
        sl=1.319,
        quantity=10.5,
    )

    assert result["status"] == "success"
    assert result["ok_count"] == 1
    assert result["orders"][0]["algoId"] == 12345
