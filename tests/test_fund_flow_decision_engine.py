import logging

import pytest

from src.fund_flow.decision_engine import FundFlowDecisionEngine
from src.fund_flow.macd_strategy_v2 import MACDSignalV2
from src.fund_flow.models import FundFlowDecision, Operation, TimeInForce


def _cfg():
    return {
        "trading": {"default_leverage": 2},
        "risk": {"max_position_pct": 0.2},
        "fund_flow": {
            "default_target_portion": 0.2,
            "open_threshold": 0.2,
            "close_threshold": 0.3,
            "entry_slippage": 0.001,
            "deepseek_weight_router": {"enabled": False},
        },
    }


def _trend_context(
    *,
    cvd_ratio: float,
    cvd_momentum: float,
    oi_delta_ratio: float,
    funding_rate: float,
    depth_ratio: float,
    imbalance: float,
    ema_fast: float,
    ema_slow: float,
    adx: float = 30.0,
    atr_pct: float = 0.005,
):
    tf_ctx = {
        "cvd_ratio": cvd_ratio,
        "cvd_momentum": cvd_momentum,
        "oi_delta_ratio": oi_delta_ratio,
        "funding_rate": funding_rate,
        "depth_ratio": depth_ratio,
        "imbalance": imbalance,
    }
    tf_15m = {**tf_ctx, "ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx, "atr_pct": atr_pct}
    return {"timeframes": {"15m": tf_15m, "5m": dict(tf_ctx)}}


def test_macd_mtf_default_4h_enhancement_weight_is_aligned_to_v2_default():
    cfg = _cfg()
    cfg["fund_flow"]["macd_mtf_strategy"] = {}

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_mtf_strategy_config.weight_4h_enhancement == 0.10


def test_macd_v2_common_stable_continuation_threshold_populates_both_sides():
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_thresholds": {
            "stable_continuation_min_signal_score": 0.86,
        },
        "entry_filters": {
            "enable_stable_bear_continuation": True,
            "enable_stable_bull_continuation": True,
        },
    }

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.stable_bear_continuation_min_signal_score == 0.86
    assert engine.macd_v2_config.stable_bull_continuation_min_signal_score == 0.86


def test_macd_v2_common_stable_continuation_filters_are_side_defaults_only():
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_stable_bear_continuation": True,
            "enable_stable_bull_continuation": True,
            "stable_continuation_min_vwap_score": 0.07,
            "stable_continuation_min_adx_1h": 28.0,
            "stable_continuation_min_4h_bars": 2,
            "stable_bull_continuation_min_vwap_score": 0.11,
        },
    }

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.stable_bear_continuation_min_vwap_score == 0.07
    assert engine.macd_v2_config.stable_bear_continuation_min_adx_1h == 28.0
    assert engine.macd_v2_config.stable_bear_continuation_min_4h_bars == 2
    assert engine.macd_v2_config.stable_bull_continuation_min_vwap_score == 0.11
    assert engine.macd_v2_config.stable_bull_continuation_min_adx_1h == 28.0
    assert engine.macd_v2_config.stable_bull_continuation_min_4h_bars == 2


def test_macd_v2_weak_combo_veto_flag_propagates_from_live_config():
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_weak_combo_veto": False,
        },
    }

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.enable_weak_combo_veto is False


def test_macd_v2_soft_long_threshold_override_populates_config():
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_thresholds": {
            "soft_long_min_signal_score": 0.80,
        },
    }

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.soft_long_min_signal_score == 0.80


def test_macd_v2_direction_gate_veto_uses_effective_runtime_mode():
    engine = FundFlowDecisionEngine(_cfg())
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="VETUSDT",
        target_portion_of_balance=0.2,
        leverage=4,
        reason="macd_v2_short_1h_green_bar_growing_15m_soft_short_neutral_vwap_0.12",
        metadata={"direction_lock": "BOTH"},
    )

    resolved = engine._apply_macd_v2_direction_gate(
        decision,
        effective_mode="LONG_ONLY",
        source="macd_4h_regime_state.side_override_mode",
    )

    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["direction_lock"] == "LONG_ONLY"
    assert resolved.metadata["direction_gate_source"] == "macd_4h_regime_state.side_override_mode"
    assert resolved.metadata["direction_gate_effective_mode"] == "LONG_ONLY"
    assert resolved.metadata["direction_gate_pre_decision"] == Operation.SELL.value
    assert resolved.metadata["direction_gate_final_decision"] == Operation.HOLD.value
    assert resolved.metadata["direction_gate_veto"] is True
    assert resolved.metadata["blocked_reason"] == "direction_gate_veto"


def test_macd_v2_entry_routing_extracts_sovereign_metadata_and_gtc_tif() -> None:
    engine = FundFlowDecisionEngine(_cfg())
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.91,
        signal_type_1h="flip_bullish",
        details={
            "competition_score": 1.0465,
            "execution_route": "rsi_launch_sovereign",
            "priority_execution_applied": True,
            "priority_signal": True,
            "entry_time_in_force": "GTC",
            "entry_expire_seconds": 30,
            "entry_price_mode": "elastic_limit",
            "entry_retry_enabled": True,
            "entry_retry_max_attempts": 1,
            "rsi_launch_sovereign_active": True,
            "rsi_launch_sovereign_side": "long",
            "rsi_launch_sovereign_bonus_score": 0.12,
            "rsi_launch_sovereign_threshold_override": 0.80,
            "rsi_launch_sovereign_competition_multiplier": 1.15,
        },
    )

    tif, metadata = engine._extract_macd_v2_entry_routing(signal)

    assert tif.value == "Gtc"
    assert metadata["competition_score"] == pytest.approx(1.0465, rel=1e-6)
    assert metadata["execution_route"] == "rsi_launch_sovereign"
    assert metadata["priority_execution_applied"] is True
    assert metadata["priority_signal"] is True
    assert metadata["entry_time_in_force"] == "GTC"
    assert metadata["entry_expire_seconds"] == 30
    assert metadata["entry_price_mode"] == "elastic_limit"
    assert metadata["entry_retry_enabled"] is True
    assert metadata["entry_retry_max_attempts"] == 1
    assert metadata["rsi_launch_sovereign_active"] is True
    assert metadata["rsi_launch_sovereign_side"] == "long"
    assert metadata["rsi_launch_sovereign_bonus_score"] == pytest.approx(0.12, rel=1e-6)
    assert metadata["rsi_launch_sovereign_threshold_override"] == pytest.approx(0.80, rel=1e-6)
    assert metadata["rsi_launch_sovereign_competition_multiplier"] == pytest.approx(1.15, rel=1e-6)


def test_macd_v2_entry_routing_defaults_to_standard_ioc() -> None:
    engine = FundFlowDecisionEngine(_cfg())
    signal = MACDSignalV2(direction="short", signal_score=0.84, signal_type_1h="flip_bearish", details={})

    tif, metadata = engine._extract_macd_v2_entry_routing(signal)

    assert tif.value == "Ioc"
    assert metadata["competition_score"] == pytest.approx(0.84, rel=1e-6)
    assert metadata["execution_route"] == "standard"
    assert metadata["priority_execution_applied"] is False
    assert metadata["rsi_launch_sovereign_active"] is False


def test_macd_v2_priority_metadata_enables_standard_ioc_market_fallback() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_priority_execution": True,
            "priority_exec_min_score": 0.90,
            "priority_exec_vip_min_score": 0.92,
        }
    }
    engine = FundFlowDecisionEngine(cfg)
    signal = MACDSignalV2(direction="long", signal_score=0.68, signal_type_1h="red_bar_growing", details={})

    metadata = engine._resolve_macd_v2_priority_metadata(signal, macd_v2_engine=None)

    assert metadata["execution_route"] == "ioc_market_fallback"
    assert metadata["priority_execution_applied"] is False
    assert metadata["entry_time_in_force"] == "IOC"
    assert metadata["entry_market_fallback_enabled"] is True
    assert metadata["entry_market_fallback_timeout_ms"] == 2000
    assert metadata["entry_market_fallback_max_slippage_bps"] == 5
    assert metadata["entry_execution_policy"] == "ioc_market_fallback"


def test_macd_v2_priority_metadata_uses_updated_live_default_expiry_windows() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_priority_execution": True,
            "priority_exec_min_score": 0.90,
            "priority_exec_expire_seconds": 25,
            "priority_exec_vip_min_score": 0.92,
            "priority_exec_vip_expire_seconds": 45,
        }
    }
    engine = FundFlowDecisionEngine(cfg)

    regular = MACDSignalV2(direction="long", signal_score=0.91, signal_type_1h="red_bar_growing", details={})
    vip = MACDSignalV2(direction="long", signal_score=0.93, signal_type_1h="red_bar_growing", details={})

    regular_md = engine._resolve_macd_v2_priority_metadata(regular, macd_v2_engine=None)
    vip_md = engine._resolve_macd_v2_priority_metadata(vip, macd_v2_engine=None)

    assert regular_md["entry_expire_seconds"] == 25
    assert vip_md["entry_expire_seconds"] == 45


def test_macd_v2_sovereign_entry_routing_keeps_market_fallback_disabled() -> None:
    engine = FundFlowDecisionEngine(_cfg())
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.91,
        signal_type_1h="flip_bullish",
        details={
            "competition_score": 1.0465,
            "execution_route": "rsi_launch_sovereign",
            "priority_execution_applied": True,
            "priority_signal": True,
            "entry_time_in_force": "GTC",
            "entry_expire_seconds": 30,
            "entry_price_mode": "elastic_limit",
            "entry_retry_enabled": True,
            "entry_retry_max_attempts": 1,
            "rsi_launch_sovereign_active": True,
            "rsi_launch_sovereign_side": "long",
            "rsi_launch_sovereign_bonus_score": 0.12,
            "rsi_launch_sovereign_threshold_override": 0.80,
            "rsi_launch_sovereign_competition_multiplier": 1.15,
            "entry_market_fallback_enabled": False,
            "entry_market_fallback_timeout_ms": 0,
            "entry_market_fallback_max_slippage_bps": 0,
            "entry_execution_policy": "priority_execution_vip",
        },
    )

    tif, metadata = engine._extract_macd_v2_entry_routing(signal)

    assert tif.value == "Gtc"
    assert metadata["entry_market_fallback_enabled"] is False
    assert metadata["entry_market_fallback_timeout_ms"] == 0
    assert metadata["entry_market_fallback_max_slippage_bps"] == 0
    assert metadata["entry_execution_policy"] == "priority_execution_vip"


def test_macd_v2_live_defaults_use_rsi_rhythm_weights() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {}

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.weight_4h_direction == 0.40
    assert engine.macd_v2_config.weight_1h_direction == 0.15
    assert engine.macd_v2_config.weight_rsi_rhythm == 0.30
    assert engine.macd_v2_config.weight_vwap == 0.05
    assert engine.macd_v2_config.weight_15m_entry == 0.0
    assert engine.macd_v2_config.min_signal_score == 0.85
    assert engine.macd_v2_config.red_bar_growing_min_signal_score == 0.90
    assert engine.macd_v2_config.green_bar_growing_min_signal_score == 0.87
    assert engine.macd_v2_config.flip_bearish_min_signal_score == 0.84
    assert engine.macd_v2_config.flip_bullish_min_signal_score == 0.82
    assert engine.macd_v2_config.min_vwap_score_for_entry == 0.10


def test_macd_v2_legacy_soft_15m_flags_emit_deprecation_warning(caplog) -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_soft_15m_confirmation_when_4h_primary": True,
            "soft_15m_entry_score": 0.28,
        },
        "rsi_config": {
            "enable_entry_refinement": False,
            "period": 14,
        },
    }

    with caplog.at_level(logging.WARNING):
        FundFlowDecisionEngine(cfg)

    assert "deprecated" in caplog.text.lower()
    assert "soft_15m" in caplog.text.lower()
    assert "rsi refinement" in caplog.text.lower()


def test_macd_v2_priority_execution_uses_gtc_route_for_high_score_signal() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_priority_execution": True,
            "priority_exec_min_score": 0.90,
            "priority_exec_expire_seconds": 15,
        }
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="long",
                signal_score=0.91,
                signal_type_1h="flip_bullish",
                entry_type_15m="rsi_spring",
                vwap_score=0.04,
                vwap_state="long_dual_support",
                ema_multiplier=1.0,
                ema_structure_status="normal",
                details={
                    "rsi_exposure_mult": 1.0,
                    "rsi_macd_conflict": False,
                },
            )

        def calculate_leverage(self, *args, **kwargs):
            return 4

        def resolve_session_position_scale(self, *args, **kwargs):
            return 1.0

        def resolve_symbol_risk_session_scale(self, *args, **kwargs):
            return 1.0

        def calculate_position_portion(self, *args, **kwargs):
            return 0.20

        def is_watchlist_symbol(self, symbol):
            return False

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "long",
        "max_leverage": 4,
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "volume": 1000.0,
                "avg_volume": 500.0,
                "bb_middle": 100.0,
                "bb_upper": 102.0,
                "bb_lower": 98.0,
                "close": 101.0,
                "close_series": [99.0, 100.0, 101.0],
            },
            "1h": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "vwap": 100.5,
                "close": 101.0,
                "bb_middle": 100.0,
                "bb_upper": 103.0,
                "bb_lower": 97.0,
                "atr": 1.0,
                "adx": 24.0,
                "close_series": [99.0, 100.0, 101.0],
                "vwap_series": [100.0, 100.2, 100.5],
            },
            "4h": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "bb_middle": 99.5,
                "bb_upper": 104.0,
                "bb_lower": 95.0,
                "adx": 22.0,
                "close_series": [98.0, 99.5, 101.0],
            },
        }
    }

    decision = engine._decide_macd_v2_strategy(
        "VETUSDT",
        {"positions": {}},
        101.0,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.BUY
    assert decision.time_in_force == TimeInForce.GTC
    assert decision.metadata["execution_route"] == "priority_execution"
    assert decision.metadata["entry_time_in_force"] == "GTC"
    assert decision.metadata["entry_expire_seconds"] == 15
    assert decision.metadata["entry_price_mode"] == "elastic_limit"
    assert decision.metadata["priority_execution_applied"] is True
    assert decision.metadata["competition_score"] == pytest.approx(1.0465, rel=1e-6)


def test_macd_v2_priority_execution_uses_vip_route_for_score_above_vip_floor() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "enable_priority_execution": True,
            "priority_exec_min_score": 0.90,
            "priority_exec_expire_seconds": 15,
            "priority_exec_vip_min_score": 0.92,
            "priority_exec_vip_expire_seconds": 30,
            "priority_exec_vip_allow_retry": True,
        }
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="long",
                signal_score=0.93,
                signal_type_1h="flip_bullish",
                entry_type_15m="rsi_spring",
                vwap_score=0.04,
                vwap_state="long_dual_support",
                ema_multiplier=1.0,
                ema_structure_status="normal",
                details={
                    "rsi_exposure_mult": 1.0,
                    "rsi_macd_conflict": False,
                },
            )

        def calculate_leverage(self, *args, **kwargs):
            return 4

        def resolve_session_position_scale(self, *args, **kwargs):
            return 1.0

        def resolve_symbol_risk_session_scale(self, *args, **kwargs):
            return 1.0

        def calculate_position_portion(self, *args, **kwargs):
            return 0.20

        def is_watchlist_symbol(self, symbol):
            return False

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "long",
        "max_leverage": 4,
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "volume": 1000.0,
                "avg_volume": 500.0,
                "bb_middle": 100.0,
                "bb_upper": 102.0,
                "bb_lower": 98.0,
                "close": 101.0,
                "close_series": [99.0, 100.0, 101.0],
            },
            "1h": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "vwap": 100.5,
                "close": 101.0,
                "bb_middle": 100.0,
                "bb_upper": 103.0,
                "bb_lower": 97.0,
                "atr": 1.0,
                "adx": 24.0,
                "close_series": [99.0, 100.0, 101.0],
                "vwap_series": [100.0, 100.2, 100.5],
            },
            "4h": {
                "timestamp": 1714132800,
                "macd_hist_series": [0.01, 0.02],
                "bb_middle": 99.5,
                "bb_upper": 104.0,
                "bb_lower": 95.0,
                "adx": 22.0,
                "close_series": [98.0, 99.5, 101.0],
            },
        }
    }

    decision = engine._decide_macd_v2_strategy(
        "VETUSDT",
        {"positions": {}},
        101.0,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.BUY
    assert decision.time_in_force == TimeInForce.GTC
    assert decision.metadata["execution_route"] == "priority_execution_vip"
    assert decision.metadata["entry_time_in_force"] == "GTC"
    assert decision.metadata["entry_expire_seconds"] == 30
    assert decision.metadata["entry_price_mode"] == "elastic_limit"
    assert decision.metadata["priority_execution_applied"] is True
    assert decision.metadata["priority_execution_tier"] == "vip"
    assert decision.metadata["entry_retry_enabled"] is True
    assert decision.metadata["entry_retry_max_attempts"] == 1


def test_decide_hold_when_long_score_lacks_breakout_or_pullback():
    engine = FundFlowDecisionEngine(_cfg())
    decision = engine.decide(
        symbol="BTCUSDT",
        portfolio={"positions": {}},
        price=100.0,
        market_flow_context=_trend_context(
            cvd_ratio=0.8,
            cvd_momentum=0.6,
            oi_delta_ratio=0.4,
            funding_rate=-0.1,
            depth_ratio=1.2,
            imbalance=0.7,
            ema_fast=101.0,
            ema_slow=100.0,
        ),
        trigger_context={"trigger_type": "signal"},
    )
    assert decision.operation == Operation.HOLD


def test_decide_close_long_when_short_reversal():
    engine = FundFlowDecisionEngine(_cfg())
    decision = engine.decide(
        symbol="BTCUSDT",
        portfolio={"positions": {"BTCUSDT": {"side": "LONG"}}},
        price=100.0,
        market_flow_context=_trend_context(
            cvd_ratio=-0.9,
            cvd_momentum=-0.8,
            oi_delta_ratio=0.5,
            funding_rate=0.2,
            depth_ratio=0.8,
            imbalance=-0.7,
            ema_fast=99.0,
            ema_slow=100.0,
        ),
        trigger_context={"trigger_type": "signal"},
    )
    assert decision.operation == Operation.CLOSE
    assert decision.target_portion_of_balance == 1.0


def test_decide_hold_when_signal_not_enough():
    engine = FundFlowDecisionEngine(_cfg())
    decision = engine.decide(
        symbol="BTCUSDT",
        portfolio={"positions": {}},
        price=100.0,
        market_flow_context={"cvd_ratio": 0.0},
    )
    assert decision.operation == Operation.HOLD


def test_trend_capture_keeps_partial_score_without_micro_confirm():
    cfg = _cfg()
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "partial_confirm_enabled": True,
        "partial_confirm_min_align": 2,
        "partial_confirm_penalty": 0.03,
        "depth_ratio_neutral": 1.0,
        "depth_ratio_buffer": 0.0,
    }
    engine = FundFlowDecisionEngine(cfg)
    capture = engine._compute_trend_capture(
        "BTCUSDT",
        market_flow_context={
            "timeframes": {
                "5m": {
                    "close": 105.0,
                    "hh_n": 105.0,
                    "ll_n": 100.0,
                    "ema_fast": 104.0,
                    "ema_slow": 102.0,
                    "ret_period": 0.01,
                    "cvd_momentum": 0.02,
                    "oi_delta_ratio": 0.0,
                    "depth_ratio": 1.02,
                    "imbalance": 0.03,
                },
                "3m": {
                    "ret_period": 0.0,
                },
            },
            "microstructure_features": {
                "micro_delta": 0.0,
                "microprice_bias": 0.0,
                "trap_score": 0.1,
                "phantom_score": 0.1,
                "spread_z": 0.1,
            },
        },
        regime_info={},
        trend_pending={},
    )
    assert capture["trend_capture_breakout_long"] is True
    assert capture["trend_capture_confirm_3m_long"] is False
    assert capture["trend_capture_score_long"] > 0.0
    assert capture["trend_capture_side"] == "LONG"


def test_pick_leverage_uses_discrete_config_levels():
    engine = FundFlowDecisionEngine(_cfg())
    assert engine._pick_leverage(0.11, 0.10, 4, 8, 6) == 4
    assert engine._pick_leverage(0.55, 0.10, 4, 8, 6) == 6
    assert engine._pick_leverage(0.95, 0.10, 4, 8, 6) == 8


def test_resolve_entry_mode_uses_base_score_floor_for_trend_entry():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.085
    cfg["fund_flow"]["short_open_threshold"] = 0.085
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BTCUSDT",
        regime_info={
            "regime": "TREND",
            "cvd_norm": 0.3,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.10, "short_score": 0.0},
        trend_pending={"trend_pending_side": "NONE", "trend_pending_score": 0.0},
        trend_capture={
            "trend_capture_score_long": 0.0,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.BUY
    assert resolved.metadata["final_long_score"] >= 0.085


def test_confluence_ignores_ma10_bias_for_hard_block():
    engine = FundFlowDecisionEngine(_cfg())
    confluence = engine._compute_entry_confluence_v2(
        "BTCUSDT",
        market_flow_context={
            "_ma10_macd_confluence": {
                "last_close_1h": 99.0,
                "ma10_1h": 100.0,
                "ma10_1h_bias": -1,
                "macd_5m": 0.5,
                "macd_5m_signal": 0.1,
                "macd_5m_hist": 0.6,
                "macd_5m_hist_delta": 0.1,
                "kdj_k": 55.0,
                "kdj_d": 50.0,
                "kdj_j": 65.0,
            },
            "timeframes": {"5m": {}, "1h": {}},
        },
        cfg=engine._trend_capture_config(),
    )
    assert confluence["confluence_hard_block_long"] is False
    assert confluence["confluence_macd_trigger_long"] is True


def test_resolve_entry_mode_prunes_opposite_short_capture_when_confluence_fallback_turns_long():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["short_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 0.5,
            "consistency_3bars": 0,
            "cvd_norm": 0.25,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
            "lw": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
            "ev": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
        },
        base_scores={"long_score": 0.09, "short_score": 0.0},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_side": "SHORT",
            "trend_capture_score_long": 0.0,
            "trend_capture_score_short": 0.2,
            "trend_capture_breakout_short": True,
            "trend_capture_cvd_align_short": True,
            "trend_capture_depth_align_short": True,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
            "confluence_macd_trigger_long": True,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.BUY
    assert resolved.metadata["trend_capture_score_short"] == 0.0
    assert resolved.metadata["trend_capture_side"] in {"LONG", "NONE"}
    assert resolved.metadata["trend_capture_directional_prune"] is True
    assert resolved.metadata["trend_capture_pruned_side"] == "SHORT"


def test_resolve_entry_mode_prunes_opposite_long_capture_when_confluence_fallback_turns_short():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["short_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "SHORT_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 0.5,
            "consistency_3bars": 0,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
            "lw": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
            "ev": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
        },
        base_scores={"long_score": 0.0, "short_score": 0.09},
        trend_pending={"trend_pending_side": "SHORT", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_side": "LONG",
            "trend_capture_score_long": 0.2,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_cvd_align_long": True,
            "trend_capture_depth_align_long": True,
            "trend_capture_breakout_short": True,
            "trend_capture_pullback_resume_short": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
            "confluence_macd_trigger_short": True,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.SELL
    assert resolved.metadata["trend_capture_score_long"] == 0.0
    assert resolved.metadata["trend_capture_side"] in {"SHORT", "NONE"}
    assert resolved.metadata["trend_capture_directional_prune"] is True
    assert resolved.metadata["trend_capture_pruned_side"] == "LONG"


def test_resolve_entry_mode_blocks_short_without_3m_confirm_when_required():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["short_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "short_require_confirm_3m": True,
        "short_min_score_boost": 0.02,
        "short_min_gap_boost": 0.01,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="SOLUSDT",
        regime_info={"regime": "TREND"},
        base_scores={"long_score": 0.0, "short_score": 0.34},
        trend_pending={"trend_pending_side": "NONE", "trend_pending_score": 0.0},
        trend_capture={
            "trend_capture_score_long": 0.0,
            "trend_capture_score_short": 1.0,
            "trend_capture_confirm_3m_short": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["decision_source"] == "trend_short_confirm_blocked"
    assert resolved.metadata["short_entry_confirm_3m_required"] is True
    assert resolved.metadata["short_entry_confirm_gate_pass"] is False


def test_resolve_entry_mode_injects_long_confluence_fallback_into_entry_score():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["short_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 0.5,
            "consistency_3bars": 0,
            "cvd_norm": 0.25,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
            "lw": {
                "components": {
                    "primary_flat": True,
                    "backup_source": "ma10_macd_confluence_5m",
                    "backup_long_score": 1.0,
                    "backup_short_score": 0.0,
                }
            },
            "ev": {
                "components": {
                    "primary_flat": True,
                    "backup_source": "ma10_macd_confluence_5m",
                    "backup_long_score": 1.0,
                    "backup_short_score": 0.0,
                }
            },
        },
        base_scores={"long_score": 0.0001, "short_score": 0.0384},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_side": "SHORT",
            "trend_capture_score_long": 0.0,
            "trend_capture_score_short": 0.2,
            "trend_capture_breakout_short": True,
            "trend_capture_cvd_align_short": True,
            "trend_capture_depth_align_short": True,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.08,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": True,
            "confluence_macd_trigger_long": True,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.BUY
    assert resolved.metadata["trend_capture_score_long"] == 1.0
    assert resolved.metadata["trend_capture_confluence_injected"] is True
    assert resolved.metadata["trend_capture_confluence_injected_side"] == "LONG"
    assert resolved.metadata["trend_capture_confluence_injected_score"] == 1.0
    assert resolved.metadata["trend_capture_injection_confirm_pass"] is True
    assert resolved.metadata["trend_capture_injection_gate_pass"] is True
    assert resolved.metadata["final_long_score"] >= 0.07


def test_resolve_entry_mode_injects_short_confluence_fallback_into_entry_score():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["short_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "SHORT_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 0.5,
            "consistency_3bars": 0,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
            "lw": {
                "components": {
                    "primary_flat": True,
                    "backup_source": "ma10_macd_confluence_5m",
                    "backup_long_score": 0.0,
                    "backup_short_score": 1.0,
                }
            },
            "ev": {
                "components": {
                    "primary_flat": True,
                    "backup_source": "ma10_macd_confluence_5m",
                    "backup_long_score": 0.0,
                    "backup_short_score": 1.0,
                }
            },
        },
        base_scores={"long_score": 0.0384, "short_score": 0.0001},
        trend_pending={"trend_pending_side": "SHORT", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_side": "LONG",
            "trend_capture_score_long": 0.2,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_cvd_align_long": True,
            "trend_capture_depth_align_long": True,
            "trend_capture_breakout_short": True,
            "trend_capture_pullback_resume_short": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.08,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": True,
            "confluence_hard_block_short": False,
            "confluence_macd_trigger_short": True,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.SELL
    assert resolved.metadata["trend_capture_score_short"] == 1.0
    assert resolved.metadata["trend_capture_confluence_injected"] is True
    assert resolved.metadata["trend_capture_confluence_injected_side"] == "SHORT"
    assert resolved.metadata["trend_capture_confluence_injected_score"] == 1.0
    assert resolved.metadata["trend_capture_injection_confirm_pass"] is True
    assert resolved.metadata["trend_capture_injection_gate_pass"] is True
    assert resolved.metadata["final_short_score"] >= 0.07


def test_resolve_entry_mode_does_not_inject_fallback_when_entry_window_closed():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": False,
            "flow_confirm": 1.0,
            "consistency_3bars": 1,
            "lw": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m", "backup_long_score": 1.0}},
            "ev": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m", "backup_long_score": 1.0}},
        },
        base_scores={"long_score": 0.0001, "short_score": 0.0384},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={"trend_capture_score_long": 0.0, "trend_capture_score_short": 0.2, "trend_capture_side": "SHORT"},
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.08,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": True,
            "confluence_macd_trigger_long": True,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["trend_capture_confluence_injected"] is False
    assert resolved.metadata["trend_capture_injection_confirm_pass"] is True
    assert resolved.metadata["trend_capture_injection_gate_pass"] is False


def test_detect_regime_primary_flat_prefers_5m_confluence_fallback_over_cvd():
    engine = FundFlowDecisionEngine(_cfg())
    regime_info = engine._detect_regime(
        {
            "cvd_momentum": -0.8,
            "imbalance": -0.7,
            "timeframes": {
                "15m": {
                    "adx": 20.0,
                    "atr_pct": 0.004,
                    "ema_fast": 101.0,
                    "ema_slow": 100.0,
                    "last_open": 100.0,
                    "last_close": 100.2,
                    "macd_hist_norm": 0.0,
                    "macd_cross": "NONE",
                    "macd_hist_delta": 0.0,
                    "kdj_j": 50.0,
                    "kdj_cross": "NONE",
                    "kdj_zone": "MID",
                    "bb_pos_norm": 0.0,
                    "bb_width_norm": 0.0,
                    "bb_break": "NONE",
                    "bb_trend": "MID",
                    "bb_squeeze": False,
                },
                "5m": {},
                "1h": {},
            },
            "_ma10_macd_confluence": {
                "last_close_1h": 101.5,
                "ma10_1h": 100.0,
                "ma10_1h_bias": 1,
                "macd_5m": 0.6,
                "macd_5m_signal": 0.2,
                "macd_5m_hist": 0.4,
                "macd_5m_hist_delta": 0.1,
                "macd_5m_cross": "NONE",
                "macd_5m_zone": "ABOVE_ZERO",
                "kdj_k": 62.0,
                "kdj_d": 55.0,
                "kdj_j": 76.0,
                "kdj_cross": "NONE",
                "kdj_zone": "HIGH",
            },
        }
    )
    assert regime_info["guide_direction"] == "LONG_ONLY"
    assert regime_info["lw"]["components"]["backup_source"] == "ma10_macd_confluence_5m"
    assert regime_info["ev"]["components"]["backup_source"] == "ma10_macd_confluence_5m"


def test_detect_regime_primary_flat_still_uses_cvd_fallback_when_no_confluence():
    engine = FundFlowDecisionEngine(_cfg())
    regime_info = engine._detect_regime(
        {
            "cvd_momentum": -0.8,
            "imbalance": -0.7,
            "timeframes": {
                "15m": {
                    "adx": 20.0,
                    "atr_pct": 0.004,
                    "ema_fast": 101.0,
                    "ema_slow": 100.0,
                    "last_open": 100.0,
                    "last_close": 99.8,
                    "macd_hist_norm": 0.0,
                    "macd_cross": "NONE",
                    "macd_hist_delta": 0.0,
                    "kdj_j": 50.0,
                    "kdj_cross": "NONE",
                    "kdj_zone": "MID",
                    "bb_pos_norm": 0.0,
                    "bb_width_norm": 0.0,
                    "bb_break": "NONE",
                    "bb_trend": "MID",
                    "bb_squeeze": False,
                },
                "5m": {},
            },
        }
    )
    assert regime_info["guide_direction"] == "SHORT_ONLY"
    assert regime_info["lw"]["components"]["backup_source"] == "cvd_imbalance"


def test_resolve_entry_mode_blocks_long_when_symbol_override_is_short_only():
    cfg = _cfg()
    cfg["fund_flow"]["symbol_side_overrides"] = {"APTUSDT": "SHORT_ONLY"}
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="APTUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 0.6,
            "consistency_3bars": 1,
            "cvd_norm": 0.25,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.12, "short_score": 0.01},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_side": "LONG",
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["symbol_side_override_mode"] == "SHORT_ONLY"
    assert resolved.metadata["symbol_side_override_allowed"] is False
    assert resolved.metadata["blocked_operation"] == Operation.BUY.value


def test_decide_blocks_range_long_when_symbol_override_is_short_only(monkeypatch):
    cfg = _cfg()
    cfg["fund_flow"]["symbol_side_overrides"] = {"SUIUSDT": "SHORT_ONLY"}
    engine = FundFlowDecisionEngine(cfg)

    monkeypatch.setattr(engine, "_detect_regime", lambda _ctx: {"regime": "RANGE", "direction": "BOTH", "reason": "test"})
    monkeypatch.setattr(engine, "_compute_trend_pending", lambda *args, **kwargs: {"trend_pending_side": "NONE", "trend_pending_score": 0.0})
    monkeypatch.setattr(
        engine,
        "_engine_params_for",
        lambda _regime: {
            "default_leverage": 2,
            "default_target_portion": 0.2,
            "long_open_threshold": 0.07,
            "short_open_threshold": 0.07,
            "close_threshold": 0.3,
        },
    )
    monkeypatch.setattr(
        engine,
        "_extract_range_quantiles",
        lambda _ctx: {
            "ready": True,
            "imb_hi": 0.4,
            "imb_lo": -0.4,
            "cvd_hi": 0.3,
            "cvd_lo": -0.3,
            "trap_guard_enabled": False,
            "n": 64,
        },
    )
    monkeypatch.setattr(engine, "_extract_15m_context", lambda _ctx: {})
    monkeypatch.setattr(engine, "_extract_5m_context", lambda _ctx: {})
    monkeypatch.setattr(engine, "_score_range", lambda _ctx: {"long_score": 0.6, "short_score": 0.1})
    monkeypatch.setattr(engine, "_score_trend", lambda _ctx: {"long_score": 0.0, "short_score": 0.0})
    monkeypatch.setattr(
        engine,
        "_fuse_scores",
        lambda *_args, **_kwargs: {"long_score": 0.6, "short_score": 0.1, "fusion_applied": False},
    )
    monkeypatch.setattr(engine, "_record_15m_score", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_compute_flow_consistency", lambda *_args, **_kwargs: (0.0, 0))
    monkeypatch.setattr(engine, "_compute_trend_capture", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engine, "_compute_entry_confluence_v2", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engine, "_compute_range_veto_by_trend", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engine, "_extract_range_turn_values", lambda _ctx: {})
    monkeypatch.setattr(
        engine,
        "_evaluate_range_turn_confirm",
        lambda _vals: {
            "turned_up": True,
            "turned_down": False,
            "pass_count_long": 2,
            "pass_count_short": 0,
            "min_pass_count": 2,
            "mode": "1bar",
            "ready": True,
        },
    )

    decision = engine.decide(
        symbol="SUIUSDT",
        portfolio={"positions": {}},
        price=100.0,
        market_flow_context={
            "imbalance": -0.5,
            "cvd_momentum": -0.4,
            "oi_delta_ratio": 0.0,
        },
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert decision.operation == Operation.HOLD
    assert decision.metadata["symbol_side_override_mode"] == "SHORT_ONLY"
    assert decision.metadata["symbol_side_override_allowed"] is False
    assert decision.metadata["blocked_operation"] == Operation.BUY.value


def test_resolve_entry_mode_blocks_entry_when_feature_snapshot_is_all_zero():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BTCUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 1.0,
            "consistency_3bars": 2,
            "cvd_norm": 0.35,
            "combo_compare": {
                "feature_snapshot": {
                    "macd_hist_sign": 0,
                    "macd_cross_sign": 0,
                    "kdj_cross_sign": 0,
                    "kdj_zone_sign": 0,
                }
            },
        },
        base_scores={"long_score": 0.12, "short_score": 0.0},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["decision_source"] == "entry_hard_filter_blocked"
    assert resolved.metadata["entry_hard_filter_blocked"] is True
    assert "feature_snapshot_all_zero" in resolved.metadata["entry_hard_filters"]


def test_resolve_entry_mode_allows_primary_flat_ma10_fallback_when_feature_snapshot_is_all_zero():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BTCUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 1.0,
            "consistency_3bars": 2,
            "cvd_norm": 0.35,
            "combo_compare": {
                "feature_snapshot": {
                    "macd_hist_sign": 0,
                    "macd_cross_sign": 0,
                    "kdj_cross_sign": 0,
                    "kdj_zone_sign": 0,
                }
            },
            "lw": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
            "ev": {"components": {"primary_flat": True, "backup_source": "ma10_macd_confluence_5m"}},
        },
        base_scores={"long_score": 0.12, "short_score": 0.0},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.BUY
    assert resolved.metadata["entry_feature_snapshot_all_zero"] is True
    assert resolved.metadata["entry_feature_snapshot_zero_soft_bypass"] is True
    assert "feature_snapshot_all_zero" not in resolved.metadata["entry_hard_filters"]


def test_resolve_entry_mode_blocks_long_when_pending_side_is_short():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="ETHUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 1.0,
            "consistency_3bars": 2,
            "cvd_norm": 0.28,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.12, "short_score": 0.0},
        trend_pending={"trend_pending_side": "SHORT", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["decision_source"] == "entry_hard_filter_blocked"
    assert "pending_side_short_blocks_long" in resolved.metadata["entry_hard_filters"]


def test_resolve_entry_mode_blocks_long_when_cvd_norm_is_non_positive():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "required_long_cvd_norm": 0.12,
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="SOLUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 1.0,
            "consistency_3bars": 2,
            "cvd_norm": 0.0,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.12, "short_score": 0.0},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["decision_source"] == "entry_hard_filter_blocked"
    assert "cvd_norm_below_required_long" in resolved.metadata["entry_hard_filters"]


def test_resolve_entry_mode_blocks_entry_without_breakout_or_pullback():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BNBUSDT",
        regime_info={
            "regime": "TREND",
            "guide_direction": "LONG_ONLY",
            "allow_entry_window": True,
            "flow_confirm": 1.0,
            "consistency_3bars": 2,
            "cvd_norm": 0.31,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.12, "short_score": 0.0},
        trend_pending={"trend_pending_side": "LONG", "trend_pending_score": 0.6},
        trend_capture={
            "trend_capture_score_long": 0.12,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": False,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert resolved.metadata["decision_source"] == "entry_hard_filter_blocked"
    assert "no_breakout_no_pullback_long" in resolved.metadata["entry_hard_filters"]


def test_resolve_entry_mode_blocks_long_when_strict_trend_requirements_fail():
    cfg = _cfg()
    cfg["fund_flow"]["long_open_threshold"] = 0.07
    cfg["fund_flow"]["trend_capture"] = {
        "trend_only_mode": True,
        "required_flow_confirm": 1.0,
        "required_long_cvd_norm": 0.12,
        "required_price_oi_alignment_15m": 1.0,
        "required_adx_slope": 0.05,
        "required_long_ema_spread_expand": 0.0,
        "min_score": 0.08,
        "min_gap": 0.02,
        "base_score_floor_mult": 0.85,
    }
    engine = FundFlowDecisionEngine(cfg)
    resolved = engine._resolve_entry_mode(
        symbol="BTCUSDT",
        regime_info={
            "regime": "TREND",
            "flow_confirm": 0.5,
            "cvd_norm": 0.10,
            "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
        },
        base_scores={"long_score": 0.15, "short_score": 0.0},
        trend_pending={
            "trend_pending_side": "LONG",
            "trend_pending_score": 0.8,
            "trend_pending_price_oi_align": 0.0,
            "trend_pending_adx_slope": 0.01,
            "trend_pending_ema_spread_expand": 0.0,
        },
        trend_capture={
            "trend_capture_score_long": 0.2,
            "trend_capture_score_short": 0.0,
            "trend_capture_breakout_long": True,
            "trend_capture_pullback_resume_long": False,
        },
        confluence={
            "confluence_soft_penalty_long": 0.0,
            "confluence_soft_penalty_short": 0.0,
            "confluence_hard_block_long": False,
            "confluence_hard_block_short": False,
        },
        range_veto={},
        cfg=engine._trend_capture_config(),
    )
    assert resolved.operation == Operation.HOLD
    assert "flow_confirm_below_required" in resolved.metadata["entry_hard_filters"]
    assert "cvd_norm_below_required_long" in resolved.metadata["entry_hard_filters"]
    assert "price_oi_alignment_below_required" in resolved.metadata["entry_hard_filters"]
    assert "adx_slope_below_required" in resolved.metadata["entry_hard_filters"]
    assert "ema_spread_expand_not_positive_long" in resolved.metadata["entry_hard_filters"]


def test_decide_uses_dynamic_short_term_stop_loss_for_trend_entries():
    cfg = _cfg()
    cfg["fund_flow"].update(
        {
            "default_target_portion": 0.08,
            "long_open_threshold": 0.07,
            "default_leverage": 5,
            "min_leverage": 4,
            "max_leverage": 5,
            "engine_params": {
                "TREND": {
                    "default_target_portion": 0.08,
                    "default_leverage": 5,
                    "min_leverage": 4,
                    "max_leverage": 5,
                    "long_open_threshold": 0.07,
                    "dynamic_stop_loss_enabled": True,
                    "short_stop_loss_min_pct": 0.0035,
                    "short_stop_loss_max_pct": 0.0045,
                    "short_stop_loss_atr_mult": 1.2,
                    "take_profit_pct_levels": [0.0025, 0.0055],
                    "take_profit_reduce_pct_levels": [0.4, 0.3],
                }
            },
            "trend_capture": {
                "trend_only_mode": True,
                "required_flow_confirm": 1.0,
                "required_long_cvd_norm": 0.12,
                "required_price_oi_alignment_15m": 1.0,
                "required_adx_slope": 0.05,
                "required_long_ema_spread_expand": 0.0,
                "min_score": 0.08,
                "min_gap": 0.02,
                "base_score_floor_mult": 0.85,
            },
        }
    )
    engine = FundFlowDecisionEngine(cfg)
    engine._detect_regime = lambda *_args, **_kwargs: {
        "regime": "TREND",
        "direction": "LONG_ONLY",
        "guide_direction": "LONG_ONLY",
        "adx": 25.0,
        "atr_pct": 0.002,
        "cvd_norm": 0.2,
        "combo_compare": {"feature_snapshot": {"macd_hist_sign": 1, "kdj_cross_sign": 1}},
    }
    engine._compute_trend_pending = lambda *_args, **_kwargs: {
        "trend_pending_side": "LONG",
        "trend_pending_score": 0.8,
        "trend_pending_price_oi_align": 1.0,
        "trend_pending_adx_slope": 0.08,
        "trend_pending_ema_spread": 1.0,
        "trend_pending_ema_spread_expand": 0.01,
    }
    engine._compute_flow_consistency = lambda *_args, **_kwargs: (1.0, 2)
    engine._compute_trend_capture = lambda *_args, **_kwargs: {
        "trend_capture_side": "LONG",
        "trend_capture_score_long": 0.43,
        "trend_capture_score_short": 0.0,
        "trend_capture_breakout_long": True,
        "trend_capture_breakout_short": False,
        "trend_capture_pullback_resume_long": False,
        "trend_capture_pullback_resume_short": False,
    }
    engine._compute_entry_confluence_v2 = lambda *_args, **_kwargs: {
        "confluence_side": "LONG",
        "confluence_hard_block_long": False,
        "confluence_hard_block_short": False,
        "confluence_soft_penalty_long": 0.0,
        "confluence_soft_penalty_short": 0.0,
    }
    engine._compute_range_veto_by_trend = lambda *_args, **_kwargs: {}
    decision = engine.decide(
        symbol="BTCUSDT",
        portfolio={"positions": {}},
        price=100.0,
        market_flow_context={
            "timeframes": {
                "15m": {
                    "adx": 25.0,
                    "atr_pct": 0.002,
                    "ema_fast": 101.0,
                    "ema_slow": 100.0,
                    "ret_period": 0.01,
                    "oi_delta_ratio": 0.02,
                },
                "5m": {
                    "close": 105.0,
                    "hh_n": 105.0,
                    "ll_n": 100.0,
                    "ema_fast": 104.0,
                    "ema_slow": 102.0,
                    "ret_period": 0.01,
                    "cvd_momentum": 0.02,
                    "oi_delta_ratio": 0.02,
                    "depth_ratio": 1.02,
                    "imbalance": 0.03,
                },
                "3m": {
                    "ret_period": 0.02,
                },
            },
            "fund_flow_features": {"15m": {"oi_delta_ratio": 0.02}, "5m": {"oi_delta_ratio": 0.02}},
            "microstructure_features": {"micro_delta": 0.02, "microprice_bias": 0.02},
        },
        trigger_context={"trigger_type": "signal"},
        use_weight_router=False,
        use_ai_weights=False,
    )
    assert decision.operation == Operation.BUY
    assert decision.stop_loss_price is not None
    assert round((100.0 - float(decision.stop_loss_price)) / 100.0, 4) == 0.0035
    tp_levels = decision.metadata.get("tp_levels", [])
    assert len(tp_levels) == 2


def _rule_cfg():
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "ema10_ema30_1h_15m_rule"
    cfg["fund_flow"]["decision_timeframe"] = "15m"
    cfg["fund_flow"]["rule_strategy"] = {
        "enabled": True,
        "primary_trend_timeframe": "1h",
        "entry_timeframe": "15m",
        "min_stop_pct": 0.02,
        "max_stop_pct": 0.05,
        "tp1_min_pct": 0.05,
        "tp1_max_pct": 0.10,
        "runner_activate_pct": 0.05,
        "tp1_reduce_pct": 0.5,
        "stop_break_buffer_pct": 0.0,
    }
    return cfg


def _rule_entry_context(*, direction: str, overrides=None):
    entry_tf = {
        "last_open": 100.0,
        "last_close": 101.0 if direction == "LONG_ONLY" else 99.0,
        "ema_10": 101.0 if direction == "LONG_ONLY" else 99.0,
        "ema_30": 100.0,
        "ema_cross": "GOLDEN" if direction == "LONG_ONLY" else "DEAD",
        "macd_cross": "GOLDEN" if direction == "LONG_ONLY" else "DEAD",
        "macd_zone": "ABOVE_ZERO" if direction == "LONG_ONLY" else "BELOW_ZERO",
        "macd_hist": 0.2 if direction == "LONG_ONLY" else -0.2,
        "macd_hist_expand_up": direction == "LONG_ONLY",
        "macd_hist_expand_down": direction == "SHORT_ONLY",
        "bb_middle": 100.0,
        "bb_upper": 101.2,
        "bb_lower": 98.8,
        "bb_break": "NONE",
        "bb_width_expand": False,
    }
    if isinstance(overrides, dict):
        entry_tf.update(overrides)
    return {"timeframes": {"15m": entry_tf}}


def test_rule_entry_confluence_macd_long_requires_ema_cross():
    engine = FundFlowDecisionEngine(_rule_cfg())
    confluence = engine._rule_entry_confluence(
        _rule_entry_context(direction="LONG_ONLY", overrides={"ema_cross": "NONE"}),
        {"direction": "LONG_ONLY"},
    )
    assert confluence["long_ok"] is False
    assert confluence["long_models"] == []



def test_rule_entry_confluence_bollinger_long_allows_without_ema_cross():
    engine = FundFlowDecisionEngine(_rule_cfg())
    confluence = engine._rule_entry_confluence(
        _rule_entry_context(
            direction="LONG_ONLY",
            overrides={
                "ema_cross": "NONE",
                "macd_cross": "NONE",
                "macd_hist_expand_up": False,
                "bb_break": "UPPER",
                "bb_width_expand": True,
            },
        ),
        {"direction": "LONG_ONLY"},
    )
    assert confluence["long_ok"] is True
    assert confluence["long_models"] == ["EMA_BB"]



def test_rule_entry_confluence_macd_short_requires_ema_cross():
    engine = FundFlowDecisionEngine(_rule_cfg())
    confluence = engine._rule_entry_confluence(
        _rule_entry_context(direction="SHORT_ONLY", overrides={"ema_cross": "NONE"}),
        {"direction": "SHORT_ONLY"},
    )
    assert confluence["short_ok"] is False
    assert confluence["short_models"] == []


def test_rule_entry_confluence_blocks_long_when_4h_macd_risk_is_bearish():
    cfg = _rule_cfg()
    cfg["dual_timeframe"] = {
        "enabled": True,
        "risk_filter": {
            "enable_4h_macd": True,
            "block_on_4h_divergence": True,
        },
    }
    engine = FundFlowDecisionEngine(cfg)
    ctx = _rule_entry_context(direction="LONG_ONLY")
    ctx["timeframes"]["4h"] = {
        "last_open": 101.0,
        "last_close": 99.0,
        "macd_cross": "DEAD",
        "macd_zone": "BELOW_ZERO",
        "macd_hist": -0.15,
        "macd_hist_delta": -0.04,
        "macd_hist_expand_up": False,
        "macd_hist_expand_down": True,
    }
    confluence = engine._rule_entry_confluence(ctx, {"direction": "LONG_ONLY"})
    assert confluence["long_ok"] is False
    assert confluence["long_models"] == []
    assert confluence["risk_filter_allow_long"] is False
    assert "4h_macd_risk_block" in confluence["reason"]


def test_rule_entry_confluence_blocks_short_when_4h_macd_risk_is_bullish():
    cfg = _rule_cfg()
    cfg["dual_timeframe"] = {
        "enabled": True,
        "risk_filter": {
            "enable_4h_macd": True,
            "block_on_4h_divergence": True,
        },
    }
    engine = FundFlowDecisionEngine(cfg)
    ctx = _rule_entry_context(direction="SHORT_ONLY")
    ctx["timeframes"]["4h"] = {
        "last_open": 99.0,
        "last_close": 101.0,
        "macd_cross": "GOLDEN",
        "macd_zone": "ABOVE_ZERO",
        "macd_hist": 0.15,
        "macd_hist_delta": 0.04,
        "macd_hist_expand_up": True,
        "macd_hist_expand_down": False,
    }
    confluence = engine._rule_entry_confluence(ctx, {"direction": "SHORT_ONLY"})
    assert confluence["short_ok"] is False
    assert confluence["short_models"] == []
    assert confluence["risk_filter_allow_short"] is False
    assert "4h_macd_risk_block" in confluence["reason"]


def test_rule_entry_confluence_keeps_entry_when_4h_risk_context_is_missing():
    cfg = _rule_cfg()
    cfg["dual_timeframe"] = {
        "enabled": True,
        "risk_filter": {
            "enable_4h_macd": True,
        },
    }
    engine = FundFlowDecisionEngine(cfg)
    confluence = engine._rule_entry_confluence(
        _rule_entry_context(direction="LONG_ONLY"),
        {"direction": "LONG_ONLY"},
    )
    assert confluence["long_ok"] is True
    assert confluence["risk_filter_allow_long"] is True
    assert confluence["risk_filter_reason"] == "missing_4h_context"


def test_rule_risk_plan_respects_2_to_5_pct_stop_band():
    engine = FundFlowDecisionEngine(_rule_cfg())
    risk_plan = engine._rule_build_risk_plan(
        direction="LONG",
        entry_price=100.0,
        stop_anchor=99.8,
        entry_models=["EMA_MACD"],
    )
    assert risk_plan["valid"] is True
    assert round((100.0 - float(risk_plan["stop_trigger_price"])) / 100.0, 4) == 0.02

    too_wide = engine._rule_build_risk_plan(
        direction="LONG",
        entry_price=100.0,
        stop_anchor=94.0,
        entry_models=["EMA_MACD"],
    )
    assert too_wide["valid"] is False
    assert "stop_too_wide" in too_wide["reason"]


def test_rule_stop_trigger_long_stops_on_macd_dead_cross_before_ema30_break():
    engine = FundFlowDecisionEngine(_rule_cfg())
    stop_state = engine._rule_stop_trigger(
        "LONG",
        _rule_entry_context(
            direction="LONG_ONLY",
            overrides={
                "last_close": 101.0,
                "ema_10": 102.0,
                "ema_30": 100.0,
                "macd_cross": "DEAD",
                "macd_zone": "ABOVE_ZERO",
            },
        ),
        fallback_price=101.0,
        current_pos={"entry_price": 100.0},
    )
    assert stop_state["triggered"] is True
    assert stop_state["runner_active"] is False
    assert stop_state["exit_trigger"] == "macd_dead_cross"


def test_rule_stop_trigger_short_stops_on_below_zero_golden_cross_before_ema30_break():
    engine = FundFlowDecisionEngine(_rule_cfg())
    stop_state = engine._rule_stop_trigger(
        "SHORT",
        _rule_entry_context(
            direction="SHORT_ONLY",
            overrides={
                "last_close": 99.0,
                "ema_10": 98.5,
                "ema_30": 100.0,
                "macd_cross": "GOLDEN",
                "macd_zone": "BELOW_ZERO",
            },
        ),
        fallback_price=99.0,
        current_pos={"entry_price": 100.0},
    )
    assert stop_state["triggered"] is True
    assert stop_state["runner_active"] is False
    assert stop_state["exit_trigger"] == "macd_golden_cross_below_zero"


def test_rule_stop_trigger_long_runner_exits_on_ema10_break():
    engine = FundFlowDecisionEngine(_rule_cfg())
    stop_state = engine._rule_stop_trigger(
        "LONG",
        _rule_entry_context(
            direction="LONG_ONLY",
            overrides={
                "last_close": 106.0,
                "ema_10": 107.0,
                "ema_30": 100.0,
                "macd_cross": "NONE",
            },
        ),
        fallback_price=106.0,
        current_pos={"entry_price": 100.0},
    )
    assert stop_state["triggered"] is True
    assert stop_state["runner_active"] is True
    assert stop_state["exit_stage"] == "RUNNER"
    assert stop_state["exit_trigger"] == "ema10_break"


def test_rule_stop_trigger_short_runner_exits_on_below_zero_golden_cross():
    engine = FundFlowDecisionEngine(_rule_cfg())
    stop_state = engine._rule_stop_trigger(
        "SHORT",
        _rule_entry_context(
            direction="SHORT_ONLY",
            overrides={
                "last_close": 94.0,
                "ema_10": 95.0,
                "ema_30": 100.0,
                "macd_cross": "GOLDEN",
                "macd_zone": "BELOW_ZERO",
            },
        ),
        fallback_price=94.0,
        current_pos={"entry_price": 100.0},
    )
    assert stop_state["triggered"] is True
    assert stop_state["runner_active"] is True
    assert stop_state["exit_stage"] == "RUNNER"
    assert stop_state["exit_trigger"] == "macd_golden_cross_below_zero"


def test_macd_v2_vol_vwap_warn_settings_propagate_from_config() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "entry_filters": {
            "vol_vwap_warn_min_score_vol": 0.02,
            "vol_vwap_warn_min_vwap_score": 0.03,
            "disable_red_bar_shrinking_long_dual_support_entries": False,
            "disable_green_bar_shrinking_short_dual_pressure_entries": False,
        },
        "position_management": {
            "vol_vwap_warn_position_scale": 0.25,
        },
    }

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.vol_vwap_warn_min_score_vol == pytest.approx(0.02, rel=1e-6)
    assert engine.macd_v2_config.vol_vwap_warn_min_vwap_score == pytest.approx(0.03, rel=1e-6)
    assert engine.vol_vwap_warn_position_scale == pytest.approx(0.25, rel=1e-6)
    assert engine.macd_v2_config.disable_red_bar_shrinking_long_dual_support_entries is False
    assert engine.macd_v2_config.disable_green_bar_shrinking_short_dual_pressure_entries is False


def test_macd_v2_buy_portion_is_scaled_when_vol_vwap_warn_is_set() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "position_management": {"vol_vwap_warn_position_scale": 0.50},
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="long",
                signal_score=0.82,
                signal_type_1h="red_bar_growing",
                entry_type_15m="rsi_confirmed",
                vwap_score=0.04,
                details={
                    "vol_vwap_warn": True,
                    "score_volume": 0.033,
                    "vwap_score": 0.04,
                    "rsi_exposure_mult": 1.0,
                    "rsi_macd_conflict": False,
                },
            )

        def calculate_leverage(self, *args, **kwargs):
            return 3

        def resolve_session_position_scale(self, *args, **kwargs):
            return 1.0

        def resolve_symbol_risk_session_scale(self, *args, **kwargs):
            return 1.0

        def calculate_position_portion(self, *args, **kwargs):
            return 0.20

        def is_watchlist_symbol(self, symbol):
            return False

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "long",
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 101.0},
            "1h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "vwap": 100.0, "close": 101.0},
            "4h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 101.0},
        }
    }

    decision = engine._decide_macd_v2_strategy(
        "ZROUSDT",
        {"positions": {}},
        101.0,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.BUY
    assert decision.target_portion_of_balance == pytest.approx(0.10, rel=1e-6)
    assert decision.metadata["vol_vwap_warn"] is True
    assert decision.metadata["vol_vwap_warn_position_scaled"] is True
    assert decision.metadata["vol_vwap_warn_position_scale"] == pytest.approx(0.50, rel=1e-6)
    assert decision.metadata["vol_vwap_warn_original_portion"] == pytest.approx(0.20, rel=1e-6)
    assert decision.metadata["vol_vwap_warn_adjusted_portion"] == pytest.approx(0.10, rel=1e-6)
    assert decision.metadata["score_volume"] == pytest.approx(0.033, rel=1e-6)
    assert decision.metadata["vwap_score"] == pytest.approx(0.04, rel=1e-6)


def test_macd_v2_sell_portion_is_not_scaled_without_vol_vwap_warn() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "position_management": {"vol_vwap_warn_position_scale": 0.50},
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="short",
                signal_score=0.82,
                signal_type_1h="green_bar_growing",
                entry_type_15m="rsi_confirmed",
                vwap_score=0.42,
                details={
                    "vol_vwap_warn": False,
                    "score_volume": 0.10,
                    "vwap_score": 0.42,
                    "rsi_exposure_mult": 1.0,
                    "rsi_macd_conflict": False,
                },
            )

        def calculate_leverage(self, *args, **kwargs):
            return 3

        def resolve_session_position_scale(self, *args, **kwargs):
            return 1.0

        def resolve_symbol_risk_session_scale(self, *args, **kwargs):
            return 1.0

        def calculate_position_portion(self, *args, **kwargs):
            return 0.20

        def is_watchlist_symbol(self, symbol):
            return False

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "short",
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 99.0},
            "1h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "vwap": 100.0, "close": 99.0},
            "4h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 99.0},
        }
    }

    decision = engine._decide_macd_v2_strategy(
        "DOGEUSDT",
        {"positions": {}},
        99.0,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.SELL
    assert decision.target_portion_of_balance == pytest.approx(0.20, rel=1e-6)
    assert decision.metadata["vol_vwap_warn"] is False
    assert decision.metadata["vol_vwap_warn_position_scaled"] is False
    assert "vol_vwap_warn_original_portion" not in decision.metadata


def test_macd_v2_neutral_signal_triggers_macd_1h_flip_exit_close() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "exit_management": {
            "macd_1h_flip_exit": {
                "enabled": True,
                "confirm_bars": 2,
                "flip_min_magnitude": 0.0003,
                "min_profit_to_early_exit": 0.006,
            }
        },
        "stop_loss_config": {"enable_4h_shrink_exit": False},
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="neutral",
                signal_score=0.0,
                signal_type_1h="red_bar_growing",
                details={
                    "macd_histogram_1h_current": -0.0005,
                    "macd_histogram_1h_history": [-0.0006, -0.0005],
                },
            )

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "long",
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "high": 100.9, "low": 100.6, "close": 100.8},
            "1h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "macd_hist": -0.0005, "macd_hist_prev": -0.0006, "close": 100.8},
            "4h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 100.8},
        }
    }
    portfolio = {"positions": {"VETUSDT": {"side": "LONG", "entry_price": 100.0}}}

    decision = engine._decide_macd_v2_strategy(
        "VETUSDT",
        portfolio,
        100.8,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.CLOSE
    assert decision.target_portion_of_balance == pytest.approx(1.0, rel=1e-6)
    assert "macd_1h_flip_exit" in decision.reason


def test_macd_v2_neutral_signal_triggers_rsi_overheat_partial_close() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {
        "exit_management": {
            "rsi_overheat_exit": {
                "enabled": True,
                "rsi_1h_overheat": 78.0,
                "min_mfe_to_trigger": 0.012,
                "partial_exit_ratio": 0.50,
            }
        },
        "stop_loss_config": {"enable_4h_shrink_exit": False},
    }
    engine = FundFlowDecisionEngine(cfg)

    class _StubStrategyEngine:
        def analyze(self, **_kwargs):
            return MACDSignalV2(
                direction="neutral",
                signal_score=0.0,
                signal_type_1h="red_bar_growing",
                details={
                    "rsi_1h": 80.0,
                    "macd_histogram_1h_current": 0.0010,
                    "macd_histogram_1h_prev": 0.0014,
                },
            )

        def resolve_4h_shrink_exit_policy(self, **kwargs):
            return {"active": False}

    engine._macd_v2_engine_for_symbol = lambda _symbol: (_StubStrategyEngine(), None)
    engine._build_macd_v2_4h_regime_state = lambda **_kwargs: {
        "side_override_mode": "BOTH",
        "state": "trend",
        "phase": "active",
        "side": "long",
        "close_on_reverse": False,
    }

    market_flow_context = {
        "timeframes": {
            "15m": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "high": 101.4, "low": 100.7, "close": 101.0},
            "1h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 101.0},
            "4h": {"timestamp": 1714132800, "macd_hist_series": [0.01, 0.02], "close": 101.0},
        }
    }
    portfolio = {"positions": {"VETUSDT": {"side": "LONG", "entry_price": 100.0}}}

    decision = engine._decide_macd_v2_strategy(
        "VETUSDT",
        portfolio,
        101.0,
        market_flow_context,
        {"regime": "trend", "adx": 24.0, "atr_pct": 0.01},
    )

    assert decision.operation == Operation.CLOSE
    assert decision.target_portion_of_balance == pytest.approx(0.50, rel=1e-6)
    assert "rsi_overheat_exit" in decision.reason

