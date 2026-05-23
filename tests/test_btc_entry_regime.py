from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.btc_entry_regime import BtcEntryRegimeGate, BtcRegime


def test_detect_btc_regime_from_four_closed_15m_returns() -> None:
    gate = BtcEntryRegimeGate({})

    assert gate.detect_btc_regime([-0.0015, -0.0012, -0.0011, -0.0013]) == BtcRegime.FALLING
    assert gate.detect_btc_regime([0.0015, 0.0012, 0.0011, 0.0013]) == BtcRegime.RISING
    assert gate.detect_btc_regime([0.0002, -0.0001, 0.0001, -0.0002]) == BtcRegime.CHOPPY


def test_falling_btc_blocks_low_vwap_long() -> None:
    gate = BtcEntryRegimeGate({})

    result = gate.check_entry(
        direction="long",
        btc_regime=BtcRegime.FALLING,
        vwap_score=0.20,
        vwap_dev_pct=-0.002,
        signal_4h="red_bar_growing",
        btc_cumret_4bar=-0.006,
    )

    assert result["action"] == "BLOCK"
    assert "btc_falling" in result["reason"]


def test_falling_btc_caps_below_vwap_long_with_medium_vwap_score() -> None:
    gate = BtcEntryRegimeGate({})

    result = gate.check_entry(
        direction="long",
        btc_regime=BtcRegime.FALLING,
        vwap_score=0.45,
        vwap_dev_pct=-0.006,
        signal_4h="red_bar_growing",
        btc_cumret_4bar=-0.006,
    )

    assert result["action"] == "PROBE_CAP"
    assert result["max_portion"] == 0.042


def test_btc_chase_short_blocks_after_large_four_bar_drop_with_weak_vwap() -> None:
    gate = BtcEntryRegimeGate({})

    result = gate.check_entry(
        direction="short",
        btc_regime=BtcRegime.FALLING,
        vwap_score=0.30,
        vwap_dev_pct=0.002,
        signal_4h="green_bar_growing",
        btc_cumret_4bar=-0.016,
    )

    assert result["action"] == "BLOCK"
    assert "chase_short" in result["reason"]


def test_rising_btc_blocks_low_vwap_short() -> None:
    gate = BtcEntryRegimeGate({})

    result = gate.check_entry(
        direction="short",
        btc_regime=BtcRegime.RISING,
        vwap_score=0.35,
        vwap_dev_pct=0.001,
        signal_4h="green_bar_growing",
        btc_cumret_4bar=0.006,
    )

    assert result["action"] == "BLOCK"
    assert "btc_rising" in result["reason"]
