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
