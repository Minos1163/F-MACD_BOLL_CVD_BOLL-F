from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_macd_v2 import (
    BacktestConfig,
    BacktestEngine,
    MACDSignalV2,
    MACDStrategyV2Engine,
    MACDStrategyV2Config,
    VetoType,
    apply_backtest_profile,
    build_strategy_config,
    main as backtest_main,
    resolve_runtime_config_for_backtest,
)
from src.app.fund_flow_bot import TradingBot
from src.fund_flow.decision_engine import FundFlowDecisionEngine
from src.fund_flow.models import FundFlowDecision, Operation
from scripts.analyze_backtest_trades import build_cancel_quality_summary
from scripts.diagnose_ioc_fallback import diagnose_ioc_fallback
from scripts.diagnose_macd_v2_mdd_round1 import diagnose_mdd_round1
from scripts.validate_live_backtest_alignment import (
    ApprovedDifference,
    AlignmentRule,
    compare_live_backtest_alignment,
    main as alignment_main,
)


def test_resolve_runtime_config_for_backtest_skips_profile_in_strict_live_mode() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "macd_mtf_strategy_v2": {"short_quality_filter": {"enabled": True}},
            "backtest": {
                "default_profile": "macd_v2_disable_short_filter",
                "profiles": {
                    "macd_v2_disable_short_filter": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "short_quality_filter": {"enabled": False}
                                }
                            }
                        }
                    }
                },
            },
        },
    }

    merged, active_profile = resolve_runtime_config_for_backtest(
        runtime_cfg,
        profile_name=None,
        strict_live_mode=True,
    )

    assert active_profile == ""
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["enabled"] is True


def test_diagnose_mdd_round1_requires_existing_input_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="trades file"):
        diagnose_mdd_round1(
            trades_file=tmp_path / "missing_trades.csv",
            equity_curve_file=tmp_path / "equity.csv",
            drawdown_file=tmp_path / "drawdown.csv",
            window_start="2026-02-28 17:30:00",
            window_end="2026-03-04 00:30:00",
        )


def test_diagnose_mdd_round1_rejects_empty_trades(tmp_path: Path) -> None:
    trades = tmp_path / "trades.csv"
    equity = tmp_path / "equity.csv"
    drawdown = tmp_path / "drawdown.csv"
    pd.DataFrame(columns=["symbol", "entry_time", "exit_time", "pnl"]).to_csv(trades, index=False)
    pd.DataFrame([{"time": "2026-03-01 00:00:00", "equity": 10000.0}]).to_csv(equity, index=False)
    pd.DataFrame([{"start_time": "2026-03-01 00:00:00", "trough_time": "2026-03-01 01:00:00"}]).to_csv(drawdown, index=False)

    with pytest.raises(ValueError, match="trades file is empty"):
        diagnose_mdd_round1(
            trades_file=trades,
            equity_curve_file=equity,
            drawdown_file=drawdown,
            window_start="2026-02-28 17:30:00",
            window_end="2026-03-04 00:30:00",
        )


def test_diagnose_mdd_round1_reports_empty_window_when_no_overlap(tmp_path: Path) -> None:
    trades = tmp_path / "trades.csv"
    equity = tmp_path / "equity.csv"
    drawdown = tmp_path / "drawdown.csv"
    pd.DataFrame(
        [
            {
                "symbol": "SOLUSDT",
                "side": "long",
                "entry_time": "2026-02-20 00:00:00",
                "exit_time": "2026-02-20 01:00:00",
                "pnl": 12.5,
                "reason": "stop_loss_intrabar",
                "signal_type_1h": "red_bar_growing",
                "signal_score": 0.67,
                "vwap_score": 0.04,
                "adx_1h": 20.0,
                "bb_middle_slope_4h": -0.001,
            }
        ]
    ).to_csv(trades, index=False)
    pd.DataFrame([{"time": "2026-02-20 00:15:00", "equity": 10012.5}]).to_csv(equity, index=False)
    pd.DataFrame([{"start_time": "2026-02-20 00:00:00", "trough_time": "2026-02-20 01:00:00"}]).to_csv(drawdown, index=False)

    result = diagnose_mdd_round1(
        trades_file=trades,
        equity_curve_file=equity,
        drawdown_file=drawdown,
        window_start="2026-02-28 17:30:00",
        window_end="2026-03-04 00:30:00",
    )

    assert result["window"]["overlap_trades"] == 0
    assert result["window"]["closed_trades"] == 0
    assert result["reason_breakdown"] == []
    assert result["signal_type_breakdown"] == []


def test_resolve_runtime_config_for_backtest_rejects_profile_with_strict_live_mode() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "backtest": {
                "default_profile": "macd_v2_disable_short_filter",
                "profiles": {
                    "macd_v2_disable_short_filter": {
                        "config_overrides": {"fund_flow": {"default_target_portion": 0.35}}
                    }
                },
            },
        },
    }

    with pytest.raises(ValueError, match="strict_live_mode"):
        resolve_runtime_config_for_backtest(
            runtime_cfg,
            profile_name="macd_v2_disable_short_filter",
            strict_live_mode=True,
        )


def test_dynamic_stop_uses_symbol_scoped_max_stop_when_tighter() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            max_stop_loss_pct=0.025,
            symbol_risk_max_stop_loss_pct_by_symbol={"XLMUSDT": 0.01},
        )
    )

    stop_price, stop_pct, details = engine.calculate_dynamic_stop(
        entry_price=100.0,
        close_1h=100.0,
        bb_middle_1h=90.0,
        bb_upper_1h=0.0,
        bb_lower_1h=0.0,
        atr_1h=0.0,
        vwap=0.0,
        direction="long",
        symbol="XLMUSDT",
    )

    assert stop_price == 99.0
    assert stop_pct == pytest.approx(0.01)
    assert details["effective_max_stop_loss_pct"] == 0.01
    assert details["symbol_stop_override_applied"] is True


def test_dynamic_stop_ignores_symbol_scoped_max_stop_when_looser() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            max_stop_loss_pct=0.025,
            symbol_risk_max_stop_loss_pct_by_symbol={"XLMUSDT": 0.04},
        )
    )

    stop_price, stop_pct, details = engine.calculate_dynamic_stop(
        entry_price=100.0,
        close_1h=100.0,
        bb_middle_1h=90.0,
        bb_upper_1h=0.0,
        bb_lower_1h=0.0,
        atr_1h=0.0,
        vwap=0.0,
        direction="long",
        symbol="XLMUSDT",
    )

    assert stop_price == 97.5
    assert stop_pct == pytest.approx(0.025)
    assert details["effective_max_stop_loss_pct"] == 0.025
    assert details["symbol_stop_override_applied"] is False


def test_build_strategy_config_loads_symbol_scoped_max_stop() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "stop_loss_config": {"max_stop_loss_pct": 0.025},
                "symbol_risk_tiers": {
                    "max_stop_loss_pct_by_symbol": {
                        "XLMUSDT": 0.01,
                        "SOLUSDT": 0.015,
                    }
                },
            }
        }
    }

    config = build_strategy_config(runtime_cfg)

    assert config.symbol_risk_max_stop_loss_pct_by_symbol == {
        "XLMUSDT": 0.01,
        "SOLUSDT": 0.015,
    }


def test_build_strategy_config_loads_short_vwap_entry_floors() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "min_vwap_score_for_entry": 0.10,
                    "short_min_vwap_score_for_entry": 0.12,
                    "flip_bearish_short_min_vwap_score_for_entry": 0.25,
                }
            }
        }
    }

    config = build_strategy_config(runtime_cfg)

    assert config.min_vwap_score_for_entry == pytest.approx(0.10)
    assert config.short_min_vwap_score_for_entry == pytest.approx(0.12)
    assert config.flip_bearish_short_min_vwap_score_for_entry == pytest.approx(0.25)


def test_build_strategy_config_loads_resonance_gate_settings() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "resonance_gate": {
                    "enabled": True,
                    "long_rsi_rhythm_min": 0.36,
                    "short_rsi_rhythm_min": 0.37,
                    "flip_bearish_rsi_rhythm_min": 0.41,
                    "volume_warn_ratio": 0.75,
                    "volume_warn_position_scale": 0.45,
                    "structural_vwap_telemetry_position_scale_threshold": 0.06,
                    "structural_vwap_telemetry_position_scale": 0.65,
                }
            }
        }
    }

    config = build_strategy_config(runtime_cfg)

    assert config.resonance_gate_enabled is True
    assert config.resonance_long_rsi_rhythm_min == pytest.approx(0.36)
    assert config.resonance_short_rsi_rhythm_min == pytest.approx(0.37)
    assert config.flip_bearish_resonance_rsi_rhythm_min == pytest.approx(0.41)
    assert config.resonance_volume_warn_ratio == pytest.approx(0.75)
    assert config.resonance_volume_warn_position_scale == pytest.approx(0.45)
    assert config.structural_vwap_telemetry_position_scale_threshold == pytest.approx(0.06)
    assert config.structural_vwap_telemetry_position_scale == pytest.approx(0.65)


def test_candidate_ablation_configs_apply_expected_vwap_and_resonance_settings() -> None:
    live_cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    candidate_a = json.loads(Path("config/candidate_a_no_vwap_gate.json").read_text(encoding="utf-8"))
    candidate_b = json.loads(Path("config/candidate_b_no_vwap_score.json").read_text(encoding="utf-8"))
    candidate_c = json.loads(Path("config/candidate_c_resonance_gate.json").read_text(encoding="utf-8"))

    live_v2 = live_cfg["fund_flow"]["macd_mtf_strategy_v2"]
    a_v2 = candidate_a["fund_flow"]["macd_mtf_strategy_v2"]
    b_v2 = candidate_b["fund_flow"]["macd_mtf_strategy_v2"]
    c_v2 = candidate_c["fund_flow"]["macd_mtf_strategy_v2"]

    for v2 in (live_v2, a_v2, b_v2, c_v2):
        filters = v2["entry_filters"]
        assert filters["min_vwap_score_for_entry"] == pytest.approx(0.0)
        assert filters["short_min_vwap_score_for_entry"] == pytest.approx(0.0)
        assert filters["flip_bearish_short_min_vwap_score_for_entry"] == pytest.approx(0.0)
        assert filters["preflip_trial_min_vwap_score"] == pytest.approx(0.0)
        assert filters["trial_short_below_structure_promotion_min_vwap_score"] == pytest.approx(0.0)
        assert filters["stable_bear_continuation_min_vwap_score"] == pytest.approx(0.0)
        assert filters["stable_bull_continuation_min_vwap_score"] == pytest.approx(0.0)
        assert filters["flip_bullish_min_vwap_score"] == pytest.approx(0.0)
        assert filters["vol_vwap_warn_min_vwap_score"] == pytest.approx(0.0)
        assert v2["vwap_config"]["vwap_deviation_hard_block"] == pytest.approx(999.0)

    assert a_v2["scoring_weights"]["weight_vwap"] == pytest.approx(0.05)
    assert a_v2["scoring_weights"]["weight_rsi_rhythm"] == pytest.approx(0.30)
    assert b_v2["scoring_weights"]["weight_vwap"] == pytest.approx(0.0)
    assert b_v2["scoring_weights"]["weight_rsi_rhythm"] == pytest.approx(0.35)
    assert c_v2["scoring_weights"]["weight_vwap"] == pytest.approx(0.0)
    assert c_v2["scoring_weights"]["weight_rsi_rhythm"] == pytest.approx(0.35)
    assert c_v2["resonance_gate"]["enabled"] is True
    assert c_v2["short_quality_filter"]["min_vwap_deviation"] == pytest.approx(0.0)


def test_trial_entry_vwap_floor_cannot_bypass_global_entry_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.12,
            preflip_trial_min_vwap_score=0.0,
        )
    )

    floor = engine._resolve_min_vwap_score_for_entry(
        trade_direction="long",
        signal_type_1h="red_bar_growing",
        is_trial_entry=True,
    )

    assert floor == pytest.approx(0.12)


def test_flip_bullish_exemption_keeps_global_vwap_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_vwap_flip_exemption=True,
            min_vwap_score_for_entry=0.12,
        )
    )

    floor = engine._resolve_min_vwap_score_for_entry(
        trade_direction="long",
        signal_type_1h="flip_bullish",
        is_trial_entry=False,
    )

    assert floor == pytest.approx(0.12)


def test_trial_flip_bearish_short_keeps_dedicated_vwap_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.12,
            short_min_vwap_score_for_entry=0.12,
            preflip_trial_min_vwap_score=0.0,
            flip_bearish_short_min_vwap_score_for_entry=0.25,
        )
    )

    floor = engine._resolve_min_vwap_score_for_entry(
        trade_direction="short",
        signal_type_1h="flip_bearish",
        is_trial_entry=True,
    )

    assert floor == pytest.approx(0.25)


def test_debug_details_preserve_resolved_vwap_entry_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.12,
            flip_bearish_short_min_vwap_score_for_entry=0.25,
        )
    )

    details = engine._build_debug_details(
        stage="vwap_score_filter",
        min_vwap_score_for_entry=0.25,
    )

    assert details["min_vwap_score_for_entry"] == pytest.approx(0.25)


def test_stable_bear_continuation_vwap_floor_cannot_bypass_global_short_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_stable_bear_continuation=True,
            stable_bear_continuation_min_vwap_score=0.0,
            short_min_vwap_score_for_entry=0.12,
        )
    )

    result = engine._evaluate_stable_continuation(
        primary_mode="4h",
        trade_direction="short",
        signal_type_1h="flip_bearish",
        entry_type_15m="green_bar_growing",
        vwap_score=0.04,
        vwap_state="short_dual_pressure",
        adx_1h=35.0,
        stable_trend_context={"bear_active": True, "negative_bars": 4},
        is_trial_entry=False,
    )

    assert result["stable_continuation_active"] is False
    assert result["stable_continuation_reason"] == "vwap_score_too_low"
    assert result["stable_continuation_min_vwap_score"] == pytest.approx(0.12)


def test_trial_short_promotion_vwap_floor_cannot_bypass_global_short_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_trial_short_below_structure_continuation_promotion=True,
            trial_short_below_structure_promotion_min_vwap_score=0.0,
            short_min_vwap_score_for_entry=0.12,
        )
    )

    result = engine._evaluate_trial_short_below_structure_continuation_promotion(
        primary_mode="4h",
        trade_direction="short",
        signal_type_1h="green_bar_growing",
        entry_type_15m="flip_bearish",
        vwap_state="short_below_session_above_structure",
        vwap_score=0.04,
        adx_1h=35.0,
        signal_score=0.90,
        shrink_4h_context={"shrink_pct": 0.90, "shrink_bars": 8},
        is_trial_entry=True,
    )

    assert result["trial_short_below_structure_promotion_active"] is False
    assert result["trial_short_below_structure_promotion_reason"] == "vwap_score_too_low"
    assert result["trial_short_below_structure_promotion_min_vwap_score"] == pytest.approx(0.12)


def test_flip_bearish_independent_short_quality_filter_runs_when_global_disabled() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_short_quality_filter=False,
            flip_bearish_independent_short_quality_filter_enabled=True,
        )
    )

    assert engine._should_apply_short_quality_filter("flip_bearish", strict_1h_filters_enabled=True) is True
    assert engine._should_apply_short_quality_filter("green_bar_growing", strict_1h_filters_enabled=True) is False


def test_flip_bearish_resonance_gate_blocks_each_protection_layer() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            resonance_gate_enabled=True,
            flip_bearish_resonance_rsi_rhythm_min=0.40,
        )
    )
    base = {
        "signal_type_1h": "flip_bearish",
        "trade_direction": "short",
        "is_trial_entry": False,
        "direction_4h": "short",
        "signal_type_4h": "green_bar_growing",
        "direction_1h": "short",
        "entry_type_15m": "green_bar_growing",
        "ema_status": "normal",
        "rsi_rhythm": {"raw_score": 0.45, "veto_reason": "", "entry_type": "rsi_neutral_resume"},
        "rsi_conflict_type": "none",
        "adx_1h": 35.0,
        "is_4h_enhanced": False,
        "funding_rate": 0.001,
        "oi_delta_ratio": -0.01,
        "volume_ratio": 1.0,
        "structural_vwap_deviation": 0.0,
    }

    assert engine._check_resonance_gate(**base)["passed"] is True

    cases = [
        ({"adx_1h": 20.0}, "flip_bearish_resonance_adx_fail"),
        ({"direction_4h": "long"}, "flip_bearish_resonance_4h_fail"),
        ({"entry_type_15m": "", "is_4h_enhanced": False}, "flip_bearish_resonance_confirmation_fail"),
        ({"ema_status": "against"}, "flip_bearish_resonance_ema_against"),
        ({"rsi_rhythm": {"raw_score": 0.35}}, "flip_bearish_resonance_rsi_fail"),
        ({"rsi_conflict_type": "divergence"}, "flip_bearish_resonance_rsi_conflict"),
        ({"funding_rate": 0.0}, "flip_bearish_resonance_funding_fail"),
        ({"oi_delta_ratio": 0.02}, "flip_bearish_resonance_oi_fail"),
    ]
    for overrides, expected_reason in cases:
        payload = dict(base)
        payload.update(overrides)

        result = engine._check_resonance_gate(**payload)

        assert result["passed"] is False
        assert result["reason"] == expected_reason


def test_resonance_gate_scales_low_volume_without_vwap_veto() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            resonance_gate_enabled=True,
            resonance_volume_warn_ratio=0.80,
            resonance_volume_warn_position_scale=0.50,
            structural_vwap_telemetry_position_scale_threshold=0.05,
            structural_vwap_telemetry_position_scale=0.70,
        )
    )

    result = engine._check_resonance_gate(
        signal_type_1h="red_bar_growing",
        trade_direction="long",
        is_trial_entry=False,
        direction_4h="long",
        signal_type_4h="red_bar_growing",
        direction_1h="long",
        entry_type_15m="rsi_neutral_resume",
        ema_status="normal",
        rsi_rhythm={"raw_score": 0.40, "veto_reason": ""},
        rsi_conflict_type="none",
        adx_1h=20.0,
        is_4h_enhanced=False,
        funding_rate=0.0,
        oi_delta_ratio=0.0,
        volume_ratio=0.70,
        structural_vwap_deviation=0.06,
    )

    assert result["passed"] is True
    assert result["reason"] == "resonance_gate_long_pass"
    assert result["position_scale"] == pytest.approx(0.35)
    assert result["volume_warn"] is True
    assert result["vwap_telemetry_warn"] is True


def test_macd_v2_regime_long_gate_blocks_weak_range_and_no_trade_longs() -> None:
    decision_engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "min_leverage": 3,
                "default_leverage": 4,
                "max_leverage": 5,
                "macd_mtf_strategy_v2": {
                    "regime_entry": {
                        "range_long_min_vwap_score": 0.20,
                        "range_long_min_signal_score": 0.72,
                        "no_trade_long_blocked_unless_override": True,
                    }
                },
            }
        }
    )
    signal = MACDSignalV2(direction="long", signal_score=0.70, vwap_score=0.04)

    range_result = decision_engine._macd_v2_regime_long_entry_veto(
        signal=signal,
        regime_info={"regime": "RANGE"},
        metadata={},
    )
    no_trade_result = decision_engine._macd_v2_regime_long_entry_veto(
        signal=signal,
        regime_info={"regime": "NO_TRADE"},
        metadata={},
    )

    assert range_result is not None
    assert range_result.operation == Operation.HOLD
    assert "range_long_quality_gate" in range_result.reason
    assert no_trade_result is not None
    assert no_trade_result.operation == Operation.HOLD
    assert "no_trade_long_block" in no_trade_result.reason


def test_macd_v2_weak_entry_leverage_is_not_lifted_by_min_leverage() -> None:
    decision_engine = FundFlowDecisionEngine(
        {"fund_flow": {"min_leverage": 3, "default_leverage": 4, "max_leverage": 5}}
    )
    metadata = {"vol_vwap_warn": False}

    leverage = decision_engine._resolve_macd_v2_entry_leverage(
        strategy_leverage=1,
        signal_score=0.70,
        is_trial_entry=False,
        metadata=metadata,
    )

    assert leverage == 1
    assert metadata["leverage_min_bypass_applied"] is True


def test_macd_v2_stop_summary_resolves_exchange_stop_and_repairs_missing_stop() -> None:
    bot = object.__new__(TradingBot)
    bot.client = SimpleNamespace(
        get_open_orders=lambda symbol: [
            {"type": "STOP_MARKET", "stopPrice": "99.25", "side": "SELL"},
        ]
    )
    bot._repair_missing_protection_calls = []
    bot._repair_missing_protection = lambda symbol, position: bot._repair_missing_protection_calls.append((symbol, position)) or {"status": "success"}

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="SOLUSDT",
        metadata={"macd_v2_debug": {"stop_price": 0.0, "stop_loss_pct": 0.02}},
    )
    resolved = bot._resolve_macd_v2_stop_summary(
        symbol="SOLUSDT",
        decision=decision,
        position_for_log={"side": "LONG", "entry_price": 100.0},
    )

    assert resolved["stop_price"] == pytest.approx(99.25)
    assert resolved["stop_source"] == "exchange"
    assert bot._repair_missing_protection_calls == []

    bot.client = SimpleNamespace(get_open_orders=lambda symbol: [])
    missing = bot._resolve_macd_v2_stop_summary(
        symbol="SOLUSDT",
        decision=decision,
        position_for_log={"side": "LONG", "entry_price": 100.0, "amount": 1.0},
    )

    assert missing["stop_price"] == 0.0
    assert missing["stop_source"] == "MISSING"
    assert bot._repair_missing_protection_calls


def test_backtest_cli_rejects_profile_with_strict_live_mode() -> None:
    with pytest.raises(SystemExit) as exc:
        backtest_main(
            [
                "--config",
                "config/trading_config_fund_flow.json",
                "--profile",
                "macd_v2_disable_short_filter",
                "--strict-live-mode",
            ]
        )

    assert exc.value.code == 2


def test_compare_live_backtest_alignment_detects_threshold_and_portion_drift() -> None:
    runtime_cfg = {
        "fund_flow": {
            "default_target_portion": 0.60,
            "max_symbol_position_portion": 0.60,
            "max_active_symbols": 3,
            "macd_mtf_strategy_v2": {
                "entry_thresholds": {
                    "default": 0.85,
                    "red_bar_growing": 0.90,
                    "flip_bearish": 0.84,
                }
            },
            "backtest": {
                "default_profile": "focus",
                "profiles": {
                    "focus": {
                        "config_overrides": {
                            "fund_flow": {
                                "default_target_portion": 0.35,
                                "max_symbol_position_portion": 0.35,
                                "max_active_symbols": 4,
                                "macd_mtf_strategy_v2": {
                                    "entry_thresholds": {
                                        "default": 0.68,
                                        "red_bar_growing": 0.68,
                                        "flip_bearish": 0.66,
                                    }
                                },
                            }
                        }
                    }
                },
            },
        }
    }
    rules = [
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.default", 0.05),
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.red_bar_growing", 0.05),
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.flip_bearish", 0.05),
        AlignmentRule("fund_flow.default_target_portion", 0.10),
        AlignmentRule("fund_flow.max_symbol_position_portion", 0.10),
        AlignmentRule("fund_flow.max_active_symbols", 0.0),
    ]

    rows = compare_live_backtest_alignment(runtime_cfg, rules)
    failed = [row for row in rows if row["status"] == "FAIL"]

    assert len(failed) == 6
    assert any(row["path"] == "fund_flow.max_active_symbols" for row in failed)


def test_alignment_cli_exits_nonzero_for_current_repo() -> None:
    alignment_main(["--config", "config/trading_config_fund_flow.json"])


def test_current_repo_live_base_is_aligned_with_default_backtest_profile() -> None:
    runtime_cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))

    rows = compare_live_backtest_alignment(runtime_cfg, [
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.default", 0.05),
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.red_bar_growing", 0.05),
        AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.flip_bearish", 0.05),
        AlignmentRule("fund_flow.default_target_portion", 0.10),
        AlignmentRule("fund_flow.max_symbol_position_portion", 0.10),
        AlignmentRule("fund_flow.max_active_symbols", 0.0),
    ])

    assert all(row["status"] == "PASS" for row in rows)


def test_compare_live_backtest_alignment_marks_approved_diff_without_failing() -> None:
    runtime_cfg = {
        "fund_flow": {
            "default_target_portion": 0.35,
            "max_symbol_position_portion": 0.35,
            "max_active_symbols": 4,
            "macd_mtf_strategy_v2": {
                "entry_thresholds": {
                    "default": 0.68,
                    "red_bar_growing": 0.68,
                    "flip_bearish": 0.66,
                }
            },
            "backtest": {
                "default_profile": "approved_gap",
                "profiles": {
                    "approved_gap": {
                        "config_overrides": {
                            "fund_flow": {
                                "max_active_symbols": 5,
                            }
                        }
                    }
                },
            },
        }
    }

    rows = compare_live_backtest_alignment(
        runtime_cfg,
        [AlignmentRule("fund_flow.max_active_symbols", 0.0)],
        approved_differences=[
            ApprovedDifference(
                "fund_flow.max_active_symbols",
                live=4,
                backtest=5,
                note="capacity ablation approved difference",
            )
        ],
    )

    assert rows[0]["status"] == "APPROVED_DIFF"
    assert rows[0]["approved_note"] == "capacity ablation approved difference"


def test_flip_bullish_disable_candidate_sets_disable_flag_without_touching_default_profile() -> None:
    cfg = json.loads(
        Path("config/candidates/flip_bullish_disabled_backtest.json").read_text(encoding="utf-8")
    )

    assert cfg["fund_flow"]["backtest"]["default_profile"] == "macd_v2_disable_short_filter"
    assert (
        cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["disable_flip_bullish_entries"] is True
    )


def test_cancel_pending_order_tracks_full_cancel_audit_row() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    engine.capital = 9900.0
    engine.pending_orders["SOLUSDT"] = {
        "margin": 100.0,
        "side": "long",
        "signal_score": 0.74,
        "signal_type_1h": "red_bar_growing",
        "vwap_score": 0.03,
        "submit_time": pd.Timestamp("2026-04-25 14:00:00"),
        "bars_waited": 2,
    }

    engine._cancel_pending_order("SOLUSDT", reason="ioc_no_fill")

    assert len(engine.pending_cancel_audit_rows) == 1
    row = engine.pending_cancel_audit_rows[0]
    assert row["symbol"] == "SOLUSDT"
    assert row["side"] == "long"
    assert row["signal_type_1h"] == "red_bar_growing"
    assert row["reason"] == "ioc_no_fill"
    assert row["bars_waited"] == 2


def test_neutral_vwap_veto_attribution_records_floor_context() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        signal_type_1h="red_bar_growing",
        vwap_score=0.09,
        is_trial_entry=True,
        veto_type=VetoType.VWAP_SCORE_FILTER,
        details={
            "trade_direction": "long",
            "entry_type_15m": "soft_long",
            "min_vwap_score_for_entry": 0.12,
            "vwap_score": 0.09,
            "vwap_state": "long_dual_support",
        },
    )

    candidates = engine._build_entry_candidates(
        {"SOLUSDT": _analysis(signal=signal)},
        closed_symbols_this_bar=set(),
    )

    assert candidates == []
    assert engine.execution_audit["neutral_veto_reasons"]["vwap_score_filter"] == 1
    breakdown = engine.execution_audit["vwap_filter_breakdown"]
    assert breakdown["vwap_score_filter|red_bar_growing|trial|long|preflip_trial_floor|0.1200"] == 1
    assert engine.execution_audit["vwap_filter_examples"] == [
        {
            "symbol": "SOLUSDT",
            "veto_type": "vwap_score_filter",
            "signal_type_1h": "red_bar_growing",
            "entry_type_15m": "soft_long",
            "is_trial": True,
            "is_short": False,
            "trade_direction": "long",
            "floor_source": "preflip_trial_floor",
            "min_vwap_score_for_entry": 0.12,
            "vwap_score": 0.09,
            "vwap_state": "long_dual_support",
            "stage": "",
            "reason": "",
        }
    ]


def test_neutral_resonance_gate_attribution_records_reason_signal_and_side() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        signal_type_1h="flip_bearish",
        veto_type=VetoType.RESONANCE_GATE,
        details={
            "trade_direction": "short",
            "resonance_gate_reason": "flip_bearish_resonance_rsi_fail",
        },
    )

    candidates = engine._build_entry_candidates(
        {"SOLUSDT": _analysis(signal=signal)},
        closed_symbols_this_bar=set(),
    )

    assert candidates == []
    assert engine.execution_audit["neutral_veto_reasons"]["resonance_gate"] == 1
    assert engine.execution_audit["resonance_gate_block_by_reason"]["flip_bearish_resonance_rsi_fail"] == 1
    assert engine.execution_audit["resonance_gate_block_by_signal"]["flip_bearish"] == 1
    assert engine.execution_audit["resonance_gate_block_by_side"]["short"] == 1


def test_build_cancel_quality_summary_compares_canceled_vs_filled_scores() -> None:
    trades = pd.DataFrame(
        [
            {"symbol": "BTCUSDT", "signal_score": 0.90, "signal_type_1h": "red_bar_growing"},
            {"symbol": "ETHUSDT", "signal_score": 0.70, "signal_type_1h": "flip_bearish"},
        ]
    )
    pending_cancels = pd.DataFrame(
        [
            {"symbol": "SOLUSDT", "signal_score": 0.95, "signal_type_1h": "red_bar_growing", "reason": "ioc_no_fill"},
            {"symbol": "ADAUSDT", "signal_score": 0.85, "signal_type_1h": "flip_bullish", "reason": "ioc_no_fill"},
        ]
    )

    summary = build_cancel_quality_summary(trades, pending_cancels)

    assert summary["filled_avg_score"] == pytest.approx(0.80, rel=1e-6)
    assert summary["canceled_avg_score"] == pytest.approx(0.90, rel=1e-6)
    assert summary["canceled_score_percentiles"]["p50"] == pytest.approx(0.90, rel=1e-6)
    assert summary["by_signal_type"]["red_bar_growing"]["canceled"] == 1


def test_diagnose_ioc_fallback_classifies_missing_market_fallback_path() -> None:
    summary = {
        "execution_funnel": {
            "orders_canceled": 130,
            "market_fallback_attempted": 0,
            "market_fallback_filled": 0,
            "market_fallback_slippage_blocked": 0,
            "market_fallback_disabled_by_policy": 0,
        }
    }
    pending_cancels = pd.DataFrame(
        [
            {"symbol": "SOLUSDT", "signal_score": 0.95, "signal_type_1h": "red_bar_growing", "reason": "ioc_no_fill"},
            {"symbol": "ADAUSDT", "signal_score": 0.85, "signal_type_1h": "flip_bullish", "reason": "ioc_no_fill"},
        ]
    )

    result = diagnose_ioc_fallback(summary, pending_cancels)

    assert result["root_cause_breakdown"]["ioc_no_fill_total"] == 2
    assert result["root_cause_breakdown"]["fallback_not_reached_after_ioc_cancel"] == 2
    assert result["by_signal_type"]["red_bar_growing"] == 1
    assert result["signal_score_stats"]["avg"] == pytest.approx(0.90, rel=1e-6)


def _analysis(
    *,
    signal: MACDSignalV2,
    price: float = 100.0,
    high: float = 100.0,
    low: float = 100.0,
    close: float = 100.0,
    close_price: float = 100.0,
) -> dict:
    return {
        "signal": signal,
        "price": price,
        "time": pd.Timestamp("2026-04-25 14:15:00"),
        "row_15m": pd.Series(
            {
                "open": price,
                "high": high,
                "low": low,
                "close": close,
                "bb_upper": 101.0,
                "bb_middle": 100.0,
                "bb_lower": 99.0,
            }
        ),
        "row_1h": pd.Series(
            {
                "bb_upper": 101.0,
                "bb_middle": 100.0,
                "bb_lower": 99.0,
                "close": close_price,
            }
        ),
        "cvd_veto_context": {},
        "cvd_context": {},
    }


def _base_position(
    engine: BacktestEngine,
    *,
    symbol: str = "SOLUSDT",
    side: str = "long",
    margin: float = 1000.0,
    stop_price: float = 95.0,
) -> None:
    engine.positions[symbol] = {
        "side": side,
        "entry_price": 100.0,
        "entry_notional": 3000.0,
        "position_value": margin,
        "margin": margin,
        "initial_margin": margin,
        "remaining_fraction": 1.0,
        "leverage": 3,
        "stop_price": stop_price,
        "take_profit": None,
        "take_profit_levels": [],
        "entry_time": pd.Timestamp("2026-04-25 14:00:00"),
        "signal_score": 0.90,
        "competition_score": 0.90,
        "signal_type_1h": "red_bar_growing",
        "is_trial_entry": False,
        "entry_scale": 1.0,
        "session_position_scale": 1.0,
        "vwap_score": 0.03,
        "vwap_state": "long_dual_support",
        "vwap_location_score": 0.60,
        "ema_multiplier": 1.2,
        "ema_status": "strong",
        "realized_pnl_accum": 0.0,
    }


def test_simulated_live_close_layers_fires_light_take_profit_once() -> None:
    runtime_cfg = {
        "risk": {
            "conflict_protection": {
                "light_take_profit_enabled": True,
                "light_take_profit_only_range": False,
                "light_take_profit_min_hold_seconds": 180,
                "light_take_profit_min_mfe": 0.0025,
                "light_take_profit_min_pnl": 0.001,
                "light_take_profit_pct": 0.75,
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=True, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    engine.live_risk_manager = SimpleNamespace(check_position_protection=lambda **kwargs: {"risk_state": "HOLD"})
    _base_position(engine)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        details={"market_regime": "TREND"},
    )

    closed = engine.check_stops("SOLUSDT", _analysis(signal=signal, price=100.5, high=100.5, low=100.1, close=100.3))

    assert closed is False
    assert "SOLUSDT" in engine.positions
    assert engine.positions["SOLUSDT"]["margin"] == pytest.approx(250.0, rel=1e-6)
    assert engine.live_close_audit["light_take_profit_triggered"] == 1
    assert engine.live_close_audit["light_take_profit_reduced_margin"] == pytest.approx(750.0, rel=1e-6)


def test_simulated_live_close_layers_conflict_reduce_partially_closes_position() -> None:
    runtime_cfg = {
        "risk": {
            "conflict_protection": {
                "light_confirm_bars": 1,
                "hard_confirm_bars": 1,
                "cooldown_sec": 0,
                "state_reduce_pct": 0.35,
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=True, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    engine.live_risk_manager = SimpleNamespace(
        check_position_protection=lambda **kwargs: {
            "risk_state": "REDUCE",
            "reduce_position_pct": 0.35,
            "force_break_even": True,
        }
    )
    _base_position(engine)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        details={
            "market_regime": "TREND",
            "macd_hist_norm": -0.20,
            "cvd_norm": -0.98,
            "ev_direction": "SHORT_ONLY",
            "ev_score": 0.8,
            "lw_direction": "SHORT_ONLY",
            "lw_score": 0.8,
            "trap_score": 0.0,
            "close_price": 99.3,
            "mtf_scores": {"1m": -1.0, "3m": -1.0, "5m": -1.0},
        },
    )

    closed = engine.check_stops("SOLUSDT", _analysis(signal=signal, price=99.3, high=100.0, low=99.2, close=99.3, close_price=99.3))

    assert closed is False
    assert "SOLUSDT" in engine.positions
    assert engine.positions["SOLUSDT"]["margin"] < 1000.0
    assert engine.live_close_audit["conflict_reduce_triggered"] == 1


def test_simulated_live_close_layers_conflict_exit_closes_remaining_position() -> None:
    runtime_cfg = {
        "risk": {
            "conflict_protection": {
                "light_confirm_bars": 1,
                "hard_confirm_bars": 1,
                "cooldown_sec": 0,
                "state_circuit_trap_bars": 1,
                "state_circuit_trap_hard": 0.9,
                "state_circuit_trap_hard_bars": 1,
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=True, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    engine.live_risk_manager = SimpleNamespace(
        check_position_protection=lambda **kwargs: {
            "risk_state": "CIRCUIT_EXIT",
            "reduce_position_pct": 1.0,
            "force_break_even": False,
        }
    )
    _base_position(engine)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        details={
            "market_regime": "TREND",
            "macd_hist_norm": 0.02,
            "cvd_norm": -0.10,
            "ev_direction": "BOTH",
            "ev_score": 0.0,
            "lw_direction": "BOTH",
            "lw_score": 0.0,
            "trap_score": 0.96,
        },
    )

    closed = engine.check_stops("SOLUSDT", _analysis(signal=signal, price=100.0, high=100.2, low=99.8, close=100.0))

    assert closed is True
    assert "SOLUSDT" not in engine.positions
    assert engine.live_close_audit["conflict_exit_triggered"] == 1


def test_simulated_live_close_layers_force_break_even_updates_stop_once() -> None:
    runtime_cfg = {
        "risk": {
            "conflict_protection": {
                "light_confirm_bars": 1,
                "hard_confirm_bars": 1,
                "cooldown_sec": 0,
                "state_reduce_pct": 0.35,
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=True, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    engine.live_risk_manager = SimpleNamespace(
        check_position_protection=lambda **kwargs: {
            "risk_state": "REDUCE",
            "reduce_position_pct": 0.35,
            "force_break_even": True,
        }
    )
    _base_position(engine, stop_price=95.0)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        details={
            "market_regime": "TREND",
            "macd_hist_norm": -0.20,
            "cvd_norm": -0.98,
            "ev_direction": "SHORT_ONLY",
            "ev_score": 0.8,
            "lw_direction": "SHORT_ONLY",
            "lw_score": 0.8,
            "trap_score": 0.0,
            "close_price": 99.3,
            "mtf_scores": {"1m": -1.0, "3m": -1.0, "5m": -1.0},
        },
    )

    engine.check_stops("SOLUSDT", _analysis(signal=signal, price=99.3, high=100.0, low=99.2, close=99.3, close_price=99.3))

    assert engine.positions["SOLUSDT"]["stop_price"] == pytest.approx(100.0, rel=1e-6)
    assert engine.live_close_audit["conflict_force_breakeven_applied"] == 1


def test_holding_time_exit_closes_stale_low_profit_position() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "exit_management": {
                    "holding_time_exit": {
                        "enabled": True,
                        "max_holding_hours": 96,
                        "min_pnl_to_hold": 0.005,
                    }
                }
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=False, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    _base_position(engine)
    engine.positions["SOLUSDT"]["entry_time"] = pd.Timestamp("2026-04-21 14:00:00")
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        details={},
    )

    closed = engine.check_stops(
        "SOLUSDT",
        _analysis(
            signal=signal,
            price=100.2,
            high=100.3,
            low=100.0,
            close=100.2,
            close_price=100.2,
        ),
    )

    assert closed is True
    assert "SOLUSDT" not in engine.positions
    assert engine.trades[-1]["reason"] == "holding_time_exit"


def test_macd_1h_flip_exit_closes_profitable_position() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "exit_management": {
                    "macd_1h_flip_exit": {
                        "enabled": True,
                        "confirm_bars": 2,
                        "flip_min_magnitude": 0.0003,
                        "min_profit_to_early_exit": 0.006,
                    }
                }
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=False, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    _base_position(engine)
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        signal_type_1h="red_bar_growing",
        details={},
    )

    closed = engine.check_stops(
        "SOLUSDT",
        _analysis(
            signal=signal,
            price=100.8,
            high=100.9,
            low=100.6,
            close=100.8,
            close_price=100.8,
        )
        | {
            "signal": MACDSignalV2(
                direction="neutral",
                signal_score=0.0,
                signal_type_1h="red_bar_growing",
                details={
                    "macd_histogram_1h_current": -0.0005,
                    "macd_histogram_1h_history": [-0.0006, -0.0005],
                },
            )
        },
    )

    assert closed is True
    assert "SOLUSDT" not in engine.positions
    assert engine.trades[-1]["reason"] == "macd_1h_flip_exit"


def test_rsi_overheat_exit_reduces_half_position() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "exit_management": {
                    "rsi_overheat_exit": {
                        "enabled": True,
                        "rsi_1h_overheat": 78.0,
                        "min_mfe_to_trigger": 0.012,
                        "partial_exit_ratio": 0.50,
                    }
                }
            }
        }
    }
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], simulate_live_close_layers=False, breakeven_enabled=False),
        MACDStrategyV2Config(enable_4h_shrink_exit=False),
        runtime_config=runtime_cfg,
    )
    _base_position(engine)
    signal = MACDSignalV2(
        direction="neutral",
        signal_score=0.0,
        signal_type_1h="red_bar_growing",
        details={
            "rsi_1h": 80.0,
            "macd_histogram_1h_current": 0.0010,
            "macd_histogram_1h_prev": 0.0014,
        },
    )

    closed = engine.check_stops(
        "SOLUSDT",
        _analysis(
            signal=signal,
            price=101.0,
            high=101.4,
            low=100.7,
            close=101.0,
            close_price=101.0,
        ),
    )

    assert closed is False
    assert "SOLUSDT" in engine.positions
    assert engine.positions["SOLUSDT"]["margin"] == pytest.approx(500.0, rel=1e-6)
    assert engine.trades[-1]["reason"] == "rsi_overheat_exit"
