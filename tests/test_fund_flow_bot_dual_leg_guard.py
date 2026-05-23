from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

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
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.003}}
    bot._position_first_seen_ts = {"ADAUSDT:LONG": 1000.0}
    bot._btc_beta_recent_returns = lambda symbol: {  # type: ignore[method-assign]
        "btc_ret_15m": -0.0005,
        "btc_ret_30m": -0.0010,
        "alt_ret_15m": -0.0012,
        "alt_ret_30m": -0.0010,
    }
    bot._btc_beta_position_age_bars = lambda _key: 1  # type: ignore[method-assign]
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
        metadata={"signal_1h": "red_bar_growing"},
    )
    position = {"side": "LONG", "entry_price": 1.0, "amount": 20.0}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.997,
        decision=decision,
        decision_md=decision.metadata,
    )

    assert adjusted.operation == Operation.CLOSE
    assert adjusted.target_portion_of_balance == pytest.approx(0.5)
    assert adjusted.reason.startswith("BETA_RISK_REDUCE")
    assert meta["action"] == "REDUCE_50"
    assert decision.metadata["btc_beta_risk"]["action"] == "REDUCE_50"


def test_btc_beta_risk_closes_small_notional_instead_of_reduce() -> None:
    bot = _bot(
        {"fund_flow": {"btc_beta_risk": {"enabled": True, "small_notional_close_threshold": 10.0}}}
    )
    bot._dca_blocked_by_exit_guard = set()
    bot._position_extrema_by_pos = {"ADAUSDT:LONG": {"max_favorable_ratio": 0.001, "max_adverse_ratio": -0.003}}
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
        __import__("src.fund_flow.btc_beta_risk", fromlist=["BtcBetaRiskConfig"]).BtcBetaRiskConfig(
            small_notional_close_threshold=10.0
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
    position = {"side": "LONG", "entry_price": 1.0, "amount": 5.0}

    adjusted, meta = bot._apply_position_exit_signal_guard(
        symbol="ADAUSDT",
        position=position,
        current_price=0.997,
        decision=decision,
        decision_md=decision.metadata,
    )

    assert adjusted.operation == Operation.CLOSE
    assert adjusted.target_portion_of_balance == pytest.approx(1.0)
    assert adjusted.reason.startswith("BETA_RISK_CLOSE")
    assert meta["action"] == "CLOSE"
    assert meta["small_notional_close"] is True


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
