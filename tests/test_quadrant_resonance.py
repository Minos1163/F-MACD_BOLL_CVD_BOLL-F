from __future__ import annotations

import pytest

from src.fund_flow.models import Operation
from src.fund_flow.quadrant_resonance import (
    Quadrant,
    QuadrantResonanceConfig,
    QuadrantResonanceEngine,
)
from src.fund_flow.decision_engine import FundFlowDecisionEngine


def _engine(**overrides) -> QuadrantResonanceEngine:
    cfg = QuadrantResonanceConfig.from_dict(overrides)
    return QuadrantResonanceEngine(cfg)


def _tf(
    *,
    close: float = 100.0,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    ema20: float = 99.0,
    ema50: float = 95.0,
    ema200: float = 90.0,
    macd_hist_series: list[float] | None = None,
    rsi: float = 55.0,
    atr: float = 2.0,
) -> dict:
    return {
        "open": close * 0.995 if open is None else open,
        "high": close * 1.005 if high is None else high,
        "low": close * 0.99 if low is None else low,
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "macd_hist_series": macd_hist_series or [0.01, 0.02, 0.03],
        "rsi": rsi,
        "atr": atr,
    }


def _timeframes(
    *,
    q4h: dict | None = None,
    tf1h: dict | None = None,
    tf15m: dict | None = None,
) -> dict:
    return {
        "4h": q4h or _tf(),
        "1h": tf1h or _tf(),
        "15m": tf15m or _tf(macd_hist_series=[-0.01, 0.02]),
    }


def test_detects_all_four_quadrants_and_defense() -> None:
    engine = _engine()

    assert engine.detect_quadrant(_tf(ema20=105, ema50=100, ema200=90, macd_hist_series=[0.1, 0.2, 0.3])) is Quadrant.Q1
    assert engine.detect_quadrant(_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[0.1, 0.2, 0.3])) is Quadrant.Q2
    assert engine.detect_quadrant(_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[-0.1, -0.2, -0.3])) is Quadrant.Q3
    assert engine.detect_quadrant(_tf(ema20=105, ema50=100, ema200=90, macd_hist_series=[-0.1, -0.2, -0.3])) is Quadrant.Q4
    assert engine.detect_quadrant(_tf(ema20=100, ema50=105, ema200=90, macd_hist_series=[0.1, 0.2, 0.3])) is Quadrant.DEFENSE


def test_q1_long_entry_scores_without_vwap_dependency() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.direction == "long"
    assert result.quadrant is Quadrant.Q1
    assert result.resonance_score == pytest.approx(1.0)
    assert "vwap" not in result.factor_scores
    assert result.metadata["min_entry_notional_usdt"] == pytest.approx(12.0)
    assert result.metadata["leverage_cap"] == 3


def test_quadrant_position_portion_uses_notional_floor_and_leverage_adjusted_risk() -> None:
    engine = _engine(risk={"risk_per_trade_pct": 0.01, "min_entry_notional_usdt": 8.0, "min_entry_margin_usdt": 1.0, "max_leverage": 3})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02], rsi=55, atr=2.0)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    # ATR stop = 2.0 * default 1.2 = 2.4%; margin risk at 3x = 1% / (2.4% * 3).
    assert result.target_portion == pytest.approx(0.01 / (0.024 * 3.0), rel=1e-6)


def test_defense_mode_blocks_new_entries() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(q4h=_tf(ema20=100, ema50=105, ema200=90)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "quadrant_defense_no_entry"
    assert result.metadata["quadrant_debug"]["ema_state_4h"] == 0
    assert result.metadata["quadrant_debug"]["blocked_reason_detail"] == "ema_disorder"
    assert result.metadata["quadrant_debug"]["macd_hist_4h_last3"] == [0.01, 0.02, 0.03]
    assert result.metadata["blocked_reason_detail"] == "ema_disorder"


def test_defense_metadata_marks_missing_4h_indicators() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(q4h={"close": 100.0, "ema20": 100.0}),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "quadrant_defense_no_entry"
    debug = result.metadata["quadrant_debug"]
    assert debug["blocked_reason_detail"] == "missing_indicators_multiple"
    assert debug["missing_indicator_fields"] == ["ema50", "ema200", "macd_hist"]
    assert result.metadata["blocked_reason_detail"] == "missing_indicators_multiple"
    assert debug["macd_pos_strength_4h"] is False
    assert debug["macd_neg_strength_4h"] is False


def test_defense_metadata_marks_single_missing_4h_indicator() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(q4h=_tf(ema20=0.0, ema50=100.0, ema200=90.0)),
        portfolio={"equity": 100.0},
    )

    debug = result.metadata["quadrant_debug"]
    assert debug["blocked_reason_detail"] == "missing_indicators_ema20"
    assert debug["missing_indicator_fields"] == ["ema20"]
    assert result.metadata["blocked_reason_detail"] == "missing_indicators_ema20"


def test_defense_metadata_marks_macd_not_strengthening_and_close_alignment() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(q4h=_tf(ema20=101.0, ema50=100.0, ema200=100.2, macd_hist_series=[0.03, 0.02, 0.01])),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "quadrant_defense_no_entry"
    debug = result.metadata["quadrant_debug"]
    assert debug["ema_state_4h"] == 0
    assert debug["blocked_reason_detail"] == "macd_not_strengthening"
    assert debug["ema_close_to_alignment"] is True
    assert debug["ema20_50_cross_pct"] == pytest.approx(0.01)
    assert debug["ema50_200_cross_pct"] == pytest.approx(-0.001996, rel=1e-3)


def test_rsi_extreme_and_ema_distance_block_chasing() -> None:
    engine = _engine()

    high_rsi = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf1h=_tf(rsi=80), tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02])),
        portfolio={"equity": 100.0},
    )
    far_from_ema = engine.analyze(
        symbol="ICPUSDT",
        price=110.0,
        timeframes=_timeframes(tf1h=_tf(close=110, ema20=100, atr=2), tf15m=_tf(close=110, ema20=109.5, macd_hist_series=[-0.01, 0.02])),
        portfolio={"equity": 100.0},
    )

    assert high_rsi.allowed is False
    assert high_rsi.reason == "rsi_extreme_block"
    assert far_from_ema.allowed is False
    assert far_from_ema.reason == "ema20_distance_chase_block"


def test_short_q3_entry_is_symmetric() -> None:
    engine = _engine()
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[-0.1, -0.2, -0.3]),
            tf1h=_tf(close=100, ema20=101, ema50=105, ema200=110, macd_hist_series=[-0.01, -0.02, -0.03], rsi=50),
            tf15m=_tf(close=100, ema20=100.5, macd_hist_series=[0.01, -0.02], rsi=50),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.direction == "short"
    assert result.quadrant is Quadrant.Q3
    assert result.resonance_score == pytest.approx(1.0)


def test_standard_quadrant_requires_entry_pattern_when_enabled() -> None:
    engine = _engine(entry={"standard_threshold": 0.85, "require_15m_entry_pattern": True})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"


def test_high_score_missing_15m_entry_pattern_degrades_to_probe_when_enabled() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "high_score_probe_portion": 0.042,
        }
    )
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m"
    assert result.target_portion == pytest.approx(0.042)
    assert result.metadata["signal_quality"] == "degraded_no_15m"
    assert result.metadata["override_reason"] == "high_score_15m_override"
    assert result.metadata["blocked_reason"] == "missing_15m_entry_pattern"


def test_high_score_missing_15m_probe_respects_min_entry_margin_floor() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "high_score_probe_portion": 0.042,
        },
        risk={"min_entry_margin_usdt": 1.0},
    )
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55)),
        portfolio={"equity": 20.0},
    )

    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m"
    assert result.target_portion == pytest.approx(0.05)
    assert result.metadata["target_portion"] == pytest.approx(0.05)


def test_high_score_missing_15m_override_still_requires_entry_threshold() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.95,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "high_score_probe_portion": 0.042,
        }
    )
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"
    assert result.resonance_score == pytest.approx(0.9)


def test_mid_score_requires_three_1h_macd_bars_when_enabled() -> None:
    engine = _engine(entry={"standard_threshold": 0.85, "mid_score_requires_3bar_macd": True})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=80),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "mid_score_needs_3bar_macd"


def test_4h_rsi_extreme_penalty_applies_before_threshold() -> None:
    engine = _engine(entry={"standard_threshold": 0.95, "extreme_4h_rsi_penalty": 0.05})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(rsi=75),
            tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.resonance_score == pytest.approx(0.95)
    assert result.metadata["extreme_4h_rsi_penalty"] == pytest.approx(0.05)


def test_close_confirm_stop_does_not_exit_on_wick_only() -> None:
    engine = _engine(exit={"stop_trigger": "close_confirm", "hard_stop_atr_mult": 1.5})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=99.2,
        timeframes={"15m": _tf(close=99.2, low=97.0, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"stage": "validation"},
    )

    assert result["action"] == "hold"


def test_close_confirm_stop_exits_on_close_breach() -> None:
    engine = _engine(exit={"stop_trigger": "close_confirm", "hard_stop_atr_mult": 1.5})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=96.9,
        timeframes={"15m": _tf(close=96.9, low=96.8, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"stage": "validation"},
    )

    assert result["action"] == "close"
    assert result["reason"] == "HARD_STOP_LOSS_CLOSE_CONFIRMED"


def test_tp1_reduces_30_percent_and_moves_to_trend_stage() -> None:
    engine = _engine(exit={"tp1_atr_mult": 1.2, "tp1_reduce_pct": 0.30, "ema20_trailing_enabled": True})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=102.5,
        timeframes={"15m": _tf(close=102.5, high=102.5, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"tp1_done": False},
    )

    assert result == {
        "action": "reduce",
        "ratio": 0.30,
        "reason": "TP1_REDUCE_TO_EMA_TRAIL",
        "updates": {"tp1_done": True, "stage": "trend", "stop_price": 100.0},
    }


def test_decision_engine_routes_quadrant_resonance_to_fund_flow_decision() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {"risk": {"min_entry_notional_usdt": 12.0}},
            }
        }
    )

    decision = engine.decide(
        "ICPUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {"timeframes": _timeframes()},
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert decision.operation is Operation.BUY
    assert decision.leverage == 3
    assert decision.target_portion_of_balance >= 0.04
    assert decision.metadata["strategy_mode"] == "quadrant_resonance"
    assert decision.metadata["quadrant_4h"] == "Q1"
    assert "vwap_score" not in decision.metadata


def test_decision_engine_routes_degraded_missing_15m_probe_to_entry() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "standard_threshold": 0.85,
                        "require_15m_entry_pattern": True,
                        "high_score_15m_override": True,
                        "high_score_15m_override_threshold": 0.85,
                        "high_score_probe_portion": 0.042,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )

    decision = engine.decide(
        "ICPUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {"timeframes": _timeframes(tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55))},
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert decision.operation is Operation.BUY
    assert decision.reason == "quadrant_resonance_probe_no_15m"
    assert decision.target_portion_of_balance == pytest.approx(0.042)
    assert decision.metadata["signal_quality"] == "degraded_no_15m"
    assert decision.metadata["blocked_reason"] == "missing_15m_entry_pattern"


def test_decision_engine_writes_quadrant_entry_audit_jsonl(tmp_path) -> None:
    audit_path = tmp_path / "entry_decision.jsonl"
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "risk": {"min_entry_notional_usdt": 12.0},
                    "audit": {"entry_decision_path": str(audit_path)},
                },
            }
        }
    )

    engine.decide(
        "ICPUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {"timeframes": _timeframes()},
        use_weight_router=False,
        use_ai_weights=False,
    )

    rows = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    assert '"type":"ENTRY_DECISION"' in rows[0]
    assert '"strategy_mode":"quadrant_resonance"' in rows[0]
    assert '"quadrant_4h":"Q1"' in rows[0]


def test_decision_engine_writes_quadrant_blocked_audit_debug_jsonl(tmp_path) -> None:
    audit_path = tmp_path / "entry_decision.jsonl"
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "audit": {"entry_decision_path": str(audit_path)},
                },
            }
        }
    )

    decision = engine.decide(
        "ICPUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {"timeframes": _timeframes(q4h=_tf(ema20=100, ema50=105, ema200=90))},
        use_weight_router=False,
        use_ai_weights=False,
    )

    rows = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert decision.operation is Operation.HOLD
    assert len(rows) == 1
    assert '"reason":"quadrant_defense_no_entry"' in rows[0]
    assert '"blocked_reason_detail":"ema_disorder"' in rows[0]
    assert '"quadrant_debug"' in rows[0]
