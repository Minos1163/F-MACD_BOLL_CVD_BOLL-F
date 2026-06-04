import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trading.order_gateway import OrderGateway


class _Resp:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class _Broker:
    FAPI_BASE = "https://fapi.binance.com"
    PAPI_BASE = "https://papi.binance.com"

    def __init__(self, base: str):
        self._base = base
        self.calls = []

    def um_base(self) -> str:
        return self._base

    def is_papi_only(self) -> bool:
        return "papi" in self._base

    def request(self, method: str, url: str, params=None, signed=False, **kwargs):
        self.calls.append((method, url, params or {}, signed))
        return _Resp({"symbol": params["symbol"], "orderId": params["orderId"], "status": "EXPIRED"})


def test_query_order_uses_papi_um_order_endpoint_when_papi_base() -> None:
    broker = _Broker("https://papi.binance.com")
    gateway = OrderGateway(broker)

    result = gateway.query_order("WLDUSDT", 21904933202)

    assert result["status"] == "EXPIRED"
    assert broker.calls == [
        (
            "GET",
            "https://papi.binance.com/papi/v1/um/order",
            {"symbol": "WLDUSDT", "orderId": 21904933202},
            True,
        )
    ]


def test_query_order_uses_fapi_order_endpoint_when_fapi_base() -> None:
    broker = _Broker("https://fapi.binance.com")
    gateway = OrderGateway(broker)

    result = gateway.query_order("ICPUSDT", 7016851051)

    assert result["orderId"] == 7016851051
    assert broker.calls == [
        (
            "GET",
            "https://fapi.binance.com/fapi/v1/order",
            {"symbol": "ICPUSDT", "orderId": 7016851051},
            True,
        )
    ]
