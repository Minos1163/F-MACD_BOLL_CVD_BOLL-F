from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, Optional


class Quadrant(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    DEFENSE = "DEFENSE"


@dataclass
class QuadrantResonanceConfig:
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    atr_period: int = 14
    standard_threshold: float = 0.80
    transition_threshold: float = 0.85
    quadrant_standard_score: float = 0.50
    quadrant_transition_score: float = 0.20
    score_1h_ema: float = 0.20
    score_1h_macd: float = 0.15
    score_15m_entry: float = 0.10
    score_15m_rsi: float = 0.05
    rsi_divergence_bonus: float = 0.10
    long_rsi_min: float = 40.0
    long_rsi_max: float = 68.0
    q2_long_rsi_min: float = 35.0
    short_rsi_min: float = 40.0
    short_rsi_max: float = 62.0
    q4_short_rsi_max: float = 65.0
    long_1h_rsi_hard_max: float = 75.0
    short_1h_rsi_hard_min: float = 25.0
    ema20_distance_atr_mult: float = 2.5
    require_15m_entry_pattern: bool = False
    high_score_15m_override: bool = False
    high_score_15m_override_threshold: float = 0.92
    high_score_probe_portion: float = 0.042
    probe_no_15m_veto_enabled: bool = False
    probe_no_15m_breadth_veto_enabled: bool = True
    probe_no_15m_flow_veto_enabled: bool = True
    probe_no_15m_rsi_macd_veto_enabled: bool = True
    probe_min_15m_resonance_enabled: bool = False
    probe_require_macd_15m_or_1h_near_ema: bool = True
    probe_breadth_zero_confirm_invalid_min: int = 2
    probe_direction_breadth_veto_enabled: bool = False
    short_probe_btc_30m_veto_pct: float = 0.005
    short_probe_btc_60m_veto_pct: float = 0.008
    short_probe_alt_med_veto_pct: float = 0.006
    long_probe_btc_30m_veto_pct: float = 0.005
    long_probe_btc_60m_veto_pct: float = 0.008
    long_probe_alt_med_veto_pct: float = 0.006
    probe_resonance_score_enabled: bool = False
    probe_resonance_min_threshold: float = 0.55
    probe_resonance_min_threshold_short: float = 0.60
    probe_flow_alignment_score_enabled: bool = False
    probe_min_flow_alignment: float = -0.20
    probe_min_flow_alignment_short: float = -0.15
    probe_min_entry_score_enabled: bool = False
    probe_min_entry_score: float = 0.45
    entry_15m_quality_mode: str = "audit"
    entry_15m_quality_open_min: float = 0.75
    entry_15m_quality_watch_min: float = 0.55
    direction_model: str = "legacy"
    direction_4h_lookback_bars: int = 50
    direction_1h_lookback_bars: int = 50
    direction_15m_lookback_bars: int = 30
    direction_open_min_abs: float = 0.30
    direction_strong_conflict_min_abs: float = 0.30
    direction_transition_mode_enabled: bool = False
    direction_transition_1h_min_abs: float = 0.05
    direction_generates_both: bool = False
    quadrant_4h_role: str = "legacy_direction"
    ema_conflict_entry_penalty: float = 0.10
    watchlist_intent_enabled: bool = False
    watchlist_intent_dry_run: bool = True
    watchlist_min_signal_score: float = 0.75
    watchlist_ttl_bars: int = 4
    watchlist_probe_veto_ttl_bars: int = 2
    watchlist_include_probe_veto: bool = True
    watchlist_direct_open_enabled: bool = False
    watchlist_promoted_portion_mult: float = 0.75
    quadrant_4h_three_state_enabled: bool = False
    quadrant_4h_three_state_act_on_recovering: bool = False
    recovering_state_portion_multiplier: float = 0.50
    recovering_state_score_threshold: float = 0.80
    probe_veto_graded_enabled: bool = False
    probe_veto_breadth_reduced_multiplier: float = 0.50
    probe_veto_direction_reduced_multiplier: float = 0.25
    probe_veto_hard_reject_btc_against_pct: float = 0.008
    probe_veto_hard_reject_flow_score: float = -0.30
    mid_score_requires_3bar_macd: bool = False
    mid_score_upper_bound: float = 0.90
    extreme_4h_rsi_penalty: float = 0.0
    long_4h_rsi_penalty_above: float = 70.0
    short_4h_rsi_penalty_below: float = 30.0
    hard_stop_atr_mult: float = 1.2
    stop_trigger: str = "intrabar"
    tp1_atr_mult: float = 1.5
    tp1_reduce_pct: float = 0.30
    ema20_trailing_enabled: bool = True
    momentum_reduce_pct_first: float = 0.50
    momentum_reduce_pct_second: float = 0.50
    trend_reduce_pct: float = 0.50
    risk_per_trade_pct: float = 0.01
    min_entry_notional_usdt: float = 12.0
    min_entry_margin_usdt: float = 1.0
    max_leverage: int = 3
    max_total_exposure_pct: float = 0.75
    max_active_symbols: int = 8
    replacement_min_new_score: float = 0.85
    replacement_score_gap: float = 0.15
    quality_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "pnl": 0.30,
            "resonance_alignment": 0.25,
            "macd_strength": 0.15,
            "time_decay": 0.10,
            "ema20_distance": 0.20,
        }
    )

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "QuadrantResonanceConfig":
        data = raw if isinstance(raw, dict) else {}
        indicators = data.get("indicators", {}) if isinstance(data.get("indicators"), dict) else {}
        entry = data.get("entry", {}) if isinstance(data.get("entry"), dict) else {}
        risk = data.get("risk", {}) if isinstance(data.get("risk"), dict) else {}
        capacity = data.get("capacity", {}) if isinstance(data.get("capacity"), dict) else {}
        exit_cfg = data.get("exit", {}) if isinstance(data.get("exit"), dict) else {}

        cfg = cls(
            ema_fast=int(_float(indicators.get("ema_fast"), 20)),
            ema_mid=int(_float(indicators.get("ema_mid"), 50)),
            ema_slow=int(_float(indicators.get("ema_slow"), 200)),
            macd_fast=int(_float(indicators.get("macd_fast"), 12)),
            macd_slow=int(_float(indicators.get("macd_slow"), 26)),
            macd_signal=int(_float(indicators.get("macd_signal"), 9)),
            rsi_period=int(_float(indicators.get("rsi_period"), 14)),
            atr_period=int(_float(indicators.get("atr_period"), 14)),
            standard_threshold=_float(entry.get("standard_threshold"), 0.80),
            transition_threshold=_float(entry.get("transition_threshold"), 0.85),
            long_rsi_min=_float(entry.get("long_rsi_min"), 40.0),
            long_rsi_max=_float(entry.get("long_rsi_max"), 68.0),
            q2_long_rsi_min=_float(entry.get("q2_long_rsi_min"), 35.0),
            short_rsi_min=_float(entry.get("short_rsi_min"), 40.0),
            short_rsi_max=_float(entry.get("short_rsi_max"), 62.0),
            q4_short_rsi_max=_float(entry.get("q4_short_rsi_max"), 65.0),
            long_1h_rsi_hard_max=_float(entry.get("long_1h_rsi_hard_max"), 75.0),
            short_1h_rsi_hard_min=_float(entry.get("short_1h_rsi_hard_min"), 25.0),
            ema20_distance_atr_mult=_float(entry.get("ema20_distance_atr_mult"), 2.5),
            require_15m_entry_pattern=bool(entry.get("require_15m_entry_pattern", False)),
            high_score_15m_override=bool(entry.get("high_score_15m_override", False)),
            high_score_15m_override_threshold=_float(entry.get("high_score_15m_override_threshold"), 0.92),
            high_score_probe_portion=max(0.0, _float(entry.get("high_score_probe_portion"), 0.042)),
            probe_no_15m_veto_enabled=bool(entry.get("probe_no_15m_veto_enabled", False)),
            probe_no_15m_breadth_veto_enabled=bool(entry.get("probe_no_15m_breadth_veto_enabled", True)),
            probe_no_15m_flow_veto_enabled=bool(entry.get("probe_no_15m_flow_veto_enabled", True)),
            probe_no_15m_rsi_macd_veto_enabled=bool(entry.get("probe_no_15m_rsi_macd_veto_enabled", True)),
            probe_min_15m_resonance_enabled=bool(entry.get("probe_min_15m_resonance_enabled", False)),
            probe_require_macd_15m_or_1h_near_ema=bool(entry.get("probe_require_macd_15m_or_1h_near_ema", True)),
            probe_breadth_zero_confirm_invalid_min=int(_float(entry.get("probe_breadth_zero_confirm_invalid_min"), 2)),
            probe_direction_breadth_veto_enabled=bool(entry.get("probe_direction_breadth_veto_enabled", False)),
            short_probe_btc_30m_veto_pct=_float(entry.get("short_probe_btc_30m_veto_pct"), 0.005),
            short_probe_btc_60m_veto_pct=_float(entry.get("short_probe_btc_60m_veto_pct"), 0.008),
            short_probe_alt_med_veto_pct=_float(entry.get("short_probe_alt_med_veto_pct"), 0.006),
            long_probe_btc_30m_veto_pct=_float(entry.get("long_probe_btc_30m_veto_pct"), 0.005),
            long_probe_btc_60m_veto_pct=_float(entry.get("long_probe_btc_60m_veto_pct"), 0.008),
            long_probe_alt_med_veto_pct=_float(entry.get("long_probe_alt_med_veto_pct"), 0.006),
            probe_resonance_score_enabled=bool(entry.get("probe_resonance_score_act_enabled", entry.get("probe_resonance_score_enabled", False))),
            probe_resonance_min_threshold=_float(entry.get("probe_resonance_min_threshold"), 0.55),
            probe_resonance_min_threshold_short=_float(entry.get("probe_resonance_min_threshold_short"), 0.60),
            probe_flow_alignment_score_enabled=bool(entry.get("probe_flow_alignment_act_enabled", entry.get("probe_flow_alignment_score_enabled", False))),
            probe_min_flow_alignment=_float(entry.get("probe_min_flow_alignment"), -0.20),
            probe_min_flow_alignment_short=_float(entry.get("probe_min_flow_alignment_short"), -0.15),
            probe_min_entry_score_enabled=bool(entry.get("probe_min_entry_score_enabled", False)),
            probe_min_entry_score=_float(entry.get("probe_min_entry_score"), 0.45),
            entry_15m_quality_mode=str(entry.get("entry_15m_quality_mode", "audit") or "audit"),
            entry_15m_quality_open_min=_float(entry.get("entry_15m_quality_open_min"), 0.75),
            entry_15m_quality_watch_min=_float(entry.get("entry_15m_quality_watch_min"), 0.55),
            direction_model=str(entry.get("direction_model", "legacy") or "legacy"),
            direction_4h_lookback_bars=int(_float(entry.get("direction_4h_lookback_bars"), 50)),
            direction_1h_lookback_bars=int(_float(entry.get("direction_1h_lookback_bars"), 50)),
            direction_15m_lookback_bars=int(_float(entry.get("direction_15m_lookback_bars"), 30)),
            direction_open_min_abs=_float(entry.get("direction_open_min_abs"), 0.30),
            direction_strong_conflict_min_abs=_float(entry.get("direction_strong_conflict_min_abs"), 0.30),
            direction_transition_mode_enabled=bool(entry.get("direction_transition_mode_enabled", False)),
            direction_transition_1h_min_abs=_float(entry.get("direction_transition_1h_min_abs"), 0.05),
            direction_generates_both=bool(entry.get("direction_generates_both", False)),
            quadrant_4h_role=str(entry.get("quadrant_4h_role", "legacy_direction") or "legacy_direction"),
            ema_conflict_entry_penalty=_float(entry.get("ema_conflict_entry_penalty"), 0.10),
            watchlist_intent_enabled=bool(entry.get("watchlist_intent_enabled", False)),
            watchlist_intent_dry_run=bool(entry.get("watchlist_intent_dry_run", True)),
            watchlist_min_signal_score=_float(entry.get("watchlist_min_signal_score"), 0.75),
            watchlist_ttl_bars=int(_float(entry.get("watchlist_ttl_bars"), 4)),
            watchlist_probe_veto_ttl_bars=int(_float(entry.get("watchlist_ttl_reversible_veto_bars", entry.get("watchlist_probe_veto_ttl_bars")), 2)),
            watchlist_include_probe_veto=bool(entry.get("watchlist_include_probe_veto", True)),
            watchlist_direct_open_enabled=bool(entry.get("watchlist_direct_open_enabled", False)),
            watchlist_promoted_portion_mult=_float(entry.get("watchlist_promoted_portion_mult"), 0.75),
            quadrant_4h_three_state_enabled=bool(entry.get("quadrant_4h_three_state_enabled", False)),
            quadrant_4h_three_state_act_on_recovering=bool(entry.get("quadrant_4h_three_state_act_on_recovering", False)),
            recovering_state_portion_multiplier=_float(entry.get("recovering_state_portion_multiplier"), 0.50),
            recovering_state_score_threshold=_float(entry.get("recovering_state_score_threshold"), 0.80),
            probe_veto_graded_enabled=bool(entry.get("probe_veto_graded_enabled", False)),
            probe_veto_breadth_reduced_multiplier=_float(entry.get("probe_veto_breadth_reduced_multiplier"), 0.50),
            probe_veto_direction_reduced_multiplier=_float(entry.get("probe_veto_direction_reduced_multiplier"), 0.25),
            probe_veto_hard_reject_btc_against_pct=_float(entry.get("probe_veto_hard_reject_btc_against_pct"), 0.008),
            probe_veto_hard_reject_flow_score=_float(entry.get("probe_veto_hard_reject_flow_score"), -0.30),
            mid_score_requires_3bar_macd=bool(entry.get("mid_score_requires_3bar_macd", False)),
            mid_score_upper_bound=_float(entry.get("mid_score_upper_bound"), 0.90),
            extreme_4h_rsi_penalty=_float(entry.get("extreme_4h_rsi_penalty"), 0.0),
            long_4h_rsi_penalty_above=_float(entry.get("long_4h_rsi_penalty_above"), 70.0),
            short_4h_rsi_penalty_below=_float(entry.get("short_4h_rsi_penalty_below"), 30.0),
            hard_stop_atr_mult=_float(exit_cfg.get("hard_stop_atr_mult"), 1.2),
            stop_trigger=str(exit_cfg.get("stop_trigger", "intrabar") or "intrabar"),
            tp1_atr_mult=_float(exit_cfg.get("tp1_atr_mult"), 1.5),
            tp1_reduce_pct=_float(exit_cfg.get("tp1_reduce_pct"), 0.30),
            ema20_trailing_enabled=bool(exit_cfg.get("ema20_trailing_enabled", True)),
            momentum_reduce_pct_first=_float(exit_cfg.get("momentum_reduce_pct_first"), 0.50),
            momentum_reduce_pct_second=_float(exit_cfg.get("momentum_reduce_pct_second"), 0.50),
            trend_reduce_pct=_float(exit_cfg.get("trend_reduce_pct"), 0.50),
            risk_per_trade_pct=_float(risk.get("risk_per_trade_pct"), 0.01),
            min_entry_notional_usdt=_float(risk.get("min_entry_notional_usdt"), 12.0),
            min_entry_margin_usdt=_float(risk.get("min_entry_margin_usdt"), 1.0),
            max_leverage=int(_float(risk.get("max_leverage"), 3)),
            max_total_exposure_pct=_float(risk.get("max_total_exposure_pct"), 0.75),
            max_active_symbols=int(_float(capacity.get("max_active_symbols"), 8)),
            replacement_min_new_score=_float(capacity.get("replacement_min_new_score"), 0.85),
            replacement_score_gap=_float(capacity.get("replacement_score_gap"), 0.15),
        )
        weights = capacity.get("quality_weights")
        if isinstance(weights, dict):
            cfg.quality_weights.update({str(k): _float(v, cfg.quality_weights.get(str(k), 0.0)) for k, v in weights.items()})
        return cfg


@dataclass
class QuadrantSignal:
    allowed: bool
    symbol: str
    direction: str = ""
    quadrant: Quadrant = Quadrant.DEFENSE
    resonance_score: float = 0.0
    threshold: float = 0.0
    factor_scores: Dict[str, float] = field(default_factory=dict)
    entry_price_ref: float = 0.0
    atr_stop_distance: float = 0.0
    target_portion: float = 0.0
    leverage: int = 1
    stop_loss_price: Optional[float] = None
    take_profit_levels: list[dict] = field(default_factory=list)
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def _float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


class QuadrantResonanceEngine:
    def __init__(self, config: Optional[QuadrantResonanceConfig] = None) -> None:
        self.config = config or QuadrantResonanceConfig()

    def detect_quadrant(self, tf_4h: Dict[str, Any]) -> Quadrant:
        ema_state = self._ema_state(tf_4h)
        hist = self._series(tf_4h, "macd_hist_series", "macd_hist_array", "macd_hist")
        pos_strength = self._hist_strengthening(hist, "long", bars=2)
        neg_strength = self._hist_strengthening(hist, "short", bars=2)
        if ema_state == 1 and pos_strength:
            return Quadrant.Q1
        if ema_state == -1 and pos_strength:
            return Quadrant.Q2
        if ema_state == -1 and neg_strength:
            return Quadrant.Q3
        if ema_state == 1 and neg_strength:
            return Quadrant.Q4
        return Quadrant.DEFENSE

    def analyze(
        self,
        *,
        symbol: str,
        price: float,
        timeframes: Dict[str, Dict[str, Any]],
        portfolio: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> QuadrantSignal:
        portfolio = portfolio or {}
        tf15 = timeframes.get("15m", {}) if isinstance(timeframes, dict) else {}
        tf1h = timeframes.get("1h", {}) if isinstance(timeframes, dict) else {}
        tf4h = timeframes.get("4h", {}) if isinstance(timeframes, dict) else {}
        if not tf15 or not tf1h or not tf4h:
            return self._blocked(symbol, "missing_timeframes")
        if (
            str(self.config.direction_model or "").strip().lower() == "multi_bar_slope"
            and bool(self.config.direction_generates_both)
        ):
            return self._analyze_multi_bar_direction_generated(
                symbol=symbol,
                price=price,
                tf15=tf15,
                tf1h=tf1h,
                tf4h=tf4h,
                portfolio=portfolio,
                market_context=market_context,
            )

        quadrant = self.detect_quadrant(tf4h)
        if quadrant is Quadrant.DEFENSE:
            debug = self._quadrant_debug(tf4h, quadrant)
            state_debug = self._quadrant_state_debug(tf4h)
            debug.update(state_debug)
            if bool(self.config.quadrant_4h_three_state_act_on_recovering) and state_debug.get("quadrant_state") == "recovering":
                return self._recovering_state_signal(
                    symbol=symbol,
                    price=price,
                    tf15=tf15,
                    tf1h=tf1h,
                    portfolio=portfolio,
                    state_debug=state_debug,
                    metadata_extra=debug,
                )
            return self._blocked(symbol, "quadrant_defense_no_entry", quadrant=quadrant, metadata_extra=debug)

        direction = "long" if quadrant in (Quadrant.Q1, Quadrant.Q2) else "short"
        hard_rsi_reason = self._hard_rsi_reason(direction, tf1h)
        if hard_rsi_reason:
            return self._blocked(symbol, hard_rsi_reason, quadrant=quadrant, direction=direction)
        if self._too_far_from_ema20(direction, price, tf1h):
            return self._blocked(symbol, "ema20_distance_chase_block", quadrant=quadrant, direction=direction)

        direction_gate = self._multi_bar_direction_gate(direction, tf4h, tf1h, tf15)
        if not bool(direction_gate.get("ok", True)):
            return self._blocked(
                symbol,
                str(direction_gate.get("reason") or "multi_bar_direction_no_entry"),
                quadrant=quadrant,
                direction=direction,
                metadata_extra={"direction_gate": direction_gate},
            )

        factor_scores = self._score_factors(direction, quadrant, tf15, tf1h)
        divergence = self._rsi_divergence_bonus(direction, tf15, tf1h)
        if divergence > 0:
            factor_scores["rsi_divergence"] = divergence
        score = sum(factor_scores.values())
        penalty = self._extreme_4h_rsi_penalty(direction, tf4h)
        if penalty > 0:
            score = max(0.0, score - penalty)
        threshold = self.config.standard_threshold if quadrant in (Quadrant.Q1, Quadrant.Q3) else self.config.transition_threshold
        metadata_extra: Dict[str, Any] = {}
        if penalty > 0:
            metadata_extra["extreme_4h_rsi_penalty"] = penalty
        if direction_gate:
            metadata_extra["direction_gate"] = direction_gate
        if self._requires_mid_score_macd_confirmation(score, threshold, direction, tf1h):
            metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
            metadata.update(metadata_extra)
            return QuadrantSignal(
                allowed=False,
                symbol=symbol,
                direction=direction,
                quadrant=quadrant,
                resonance_score=score,
                threshold=threshold,
                factor_scores=factor_scores,
                entry_price_ref=price,
                atr_stop_distance=self._atr_stop_distance(tf15),
                reason="mid_score_needs_3bar_macd",
                metadata=metadata,
            )
        if self.config.require_15m_entry_pattern and "entry_15m" not in factor_scores:
            metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
            metadata.update(metadata_extra)
            if self._allow_high_score_missing_15m_probe(score, threshold):
                entry_quality_score = _float(metadata.get("entry_15m_quality_score"), 0.0)
                probe_resonance_score = self._compute_probe_resonance_score(direction, quadrant, tf15, tf1h)
                flow_alignment_score = self._flow_alignment_score(direction, market_context)
                metadata["probe_resonance_score"] = probe_resonance_score
                metadata["probe_flow_alignment_score"] = flow_alignment_score
                veto_reasons = self._probe_no_15m_veto_reasons(
                    direction,
                    quadrant,
                    tf15,
                    tf1h,
                    market_context,
                    probe_resonance_score=probe_resonance_score,
                    flow_alignment_score=flow_alignment_score,
                    entry_quality_score=entry_quality_score,
                )
                metadata["probe_no_15m_veto_reasons"] = veto_reasons
                if veto_reasons:
                    grade = self._grade_probe_veto(veto_reasons, direction, tf15, tf1h, market_context, flow_alignment_score)
                    metadata["probe_veto_grade"] = grade
                    if str(grade.get("action") or "") == "open_reduced":
                        atr_stop_distance = self._atr_stop_distance(tf15)
                        leverage = max(1, min(3, int(self.config.max_leverage)))
                        base_portion = self._probe_position_portion(portfolio)
                        multiplier = max(0.0, min(1.0, _float(grade.get("portion_multiplier"), 0.0)))
                        target_portion = base_portion * multiplier
                        stop_loss = price - atr_stop_distance if direction == "long" else price + atr_stop_distance
                        metadata.update(
                            {
                                "allowed_reason": "high_score_15m_override_graded_veto",
                                "blocked_reason": "probe_no_15m_direction_veto",
                                "signal_quality": "degraded_no_15m_reduced_veto",
                                "override_reason": "high_score_15m_override_graded_veto",
                                "portfolio_equity": _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0),
                                "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
                                "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
                                "leverage_cap": leverage,
                                "leverage": leverage,
                                "base_target_portion": base_portion,
                                "target_portion": target_portion,
                                "high_score_15m_override_threshold": self.config.high_score_15m_override_threshold,
                            }
                        )
                        return QuadrantSignal(
                            allowed=True,
                            symbol=symbol,
                            direction=direction,
                            quadrant=quadrant,
                            resonance_score=score,
                            threshold=threshold,
                            factor_scores=factor_scores,
                            entry_price_ref=price,
                            atr_stop_distance=atr_stop_distance,
                            target_portion=target_portion,
                            leverage=leverage,
                            stop_loss_price=stop_loss,
                            take_profit_levels=self._take_profit_levels(price, atr_stop_distance, direction),
                            reason="quadrant_resonance_probe_no_15m_reduced_veto",
                            metadata=metadata,
                        )
                    intent = self._watchlist_intent(
                        symbol=symbol,
                        direction=direction,
                        score=score,
                        reason="probe_no_15m_direction_veto",
                        metadata=metadata,
                        veto_reasons=veto_reasons,
                    )
                    if intent:
                        metadata["watchlist_intent"] = intent
                    metadata.update(
                        {
                            "blocked_reason": "probe_no_15m_direction_veto",
                            "override_reason": "high_score_15m_override_vetoed",
                        }
                    )
                    return QuadrantSignal(
                        allowed=False,
                        symbol=symbol,
                        direction=direction,
                        quadrant=quadrant,
                        resonance_score=score,
                        threshold=threshold,
                        factor_scores=factor_scores,
                        entry_price_ref=price,
                        atr_stop_distance=self._atr_stop_distance(tf15),
                        reason="probe_no_15m_direction_veto",
                        metadata=metadata,
                    )
                atr_stop_distance = self._atr_stop_distance(tf15)
                leverage = max(1, min(3, int(self.config.max_leverage)))
                target_portion = self._probe_position_portion(portfolio)
                stop_loss = price - atr_stop_distance if direction == "long" else price + atr_stop_distance
                metadata.update(
                    {
                        "allowed_reason": "high_score_15m_override",
                        "blocked_reason": "missing_15m_entry_pattern",
                        "signal_quality": "degraded_no_15m",
                        "override_reason": "high_score_15m_override",
                        "portfolio_equity": _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0),
                        "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
                        "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
                        "leverage_cap": leverage,
                        "leverage": leverage,
                        "target_portion": target_portion,
                        "high_score_15m_override_threshold": self.config.high_score_15m_override_threshold,
                        "probe_no_15m_veto_reasons": [],
                    }
                )
                return QuadrantSignal(
                    allowed=True,
                    symbol=symbol,
                    direction=direction,
                    quadrant=quadrant,
                    resonance_score=score,
                    threshold=threshold,
                    factor_scores=factor_scores,
                    entry_price_ref=price,
                    atr_stop_distance=atr_stop_distance,
                    target_portion=target_portion,
                    leverage=leverage,
                    stop_loss_price=stop_loss,
                    take_profit_levels=self._take_profit_levels(price, atr_stop_distance, direction),
                    reason="quadrant_resonance_probe_no_15m",
                    metadata=metadata,
                )
            intent = self._watchlist_intent(
                symbol=symbol,
                direction=direction,
                score=score,
                reason="missing_15m_entry_pattern",
                metadata=metadata,
            )
            if intent:
                metadata["watchlist_intent"] = intent
            return QuadrantSignal(
                allowed=False,
                symbol=symbol,
                direction=direction,
                quadrant=quadrant,
                resonance_score=score,
                threshold=threshold,
                factor_scores=factor_scores,
                entry_price_ref=price,
                atr_stop_distance=self._atr_stop_distance(tf15),
                reason="missing_15m_entry_pattern",
                metadata=metadata,
            )
        if score + 1e-12 < threshold:
            metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
            metadata.update(metadata_extra)
            return QuadrantSignal(
                allowed=False,
                symbol=symbol,
                direction=direction,
                quadrant=quadrant,
                resonance_score=score,
                threshold=threshold,
                factor_scores=factor_scores,
                entry_price_ref=price,
                atr_stop_distance=self._atr_stop_distance(tf15),
                reason="resonance_score_below_threshold",
                metadata=metadata,
            )

        atr_stop_distance = self._atr_stop_distance(tf15)
        leverage = max(1, min(3, int(self.config.max_leverage)))
        target_portion = self._position_portion(price, atr_stop_distance, portfolio)
        stop_loss = price - atr_stop_distance if direction == "long" else price + atr_stop_distance
        metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
        metadata.update(metadata_extra)
        metadata.update(
            {
                "allowed_reason": "quadrant_resonance_pass",
                "portfolio_equity": _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0),
                "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
                "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
                "leverage_cap": leverage,
                "leverage": leverage,
                "target_portion": target_portion,
            }
        )
        return QuadrantSignal(
            allowed=True,
            symbol=symbol,
            direction=direction,
            quadrant=quadrant,
            resonance_score=score,
            threshold=threshold,
            factor_scores=factor_scores,
            entry_price_ref=price,
            atr_stop_distance=atr_stop_distance,
            target_portion=target_portion,
            leverage=leverage,
            stop_loss_price=stop_loss,
            take_profit_levels=self._take_profit_levels(price, atr_stop_distance, direction),
            reason="quadrant_resonance_pass",
            metadata=metadata,
        )

    def _analyze_multi_bar_direction_generated(
        self,
        *,
        symbol: str,
        price: float,
        tf15: Dict[str, Any],
        tf1h: Dict[str, Any],
        tf4h: Dict[str, Any],
        portfolio: Dict[str, Any],
        market_context: Optional[Dict[str, Any]],
    ) -> QuadrantSignal:
        quadrant = self.detect_quadrant(tf4h)
        direction_gate = self._select_multi_bar_direction(tf4h, tf1h, tf15)
        if not bool(direction_gate.get("ok", False)):
            return self._blocked(
                symbol,
                str(direction_gate.get("reason") or "multi_bar_no_direction"),
                quadrant=quadrant,
                metadata_extra={
                    "direction_gate": direction_gate,
                    "quadrant_debug": self._quadrant_debug(tf4h, quadrant).get("quadrant_debug"),
                },
            )

        direction = str(direction_gate.get("direction") or direction_gate.get("selected_direction") or "").lower()
        if direction not in {"long", "short"}:
            return self._blocked(symbol, "multi_bar_no_direction", quadrant=quadrant, metadata_extra={"direction_gate": direction_gate})

        ema_state = self._ema_state(tf4h)
        ema_conflict = not self._ema_consistent_with_direction(ema_state, direction)
        quadrant_filter = {
            "role": str(self.config.quadrant_4h_role or "ema_filter"),
            "quadrant_4h": quadrant.value,
            "ema_state_4h": ema_state,
            "ema_conflict": bool(ema_conflict),
            "ema_conflict_entry_penalty": float(self.config.ema_conflict_entry_penalty),
        }

        hard_rsi_reason = self._hard_rsi_reason(direction, tf1h)
        if hard_rsi_reason:
            return self._blocked(
                symbol,
                hard_rsi_reason,
                quadrant=quadrant,
                direction=direction,
                metadata_extra={"direction_gate": direction_gate, "quadrant_filter": quadrant_filter},
            )
        if self._too_far_from_ema20(direction, price, tf1h):
            return self._blocked(
                symbol,
                "ema20_distance_chase_block",
                quadrant=quadrant,
                direction=direction,
                metadata_extra={"direction_gate": direction_gate, "quadrant_filter": quadrant_filter},
            )

        factor_scores = self._score_factors(direction, quadrant, tf15, tf1h)
        divergence = self._rsi_divergence_bonus(direction, tf15, tf1h)
        if divergence > 0:
            factor_scores["rsi_divergence"] = divergence
        score = sum(factor_scores.values())
        threshold = self.config.standard_threshold if quadrant in (Quadrant.Q1, Quadrant.Q3) else self.config.transition_threshold
        metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
        metadata["direction_gate"] = direction_gate
        metadata["quadrant_filter"] = quadrant_filter

        base_open_min = float(self.config.entry_15m_quality_open_min)
        effective_open_min = base_open_min + (float(self.config.ema_conflict_entry_penalty) if ema_conflict else 0.0)
        metadata["entry_15m_effective_open_min"] = effective_open_min
        entry_score = _float(metadata.get("entry_15m_quality_score"), 0.0)

        if self.config.require_15m_entry_pattern and entry_score + 1e-12 < effective_open_min:
            intent = self._watchlist_intent(
                symbol=symbol,
                direction=direction,
                score=max(score, _float(direction_gate.get("direction_score"), 0.0)),
                reason="direction_ok_entry_watch",
                metadata=metadata,
            )
            if intent:
                metadata["watchlist_intent"] = intent
            return QuadrantSignal(
                allowed=False,
                symbol=symbol,
                direction=direction,
                quadrant=quadrant,
                resonance_score=score,
                threshold=threshold,
                factor_scores=factor_scores,
                entry_price_ref=price,
                atr_stop_distance=self._atr_stop_distance(tf15),
                reason="direction_ok_entry_watch" if entry_score >= float(self.config.entry_15m_quality_watch_min) else "direction_ok_entry_too_low",
                metadata=metadata,
            )

        legacy_threshold_bypassed = score + 1e-12 < threshold
        if legacy_threshold_bypassed:
            metadata["legacy_resonance_threshold_bypassed"] = True
            metadata["legacy_resonance_score"] = score
            metadata["legacy_resonance_threshold"] = threshold

        atr_stop_distance = self._atr_stop_distance(tf15)
        leverage = max(1, min(3, int(self.config.max_leverage)))
        target_portion = self._position_portion(price, atr_stop_distance, portfolio)
        stop_loss = price - atr_stop_distance if direction == "long" else price + atr_stop_distance
        metadata.update(
            {
                "allowed_reason": "multi_bar_direction_generated_pass",
                "portfolio_equity": _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0),
                "leverage": leverage,
                "target_portion": target_portion,
                "legacy_resonance_threshold_bypassed": bool(legacy_threshold_bypassed),
            }
        )
        return QuadrantSignal(
            allowed=True,
            symbol=symbol,
            direction=direction,
            quadrant=quadrant,
            resonance_score=score,
            threshold=threshold,
            factor_scores=factor_scores,
            entry_price_ref=price,
            atr_stop_distance=atr_stop_distance,
            target_portion=target_portion,
            leverage=leverage,
            stop_loss_price=stop_loss,
            take_profit_levels=self._take_profit_levels(price, atr_stop_distance, direction),
            reason="multi_bar_direction_generated_pass",
            metadata=metadata,
        )

    def evaluate_exit(
        self,
        *,
        direction: str,
        entry_price: float,
        current_price: float,
        timeframes: Dict[str, Dict[str, Any]],
        position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tf15 = timeframes.get("15m", {}) if isinstance(timeframes, dict) else {}
        tf1h = timeframes.get("1h", {}) if isinstance(timeframes, dict) else {}
        tf4h = timeframes.get("4h", {}) if isinstance(timeframes, dict) else {}
        position = position or {}
        side = str(direction or "").lower()
        atr_stop = self._atr_stop_distance(tf15)
        stop_trigger = str(self.config.stop_trigger or "intrabar").strip().lower()
        close_price = _float(tf15.get("close"), current_price)
        if stop_trigger == "close_confirm":
            if side == "long" and close_price <= entry_price - atr_stop:
                return {"action": "close", "ratio": 1.0, "reason": "HARD_STOP_LOSS_CLOSE_CONFIRMED"}
            if side == "short" and close_price >= entry_price + atr_stop:
                return {"action": "close", "ratio": 1.0, "reason": "HARD_STOP_LOSS_CLOSE_CONFIRMED"}
        else:
            if side == "long" and current_price <= entry_price - atr_stop:
                return {"action": "close", "ratio": 1.0, "reason": "HARD_STOP_LOSS"}
            if side == "short" and current_price >= entry_price + atr_stop:
                return {"action": "close", "ratio": 1.0, "reason": "HARD_STOP_LOSS"}

        tp_distance = max(self.config.tp1_atr_mult * max(_float(tf15.get("atr"), 0.0), 0.0), 0.0)
        if tp_distance > 0 and not bool(position.get("tp1_done", False)):
            if (side == "long" and current_price >= entry_price + tp_distance) or (
                side == "short" and current_price <= entry_price - tp_distance
            ):
                return {
                    "action": "reduce",
                    "ratio": max(0.0, min(1.0, float(self.config.tp1_reduce_pct))),
                    "reason": "TP1_REDUCE_TO_EMA_TRAIL",
                    "updates": {"tp1_done": True, "stage": "trend", "stop_price": float(entry_price)},
                }

        if self.config.ema20_trailing_enabled and bool(position.get("tp1_done", False)):
            ema20 = _float(tf15.get("ema20"), 0.0)
            if ema20 > 0:
                if side == "long" and close_price < ema20:
                    return {"action": "close", "ratio": 1.0, "reason": "EMA20_TRAIL_CLOSE"}
                if side == "short" and close_price > ema20:
                    return {"action": "close", "ratio": 1.0, "reason": "EMA20_TRAIL_CLOSE"}

        hist_1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
        last_hist = hist_1h[-1] if hist_1h else 0.0
        if (side == "long" and last_hist < 0) or (side == "short" and last_hist > 0):
            ratio = self.config.momentum_reduce_pct_second if bool(position.get("quadrant_momentum_reduced", False)) else self.config.momentum_reduce_pct_first
            return {"action": "reduce", "ratio": max(0.0, min(1.0, ratio)), "reason": "MOMENTUM_REDUCE"}
        if self._ema_state(tf1h) == 0:
            return {"action": "reduce", "ratio": max(0.0, min(1.0, self.config.trend_reduce_pct)), "reason": "TREND_REDUCE"}
        quadrant = self.detect_quadrant(tf4h)
        if (side == "long" and quadrant is Quadrant.Q3) or (side == "short" and quadrant is Quadrant.Q1):
            return {"action": "close", "ratio": 1.0, "reason": "QUADRANT_INVERSION_CLOSE"}
        return {"action": "hold", "ratio": 0.0, "reason": "NO_EXIT"}

    def position_quality_score(self, position: Dict[str, Any], current_context: Dict[str, Any]) -> float:
        weights = self.config.quality_weights
        pnl = max(0.0, min(1.0, (_float(position.get("unrealized_pnl_pct"), 0.0) + 0.05) / 0.10))
        aligned = 1.0 if position.get("quadrant") == current_context.get("quadrant") else 0.0
        macd_strength = max(0.0, min(1.0, abs(_float(current_context.get("macd_hist_1h"), 0.0)) / max(_float(current_context.get("atr_1h"), 1.0), 1e-9)))
        hours = max(0.0, _float(position.get("holding_hours"), 0.0))
        time_score = 1.0 if hours <= 8.0 else max(0.0, 1.0 - ((hours - 8.0) / 16.0))
        ema_distance = max(0.0, min(1.0, 1.0 - abs(_float(current_context.get("distance_to_ema20_atr"), 1.0))))
        return (
            pnl * weights.get("pnl", 0.30)
            + aligned * weights.get("resonance_alignment", 0.25)
            + macd_strength * weights.get("macd_strength", 0.15)
            + time_score * weights.get("time_decay", 0.10)
            + ema_distance * weights.get("ema20_distance", 0.20)
        )

    def _score_factors(self, direction: str, quadrant: Quadrant, tf15: Dict[str, Any], tf1h: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if quadrant in (Quadrant.Q1, Quadrant.Q3):
            out["quadrant_4h"] = self.config.quadrant_standard_score
        else:
            out["quadrant_4h"] = self.config.quadrant_transition_score
        if self._tf_ema_ok(direction, tf1h):
            out["ema_1h"] = self.config.score_1h_ema
        hist_bars = 3 if quadrant in (Quadrant.Q2, Quadrant.Q4) else 2
        if self._hist_strengthening(self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist"), direction, bars=hist_bars):
            out["macd_1h"] = self.config.score_1h_macd
        if self._entry_pattern_ok(direction, tf15) or self._entry_quality_live_open(direction, tf15):
            out["entry_15m"] = self.config.score_15m_entry
        if self._rsi_zone_ok(direction, quadrant, tf15):
            out["rsi_15m"] = self.config.score_15m_rsi
        return out

    def _entry_quality_live_open(self, direction: str, tf15: Dict[str, Any]) -> bool:
        if str(self.config.entry_15m_quality_mode or "").strip().lower() != "live":
            return False
        quality = self._entry_15m_quality(direction, tf15)
        return float(quality.get("score", 0.0)) + 1e-12 >= float(self.config.entry_15m_quality_open_min)

    def _recovering_state_signal(
        self,
        *,
        symbol: str,
        price: float,
        tf15: Dict[str, Any],
        tf1h: Dict[str, Any],
        portfolio: Dict[str, Any],
        state_debug: Dict[str, Any],
        metadata_extra: Dict[str, Any],
    ) -> QuadrantSignal:
        direction = str(state_debug.get("quadrant_recovering_direction") or "").lower()
        if direction not in {"long", "short"}:
            return self._blocked(symbol, "quadrant_defense_no_entry", metadata_extra=metadata_extra)
        quadrant = Quadrant.Q1 if direction == "long" else Quadrant.Q3
        hard_rsi_reason = self._hard_rsi_reason(direction, tf1h)
        if hard_rsi_reason:
            metadata_extra.update({"quadrant_state": "recovering", "blocked_reason": hard_rsi_reason})
            return self._blocked(symbol, hard_rsi_reason, quadrant=quadrant, direction=direction, metadata_extra=metadata_extra)
        if self._too_far_from_ema20(direction, price, tf1h):
            metadata_extra.update({"quadrant_state": "recovering", "blocked_reason": "ema20_distance_chase_block"})
            return self._blocked(symbol, "ema20_distance_chase_block", quadrant=quadrant, direction=direction, metadata_extra=metadata_extra)

        factor_scores = self._score_factors(direction, quadrant, tf15, tf1h)
        divergence = self._rsi_divergence_bonus(direction, tf15, tf1h)
        if divergence > 0:
            factor_scores["rsi_divergence"] = divergence
        score = sum(factor_scores.values())
        threshold = float(self.config.recovering_state_score_threshold)
        metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
        metadata.update(metadata_extra)
        metadata.update(
            {
                "quadrant_state": "recovering",
                "quadrant_recovering_direction": direction,
                "portfolio_equity": _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0),
                "recovering_state_score_threshold": threshold,
                "recovering_state_portion_multiplier": float(self.config.recovering_state_portion_multiplier),
            }
        )
        if score + 1e-12 < threshold:
            intent = self._watchlist_intent(
                symbol=symbol,
                direction=direction,
                score=score,
                reason="quadrant_recovering_watchlist",
                metadata=metadata,
            )
            if intent:
                metadata["watchlist_intent"] = intent
            return QuadrantSignal(
                allowed=False,
                symbol=symbol,
                direction=direction,
                quadrant=quadrant,
                resonance_score=score,
                threshold=threshold,
                factor_scores=factor_scores,
                entry_price_ref=price,
                atr_stop_distance=self._atr_stop_distance(tf15),
                reason="quadrant_recovering_watchlist",
                metadata=metadata,
            )

        atr_stop_distance = self._atr_stop_distance(tf15)
        leverage = max(1, min(3, int(self.config.max_leverage)))
        base_portion = self._position_portion(price, atr_stop_distance, portfolio)
        multiplier = max(0.0, min(1.0, float(self.config.recovering_state_portion_multiplier)))
        target_portion = base_portion * multiplier
        stop_loss = price - atr_stop_distance if direction == "long" else price + atr_stop_distance
        metadata.update(
            {
                "allowed_reason": "quadrant_recovering_reduced",
                "signal_quality": "recovering_reduced",
                "base_target_portion": base_portion,
                "target_portion": target_portion,
                "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
                "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
                "leverage_cap": leverage,
                "leverage": leverage,
            }
        )
        return QuadrantSignal(
            allowed=True,
            symbol=symbol,
            direction=direction,
            quadrant=quadrant,
            resonance_score=score,
            threshold=threshold,
            factor_scores=factor_scores,
            entry_price_ref=price,
            atr_stop_distance=atr_stop_distance,
            target_portion=target_portion,
            leverage=leverage,
            stop_loss_price=stop_loss,
            take_profit_levels=self._take_profit_levels(price, atr_stop_distance, direction),
            reason="quadrant_resonance_recovering_reduced",
            metadata=metadata,
        )

    def _allow_high_score_missing_15m_probe(self, score: float, threshold: float) -> bool:
        score_value = float(score)
        return (
            bool(self.config.high_score_15m_override)
            and score_value + 1e-12 >= float(threshold)
            and score_value + 1e-12 >= float(self.config.high_score_15m_override_threshold)
        )

    def _requires_mid_score_macd_confirmation(self, score: float, threshold: float, direction: str, tf1h: Dict[str, Any]) -> bool:
        return (
            bool(self.config.mid_score_requires_3bar_macd)
            and float(threshold) <= float(score)
            and float(score) <= float(self.config.mid_score_upper_bound) + 1e-12
            and not self._hist_strengthening(
                self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist"),
                direction,
                bars=3,
            )
        )

    def _probe_no_15m_veto_reasons(
        self,
        direction: str,
        quadrant: Quadrant,
        tf15: Dict[str, Any],
        tf1h: Dict[str, Any],
        market_context: Optional[Dict[str, Any]],
        *,
        probe_resonance_score: float,
        flow_alignment_score: float,
        entry_quality_score: float = 1.0,
    ) -> list[str]:
        if not bool(self.config.probe_no_15m_veto_enabled):
            return []
        ctx = market_context if isinstance(market_context, dict) else {}
        reasons: list[str] = []

        if bool(self.config.probe_min_15m_resonance_enabled):
            reason = self._minimum_15m_resonance_veto_reason(direction, tf15, tf1h)
            if reason:
                reasons.append(reason)

        if bool(self.config.probe_resonance_score_enabled):
            min_resonance = (
                self.config.probe_resonance_min_threshold_short
                if direction == "short"
                else self.config.probe_resonance_min_threshold
            )
            if float(probe_resonance_score) + 1e-12 < float(min_resonance):
                reasons.append("probe_veto_low_resonance_score")

        if bool(self.config.probe_no_15m_breadth_veto_enabled):
            breadth = ctx.get("market_breadth") if isinstance(ctx.get("market_breadth"), dict) else {}
            confirm_count = int(_float(breadth.get("confirm_count"), 0.0))
            invalid_count = int(_float(breadth.get("invalid_count"), 0.0))
            invalid_min = max(1, int(self.config.probe_breadth_zero_confirm_invalid_min or 2))
            if confirm_count == 0 and invalid_count >= invalid_min:
                reasons.append(f"breadth_zero_confirm_invalid_{invalid_count}")
            if bool(self.config.probe_direction_breadth_veto_enabled):
                reason = self._direction_aware_breadth_veto(direction, breadth)
                if reason:
                    reasons.append(reason)

        if bool(self.config.probe_no_15m_flow_veto_enabled):
            flow = ctx.get("flow") if isinstance(ctx.get("flow"), dict) else ctx
            cvd = _float(flow.get("cvd"), 0.0)
            oi_delta = _float(flow.get("oi_delta"), 0.0)
            imbalance = _float(flow.get("imbalance"), 0.0)
            liq_norm = _float(flow.get("liq_norm"), 0.0)
            if direction == "long" and cvd < 0.0 and oi_delta < 0.0 and imbalance < 0.0:
                reasons.append("long_flow_all_bearish")
            if direction == "short" and cvd > 0.0 and oi_delta > 0.0 and imbalance > 0.0:
                reasons.append("short_flow_all_bullish")
            if direction == "long" and liq_norm < 0.0 and cvd < 0.0 and imbalance < 0.0:
                reasons.append("long_liq_flow_bearish")
            if direction == "short" and liq_norm > 0.0 and cvd > 0.0 and imbalance > 0.0:
                reasons.append("short_liq_flow_bullish")

        if bool(self.config.probe_flow_alignment_score_enabled):
            min_flow = (
                self.config.probe_min_flow_alignment_short
                if direction == "short"
                else self.config.probe_min_flow_alignment
            )
            if float(flow_alignment_score) + 1e-12 < float(min_flow):
                reasons.append("probe_veto_flow_misaligned")

        if bool(self.config.probe_min_entry_score_enabled):
            if float(entry_quality_score) + 1e-12 < float(self.config.probe_min_entry_score):
                reasons.append("probe_veto_entry_quality_hold")

        if bool(self.config.probe_no_15m_rsi_macd_veto_enabled):
            rsi15 = _float(tf15.get("rsi"), 50.0)
            rsi1h = _float(tf1h.get("rsi"), 50.0)
            hist15 = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
            hist1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
            hist15_strengthening = self._hist_strengthening(hist15, direction, bars=3)
            hist1h_strengthening = self._hist_strengthening(hist1h, direction, bars=3)
            if direction == "long" and (rsi15 > self.config.long_rsi_max or rsi1h > 68.0) and not hist15_strengthening and not hist1h_strengthening:
                reasons.append("long_rsi_hot_macd_not_strengthening")
            if direction == "short" and (rsi15 < self.config.short_rsi_min or rsi1h < 32.0) and not hist15_strengthening and not hist1h_strengthening:
                reasons.append("short_rsi_cold_macd_not_strengthening")

        return reasons

    def _minimum_15m_resonance_veto_reason(self, direction: str, tf15: Dict[str, Any], tf1h: Dict[str, Any]) -> str:
        if not bool(self.config.probe_require_macd_15m_or_1h_near_ema):
            return ""
        hist15 = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        hist1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
        macd15 = self._hist_strengthening(hist15, direction, bars=3)
        macd1h = self._hist_strengthening(hist1h, direction, bars=3)
        near_ema = bool(self._entry_pattern_detail(direction, tf15).get("near_ema", False))
        if macd15 or (macd1h and near_ema):
            return ""
        return "probe_veto_no_15m_resonance"

    def _direction_aware_breadth_veto(self, direction: str, breadth: Dict[str, Any]) -> str:
        btc_30m = _float(breadth.get("btc_ret_30m"), 0.0)
        btc_60m = _float(breadth.get("btc_ret_60m"), 0.0)
        alt_med = _float(breadth.get("alt_median_60m"), 0.0)
        if direction == "short":
            if (
                btc_30m > self.config.short_probe_btc_30m_veto_pct
                or btc_60m > self.config.short_probe_btc_60m_veto_pct
                or alt_med > self.config.short_probe_alt_med_veto_pct
            ):
                return f"probe_veto_short_against_breadth:btc_30m={btc_30m:.4f},btc_60m={btc_60m:.4f},alt_med={alt_med:.4f}"
        elif (
            btc_30m < -self.config.long_probe_btc_30m_veto_pct
            or btc_60m < -self.config.long_probe_btc_60m_veto_pct
            or alt_med < -self.config.long_probe_alt_med_veto_pct
        ):
            return f"probe_veto_long_against_breadth:btc_30m={btc_30m:.4f},btc_60m={btc_60m:.4f},alt_med={alt_med:.4f}"
        return ""

    def _compute_probe_resonance_score(self, direction: str, quadrant: Quadrant, tf15: Dict[str, Any], tf1h: Dict[str, Any]) -> float:
        hist15 = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        hist1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
        score = 0.30 if quadrant in (Quadrant.Q1, Quadrant.Q2, Quadrant.Q3, Quadrant.Q4) else 0.0
        if self._hist_strengthening(hist1h, direction, bars=3):
            score += 0.30
        if self._hist_strengthening(hist15, direction, bars=3):
            score += 0.25
        if bool(self._entry_pattern_detail(direction, tf15).get("near_ema", False)):
            score += 0.10
        if len(hist1h) >= 2:
            if direction == "long" and hist1h[-2] <= 0.0 < hist1h[-1]:
                score += 0.05
            if direction == "short" and hist1h[-2] >= 0.0 > hist1h[-1]:
                score += 0.05
        return max(0.0, min(1.0, score))

    def _flow_alignment_score(self, direction: str, market_context: Optional[Dict[str, Any]]) -> float:
        ctx = market_context if isinstance(market_context, dict) else {}
        flow = ctx.get("flow") if isinstance(ctx.get("flow"), dict) else ctx
        side = 1.0 if direction == "long" else -1.0
        components = (
            (_float(flow.get("cvd"), 0.0) * side, 0.35),
            (_float(flow.get("oi_delta"), 0.0) * side, 0.25),
            (_float(flow.get("imbalance"), 0.0) * side, 0.25),
            (_float(flow.get("liq_norm"), 0.0) * side, 0.15),
        )
        raw = sum(value * weight for value, weight in components)
        return math.tanh(raw * 3.0)

    def _grade_probe_veto(
        self,
        veto_reasons: list[str],
        direction: str,
        tf15: Dict[str, Any],
        tf1h: Dict[str, Any],
        market_context: Optional[Dict[str, Any]],
        flow_alignment_score: float,
    ) -> Dict[str, Any]:
        if not bool(self.config.probe_veto_graded_enabled):
            return {"action": "reject", "portion_multiplier": 0.0, "reason": "graded_disabled"}
        ctx = market_context if isinstance(market_context, dict) else {}
        breadth = ctx.get("market_breadth") if isinstance(ctx.get("market_breadth"), dict) else {}
        hist15 = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        hist1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
        macd15 = self._hist_strengthening(hist15, direction, bars=3)
        macd1h = self._hist_strengthening(hist1h, direction, bars=3)
        hard_reasons: list[str] = []
        multipliers: list[float] = []

        for reason in veto_reasons:
            item = str(reason or "")
            if item == "probe_veto_no_15m_resonance":
                if macd15 or macd1h:
                    multipliers.append(float(self.config.probe_veto_breadth_reduced_multiplier))
                else:
                    hard_reasons.append(item)
                continue
            if item.startswith("probe_veto_long_against_breadth") or item.startswith("probe_veto_short_against_breadth"):
                against = self._btc_against_breadth_abs(direction, breadth)
                if against < float(self.config.probe_veto_hard_reject_btc_against_pct):
                    multipliers.append(float(self.config.probe_veto_direction_reduced_multiplier))
                else:
                    hard_reasons.append(item)
                continue
            if item.startswith("breadth_zero_confirm_invalid"):
                hard_reasons.append(item)
                continue
            if item == "probe_veto_flow_misaligned":
                if float(flow_alignment_score) > float(self.config.probe_veto_hard_reject_flow_score):
                    multipliers.append(float(self.config.probe_veto_direction_reduced_multiplier))
                else:
                    hard_reasons.append(item)
                continue
            hard_reasons.append(item)

        if hard_reasons:
            return {"action": "reject", "portion_multiplier": 0.0, "hard_reasons": hard_reasons}
        if multipliers:
            return {"action": "open_reduced", "portion_multiplier": max(0.0, min(1.0, min(multipliers)))}
        return {"action": "reject", "portion_multiplier": 0.0, "reason": "no_reducible_veto"}

    @staticmethod
    def _btc_against_breadth_abs(direction: str, breadth: Dict[str, Any]) -> float:
        btc_30m = _float(breadth.get("btc_ret_30m"), 0.0)
        btc_60m = _float(breadth.get("btc_ret_60m"), 0.0)
        alt_med = _float(breadth.get("alt_median_60m"), 0.0)
        if direction == "short":
            return max(0.0, btc_30m, btc_60m, alt_med)
        return max(0.0, -btc_30m, -btc_60m, -alt_med)

    def _probe_position_portion(self, portfolio: Dict[str, Any]) -> float:
        equity = _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0)
        base = max(0.0, float(self.config.high_score_probe_portion))
        if equity > 0:
            base = max(base, max(0.0, float(self.config.min_entry_margin_usdt)) / equity)
        return min(base, max(0.0, float(self.config.max_total_exposure_pct)))

    def _multi_bar_direction_gate(self, direction: str, tf4h: Dict[str, Any], tf1h: Dict[str, Any], tf15: Dict[str, Any]) -> Dict[str, Any]:
        if str(self.config.direction_model or "").strip().lower() != "multi_bar_slope":
            return {}

        lookbacks = {
            "4h": max(2, int(self.config.direction_4h_lookback_bars)),
            "1h": max(2, int(self.config.direction_1h_lookback_bars)),
            "15m": max(2, int(self.config.direction_15m_lookback_bars)),
        }
        series = {
            "4h": self._close_series(tf4h),
            "1h": self._close_series(tf1h),
            "15m": self._close_series(tf15),
        }
        counts = {tf: len(values) for tf, values in series.items()}
        missing = [tf for tf, required in lookbacks.items() if counts.get(tf, 0) < required]
        if missing:
            return {
                "ok": False,
                "reason": "multi_bar_direction_insufficient_history",
                "blocked_reason": "insufficient_history",
                "direction_model": "multi_bar_slope",
                "history_counts": counts,
                "required_history_counts": lookbacks,
                "missing_timeframes": missing,
            }

        scores = {
            "4h": self._trend_score_from_closes(series["4h"][-lookbacks["4h"] :]),
            "1h": self._trend_score_from_closes(series["1h"][-lookbacks["1h"] :]),
            "15m": self._trend_score_from_closes(series["15m"][-lookbacks["15m"] :]),
        }
        expected_sign = 1.0 if direction == "long" else -1.0
        aligned_4h = scores["4h"] * expected_sign
        aligned_1h = scores["1h"] * expected_sign
        aligned_15m = scores["15m"] * expected_sign
        conflict_min = max(0.0, float(self.config.direction_strong_conflict_min_abs))
        open_min = max(0.0, float(self.config.direction_open_min_abs))
        weighted = (aligned_4h * 0.50) + (aligned_1h * 0.30) + (aligned_15m * 0.20)

        soft_1h_min = max(0.0, float(self.config.direction_transition_1h_min_abs))
        transition_candidate = (
            bool(self.config.direction_transition_mode_enabled)
            and aligned_4h >= open_min
            and soft_1h_min <= aligned_1h < open_min
            and aligned_15m > -conflict_min
            and weighted >= open_min
        )
        if (aligned_4h < open_min or aligned_1h < open_min) and not transition_candidate:
            return {
                "ok": False,
                "reason": "multi_bar_direction_no_entry",
                "blocked_reason": "anchor_timeframe_not_aligned",
                "direction_model": "multi_bar_slope",
                "direction": direction,
                "direction_score": weighted,
                "scores": scores,
                "aligned_scores": {"4h": aligned_4h, "1h": aligned_1h, "15m": aligned_15m},
                "history_counts": counts,
            }
        if aligned_15m <= -conflict_min:
            return {
                "ok": False,
                "reason": "multi_bar_direction_no_entry",
                "blocked_reason": "15m_strong_countertrend",
                "direction_model": "multi_bar_slope",
                "direction": direction,
                "direction_score": weighted,
                "scores": scores,
                "aligned_scores": {"4h": aligned_4h, "1h": aligned_1h, "15m": aligned_15m},
                "history_counts": counts,
            }
        if weighted < open_min:
            return {
                "ok": False,
                "reason": "multi_bar_direction_no_entry",
                "blocked_reason": "direction_score_below_threshold",
                "direction_model": "multi_bar_slope",
                "direction": direction,
                "direction_score": weighted,
                "scores": scores,
                "aligned_scores": {"4h": aligned_4h, "1h": aligned_1h, "15m": aligned_15m},
                "history_counts": counts,
            }
        return {
            "ok": True,
            "reason": "multi_bar_direction_transition_pass" if transition_candidate else "multi_bar_direction_pass",
            "direction_model": "multi_bar_slope",
            "direction": direction,
            "direction_score": weighted,
            "scores": scores,
            "aligned_scores": {"4h": aligned_4h, "1h": aligned_1h, "15m": aligned_15m},
            "history_counts": counts,
            "transition_mode": bool(transition_candidate),
        }

    def _multi_bar_direction_scores(self, tf4h: Dict[str, Any], tf1h: Dict[str, Any], tf15: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        long_gate = self._multi_bar_direction_gate("long", tf4h, tf1h, tf15)
        short_gate = self._multi_bar_direction_gate("short", tf4h, tf1h, tf15)
        if not long_gate:
            long_gate = {"ok": False, "reason": "multi_bar_direction_disabled", "direction": "long", "direction_score": 0.0}
        if not short_gate:
            short_gate = {"ok": False, "reason": "multi_bar_direction_disabled", "direction": "short", "direction_score": 0.0}
        long_gate.setdefault("direction", "long")
        short_gate.setdefault("direction", "short")
        return {"long": long_gate, "short": short_gate}

    def _select_multi_bar_direction(self, tf4h: Dict[str, Any], tf1h: Dict[str, Any], tf15: Dict[str, Any]) -> Dict[str, Any]:
        candidates = self._multi_bar_direction_scores(tf4h, tf1h, tf15)
        passing = [gate for gate in candidates.values() if bool(gate.get("ok", False))]
        if not passing:
            return {
                "ok": False,
                "reason": "multi_bar_no_direction",
                "blocked_reason": "both_sides_below_threshold",
                "direction": "",
                "direction_model": "multi_bar_slope",
                "candidates": candidates,
            }
        selected = max(passing, key=lambda gate: abs(_float(gate.get("direction_score"), 0.0)))
        out = dict(selected)
        out["ok"] = True
        out["reason"] = "multi_bar_direction_selected"
        out["selected_direction"] = out.get("direction")
        out["candidates"] = candidates
        return out

    @staticmethod
    def _close_series(tf: Dict[str, Any]) -> list[float]:
        for key in ("close_series", "close_array", "closes"):
            value = tf.get(key)
            if isinstance(value, (list, tuple)):
                return [_float(v) for v in value if math.isfinite(_float(v, float("nan"))) and _float(v, 0.0) > 0.0]
        close = _float(tf.get("close"), 0.0)
        return [close] if close > 0.0 and math.isfinite(close) else []

    @staticmethod
    def _trend_score_from_closes(closes: list[float]) -> float:
        n = len(closes)
        if n < 2:
            return 0.0
        y = [float(v) for v in closes]
        x_mean = (n - 1) / 2.0
        y_mean = sum(y) / n
        denom = sum((i - x_mean) ** 2 for i in range(n))
        if denom <= 0.0 or y_mean <= 0.0:
            return 0.0
        slope = sum((i - x_mean) * (y[i] - y_mean) for i in range(n)) / denom
        fitted = [y_mean + slope * (i - x_mean) for i in range(n)]
        ss_tot = sum((v - y_mean) ** 2 for v in y)
        ss_res = sum((y[i] - fitted[i]) ** 2 for i in range(n))
        r2 = 0.0 if ss_tot <= 0.0 else max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))
        normalized_move = (slope * n) / y_mean
        score = math.tanh(normalized_move * 12.0) * (0.35 + 0.65 * r2)
        return max(-1.0, min(1.0, score))

    def _extreme_4h_rsi_penalty(self, direction: str, tf4h: Dict[str, Any]) -> float:
        penalty = max(0.0, float(self.config.extreme_4h_rsi_penalty or 0.0))
        if penalty <= 0:
            return 0.0
        rsi = _float(tf4h.get("rsi"), 50.0)
        if direction == "long" and rsi > self.config.long_4h_rsi_penalty_above:
            return penalty
        if direction == "short" and rsi < self.config.short_4h_rsi_penalty_below:
            return penalty
        return 0.0

    def _metadata(
        self,
        quadrant: Quadrant,
        direction: str,
        score: float,
        threshold: float,
        factor_scores: Dict[str, float],
        tf15: Dict[str, Any],
        tf1h: Dict[str, Any],
    ) -> Dict[str, Any]:
        hist15 = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        hist1h = self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist")
        entry_detail = self._entry_pattern_detail(direction, tf15)
        entry_quality = self._entry_15m_quality(direction, tf15, detail=entry_detail)
        return {
            "strategy_mode": "quadrant_resonance",
            "strategy_source": "ema_macd_rsi_quadrant_resonance",
            "quadrant_4h": quadrant.value,
            "signal_direction": direction,
            "resonance_score": score,
            "signal_score": score,
            "signal_score_threshold": threshold,
            "factor_scores": dict(factor_scores),
            "entry_rsi_15m": _float(tf15.get("rsi"), 0.0),
            "entry_rsi_1h": _float(tf1h.get("rsi"), 0.0),
            "entry_ema20_1h": _float(tf1h.get("ema20"), 0.0),
            "entry_ema50_1h": _float(tf1h.get("ema50"), 0.0),
            "entry_atr_15m": _float(tf15.get("atr"), 0.0),
            "macd_hist_15m_last3": hist15[-3:],
            "macd_hist_1h_last3": hist1h[-3:],
            "macd_hist_15m_strengthening": self._hist_strengthening(hist15, direction, bars=3),
            "macd_hist_1h_strengthening": self._hist_strengthening(hist1h, direction, bars=3),
            "entry_15m_detail": entry_detail,
            "entry_15m_quality_score": entry_quality["score"],
            "entry_15m_quality_bucket": entry_quality["bucket"],
            "entry_15m_missing_conditions": entry_quality["missing_conditions"],
            "entry_15m_quality_live_pass": (
                str(self.config.entry_15m_quality_mode or "").strip().lower() == "live"
                and float(entry_quality["score"]) + 1e-12 >= float(self.config.entry_15m_quality_open_min)
            ),
            "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
            "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
            "stage": "final",
        }

    def _blocked(
        self,
        symbol: str,
        reason: str,
        *,
        quadrant: Quadrant = Quadrant.DEFENSE,
        direction: str = "",
        metadata_extra: Optional[Dict[str, Any]] = None,
    ) -> QuadrantSignal:
        metadata = {
            "strategy_mode": "quadrant_resonance",
            "quadrant_4h": quadrant.value,
            "signal_direction": direction,
            "blocked_reason": reason,
            "stage": "blocked",
        }
        if isinstance(metadata_extra, dict):
            metadata.update(metadata_extra)
        return QuadrantSignal(
            allowed=False,
            symbol=symbol,
            direction=direction,
            quadrant=quadrant,
            reason=reason,
            metadata=metadata,
        )

    def _quadrant_debug(self, tf4h: Dict[str, Any], quadrant: Quadrant) -> Dict[str, Any]:
        ema20 = _float(tf4h.get("ema20"), 0.0)
        ema50 = _float(tf4h.get("ema50"), 0.0)
        ema200 = _float(tf4h.get("ema200"), 0.0)
        close = _float(tf4h.get("close"), 0.0)
        hist = self._series(tf4h, "macd_hist_series", "macd_hist_array", "macd_hist")
        ema_state = self._ema_state(tf4h)
        pos_strength = self._hist_strengthening(hist, "long", bars=2)
        neg_strength = self._hist_strengthening(hist, "short", bars=2)
        ema20_50_cross = self._pct_diff(ema20, ema50)
        ema50_200_cross = self._pct_diff(ema50, ema200)
        close_to_alignment = self._ema_close_to_alignment(ema20, ema50, ema200)
        missing_fields = []
        if not self._positive_finite(ema20):
            missing_fields.append("ema20")
        if not self._positive_finite(ema50):
            missing_fields.append("ema50")
        if not self._positive_finite(ema200):
            missing_fields.append("ema200")
        if len(hist) < 2:
            missing_fields.append("macd_hist")
        if len(missing_fields) == 1:
            detail = f"missing_indicators_{missing_fields[0]}"
        elif missing_fields:
            detail = "missing_indicators_multiple"
        elif ema_state == 0 and not close_to_alignment:
            detail = "ema_disorder"
        elif not pos_strength and not neg_strength:
            detail = "macd_not_strengthening"
        elif ema_state == 0:
            detail = "ema_disorder"
        else:
            detail = "macd_not_strengthening"
        debug = {
            "quadrant_4h": quadrant.value,
            "ema20_4h": ema20,
            "ema50_4h": ema50,
            "ema200_4h": ema200,
            "close_4h": close,
            "ema_state_4h": ema_state,
            "ema20_50_cross_pct": ema20_50_cross,
            "ema50_200_cross_pct": ema50_200_cross,
            "ema_close_to_alignment": close_to_alignment,
            "macd_hist_4h_last3": hist[-3:],
            "macd_pos_strength_4h": pos_strength,
            "macd_neg_strength_4h": neg_strength,
            "blocked_reason_detail": detail,
        }
        if missing_fields:
            debug["missing_indicator_fields"] = missing_fields
        return {"blocked_reason_detail": detail, "quadrant_debug": debug}

    def _quadrant_state_debug(self, tf4h: Dict[str, Any]) -> Dict[str, Any]:
        ema_state = self._ema_state(tf4h)
        hist = self._series(tf4h, "macd_hist_series", "macd_hist_array", "macd_hist")
        if not bool(self.config.quadrant_4h_three_state_enabled) or ema_state == 0 or len(hist) < 3:
            return {"quadrant_state": "defense", "quadrant_recovering_direction": ""}
        slope_improving = hist[-1] > hist[-2] > hist[-3]
        slope_weakening = hist[-1] < hist[-2] < hist[-3]
        if ema_state == 1 and slope_improving:
            return {"quadrant_state": "recovering", "quadrant_recovering_direction": "long"}
        if ema_state == -1 and slope_weakening:
            return {"quadrant_state": "recovering", "quadrant_recovering_direction": "short"}
        return {"quadrant_state": "defense", "quadrant_recovering_direction": ""}

    def _watchlist_intent(
        self,
        *,
        symbol: str,
        direction: str,
        score: float,
        reason: str,
        metadata: Dict[str, Any],
        veto_reasons: Optional[list[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not bool(self.config.watchlist_intent_enabled):
            return None
        if float(score) + 1e-12 < float(self.config.watchlist_min_signal_score):
            return None
        quality = _float(metadata.get("entry_15m_quality_score"), 0.0)
        bucket = str(metadata.get("entry_15m_quality_bucket") or "")
        if reason == "missing_15m_entry_pattern" and bucket == "hold":
            return None
        missing = metadata.get("entry_15m_missing_conditions")
        if not isinstance(missing, list):
            missing = []
        veto_reasons = veto_reasons or []
        reversible = any(
            str(reason_item).startswith("breadth_zero_confirm_invalid")
            or str(reason_item).startswith("probe_veto_long_against_breadth")
            or str(reason_item).startswith("probe_veto_short_against_breadth")
            for reason_item in veto_reasons
        )
        if reason == "probe_no_15m_direction_veto" and not (
            bool(self.config.watchlist_include_probe_veto) and reversible
        ):
            return None
        candidate_reason = "reversible_probe_veto" if reason == "probe_no_15m_direction_veto" else reason
        if candidate_reason == "reversible_probe_veto" and any(
            str(reason_item).startswith("breadth_zero_confirm_invalid") for reason_item in veto_reasons
        ):
            return None
        ttl = (
            self.config.watchlist_probe_veto_ttl_bars
            if candidate_reason == "reversible_probe_veto"
            else self.config.watchlist_ttl_bars
        )
        return {
            "enabled": True,
            "dry_run": bool(self.config.watchlist_intent_dry_run),
            "symbol": str(symbol or "").upper(),
            "side": direction,
            "score": float(score),
            "entry_15m_quality_score": quality,
            "entry_15m_quality_bucket": bucket,
            "candidate_reason": candidate_reason,
            "missing_conditions": list(missing),
            "veto_reasons": list(veto_reasons),
            "ttl_bars": max(1, int(ttl)),
        }

    @staticmethod
    def _series(tf: Dict[str, Any], *keys: str) -> list[float]:
        for key in keys:
            value = tf.get(key)
            if isinstance(value, (list, tuple)):
                return [_float(v) for v in value]
            if value is not None and key == keys[-1]:
                return [_float(value)]
        return []

    @staticmethod
    def _ema_state(tf: Dict[str, Any]) -> int:
        e20 = _float(tf.get("ema20"), 0.0)
        e50 = _float(tf.get("ema50"), 0.0)
        e200 = _float(tf.get("ema200"), 0.0)
        if e20 > e50 > e200:
            return 1
        if e20 < e50 < e200:
            return -1
        return 0

    @staticmethod
    def _ema_consistent_with_direction(ema_state: int, direction: str) -> bool:
        if ema_state == 0:
            return False
        if direction == "long":
            return ema_state == 1
        if direction == "short":
            return ema_state == -1
        return False

    @staticmethod
    def _positive_finite(value: float) -> bool:
        return math.isfinite(float(value)) and float(value) > 0.0

    @staticmethod
    def _pct_diff(left: float, right: float) -> float:
        if right <= 0 or not math.isfinite(float(right)):
            return 0.0
        return (float(left) - float(right)) / float(right)

    def _ema_close_to_alignment(self, ema20: float, ema50: float, ema200: float) -> bool:
        if not (self._positive_finite(ema20) and self._positive_finite(ema50) and self._positive_finite(ema200)):
            return False
        ema50_200 = self._pct_diff(ema50, ema200)
        near_slow_cross = -0.005 <= ema50_200 <= 0.005
        return near_slow_cross and ((ema20 > ema50 and ema50 <= ema200) or (ema20 < ema50 and ema50 >= ema200))

    @staticmethod
    def _hist_strengthening(hist: list[float], direction: str, *, bars: int) -> bool:
        if len(hist) < bars:
            return False
        tail = hist[-bars:]
        if direction == "long":
            return tail[-1] > 0 and all(tail[i] > tail[i - 1] for i in range(1, len(tail)))
        return tail[-1] < 0 and all(tail[i] < tail[i - 1] for i in range(1, len(tail)))

    def _tf_ema_ok(self, direction: str, tf: Dict[str, Any]) -> bool:
        e20 = _float(tf.get("ema20"), 0.0)
        e50 = _float(tf.get("ema50"), 0.0)
        close = _float(tf.get("close"), 0.0)
        hist = self._series(tf, "macd_hist_series", "macd_hist_array", "macd_hist")
        if direction == "long":
            return e20 > e50 and (close >= e20 or (len(hist) >= 2 and hist[-1] > hist[-2]))
        return e20 < e50 and close <= e20

    def _entry_pattern_detail(self, direction: str, tf15: Dict[str, Any]) -> Dict[str, Any]:
        close = _float(tf15.get("close"), 0.0)
        open_price = _float(tf15.get("open"), close)
        high = _float(tf15.get("high"), close)
        low = _float(tf15.get("low"), close)
        ema20 = _float(tf15.get("ema20"), close)
        atr = max(_float(tf15.get("atr"), 0.0), close * 0.001, 1e-9)
        near_ema = abs(close - ema20) <= atr
        hist = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        hist_prev = hist[-2] if len(hist) >= 2 else 0.0
        hist_current = hist[-1] if hist else 0.0
        if direction == "long":
            hist_cross = hist_prev <= 0 < hist_current
            direction_candle = close > open_price
        else:
            hist_cross = hist_prev >= 0 > hist_current
            direction_candle = close < open_price
        body = abs(close - open_price)
        wick = high - low
        pin_bar = wick > 0 and body / wick <= 0.35
        ok = near_ema and (hist_cross or direction_candle or pin_bar)
        return {
            "ok": bool(ok),
            "near_ema": bool(near_ema),
            "hist_cross": bool(hist_cross),
            "direction_candle": bool(direction_candle),
            "pin_bar": bool(pin_bar),
            "close": close,
            "ema20": ema20,
            "atr": atr,
            "ema_distance_atr_ratio": abs(close - ema20) / atr,
            "hist_prev": hist_prev,
            "hist_current": hist_current,
        }

    def _entry_15m_quality(
        self,
        direction: str,
        tf15: Dict[str, Any],
        *,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        detail = detail or self._entry_pattern_detail(direction, tf15)
        hist = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        macd_strengthening = self._hist_strengthening(hist, direction, bars=3)
        ema_ratio = _float(detail.get("ema_distance_atr_ratio"), 99.0)
        score = 0.0
        missing: list[str] = []

        if bool(detail.get("near_ema", False)):
            score += 0.25
            if ema_ratio < 0.5:
                score += 0.10
        else:
            missing.append("near_ema")

        if macd_strengthening:
            score += 0.20
        else:
            missing.append("macd_15m_strengthening")

        if bool(detail.get("hist_cross", False)):
            score += 0.15
        else:
            missing.append("hist_cross")

        if bool(detail.get("direction_candle", False)):
            score += 0.15
        else:
            missing.append("direction_candle")

        if bool(detail.get("pin_bar", False)):
            score += 0.10
        else:
            missing.append("pin_bar")

        score = max(0.0, min(1.0, score))
        if bool(detail.get("ok", False)) and score < float(self.config.entry_15m_quality_open_min):
            score = float(self.config.entry_15m_quality_open_min)
        if score >= float(self.config.entry_15m_quality_open_min):
            bucket = "open"
        elif score >= float(self.config.entry_15m_quality_watch_min):
            bucket = "watch"
        else:
            bucket = "hold"
        return {"score": score, "bucket": bucket, "missing_conditions": missing}

    def _entry_pattern_ok(self, direction: str, tf15: Dict[str, Any]) -> bool:
        return bool(self._entry_pattern_detail(direction, tf15).get("ok"))

    def _rsi_zone_ok(self, direction: str, quadrant: Quadrant, tf15: Dict[str, Any]) -> bool:
        rsi = _float(tf15.get("rsi"), 50.0)
        if direction == "long":
            low = self.config.q2_long_rsi_min if quadrant is Quadrant.Q2 else self.config.long_rsi_min
            return low <= rsi <= self.config.long_rsi_max
        high = self.config.q4_short_rsi_max if quadrant is Quadrant.Q4 else self.config.short_rsi_max
        return self.config.short_rsi_min <= rsi <= high

    def _hard_rsi_reason(self, direction: str, tf1h: Dict[str, Any]) -> str:
        rsi = _float(tf1h.get("rsi"), 50.0)
        if direction == "long" and rsi > self.config.long_1h_rsi_hard_max:
            return "rsi_extreme_block"
        if direction == "short" and rsi < self.config.short_1h_rsi_hard_min:
            return "rsi_extreme_block"
        return ""

    def _too_far_from_ema20(self, direction: str, price: float, tf1h: Dict[str, Any]) -> bool:
        ema20 = _float(tf1h.get("ema20"), 0.0)
        atr = _float(tf1h.get("atr"), 0.0)
        if ema20 <= 0 or atr <= 0:
            return False
        return abs(float(price) - ema20) > (atr * self.config.ema20_distance_atr_mult)

    def _rsi_divergence_bonus(self, direction: str, tf15: Dict[str, Any], tf1h: Dict[str, Any]) -> float:
        key = "bullish_rsi_divergence" if direction == "long" else "bearish_rsi_divergence"
        if bool(tf15.get(key, False)) or bool(tf1h.get(key, False)):
            return self.config.rsi_divergence_bonus
        return 0.0

    def _atr_stop_distance(self, tf15: Dict[str, Any]) -> float:
        close = _float(tf15.get("close"), 0.0)
        atr = _float(tf15.get("atr"), close * 0.01)
        return max(atr * self.config.hard_stop_atr_mult, close * 0.001)

    def _position_portion(self, price: float, stop_distance: float, portfolio: Dict[str, Any]) -> float:
        equity = _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0)
        if equity <= 0:
            return 0.0
        leverage = max(1.0, min(3.0, float(self.config.max_leverage or 1.0)))
        stop_pct = max(stop_distance / max(float(price), 1e-9), 1e-9)
        risk_portion = self.config.risk_per_trade_pct / (stop_pct * leverage)
        min_portion = self.config.min_entry_notional_usdt / (equity * leverage)
        margin_floor = self.config.min_entry_margin_usdt / equity
        portion = max(risk_portion, min_portion, margin_floor)
        return max(0.0, min(self.config.max_total_exposure_pct, portion))

    @staticmethod
    def _take_profit_levels(price: float, stop_distance: float, direction: str) -> list[dict]:
        sign = 1.0 if direction == "long" else -1.0
        return [
            {"multiple": 1.5, "price": price + sign * stop_distance * 1.5, "reduce_pct": 0.30, "reason": "ATR_TP1_REDUCE"},
            {"multiple": 3.0, "price": price + sign * stop_distance * 3.0, "reduce_pct": 0.40, "reason": "ATR_TP2_REDUCE"},
            {"multiple": 4.0, "price": price + sign * stop_distance * 4.0, "reduce_pct": 1.00, "reason": "ATR_TP3_CLOSE"},
        ]
