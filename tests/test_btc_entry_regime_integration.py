from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.decision_engine import FundFlowDecisionEngine
from src.fund_flow.macd_strategy_v2 import MACDSignalV2
from src.fund_flow.models import Operation


def test_decision_engine_blocks_low_vwap_long_when_btc_is_falling() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
                "btc_entry_regime_gate": {"enabled": True},
            }
        }
    )
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.80,
        vwap_score=0.20,
        vwap_deviation=-0.002,
        signal_type_1h="red_bar_growing",
        details={"signal_type_4h": "red_bar_growing", "score_volume": 0.05, "market_regime": "TREND"},
    )
    metadata = {
        "signal_direction": "long",
        "signal_score": 0.80,
        "vwap_score": 0.20,
        "vwap_deviation": -0.002,
    }

    decision = engine._apply_entry_quality_pretrade_gates(
        symbol="ADAUSDT",
        signal=signal,
        metadata=metadata,
        proposed_operation=Operation.BUY,
        portion=0.15,
        btc_rets_4bar=[-0.0015, -0.0012, -0.0011, -0.0013],
    )

    assert decision is not None
    assert decision.operation == Operation.HOLD
    assert decision.reason == "btc_entry_regime_block"
    assert metadata["btc_entry_regime_gate"]["action"] == "BLOCK"


def test_decision_engine_caps_range_high_score_entry() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
                "macd_mtf_strategy_v2": {
                    "entry_quality_gates": {
                        "range_gate": {"enabled": True, "block_below_score": 0.80, "probe_max": 0.060}
                    }
                },
            }
        }
    )
    signal = MACDSignalV2(
        direction="short",
        signal_score=0.82,
        vwap_score=0.70,
        vwap_deviation=0.001,
        signal_type_1h="green_bar_growing",
        details={"signal_type_4h": "green_bar_growing", "score_volume": 0.05, "market_regime": "RANGE"},
    )
    metadata = {"signal_score": 0.82, "vwap_score": 0.70, "regime": "RANGE"}

    decision = engine._apply_entry_quality_pretrade_gates(
        symbol="SUIUSDT",
        signal=signal,
        metadata=metadata,
        proposed_operation=Operation.SELL,
        portion=0.15,
        btc_rets_4bar=[0.0, 0.0, 0.0, 0.0],
    )

    assert decision is None
    assert metadata["entry_quality_portion_cap"] == 0.060
    assert metadata["regime_entry_gate"]["action"] == "PROBE_CAP"
