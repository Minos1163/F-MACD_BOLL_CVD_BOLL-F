from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.macd_strategy_v2 import MACDStrategyV2Config, MACDStrategyV2Engine


def test_adaptive_rsi_direction_gate_softens_short_pullback_against_veto() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_rsi_adaptive_direction_gate=True,
            rsi_adaptive_soft_rsi_against_mult=0.88,
            rsi_adaptive_soft_rsi_against_max_portion=0.06,
        )
    )
    rhythm = {
        "hard_veto": True,
        "veto_reason": "rsi_1h_direction_against_veto",
        "entry_type": "rsi_1h_direction_block",
        "exposure_mult": 0.0,
        "rsi_1h_direction": "up",
    }

    adjusted = engine._apply_adaptive_rsi_direction_gate(
        rsi_rhythm=rhythm,
        signal_type_4h="green_bar_growing",
        signal_type_1h="green_bar_shrinking",
        direction="short",
    )

    assert adjusted["hard_veto"] is False
    assert adjusted["veto_reason"] == ""
    assert adjusted["entry_type"] == "rsi_soft_against_probe"
    assert adjusted["exposure_mult"] == pytest.approx(0.88)
    assert adjusted["probe_mode"] is True
    assert adjusted["rsi_soft_gate_applied"] is True
    assert adjusted["rsi_soft_max_portion"] == pytest.approx(0.06)
    assert adjusted["rsi_soft_gate_reason"] == "soft_short_green_bar_growing_green_bar_shrinking_against"


def test_adaptive_rsi_direction_gate_keeps_non_whitelisted_against_veto_hard() -> None:
    engine = MACDStrategyV2Engine(MACDStrategyV2Config(enable_rsi_adaptive_direction_gate=True))
    rhythm = {
        "hard_veto": True,
        "veto_reason": "rsi_1h_direction_against_veto",
        "entry_type": "rsi_1h_direction_block",
        "exposure_mult": 0.0,
        "rsi_1h_direction": "up",
    }

    adjusted = engine._apply_adaptive_rsi_direction_gate(
        rsi_rhythm=rhythm,
        signal_type_4h="green_bar_shrinking",
        signal_type_1h="red_bar_growing",
        direction="short",
    )

    assert adjusted["hard_veto"] is True
    assert adjusted["veto_reason"] == "rsi_1h_direction_against_veto"
    assert adjusted.get("rsi_soft_gate_applied") is not True


def test_adaptive_rsi_direction_gate_softens_strong_same_direction_flat_veto() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_rsi_adaptive_direction_gate=True,
            rsi_adaptive_soft_rsi_flat_mult=0.93,
        )
    )
    rhythm = {
        "hard_veto": True,
        "veto_reason": "rsi_1h_direction_flat_veto",
        "entry_type": "rsi_1h_direction_block",
        "exposure_mult": 0.0,
        "rsi_1h_direction": "flat",
    }

    adjusted = engine._apply_adaptive_rsi_direction_gate(
        rsi_rhythm=rhythm,
        signal_type_4h="green_bar_growing",
        signal_type_1h="green_bar_growing",
        direction="short",
    )

    assert adjusted["hard_veto"] is False
    assert adjusted["entry_type"] == "rsi_soft_flat_penalty"
    assert adjusted["exposure_mult"] == pytest.approx(0.93)
    assert adjusted.get("probe_mode") is not True
    assert adjusted["rsi_soft_gate_reason"] == "soft_short_green_bar_growing_green_bar_growing_flat"


def test_slow_bull_1h_direction_gate_ignores_conflict_when_long_momentum_ok() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_slow_bull_1h_gate_downgrade=True,
            slow_bull_1h_gate_mode="ignore_if_momentum_ok",
            slow_bull_1h_momentum_threshold_30m=0.003,
            slow_bull_1h_momentum_threshold_60m=0.005,
        )
    )
    rhythm = {
        "hard_veto": True,
        "veto_reason": "rsi_1h_direction_against_veto",
        "entry_type": "rsi_1h_direction_block",
        "exposure_mult": 0.0,
        "rsi_1h_direction": "down",
    }

    adjusted = engine._apply_slow_bull_1h_direction_gate_downgrade(
        rsi_rhythm=rhythm,
        direction="long",
        is_slow_bull=True,
        symbol_ret_30m=0.004,
        symbol_ret_60m=0.006,
    )

    assert adjusted["hard_veto"] is False
    assert adjusted["veto_reason"] == ""
    assert adjusted["entry_type"] == "rsi_1h_direction_momentum_override"
    assert adjusted["1h_gate_override"] == "ignored_by_momentum"
    assert adjusted["rsi_1h_direction_gate_passed"] is True


def test_slow_bull_1h_direction_gate_keeps_block_when_momentum_weak() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_slow_bull_1h_gate_downgrade=True,
            slow_bull_1h_gate_mode="ignore_if_momentum_ok",
        )
    )
    rhythm = {
        "hard_veto": True,
        "veto_reason": "rsi_1h_direction_against_veto",
        "entry_type": "rsi_1h_direction_block",
        "exposure_mult": 0.0,
    }

    adjusted = engine._apply_slow_bull_1h_direction_gate_downgrade(
        rsi_rhythm=rhythm,
        direction="long",
        is_slow_bull=True,
        symbol_ret_30m=0.001,
        symbol_ret_60m=0.006,
    )

    assert adjusted["hard_veto"] is True
    assert adjusted["veto_reason"] == "rsi_1h_direction_against_veto"
