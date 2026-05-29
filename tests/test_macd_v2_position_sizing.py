from __future__ import annotations

import sys
import json
import logging
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.macd_strategy_v2 import MACDSignalV2, MACDStrategyV2Config, MACDStrategyV2Engine, VetoType
from src.fund_flow.decision_engine import FundFlowDecisionEngine


def test_total_compression_floor_preserves_high_score_position_size() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_dynamic_position_sizing=True,
            dynamic_vwap_score_position_tiers=[
                {"max": 0.25, "position_mult": 0.60},
            ],
            dynamic_volume_score_position_tiers=[
                {"max": 0.033, "position_mult": 0.75},
            ],
            dynamic_adx_trend_min=40.0,
            dynamic_adx_trend_position_mult=0.70,
            total_compression_floor_enabled=True,
            total_compression_floor_tiers=[
                {"min_score": 0.85, "min_mult_of_base": 0.45},
                {"min_score": 0.75, "min_mult_of_base": 0.35},
                {"min_score": 0.65, "min_mult_of_base": 0.25},
                {"min_score": 0.00, "min_mult_of_base": 0.15},
            ],
        )
    )

    portion = engine.calculate_position_portion(
        score=0.85,
        base_default_portion=0.35,
        base_max_symbol_position_portion=0.50,
        signal_type_1h="red_bar_growing",
        signal_type_4h="green_bar_shrinking",
        vwap_score=0.25,
        volume_score=0.033,
        adx_1h=45.0,
        market_regime="TREND",
    )

    assert portion == pytest.approx(0.1575)


def test_total_compression_floor_does_not_override_signal_type_cap() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_dynamic_position_sizing=True,
            dynamic_vwap_score_position_tiers=[
                {"max": 0.25, "position_mult": 0.60},
            ],
            dynamic_volume_score_position_tiers=[
                {"max": 0.033, "position_mult": 0.75},
            ],
            dynamic_adx_trend_min=40.0,
            dynamic_adx_trend_position_mult=0.70,
            dynamic_signal_type_position_caps={
                "green_bar_shrinking": {
                    "max_target_portion": 0.10,
                    "apply_to": ["signal_4h"],
                },
            },
            total_compression_floor_enabled=True,
            total_compression_floor_tiers=[
                {"min_score": 0.85, "min_mult_of_base": 0.45},
            ],
        )
    )

    portion = engine.calculate_position_portion(
        score=0.85,
        base_default_portion=0.35,
        base_max_symbol_position_portion=0.50,
        signal_type_1h="red_bar_growing",
        signal_type_4h="green_bar_shrinking",
        vwap_score=0.25,
        volume_score=0.033,
        adx_1h=45.0,
        market_regime="TREND",
    )

    assert portion == pytest.approx(0.10)


def test_total_compression_floor_does_not_raise_probe_or_shrink_paths() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_dynamic_position_sizing=True,
            dynamic_vwap_score_position_tiers=[
                {"max": 0.25, "position_mult": 0.60},
            ],
            dynamic_volume_score_position_tiers=[
                {"max": 0.033, "position_mult": 0.75},
            ],
            dynamic_adx_trend_min=40.0,
            dynamic_adx_trend_position_mult=0.70,
            total_compression_floor_enabled=True,
            total_compression_floor_tiers=[
                {"min_score": 0.85, "min_mult_of_base": 0.45},
            ],
        )
    )

    portion = engine.calculate_position_portion(
        score=0.85,
        base_default_portion=0.35,
        base_max_symbol_position_portion=0.50,
        trade_direction="long",
        signal_type_1h="red_bar_shrinking",
        vwap_score=0.25,
        volume_score=0.033,
        adx_1h=45.0,
        market_regime="TREND",
        rsi_probe_mode=True,
    )

    assert portion < 0.1575
    assert portion == pytest.approx(0.0275625, rel=1e-3)


def test_signal_combo_hard_block_blocks_long_flip_bearish() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._apply_signal_combo_hard_block(
        direction="long",
        signal_1h="flip_bearish",
        symbol="RENDERUSDT",
        score=0.96,
    )

    assert result["action"] == "BLOCK"
    assert result["max_portion"] == pytest.approx(0.0)


def test_signal_combo_hard_block_forces_probe_for_long_red_bar_shrinking() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config())

    result = engine._apply_signal_combo_hard_block(
        direction="long",
        signal_1h="red_bar_shrinking",
        symbol="PUMPUSDT",
        score=0.85,
    )

    assert result["action"] == "PROBE"
    assert result["max_portion"] == pytest.approx(0.042)


def test_15m_entry_gate_blocks_multi_risk_long_with_weak_15m() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_15m_hard_gate_enabled=True)
    )

    result = engine._apply_15m_entry_gate(
        direction="long",
        raw_15m=0.18,
        entry_15m="-",
        vwap_dev_pct=-0.015,
        adx=17.0,
        regime="NO_TRADE",
        signal_4h="flip_bullish",
        signal_1h="red_bar_growing",
        current_portion=0.17,
    )

    assert result["action"] == "BLOCK"
    assert "multi_risk" in result["reason"]


def test_15m_entry_gate_caps_dual_risk_long_to_probe() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_15m_hard_gate_enabled=True)
    )

    result = engine._apply_15m_entry_gate(
        direction="long",
        raw_15m=0.12,
        entry_15m="-",
        vwap_dev_pct=-0.008,
        adx=17.29,
        regime="TREND",
        signal_4h="red_bar_growing",
        signal_1h="red_bar_growing",
        current_portion=0.17,
    )

    assert result["action"] == "PROBE"
    assert result["max_portion"] == pytest.approx(0.06)
    assert "rbg_below_vwap" in result["reason"]


def test_15m_entry_gate_caps_red_bar_growing_below_vwap_without_15m_confirmation() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_15m_hard_gate_enabled=True)
    )

    result = engine._apply_15m_entry_gate(
        direction="long",
        raw_15m=0.12,
        entry_15m="-",
        vwap_dev_pct=-0.0063,
        adx=21.73,
        regime="TREND",
        signal_4h="red_bar_growing",
        signal_1h="red_bar_growing",
        current_portion=0.18,
    )

    assert result["action"] == "PROBE"
    assert result["max_portion"] == pytest.approx(0.06)
    assert "rbg_below_vwap" in result["reason"]


def test_flip_bullish_size_guard_blocks_below_vwap_without_15m_confirmation() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_flip_bullish_size_guard_enabled=True)
    )

    result = engine._apply_flip_bullish_size_guard(
        signal_4h="flip_bullish",
        signal_1h="red_bar_growing",
        vwap_dev_pct=-0.0091,
        raw_15m=0.18,
        entry_15m="-",
        current_portion=0.17,
    )

    assert result["action"] == "BLOCK"
    assert "below_vwap_no_15m" in result["reason"]


def test_regime_size_cap_limits_weak_adx_new_entry() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_adx_regime_size_cap_enabled=True)
    )

    capped = engine._apply_regime_size_cap(
        direction="long",
        adx=17.29,
        regime="TREND",
        current_portion=0.17,
        signal_score=0.80,
    )

    assert capped == pytest.approx(0.06)


def test_ema_multiplier_strong_requires_price_15m_and_adx_alignment() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_ema_conditional_multiplier_enabled=True)
    )

    capped = engine._resolve_ema_multiplier(
        ema_raw_mult=1.20,
        vwap_dev_pct=0.0001,
        raw_15m=0.24,
        adx=32.42,
        direction="long",
    )
    allowed = engine._resolve_ema_multiplier(
        ema_raw_mult=1.20,
        vwap_dev_pct=0.0001,
        raw_15m=0.30,
        adx=32.42,
        direction="long",
    )

    assert capped == pytest.approx(1.0)
    assert allowed == pytest.approx(1.2)


def test_vwap_score_gate_passes_extremely_low_entry_score() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_vwap_score_hard_block_enabled=True)
    )

    result = engine._apply_vwap_score_entry_gate(vwap_score=0.10, current_portion=0.18)

    assert result["action"] == "PASS"
    assert result["max_portion"] == pytest.approx(0.18)
    assert result["reason"] == "vwap_fully_ablated_observation_only"


def test_vwap_score_gate_does_not_cap_low_entry_score_to_probe() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(entry_quality_vwap_score_hard_block_enabled=True)
    )

    result = engine._apply_vwap_score_entry_gate(vwap_score=0.25, current_portion=0.18)

    assert result["action"] == "PASS"
    assert result["max_portion"] == pytest.approx(0.18)


def test_slow_bull_vwap_override_no_longer_caps_long() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            entry_quality_vwap_score_hard_block_enabled=True,
            vwap_score_slow_bull_override_enabled=True,
        )
    )

    result = engine._apply_vwap_score_entry_gate(
        vwap_score=0.10,
        current_portion=0.18,
        direction="long",
        is_slow_bull=True,
    )

    assert result["action"] == "PASS"
    assert result["max_portion"] == pytest.approx(0.18)


def test_slow_bull_vwap_override_no_longer_blocks_extreme_low_score() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            entry_quality_vwap_score_hard_block_enabled=True,
            vwap_score_slow_bull_override_enabled=True,
        )
    )

    result = engine._apply_vwap_score_entry_gate(
        vwap_score=0.03,
        current_portion=0.18,
        direction="long",
        is_slow_bull=True,
    )

    assert result["action"] == "PASS"
    assert result["max_portion"] == pytest.approx(0.18)


def test_continuation_long_candidate_allows_small_probe_when_momentum_confirms() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(enable_continuation_long=True)
    )

    result = engine._evaluate_continuation_long_candidate(
        symbol="WLDUSDT",
        symbol_ret_30m=0.004,
        symbol_ret_60m=0.010,
        rsi_15m=63.0,
        ema_slope_15m=0.001,
        close_15m=1.03,
        ema_fast_15m=1.02,
        btc_ret_30m=0.003,
        breadth_state={"is_slow_bull": True},
        vwap_score=0.10,
        corr_btc_alt=0.65,
    )

    assert result["allowed"] is True
    assert result["max_portion"] == pytest.approx(0.042)
    assert result["conditions_met"] == 6


def test_continuation_long_candidate_blocks_overheated_chase_after_fast_extension() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_continuation_long=True,
            continuation_long_overheat_guard_enabled=True,
            continuation_long_overheat_ret_30m=0.008,
            continuation_long_overheat_ret_60m=0.018,
        )
    )

    result = engine._evaluate_continuation_long_candidate(
        symbol="FETUSDT",
        symbol_ret_30m=0.0182,
        symbol_ret_60m=0.0200,
        rsi_15m=71.0,
        ema_slope_15m=0.001,
        close_15m=1.03,
        ema_fast_15m=1.02,
        btc_ret_30m=0.003,
        breadth_state={"is_slow_bull": True},
        vwap_score=0.10,
        corr_btc_alt=0.65,
    )

    assert result["allowed"] is False
    assert result["reason"].startswith("continuation_overheat_chase_block")


def test_continuation_long_candidate_requires_strict_checks_for_low_corr_symbol() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(enable_continuation_long=True)
    )

    result = engine._evaluate_continuation_long_candidate(
        symbol="DOGEUSDT",
        symbol_ret_30m=0.004,
        symbol_ret_60m=0.010,
        rsi_15m=63.0,
        ema_slope_15m=0.001,
        close_15m=1.01,
        ema_fast_15m=1.02,
        btc_ret_30m=0.003,
        breadth_state={"is_slow_bull": True},
        vwap_score=0.40,
        corr_btc_alt=0.05,
    )

    assert result["allowed"] is False
    assert "low_corr" in result["reason"]


def test_slow_bull_short_guard_blocks_low_vwap_short_when_breadth_is_high() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(enable_slow_bull_short_guard=True)
    )

    result = engine._apply_slow_bull_short_guard(
        direction="short",
        signal_1h="green_bar_shrinking",
        vwap_score=0.25,
        breadth_ratio=0.72,
        is_slow_bull=True,
    )

    assert result["action"] == "BLOCK"
    assert "slow_bull" in result["reason"]


def test_regime_entry_block_blocks_low_score_no_trade_and_caps_high_score_range() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            entry_quality_no_trade_gate_enabled=True,
            entry_quality_range_gate_enabled=True,
        )
    )

    no_trade = engine._check_regime_entry_block(regime="NO_TRADE", direction="long", signal_score=0.80)
    range_high = engine._check_regime_entry_block(regime="RANGE", direction="short", signal_score=0.82)

    assert no_trade["action"] == "BLOCK"
    assert range_high["action"] == "PROBE_CAP"
    assert range_high["max_portion"] == pytest.approx(0.060)


def test_macd_v2_dynamic_leverage_uses_three_four_five_ladder() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            rsi_probe_forced_leverage=3,
            red_bar_growing_probe_max_leverage=3,
            green_bar_growing_probe_max_leverage=3,
            preflip_trial_max_leverage=3,
        )
    )

    assert engine.calculate_leverage(0.86, signal_type_1h="red_bar_growing") == 5
    assert engine.calculate_leverage(0.76, signal_type_1h="red_bar_growing") == 4
    assert engine.calculate_leverage(0.70, signal_type_1h="red_bar_growing") == 3
    assert engine.calculate_leverage(0.90, signal_type_1h="red_bar_growing", is_trial_entry=True) == 3


def test_live_config_disables_total_compression_floor() -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))

    engine = FundFlowDecisionEngine(cfg)

    strategy_cfg = engine.macd_v2_config
    assert strategy_cfg.total_compression_floor_enabled is False
    assert strategy_cfg.total_compression_floor_tiers[0]["min_score"] == pytest.approx(0.85)
    assert strategy_cfg.total_compression_floor_tiers[0]["min_mult_of_base"] == pytest.approx(0.45)


def test_vwap_atr_gate_allows_extension_inside_atr_block_threshold() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="atr_normalized",
            vwap_gate_block_atr_multiplier=4.0,
            vwap_gate_fallback_hard_block_pct=0.06,
        )
    )

    score, veto, details = engine.calculate_vwap_score(
        price=104.0,
        vwap=100.0,
        direction="long",
        atr_pct=0.02,
    )

    assert veto is VetoType.NONE
    assert score > 0
    assert details["vwap_gate_mode"] == "atr_normalized"
    assert details["vwap_deviation_in_atr"] == pytest.approx(2.0)
    assert details["vwap_hard_block_threshold"] == pytest.approx(0.08)


def test_vwap_atr_gate_blocks_extension_beyond_atr_block_threshold() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="atr_normalized",
            vwap_gate_block_atr_multiplier=4.0,
            vwap_gate_fallback_hard_block_pct=0.06,
        )
    )

    score, veto, details = engine.calculate_vwap_score(
        price=104.0,
        vwap=100.0,
        direction="long",
        atr_pct=0.005,
    )

    assert score == pytest.approx(0.0)
    assert veto is VetoType.VWAP_HARD_BLOCK
    assert details["vwap_gate_mode"] == "atr_normalized"
    assert details["vwap_deviation_in_atr"] == pytest.approx(8.0)
    assert details["vwap_hard_block_threshold"] == pytest.approx(0.02)


def test_directional_vwap_gate_allows_same_direction_trend_aligned_short_extension() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="directional_ablation",
            vwap_same_dir_trend_aligned_pass_dev_pct=0.05,
            vwap_same_dir_trend_aligned_penalty_dev_pct=0.10,
            vwap_same_dir_trend_aligned_probe_dev_pct=0.15,
        )
    )

    score, veto, details = engine.calculate_vwap_score(
        price=92.0,
        vwap=100.0,
        direction="short",
        atr_pct=0.01,
        signal_type_4h="green_bar_growing",
        signal_type_1h="green_bar_growing",
    )

    assert veto is VetoType.NONE
    assert score > 0
    assert score == pytest.approx(0.045)
    assert details["vwap_gate_mode"] == "directional_ablation"
    assert details["vwap_gate_action"] == "same_dir_trend_aligned_penalty"
    assert details["vwap_gate_score_mult"] == pytest.approx(0.90)


def test_directional_vwap_gate_blocks_same_direction_counter_trend_short_extension() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="directional_ablation",
            vwap_same_dir_counter_pass_atr_mult=2.0,
            vwap_same_dir_counter_penalty_atr_mult=3.5,
            vwap_same_dir_counter_probe_atr_mult=5.0,
        )
    )

    score, veto, details = engine.calculate_vwap_score(
        price=108.0,
        vwap=100.0,
        direction="short",
        atr_pct=0.01,
        signal_type_4h="green_bar_growing",
        signal_type_1h="green_bar_growing",
    )

    assert score == pytest.approx(0.0)
    assert veto is VetoType.VWAP_HARD_BLOCK
    assert details["vwap_gate_action"] == "same_dir_counter_block"


def test_vwap_atr_gate_emits_diagnostic_log(caplog: pytest.LogCaptureFixture) -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="atr_normalized",
            vwap_gate_block_atr_multiplier=4.0,
        )
    )

    with caplog.at_level(logging.INFO, logger="src.fund_flow.macd_strategy_v2"):
        engine.calculate_vwap_score(
            price=92.0,
            vwap=100.0,
            direction="short",
            atr_pct=0.01,
        )

    assert "[VWAP_GATE]" in caplog.text
    assert "vwap_gate_action=vwap_hard_block" in caplog.text
    assert "vwap_deviation_in_atr=8.0000" in caplog.text


def test_vwap_atr_probe_band_is_not_hard_block_and_caps_position_size() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            vwap_deviation_gate_mode="atr_normalized",
            vwap_gate_penalty_atr_multiplier=2.5,
            vwap_gate_block_atr_multiplier=4.0,
            vwap_gate_probe_max_portion=0.06,
        )
    )

    score, veto, details = engine.calculate_vwap_score(
        price=103.0,
        vwap=100.0,
        direction="long",
        atr_pct=0.01,
    )
    portion = engine.calculate_position_portion(
        score=0.85,
        base_default_portion=0.35,
        base_max_symbol_position_portion=0.50,
        vwap_score=score,
        vwap_probe_mode=bool(details.get("vwap_probe_mode")),
    )

    assert veto is VetoType.NONE
    assert details["vwap_gate_action"] == "vwap_probe"
    assert details["vwap_probe_mode"] is True
    assert portion == pytest.approx(0.06)


def test_counter_trend_long_guard_blocks_extreme_below_vwap_weak_trend_long() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            counter_trend_long_guard_enabled=True,
            counter_trend_long_extreme_range_action="BLOCK",
        )
    )

    result = engine._check_counter_trend_long_guard(
        direction="long",
        vwap_dev_pct=-0.0457,
        adx=17.38,
        regime="TREND",
        score_15m=0.0135,
        raw_15m=0.27,
        signal_4h="red_bar_growing",
        signal_1h="red_bar_growing",
        current_portion=0.26775,
    )

    assert result["action"] == "BLOCK"
    assert result["max_portion"] == pytest.approx(0.0)


def test_counter_trend_long_guard_caps_moderate_below_vwap_range_long_to_probe() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config(counter_trend_long_guard_enabled=True))

    result = engine._check_counter_trend_long_guard(
        direction="long",
        vwap_dev_pct=-0.0148,
        adx=12.76,
        regime="RANGE",
        score_15m=0.0135,
        raw_15m=0.27,
        signal_4h="flip_bullish",
        signal_1h="red_bar_growing",
        current_portion=0.26775,
    )

    assert result["action"] == "PROBE"
    assert result["max_portion"] == pytest.approx(0.06)


def test_green_bar_probe_penalty_uses_configured_multiplier_without_extra_probe_scale() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_green_bar_growing_probe_overlay=True,
            green_bar_growing_probe_position_penalty=0.25,
            rsi_probe_portion_scale=0.25,
        )
    )

    portion = engine.calculate_position_portion(
        score=0.75,
        base_default_portion=0.35,
        base_max_symbol_position_portion=0.50,
        trade_direction="short",
        signal_type_1h="green_bar_growing",
        signal_type_4h="green_bar_growing",
        vwap_score=0.20,
        volume_score=0.10,
        adx_1h=25.0,
        market_regime="TREND",
    )

    assert portion == pytest.approx(0.07)


def test_vol_vwap_warn_scale_skips_dust_position_below_min_notional() -> None:
    cfg = {
        "fund_flow": {
            "min_open_notional": {
                "default_usdt": 2.0,
                "btc_usdt": 5.0,
                "major_usdt": 2.0,
            },
            "macd_mtf_strategy_v2": {
                "position_management": {
                    "vol_vwap_warn_position_scale": 0.5,
                    "vol_vwap_warn_scale_min_notional_guard": {"enabled": True},
                }
            },
        }
    }
    engine = FundFlowDecisionEngine(cfg)
    signal = MACDSignalV2(
        direction="short",
        signal_score=0.77,
        signal_type_1h="green_bar_growing",
        details={"vol_vwap_warn": True, "score_volume": 0.033, "vwap_score": 0.0432},
    )
    metadata = {"account_equity": 111.18}

    portion = engine._apply_macd_v2_vol_vwap_warn_position_scale(0.000437, signal, metadata)

    assert portion == pytest.approx(0.000437)
    assert metadata["vol_vwap_warn_position_scaled"] is False
    assert metadata["vol_vwap_warn_position_scale_skipped_below_min_notional"] is True


def test_live_config_keeps_vwap_observation_only() -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))

    engine = FundFlowDecisionEngine(cfg)
    strategy_cfg = engine.macd_v2_config
    macd_engine = MACDStrategyV2Engine(strategy_cfg)

    assert strategy_cfg.vwap_deviation_gate_mode == "observation_only"
    assert strategy_cfg.weight_vwap == pytest.approx(0.0)

    score, veto, details = macd_engine.calculate_vwap_score(
        price=92.0,
        vwap=100.0,
        direction="short",
        atr_pct=0.01,
        signal_type_4h="green_bar_growing",
        signal_type_1h="green_bar_growing",
    )

    assert veto is VetoType.NONE
    assert score > 0
    assert details["vwap_gate_action"] != "BLOCK"


def test_partial_confirm_shadow_scores_shrink_confirm_candidate() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            partial_confirm_enabled=True,
            partial_confirm_shadow_mode=True,
            partial_confirm_penalty_mult=0.85,
        )
    )

    pc = engine._check_partial_confirm("green_bar_shrinking", "red_bar_growing")
    shadow = engine._compute_partial_confirm_shadow_score(
        pc,
        score_1h=0.1275,
        score_vwap=0.85,
        score_vol=0.10,
        score_15m=0.0,
        rsi_score=1.0,
        vwap_dev_pct=-0.01,
        atr_pct=0.01,
    )

    assert pc is not None
    assert shadow["pc_direction"] == "long"
    assert shadow["pc_confidence"] == "MEDIUM"
    assert shadow["pc_shadow_only"] is False
    assert shadow["pc_vwap_safe"] is True
    assert shadow["pc_vwap_aligned"] is True
    assert shadow["pc_threshold"] == pytest.approx(0.58)
    assert shadow["pc_max_portion"] == pytest.approx(0.06)


def test_partial_confirm_low_confidence_is_shadow_only() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config(partial_confirm_enabled=True))

    pc = engine._check_partial_confirm("green_bar_shrinking", "red_bar_shrinking")
    shadow = engine._compute_partial_confirm_shadow_score(
        pc,
        score_1h=0.0,
        score_vwap=0.85,
        score_vol=0.0,
        score_15m=0.0,
        rsi_score=1.0,
        vwap_dev_pct=-0.01,
        atr_pct=0.01,
    )

    assert pc["confidence"] == "LOW"
    assert shadow["pc_shadow_only"] is True
    assert shadow["pc_would_pass"] is False


def test_partial_confirm_shadow_score_uses_rsi_rhythm_sample() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config(partial_confirm_enabled=True))
    pc = engine._check_partial_confirm("green_bar_shrinking", "red_bar_growing")

    rsi = engine.evaluate_rsi_rhythm(
        direction="long",
        rsi_15m_series=np.asarray([44.0, 47.0, 51.0, 55.0]),
        rsi_1h_series=np.asarray([46.0, 48.0, 51.0, 55.0]),
        rsi_4h_series=np.asarray([50.0, 51.0, 53.0, 55.0]),
        close_15m_series=np.asarray([95.0, 97.0, 100.0, 104.0]),
        close_1h_series=np.asarray([95.0, 97.0, 100.0, 104.0]),
        close_4h_series=np.asarray([95.0, 97.0, 100.0, 104.0]),
        macd_hist_1h_current=1.0,
    )
    shadow = engine._compute_partial_confirm_shadow_score(
        pc,
        score_1h=engine._score_1h_direction_from_signal("red_bar_growing"),
        score_vwap=0.85,
        score_vol=1.0,
        score_15m=float(rsi.get("raw_score", 0.0)),
        rsi_score=float(rsi.get("raw_score", 0.0)),
        vwap_dev_pct=-0.01,
        atr_pct=0.01,
    )

    assert rsi["raw_score"] > 0.0
    assert shadow["pc_scored"] > 0.40


def test_live_config_enables_partial_confirm_shadow_mode() -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))

    engine = FundFlowDecisionEngine(cfg)

    strategy_cfg = engine.macd_v2_config
    assert strategy_cfg.partial_confirm_enabled is True
    assert strategy_cfg.partial_confirm_shadow_mode is True
    assert strategy_cfg.partial_confirm_thresholds["MEDIUM"] == pytest.approx(0.58)
