from __future__ import annotations

from datetime import datetime, timezone

import pytest
import numpy as np

from src.fund_flow.macd_strategy_v2 import MACDStrategyV2Config, MACDStrategyV2Engine


def test_analyze_uses_4h_as_primary_score_source() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.5,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.0,
            weight_volume=0.15,
            min_signal_score=0.1,
            min_entry_score=0.1,
            red_bar_growing_min_signal_score=0.1,
            flip_bullish_min_signal_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.signal_score == pytest.approx(0.65, rel=1e-6)
    assert signal.details["primary_timeframe"] == "4h"
    assert signal.details["score_4h"] == pytest.approx(0.5, rel=1e-6)
    assert signal.details["score_1h"] == pytest.approx(0.0, rel=1e-6)


def test_analyze_blocks_when_4h_primary_but_1h_confirmation_is_opposite() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.5,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.0,
            weight_volume=0.15,
            min_signal_score=0.1,
            min_entry_score=0.1,
            red_bar_growing_min_signal_score=0.1,
            flip_bearish_min_signal_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.10, 0.05, -0.02, -0.05]),
        macd_hist_1h=np.array([0.20, 0.10, -0.05, -0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert "1H方向反向" in str(signal.details.get("reason"))


def test_neutral_upgrade_reenters_when_4h_anchor_exists_and_rsi_is_strong() -> None:
    base_kwargs = dict(
        weight_1h_direction=0.15,
        weight_4h_direction=0.40,
        weight_4h_enhancement=0.10,
        weight_rsi_rhythm=0.25,
        weight_vwap=0.0,
        weight_15m_entry=0.0,
        weight_volume=0.10,
        min_signal_score=0.40,
        min_entry_score=0.1,
        flip_bullish_min_signal_score=0.40,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=False,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="4h",
        require_1h_confirmation_when_4h_primary=True,
        allow_neutral_1h_confirmation=False,
        enable_neutral_upgrade=True,
        neutral_upgrade_min_rsi_score=0.30,
        neutral_upgrade_penalty_mult=0.90,
        rsi_period=3,
    )
    engine = MACDStrategyV2Engine(MACDStrategyV2Config(**base_kwargs))

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([0.02, 0.08, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=2,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=101.0,
        close_15m_series=np.array([100.0, 98.0, 96.0, 98.0, 101.0]),
        close_1h_series=np.array([100.0, 98.0, 99.0, 101.0, 103.0]),
        close_4h_series=np.array([98.0, 98.7, 99.8, 101.0, 102.4]),
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.details["neutral_upgrade_considered"] is True
    assert signal.details["neutral_upgrade_applied"] is True
    assert signal.details["neutral_original_reason"] == "1H无确认信号"
    assert signal.details["neutral_upgrade_penalty_mult"] == pytest.approx(0.90, rel=1e-6)
    assert signal.details["score_rsi_rhythm_raw"] >= 0.30
    assert signal.details["entry_type_15m"] == "rsi_spring"


def test_light_1h_confirmation_still_respects_flip_bullish_disable_filter() -> None:
    base_kwargs = dict(
        weight_1h_direction=0.0,
        weight_4h_direction=0.5,
        weight_4h_enhancement=0.0,
        weight_vwap=0.0,
        weight_15m_entry=0.15,
        weight_volume=0.15,
        min_signal_score=0.1,
        min_entry_score=0.1,
        red_bar_growing_min_signal_score=0.1,
        flip_bullish_min_signal_score=0.1,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_sniper=False,
        enable_flip_bullish_cooling=False,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=True,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="4h",
        require_1h_confirmation_when_4h_primary=True,
    )

    strict_engine = MACDStrategyV2Engine(MACDStrategyV2Config(**base_kwargs))
    light_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            **base_kwargs,
            light_1h_confirmation_when_4h_primary=True,
        )
    )

    analyze_kwargs = dict(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, -0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    strict_signal = strict_engine.analyze(**analyze_kwargs)
    light_signal = light_engine.analyze(**analyze_kwargs)

    assert strict_signal.direction == "neutral"
    assert "flip_bullish_disabled" in str(strict_signal.details.get("reason"))
    assert light_signal.direction == "neutral"
    assert "flip_bullish_disabled" in str(light_signal.details.get("reason"))


def test_promoted_trial_uses_stable_continuation_threshold() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.55,
            weight_4h_enhancement=0.0,
            weight_vwap=0.35,
            weight_15m_entry=0.05,
            weight_volume=0.20,
            min_signal_score=0.85,
            min_entry_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_soft_15m_confirmation_when_4h_primary=True,
            enable_4h_preflip_trial_entries=True,
            preflip_trial_min_shrink_pct_short=0.30,
            preflip_trial_min_signal_score=0.75,
            preflip_trial_min_vwap_score=0.06,
            preflip_trial_entry_scale=0.35,
            enable_trial_short_below_structure_continuation_promotion=True,
            trial_short_below_structure_promotion_min_signal_score=0.79,
            trial_short_below_structure_promotion_min_vwap_score=0.075,
            trial_short_below_structure_promotion_min_adx_1h=30.0,
            trial_short_below_structure_promotion_min_4h_shrink_pct=0.80,
            trial_short_below_structure_promotion_min_4h_shrink_bars=6,
            enable_stable_bear_continuation=True,
            stable_bear_continuation_min_signal_score=0.82,
            stable_bear_continuation_min_vwap_score=0.10,
            stable_bear_continuation_min_adx_1h=30.0,
            stable_bear_continuation_min_4h_bars=2,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.10, 0.05, -0.02, -0.08]),
        macd_hist_1h=np.array([0.20, 0.10, -0.05, -0.12]),
        macd_hist_4h=np.array([0.90, 1.20, 1.40, 1.50, 1.20, 0.90, 0.70, 0.50, 0.35, 0.25]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=9,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=99.45,
        close_price=99.5,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=100.0,
        bb_upper_4h=110.0,
        bb_lower_4h=90.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=99.5,
        adx_1h=35.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.signal_score == pytest.approx(0.7741666666666667, rel=1e-6)
    assert signal.direction == "short"
    assert signal.is_trial_entry is True
    assert signal.details["stable_continuation_active"] is False
    assert signal.details["stable_continuation_reason"] == "primary_mode_or_trial_not_eligible"
    assert signal.details["entry_type_15m"] == ""
    assert signal.details.get("threshold_source") is None


def test_preflip_zero_shrink_falls_back_to_primary_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.5,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.0,
            weight_volume=0.15,
            min_signal_score=0.1,
            min_entry_score=0.0,
            flip_bullish_min_signal_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_4h_preflip_trial_entries=True,
            preflip_trial_min_shrink_pct_long=0.75,
        )
    )

    monkeypatch.setattr(
        engine,
        "detect_1h_macd_direction",
        lambda hist, idx: (
            None,
            {
                "signal_type": "",
                "signal_strength": 0.0,
                "hist_current": float(hist[idx]),
                "hist_prev": float(hist[idx - 1]) if idx > 0 else float(hist[idx]),
            },
        ),
    )
    monkeypatch.setattr(
        engine,
        "detect_macd_direction",
        lambda hist, idx: (
            None,
            {
                "signal_type": "green_bar_shrinking",
                "signal_strength": 0.0,
                "hist_current": float(hist[idx]),
                "hist_prev": float(hist[idx - 1]) if idx > 0 else float(hist[idx]),
            },
        ),
    )
    monkeypatch.setattr(
        engine,
        "_build_4h_shrink_context",
        lambda hist, idx, signal_type: {
            "signal_type_4h": "green_bar_shrinking",
            "shrink_pct": 0.0,
            "shrink_bars": 0,
            "preflip_direction": "long",
            "exit_direction": "short",
            "shrink_exit_ready": False,
        },
    )
    monkeypatch.setattr(
        engine,
        "resolve_primary_direction",
        lambda **kwargs: ("long", None, {"fallback_primary_direction_used": True}),
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([0.40, 0.45, 0.45, 0.45]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        close_15m_series=np.array([99.0, 99.5, 100.0, 100.8]),
        close_1h_series=np.array([98.5, 99.0, 100.0, 101.0]),
        close_4h_series=np.array([97.0, 98.0, 99.0, 101.0]),
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.details["trade_direction"] == "long"
    assert signal.details["is_trial_entry"] is False
    assert signal.details["macd_4h_shrink_pct"] == pytest.approx(0.0, rel=1e-6)
    assert "4H预翻转缩短不足" not in str(signal.details.get("reason"))


def test_preflip_insufficient_shrink_falls_back_to_primary_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.5,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.0,
            weight_volume=0.15,
            min_signal_score=0.1,
            min_entry_score=0.0,
            flip_bullish_min_signal_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_4h_preflip_trial_entries=True,
            preflip_trial_min_shrink_pct_long=0.75,
        )
    )

    monkeypatch.setattr(
        engine,
        "detect_1h_macd_direction",
        lambda hist, idx: (
            None,
            {
                "signal_type": "",
                "signal_strength": 0.0,
                "hist_current": float(hist[idx]),
                "hist_prev": float(hist[idx - 1]) if idx > 0 else float(hist[idx]),
            },
        ),
    )
    monkeypatch.setattr(
        engine,
        "detect_macd_direction",
        lambda hist, idx: (
            None,
            {
                "signal_type": "green_bar_shrinking",
                "signal_strength": 0.0,
                "hist_current": float(hist[idx]),
                "hist_prev": float(hist[idx - 1]) if idx > 0 else float(hist[idx]),
            },
        ),
    )
    monkeypatch.setattr(
        engine,
        "_build_4h_shrink_context",
        lambda hist, idx, signal_type: {
            "signal_type_4h": "green_bar_shrinking",
            "shrink_pct": 0.20,
            "shrink_bars": 2,
            "preflip_direction": "long",
            "exit_direction": "short",
            "shrink_exit_ready": False,
        },
    )
    monkeypatch.setattr(
        engine,
        "resolve_primary_direction",
        lambda **kwargs: ("long", None, {"fallback_primary_direction_used": True}),
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([0.40, 0.45, 0.45, 0.45]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        close_15m_series=np.array([99.0, 99.5, 100.0, 100.8]),
        close_1h_series=np.array([98.5, 99.0, 100.0, 101.0]),
        close_4h_series=np.array([97.0, 98.0, 99.0, 101.0]),
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.details["trade_direction"] == "long"
    assert signal.details["macd_4h_shrink_pct"] == pytest.approx(0.20, rel=1e-6)
    assert signal.details["is_trial_entry"] is False
    assert "4H预翻转缩短不足" not in str(signal.details.get("reason"))


def test_evaluate_rsi_rhythm_long_spring_reports_weighted_trace() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_4h_direction=0.40,
            weight_1h_direction=0.15,
            weight_4h_enhancement=0.10,
            weight_rsi_rhythm=0.25,
            weight_vwap=0.10,
            weight_15m_entry=0.0,
            weight_volume=0.10,
            rsi_period=3,
        )
    )

    result = engine.evaluate_rsi_rhythm(
        direction="long",
        rsi_15m_series=np.array([31.0, 34.0, 43.0, 52.0], dtype=float),
        rsi_1h_series=np.array([41.0, 45.0, 49.0, 55.5], dtype=float),
        rsi_4h_series=np.array([48.0, 53.0, 58.5, 62.0], dtype=float),
        close_15m_series=np.array([100.0, 99.4, 99.0, 100.2, 101.5], dtype=float),
        close_1h_series=np.array([100.0, 99.8, 100.2, 101.1], dtype=float),
        close_4h_series=np.array([98.0, 98.5, 99.5, 100.8], dtype=float),
    )

    assert result["hard_veto"] is False
    assert result["entry_type"] == "rsi_spring"
    assert result["rsi_4h_regime"] == "supportive"
    assert result["rsi_1h_phase"] == "launch"
    assert result["raw_score"] > 0.70
    assert result["weighted_score"] == pytest.approx(result["raw_score"] * 0.25, rel=1e-6)
    assert result["exposure_mult"] == pytest.approx(1.2, rel=1e-6)


def test_calculate_portion_multiplier_keeps_mid_score_candidates_tradeable() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    assert engine.calculate_portion_multiplier(0.92) == pytest.approx(1.2, rel=1e-6)
    assert engine.calculate_portion_multiplier(0.82) == pytest.approx(1.0, rel=1e-6)
    assert engine.calculate_portion_multiplier(0.66) == pytest.approx(0.8, rel=1e-6)
    assert engine.calculate_portion_multiplier(0.60) == pytest.approx(0.6, rel=1e-6)
    assert engine.calculate_portion_multiplier(0.54) == pytest.approx(0.0, rel=1e-6)


def test_evaluate_rsi_rhythm_extreme_veto_blocks_without_price_breakout() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_rsi_rhythm=0.25,
            weight_15m_entry=0.0,
            rsi_period=3,
        )
    )

    result = engine.evaluate_rsi_rhythm(
        direction="long",
        rsi_15m_series=np.array([61.0, 69.0, 76.0, 78.0], dtype=float),
        rsi_1h_series=np.array([52.0, 55.0, 58.0, 60.0], dtype=float),
        rsi_4h_series=np.array([54.0, 57.0, 60.0, 61.0], dtype=float),
        close_15m_series=np.array([100.0, 101.0, 100.8, 100.7], dtype=float),
        close_1h_series=np.array([100.0, 100.6, 101.0, 101.3], dtype=float),
        close_4h_series=np.array([98.0, 99.5, 100.8, 101.4], dtype=float),
    )

    assert result["hard_veto"] is True
    assert result["veto_reason"] == "rsi_15m_extreme_veto"
    assert result["raw_score"] == pytest.approx(0.0, rel=1e-6)
    assert result["weighted_score"] == pytest.approx(0.0, rel=1e-6)


def test_resolve_signal_score_threshold_uses_family_specific_defaults() -> None:
    config = MACDStrategyV2Config()

    assert config.resolve_signal_score_threshold("flip_bullish") == pytest.approx(0.82, rel=1e-6)
    assert config.resolve_signal_score_threshold("flip_bearish") == pytest.approx(0.84, rel=1e-6)
    assert config.resolve_signal_score_threshold("red_bar_growing") == pytest.approx(0.90, rel=1e-6)
    assert config.resolve_signal_score_threshold("green_bar_growing") == pytest.approx(0.87, rel=1e-6)
    assert config.resolve_signal_score_threshold("unknown") == pytest.approx(0.85, rel=1e-6)


def test_classify_rsi_macd_conflict_uses_tiered_policy() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    leading = engine._classify_rsi_macd_conflict(
        trade_direction="long",
        direction_1h=None,
        direction_4h="long",
        score_rsi_rhythm_raw=0.55,
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_1h_phase": "launch",
            "rsi_1h_slope": 2.4,
            "probe_mode": False,
        },
    )
    divergence = engine._classify_rsi_macd_conflict(
        trade_direction="long",
        direction_1h="long",
        direction_4h="long",
        score_rsi_rhythm_raw=-0.25,
        rsi_rhythm={
            "entry_type": "rsi_neutral_resume",
            "rsi_1h_phase": "trend_health",
            "rsi_1h_slope": -0.4,
            "probe_mode": False,
        },
    )
    extreme = engine._classify_rsi_macd_conflict(
        trade_direction="long",
        direction_1h="long",
        direction_4h="long",
        score_rsi_rhythm_raw=-0.45,
        rsi_rhythm={
            "entry_type": "rsi_neutral_resume",
            "rsi_1h_phase": "divergence_warning",
            "rsi_1h_slope": -1.2,
            "probe_mode": True,
        },
    )

    assert leading["type"] == "leading"
    assert leading["score_penalty_mult"] == pytest.approx(1.0, rel=1e-6)
    assert leading["portion_penalty_mult"] == pytest.approx(0.80, rel=1e-6)
    assert divergence["type"] == "divergence"
    assert divergence["score_penalty_mult"] == pytest.approx(0.95, rel=1e-6)
    assert divergence["portion_penalty_mult"] == pytest.approx(0.85, rel=1e-6)
    assert extreme["type"] == "extreme_oppose"
    assert extreme["force_probe"] is True


def test_resolve_threshold_override_for_rsi_spring_relaunch() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_15m_spring_threshold_override=True,
            spring_override_min_signal_score=0.82,
            spring_override_score_bonus=0.10,
        )
    )

    override = engine._resolve_rsi_spring_threshold_override(
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_1h_phase": "launch",
            "rsi_1h_recent_low": 43.0,
            "rsi_1h_current": 52.0,
        },
    )

    assert override["applied"] is True
    assert override["threshold"] == pytest.approx(0.82, rel=1e-6)
    assert override["score_bonus"] == pytest.approx(0.10, rel=1e-6)


def test_flip_bullish_sniper_accepts_two_of_three_launch_confirmations() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_sniper(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_15m_recent_low": 31.0,
            "price_break_high": True,
        },
        rsi_1h_series=np.array([48.0, 51.0, 54.0, 56.0, 58.0, 60.0, 59.0, 57.0], dtype=float),
        macd_hist_4h=np.array([-0.10, 0.02, 0.05, 0.08], dtype=float),
        idx_4h=3,
    )

    assert result["applies"] is True
    assert result["passed"] is True
    assert result["reason"] == "qualified_launch"
    assert result["quality_matches"] == 2
    assert result["bonus_score"] == pytest.approx(0.02, rel=1e-6)


def test_flip_bullish_sniper_softens_missing_reset_into_small_penalty() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_sniper(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_15m_recent_low": 31.0,
            "price_break_high": True,
        },
        rsi_1h_series=np.array([48.0, 51.0, 54.0, 56.0, 58.0, 60.0, 59.0, 57.0], dtype=float),
        macd_hist_4h=np.array([-0.10, 0.02, 0.05, 0.08], dtype=float),
        idx_4h=3,
    )

    assert result["applies"] is True
    assert result["passed"] is True
    assert result["reason"] == "qualified_launch"
    assert result["momentum_reset_found"] is False
    assert result["spring_confirmed"] is True
    assert result["trend_aligned"] is True
    assert result["bonus_score"] == pytest.approx(0.02, rel=1e-6)


def test_flip_bullish_sniper_passes_and_grants_perfect_bonus() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_sniper(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_15m_recent_low": 29.0,
            "price_break_high": True,
        },
        rsi_1h_series=np.array([52.0, 47.0, 41.0, 38.0, 44.0, 49.0, 52.0, 55.0], dtype=float),
        macd_hist_4h=np.array([-0.10, 0.02, 0.05, 0.08], dtype=float),
        idx_4h=3,
    )

    assert result["passed"] is True
    assert result["reason"] == "perfect_launch"
    assert result["quality_matches"] == 3
    assert result["bonus_score"] == pytest.approx(0.08, rel=1e-6)


def test_flip_bullish_sniper_rejects_weak_launch_profile() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_sniper(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "",
            "rsi_15m_recent_low": 48.0,
        },
        rsi_1h_series=np.array([48.0, 50.0, 53.0, 55.0, 56.0, 57.0, 58.0, 59.0], dtype=float),
        macd_hist_4h=np.array([-0.10, -0.05, -0.02, -0.01], dtype=float),
        idx_4h=3,
    )

    assert result["applies"] is True
    assert result["passed"] is False
    assert result["reason"] == "no_trend_alignment"


def test_flip_bullish_cooling_rejects_overheated_non_spring_launch() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_cooling(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_extreme_block",
            "rsi_1h_current": 76.0,
            "rsi_15m_current": 61.0,
        },
    )

    assert result["applies"] is True
    assert result["passed"] is False
    assert result["reason"] == "overheated_launch"


def test_flip_bullish_cooling_allows_spring_like_high_rsi_launch() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_cooling(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "rsi_spring",
            "rsi_1h_current": 74.0,
            "rsi_15m_current": 67.0,
        },
    )

    assert result["applies"] is True
    assert result["passed"] is True
    assert result["reason"] == "passed"
    assert result["score_multiplier"] == pytest.approx(1.0, rel=1e-6)


def test_flip_bullish_cooling_softens_mildly_overheated_non_spring_launch() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_cooling(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "",
            "rsi_1h_current": 73.0,
            "rsi_15m_current": 61.0,
        },
    )

    assert result["applies"] is True
    assert result["passed"] is True
    assert result["reason"] == "soft_launch_profile"
    assert result["score_multiplier"] == pytest.approx(0.90, rel=1e-6)


def test_flip_bullish_cooling_rejects_high_15m_rsi_without_spring() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_cooling(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": "",
            "rsi_1h_current": 63.0,
            "rsi_15m_current": 67.0,
        },
    )

    assert result["applies"] is True
    assert result["passed"] is False
    assert result["reason"] == "no_spring_high_rsi"
    assert result["score_multiplier"] == pytest.approx(1.0, rel=1e-6)


def test_analyze_vwap_hard_block_only_triggers_beyond_3pct_deviation() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.15,
            weight_4h_direction=0.40,
            weight_4h_enhancement=0.0,
            weight_rsi_rhythm=0.25,
            weight_vwap=0.0,
            weight_15m_entry=0.0,
            weight_volume=0.20,
            min_signal_score=0.10,
            min_entry_score=0.10,
            flip_bullish_min_signal_score=0.10,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_sniper=False,
            enable_flip_bullish_cooling=False,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
        )
    )

    analyze_kwargs = dict(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=100.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=102.5,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    slight_deviation_signal = engine.analyze(
        close_price=102.5,
        **analyze_kwargs,
    )
    hard_block_signal = engine.analyze(
        close_price=103.5,
        **analyze_kwargs,
    )

    assert slight_deviation_signal.direction == "long"
    assert hard_block_signal.direction == "neutral"
    assert hard_block_signal.veto_type is not None
    assert hard_block_signal.veto_type.value == "vwap_hard_block"


def test_analyze_volume_vwap_warn_does_not_block_high_score_signal() -> None:
    config = MACDStrategyV2Config(
        weight_1h_direction=0.15,
        weight_4h_direction=0.40,
        weight_4h_enhancement=0.0,
        weight_rsi_rhythm=0.25,
        weight_vwap=0.05,
        weight_15m_entry=0.0,
        weight_volume=0.10,
        min_signal_score=0.10,
        min_entry_score=0.10,
        flip_bullish_min_signal_score=0.10,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_sniper=False,
        enable_flip_bullish_cooling=False,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=False,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="4h",
    )
    config.vol_vwap_warn_min_score_vol = 0.05
    config.vol_vwap_warn_min_vwap_score = 0.10
    engine = MACDStrategyV2Engine(config)

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=0.7,
        vwap=100.0,
        structural_vwap=100.0,
        close_price=100.6,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.6,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.veto_type is not None
    assert signal.veto_type.value == "none"
    assert signal.details["vol_vwap_warn"] is True
    assert signal.details["score_volume"] == pytest.approx(0.033, abs=1e-6)
    assert signal.details["vwap_score"] <= 0.10


def test_analyze_low_score_vol_vwap_warn_still_reaches_threshold_check() -> None:
    config = MACDStrategyV2Config(
        weight_1h_direction=0.0,
        weight_4h_direction=0.0,
        weight_4h_enhancement=0.0,
        weight_rsi_rhythm=0.0,
        weight_vwap=0.0,
        weight_15m_entry=0.0,
        weight_volume=0.10,
        min_signal_score=0.68,
        min_entry_score=0.68,
        red_bar_growing_min_signal_score=0.68,
        flip_bullish_min_signal_score=0.68,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_sniper=False,
        enable_flip_bullish_cooling=False,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=False,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="4h",
    )
    config.vol_vwap_warn_min_score_vol = 0.05
    config.vol_vwap_warn_min_vwap_score = 0.10
    engine = MACDStrategyV2Engine(config)

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.05]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=0.7,
        vwap=100.0,
        structural_vwap=100.0,
        close_price=100.6,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.6,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert signal.veto_type is not None
    assert signal.veto_type.value != "volume_vwap_both_low"
    assert signal.details["stage"] == "threshold_check"
    assert signal.details["vol_vwap_warn"] is True
    assert signal.details["reason"].startswith("信号评分低于阈值")


def test_flip_bullish_strict_filter_softens_into_score_penalty() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._evaluate_flip_bullish_strict_filter(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        entry_type_15m="",
        entry_refine_15m="",
        vwap_score=0.05,
    )

    assert result["applies"] is True
    assert result["passed"] is True
    assert result["score_multiplier"] == pytest.approx(0.85, rel=1e-6)
    assert result["reasons"] == [
        "15m_entry=none",
        "15m_refine=none",
        "vwap_score=0.05<0.12",
    ]


@pytest.mark.parametrize("entry_type", ["rsi_spring", "rsi_neutral_resume"])
def test_flip_bullish_spring_weight_floor_applies_for_valid_launches(entry_type: str) -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._resolve_flip_bullish_rsi_spring_weight_floor(
        signal_type_1h="flip_bullish",
        trade_direction="long",
        rsi_rhythm={
            "entry_type": entry_type,
            "rsi_1h_phase": "launch",
            "price_break_high": True,
        },
        score_rsi_rhythm_weighted=0.08,
    )

    assert result["applied"] is True
    assert result["rsi_spring_weighted_floor_applied"] is True
    assert result["rsi_spring_weighted_floor_value"] == pytest.approx(0.20, rel=1e-6)
    assert result["score_rsi_rhythm_weighted"] == pytest.approx(0.20, rel=1e-6)


def test_evaluate_neutral_upgrade_tiers_strong_and_probe_modes() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    strong = engine._evaluate_neutral_upgrade(
        neutral_upgrade_candidate="long",
        neutral_upgrade_raw=0.36,
        hard_veto=False,
    )
    probe = engine._evaluate_neutral_upgrade(
        neutral_upgrade_candidate="long",
        neutral_upgrade_raw=0.24,
        hard_veto=False,
    )
    weak = engine._evaluate_neutral_upgrade(
        neutral_upgrade_candidate="long",
        neutral_upgrade_raw=0.12,
        hard_veto=False,
    )

    assert strong["applied"] is True
    assert strong["mode"] == "full"
    assert strong["probe_mode"] is False
    assert strong["threshold_override"] == pytest.approx(0.82, rel=1e-6)
    assert probe["applied"] is True
    assert probe["mode"] == "probe"
    assert probe["probe_mode"] is True
    assert probe["threshold_override"] == pytest.approx(0.82, rel=1e-6)
    assert weak["applied"] is False
    assert weak["mode"] == "reject"


def test_rsi_conflict_downshifts_leverage_and_portion() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_rsi_rhythm=0.25,
            min_signal_score=0.85,
            enable_red_bar_growing_probe_overlay=False,
        )
    )

    leverage = engine.calculate_leverage(
        0.90,
        ema_multiplier=1.0,
        signal_type_1h="red_bar_growing",
        rsi_conflict=True,
    )
    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.20,
        base_max_symbol_position_portion=0.30,
        signal_type_1h="red_bar_growing",
        rsi_exposure_mult=0.5,
        rsi_conflict=True,
        rsi_conflict_portion_mult=0.85,
    )

    assert leverage == 3
    assert portion == pytest.approx(0.102, rel=1e-6)


def test_red_bar_growing_overlay_forces_probe_sizing_and_leverage_cap() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_red_bar_growing_probe_overlay=True,
            red_bar_growing_probe_position_penalty=0.50,
            red_bar_growing_probe_max_leverage=2,
            rsi_probe_portion_scale=0.25,
        )
    )

    leverage = engine.calculate_leverage(
        0.90,
        ema_multiplier=1.0,
        signal_type_1h="red_bar_growing",
    )
    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.20,
        base_max_symbol_position_portion=0.30,
        signal_type_1h="red_bar_growing",
        rsi_exposure_mult=1.0,
    )

    assert leverage == 2
    assert portion == pytest.approx(0.03, rel=1e-6)


def test_green_bar_growing_overlay_forces_micro_probe_sizing_and_leverage_cap() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_green_bar_growing_probe_overlay=True,
            green_bar_growing_probe_position_penalty=0.40,
            green_bar_growing_probe_max_leverage=2,
            rsi_probe_portion_scale=0.25,
        )
    )

    leverage = engine.calculate_leverage(
        0.90,
        ema_multiplier=1.0,
        signal_type_1h="green_bar_growing",
    )
    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.20,
        base_max_symbol_position_portion=0.30,
        signal_type_1h="green_bar_growing",
        rsi_exposure_mult=1.0,
    )

    assert leverage == 2
    assert portion == pytest.approx(0.024, rel=1e-6)


def test_rsi_exposure_multiplier_uses_probe_tier_below_block_threshold() -> None:
    assert MACDStrategyV2Engine._resolve_rsi_exposure_multiplier(-0.31) == pytest.approx(0.20, rel=1e-6)


def test_flip_signals_skip_vwap_score_floor_when_exemption_enabled() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.10,
            preflip_trial_min_vwap_score=0.06,
            enable_vwap_flip_exemption=True,
        )
    )

    assert engine._resolve_min_vwap_score_for_entry(
        signal_type_1h="flip_bullish",
        is_trial_entry=False,
    ) == pytest.approx(0.0, rel=1e-6)
    assert engine._resolve_min_vwap_score_for_entry(
        signal_type_1h="green_bar_growing",
        is_trial_entry=False,
    ) == pytest.approx(0.10, rel=1e-6)


def test_calculate_position_portion_applies_priority_bonus_and_probe_scale() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_priority_allocation=True,
            priority_allocation_overdraft_pct=0.08,
            rsi_probe_portion_scale=0.25,
        )
    )

    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        signal_type_1h="flip_bullish",
        vwap_state="long_dual_support",
        rsi_exposure_mult=0.20,
        rsi_probe_mode=True,
    )

    assert portion == pytest.approx(0.034, rel=1e-6)


def test_priority_flip_bullish_uses_slower_4h_shrink_exit_policy() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_priority_signal_shrink_exit=True,
            priority_signal_shrink_exit_required_bars=3,
            priority_signal_shrink_exit_required_pct=0.40,
            exit_4h_shrink_bars=2,
            exit_4h_min_shrink_pct=0.20,
        )
    )

    policy = engine.resolve_4h_shrink_exit_policy(
        signal_details={
            "signal_type_1h": "flip_bullish",
            "priority_signal": True,
            "vwap_state": "long_dual_support",
            "shrink_exit_direction": "LONG",
            "macd_4h_shrink_pct": 0.25,
            "macd_4h_shrink_bars": 2,
        },
        position_side="LONG",
    )

    assert policy["mode"] == "priority_signal_slow"
    assert policy["required_bars"] == 3
    assert policy["required_pct"] == pytest.approx(0.40, rel=1e-6)
    assert policy["active"] is False


def test_vwap_score_filter_uses_distinct_reason_code() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.55,
            weight_4h_enhancement=0.0,
            weight_vwap=0.20,
            weight_15m_entry=0.05,
            weight_volume=0.20,
            min_signal_score=0.82,
            min_entry_score=0.1,
            min_vwap_score_for_entry=0.10,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_soft_15m_confirmation_when_4h_primary=True,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.08]),
        macd_hist_1h=np.array([0.10, 0.15, 0.20, 0.25]),
        macd_hist_4h=np.array([0.10, 0.15, 0.20, 0.25]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=100.05,
        close_price=100.12,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.12,
        adx_1h=20.0,
        adx_4h=22.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert signal.veto_type.value == "vwap_score_filter"
    assert signal.details["reject_stage"] == "vwap_score_filter"
    assert signal.details["reject_reason_code"] == "vwap_score_filter"
    assert "vwap_score_filter(" in signal.details["reason"]


def test_soft_long_threshold_override_only_affects_soft_long_entries() -> None:
    config = MACDStrategyV2Config(
        min_signal_score=0.85,
        red_bar_growing_min_signal_score=0.82,
        soft_long_min_signal_score=0.80,
    )

    threshold, source = config.resolve_entry_threshold(
        signal_type="red_bar_growing",
        entry_type_15m="soft_long_recovery",
        primary_mode="4h",
        is_trial_entry=False,
        stable_continuation_active=False,
        stable_continuation_side=None,
    )
    short_threshold, short_source = config.resolve_entry_threshold(
        signal_type="red_bar_growing",
        entry_type_15m="soft_short_recovery",
        primary_mode="4h",
        is_trial_entry=False,
        stable_continuation_active=False,
        stable_continuation_side=None,
    )

    assert threshold == pytest.approx(0.80, rel=1e-6)
    assert source == "soft_long_override(primary_4h_red_bar_growing)"
    assert short_threshold == pytest.approx(0.82, rel=1e-6)
    assert short_source == "primary_4h_red_bar_growing"


def test_neutral_signal_carries_4h_shrink_exit_metadata() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.5,
            weight_4h_enhancement=0.0,
            weight_vwap=0.20,
            weight_15m_entry=0.15,
            weight_volume=0.15,
            min_signal_score=0.85,
            min_entry_score=0.1,
            min_vwap_score_for_entry=0.12,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_4h_preflip_trial_entries=True,
            enable_4h_shrink_exit=True,
            exit_4h_shrink_bars=2,
            exit_4h_min_shrink_pct=0.20,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.20, 0.16, 0.12, 0.08]),
        macd_hist_1h=np.array([0.30, 0.24, 0.18, 0.12]),
        macd_hist_4h=np.array([0.90, 1.20, 1.40, 1.50, 1.40, 1.20, 1.00, 0.82, 0.70, 0.58]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=9,
        volume_ratio=1.1,
        vwap=100.0,
        structural_vwap=100.5,
        close_price=99.8,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=101.0,
        bb_upper_4h=111.0,
        bb_lower_4h=91.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=99.8,
        adx_1h=18.0,
        adx_4h=20.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert signal.details["shrink_exit_direction"] == "long"
    assert signal.details["shrink_exit_ready"] is True


def test_green_bar_growing_short_adx_range_filter_blocks_full_size() -> None:
    base_kwargs = dict(
        weight_1h_direction=0.5,
        weight_4h_direction=0.0,
        weight_4h_enhancement=0.0,
        weight_vwap=0.0,
        weight_15m_entry=0.15,
        weight_volume=0.15,
        min_signal_score=0.1,
        green_bar_growing_min_signal_score=0.1,
        flip_bullish_min_signal_score=0.1,
        min_entry_score=0.1,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_sniper=False,
        enable_flip_bullish_cooling=False,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=False,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="1h",
    )

    plain_engine = MACDStrategyV2Engine(MACDStrategyV2Config(**base_kwargs))
    filtered_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            **base_kwargs,
            enable_green_bar_growing_short_adx_1h_range_filter=True,
            green_bar_growing_short_min_adx_1h=25.0,
            green_bar_growing_short_max_adx_1h=30.0,
        )
    )

    analyze_kwargs = dict(
        macd_hist_15m=np.array([0.10, 0.05, -0.03, -0.08]),
        macd_hist_1h=np.array([-0.01, -0.02, -0.05, -0.10]),
        macd_hist_4h=np.array([-0.02, -0.04, -0.08, -0.12]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=99.5,
        structural_vwap=100.0,
        close_price=99.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=100.0,
        bb_upper_4h=110.0,
        bb_lower_4h=90.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=99.2,
        adx_1h=27.0,
        adx_4h=24.0,
        atr_1h=1.0,
    )

    plain_signal = plain_engine.analyze(**analyze_kwargs)
    filtered_signal = filtered_engine.analyze(**analyze_kwargs)

    assert plain_signal.direction == "short"
    assert filtered_signal.direction == "neutral"
    assert "green_bar_growing_short_adx_1h_range_filter" in str(filtered_signal.details.get("reason"))


def test_flip_bullish_cvd_context_filter_blocks_full_size() -> None:
    base_kwargs = dict(
        weight_1h_direction=0.5,
        weight_4h_direction=0.0,
        weight_4h_enhancement=0.0,
        weight_vwap=0.0,
        weight_15m_entry=0.15,
        weight_volume=0.15,
        min_signal_score=0.1,
        flip_bullish_min_signal_score=0.1,
        min_entry_score=0.1,
        min_vwap_score_for_entry=0.0,
        overheat_growing_penalty=0.0,
        enable_flip_bullish_sniper=False,
        enable_flip_bullish_cooling=False,
        enable_flip_bullish_strict_filter=False,
        disable_flip_bullish_entries=False,
        disable_green_bar_growing_entries=False,
        primary_direction_timeframe="1h",
    )

    plain_engine = MACDStrategyV2Engine(MACDStrategyV2Config(**base_kwargs))
    filtered_engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            **base_kwargs,
            enable_flip_bullish_cvd_context_filter=True,
            flip_bullish_max_cvd_upper_wick_ratio=0.20,
            flip_bullish_min_cvd_1h_delta_ratio=0.03,
        )
    )

    analyze_kwargs = dict(
        macd_hist_15m=np.array([-0.10, -0.05, 0.03, 0.08]),
        macd_hist_1h=np.array([-0.08, -0.04, -0.02, 0.06]),
        macd_hist_4h=np.array([-0.10, -0.05, 0.04, 0.09]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.5,
        structural_vwap=100.0,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.5,
        bb_upper_4h=109.5,
        bb_lower_4h=89.5,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        adx_1h=28.0,
        adx_4h=24.0,
        cvd_upper_wick_ratio=0.25,
        cvd_1h_delta_ratio=0.01,
        atr_1h=1.0,
    )

    plain_signal = plain_engine.analyze(**analyze_kwargs)
    filtered_signal = filtered_engine.analyze(**analyze_kwargs)

    assert plain_signal.direction == "long"
    assert filtered_signal.direction == "neutral"
    assert "flip_bullish_cvd_context_filter" in str(filtered_signal.details.get("reason"))


def test_session_risk_position_scale_matches_target_states() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            session_risk_control_enabled=True,
            session_risk_high_risk_sessions=[
                {"utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65}
            ],
            session_risk_apply_to_states=["short_dual_pressure", "flip_bullish"],
        )
    )

    in_window = datetime(2026, 3, 21, 15, 0, tzinfo=timezone.utc)
    out_window = datetime(2026, 3, 21, 17, 0, tzinfo=timezone.utc)

    assert engine.resolve_session_position_scale(in_window, signal_type_1h="flip_bullish") == pytest.approx(0.65, rel=1e-6)
    assert engine.resolve_session_position_scale(in_window, signal_type_1h="green_bar_growing", vwap_state="short_dual_pressure") == pytest.approx(0.65, rel=1e-6)
    assert engine.resolve_session_position_scale(in_window, signal_type_1h="green_bar_growing", vwap_state="long_bias") == pytest.approx(1.0, rel=1e-6)
    assert engine.resolve_session_position_scale(out_window, signal_type_1h="flip_bullish") == pytest.approx(1.0, rel=1e-6)


def test_calculate_position_portion_applies_session_scale_after_trial_scale() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        is_trial_entry=True,
        entry_scale=0.35,
        session_scale=0.65,
    )

    assert portion == pytest.approx(0.60 * 0.35 * 0.65, rel=1e-6)


def test_green_bar_growing_probe_overlay_caps_leverage_and_base_portion() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_green_bar_growing_probe_overlay=True,
            green_bar_growing_probe_position_penalty=0.10,
            green_bar_growing_probe_max_leverage=2,
        )
    )

    leverage = engine.calculate_leverage(
        score=0.85,
        ema_multiplier=1.0,
        signal_type_1h="green_bar_growing",
        symbol="SOLUSDT",
        rsi_probe_mode=False,
    )
    portion = engine.calculate_position_portion(
        score=0.80,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        signal_type_1h="green_bar_growing",
        vwap_state="short_dual_pressure",
        rsi_probe_mode=False,
    )

    assert leverage == 2
    assert portion == pytest.approx(0.06, rel=1e-6)


def test_watchlist_symbol_risk_caps_leverage_and_session_scaled_portion() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            symbol_risk_watchlist_symbols=["LINKUSDT"],
            symbol_risk_watchlist_max_position_portion=0.40,
            symbol_risk_watchlist_max_leverage=2,
            symbol_risk_watchlist_apply_session_scale_double=True,
            symbol_risk_watchlist_session_scale_multiplier=0.80,
            dual_pressure_target_portion_bonus=0.08,
            dual_pressure_max_symbol_position_portion=0.68,
        )
    )

    leverage = engine.calculate_leverage(
        score=0.90,
        ema_multiplier=1.0,
        signal_type_1h="green_bar_growing",
        symbol="LINKUSDT",
    )
    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        symbol="LINKUSDT",
        vwap_state="short_dual_pressure",
        session_scale=0.65,
    )

    assert leverage == 2
    assert portion == pytest.approx(0.40 * (0.65 * 0.80), rel=1e-6)


def test_non_watchlist_symbol_keeps_original_dual_pressure_cap() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            symbol_risk_watchlist_symbols=["LINKUSDT"],
            symbol_risk_watchlist_max_position_portion=0.40,
            dual_pressure_target_portion_bonus=0.08,
            dual_pressure_max_symbol_position_portion=0.68,
        )
    )

    portion = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        symbol="SOLUSDT",
        vwap_state="short_dual_pressure",
        session_scale=1.0,
    )

    assert portion == pytest.approx(0.68, rel=1e-6)


def test_vwap_score_position_tiers_apply_only_to_target_states() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_score_tier_apply_to_states=["short_dual_pressure", "flip_bullish"],
            enable_red_bar_growing_probe_overlay=False,
            enable_green_bar_growing_probe_overlay=False,
            vwap_score_position_tiers=[
                {"min": 0.12, "max": 0.20, "position_mult": 0.80},
                {"min": 0.20, "max": 0.30, "position_mult": 1.00},
                {"min": 0.30, "max": 1.00, "position_mult": 1.15},
            ],
        )
    )

    weak_dual_pressure = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        signal_type_1h="green_bar_growing",
        vwap_score=0.15,
        vwap_state="short_dual_pressure",
    )
    strong_flip = engine.calculate_position_portion(
        score=0.85,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        signal_type_1h="flip_bullish",
        vwap_score=0.35,
        vwap_state="long_reclaim_confirmed",
    )
    untouched = engine.calculate_position_portion(
        score=0.90,
        base_default_portion=0.60,
        base_max_symbol_position_portion=0.60,
        signal_type_1h="red_bar_growing",
        vwap_score=0.35,
        vwap_state="long_dual_support",
    )

    assert weak_dual_pressure == pytest.approx(0.60 * 0.80, rel=1e-6)
    assert strong_flip == pytest.approx(0.60, rel=1e-6)
    assert untouched == pytest.approx(0.60, rel=1e-6)


def test_check_15m_macd_follow_prefers_rsi_spring_refinement_for_long() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            rsi_period=5,
            enable_rsi_entry_refinement=True,
            rsi_spring_recent_extreme_lookback=6,
            rsi_spring_recent_oversold=35.0,
            rsi_spring_prev_max=50.0,
            rsi_spring_confirm=50.0,
            rsi_1h_long_support=52.0,
        )
    )

    can_enter, entry_score, details = engine.check_15m_macd_follow(
        macd_hist_15m=np.array([-0.10, 0.02, 0.08]),
        idx=2,
        direction="long",
        close_15m=98.0,
        close_15m_series=np.array([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 92, 96], dtype=float),
        close_1h_series=np.array([100, 101, 102, 101, 103, 104, 105, 106, 107, 108, 109, 110], dtype=float),
    )

    assert can_enter is True
    assert details["entry_type"] == "red_bar_growing"
    assert details["ema_15m_refine"] == "rsi_spring"
    assert entry_score > 0.85


def test_analyze_blocks_rsi_extreme_short_path_with_hard_veto() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.55,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
                weight_15m_entry=0.0,
                weight_volume=0.15,
                min_signal_score=0.1,
                min_entry_score=0.1,
                min_vwap_score_for_entry=0.0,
                overheat_growing_penalty=0.0,
                primary_direction_timeframe="4h",
                require_1h_confirmation_when_4h_primary=True,
                allow_neutral_1h_confirmation=True,
                disable_green_bar_shrinking_short_dual_pressure_entries=False,
                rsi_period=3,
            )
        )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.00020, 0.00010, 0.00005, 0.0]),
        macd_hist_1h=np.array([-0.35, -0.30, -0.25, -0.20]),
        macd_hist_4h=np.array([0.10, -0.02, -0.08, -0.14]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=99.6,
        close_price=99.2,
        bb_middle_1h=100.0,
        bb_upper_1h=106.0,
        bb_lower_1h=94.0,
        bb_middle_4h=100.0,
        bb_upper_4h=106.0,
        bb_lower_4h=94.0,
        bb_middle_15m=99.5,
        bb_upper_15m=100.5,
        bb_lower_15m=98.5,
        close_15m=99.2,
        close_15m_series=np.array([100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 101.0], dtype=float),
        close_1h_series=np.array([100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 101.0], dtype=float),
        close_4h_series=np.array([100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 101.0], dtype=float),
        adx_1h=30.0,
        adx_4h=24.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert signal.details["reason"] == "rsi_15m_extreme_veto"
    assert signal.details["entry_type_15m"] == "rsi_extreme_block"
    assert signal.details["rsi_hard_veto"] is True


def test_analyze_skips_weak_combo_veto_when_disabled() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.55,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.15,
            weight_volume=0.15,
            min_signal_score=0.1,
            min_entry_score=0.1,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            disable_green_bar_shrinking_short_dual_pressure_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            enable_soft_15m_confirmation_when_4h_primary=True,
            enable_rsi_entry_refinement=False,
            enable_weak_combo_veto=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.00020, 0.00010, 0.00005, 0.0]),
        macd_hist_1h=np.array([-0.35, -0.30, -0.25, -0.20]),
        macd_hist_4h=np.array([0.10, -0.02, -0.08, -0.14]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=99.6,
        close_price=99.2,
        bb_middle_1h=100.0,
        bb_upper_1h=106.0,
        bb_lower_1h=94.0,
        bb_middle_4h=100.0,
        bb_upper_4h=106.0,
        bb_lower_4h=94.0,
        bb_middle_15m=99.5,
        bb_upper_15m=100.5,
        bb_lower_15m=98.5,
        close_15m=99.2,
        close_15m_series=np.array([99.8, 99.6, 99.4, 99.3, 99.2], dtype=float),
        close_1h_series=np.array([101.0, 100.7, 100.3, 99.8, 99.4, 99.2], dtype=float),
        close_4h_series=np.array([103.0, 102.0, 101.0, 100.0, 99.6, 99.2], dtype=float),
        adx_1h=30.0,
        adx_4h=24.0,
        atr_1h=1.0,
    )

    assert signal.details.get("reject_reason_code") != "weak_combo_veto"


def test_rsi_launch_sovereign_mode_applies_to_long_flip_bullish() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    sovereign = engine._evaluate_rsi_launch_sovereign_mode(
        trade_direction="long",
        signal_type_1h="flip_bullish",
        signal_type_4h="flip_bullish",
        macd_hist_4h_current=0.20,
        rsi_context={
            "refine": "rsi_spring",
            "rsi_1h": 61.0,
            "rsi_4h": 56.0,
            "price_break_high": True,
            "price_break_low": False,
            "rsi_1h_recent_reset_min": 42.0,
            "rsi_1h_recent_reset_max": 61.0,
        },
    )

    assert sovereign["applied"] is True
    assert sovereign["rsi_launch_sovereign_active"] is True
    assert sovereign["direction"] == "long"
    assert sovereign["rsi_launch_sovereign_side"] == "long"
    assert sovereign["score_bonus"] == pytest.approx(0.12, rel=1e-6)
    assert sovereign["threshold_override"] == pytest.approx(0.80, rel=1e-6)
    assert sovereign["competition_multiplier"] == pytest.approx(1.15, rel=1e-6)
    assert sovereign["priority_execution_applied"] is True


def test_rsi_launch_sovereign_mode_applies_to_short_flip_bearish_symmetrically() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    sovereign = engine._evaluate_rsi_launch_sovereign_mode(
        trade_direction="short",
        signal_type_1h="flip_bearish",
        signal_type_4h="flip_bearish",
        macd_hist_4h_current=-0.22,
        rsi_context={
            "refine": "rsi_reject",
            "rsi_1h": 34.0,
            "rsi_4h": 44.0,
            "price_break_high": False,
            "price_break_low": True,
            "rsi_1h_recent_reset_min": 34.0,
            "rsi_1h_recent_reset_max": 64.0,
        },
    )

    assert sovereign["applied"] is True
    assert sovereign["rsi_launch_sovereign_active"] is True
    assert sovereign["direction"] == "short"
    assert sovereign["rsi_launch_sovereign_side"] == "short"
    assert sovereign["priority_execution_applied"] is True
    assert sovereign["competition_multiplier"] == pytest.approx(1.15, rel=1e-6)


def test_rsi_launch_sovereign_mode_does_not_apply_without_price_break() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    sovereign = engine._evaluate_rsi_launch_sovereign_mode(
        trade_direction="long",
        signal_type_1h="flip_bullish",
        signal_type_4h="flip_bullish",
        macd_hist_4h_current=0.20,
        rsi_context={
            "refine": "rsi_spring",
            "rsi_1h": 61.0,
            "rsi_4h": 56.0,
            "price_break_high": False,
            "price_break_low": False,
            "rsi_1h_recent_reset_min": 42.0,
            "rsi_1h_recent_reset_max": 61.0,
        },
    )

    assert sovereign["applied"] is False
    assert sovereign["rsi_launch_sovereign_active"] is False
    assert sovereign["priority_execution_applied"] is False
    assert sovereign["competition_multiplier"] == pytest.approx(1.0, rel=1e-6)


def test_rsi_launch_sovereign_mode_requires_true_spring_refine() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    sovereign = engine._evaluate_rsi_launch_sovereign_mode(
        trade_direction="long",
        signal_type_1h="flip_bullish",
        signal_type_4h="flip_bullish",
        macd_hist_4h_current=0.20,
        rsi_context={
            "refine": "rsi_neutral_resume",
            "rsi_1h": 61.0,
            "rsi_4h": 56.0,
            "price_break_high": True,
            "price_break_low": False,
            "rsi_1h_recent_reset_min": 42.0,
            "rsi_1h_recent_reset_max": 61.0,
        },
    )

    assert sovereign["applied"] is False
    assert sovereign["rsi_launch_sovereign_active"] is False
    assert sovereign["rsi_launch_sovereign_reason"] == "long_refine_not_eligible"


def test_analyze_applies_long_sovereign_metadata_without_forced_swap() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.45,
            weight_4h_enhancement=0.0,
            weight_vwap=0.0,
            weight_15m_entry=0.10,
            weight_volume=0.20,
            min_signal_score=0.90,
            min_entry_score=0.10,
            min_vwap_score_for_entry=0.0,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            enable_rsi_entry_refinement=True,
            rsi_period=5,
            rsi_spring_recent_extreme_lookback=6,
            rsi_spring_recent_oversold=35.0,
            rsi_spring_prev_max=50.0,
            rsi_spring_confirm=50.0,
            rsi_1h_long_support=52.0,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.10, -0.05, 0.02, 0.08]),
        macd_hist_1h=np.array([-0.20, -0.10, -0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=99.8,
        close_price=101.0,
        bb_middle_1h=100.0,
        bb_upper_1h=110.0,
        bb_lower_1h=90.0,
        bb_middle_4h=99.0,
        bb_upper_4h=109.0,
        bb_lower_4h=89.0,
        bb_middle_15m=100.0,
        bb_upper_15m=103.0,
        bb_lower_15m=97.0,
        close_15m=100.8,
        close_15m_series=np.array([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 92, 96], dtype=float),
        close_1h_series=np.array([100, 98, 96, 95, 94, 95, 94, 96, 95, 97, 96, 98], dtype=float),
        close_4h_series=np.array([90, 91, 92, 94, 96, 95, 97, 96, 98, 97, 99, 100], dtype=float),
        adx_1h=22.0,
        adx_4h=24.0,
        atr_1h=1.0,
    )

    assert signal.direction == "long"
    assert signal.signal_score >= 0.80
    assert signal.details["rsi_launch_sovereign_applied"] is True
    assert signal.details["rsi_launch_sovereign_active"] is True
    assert signal.details["rsi_launch_sovereign_side"] == "long"
    assert signal.details["priority_execution_applied"] is True
    assert signal.details["priority_signal"] is True
    assert signal.details["competition_score"] > signal.signal_score
    assert signal.details["signal_score_threshold"] == pytest.approx(0.80, rel=1e-6)
    assert signal.details["final_leverage_after_rsi"] == pytest.approx(1.0, rel=1e-6)
    assert signal.details["final_portion_after_rsi"] == pytest.approx(1.0, rel=1e-6)
    assert "force_flat" not in signal.details
    assert "strong_flat" not in signal.details
