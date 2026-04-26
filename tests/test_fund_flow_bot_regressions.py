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
