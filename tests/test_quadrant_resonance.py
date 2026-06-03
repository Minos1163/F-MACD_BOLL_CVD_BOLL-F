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
    close_series: list[float] | None = None,
    high_series: list[float] | None = None,
    low_series: list[float] | None = None,
    macd_hist_series: list[float] | None = None,
    rsi: float = 55.0,
    atr: float = 2.0,
) -> dict:
    out = {
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
    if close_series is not None:
        out["close_series"] = close_series
    if high_series is not None:
        out["high_series"] = high_series
    if low_series is not None:
        out["low_series"] = low_series
    return out


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


def test_quadrant_config_parses_direction_generator_fields() -> None:
    cfg = QuadrantResonanceConfig.from_dict(
        {
            "entry": {
                "direction_generates_both": True,
                "quadrant_4h_role": "ema_filter",
                "ema_conflict_entry_penalty": 0.10,
                "direction_transition_mode_enabled": True,
                "direction_transition_1h_min_abs": 0.05,
            }
        }
    )

    assert cfg.direction_generates_both is True
    assert cfg.quadrant_4h_role == "ema_filter"
    assert cfg.ema_conflict_entry_penalty == pytest.approx(0.10)
    assert cfg.direction_transition_mode_enabled is True
    assert cfg.direction_transition_1h_min_abs == pytest.approx(0.05)


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


def test_quadrant_metadata_includes_closed_bar_direction_quality_fields() -> None:
    engine = _engine(entry={"standard_threshold": 0.85})
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.04, 0.03, 0.02], rsi=69),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=72),
        ),
        portfolio={"equity": 100.0},
    )

    md = result.metadata
    assert md["entry_rsi_15m"] == pytest.approx(72.0)
    assert md["entry_rsi_1h"] == pytest.approx(69.0)
    assert md["macd_hist_15m_last3"] == [0.03, 0.02, 0.01]
    assert md["macd_hist_1h_last3"] == [0.04, 0.03, 0.02]
    assert md["macd_hist_15m_strengthening"] is False
    assert md["macd_hist_1h_strengthening"] is False
    assert md["entry_15m_detail"]["near_ema"] is True
    assert md["entry_15m_detail"]["hist_cross"] is False
    assert md["entry_15m_detail"]["direction_candle"] is False


def test_15m_entry_quality_scores_partial_setup_without_opening_trade() -> None:
    engine = _engine(entry={"standard_threshold": 0.85})
    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    detail = result.metadata["entry_15m_detail"]
    assert detail["ok"] is False
    assert result.metadata["entry_15m_quality_score"] == pytest.approx(0.55)
    assert result.metadata["entry_15m_quality_bucket"] == "watch"
    assert result.metadata["entry_15m_missing_conditions"] == ["hist_cross", "direction_candle", "pin_bar"]


def test_15m_entry_quality_marks_open_bucket_for_existing_valid_pattern() -> None:
    engine = _engine(entry={"standard_threshold": 0.85})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=99.8,
                high=100.25,
                low=99.75,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[-0.01, -0.005, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.metadata["entry_15m_detail"]["ok"] is True
    assert result.metadata["entry_15m_quality_score"] >= 0.75
    assert result.metadata["entry_15m_quality_bucket"] == "open"


def test_missing_15m_high_partial_quality_emits_watchlist_intent_without_entry() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.95,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": True,
            "watchlist_min_signal_score": 0.75,
        }
    )
    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"
    assert result.metadata["watchlist_intent"]["enabled"] is True
    assert result.metadata["watchlist_intent"]["dry_run"] is True
    assert result.metadata["watchlist_intent"]["side"] == "long"
    assert result.metadata["watchlist_intent"]["candidate_reason"] == "missing_15m_entry_pattern"
    assert "hist_cross" in result.metadata["watchlist_intent"]["missing_conditions"]


def test_entry_15m_quality_live_mode_allows_open_bucket_without_legacy_pattern() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.55,
            "entry_15m_quality_watch_min": 0.50,
        }
    )

    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.9,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.metadata["entry_15m_detail"]["ok"] is False
    assert result.metadata["entry_15m_quality_score"] == pytest.approx(0.55)
    assert result.metadata["entry_15m_quality_bucket"] == "open"
    assert result.allowed is True
    assert result.reason == "quadrant_resonance_pass"
    assert result.metadata["entry_15m_quality_live_pass"] is True


def test_entry_15m_quality_live_mode_watch_bucket_adds_watchlist_without_entry() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": False,
        }
    )

    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"
    assert result.metadata["entry_15m_quality_score"] == pytest.approx(0.55)
    assert result.metadata["entry_15m_quality_bucket"] == "watch"
    assert result.metadata["watchlist_intent"]["dry_run"] is False


def test_entry_15m_quality_live_mode_hold_bucket_stays_hold() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": False,
        }
    )

    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=103.0,
                open=103.2,
                high=103.25,
                low=102.95,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.03, 0.02, 0.01],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"
    assert result.metadata["entry_15m_quality_score"] < 0.50
    assert "watchlist_intent" not in result.metadata


def test_structural_entry_quality_opens_trend_continuation_without_single_bar_pattern() -> None:
    engine = _engine(
        entry={
            "entry_15m_quality_model": "structural_v2",
            "entry_15m_quality_open_min": 0.60,
            "entry_15m_quality_watch_min": 0.40,
        }
    )
    tf15 = _tf(
        close=115.0,
        open=115.4,
        high=115.3,
        low=114.8,
        ema20=114.8,
        atr=1.0,
        close_series=[
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
            116.0,
            116.7,
            116.2,
            115.8,
            115.2,
            114.8,
            114.4,
            114.1,
            114.6,
            115.0,
            115.4,
            115.8,
            115.3,
            115.0,
        ],
        high_series=[
            110.5,
            111.5,
            112.5,
            113.5,
            114.5,
            115.5,
            116.4,
            116.9,
            116.5,
            116.0,
            115.7,
            115.3,
            115.0,
            114.8,
            115.1,
            115.4,
            115.8,
            116.0,
            115.6,
            115.3,
        ],
        low_series=[
            109.7,
            110.7,
            111.7,
            112.7,
            113.7,
            114.5,
            115.2,
            115.9,
            115.4,
            115.0,
            114.7,
            114.3,
            114.0,
            113.8,
            114.2,
            114.6,
            115.0,
            115.3,
            115.0,
            114.8,
        ],
        macd_hist_series=[0.01, 0.012, 0.014, 0.018, 0.024],
    )

    detail = engine._entry_pattern_detail("long", tf15)
    quality = engine._entry_15m_quality("long", tf15, detail=detail)

    assert detail["hist_cross"] is False
    assert detail["direction_candle"] is False
    assert detail["pin_bar"] is False
    assert quality["score"] >= 0.60
    assert quality["bucket"] == "open"
    assert "direction_candle" not in quality["missing_conditions"]


def test_structural_entry_quality_penalizes_long_chase_far_from_ema() -> None:
    engine = _engine(
        entry={
            "entry_15m_quality_model": "structural_v2",
            "entry_15m_quality_open_min": 0.60,
            "entry_15m_quality_watch_min": 0.40,
        }
    )
    tf15 = _tf(
        close=120.0,
        open=119.7,
        high=120.4,
        low=119.5,
        ema20=116.0,
        atr=1.0,
        close_series=[
            110.0,
            110.5,
            111.0,
            111.5,
            112.0,
            112.5,
            113.0,
            113.5,
            114.0,
            114.5,
            115.0,
            115.5,
            116.0,
            116.5,
            117.0,
            117.5,
            118.0,
            118.5,
            119.0,
            120.0,
        ],
        high_series=[
            110.3,
            110.8,
            111.3,
            111.8,
            112.3,
            112.8,
            113.3,
            113.8,
            114.3,
            114.8,
            115.3,
            115.8,
            116.3,
            116.8,
            117.3,
            117.8,
            118.3,
            118.8,
            119.3,
            120.4,
        ],
        low_series=[
            109.8,
            110.3,
            110.8,
            111.3,
            111.8,
            112.3,
            112.8,
            113.3,
            113.8,
            114.3,
            114.8,
            115.3,
            115.8,
            116.3,
            116.8,
            117.3,
            117.8,
            118.3,
            118.8,
            119.5,
        ],
        macd_hist_series=[0.01, 0.012, 0.014, 0.018, 0.024],
    )

    quality = engine._entry_15m_quality("long", tf15)

    assert quality["score"] < 0.30
    assert quality["bucket"] == "hold"


def test_structural_entry_quality_requires_multi_bar_history() -> None:
    engine = _engine(
        entry={
            "entry_15m_quality_model": "structural_v2",
            "entry_15m_quality_open_min": 0.60,
            "entry_15m_quality_watch_min": 0.40,
        }
    )
    tf15 = _tf(
        close=100.0,
        open=99.8,
        high=100.3,
        low=99.7,
        ema20=99.9,
        atr=1.0,
        macd_hist_series=[0.01, 0.012, 0.014, 0.018, 0.024],
    )

    quality = engine._entry_15m_quality("long", tf15)

    assert quality["score"] == pytest.approx(0.0)
    assert quality["bucket"] == "hold"
    assert "structural_history" in quality["missing_conditions"]


def test_probe_veto_reversible_breadth_emits_watchlist_intent() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": True,
            "watchlist_include_probe_veto": True,
        }
    )
    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 0, "invalid_count": 2}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert "watchlist_intent" not in result.metadata


def test_quadrant_defense_can_emit_recovering_state_metadata_without_entry() -> None:
    engine = _engine(entry={"quadrant_4h_three_state_enabled": True})
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105.0,
                ema50=100.0,
                ema200=90.0,
                macd_hist_series=[-0.03, -0.02, -0.01],
            ),
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03]),
            tf15m=_tf(macd_hist_series=[0.01, 0.02, 0.03]),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "quadrant_defense_no_entry"
    assert result.metadata["quadrant_state"] == "recovering"
    assert result.metadata["quadrant_recovering_direction"] == "long"


def test_4h_recovering_state_can_enter_half_position_when_enabled() -> None:
    engine = _engine(
        entry={
            "quadrant_4h_three_state_enabled": True,
            "quadrant_4h_three_state_act_on_recovering": True,
            "recovering_state_score_threshold": 0.80,
            "recovering_state_portion_multiplier": 0.50,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
        }
    )

    recovering = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=105.0, ema50=100.0, ema200=90.0, macd_hist_series=[-0.03, -0.02, -0.01]),
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=101.0, low=99.6, ema20=99.7, atr=1.0, macd_hist_series=[-0.01, -0.005, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )
    standard = _engine(entry={"entry_15m_quality_mode": "live", "entry_15m_quality_open_min": 0.70}).analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=105.0, ema50=100.0, ema200=90.0, macd_hist_series=[0.01, 0.02, 0.03]),
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=101.0, low=99.6, ema20=99.7, atr=1.0, macd_hist_series=[-0.01, -0.005, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert recovering.allowed is True
    assert recovering.reason == "quadrant_resonance_recovering_reduced"
    assert recovering.metadata["quadrant_state"] == "recovering"
    assert recovering.metadata["allowed_reason"] == "quadrant_recovering_reduced"
    assert recovering.target_portion == pytest.approx(standard.target_portion * 0.50)


def test_4h_recovering_below_threshold_adds_watchlist_and_defense_still_holds() -> None:
    engine = _engine(
        entry={
            "quadrant_4h_three_state_enabled": True,
            "quadrant_4h_three_state_act_on_recovering": True,
            "recovering_state_score_threshold": 0.80,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": False,
            "watchlist_min_signal_score": 0.50,
        }
    )

    recovering_low = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=105.0, ema50=100.0, ema200=90.0, macd_hist_series=[-0.03, -0.02, -0.01]),
            tf1h=_tf(close=99.0, ema20=100.0, ema50=101.0, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=100.25, low=99.95, ema20=99.7, atr=1.0, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )
    defense = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(q4h=_tf(ema20=100.0, ema50=105.0, ema200=90.0)),
        portfolio={"equity": 100.0},
    )

    assert recovering_low.allowed is False
    assert recovering_low.reason == "quadrant_recovering_watchlist"
    assert recovering_low.metadata["quadrant_state"] == "recovering"
    assert recovering_low.metadata["watchlist_intent"]["candidate_reason"] == "quadrant_recovering_watchlist"
    assert defense.allowed is False
    assert defense.reason == "quadrant_defense_no_entry"
    assert defense.metadata["quadrant_state"] == "defense"


def _bad_hype_like_context() -> dict:
    return {
        "market_breadth": {
            "confirm_count": 0,
            "invalid_count": 2,
            "mode_a": "FAIL",
            "mode_b": "FAIL",
            "mode_c": "FAIL",
        },
        "flow": {
            "cvd": -0.0665,
            "oi_delta": -0.0020,
            "imbalance": -0.2635,
            "liq_norm": -0.1919,
        },
    }


def test_high_score_missing_15m_probe_blocks_bad_breadth_and_bearish_flow() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=69),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context=_bad_hype_like_context(),
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["blocked_reason"] == "probe_no_15m_direction_veto"
    assert "breadth_zero_confirm_invalid_2" in result.metadata["probe_no_15m_veto_reasons"]
    assert "long_flow_all_bearish" in result.metadata["probe_no_15m_veto_reasons"]


def test_high_score_missing_15m_probe_reads_live_flow_aliases() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={
            "market_breadth": {"confirm_count": 2, "invalid_count": 0},
            "cvd_ratio": -0.0665,
            "oi_delta_ratio": -0.0020,
            "imbalance": -0.2635,
            "liquidity_delta_norm": -0.1919,
        },
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert "long_flow_all_bearish" in result.metadata["probe_no_15m_veto_reasons"]
    assert "long_liq_flow_bearish" in result.metadata["probe_no_15m_veto_reasons"]


def test_high_score_missing_15m_probe_still_allows_confirmed_flow_context() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={
            "market_breadth": {"confirm_count": 2, "invalid_count": 0},
            "flow": {"cvd": 0.03, "oi_delta": 0.001, "imbalance": 0.05, "liq_norm": 0.0},
        },
    )

    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m"
    assert result.metadata["probe_no_15m_veto_reasons"] == []


def test_probe_min_15m_resonance_blocks_score_only_override_when_enabled() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.75,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.75,
            "probe_no_15m_veto_enabled": True,
            "probe_min_15m_resonance_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert "probe_veto_no_15m_resonance" in result.metadata["probe_no_15m_veto_reasons"]


def test_probe_min_15m_resonance_allows_15m_strengthening_without_full_entry_pattern() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "probe_no_15m_veto_enabled": True,
            "probe_min_15m_resonance_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m"
    assert result.metadata["entry_15m_detail"]["ok"] is False
    assert result.metadata["probe_no_15m_veto_reasons"] == []


def test_probe_direction_aware_breadth_blocks_short_against_strong_market_rise() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "probe_no_15m_veto_enabled": True,
            "probe_direction_breadth_veto_enabled": True,
        }
    )
    result = engine.analyze(
        symbol="VETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[-0.01, -0.02, -0.03]),
            tf1h=_tf(close=100, ema20=101, ema50=105, ema200=110, macd_hist_series=[-0.01, -0.02, -0.03], rsi=50),
            tf15m=_tf(close=100, open=99.8, high=100.25, low=99.95, ema20=100.5, macd_hist_series=[-0.03, -0.02, -0.01], rsi=50),
        ),
        portfolio={"equity": 100.0},
        market_context={
            "market_breadth": {
                "confirm_count": 1,
                "invalid_count": 0,
                "btc_ret_30m": 0.01437,
                "btc_ret_60m": 0.00934,
                "alt_median_60m": 0.01204,
            }
        },
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert any(reason.startswith("probe_veto_short_against_breadth") for reason in result.metadata["probe_no_15m_veto_reasons"])


def test_probe_zero_confirm_invalid_threshold_is_configurable() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_breadth_zero_confirm_invalid_min": 1,
        }
    )
    result = engine.analyze(
        symbol="SOLUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 0, "invalid_count": 1}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert "breadth_zero_confirm_invalid_1" in result.metadata["probe_no_15m_veto_reasons"]


def test_probe_resonance_and_flow_alignment_scores_can_veto_when_enabled() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.75,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.75,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": False,
            "probe_resonance_score_enabled": True,
            "probe_resonance_min_threshold": 0.55,
            "probe_flow_alignment_score_enabled": True,
            "probe_min_flow_alignment": -0.20,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context=_bad_hype_like_context(),
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["probe_resonance_score"] < 0.55
    assert result.metadata["probe_flow_alignment_score"] < -0.20
    assert "probe_veto_low_resonance_score" in result.metadata["probe_no_15m_veto_reasons"]
    assert "probe_veto_flow_misaligned" in result.metadata["probe_no_15m_veto_reasons"]


def test_probe_veto_graded_breadth_zero_confirm_rejects_instead_of_opening_half_probe() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "high_score_probe_portion": 0.042,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_veto_graded_enabled": True,
            "probe_veto_breadth_reduced_multiplier": 0.50,
        }
    )

    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=100.25, low=99.95, ema20=99.7, atr=1.0, macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 0, "invalid_count": 2}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["probe_veto_grade"]["action"] == "reject"
    assert result.metadata["probe_veto_grade"]["hard_reasons"] == ["breadth_zero_confirm_invalid_2"]


def test_probe_veto_graded_breadth_zero_confirm_is_hard_reject_even_when_configured() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "high_score_probe_portion": 0.042,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_veto_graded_enabled": True,
            "probe_veto_breadth_reduced_multiplier": 0.50,
        }
    )

    result = engine.analyze(
        symbol="JSTUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=100.25, low=99.95, ema20=99.7, atr=1.0, macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 0, "invalid_count": 2}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["probe_veto_grade"]["action"] == "reject"
    assert result.metadata["probe_veto_grade"]["hard_reasons"] == ["breadth_zero_confirm_invalid_2"]


def test_probe_override_rejects_entry_quality_hold_bucket() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "probe_no_15m_veto_enabled": True,
            "probe_min_entry_score_enabled": True,
            "probe_min_entry_score": 0.45,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
        }
    )

    result = engine.analyze(
        symbol="ALGOUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=97.5, atr=1.0, macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 2, "invalid_count": 0}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["entry_15m_quality_score"] == pytest.approx(0.20)
    assert result.metadata["entry_15m_quality_bucket"] == "hold"
    assert "probe_veto_entry_quality_hold" in result.metadata["probe_no_15m_veto_reasons"]


def test_multi_bar_direction_model_blocks_strong_15m_countertrend() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "direction_strong_conflict_min_abs": 0.30,
        }
    )

    result = engine.analyze(
        symbol="FETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(close_series=[100.0 + i for i in range(50)], macd_hist_series=[0.01, 0.02, 0.03]),
            tf1h=_tf(close_series=[100.0 + i * 0.5 for i in range(50)], macd_hist_series=[0.01, 0.02, 0.03]),
            tf15m=_tf(
                close_series=[120.0 - i * 0.8 for i in range(30)],
                close=96.8,
                ema20=97.0,
                macd_hist_series=[-0.03, -0.04, -0.05],
                rsi=55,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "multi_bar_direction_no_entry"
    gate = result.metadata["direction_gate"]
    assert gate["direction_model"] == "multi_bar_slope"
    assert gate["scores"]["15m"] < -0.30
    assert gate["blocked_reason"] == "15m_strong_countertrend"


def test_multi_bar_direction_model_blocks_insufficient_history() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
        }
    )

    result = engine.analyze(
        symbol="FETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(close_series=[100.0 + i for i in range(12)], macd_hist_series=[0.01, 0.02, 0.03]),
            tf1h=_tf(close_series=[100.0 + i for i in range(20)], macd_hist_series=[0.01, 0.02, 0.03]),
            tf15m=_tf(close_series=[100.0 + i for i in range(15)], macd_hist_series=[0.01, 0.02, 0.03]),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "multi_bar_direction_insufficient_history"
    assert result.metadata["direction_gate"]["history_counts"] == {"4h": 12, "1h": 20, "15m": 15}


def test_multi_bar_direction_scores_can_identify_short_when_legacy_quadrant_is_long() -> None:
    engine = _engine(
        entry={
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
        }
    )
    tf4h = _tf(
        ema20=105,
        ema50=100,
        ema200=90,
        close_series=[150.0 - i * 0.8 for i in range(50)],
        macd_hist_series=[0.03, 0.04, 0.05],
    )
    tf1h = _tf(close_series=[120.0 - i * 0.4 for i in range(50)])
    tf15 = _tf(close_series=[105.0 - i * 0.2 for i in range(30)])

    scores = engine._multi_bar_direction_scores(tf4h, tf1h, tf15)

    assert scores["long"]["ok"] is False
    assert scores["short"]["ok"] is True
    assert scores["short"]["direction"] == "short"
    assert scores["short"]["direction_score"] >= 0.30
    assert scores["long"]["direction_score"] < 0.0


def test_multi_bar_transition_direction_allows_strong_anchor_with_soft_1h() -> None:
    engine = _engine(
        entry={
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "direction_transition_mode_enabled": True,
            "direction_transition_1h_min_abs": 0.05,
        }
    )

    gate = engine._multi_bar_direction_gate(
        "short",
        _tf(close_series=[160.0 - i * 0.2 for i in range(50)]),
        _tf(close_series=[120.0 - i * 0.01 for i in range(50)]),
        _tf(close_series=[102.0 - i * 0.04 for i in range(30)]),
    )

    assert gate["ok"] is True
    assert gate["reason"] == "multi_bar_direction_transition_pass"
    assert gate["transition_mode"] is True
    assert gate["aligned_scores"]["4h"] >= 0.30
    assert 0.05 <= gate["aligned_scores"]["1h"] < 0.30
    assert gate["direction_score"] >= 0.30


def test_multi_bar_transition_mode_keeps_fully_aligned_direction_as_standard_pass() -> None:
    engine = _engine(
        entry={
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "direction_transition_mode_enabled": True,
            "direction_transition_1h_min_abs": 0.05,
        }
    )

    gate = engine._multi_bar_direction_gate(
        "short",
        _tf(close_series=[160.0 - i * 0.4 for i in range(50)]),
        _tf(close_series=[120.0 - i * 0.08 for i in range(50)]),
        _tf(close_series=[102.0 - i * 0.04 for i in range(30)]),
    )

    assert gate["ok"] is True
    assert gate["reason"] == "multi_bar_direction_pass"
    assert gate["transition_mode"] is False
    assert gate["aligned_scores"]["1h"] >= 0.30


def test_multi_bar_selects_no_direction_when_both_sides_below_threshold() -> None:
    engine = _engine(
        entry={
            "direction_model": "multi_bar_slope",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
        }
    )
    flat50 = [100.0 + ((i % 2) * 0.01) for i in range(50)]
    flat30 = [100.0 + ((i % 2) * 0.01) for i in range(30)]

    selected = engine._select_multi_bar_direction(
        _tf(close_series=flat50),
        _tf(close_series=flat50),
        _tf(close_series=flat30),
    )

    assert selected["ok"] is False
    assert selected["reason"] == "multi_bar_no_direction"
    assert selected["direction"] == ""
    assert selected["candidates"]["long"]["ok"] is False
    assert selected["candidates"]["short"]["ok"] is False


def test_multi_bar_direction_generator_can_select_short_despite_legacy_long_quadrant() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "ema_conflict_entry_penalty": 0.10,
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
        }
    )

    result = engine.analyze(
        symbol="FETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[150.0 - i * 0.8 for i in range(50)],
                macd_hist_series=[0.03, 0.04, 0.05],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=101.0,
                ema50=103.0,
                ema200=106.0,
                close_series=[120.0 - i * 0.4 for i in range(50)],
                macd_hist_series=[-0.01, -0.02, -0.03],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=100.3,
                high=100.4,
                low=99.8,
                ema20=100.2,
                atr=1.0,
                close_series=[105.0 - i * 0.2 for i in range(30)],
                macd_hist_series=[0.01, -0.02],
                rsi=50,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.direction == "short"
    assert result.metadata["direction_gate"]["selected_direction"] == "short"
    assert result.metadata["direction_gate"]["candidates"]["short"]["ok"] is True
    assert result.metadata["quadrant_filter"]["ema_conflict"] is True
    assert result.metadata["ema_conflict"] is True
    assert result.metadata["entry_15m_base_open_min"] == pytest.approx(0.70)
    assert result.metadata["entry_15m_effective_open_min"] == pytest.approx(0.80)
    assert result.metadata["entry_15m_quality_bucket_effective"] in {"hold", "watch", "open"}


def test_multi_bar_direction_generated_open_entry_bypasses_legacy_resonance_threshold() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[-0.03, -0.02, -0.01],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=99.0,
                ema50=101.0,
                ema200=103.0,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                close_series=[100.0 + i * 0.12 for i in range(30)],
                macd_hist_series=[-0.01, -0.005, 0.03],
                rsi=50,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is True
    assert result.reason == "multi_bar_direction_generated_pass"
    assert result.resonance_score < result.threshold
    assert result.metadata["legacy_resonance_threshold_bypassed"] is True
    assert result.metadata["direction_score"] == pytest.approx(result.metadata["direction_gate"]["direction_score"])
    assert result.metadata["signal_score"] == pytest.approx(result.metadata["direction_gate"]["direction_score"])
    assert result.metadata["competition_score"] == pytest.approx(result.metadata["direction_gate"]["direction_score"])
    assert result.metadata["legacy_resonance_score"] == pytest.approx(result.resonance_score)
    assert result.metadata["entry_15m_quality_bucket"] == "open"


def test_multi_bar_direction_generated_nontrend_ema_without_1h_macd_waits() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "transition_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "watchlist_intent_enabled": True,
            "watchlist_intent_dry_run": False,
            "watchlist_min_signal_score": 0.30,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[-0.01, -0.02, -0.03],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=99.0,
                ema50=95.0,
                ema200=90.0,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[0.03, 0.02, 0.01],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=99.8,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                close_series=[100.0 + i * 0.12 for i in range(30)],
                macd_hist_series=[-0.02, -0.01, 0.03],
                rsi=50,
            ),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "multi_bar_nontrend_ema_without_1h_macd_watch"
    assert result.metadata["quadrant_4h"] == "Q4"
    assert result.metadata["direction_gate"]["ok"] is True
    assert "ema_1h" in result.factor_scores
    assert "macd_1h" not in result.factor_scores
    assert result.metadata["watchlist_intent"]["candidate_reason"] == "multi_bar_nontrend_ema_without_1h_macd_watch"


def test_multi_bar_direction_generated_respects_breadth_hard_reject() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_breadth_zero_confirm_invalid_min": 2,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[-0.03, -0.02, -0.01],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=99.0,
                ema50=101.0,
                ema200=103.0,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                close_series=[100.0 + i * 0.12 for i in range(30)],
                macd_hist_series=[-0.01, -0.005, 0.03],
                rsi=50,
            ),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 0, "invalid_count": 2}},
    )

    assert result.allowed is False
    assert result.reason == "market_participation_hard_reject"
    assert result.metadata["direction_gate"]["ok"] is True
    assert result.metadata["market_participation"]["blocked_reason"] == "breadth_zero_confirm_invalid_2"


def test_multi_bar_direction_generated_respects_live_flow_alias_hard_reject() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
            "probe_no_15m_breadth_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": True,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[-0.03, -0.02, -0.01],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=99.0,
                ema50=101.0,
                ema200=103.0,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                close_series=[100.0 + i * 0.12 for i in range(30)],
                macd_hist_series=[-0.01, -0.005, 0.03],
                rsi=50,
            ),
        ),
        portfolio={"equity": 100.0},
        market_context={
            "market_breadth": {"confirm_count": 2, "invalid_count": 0},
            "cvd_ratio": -0.0665,
            "oi_delta_ratio": -0.0020,
            "imbalance": -0.2635,
            "liquidity_delta_norm": -0.1919,
        },
    )

    assert result.allowed is False
    assert result.reason == "market_participation_hard_reject"
    assert result.metadata["market_participation"]["blocked_reason"] == "long_flow_all_bearish"


def test_multi_bar_direction_generated_sizes_from_bot_total_assets_portfolio() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "entry_15m_quality_mode": "live",
            "entry_15m_quality_open_min": 0.70,
            "entry_15m_quality_watch_min": 0.50,
            "direction_model": "multi_bar_slope",
            "direction_generates_both": True,
            "quadrant_4h_role": "ema_filter",
            "direction_4h_lookback_bars": 50,
            "direction_1h_lookback_bars": 50,
            "direction_15m_lookback_bars": 30,
            "direction_open_min_abs": 0.30,
        },
        risk={"min_entry_margin_usdt": 1.0, "min_entry_notional_usdt": 12.0},
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(
                ema20=105,
                ema50=100,
                ema200=90,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[-0.03, -0.02, -0.01],
            ),
            tf1h=_tf(
                close=100.0,
                ema20=99.0,
                ema50=101.0,
                ema200=103.0,
                close_series=[100.0 + i * 0.2 for i in range(50)],
                macd_hist_series=[0.01, 0.02, 0.03],
                rsi=50,
            ),
            tf15m=_tf(
                close=100.0,
                open=100.2,
                high=100.25,
                low=99.95,
                ema20=99.7,
                atr=1.0,
                close_series=[100.0 + i * 0.12 for i in range(30)],
                macd_hist_series=[-0.01, -0.005, 0.03],
                rsi=50,
            ),
        ),
        portfolio={"cash": 100.0, "total_assets": 100.0, "positions": {}},
    )

    assert result.allowed is True
    assert result.reason == "multi_bar_direction_generated_pass"
    assert result.target_portion > 0.0
    assert result.metadata["portfolio_equity"] == pytest.approx(100.0)


def test_probe_veto_graded_direction_against_under_hard_threshold_opens_quarter_probe() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "high_score_probe_portion": 0.042,
            "probe_no_15m_veto_enabled": True,
            "probe_direction_breadth_veto_enabled": True,
            "probe_veto_graded_enabled": True,
            "probe_veto_direction_reduced_multiplier": 0.25,
            "probe_veto_hard_reject_btc_against_pct": 0.008,
        }
    )

    result = engine.analyze(
        symbol="VETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[-0.01, -0.02, -0.03]),
            tf1h=_tf(close=100, ema20=101, ema50=105, ema200=110, macd_hist_series=[-0.01, -0.02, -0.03], rsi=50),
            tf15m=_tf(close=100, open=99.8, high=100.25, low=99.95, ema20=100.5, macd_hist_series=[-0.03, -0.02, -0.01], rsi=50),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 1, "invalid_count": 0, "btc_ret_30m": 0.006}},
    )

    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m_reduced_veto"
    assert result.target_portion == pytest.approx(0.0105)
    assert result.metadata["probe_veto_grade"]["portion_multiplier"] == pytest.approx(0.25)


def test_probe_veto_graded_direction_against_hard_threshold_rejects() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "probe_no_15m_veto_enabled": True,
            "probe_direction_breadth_veto_enabled": True,
            "probe_veto_graded_enabled": True,
            "probe_veto_hard_reject_btc_against_pct": 0.008,
        }
    )

    result = engine.analyze(
        symbol="VETUSDT",
        price=100.0,
        timeframes=_timeframes(
            q4h=_tf(ema20=90, ema50=100, ema200=105, macd_hist_series=[-0.01, -0.02, -0.03]),
            tf1h=_tf(close=100, ema20=101, ema50=105, ema200=110, macd_hist_series=[-0.01, -0.02, -0.03], rsi=50),
            tf15m=_tf(close=100, open=99.8, high=100.25, low=99.95, ema20=100.5, macd_hist_series=[-0.03, -0.02, -0.01], rsi=50),
        ),
        portfolio={"equity": 100.0},
        market_context={"market_breadth": {"confirm_count": 1, "invalid_count": 0, "btc_ret_30m": 0.0085}},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["probe_veto_grade"]["action"] == "reject"


def test_probe_veto_graded_no_15m_resonance_rejects_when_15m_and_1h_not_strengthening() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.75,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.75,
            "probe_no_15m_veto_enabled": True,
            "probe_min_15m_resonance_enabled": True,
            "probe_veto_graded_enabled": True,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.03, 0.02, 0.01], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "probe_no_15m_direction_veto"
    assert result.metadata["probe_veto_grade"]["action"] == "reject"
    assert "probe_veto_no_15m_resonance" in result.metadata["probe_no_15m_veto_reasons"]


def test_probe_veto_graded_flow_misaligned_above_hard_threshold_opens_quarter_probe() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.85,
            "high_score_probe_portion": 0.042,
            "probe_no_15m_veto_enabled": True,
            "probe_no_15m_flow_veto_enabled": False,
            "probe_flow_alignment_score_enabled": True,
            "probe_min_flow_alignment": -0.20,
            "probe_veto_graded_enabled": True,
            "probe_veto_direction_reduced_multiplier": 0.25,
            "probe_veto_hard_reject_flow_score": -0.30,
        }
    )

    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
            tf15m=_tf(close=100.0, open=100.2, high=100.25, low=99.95, ema20=99.7, atr=1.0, macd_hist_series=[0.01, 0.02, 0.03], rsi=55),
        ),
        portfolio={"equity": 100.0},
        market_context={"flow": {"cvd": -0.20, "oi_delta": 0.0, "imbalance": -0.08, "liq_norm": 0.0}},
    )

    assert -0.30 < result.metadata["probe_flow_alignment_score"] < -0.20
    assert result.allowed is True
    assert result.reason == "quadrant_resonance_probe_no_15m_reduced_veto"
    assert result.target_portion == pytest.approx(0.0105)
    assert result.metadata["probe_veto_grade"]["portion_multiplier"] == pytest.approx(0.25)


def test_score_equal_to_mid_upper_bound_requires_three_bar_macd_before_high_score_probe() -> None:
    engine = _engine(
        entry={
            "standard_threshold": 0.85,
            "require_15m_entry_pattern": True,
            "high_score_15m_override": True,
            "high_score_15m_override_threshold": 0.90,
            "mid_score_requires_3bar_macd": True,
            "mid_score_upper_bound": 0.90,
        }
    )
    result = engine.analyze(
        symbol="HYPEUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02], rsi=55),
            tf15m=_tf(close=100, open=100.2, high=100.25, low=99.95, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )

    assert result.allowed is False
    assert result.reason == "mid_score_needs_3bar_macd"


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


def test_decision_engine_live_watchlist_records_candidate_without_entry() -> None:
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
                        "high_score_15m_override_threshold": 0.95,
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                        "watchlist_min_signal_score": 0.75,
                        "watchlist_ttl_bars": 4,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )

    decision = engine.decide(
        "JSTUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {
            "timeframes": _timeframes(
                tf15m=_tf(
                    close=100.0,
                    open=100.2,
                    high=100.25,
                    low=99.95,
                    ema20=99.7,
                    atr=1.0,
                    macd_hist_series=[0.01, 0.02, 0.03],
                    rsi=55,
                )
            )
        },
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert decision.operation is Operation.HOLD
    assert decision.reason == "missing_15m_entry_pattern"
    assert decision.metadata["watchlist_intent"]["dry_run"] is False
    assert decision.metadata["watchlist_update"]["result"] == "added"
    assert engine._quadrant_watchlist["JSTUSDT:long"]["side"] == "long"


def test_decision_engine_live_watchlist_sizes_candidate_from_bot_total_assets_portfolio() -> None:
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
                        "high_score_15m_override_threshold": 0.95,
                        "high_score_probe_portion": 0.02,
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                        "watchlist_min_signal_score": 0.75,
                        "watchlist_ttl_bars": 4,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0, "min_entry_margin_usdt": 1.0},
                },
            }
        }
    )

    decision = engine.decide(
        "JSTUSDT",
        {"cash": 100.0, "total_assets": 100.0, "positions": {}},
        100.0,
        {
            "timeframes": _timeframes(
                tf15m=_tf(
                    close=100.0,
                    open=100.2,
                    high=100.25,
                    low=99.95,
                    ema20=99.7,
                    atr=1.0,
                    macd_hist_series=[0.01, 0.02, 0.03],
                    rsi=55,
                )
            )
        },
        use_weight_router=False,
        use_ai_weights=False,
    )

    candidate = engine._quadrant_watchlist["JSTUSDT:long"]
    assert decision.operation is Operation.HOLD
    assert decision.metadata["portfolio_equity"] == pytest.approx(100.0)
    assert candidate["portfolio_equity"] == pytest.approx(100.0)
    assert candidate["base_portion"] >= (12.0 / (100.0 * 3.0)) - 1e-12


def test_decision_engine_watchlist_keeps_long_and_short_candidates_separate() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                        "watchlist_min_signal_score": 0.0,
                        "watchlist_ttl_bars": 4,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )

    engine._apply_quadrant_watchlist_intent(
        symbol="JUPUSDT",
        metadata={"watchlist_intent": {"dry_run": False, "symbol": "JUPUSDT", "side": "long", "score": 0.8, "ttl_bars": 4}},
    )
    engine._apply_quadrant_watchlist_intent(
        symbol="JUPUSDT",
        metadata={"watchlist_intent": {"dry_run": False, "symbol": "JUPUSDT", "side": "short", "score": 0.9, "ttl_bars": 4}},
    )

    assert "JUPUSDT:long" in engine._quadrant_watchlist
    assert "JUPUSDT:short" in engine._quadrant_watchlist
    assert len(engine._quadrant_watchlist) == 2


def test_decision_engine_live_watchlist_marks_standard_entry_promotion() -> None:
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
                        "high_score_15m_override_threshold": 0.95,
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                        "watchlist_min_signal_score": 0.75,
                        "watchlist_ttl_bars": 4,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )

    engine.decide(
        "JSTUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {
            "timeframes": _timeframes(
                tf15m=_tf(
                    close=100.0,
                    open=100.2,
                    high=100.25,
                    low=99.95,
                    ema20=99.7,
                    atr=1.0,
                    macd_hist_series=[0.01, 0.02, 0.03],
                    rsi=55,
                )
            )
        },
        use_weight_router=False,
        use_ai_weights=False,
    )
    decision = engine.decide(
        "JSTUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {"timeframes": _timeframes(tf15m=_tf(close=100.0, open=99.8, high=100.25, low=99.75, ema20=99.7, atr=1.0, macd_hist_series=[-0.01, 0.02], rsi=55))},
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert decision.operation is Operation.BUY
    assert decision.reason == "quadrant_resonance_pass"
    assert decision.metadata["watchlist_review"]["result"] == "promoted_by_standard_entry"
    assert "JSTUSDT:long" not in engine._quadrant_watchlist


def test_decision_engine_live_watchlist_directly_promotes_when_missing_conditions_clear() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "standard_threshold": 1.05,
                        "require_15m_entry_pattern": True,
                        "high_score_15m_override": True,
                        "high_score_15m_override_threshold": 1.10,
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                        "watchlist_direct_open_enabled": True,
                        "watchlist_promoted_portion_mult": 0.75,
                        "watchlist_min_signal_score": 0.75,
                        "watchlist_ttl_bars": 4,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )

    first = engine.decide(
        "JSTUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {
            "timeframes": _timeframes(
                tf15m=_tf(
                    close=100.0,
                    open=100.2,
                    high=100.25,
                    low=99.95,
                    ema20=99.7,
                    atr=1.0,
                    macd_hist_series=[0.01, 0.02, 0.03],
                    rsi=55,
                )
            )
        },
        use_weight_router=False,
        use_ai_weights=False,
    )
    base_portion = engine._quadrant_watchlist["JSTUSDT:long"]["base_portion"]

    promoted = engine.decide(
        "JSTUSDT",
        {"equity": 100.0, "positions": {}},
        100.0,
        {
            "timeframes": _timeframes(
                tf15m=_tf(
                    close=100.0,
                    open=99.8,
                    high=100.3,
                    low=99.75,
                    ema20=99.7,
                    atr=1.0,
                    macd_hist_series=[-0.01, 0.02],
                    rsi=55,
                )
            )
        },
        use_weight_router=False,
        use_ai_weights=False,
    )

    assert first.operation is Operation.HOLD
    assert promoted.operation is Operation.BUY
    assert promoted.reason == "watchlist_promoted"
    assert promoted.target_portion_of_balance == pytest.approx(base_portion * 0.75)
    assert promoted.metadata["watchlist_review"]["result"] == "promoted_direct"
    assert promoted.metadata["allowed_reason"] == "watchlist_direct_open"
    assert "JSTUSDT:long" not in engine._quadrant_watchlist


def test_decision_engine_watchlist_direct_promotion_requires_watch_entry_score() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_direct_open_enabled": True,
                        "watchlist_promoted_portion_mult": 0.75,
                        "entry_15m_quality_watch_min": 0.50,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )
    candidate = {
        "symbol": "JUPUSDT",
        "side": "long",
        "score": 0.8,
        "candidate_reason": "direction_ok_entry_watch",
        "missing_conditions": [],
        "base_portion": 0.10,
    }
    low_signal = type(
        "Signal",
        (),
        {
            "direction": "long",
            "reason": "direction_ok_entry_too_low",
            "metadata": {
                "entry_15m_quality_score": 0.45,
                "entry_15m_quality_bucket": "hold",
                "entry_15m_detail": {"ok": False},
            },
            "target_portion": 0.10,
            "leverage": 3,
            "atr_stop_distance": 1.0,
        },
    )()

    review = engine._review_quadrant_watchlist_direct(
        candidate=candidate,
        signal=low_signal,
        reviewed_at="2026-06-01T00:00:00+00:00",
    )

    assert review is None


def test_decision_engine_watchlist_direct_promotes_watch_score_even_with_legacy_missing_conditions() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_direct_open_enabled": True,
                        "watchlist_promoted_portion_mult": 0.75,
                        "entry_15m_quality_watch_min": 0.50,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )
    candidate = {
        "symbol": "JUPUSDT",
        "side": "long",
        "score": 0.8,
        "candidate_reason": "direction_ok_entry_watch",
        "missing_conditions": ["hist_cross", "direction_candle", "pin_bar"],
        "base_portion": 0.10,
    }
    signal = type(
        "Signal",
        (),
        {
            "direction": "long",
            "reason": "direction_ok_entry_watch",
            "metadata": {
                "entry_15m_quality_score": 0.55,
                "entry_15m_quality_bucket": "watch",
                "entry_15m_detail": {"ok": False},
            },
            "target_portion": 0.0,
            "leverage": 3,
            "atr_stop_distance": 1.0,
        },
    )()

    review = engine._review_quadrant_watchlist_direct(
        candidate=candidate,
        signal=signal,
        reviewed_at="2026-06-01T00:00:00+00:00",
    )

    assert review["result"] == "promoted_direct"
    assert review["quality_score"] == pytest.approx(0.55)
    assert review["base_portion"] == pytest.approx(0.10)


def test_decision_engine_watchlist_direct_does_not_promote_nontrend_without_1h_macd() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_direct_open_enabled": True,
                        "watchlist_promoted_portion_mult": 0.75,
                        "entry_15m_quality_watch_min": 0.50,
                    },
                    "risk": {"min_entry_notional_usdt": 12.0},
                },
            }
        }
    )
    candidate = {
        "symbol": "JUPUSDT",
        "side": "long",
        "score": 0.8,
        "candidate_reason": "multi_bar_nontrend_ema_without_1h_macd_watch",
        "base_portion": 0.10,
    }
    signal = type(
        "Signal",
        (),
        {
            "direction": "long",
            "reason": "multi_bar_nontrend_ema_without_1h_macd_watch",
            "metadata": {
                "entry_15m_quality_score": 0.55,
                "entry_15m_quality_bucket": "watch",
                "factor_scores": {"quadrant_4h": 0.20, "ema_1h": 0.20, "entry_15m": 0.10, "rsi_15m": 0.05},
            },
            "target_portion": 0.0,
            "leverage": 3,
            "atr_stop_distance": 1.0,
        },
    )()

    review = engine._review_quadrant_watchlist_direct(
        candidate=candidate,
        signal=signal,
        reviewed_at="2026-06-01T00:00:00+00:00",
    )

    assert review is None


def test_decision_engine_watchlist_candidate_base_portion_uses_min_notional_when_hold_metadata_has_no_target() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "min_leverage": 1,
                "default_leverage": 3,
                "max_leverage": 9,
                "quadrant_resonance": {
                    "entry": {
                        "high_score_probe_portion": 0.02,
                        "watchlist_intent_enabled": True,
                        "watchlist_intent_dry_run": False,
                    },
                    "risk": {
                        "min_entry_notional_usdt": 12.0,
                        "min_entry_margin_usdt": 1.0,
                        "max_leverage": 3,
                    },
                },
            }
        }
    )

    update = engine._apply_quadrant_watchlist_intent(
        symbol="JUPUSDT",
        metadata={
            "portfolio_equity": 100.0,
            "leverage": 3,
            "watchlist_intent": {
                "dry_run": False,
                "symbol": "JUPUSDT",
                "side": "long",
                "score": 0.8,
                "candidate_reason": "direction_ok_entry_watch",
                "ttl_bars": 4,
            },
        },
    )

    candidate = engine._quadrant_watchlist["JUPUSDT:long"]
    assert update["result"] == "added"
    assert candidate["base_portion"] > 0.0
    assert candidate["base_portion"] >= (12.0 / (100.0 * 3.0)) - 1e-12


def test_decision_engine_watchlist_base_portion_falls_back_when_equity_missing() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "default_leverage": 3,
                "quadrant_resonance": {
                    "entry": {
                        "high_score_probe_portion": 0.02,
                        "watchlist_fallback_min_portion": 0.033,
                    },
                    "risk": {
                        "min_entry_notional_usdt": 12.0,
                        "min_entry_margin_usdt": 1.0,
                        "max_leverage": 3,
                    },
                },
            }
        }
    )

    portion = engine._quadrant_watchlist_base_portion(metadata={}, leverage=3)

    assert portion == pytest.approx(0.033)


def test_decision_engine_watchlist_promoted_signal_never_returns_zero_target_portion() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "default_leverage": 3,
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_fallback_min_portion": 0.033,
                        "watchlist_promoted_portion_mult": 0.75,
                    }
                },
            }
        }
    )
    signal = type(
        "Signal",
        (),
        {
            "direction": "long",
            "target_portion": 0.0,
            "leverage": 3,
            "atr_stop_distance": 0.0,
            "quadrant": Quadrant.Q1,
            "resonance_score": 0.0,
            "threshold": 0.0,
            "factor_scores": {},
            "take_profit_levels": [],
        },
    )()

    promoted = engine._quadrant_watchlist_promoted_signal(
        symbol="HYPEUSDT",
        price=10.0,
        signal=signal,
        review={"result": "promoted_direct", "side": "long", "base_portion": 0.0, "portion_multiplier": 0.75},
        metadata={},
    )

    assert promoted is not None
    assert promoted.target_portion > 0.0
    assert promoted.metadata["watchlist_sizing_fallback_applied"] is True


def test_decision_engine_watchlist_review_reports_age_and_ttl() -> None:
    engine = FundFlowDecisionEngine(
        {
            "fund_flow": {
                "strategy_mode": "quadrant_resonance",
                "quadrant_resonance": {
                    "entry": {
                        "watchlist_direct_open_enabled": True,
                        "entry_15m_quality_watch_min": 0.50,
                    }
                },
            }
        }
    )
    engine._quadrant_watchlist["JUPUSDT:long"] = {
        "symbol": "JUPUSDT",
        "side": "long",
        "score": 0.8,
        "candidate_reason": "direction_ok_entry_watch",
        "ttl_bars": 2,
        "ttl_remaining_bars": 2,
        "entry_15m_quality_score": 0.35,
    }
    signal = type(
        "Signal",
        (),
        {
            "allowed": False,
            "direction": "long",
            "reason": "direction_ok_entry_too_low",
            "metadata": {"entry_15m_quality_score": 0.35, "entry_15m_quality_bucket": "hold"},
        },
    )()

    review = engine._review_quadrant_watchlist(symbol="JUPUSDT", signal=signal)

    assert review["result"] == "pending"
    assert review["symbol"] == "JUPUSDT"
    assert review["side"] == "long"
    assert review["ttl_bars"] == 2
    assert review["ttl_remaining_bars"] == 1
    assert review["entry_score_now"] == pytest.approx(0.35)


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
