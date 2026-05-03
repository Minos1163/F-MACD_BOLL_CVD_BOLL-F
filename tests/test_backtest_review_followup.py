from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.backtest_macd_v2 import (
    BacktestConfig,
    BacktestEngine,
    MACDSignalV2,
    MACDStrategyV2Config,
    apply_backtest_profile,
    main as backtest_main,
    resolve_runtime_config_for_backtest,
)
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
