from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.market_breadth import MarketBreadthConfig, MarketBreadthDetector


def test_slow_bull_requires_breadth_and_confirm_cycles() -> None:
    detector = MarketBreadthDetector(
        MarketBreadthConfig(confirm_cycles=2),
        ["ADAUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "FETUSDT"],
    )

    for _ in range(3):
        detector.update(
            btc_ret_15m=0.0015,
            alt_rets={
                "ADAUSDT": 0.002,
                "SOLUSDT": 0.001,
                "XRPUSDT": 0.001,
                "DOGEUSDT": -0.0005,
                "FETUSDT": 0.003,
            },
        )
        assert detector.detect()["is_slow_bull"] is False

    detector.update(
        btc_ret_15m=0.0015,
        alt_rets={
            "ADAUSDT": 0.002,
            "SOLUSDT": 0.001,
            "XRPUSDT": 0.001,
            "DOGEUSDT": -0.0005,
            "FETUSDT": 0.003,
        },
    )
    first = detector.detect()
    assert first["is_slow_bull"] is False
    assert first["confirm_count"] == 1

    detector.update(
        btc_ret_15m=0.0015,
        alt_rets={
            "ADAUSDT": 0.002,
            "SOLUSDT": 0.001,
            "XRPUSDT": 0.001,
            "DOGEUSDT": -0.0005,
            "FETUSDT": 0.003,
        },
    )
    second = detector.detect()
    assert second["is_slow_bull"] is True
    assert second["breadth_ratio"] >= 0.60


def test_slow_bull_invalidates_after_two_weak_cycles() -> None:
    detector = MarketBreadthDetector(
        MarketBreadthConfig(confirm_cycles=1, invalidate_cycles=2),
        ["ADAUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"],
    )
    for _ in range(4):
        detector.update(0.002, {"ADAUSDT": 0.002, "SOLUSDT": 0.002, "XRPUSDT": 0.002, "DOGEUSDT": 0.002})
    assert detector.detect()["is_slow_bull"] is True

    detector.update(-0.002, {"ADAUSDT": -0.002, "SOLUSDT": -0.002, "XRPUSDT": 0.001, "DOGEUSDT": -0.002})
    assert detector.detect()["is_slow_bull"] is True

    detector.update(-0.002, {"ADAUSDT": -0.002, "SOLUSDT": -0.002, "XRPUSDT": 0.001, "DOGEUSDT": -0.002})
    assert detector.detect()["is_slow_bull"] is True

    detector.update(-0.002, {"ADAUSDT": -0.002, "SOLUSDT": -0.002, "XRPUSDT": 0.001, "DOGEUSDT": -0.002})
    assert detector.detect()["is_slow_bull"] is False


def test_alt_breadth_led_slow_bull_enters_true_when_btc_is_flat() -> None:
    detector = MarketBreadthDetector(
        MarketBreadthConfig(confirm_cycles=2),
        ["ADAUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "FETUSDT"],
    )
    alt_rets = {
        "ADAUSDT": 0.0015,
        "SOLUSDT": 0.0015,
        "XRPUSDT": 0.0015,
        "DOGEUSDT": 0.0015,
        "FETUSDT": 0.0015,
    }

    for _ in range(4):
        detector.update(btc_ret_15m=-0.0002, alt_rets=alt_rets)

    first = detector.detect()
    assert first["is_slow_bull"] is False
    assert first["confirm_count"] == 1

    detector.update(btc_ret_15m=0.0, alt_rets=alt_rets)
    second = detector.detect()
    assert second["is_slow_bull"] is True
    assert second["mode"] in {"alt_breadth_led", "extreme_breadth"}
    assert second["breadth_ratio"] >= 0.80
