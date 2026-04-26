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


def test_light_1h_confirmation_skips_flip_bullish_disable_filter() -> None:
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
    assert light_signal.direction == "long"


def test_preflip_trial_entry_allows_4h_green_shrinking_long() -> None:
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
            preflip_trial_min_shrink_pct_long=0.75,
            preflip_trial_min_signal_score=0.78,
            preflip_trial_min_vwap_score=0.06,
            preflip_trial_entry_scale=0.35,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_1h=np.array([-0.30, -0.18, -0.08, 0.12]),
        macd_hist_4h=np.array([-0.90, -1.20, -1.40, -1.50, -1.40, -1.20, -0.90, -0.70, -0.50, -0.35]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=9,
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
    assert signal.is_trial_entry is True
    assert signal.entry_scale == pytest.approx(0.35, rel=1e-6)
    assert signal.signal_score >= 0.78
    assert signal.details["macd_4h_shrink_pct"] >= 0.75


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

    assert signal.signal_score == pytest.approx(0.8167, rel=1e-4)
    assert signal.direction == "neutral"
    assert signal.is_trial_entry is True
    assert signal.details["stable_continuation_active"] is True
    assert signal.details["stable_continuation_reason"] == "trial_short_below_structure_promoted"
    assert signal.details["signal_score_threshold"] == pytest.approx(0.82, rel=1e-6)
    assert signal.details["threshold_source"] == "stable_continuation_short"


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


def test_soft_15m_confirmation_allows_4h_primary_entry() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.0,
            weight_4h_direction=0.55,
            weight_4h_enhancement=0.0,
            weight_vwap=0.20,
            weight_15m_entry=0.05,
            weight_volume=0.20,
            min_signal_score=0.85,
            min_entry_score=0.1,
            min_vwap_score_for_entry=0.12,
            overheat_growing_penalty=0.0,
            enable_flip_bullish_strict_filter=False,
            disable_flip_bullish_entries=False,
            disable_green_bar_growing_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            light_1h_confirmation_when_4h_primary=True,
            enable_soft_15m_confirmation_when_4h_primary=True,
            soft_15m_entry_score=0.28,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.00040, -0.00025, -0.00018, -0.00010]),
        macd_hist_1h=np.array([-0.20, -0.10, 0.05, 0.10]),
        macd_hist_4h=np.array([-0.30, -0.15, -0.05, 0.20]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=99.6,
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
    assert signal.signal_score >= 0.85
    assert signal.details["entry_score_15m"] == pytest.approx(0.28, rel=1e-6)
    assert signal.details["vwap_score"] >= 0.12
    assert str(signal.details["entry_type_15m"]).startswith("soft_long_")


def test_green_bar_growing_short_adx_range_filter_blocks_full_size() -> None:
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


def test_analyze_blocks_shrinking_soft_short_combo_with_weak_combo_veto() -> None:
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

    assert signal.direction == "neutral"
    assert signal.signal_type_1h == "green_bar_shrinking"
    assert signal.entry_type_15m == "soft_short_neutral"
    assert signal.details["reject_reason_code"] == "weak_combo_veto"


def test_analyze_blocks_shrinking_soft_long_combo_with_weak_combo_veto() -> None:
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
            disable_red_bar_shrinking_long_dual_support_entries=False,
            primary_direction_timeframe="4h",
            require_1h_confirmation_when_4h_primary=True,
            allow_neutral_1h_confirmation=True,
            enable_soft_15m_confirmation_when_4h_primary=True,
            enable_rsi_entry_refinement=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([-0.00020, -0.00010, -0.00005, 0.0]),
        macd_hist_1h=np.array([0.35, 0.30, 0.25, 0.20]),
        macd_hist_4h=np.array([-0.10, 0.02, 0.08, 0.14]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=2.0,
        vwap=100.0,
        structural_vwap=100.4,
        close_price=100.8,
        bb_middle_1h=100.0,
        bb_upper_1h=106.0,
        bb_lower_1h=94.0,
        bb_middle_4h=100.0,
        bb_upper_4h=106.0,
        bb_lower_4h=94.0,
        bb_middle_15m=100.5,
        bb_upper_15m=101.5,
        bb_lower_15m=99.5,
        close_15m=100.8,
        close_15m_series=np.array([100.2, 100.4, 100.6, 100.7, 100.8], dtype=float),
        close_1h_series=np.array([99.0, 99.3, 99.7, 100.2, 100.6, 100.8], dtype=float),
        close_4h_series=np.array([97.0, 98.0, 99.0, 100.0, 100.4, 100.8], dtype=float),
        adx_1h=30.0,
        adx_4h=24.0,
        atr_1h=1.0,
    )

    assert signal.direction == "neutral"
    assert signal.signal_type_1h == "red_bar_shrinking"
    assert signal.entry_type_15m == "soft_long_neutral"
    assert signal.details["reject_reason_code"] == "weak_combo_veto"


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
