from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.fund_flow_bot import TradingBot
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
