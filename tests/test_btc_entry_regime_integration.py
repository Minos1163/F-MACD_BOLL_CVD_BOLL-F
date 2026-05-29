from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.decision_engine import FundFlowDecisionEngine
from src.fund_flow.macd_strategy_v2 import MACDSignalV2, MACDStrategyV2Config, MACDStrategyV2Engine
from src.fund_flow.models import Operation


def test_decision_engine_does_not_block_long_because_of_vwap_when_btc_is_falling() -> None:
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

    assert decision is None
    assert metadata["btc_entry_regime_gate"]["action"] == "PASS"


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


def test_decision_engine_builds_continuation_long_decision_from_slow_bull_context() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "min_leverage": 3,
                "default_leverage": 4,
                "max_leverage": 9,
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
            }
        }
    )
    macd_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(enable_continuation_long=True)
    )
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        vwap_score=0.10,
        signal_type_1h="red_bar_shrinking",
    )
    metadata = {"close_15m": 1.03, "vwap_score": 0.10}
    flow_context = {
        "market_breadth": {"is_slow_bull": True, "btc_ret_30m": 0.003, "breadth_ratio": 0.72},
        "timeframes": {
            "15m": {
                "close_series": [
                    1.00, 1.002, 1.004, 1.006, 1.008, 1.010, 1.012, 1.014,
                    1.016, 1.018, 1.020, 1.022, 1.024, 1.026, 1.028, 1.030,
                ],
            }
        },
        "btc_alt_corr": 0.60,
    }

    decision = engine._build_continuation_long_decision(
        symbol="WLDUSDT",
        price=1.03,
        current_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        signal=signal,
        metadata=metadata,
        macd_v2_engine=macd_engine,
        market_flow_context=flow_context,
        regime_runtime_mode="BOTH",
    )

    assert decision is not None
    assert decision.operation == Operation.BUY
    assert decision.target_portion_of_balance <= 0.042
    assert decision.leverage == 3
    assert decision.reason.startswith("slow_bull_continuation_long")
    assert decision.metadata["competition_score"] > 0.60
    assert decision.metadata["continuation_ranking_score"] == decision.metadata["competition_score"]


def test_continuation_long_allows_zero_vwap_score_in_slow_bull() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "min_leverage": 3,
                "default_leverage": 4,
                "max_leverage": 9,
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
            }
        }
    )
    macd_engine = MACDStrategyV2Engine(MACDStrategyV2Config(enable_continuation_long=True))
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        vwap_score=0.0,
        signal_type_1h="red_bar_shrinking",
    )
    metadata = {"close_15m": 1.06, "vwap_score": 0.0}
    flow_context = {
        "market_breadth": {
            "is_slow_bull": True,
            "mode": "alt_breadth_led",
            "btc_ret_30m": 0.0005,
            "breadth_ratio": 0.92,
            "alt_median_60m": 0.006,
        },
        "timeframes": {
            "15m": {
                "close_series": [
                    1.00, 1.004, 1.008, 1.012, 1.016, 1.020, 1.024, 1.028,
                    1.032, 1.036, 1.040, 1.044, 1.048, 1.052, 1.056, 1.060,
                ],
            }
        },
        "btc_alt_corr": 0.70,
    }

    decision = engine._build_continuation_long_decision(
        symbol="HYPEUSDT",
        price=1.06,
        current_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        signal=signal,
        metadata=metadata,
        macd_v2_engine=macd_engine,
        market_flow_context=flow_context,
        regime_runtime_mode="BOTH",
    )

    assert decision is not None
    assert decision.operation == Operation.BUY
    assert decision.reason.startswith("slow_bull_continuation_long")
    assert decision.metadata["slow_bull_continuation"]["allowed"] is True


def test_live_slow_bull_rsi_cap_allows_extreme_continuation_probe() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "min_leverage": 3,
                "default_leverage": 4,
                "max_leverage": 9,
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
                "slow_bull_live_test": {
                    "enabled": True,
                    "rsi_extreme_mode": "cap_not_block",
                    "rsi_extreme_max_portion": 0.02,
                },
            }
        }
    )
    macd_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_continuation_long=True,
            continuation_long_rsi_max=100.0,
        )
    )
    signal = MACDSignalV2(direction="neutral", signal_score=0.0, signal_type_1h="red_bar_shrinking")
    metadata = {"close_15m": 1.06}
    flow_context = {
        "market_breadth": {"is_slow_bull": True, "mode": "alt_breadth_led", "btc_ret_30m": 0.0005, "breadth_ratio": 0.92},
        "timeframes": {"15m": {"close_series": [1.00, 1.004, 1.008, 1.012, 1.016, 1.020, 1.024, 1.028, 1.032, 1.036, 1.040, 1.044, 1.048, 1.052, 1.056, 1.060]}},
        "btc_alt_corr": 0.70,
    }

    decision = engine._build_continuation_long_decision(
        symbol="ICPUSDT",
        price=1.06,
        current_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        signal=signal,
        metadata=metadata,
        macd_v2_engine=macd_engine,
        market_flow_context=flow_context,
        regime_runtime_mode="BOTH",
    )

    assert decision is not None
    assert decision.target_portion_of_balance == 0.02
    assert decision.metadata["rsi_override"] == "capped_extreme"
    assert decision.metadata["final_portion_after_rsi"] == 0.02


def test_continuation_long_caps_strong_boll_probe_size_without_blocking() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "macd_mtf_strategy_v2",
                "min_leverage": 3,
                "default_leverage": 4,
                "max_leverage": 9,
                "default_target_portion": 0.15,
                "max_symbol_position_portion": 0.20,
                "macd_mtf_strategy_v2": {
                    "continuation_long": {
                        "enabled": True,
                        "strong_boll_portion_cap_enabled": True,
                        "strong_boll_ema_multiplier_threshold": 1.2,
                        "strong_boll_max_portion": 0.02,
                    }
                },
            }
        }
    )
    macd_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_continuation_long=True,
            continuation_long_max_portion_6of6=0.042,
            continuation_long_strong_boll_portion_cap_enabled=True,
            continuation_long_strong_boll_ema_multiplier_threshold=1.2,
            continuation_long_strong_boll_max_portion=0.02,
        )
    )
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        vwap_score=0.0,
        signal_type_1h="red_bar_shrinking",
        ema_multiplier=1.2,
    )
    metadata = {"close_15m": 1.06}
    flow_context = {
        "market_breadth": {
            "is_slow_bull": True,
            "mode": "alt_breadth_led",
            "btc_ret_30m": 0.0005,
            "breadth_ratio": 0.92,
            "alt_median_60m": 0.006,
        },
        "timeframes": {
            "15m": {
                "close_series": [
                    1.00, 1.004, 1.008, 1.012, 1.016, 1.020, 1.024, 1.028,
                    1.032, 1.036, 1.040, 1.044, 1.048, 1.052, 1.056, 1.060,
                ],
            }
        },
        "btc_alt_corr": 0.70,
    }

    decision = engine._build_continuation_long_decision(
        symbol="HYPEUSDT",
        price=1.06,
        current_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        signal=signal,
        metadata=metadata,
        macd_v2_engine=macd_engine,
        market_flow_context=flow_context,
        regime_runtime_mode="BOTH",
    )

    assert decision is not None
    assert decision.operation == Operation.BUY
    assert decision.target_portion_of_balance == 0.02
    assert decision.metadata["continuation_strong_boll_portion_cap"]["applied"] is True
    assert decision.metadata["final_portion_after_rsi"] == 0.02
