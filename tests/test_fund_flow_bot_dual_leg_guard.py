from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.fund_flow_bot import TradingBot
from src.app.fund_flow_bot import ExitCooldownRegistry
from src.fund_flow.exit_signal_guard import PositionExitSignalGuard
from src.fund_flow.models import FundFlowDecision, Operation


class _Broker:
    def __init__(self, hedge_mode: bool) -> None:
        self.hedge_mode = hedge_mode

    def get_hedge_mode(self) -> bool:
        return self.hedge_mode


class _Client:
    def __init__(self, hedge_mode: bool = True) -> None:
        self.broker = _Broker(hedge_mode)


def _bot(config: Dict[str, Any] | None = None, hedge_mode: bool = True) -> TradingBot:
    bot = TradingBot.__new__(TradingBot)
    bot.config = config or {
        "fund_flow": {
            "dual_leg_extreme_hedge": {
                "enabled": True,
                "min_unrealized_loss_ratio": 0.01,
                "min_signal_score": 0.70,
                "min_regime_atr_pct": 0.01,
                "max_target_portion": 0.08,
                "leverage_cap": 2,
            }
        }
    }
    bot.client = _Client(hedge_mode=hedge_mode)
    bot._dca_blocked_by_exit_guard = set()
    return bot


def test_timeframe_context_normalizes_live_ema_aliases_for_quadrant_engine() -> None:
    bot = _bot({"fund_flow": {"decision_timeframe": "15m"}})
    flow_snapshot = Mock(timeframes={})
    raw_context = {
        "trend_filters_by_timeframe": {
            "4h": {
                "close": 100.0,
                "ema_fast": 101.0,
                "ema_slow": 99.0,
                "ema200": 95.0,
                "macd_hist_series": [0.01, 0.02, 0.03],
            },
            "1h": {
                "close": 100.0,
                "ema21": 100.5,
                "ema55": 98.0,
                "ema_200": 90.0,
            },
        }
    }

    out = bot._apply_timeframe_context(raw_context, flow_snapshot)

    assert out["timeframes"]["4h"]["ema20"] == pytest.approx(101.0)
    assert out["timeframes"]["4h"]["ema50"] == pytest.approx(99.0)
    assert out["timeframes"]["4h"]["ema200"] == pytest.approx(95.0)
    assert out["timeframes"]["1h"]["ema20"] == pytest.approx(100.5)
    assert out["timeframes"]["1h"]["ema50"] == pytest.approx(98.0)
    assert out["timeframes"]["1h"]["ema200"] == pytest.approx(90.0)


def test_timeframe_context_keeps_exact_positive_ema_fields_over_aliases() -> None:
    bot = _bot({"fund_flow": {"decision_timeframe": "4h"}})
    flow_snapshot = Mock(timeframes={})
    raw_context = {
        "trend_filters_by_timeframe": {
            "4h": {
                "close": 100.0,
                "ema20": 102.0,
                "ema50": 98.0,
                "ema_fast": 88.0,
                "ema_slow": 77.0,
                "ema200": 90.0,
            }
        }
    }

    out = bot._apply_timeframe_context(raw_context, flow_snapshot)

    assert out["timeframes"]["4h"]["ema20"] == pytest.approx(102.0)
    assert out["timeframes"]["4h"]["ema50"] == pytest.approx(98.0)
    assert out["timeframes"]["4h"]["ema200"] == pytest.approx(90.0)


def test_quadrant_multi_bar_live_fetches_required_direction_timeframes() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "decision_timeframe": "15m",
                "strategy_mode": "quadrant_resonance",
                "quadrant_resonance": {
                    "entry": {
                        "direction_model": "multi_bar_slope",
                        "direction_4h_lookback_bars": 50,
                        "direction_1h_lookback_bars": 50,
                        "direction_15m_lookback_bars": 30,
                    }
                },
            }
        }
    )
    calls: list[tuple[str, int]] = []
    market_data = Mock()
    market_data.get_realtime_market_data.return_value = {}

    def _trend_filter(symbol: str, interval: str, limit: int) -> dict:
        calls.append((interval, limit))
        return {"close": 100.0, "close_series": [100.0] * limit}

    market_data.get_trend_filter_metrics.side_effect = _trend_filter
    market_data.get_order_flow_snapshot.return_value = {}
    bot.market_data = market_data
    bot._extract_orderbook_flow = Mock(return_value={})
    bot._closed_15m_returns_4bar_from_symbol = Mock(return_value=[])

    result = bot.get_market_data_for_symbol("FETUSDT")

    requested = {interval: limit for interval, limit in calls}
    assert requested["15m"] >= 30
    assert requested["1h"] >= 50
    assert requested["4h"] >= 50
    assert set(("15m", "1h", "4h")).issubset(result["trend_filters_by_timeframe"])


def test_quadrant_resonance_live_signal_score_uses_direction_execution_score() -> None:
    bot = _bot()
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="FETUSDT",
        metadata={
            "strategy_mode": "quadrant_resonance",
            "direction_score": 0.44,
            "signal_score": 0.44,
            "competition_score": 0.44,
            "legacy_resonance_score": 0.20,
            "long_score": 0.0,
            "short_score": 0.0,
        },
    )

    assert bot._decision_signal_score(decision) == pytest.approx(0.44)


def test_extreme_dual_leg_guard_allows_opposite_hedge_only_when_loss_and_shock_are_large() -> None:
    bot = _bot()
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=4,
        metadata={"signal_score": 0.82, "regime_atr_pct": 0.018, "regime": "TREND"},
    )
    position = {"side": "LONG", "entry_price": 100.0, "mark_price": 97.0, "amount": 1.0}

    allowed, adjusted, meta = bot._maybe_allow_extreme_dual_leg_hedge(
        symbol="BTCUSDT",
        position=position,
        decision=decision,
        current_price=97.0,
    )

    assert allowed is True
    assert adjusted.target_portion_of_balance == 0.08
    assert adjusted.leverage == 2
    assert adjusted.metadata["dual_leg_extreme_hedge_allowed"] is True
    assert meta["reason"] == "allowed"


def test_extreme_dual_leg_guard_blocks_when_account_is_not_hedge_mode() -> None:
    bot = _bot(hedge_mode=False)
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=4,
        metadata={"signal_score": 0.90, "regime_atr_pct": 0.03},
    )
    position = {"side": "LONG", "entry_price": 100.0, "mark_price": 95.0, "amount": 1.0}

    allowed, adjusted, meta = bot._maybe_allow_extreme_dual_leg_hedge(
        symbol="BTCUSDT",
        position=position,
        decision=decision,
        current_price=95.0,
    )

    assert allowed is False
    assert adjusted is decision
    assert meta["reason"] == "hedge_mode_disabled"


def test_extreme_dual_leg_guard_blocks_when_existing_position_is_not_losing_enough() -> None:
    bot = _bot()
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="BTCUSDT",
        target_portion_of_balance=0.35,
        leverage=4,
        metadata={"signal_score": 0.90, "regime_atr_pct": 0.03},
    )
    position = {"side": "LONG", "entry_price": 100.0, "mark_price": 99.5, "amount": 1.0}

    allowed, _adjusted, meta = bot._maybe_allow_extreme_dual_leg_hedge(
        symbol="BTCUSDT",
        position=position,
        decision=decision,
        current_price=99.5,
    )

    assert allowed is False
    assert meta["reason"] == "loss_ratio=0.0050"


def test_probe_floor_rescue_shadow_records_candidate_without_changing_decision() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "probe_floor_rescue": {
                    "enabled": True,
                    "shadow_mode": True,
                    "min_score_threshold": 0.80,
                    "probe_portion": 0.06,
                    "probe_leverage_cap": 2,
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="WLDUSDT",
        target_portion_of_balance=0.001,
        leverage=4,
        metadata={"signal_score": 0.85},
    )

    adjusted, meta = bot._apply_probe_floor_rescue(decision=decision, min_open_portion=0.06)

    assert adjusted is decision
    assert adjusted.target_portion_of_balance == pytest.approx(0.001)
    assert adjusted.metadata["probe_floor_rescue_shadow"] is True
    assert meta["shadow_mode"] is True
    assert meta["probe_portion"] == pytest.approx(0.06)


def test_probe_floor_rescue_live_promotes_high_score_signal_to_probe_floor() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "probe_floor_rescue": {
                    "enabled": True,
                    "shadow_mode": False,
                    "min_score_threshold": 0.80,
                    "probe_portion": 0.06,
                    "probe_leverage_cap": 2,
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="WLDUSDT",
        target_portion_of_balance=0.001,
        leverage=4,
        metadata={"signal_score": 0.85},
    )

    adjusted, meta = bot._apply_probe_floor_rescue(decision=decision, min_open_portion=0.06)

    assert adjusted.target_portion_of_balance == pytest.approx(0.06)
    assert adjusted.leverage == 2
    assert adjusted.metadata["probe_floor_rescue_applied"] is True
    assert meta["applied"] is True


def test_probe_floor_rescue_live_allows_probe_specific_min_open() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "probe_floor_rescue": {
                    "enabled": True,
                    "shadow_mode": False,
                    "min_score_threshold": 0.80,
                    "probe_min_open_portion": 0.042,
                    "probe_leverage_cap": 2,
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ALGOUSDT",
        target_portion_of_balance=0.001,
        leverage=4,
        metadata={"signal_score": 0.85},
    )

    adjusted, meta = bot._apply_probe_floor_rescue(decision=decision, min_open_portion=0.06)

    assert adjusted.target_portion_of_balance == pytest.approx(0.042)
    assert adjusted.leverage == 2
    assert adjusted.metadata["probe_floor_rescue_applied"] is True
    assert adjusted.metadata["probe_floor_rescue_probe_portion"] == pytest.approx(0.042)
    assert meta["applied"] is True
    assert meta["probe_portion"] == pytest.approx(0.042)


def test_min_open_notional_gate_allows_small_portion_when_notional_is_sufficient() -> None:
    bot = _bot({"fund_flow": {"min_open_notional_usdt": 5.0}})
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="JSTUSDT",
        target_portion_of_balance=0.05,
        leverage=3,
        metadata={"signal_score": 0.86},
    )

    allowed, meta = bot._allows_entry_below_min_open_by_notional(
        decision=decision,
        min_open_portion=0.06,
        account_equity=110.0,
    )

    assert allowed is True
    assert meta["notional_usdt"] == pytest.approx(5.5)
    assert meta["min_open_notional_usdt"] == pytest.approx(5.0)


def test_min_open_notional_gate_blocks_true_micro_position() -> None:
    bot = _bot({"fund_flow": {"min_open_notional_usdt": 5.0}})
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="JSTUSDT",
        target_portion_of_balance=0.0013,
        leverage=3,
        metadata={"signal_score": 0.86},
    )

    allowed, meta = bot._allows_entry_below_min_open_by_notional(
        decision=decision,
        min_open_portion=0.06,
        account_equity=110.0,
    )

    assert allowed is False
    assert meta["notional_usdt"] == pytest.approx(0.143)
    assert meta["reason"] == "notional_below_min_open"


def test_micro_notional_gate_blocks_entry_below_ten_cents() -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="WLDUSDT",
        target_portion_of_balance=0.0009,
        leverage=3,
        metadata={"signal_score": 0.86},
    )

    allowed, meta = bot._allows_entry_above_micro_notional(
        decision=decision,
        account_equity=100.0,
    )

    assert allowed is False
    assert meta["reason"] == "micro_notional_block"
    assert meta["estimated_notional_usdt"] == pytest.approx(0.09)


def test_micro_notional_gate_allows_entry_at_ten_cents_and_ignores_close() -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    entry = FundFlowDecision(
        operation=Operation.BUY,
        symbol="WLDUSDT",
        target_portion_of_balance=0.001,
        leverage=3,
        metadata={"signal_score": 0.86},
    )
    close = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="WLDUSDT",
        target_portion_of_balance=1.0,
        leverage=3,
        metadata={"signal_score": 0.0},
    )

    entry_allowed, entry_meta = bot._allows_entry_above_micro_notional(
        decision=entry,
        account_equity=100.0,
    )
    close_allowed, close_meta = bot._allows_entry_above_micro_notional(
        decision=close,
        account_equity=0.01,
    )

    assert entry_allowed is True
    assert entry_meta["estimated_notional_usdt"] == pytest.approx(0.10)
    assert close_allowed is True
    assert close_meta["reason"] == "not_entry"


def test_micro_margin_gate_blocks_entry_below_one_usdt_margin() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    entry = FundFlowDecision(
        operation=Operation.SELL,
        symbol="PUMPUSDT",
        target_portion_of_balance=0.008,
        leverage=9,
        metadata={"signal_score": 0.60},
    )
    close = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="PUMPUSDT",
        target_portion_of_balance=1.0,
        leverage=9,
        metadata={"signal_score": 0.0},
    )

    entry_allowed, entry_meta = bot._allows_entry_above_micro_notional(
        decision=entry,
        account_equity=111.18,
    )
    close_allowed, close_meta = bot._allows_entry_above_micro_notional(
        decision=close,
        account_equity=0.01,
    )

    assert entry_allowed is False
    assert entry_meta["reason"] == "micro_margin_block"
    assert entry_meta["estimated_notional_usdt"] == pytest.approx(0.88944)
    assert entry_meta["estimated_margin_usdt"] == pytest.approx(0.88944)
    assert close_allowed is True
    assert close_meta["reason"] == "not_entry"


def test_micro_margin_gate_matches_execution_router_margin_semantics() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    entry = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ONDOUSDT",
        target_portion_of_balance=0.02,
        leverage=3,
        metadata={"signal_score": 0.60},
    )

    allowed, meta = bot._allows_entry_above_micro_notional(
        decision=entry,
        account_equity=53.5,
    )

    assert allowed is True
    assert meta["reason"] == "notional_check_passed"
    assert meta["estimated_margin_usdt"] == pytest.approx(1.07)


def test_entry_audit_uses_execution_router_margin_semantics_without_gate_meta() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    entry = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ONDOUSDT",
        target_portion_of_balance=0.02,
        leverage=3,
        metadata={"signal_score": 0.60},
    )

    payload = bot._build_entry_exit_audit_payload(
        stage="pre_execution",
        symbol="ONDOUSDT",
        decision=entry,
        account_summary={"equity": 53.5},
        current_price=1.0,
    )

    assert payload["sizing"]["estimated_notional_usdt"] == pytest.approx(1.07)
    assert payload["sizing"]["estimated_margin_usdt"] == pytest.approx(1.07)


def test_entry_audit_includes_quadrant_defense_debug_metadata() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    debug = {
        "quadrant_4h": "DEFENSE",
        "ema20_4h": 101.0,
        "ema50_4h": 100.0,
        "ema200_4h": 100.2,
        "ema_state_4h": 0,
        "macd_hist_4h_last3": [0.03, 0.02, 0.01],
        "macd_pos_strength_4h": False,
        "macd_neg_strength_4h": False,
        "blocked_reason_detail": "macd_not_strengthening",
        "ema_close_to_alignment": True,
    }
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="ICPUSDT",
        reason="quadrant_defense_no_entry",
        metadata={
            "stage": "blocked",
            "strategy_mode": "quadrant_resonance",
            "quadrant_debug": debug,
            "blocked_reason_detail": "macd_not_strengthening",
        },
    )

    payload = bot._build_entry_exit_audit_payload(
        stage="pre_execution",
        symbol="ICPUSDT",
        decision=decision,
        account_summary={"equity": 98.0},
        current_price=6.0,
    )

    assert payload["strategy"]["blocked_reason_detail"] == "macd_not_strengthening"
    assert payload["signal"]["quadrant_debug"] == debug


def test_entry_audit_expands_quadrant_direction_quality_fields() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="HYPEUSDT",
        target_portion_of_balance=0.042,
        leverage=3,
        reason="quadrant_resonance_probe_no_15m",
        metadata={
            "strategy_mode": "quadrant_resonance",
            "signal_score": 0.90,
            "signal_score_threshold": 0.85,
            "factor_scores": {"quadrant": 0.5, "ema_1h": 0.2, "macd_1h": 0.15, "rsi_15m": 0.05},
            "entry_rsi_15m": 72.0,
            "entry_rsi_1h": 69.0,
            "macd_hist_15m_last3": [0.03, 0.02, 0.01],
            "macd_hist_1h_last3": [0.04, 0.03, 0.02],
            "macd_hist_15m_strengthening": False,
            "macd_hist_1h_strengthening": False,
            "entry_15m_detail": {"ok": False, "near_ema": True, "hist_cross": False},
            "probe_no_15m_veto_reasons": ["breadth_zero_confirm_invalid_2"],
            "requested_leverage": 3,
            "effective_leverage": 9,
        },
    )

    payload = bot._build_entry_exit_audit_payload(
        stage="pre_execution",
        symbol="HYPEUSDT",
        decision=decision,
        account_summary={"equity": 98.0},
        current_price=62.42,
        flow_context={"market_breadth": {"confirm_count": 0, "invalid_count": 2}},
    )

    assert payload["signal"]["factor_scores"]["macd_1h"] == pytest.approx(0.15)
    assert payload["signal"]["entry_rsi_15m"] == pytest.approx(72.0)
    assert payload["signal"]["macd_hist_15m_last3"] == [0.03, 0.02, 0.01]
    assert payload["signal"]["entry_15m_detail"]["ok"] is False
    assert payload["gates"]["probe_no_15m_veto_reasons"] == ["breadth_zero_confirm_invalid_2"]
    assert payload["sizing"]["requested_leverage"] == 3
    assert payload["sizing"]["effective_leverage"] == 9


def test_entry_audit_includes_watchlist_and_probe_quality_metadata() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="JSTUSDT",
        reason="probe_no_15m_direction_veto",
        metadata={
            "signal_score": 0.90,
            "signal_score_threshold": 0.85,
            "entry_15m_quality_score": 0.55,
            "entry_15m_quality_bucket": "watch",
            "entry_15m_missing_conditions": ["hist_cross"],
            "probe_resonance_score": 0.65,
            "probe_flow_alignment_score": -0.12,
            "probe_no_15m_veto_reasons": ["breadth_zero_confirm_invalid_2"],
            "watchlist_intent": {
                "enabled": True,
                "dry_run": True,
                "symbol": "JSTUSDT",
                "side": "long",
                "score": 0.90,
                "candidate_reason": "reversible_probe_veto",
                "missing_conditions": ["hist_cross"],
                "ttl_bars": 2,
            },
            "quadrant_state": "recovering",
            "quadrant_recovering_direction": "long",
            "watchlist_update": {"result": "added", "symbol": "JSTUSDT"},
            "watchlist_review": {"result": "pending", "ttl_remaining_bars": 3},
        },
    )

    payload = bot._build_entry_exit_audit_payload(
        stage="post_execution",
        symbol="JSTUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
    )

    assert payload["signal"]["entry_15m_quality_score"] == 0.55
    assert payload["signal"]["entry_15m_quality_bucket"] == "watch"
    assert payload["signal"]["entry_15m_missing_conditions"] == ["hist_cross"]
    assert payload["signal"]["watchlist_intent"]["candidate_reason"] == "reversible_probe_veto"
    assert payload["signal"]["watchlist_update"]["result"] == "added"
    assert payload["signal"]["watchlist_review"]["result"] == "pending"
    assert payload["signal"]["quadrant_state"] == "recovering"
    assert payload["signal"]["quadrant_recovering_direction"] == "long"
    assert payload["gates"]["probe_resonance_score"] == 0.65
    assert payload["gates"]["probe_flow_alignment_score"] == -0.12


def test_entry_audit_includes_direction_gate_metadata() -> None:
    bot = _bot({"fund_flow": {"min_entry_margin_usdt": 1.0}})
    direction_gate = {
        "ok": False,
        "reason": "multi_bar_direction_no_entry",
        "blocked_reason": "anchor_timeframe_not_aligned",
        "direction_model": "multi_bar_slope",
        "direction": "long",
        "direction_score": 0.12,
        "scores": {"4h": 0.22, "1h": -0.10, "15m": 0.35},
        "aligned_scores": {"4h": 0.22, "1h": -0.10, "15m": 0.35},
        "history_counts": {"4h": 50, "1h": 50, "15m": 30},
    }
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="JUPUSDT",
        reason="multi_bar_direction_no_entry",
        metadata={
            "signal_score": 0.0,
            "signal_score_threshold": 0.85,
            "direction_gate": direction_gate,
        },
    )

    payload = bot._build_entry_exit_audit_payload(
        stage="post_execution",
        symbol="JUPUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
    )

    assert payload["gates"]["direction_gate"] == direction_gate
    assert payload["gates"]["direction_gate"]["blocked_reason"] == "anchor_timeframe_not_aligned"
    assert payload["gates"]["direction_gate"]["scores"]["1h"] == pytest.approx(-0.10)


def test_live_slow_bull_fee_fragmentation_blocks_small_probe_notional() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "slow_bull_live_test": {
                    "enabled": True,
                    "fee_fragmentation_control": {
                        "enabled": True,
                        "min_probe_notional": 5.0,
                    },
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ICPUSDT",
        target_portion_of_balance=0.04,
        leverage=3,
        metadata={"stage": "continuation_long", "is_trial_entry": True},
    )

    allowed, meta = bot._allows_entry_above_live_slow_bull_fee_floor(
        decision=decision,
        account_equity=100.0,
    )

    assert allowed is False
    assert meta["reason"] == "slow_bull_min_probe_notional_block"
    assert meta["estimated_notional_usdt"] == pytest.approx(4.0)


def test_live_slow_bull_fee_fragmentation_does_not_block_close() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "slow_bull_live_test": {
                    "enabled": True,
                    "fee_fragmentation_control": {"enabled": True, "min_probe_notional": 5.0},
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="ICPUSDT",
        target_portion_of_balance=1.0,
        leverage=3,
        metadata={"stage": "continuation_long"},
    )

    allowed, meta = bot._allows_entry_above_live_slow_bull_fee_floor(
        decision=decision,
        account_equity=1.0,
    )

    assert allowed is True
    assert meta["reason"] == "not_entry"


def test_execute_and_log_decision_writes_entry_exit_audit_events(tmp_path: Path) -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    bot.logs_dir = str(tmp_path)
    bot.fund_flow_attribution_engine = Mock()
    bot.fund_flow_execution_router = Mock()
    bot.fund_flow_execution_router.execute_decision.return_value = {
        "status": "success",
        "order": {"orderId": "42"},
        "quantity": 1.0,
    }
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = {"side": "LONG", "amount": 1.0, "entry_price": 1.0}
    bot._post_execution_protection_hook = Mock(return_value={})
    bot._update_dca_state_after_execution = Mock()
    bot._safe_storage_call = Mock()
    bot._write_trade_fill_log = Mock()
    bot._has_pending_close_order = Mock(return_value=False)
    bot.trade_count = 0
    bot._opened_symbols_this_cycle = set()
    bot._position_first_seen_ts = {}
    bot._position_extrema_by_pos = {}

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="WLDUSDT",
        target_portion_of_balance=0.02,
        leverage=3,
        reason="slow_bull_continuation",
        metadata={
            "signal_score": 0.60,
            "source": "continuation_long",
            "signal_type_1h": "yellow_bar_growing",
            "signal_type_4h": "red_bar_growing",
            "entry_type_15m": "bullish_momentum",
            "direction_reason": "slow_bull_breadth+symbol_momentum",
            "entry_reason": "ret30_ret60_rsi_ema_pass",
            "market_breadth": {"is_slow_bull": True, "mode": "alt_breadth_led", "breadth_ratio": 0.86},
            "btc_beta_risk": {"use_btc": True, "risk_score": 0},
            "btc_entry_regime_gate": {"action": "PASS", "reason": "btc_not_down"},
            "micro_notional_gate": {"reason": "notional_check_passed"},
            "micro_margin_gate": {"reason": "margin_check_passed", "estimated_margin_usdt": 0.6667},
        },
    )

    bot._execute_and_log_decision(
        symbol="WLDUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
        current_price=1.0,
        position=None,
        flow_context={"market_breadth": {"is_slow_bull": True}},
        trigger_type="test",
        trigger_id="t1",
        trigger_context={"trigger_type": "test", "trigger_id": "t1"},
        portfolio={},
    )

    rows = (tmp_path / "fund_flow_entry_exit_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert '"stage":"pre_execution"' in rows[0]
    assert '"stage":"post_execution"' in rows[1]
    assert '"strategy_source":"continuation_long"' in rows[0]
    assert '"estimated_notional_usdt":2.0' in rows[0]
    assert '"mfe_pct"' in rows[1]
    assert '"mae_pct"' in rows[1]

    pre = json.loads(rows[0])
    post = json.loads(rows[1])
    assert pre["strategy"]["method"] == "continuation_long"
    assert pre["strategy"]["direction_reason"] == "slow_bull_breadth+symbol_momentum"
    assert pre["strategy"]["decision_reason"] == "ret30_ret60_rsi_ema_pass"
    assert pre["signal"]["type_1h"] == "yellow_bar_growing"
    assert pre["signal"]["type_4h"] == "red_bar_growing"
    assert pre["signal"]["entry_15m"] == "bullish_momentum"
    assert pre["gates"]["btc_entry_regime_gate"]["action"] == "PASS"
    assert pre["sizing"]["estimated_margin_usdt"] == pytest.approx(0.6667)
    assert pre["sizing"]["micro_margin_gate"]["reason"] == "margin_check_passed"
    assert post["execution"]["status"] == "success"
    assert post["execution"]["order"]["orderId"] == "42"


def test_execute_and_log_decision_writes_fill_reconciled_audit_when_pending_order_has_fills(tmp_path: Path) -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    bot.logs_dir = str(tmp_path)
    bot.fund_flow_attribution_engine = Mock()
    bot.fund_flow_execution_router = Mock()
    bot.fund_flow_execution_router.execute_decision.return_value = {
        "status": "pending",
        "message": "entry submitted",
        "order": {"orderId": 8172959957, "status": "NEW", "executedQty": "0.00"},
        "quantity": 0.0,
    }
    bot._fetch_order_trade_fills = Mock(return_value=[{"orderId": 8172959957, "id": 123, "qty": "0.5", "price": "62.4637"}])
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = {"side": "LONG", "amount": 0.5, "entry_price": 62.4637}
    bot._post_execution_protection_hook = Mock(return_value={"status": "repaired", "message": "protection_repaired"})
    bot._update_dca_state_after_execution = Mock()
    bot._safe_storage_call = Mock()
    bot._write_trade_fill_log = Mock()
    bot._has_pending_close_order = Mock(return_value=False)
    bot.trade_count = 0
    bot._opened_symbols_this_cycle = set()
    bot._position_first_seen_ts = {}
    bot._position_extrema_by_pos = {}

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="HYPEUSDT",
        target_portion_of_balance=0.042,
        leverage=9,
        reason="quadrant_resonance_probe_no_15m",
        metadata={"signal_score": 0.90},
    )

    bot._execute_and_log_decision(
        symbol="HYPEUSDT",
        decision=decision,
        account_summary={"equity": 98.0},
        current_price=62.42,
        position=None,
        flow_context={},
        trigger_type="test",
        trigger_id="hype-entry",
        trigger_context={"trigger_type": "test", "trigger_id": "hype-entry"},
        portfolio={},
    )

    rows = [json.loads(line) for line in (tmp_path / "fund_flow_entry_exit_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["pre_execution", "post_execution", "entry_order_reconciled"]
    assert rows[2]["execution"]["status"] == "success"
    assert rows[2]["execution"]["message"] == "pending_order_fills_confirmed"
    assert rows[2]["execution"]["fills"][0]["qty"] == "0.5"


def test_execute_and_log_decision_writes_entry_order_reconciled_audit_when_pending_ioc_expired(tmp_path: Path) -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    bot.logs_dir = str(tmp_path)
    bot.fund_flow_attribution_engine = Mock()
    bot.fund_flow_execution_router = Mock()
    bot.fund_flow_execution_router.execute_decision.return_value = {
        "status": "pending",
        "message": "entry submitted",
        "order": {
            "orderId": 21904933202,
            "status": "NEW",
            "executedQty": "0",
            "price": "0.5237000",
            "side": "BUY",
            "timeInForce": "IOC",
        },
        "quantity": 0.0,
    }
    bot._fetch_order_trade_fills = Mock(return_value=[])
    bot._fetch_entry_order_final_state = Mock(
        return_value={
            "symbol": "WLDUSDT",
            "orderId": 21904933202,
            "status": "EXPIRED",
            "executedQty": "0",
            "avgPrice": "0",
            "price": "0.5237000",
            "side": "BUY",
            "timeInForce": "IOC",
            "updateTime": 1780508715000,
        }
    )
    bot._extract_orderbook_flow = Mock(
        return_value={
            "best_bid": 0.5240,
            "best_ask": 0.5246,
            "spread_pct": 0.001145,
        }
    )
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = None
    bot._post_execution_protection_hook = Mock(return_value={})
    bot._update_dca_state_after_execution = Mock()
    bot._safe_storage_call = Mock()
    bot._write_trade_fill_log = Mock()
    bot._has_pending_close_order = Mock(return_value=False)
    bot.trade_count = 0
    bot._opened_symbols_this_cycle = set()
    bot._position_first_seen_ts = {}
    bot._position_extrema_by_pos = {}

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="WLDUSDT",
        target_portion_of_balance=0.068658,
        leverage=3,
        reason="multi_bar_direction_generated_pass",
        metadata={"signal_score": 0.85},
    )

    bot._execute_and_log_decision(
        symbol="WLDUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
        current_price=0.5237,
        position=None,
        flow_context={},
        trigger_type="test",
        trigger_id="wld-entry",
        trigger_context={"trigger_type": "test", "trigger_id": "wld-entry"},
        portfolio={},
    )

    rows = [json.loads(line) for line in (tmp_path / "fund_flow_entry_exit_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["pre_execution", "post_execution", "entry_order_reconciled"]
    execution = rows[2]["execution"]
    assert execution["status"] == "expired"
    assert execution["message"] == "pending_entry_order_final_status_expired"
    assert execution["order"]["status"] == "EXPIRED"
    assert execution["entry_order_final_status"] == "EXPIRED"
    assert execution["entry_order_executed_qty"] == pytest.approx(0.0)
    assert execution["entry_order_limit_price"] == pytest.approx(0.5237)
    assert execution["entry_ioc_fail_reason"].startswith("limit_below_ask")
    assert execution["entry_best_bid_at_reconcile"] == pytest.approx(0.5240)
    assert execution["entry_best_ask_at_reconcile"] == pytest.approx(0.5246)
    assert execution["entry_spread_pct_at_reconcile"] == pytest.approx(0.001145)


def test_execute_and_log_decision_marks_pending_ioc_success_when_final_order_is_filled(tmp_path: Path) -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    bot.logs_dir = str(tmp_path)
    bot.fund_flow_attribution_engine = Mock()
    bot.fund_flow_execution_router = Mock()
    bot.fund_flow_execution_router.execute_decision.return_value = {
        "status": "pending",
        "message": "entry submitted",
        "order": {"orderId": 7016851051, "status": "NEW", "executedQty": "0", "price": "3.084000", "side": "BUY"},
        "quantity": 0.0,
    }
    bot._fetch_order_trade_fills = Mock(return_value=[])
    bot._fetch_entry_order_final_state = Mock(
        return_value={
            "symbol": "ICPUSDT",
            "orderId": 7016851051,
            "status": "FILLED",
            "executedQty": "1.2",
            "avgPrice": "3.083",
            "price": "3.084000",
            "side": "BUY",
            "timeInForce": "IOC",
        }
    )
    bot._extract_orderbook_flow = Mock(return_value={})
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = {"side": "LONG", "amount": 1.2, "entry_price": 3.083}
    bot._post_execution_protection_hook = Mock(return_value={"status": "repaired", "message": "protection_repaired"})
    bot._update_dca_state_after_execution = Mock()
    bot._safe_storage_call = Mock()
    bot._write_trade_fill_log = Mock()
    bot._has_pending_close_order = Mock(return_value=False)
    bot.trade_count = 0
    bot._opened_symbols_this_cycle = set()
    bot._position_first_seen_ts = {}
    bot._position_extrema_by_pos = {}

    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ICPUSDT",
        target_portion_of_balance=0.115082,
        leverage=3,
        reason="multi_bar_direction_generated_pass",
        metadata={"signal_score": 0.85},
    )

    bot._execute_and_log_decision(
        symbol="ICPUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
        current_price=3.084,
        position=None,
        flow_context={},
        trigger_type="test",
        trigger_id="icp-entry",
        trigger_context={"trigger_type": "test", "trigger_id": "icp-entry"},
        portfolio={},
    )

    rows = [json.loads(line) for line in (tmp_path / "fund_flow_entry_exit_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["pre_execution", "post_execution", "entry_order_reconciled"]
    assert rows[2]["execution"]["status"] == "success"
    assert rows[2]["execution"]["message"] == "pending_entry_order_final_status_filled"
    assert rows[2]["execution"]["quantity"] == pytest.approx(1.2)
    assert rows[2]["execution"]["entry_order_avg_price"] == pytest.approx(3.083)
    assert rows[2]["execution"]["post_protection_hook"]["status"] == "repaired"


def test_fetch_entry_order_final_state_retries_new_zero_qty_order() -> None:
    bot = _bot()
    bot.client = Mock()
    bot.client.get_order = Mock(
        side_effect=[
            {"symbol": "WLDUSDT", "orderId": 1, "status": "NEW", "executedQty": "0"},
            {"symbol": "WLDUSDT", "orderId": 1, "status": "EXPIRED", "executedQty": "0"},
        ]
    )

    result = bot._fetch_entry_order_final_state("WLDUSDT", 1)

    assert result["status"] == "EXPIRED"
    assert bot.client.get_order.call_count == 2


def test_execute_and_log_decision_writes_close_audit_details(tmp_path: Path) -> None:
    bot = _bot({"fund_flow": {"min_entry_notional_usdt": 0.10}})
    bot.logs_dir = str(tmp_path)
    bot.fund_flow_attribution_engine = Mock()
    bot.fund_flow_execution_router = Mock()
    bot.fund_flow_execution_router.execute_decision.return_value = {
        "status": "success",
        "message": "closed by beta risk",
        "realized_pnl": -0.12,
        "quantity": 1.0,
        "order": {"orderId": "99"},
    }
    bot.position_data = Mock()
    bot.position_data.get_current_position.return_value = {"side": "LONG", "amount": 0.0, "entry_price": 1.0}
    bot._post_execution_protection_hook = Mock(return_value={})
    bot._update_dca_state_after_execution = Mock()
    bot._safe_storage_call = Mock()
    bot._write_trade_fill_log = Mock()
    bot._has_pending_close_order = Mock(return_value=False)
    bot.trade_count = 0
    bot._opened_symbols_this_cycle = set()
    bot._position_first_seen_ts = {}
    bot._position_extrema_by_pos = {}

    decision = FundFlowDecision(
        operation=Operation.CLOSE,
        symbol="WLDUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        reason="BETA_CLOSE score=4",
        metadata={
            "source": "btc_beta_risk",
            "exit_source": "BETA_CLOSE",
            "close_ratio": 1.0,
            "btc_beta_risk": {"action": "CLOSE", "risk_score": 4, "reason": "btc_alt_reverse"},
            "exit_signal_guard": {"action": "HOLD", "confirm_bars": 1},
            "reverse_signal": {"type": "15m_reverse", "strength": 0.72},
            "entry_summary": {
                "strategy_source": "continuation_long",
                "direction_reason": "slow_bull_breadth+symbol_momentum",
            },
        },
    )

    bot._execute_and_log_decision(
        symbol="WLDUSDT",
        decision=decision,
        account_summary={"equity": 100.0},
        current_price=1.0,
        position={
            "side": "LONG",
            "amount": 1.0,
            "entry_price": 1.05,
            "hold_bars_15m": 3,
            "mfe_pct": 0.42,
            "mae_pct": -0.88,
        },
        flow_context={},
        trigger_type="exit_cycle",
        trigger_id="exit-1",
        trigger_context={"trigger_type": "exit_cycle", "trigger_id": "exit-1"},
        portfolio={},
    )

    rows = (tmp_path / "fund_flow_entry_exit_audit.jsonl").read_text(encoding="utf-8").splitlines()
    post = json.loads(rows[1])
    assert post["exit"]["trigger_source"] == "BETA_CLOSE"
    assert post["exit"]["close_ratio"] == pytest.approx(1.0)
    assert post["exit"]["exit_reason"] == "BETA_CLOSE score=4"
    assert post["exit"]["btc_beta_risk"]["risk_score"] == 4
    assert post["exit"]["exit_signal_guard"]["confirm_bars"] == 1
    assert post["exit"]["reverse_signal"]["type"] == "15m_reverse"
    assert post["exit"]["entry_summary"]["strategy_source"] == "continuation_long"
    assert post["exit"]["holding_bars_15m"] == 3
    assert post["exit"]["holding_minutes_estimated"] == 45
    assert post["position"]["mfe_pct"] == pytest.approx(0.42)
    assert post["position"]["mae_pct"] == pytest.approx(-0.88)
    assert post["execution"]["realized_pnl"] == pytest.approx(-0.12)


def test_dynamic_min_open_notional_uses_probe_floor_when_lower_than_configured_min() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "min_open_notional_usdt": 5.0,
                "min_open_notional_mode": "dynamic",
                "probe_floor_rescue": {"probe_min_open_portion": 0.042},
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="ATOMUSDT",
        target_portion_of_balance=0.042,
        leverage=2,
        metadata={"signal_score": 0.766},
    )

    allowed, meta = bot._allows_entry_below_min_open_by_notional(
        decision=decision,
        min_open_portion=0.06,
        account_equity=111.18,
    )

    assert allowed is True
    assert meta["notional_usdt"] == pytest.approx(4.66956)
    assert meta["min_open_notional_usdt"] == pytest.approx(4.436082)
    assert meta["min_open_notional_mode"] == "dynamic"
    assert meta["reason"] == "notional_check_passed"


def test_exit_cooldown_blocks_same_side_and_allows_opposite() -> None:
    cooldown = ExitCooldownRegistry(cooldown_seconds=1800, now_func=lambda: 1000.0)

    cooldown.register_exit("PUMPUSDT", "LONG")

    assert cooldown.is_blocked("PUMPUSDT", "LONG") is True
    assert cooldown.is_blocked("PUMPUSDT", "SHORT") is False
    assert cooldown.is_blocked("BCHUSDT", "LONG") is False


def test_exit_cooldown_expires() -> None:
    now = {"value": 1000.0}
    cooldown = ExitCooldownRegistry(cooldown_seconds=60, now_func=lambda: now["value"])

    cooldown.register_exit("PUMPUSDT", "LONG")
    now["value"] = 1061.0

    assert cooldown.is_blocked("PUMPUSDT", "LONG") is False


def test_position_exit_guard_blocks_dca_before_building_dca_decision() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "position_exit_signal_guard": {
                    "enabled": True,
                    "confirm_bars_required": 2,
                    "mae_trigger_pct": -0.008,
                    "block_dca_on_reverse": True,
                }
            }
        }
    )
    bot.exit_signal_guard = PositionExitSignalGuard(bot._position_exit_signal_guard_config())
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="TRUMPUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        metadata={
            "signal_1h": "red_bar_shrinking",
            "reject_code": "rsi_1h_direction_against_veto",
        },
    )
    position = {"side": "LONG", "entry_price": 2.483, "amount": 11.78}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="TRUMPUSDT",
        position=position,
        current_price=2.459,
        decision=decision,
        decision_md=decision.metadata,
    )

    assert adjusted is decision
    assert meta["action"] == "BLOCK_DCA"
    assert "TRUMPUSDT:LONG" in bot._dca_blocked_by_exit_guard


def test_btc_beta_risk_reduce_preempts_exit_guard() -> None:
    bot = _bot({"fund_flow": {"btc_beta_risk": {"enabled": True}}})
    bot._dca_blocked_by_exit_guard = set()
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.004}}
    bot._position_first_seen_ts = {"ADAUSDT:LONG": 1000.0}
    bot._btc_beta_recent_returns = lambda symbol: {  # type: ignore[method-assign]
        "btc_ret_15m": -0.0005,
        "btc_ret_30m": -0.0010,
        "alt_ret_15m": -0.0012,
        "alt_ret_30m": -0.0010,
    }
    bot._btc_beta_position_age_bars = lambda _key: 4  # type: ignore[method-assign]
    bot._now_ts = lambda: 1900.0  # type: ignore[method-assign]
    bot.btc_beta_scorer = __import__(
        "src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskScorer", "BtcBetaRiskConfig"]
    ).BtcBetaRiskScorer(
        __import__("src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskConfig"]).BtcBetaRiskConfig()
    )
    for i in range(12):
        ret = 0.001 if i % 2 == 0 else -0.001
        bot.btc_beta_scorer.update_corr_history("ADAUSDT", ret, ret)
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="ADAUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        metadata={"signal_1h": "red_bar_growing", "account_equity_usdt": 100.0},
    )
    position = {"side": "LONG", "entry_price": 1.0, "amount": 20.0}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.997,
        decision=decision,
        decision_md=decision.metadata,
        account_summary={"equity": 100.0},
    )

    assert adjusted.operation == Operation.CLOSE
    assert adjusted.target_portion_of_balance == pytest.approx(0.5)
    assert adjusted.reason.startswith("BETA_RISK_REDUCE")
    assert meta["action"] == "REDUCE_50"
    assert decision.metadata["btc_beta_risk"]["action"] == "REDUCE_50"


def test_btc_beta_risk_closes_small_notional_instead_of_reduce() -> None:
    bot = _bot(
        {"fund_flow": {"btc_beta_risk": {"enabled": True, "small_notional_close_threshold": 5.0}}}
    )
    bot._dca_blocked_by_exit_guard = set()
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.004}}
    bot._position_first_seen_ts = {"ADAUSDT:LONG": 1000.0}
    bot._btc_beta_recent_returns = lambda symbol: {  # type: ignore[method-assign]
        "btc_ret_15m": -0.0005,
        "btc_ret_30m": -0.0010,
        "alt_ret_15m": -0.0012,
        "alt_ret_30m": -0.0010,
    }
    bot._btc_beta_position_age_bars = lambda _key: 4  # type: ignore[method-assign]
    bot.btc_beta_scorer = __import__(
        "src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskScorer", "BtcBetaRiskConfig"]
    ).BtcBetaRiskScorer(
        __import__("src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskConfig"]).BtcBetaRiskConfig(
            small_notional_close_threshold=5.0
        )
    )
    for i in range(12):
        ret = 0.001 if i % 2 == 0 else -0.001
        bot.btc_beta_scorer.update_corr_history("ADAUSDT", ret, ret)
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="ADAUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        metadata={"signal_1h": "red_bar_growing", "account_equity_usdt": 100.0},
    )
    position = {"side": "LONG", "entry_price": 1.0, "amount": 3.0}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.997,
        decision=decision,
        decision_md=decision.metadata,
        account_summary={"equity": 100.0},
    )

    assert adjusted.operation == Operation.CLOSE
    assert adjusted.target_portion_of_balance == pytest.approx(1.0)
    assert adjusted.reason.startswith("BETA_RISK_CLOSE")
    assert meta["action"] == "CLOSE"
    assert meta["small_notional_close"] is True


def test_btc_beta_risk_tiny_notional_skip_does_not_create_close_decision() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "btc_beta_risk": {
                    "enabled": True,
                    "small_notional_close_threshold": 5.0,
                    "tiny_notional_skip_threshold": 1.0,
                }
            }
        }
    )
    bot._dca_blocked_by_exit_guard = set()
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.004}}
    bot._position_first_seen_ts = {"ADAUSDT:LONG": 1000.0}
    bot._btc_beta_recent_returns = lambda symbol: {  # type: ignore[method-assign]
        "btc_ret_15m": -0.0005,
        "btc_ret_30m": -0.0010,
        "alt_ret_15m": -0.0012,
        "alt_ret_30m": -0.0010,
    }
    bot._btc_beta_position_age_bars = lambda _key: 4  # type: ignore[method-assign]
    bot.btc_beta_scorer = __import__(
        "src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskScorer", "BtcBetaRiskConfig"]
    ).BtcBetaRiskScorer(
        __import__("src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskConfig"]).BtcBetaRiskConfig(
            small_notional_close_threshold=5.0,
            tiny_notional_skip_threshold=1.0,
        )
    )
    for i in range(12):
        ret = 0.001 if i % 2 == 0 else -0.001
        bot.btc_beta_scorer.update_corr_history("ADAUSDT", ret, ret)
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="ADAUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        metadata={"signal_1h": "red_bar_growing"},
    )
    position = {"side": "LONG", "entry_price": 1.0, "amount": 0.5}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.997,
        decision=decision,
        decision_md=decision.metadata,
    )

    assert adjusted is decision
    assert meta["action"] == "HOLD"
    assert decision.metadata["btc_beta_risk"]["action"] == "SKIP_TINY_CLOSE"
    assert decision.metadata["btc_beta_risk"]["tiny_notional_skip"] is True


def test_btc_beta_reduce_still_allows_exit_guard_full_close() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "btc_beta_risk": {"enabled": True},
                "position_exit_signal_guard": {
                    "enabled": True,
                    "confirm_bars_required": 1,
                    "mae_trigger_pct": -0.008,
                    "block_dca_on_reverse": True,
                },
            }
        }
    )
    bot._dca_blocked_by_exit_guard = set()
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.010}}
    bot._position_first_seen_ts = {"ADAUSDT:LONG": 1000.0}
    bot._btc_beta_recent_returns = lambda symbol: {  # type: ignore[method-assign]
        "btc_ret_15m": -0.0005,
        "btc_ret_30m": -0.0010,
        "alt_ret_15m": -0.0012,
        "alt_ret_30m": -0.0010,
    }
    bot._btc_beta_position_age_bars = lambda _key: 1  # type: ignore[method-assign]
    bot.btc_beta_scorer = __import__(
        "src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskScorer", "BtcBetaRiskConfig"]
    ).BtcBetaRiskScorer(
        __import__("src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskConfig"]).BtcBetaRiskConfig()
    )
    for i in range(12):
        ret = 0.001 if i % 2 == 0 else -0.001
        bot.btc_beta_scorer.update_corr_history("ADAUSDT", ret, ret)
    bot.exit_signal_guard = PositionExitSignalGuard(bot._position_exit_signal_guard_config())
    bot.exit_signal_guard._reverse_bars["ADAUSDT"] = 1
    decision = FundFlowDecision(
        operation=Operation.HOLD,
        symbol="ADAUSDT",
        target_portion_of_balance=0.0,
        leverage=3,
        metadata={"signal_1h": "red_bar_shrinking"},
    )
    position = {"side": "LONG", "entry_price": 1.0, "amount": 20.0}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.990,
        decision=decision,
        decision_md=decision.metadata,
    )

    assert adjusted.operation == Operation.CLOSE
    assert adjusted.target_portion_of_balance == pytest.approx(1.0)
    assert adjusted.reason.startswith("EXIT_SIGNAL_GUARD_CLOSE")
    assert meta["action"] == "CLOSE"


def test_config_fingerprint_snapshot_includes_deployment_critical_fields() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "probe_floor_rescue": {
                    "enabled": True,
                    "shadow_mode": False,
                    "probe_min_open_portion": 0.042,
                },
                "position_exit_signal_guard": {
                    "enabled": True,
                    "confirm_bars_required": 2,
                },
                "macd_mtf_strategy_v2": {
                    "vwap_config": {
                        "vwap_deviation_hard_block": 0.03,
                        "vwap_deviation_gate": {
                            "mode": "atr_normalized",
                            "block_atr_multiplier": 4.0,
                            "probe_max_portion": 0.06,
                        },
                    },
                    "scoring_weights": {
                        "weight_rsi_rhythm": 0.30,
                        "weight_4h_direction": 0.40,
                        "weight_4h_enhancement": 0.10,
                    },
                    "entry_filters": {
                        "neutral_upgrade_min_rsi_score": 0.35,
                    },
                    "partial_confirm": {
                        "enabled": True,
                        "shadow_mode": True,
                    },
                    "dynamic_position_sizing": {
                        "signal_type_caps": {
                            "red_bar_shrinking": {
                                "apply_to": ["signal_1h", "signal_4h"],
                            },
                        },
                    },
                },
            }
        }
    )

    snapshot = bot._build_config_fingerprint_snapshot()

    assert snapshot["probe_shadow"] is False
    assert snapshot["probe_min_open"] == pytest.approx(0.042)
    assert snapshot["weight_rsi"] == pytest.approx(0.30)
    assert snapshot["weight_4h"] == pytest.approx(0.40)
    assert snapshot["vwap_gate_mode"] == "atr_normalized"
    assert snapshot["vwap_probe_max_portion"] == pytest.approx(0.06)
    assert snapshot["neutral_upg_rsi"] == pytest.approx(0.35)
    assert snapshot["pc_shadow"] is True
    assert snapshot["pc_enabled"] is True
    assert snapshot["exit_guard"] is True
    assert snapshot["exit_guard_bars"] == 2
    assert snapshot["shrink_cap_1h"] is True


def test_extreme_dual_leg_shadow_uses_btc_or_atr_shock_without_live_hedge() -> None:
    bot = _bot(
        {
            "fund_flow": {
                "dual_leg_extreme_hedge": {
                    "enabled": True,
                    "shadow_mode": True,
                    "min_unrealized_loss_ratio": 0.015,
                    "min_signal_score": 0.72,
                    "min_regime_atr_pct": 0.012,
                    "max_target_portion": 0.08,
                    "leverage_cap": 2,
                    "shock_detector": {
                        "type": "btc_or_atr",
                        "btc_5m_threshold": -0.015,
                        "btc_15m_threshold": -0.020,
                        "min_atr_pct": 0.012,
                    },
                }
            }
        }
    )
    decision = FundFlowDecision(
        operation=Operation.SELL,
        symbol="SOLUSDT",
        target_portion_of_balance=0.35,
        leverage=4,
        metadata={
            "signal_score": 0.82,
            "regime_atr_pct": 0.004,
            "btc_return_5m": -0.016,
            "btc_return_15m": -0.010,
        },
    )
    position = {"side": "LONG", "entry_price": 100.0, "mark_price": 98.0, "amount": 1.0}

    allowed, adjusted, meta = bot._maybe_allow_extreme_dual_leg_hedge(
        symbol="SOLUSDT",
        position=position,
        decision=decision,
        current_price=98.0,
    )

    assert allowed is False
    assert adjusted is decision
    assert adjusted.metadata["dual_leg_shadow_allowed"] is True
    assert adjusted.metadata["btc_shock_level"] == "LIGHT"
    assert adjusted.metadata["btc_return_5m"] == pytest.approx(-0.016)
    assert adjusted.metadata["btc_return_15m"] == pytest.approx(-0.010)
    assert meta["shadow_mode"] is True
