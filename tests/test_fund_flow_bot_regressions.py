import json
from pathlib import Path
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from src.app.fund_flow_bot import FundFlowDecision, FundFlowOperation, TradingBot


def test_trading_bot_does_not_use_missing_private_config_attr():
    source = Path("src/app/fund_flow_bot.py").read_text(encoding="utf-8")
    assert re.search(r"self\._config(?![A-Za-z0-9_])", source) is None


def test_live_config_stage2_ablation_disables_outer_entry_filters_and_ai_review():
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    ff = cfg["fund_flow"]

    assert ff["ma10_macd_confluence"]["enabled"] is False
    assert ff["ma10_macd_confluence"]["entry_hard_filter"] is False
    assert ff["pretrade_risk_gate"]["enabled"] is False
    assert ff["ai_review"]["enabled"] is False


def test_soften_conflict_exit_for_small_mae_downgrades_to_reduce():
    bot = TradingBot.__new__(TradingBot)
    out = bot._soften_conflict_exit_for_small_mae(
        protection={
            "risk_state": "CIRCUIT_EXIT",
            "reason": "熔断 test",
            "state_deep_break": False,
            "reduce_position_pct": 1.0,
            "force_break_even": False,
        },
        drawdown_ratio=0.0013,
        conflict_cfg_hard={"hard_exit_min_mae": 0.002, "state_reduce_pct": 0.35},
    )

    assert out["softened"] is True
    assert out["risk_state"] == "REDUCE"
    assert out["force_break_even"] is True
    assert out["force_reduce_signal"] is True
    assert out["reduce_pct"] == 0.35


def test_soften_conflict_exit_for_small_mae_keeps_circuit_exit_on_deep_break():
    bot = TradingBot.__new__(TradingBot)
    out = bot._soften_conflict_exit_for_small_mae(
        protection={
            "risk_state": "CIRCUIT_EXIT",
            "reason": "熔断 test",
            "state_deep_break": True,
            "reduce_position_pct": 1.0,
            "force_break_even": False,
        },
        drawdown_ratio=0.0013,
        conflict_cfg_hard={"hard_exit_min_mae": 0.002, "state_reduce_pct": 0.35},
    )

    assert out["softened"] is False
    assert out["risk_state"] == "CIRCUIT_EXIT"


def test_symbols_for_current_cycle_prioritizes_positions_without_truncation():
    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "schedule": {
            "symbols_per_cycle": 7,
            "symbols_per_cycle_prioritize_positions": True,
        }
    }

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
    ordered = bot._symbols_for_current_cycle(symbols, {"SOLUSDT"})

    assert ordered == ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]


def test_diff_counter_dict_only_keeps_positive_deltas():
    delta = TradingBot._diff_counter_dict(
        after={"200": 12, "429": 3, "500": 1},
        before={"200": 10, "429": 3, "418": 2},
    )

    assert delta == {"200": 2, "500": 1}


def test_decision_signal_score_prefers_macd_v2_signal_score():
    bot = TradingBot.__new__(TradingBot)
    decision = FundFlowDecision(
        operation=FundFlowOperation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.1,
        leverage=1.0,
        reason="test",
        metadata={
            "strategy_mode": "macd_mtf_strategy_v2",
            "signal_score": 0.7825,
            "long_score": 0.0,
            "short_score": 0.0,
        },
    )

    assert bot._decision_signal_score(decision) == 0.7825


def test_post_execution_protection_hook_defers_pending_entry_protection():
    bot = TradingBot.__new__(TradingBot)
    calls = {"repair": 0, "flatten": 0}
    bot.position_data = SimpleNamespace(
        get_current_position=lambda symbol: {
            "symbol": symbol,
            "side": "LONG",
            "positionAmt": "52.0",
        }
    )
    bot._protection_coverage = lambda symbol, side: {"has_tp": False, "has_sl": False}

    def _repair(symbol, position):
        calls["repair"] += 1
        return {"status": "failed"}

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._repair_missing_protection = _repair
    bot._emergency_flatten_unprotected = _flatten
    bot._protection_sla_config = lambda: {"immediate_close_on_repair_fail": True}
    decision = FundFlowDecision(
        operation=FundFlowOperation.BUY,
        symbol="ONDOUSDT",
        target_portion_of_balance=0.14,
        leverage=1.0,
        reason="test",
        metadata={},
    )

    result = bot._post_execution_protection_hook(
        symbol="ONDOUSDT",
        decision=decision,
        execution_result={
            "status": "pending",
            "protection": {
                "status": "pending",
                "message": "entry not filled yet, tp/sl skipped for now",
            },
        },
    )

    assert result["status"] == "pending"
    assert result["message"] == "entry_pending_protection_deferred"
    assert calls == {"repair": 0, "flatten": 0}


def test_post_execution_protection_hook_accepts_sl_only_when_take_profit_disabled():
    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "fund_flow": {"take_profit_pct": 0.0, "stop_loss_pct": 0.005},
        "risk": {},
    }
    calls = {"repair": 0, "flatten": 0}
    coverages = iter(
        [
            {"has_tp": False, "has_sl": False, "orders": []},
            {"has_tp": False, "has_sl": True, "orders": [{"type": "STOP_MARKET"}]},
        ]
    )
    bot.position_data = SimpleNamespace(
        get_current_position=lambda symbol: {
            "symbol": symbol,
            "side": "LONG",
            "positionAmt": "52.0",
        }
    )
    bot._protection_coverage = lambda symbol, side: next(coverages)

    def _repair(symbol, position):
        calls["repair"] += 1
        return {"status": "success"}

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._repair_missing_protection = _repair
    bot._emergency_flatten_unprotected = _flatten
    bot._protection_sla_config = lambda: {"immediate_close_on_repair_fail": True}
    decision = FundFlowDecision(
        operation=FundFlowOperation.BUY,
        symbol="ONDOUSDT",
        target_portion_of_balance=0.14,
        leverage=1.0,
        reason="test",
        metadata={},
    )

    result = bot._post_execution_protection_hook(
        symbol="ONDOUSDT",
        decision=decision,
        execution_result={"status": "success", "protection": {"status": "success"}},
    )

    assert result["status"] == "repaired"
    assert result["message"] == "protection_repaired"
    assert calls == {"repair": 1, "flatten": 0}


def test_post_execution_protection_hook_treats_successful_repair_stop_order_as_covered_when_query_lags():
    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "fund_flow": {"take_profit_pct": 0.0, "stop_loss_pct": 0.005},
        "risk": {},
    }
    calls = {"repair": 0, "flatten": 0}
    coverages = iter(
        [
            {"has_tp": False, "has_sl": False, "orders": []},
            {"has_tp": False, "has_sl": False, "orders": []},
        ]
    )
    bot.position_data = SimpleNamespace(
        get_current_position=lambda symbol: {
            "symbol": symbol,
            "side": "LONG",
            "positionAmt": "52.0",
        }
    )
    bot._protection_coverage = lambda symbol, side: next(coverages)

    def _repair(symbol, position):
        calls["repair"] += 1
        return {
            "status": "success",
            "orders": [
                {
                    "algoId": 2000000872301767,
                    "orderType": "STOP_MARKET",
                    "algoStatus": "NEW",
                    "positionSide": "LONG",
                    "side": "SELL",
                    "triggerPrice": "1.7100000",
                }
            ],
        }

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._repair_missing_protection = _repair
    bot._emergency_flatten_unprotected = _flatten
    bot._protection_sla_config = lambda: {"immediate_close_on_repair_fail": True}
    decision = FundFlowDecision(
        operation=FundFlowOperation.BUY,
        symbol="RENDERUSDT",
        target_portion_of_balance=0.14,
        leverage=1.0,
        reason="test",
        metadata={},
    )

    result = bot._post_execution_protection_hook(
        symbol="RENDERUSDT",
        decision=decision,
        execution_result={"status": "success", "protection": {"status": "success"}},
    )

    assert result["status"] == "repaired"
    assert result["message"] == "protection_repaired"
    assert calls == {"repair": 1, "flatten": 0}


def test_post_execution_protection_hook_does_not_immediate_flatten_on_repair_failure():
    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "fund_flow": {"take_profit_pct": 0.0, "stop_loss_pct": 0.005},
        "risk": {},
    }
    calls = {"repair": 0, "flatten": 0}
    bot.position_data = SimpleNamespace(
        get_current_position=lambda symbol: {
            "symbol": symbol,
            "side": "LONG",
            "positionAmt": "52.0",
        }
    )
    bot._protection_coverage = lambda symbol, side: {"has_tp": False, "has_sl": False, "orders": []}

    def _repair(symbol, position):
        calls["repair"] += 1
        return {"status": "error", "message": "保护单下发失败"}

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._repair_missing_protection = _repair
    bot._emergency_flatten_unprotected = _flatten
    bot._protection_sla_config = lambda: {"immediate_close_on_repair_fail": True}
    decision = FundFlowDecision(
        operation=FundFlowOperation.BUY,
        symbol="TONUSDT",
        target_portion_of_balance=0.14,
        leverage=1.0,
        reason="test",
        metadata={},
    )

    result = bot._post_execution_protection_hook(
        symbol="TONUSDT",
        decision=decision,
        execution_result={"status": "success", "protection": {"status": "failed"}},
    )

    assert result["status"] == "failed"
    assert result["message"] == "protection_missing_after_repair"
    assert result["immediate_close_suppressed"] is True
    assert calls == {"repair": 1, "flatten": 0}


def test_open_protection_orders_accepts_manual_stop_without_position_side_in_hedge_mode():
    bot = TradingBot.__new__(TradingBot)
    bot.client = SimpleNamespace(
        get_open_orders=lambda symbol: [
            {
                "orderId": 11,
                "status": "NEW",
                "type": "STOP_MARKET",
                "side": "SELL",
                "positionSide": "",
            }
        ],
        get_open_conditional_orders=lambda symbol: [],
        broker=SimpleNamespace(get_hedge_mode=lambda: True),
    )

    coverage = bot._protection_coverage("TONUSDT", side="LONG")

    assert coverage["has_sl"] is True
    assert coverage["orders"][0]["orderId"] == 11


def test_open_protection_orders_accepts_papi_algo_stop_order():
    bot = TradingBot.__new__(TradingBot)
    bot.client = SimpleNamespace(
        get_open_orders=lambda symbol: [],
        get_open_conditional_orders=lambda symbol: [
            {
                "algoId": 91,
                "algoStatus": "NEW",
                "algoType": "CONDITIONAL",
                "type": "STOP_MARKET",
                "side": "SELL",
                "positionSide": "LONG",
                "triggerPrice": "1.319",
            }
        ],
        broker=SimpleNamespace(get_hedge_mode=lambda: True),
    )

    coverage = bot._protection_coverage("TONUSDT", side="LONG")

    assert coverage["has_sl"] is True
    assert coverage["orders"][0]["algoId"] == 91


def test_position_sla_does_not_immediate_flatten_on_repair_failure_before_timeout():
    bot = TradingBot.__new__(TradingBot)
    now_ts = 1000.0
    calls = {"flatten": 0, "alerts": []}
    bot._position_first_seen_ts = {}
    bot._position_last_direction_eval_ts = {}
    bot._position_extrema_by_pos = {}
    bot._protection_missing_since_ts = {}
    bot._protection_last_alert_ts = {}
    bot._pre_risk_exit_streak_by_pos = {}
    bot._clear_sla_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._clear_dca_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._update_position_extrema = lambda symbol, position, current_price: None
    bot._protection_coverage = lambda symbol, side: {"has_tp": False, "has_sl": False, "orders": []}
    bot._protection_is_covered = lambda coverage: False
    bot._repair_missing_protection = lambda symbol, position: {"status": "error", "message": "保护单下发失败"}

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._emergency_flatten_unprotected = _flatten
    bot._emit_protection_sla_alert = lambda **kwargs: calls["alerts"].append(kwargs)

    skipped, blocked = bot._handle_symbol_protection_and_sla(
        symbol="TONUSDT",
        position={"side": "LONG", "amount": 0.1, "entry_price": 1.3311},
        current_price=1.3321,
        now_ts=now_ts,
        sla_cfg={
            "enabled": True,
            "timeout_seconds": 45,
            "force_flatten_on_breach": True,
            "immediate_close_on_repair_fail": True,
            "alert_cooldown_seconds": 15,
        },
        repair_fail_reduce_ratio=1.0,
        immediate_close_on_repair_fail=True,
        block_new_entries_due_to_protection_gap=False,
        protection_gap_symbols=[],
    )

    assert skipped is True
    assert blocked is True
    assert calls["flatten"] == 0
    assert [x["detail"] for x in calls["alerts"]] == ["protection_repair_failed_no_immediate_close"]


def test_position_sla_does_not_flatten_when_repair_success_returns_stop_order_but_query_lags():
    bot = TradingBot.__new__(TradingBot)
    now_ts = 1000.0
    pos_key = "RENDERUSDT:LONG"
    calls = {"flatten": 0, "alerts": []}
    bot.config = {
        "fund_flow": {"take_profit_pct": 0.0, "stop_loss_pct": 0.005},
        "risk": {},
    }
    bot._position_first_seen_ts = {pos_key: now_ts - 60}
    bot._position_last_direction_eval_ts = {}
    bot._position_extrema_by_pos = {}
    bot._protection_missing_since_ts = {pos_key: now_ts - 60}
    bot._protection_last_alert_ts = {}
    bot._pre_risk_exit_streak_by_pos = {}
    bot._clear_sla_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._clear_dca_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._update_position_extrema = lambda symbol, position, current_price: None
    bot._protection_coverage = lambda symbol, side: {"has_tp": False, "has_sl": False, "orders": []}

    bot._repair_missing_protection = lambda symbol, position: {
        "status": "success",
        "message": "保护单下发成功",
        "orders": [
            {
                "algoId": 2000000872301767,
                "orderType": "STOP_MARKET",
                "algoStatus": "NEW",
                "positionSide": "LONG",
                "side": "SELL",
                "triggerPrice": "1.7100000",
            }
        ],
    }

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._emergency_flatten_unprotected = _flatten
    bot._emit_protection_sla_alert = lambda **kwargs: calls["alerts"].append(kwargs)

    skipped, blocked = bot._handle_symbol_protection_and_sla(
        symbol="RENDERUSDT",
        position={"side": "LONG", "amount": 0.1, "entry_price": 1.7311},
        current_price=1.7321,
        now_ts=now_ts,
        sla_cfg={
            "enabled": True,
            "timeout_seconds": 45,
            "force_flatten_on_breach": True,
            "immediate_close_on_repair_fail": True,
            "alert_cooldown_seconds": 15,
        },
        repair_fail_reduce_ratio=1.0,
        immediate_close_on_repair_fail=True,
        block_new_entries_due_to_protection_gap=False,
        protection_gap_symbols=[],
    )

    assert skipped is True
    assert blocked is False
    assert calls["flatten"] == 0
    assert calls["alerts"] == []
    assert pos_key not in bot._protection_missing_since_ts


def test_position_sla_flattens_after_timeout_when_repair_still_fails():
    bot = TradingBot.__new__(TradingBot)
    now_ts = 1000.0
    pos_key = "TONUSDT:LONG"
    calls = {"flatten": 0, "alerts": []}
    bot._position_first_seen_ts = {pos_key: now_ts - 60}
    bot._position_last_direction_eval_ts = {}
    bot._position_extrema_by_pos = {}
    bot._protection_missing_since_ts = {pos_key: now_ts - 60}
    bot._protection_last_alert_ts = {}
    bot._pre_risk_exit_streak_by_pos = {}
    bot._clear_sla_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._clear_dca_tracking_for_symbol = lambda symbol, keep_key=None: None
    bot._update_position_extrema = lambda symbol, position, current_price: None
    bot._protection_coverage = lambda symbol, side: {"has_tp": False, "has_sl": False, "orders": []}
    bot._protection_is_covered = lambda coverage: False
    bot._repair_missing_protection = lambda symbol, position: {"status": "error", "message": "保护单下发失败"}

    def _flatten(symbol, position, reduce_ratio):
        calls["flatten"] += 1
        return {"status": "success"}

    bot._emergency_flatten_unprotected = _flatten
    bot._emit_protection_sla_alert = lambda **kwargs: calls["alerts"].append(kwargs)

    skipped, blocked = bot._handle_symbol_protection_and_sla(
        symbol="TONUSDT",
        position={"side": "LONG", "amount": 0.1, "entry_price": 1.3311},
        current_price=1.3321,
        now_ts=now_ts,
        sla_cfg={
            "enabled": True,
            "timeout_seconds": 45,
            "force_flatten_on_breach": True,
            "immediate_close_on_repair_fail": True,
            "alert_cooldown_seconds": 15,
        },
        repair_fail_reduce_ratio=1.0,
        immediate_close_on_repair_fail=True,
        block_new_entries_due_to_protection_gap=False,
        protection_gap_symbols=[],
    )

    assert skipped is True
    assert blocked is True
    assert calls["flatten"] == 1
    assert "protection_sla_breached" in [x["detail"] for x in calls["alerts"]]
    assert "protection_sla_force_flatten" in [x["detail"] for x in calls["alerts"]]


def test_emergency_flatten_unprotected_cancels_conditional_orders_after_success():
    bot = TradingBot.__new__(TradingBot)
    cancelled = []
    bot.client = SimpleNamespace(
        format_quantity=lambda symbol, qty: qty,
        broker=SimpleNamespace(get_hedge_mode=lambda: False),
        _execute_order_v2=lambda params, side, reduce_only: {"status": "success", "orderId": 12345},
        cancel_all_conditional_orders=lambda symbol: cancelled.append(symbol) or {"status": "success"},
    )
    bot.position_data = SimpleNamespace(get_current_position=lambda symbol: None)

    result = bot._emergency_flatten_unprotected(
        "TONUSDT",
        {"side": "LONG", "amount": 0.25},
        reduce_ratio=1.0,
    )

    assert result["status"] == "success"
    assert cancelled == ["TONUSDT"]


def test_load_and_save_risk_state_round_trips_protection_plan_by_pos(tmp_path):
    bot = TradingBot.__new__(TradingBot)
    bot._risk_state_path = str(tmp_path / "fund_flow_risk_state.json")
    bot._consecutive_losses = 0
    bot._cooldown_reason = None
    bot._cooldown_expires = None
    bot._daily_open_equity = None
    bot._daily_open_date = None
    bot._peak_equity = None
    bot._dca_stage_by_pos = {}
    bot._winner_pyramid_stage_by_pos = {}
    bot._conflict_exit_streak_by_symbol = {}
    bot._conflict_cooldown_until_by_symbol = {}
    bot._conflict_cooldown_reason_by_symbol = {}
    bot._protection_plan_by_pos = {
        "XLMUSDT:LONG": {
            "stop_loss_price": 0.159364,
            "take_profit_price": 0.1625,
            "tp_levels": [{"price": 0.1625, "reduce_pct": 1.0}],
        }
    }

    bot._save_risk_state()

    reloaded = TradingBot.__new__(TradingBot)
    reloaded._risk_state_path = bot._risk_state_path
    reloaded._consecutive_losses = 0
    reloaded._cooldown_reason = None
    reloaded._cooldown_expires = None
    reloaded._daily_open_equity = None
    reloaded._daily_open_date = None
    reloaded._peak_equity = None
    reloaded._dca_stage_by_pos = {}
    reloaded._winner_pyramid_stage_by_pos = {}
    reloaded._conflict_exit_streak_by_symbol = {}
    reloaded._conflict_cooldown_until_by_symbol = {}
    reloaded._conflict_cooldown_reason_by_symbol = {}
    reloaded._protection_plan_by_pos = {}

    reloaded._load_risk_state()

    assert reloaded._protection_plan_by_pos == {
        "XLMUSDT:LONG": {
            "stop_loss_price": 0.159364,
            "take_profit_price": 0.1625,
            "tp_levels": [{"price": 0.1625, "reduce_pct": 1.0}],
        }
    }


def test_repair_missing_protection_uses_persisted_plan_when_global_tp_disabled():
    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "fund_flow": {"take_profit_pct": 0.0, "take_profit_pct_levels": [], "stop_loss_pct": 0.005},
        "risk": {},
    }
    bot._dynamic_stop_loss_enabled = False
    bot._protection_plan_by_pos = {
        "XLMUSDT:LONG": {
            "stop_loss_price": 0.159364,
            "take_profit_price": 0.1625,
            "tp_levels": [{"price": 0.1625, "reduce_pct": 1.0}],
        }
    }
    captured = {}

    def _exec(symbol, side, tp, sl, quantity, tp_levels=None):
        captured.update(
            {
                "symbol": symbol,
                "side": side,
                "tp": tp,
                "sl": sl,
                "quantity": quantity,
                "tp_levels": tp_levels,
            }
        )
        return {"status": "success", "orders": []}

    bot.client = SimpleNamespace(_execute_protection_v2=_exec)

    bot._repair_missing_protection(
        "XLMUSDT",
        {"side": "LONG", "entry_price": 0.16018, "amount": 69.0, "mark_price": 0.16013},
    )

    assert captured["tp"] == 0.1625
    assert captured["sl"] == 0.159364
    assert captured["tp_levels"] == [(0.1625, 1.0)]


def test_cancel_stale_pending_entry_orders_only_cancels_old_entry_orders():
    bot = TradingBot.__new__(TradingBot)
    now_ms = int(time.time() * 1000)
    cancelled = []

    bot.client = SimpleNamespace(
        get_open_orders=lambda symbol: [
            {"orderId": 1, "status": "NEW", "type": "LIMIT", "time": now_ms - 3 * 3600 * 1000},
            {"orderId": 2, "status": "NEW", "type": "LIMIT", "time": now_ms - 10 * 60 * 1000},
            {"orderId": 3, "status": "NEW", "type": "TAKE_PROFIT_MARKET", "time": now_ms - 5 * 3600 * 1000},
            {"orderId": 4, "status": "FILLED", "type": "LIMIT", "time": now_ms - 5 * 3600 * 1000},
        ],
        cancel_order=lambda symbol, order_id: cancelled.append((symbol, order_id)) or {"status": "success"},
    )

    summary = bot._cancel_stale_pending_entry_orders("BTCUSDT", stale_seconds=3600)

    assert cancelled == [("BTCUSDT", 1)]
    assert summary["stale"] == 1
    assert summary["cancelled"] == 1


def test_cancel_stale_pending_entry_orders_keeps_fresh_entry_orders():
    bot = TradingBot.__new__(TradingBot)
    now_ms = int(time.time() * 1000)
    cancelled = []

    bot.client = SimpleNamespace(
        get_open_orders=lambda symbol: [
            {"orderId": 11, "status": "NEW", "type": "LIMIT", "time": now_ms - 15 * 60 * 1000},
        ],
        cancel_order=lambda symbol, order_id: cancelled.append((symbol, order_id)) or {"status": "success"},
    )

    summary = bot._cancel_stale_pending_entry_orders("ETHUSDT", stale_seconds=3600)

    assert cancelled == []
    assert summary["stale"] == 0
    assert summary["cancelled"] == 0


def test_range_dynamic_signal_pool_inherits_edge_trigger_flag_from_runtime_pool():
    bot = TradingBot.__new__(TradingBot)
    captured = {}

    bot._materialize_flow_snapshot = lambda symbol, market_data: (
        None,
        SimpleNamespace(signal_strength=1.0, timestamp=market_data["timestamp"]),
        {},
    )
    bot._update_extreme_volatility_state = lambda symbol, flow_context: {"blocked": False}
    bot._conflict_symbol_cooldown_state = lambda symbol: {"blocked": False}
    bot._entry_window_state = lambda: {"allowed": True}
    bot._ma10_macd_confluence_config = lambda: {"enabled": False}
    bot._resolve_runtime_signal_pool_config = lambda pool_id: {
        "pool_id": pool_id,
        "id": pool_id,
        "edge_trigger_enabled": False,
        "edge_cooldown_seconds": 600,
    }

    class _TriggerEngine:
        def should_trigger(self, **kwargs):
            return True

        def evaluate_signal_pool(self, **kwargs):
            captured.update(kwargs["signal_pool_config"])
            return {"passed": False, "reason": "test", "edge": {}}

    class _DecisionEngine:
        def decide(self, **kwargs):
            return FundFlowDecision(
                operation=FundFlowOperation.BUY,
                symbol=kwargs["symbol"],
                target_portion_of_balance=0.1,
                leverage=1.0,
                reason="test",
                metadata={"engine": "RANGE", "signal_pool_id": "range_pool"},
            )

    bot.fund_flow_trigger_engine = _TriggerEngine()
    bot.fund_flow_decision_engine = _DecisionEngine()

    bot._execute_symbol_signal_decision(
        symbol="PUMPUSDT",
        market_data={"timestamp": __import__("datetime").datetime(2026, 3, 25)},
        position=None,
        current_price=1.0,
        account_summary={"available_balance": 1000.0, "equity": 1000.0},
        pending_new_entries=[],
        protection_gap_symbols=[],
        block_new_entries_due_to_protection_gap=False,
        allow_new_entries=True,
        ff_cfg={"trigger_dedupe_seconds": 180},
        max_active_symbols=10,
        max_symbol_position_portion=0.1,
        add_position_portion=0.0,
        risk_guard_enabled=False,
        ai_review_mode="disabled",
        ai_review_cfg={"enabled": False},
    )

    assert captured["pool_id"] == "range_pool"
    assert captured["edge_trigger_enabled"] is False
    assert captured["edge_cooldown_seconds"] == 600


def test_execute_symbol_signal_decision_blocks_new_entry_below_min_open_portion():
    bot = TradingBot.__new__(TradingBot)
    pending_new_entries = []
    captured = {}
    bot.fund_flow_risk_engine = SimpleNamespace(min_open_portion=0.06)
    bot._materialize_flow_snapshot = lambda symbol, market_data: (
        None,
        SimpleNamespace(signal_strength=1.0, timestamp=market_data["timestamp"]),
        {},
    )
    bot._update_extreme_volatility_state = lambda symbol, flow_context: {"blocked": False}
    bot._conflict_symbol_cooldown_state = lambda symbol: {"blocked": False}
    bot._entry_window_state = lambda: {"allowed": True}
    bot._ma10_macd_confluence_config = lambda: {"enabled": False}
    bot._resolve_runtime_signal_pool_config = lambda pool_id: {}
    bot._apply_ma10_macd_entry_filter = lambda symbol, decision: decision
    bot._apply_pretrade_risk_gate = lambda **kwargs: (kwargs["decision"], {"action": "BYPASS"})
    bot._is_cooldown_active = lambda: False
    bot._resolve_dynamic_max_active_symbols = lambda **kwargs: (kwargs["base_max_active_symbols"], {})
    bot._decision_signal_score = lambda decision, flow_context=None: 0.7
    bot._log_entry_gate_block = lambda **kwargs: captured.update(kwargs)

    class _TriggerEngine:
        def should_trigger(self, **kwargs):
            return True

        def evaluate_signal_pool(self, **kwargs):
            return {"passed": True, "reason": "ok"}

    class _DecisionEngine:
        def decide(self, **kwargs):
            return FundFlowDecision(
                operation=FundFlowOperation.SELL,
                symbol=kwargs["symbol"],
                target_portion_of_balance=0.001249,
                leverage=1.0,
                reason="tiny trial",
                metadata={"engine": "TREND"},
            )

    bot.fund_flow_trigger_engine = _TriggerEngine()
    bot.fund_flow_decision_engine = _DecisionEngine()

    bot._execute_symbol_signal_decision(
        symbol="ATOMUSDT",
        market_data={"timestamp": datetime(2026, 5, 2, tzinfo=timezone.utc)},
        position=None,
        current_price=1.0,
        account_summary={"available_balance": 1000.0, "equity": 1000.0},
        pending_new_entries=pending_new_entries,
        protection_gap_symbols=[],
        block_new_entries_due_to_protection_gap=False,
        allow_new_entries=True,
        ff_cfg={"trigger_dedupe_seconds": 180, "signal_pool": {"enabled": False}},
        max_active_symbols=10,
        max_symbol_position_portion=0.6,
        add_position_portion=0.2,
        risk_guard_enabled=False,
        ai_review_mode="disabled",
        ai_review_cfg={"enabled": False},
    )

    assert pending_new_entries == []
    assert captured["gate"] == "min_open_portion"
    assert captured["reason"] == "target_below_min_open"
    assert captured["threshold"] == 0.06
    assert captured["value"] == 0.001249


def test_global_signal_pool_disable_skips_outer_pool_evaluation():
    bot = TradingBot.__new__(TradingBot)

    class _ReachedNextStage(Exception):
        pass

    bot._materialize_flow_snapshot = lambda symbol, market_data: (
        None,
        SimpleNamespace(signal_strength=1.0, timestamp=market_data["timestamp"]),
        {},
    )
    bot._update_extreme_volatility_state = lambda symbol, flow_context: {"blocked": False}
    bot._conflict_symbol_cooldown_state = lambda symbol: {"blocked": False}
    bot._entry_window_state = lambda: {"allowed": True}
    bot._ma10_macd_confluence_config = lambda: {"enabled": False}
    bot._resolve_runtime_signal_pool_config = lambda pool_id: {
        "pool_id": pool_id,
        "id": pool_id,
        "enabled": True,
    }

    class _TriggerEngine:
        def should_trigger(self, **kwargs):
            return True

        def evaluate_signal_pool(self, **kwargs):
            raise AssertionError("signal_pool should be bypassed when globally disabled")

    class _DecisionEngine:
        def decide(self, **kwargs):
            return FundFlowDecision(
                operation=FundFlowOperation.BUY,
                symbol=kwargs["symbol"],
                target_portion_of_balance=0.1,
                leverage=1.0,
                reason="test",
                metadata={"engine": "TREND", "signal_pool_id": "trend_pool"},
            )

    def _stop_after_pool_bypass(symbol, decision):
        raise _ReachedNextStage()

    bot.fund_flow_trigger_engine = _TriggerEngine()
    bot.fund_flow_decision_engine = _DecisionEngine()
    bot._apply_ma10_macd_entry_filter = _stop_after_pool_bypass

    try:
        bot._execute_symbol_signal_decision(
            symbol="VETUSDT",
            market_data={"timestamp": __import__("datetime").datetime(2026, 3, 25)},
            position=None,
            current_price=1.0,
            account_summary={"available_balance": 1000.0, "equity": 1000.0},
            pending_new_entries=[],
            protection_gap_symbols=[],
            block_new_entries_due_to_protection_gap=False,
            allow_new_entries=True,
            ff_cfg={"trigger_dedupe_seconds": 180, "signal_pool": {"enabled": False}},
            max_active_symbols=10,
            max_symbol_position_portion=0.1,
            add_position_portion=0.0,
            risk_guard_enabled=False,
            ai_review_mode="disabled",
            ai_review_cfg={"enabled": False},
        )
    except _ReachedNextStage:
        pass
    else:
        raise AssertionError("expected to reach the next stage after signal_pool bypass")


def test_execute_symbol_signal_decision_logs_blocked_gate_payload():
    bot = TradingBot.__new__(TradingBot)
    captured = {}

    bot._materialize_flow_snapshot = lambda symbol, market_data: (
        {"symbol": symbol},
        SimpleNamespace(signal_strength=1.0, timestamp=market_data["timestamp"]),
        {"active_timeframe": "15m"},
    )
    bot._update_extreme_volatility_state = lambda symbol, flow_context: {
        "blocked": True,
        "remaining_seconds": 90,
        "atr_pct": 0.031,
        "threshold": 0.02,
        "streak": 3,
        "timeframe": "1m",
        "reason": "extreme_volatility",
    }
    bot._conflict_symbol_cooldown_state = lambda symbol: {"blocked": False}
    bot._log_entry_gate_block = lambda **kwargs: captured.update(kwargs)

    bot._execute_symbol_signal_decision(
        symbol="BTCUSDT",
        market_data={"timestamp": __import__("datetime").datetime(2026, 3, 25)},
        position=None,
        current_price=1.0,
        account_summary={"available_balance": 1000.0, "equity": 1000.0},
        pending_new_entries=[],
        protection_gap_symbols=[],
        block_new_entries_due_to_protection_gap=False,
        allow_new_entries=True,
        ff_cfg={"trigger_dedupe_seconds": 180},
        max_active_symbols=10,
        max_symbol_position_portion=0.1,
        add_position_portion=0.0,
        risk_guard_enabled=False,
        ai_review_mode="disabled",
        ai_review_cfg={"enabled": False},
    )

    assert captured["gate"] == "extreme_volatility_cooldown"
    assert captured["threshold"] == 0.02
    assert captured["value"] == 0.031
    assert captured["extra"]["remaining_seconds"] == 90


def test_write_trade_fill_log_normalizes_fee_sign_and_realized_pnl():
    bot = TradingBot.__new__(TradingBot)
    captured = []
    bot._trade_fill_logged_keys = set()
    bot._trade_fill_last_seen_ms_by_symbol = {}
    trade_ts = int(datetime(2026, 4, 25, 18, 45, 12, tzinfo=timezone.utc).timestamp() * 1000)
    bot._fetch_order_trade_fills = lambda symbol, order_id: [
        {
            "orderId": 123,
            "id": 456,
            "time": trade_ts,
            "side": "SELL",
            "qty": "10",
            "price": "0.09750",
            "quoteQty": "0.975",
            "commission": "0.0005",
            "commissionAsset": "USDT",
            "realizedPnl": "-0.0123",
        }
    ]
    bot._append_trade_fill_rows = lambda rows: captured.extend(rows)

    bot._write_trade_fill_log(
        symbol="DOGEUSDT",
        decision=FundFlowDecision(
            operation=FundFlowOperation.CLOSE,
            symbol="DOGEUSDT",
            target_portion_of_balance=1.0,
            leverage=1.0,
            reason="test close",
        ),
        execution_result={"order": {"orderId": 123, "side": "SELL"}},
    )

    assert len(captured) == 1
    assert captured[0]["手续费"] == -0.0005
    assert captured[0]["已实现盈亏"] == -0.0123
    assert captured[0]["订单ID"] == "123"
    assert captured[0]["成交ID"] == "456"


def test_sync_recent_trade_fills_reconciles_exchange_side_close_fills():
    bot = TradingBot.__new__(TradingBot)
    captured = []
    bot._trade_fill_logged_keys = set()
    bot._trade_fill_last_seen_ms_by_symbol = {}
    trade_ts = int(datetime(2026, 4, 25, 23, 30, 10, tzinfo=timezone.utc).timestamp() * 1000)

    def _fetch(symbol, order_id):
        assert order_id is None
        if symbol == "VETUSDT":
            return [
                {
                    "orderId": 789,
                    "id": 999,
                    "time": trade_ts,
                    "side": "BUY",
                    "qty": "4424",
                    "price": "0.007354",
                    "quoteQty": "32.531696",
                    "commission": "0.0162",
                    "commissionAsset": "USDT",
                    "realizedPnl": "-0.3415",
                }
            ]
        return []

    bot._fetch_order_trade_fills = _fetch
    bot._append_trade_fill_rows = lambda rows: captured.extend(rows)

    bot._sync_recent_trade_fills(["VETUSDT", "DOGEUSDT"])

    assert len(captured) == 1
    assert captured[0]["合约"] == "VETUSDT"
    assert captured[0]["方向"] == "买入"
    assert captured[0]["手续费"] == -0.0162
    assert captured[0]["已实现盈亏"] == -0.3415
    assert captured[0]["来源"] == "user_trades"
