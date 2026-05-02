from types import SimpleNamespace

from src.trading.tp_sl import PapiTpSlManager, TpSlConfig


class _FakeBroker:
    def __init__(self):
        self.position = SimpleNamespace(get_position=lambda symbol, side=None: {"positionAmt": 10})

    def calculate_position_side(self, order_side, reduce_only):
        return "LONG"

    def format_quantity(self, symbol, qty):
        return qty


class _FakeResponse:
    status_code = 200
    text = "{}"

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_build_tp_orders_supports_ladder_reduce():
    manager = PapiTpSlManager(_FakeBroker())
    cfg = TpSlConfig(
        symbol="BTCUSDT",
        position_side="LONG",
        entry_price=100.0,
        quantity=10.0,
        take_profit_levels=[(100.6, 0.5), (101.0, 0.5)],
    )

    orders = manager._build_tp_orders(cfg, manager._resolve_take_profit_levels(cfg, None))

    assert len(orders) == 2
    assert orders[0]["quantity"] == 5.0
    assert orders[1]["quantity"] == 5.0
    assert "closePosition" not in orders[0]
    assert "closePosition" not in orders[1]


def test_papi_tp_sl_uses_algo_order_endpoint_and_payload_shape():
    calls = []

    class _Broker(_FakeBroker):
        PAPI_BASE = "https://papi.binance.com"

        def request(self, method, url, params=None, signed=False, allow_error=False):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "params": dict(params or {}),
                    "signed": signed,
                    "allow_error": allow_error,
                }
            )
            return _FakeResponse({"algoId": 12345, "algoStatus": "NEW", "algoType": "CONDITIONAL"})

    manager = PapiTpSlManager(_Broker())
    cfg = TpSlConfig(
        symbol="TONUSDT",
        position_side="LONG",
        entry_price=1.33,
        quantity=10.5,
        stop_loss_price=1.319,
    )

    results = manager.place_tp_sl(cfg)

    assert results == [{"algoId": 12345, "algoStatus": "NEW", "algoType": "CONDITIONAL"}]
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/papi/v1/um/algo/order")
    assert calls[0]["signed"] is True
    assert calls[0]["allow_error"] is True
    assert calls[0]["params"]["algoType"] == "CONDITIONAL"
    assert calls[0]["params"]["type"] == "STOP_MARKET"
    assert calls[0]["params"]["triggerPrice"] == 1.319
    assert "strategyType" not in calls[0]["params"]
    assert "stopPrice" not in calls[0]["params"]
