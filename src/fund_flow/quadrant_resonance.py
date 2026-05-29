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
    ) -> QuadrantSignal:
        portfolio = portfolio or {}
        tf15 = timeframes.get("15m", {}) if isinstance(timeframes, dict) else {}
        tf1h = timeframes.get("1h", {}) if isinstance(timeframes, dict) else {}
        tf4h = timeframes.get("4h", {}) if isinstance(timeframes, dict) else {}
        if not tf15 or not tf1h or not tf4h:
            return self._blocked(symbol, "missing_timeframes")

        quadrant = self.detect_quadrant(tf4h)
        if quadrant is Quadrant.DEFENSE:
            debug = self._quadrant_debug(tf4h, quadrant)
            return self._blocked(symbol, "quadrant_defense_no_entry", quadrant=quadrant, metadata_extra=debug)

        direction = "long" if quadrant in (Quadrant.Q1, Quadrant.Q2) else "short"
        hard_rsi_reason = self._hard_rsi_reason(direction, tf1h)
        if hard_rsi_reason:
            return self._blocked(symbol, hard_rsi_reason, quadrant=quadrant, direction=direction)
        if self._too_far_from_ema20(direction, price, tf1h):
            return self._blocked(symbol, "ema20_distance_chase_block", quadrant=quadrant, direction=direction)

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
        if self.config.require_15m_entry_pattern and "entry_15m" not in factor_scores:
            metadata = self._metadata(quadrant, direction, score, threshold, factor_scores, tf15, tf1h)
            metadata.update(metadata_extra)
            if self._allow_high_score_missing_15m_probe(score, threshold):
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
                        "min_entry_notional_usdt": self.config.min_entry_notional_usdt,
                        "min_entry_margin_usdt": self.config.min_entry_margin_usdt,
                        "leverage_cap": leverage,
                        "leverage": leverage,
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
                    reason="quadrant_resonance_probe_no_15m",
                    metadata=metadata,
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
                reason="missing_15m_entry_pattern",
                metadata=metadata,
            )
        if (
            self.config.mid_score_requires_3bar_macd
            and threshold <= score < float(self.config.mid_score_upper_bound)
            and not self._hist_strengthening(self._series(tf1h, "macd_hist_series", "macd_hist_array", "macd_hist"), direction, bars=3)
        ):
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
        if self._entry_pattern_ok(direction, tf15):
            out["entry_15m"] = self.config.score_15m_entry
        if self._rsi_zone_ok(direction, quadrant, tf15):
            out["rsi_15m"] = self.config.score_15m_rsi
        return out

    def _allow_high_score_missing_15m_probe(self, score: float, threshold: float) -> bool:
        score_value = float(score)
        return (
            bool(self.config.high_score_15m_override)
            and score_value + 1e-12 >= float(threshold)
            and score_value + 1e-12 >= float(self.config.high_score_15m_override_threshold)
        )

    def _probe_position_portion(self, portfolio: Dict[str, Any]) -> float:
        equity = _float(portfolio.get("equity", portfolio.get("account_equity", portfolio.get("available_balance"))), 0.0)
        base = max(0.0, float(self.config.high_score_probe_portion))
        if equity > 0:
            base = max(base, max(0.0, float(self.config.min_entry_margin_usdt)) / equity)
        return min(base, max(0.0, float(self.config.max_total_exposure_pct)))

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

    def _entry_pattern_ok(self, direction: str, tf15: Dict[str, Any]) -> bool:
        close = _float(tf15.get("close"), 0.0)
        ema20 = _float(tf15.get("ema20"), close)
        atr = max(_float(tf15.get("atr"), 0.0), close * 0.001, 1e-9)
        near_ema = abs(close - ema20) <= atr
        hist = self._series(tf15, "macd_hist_series", "macd_hist_array", "macd_hist")
        if len(hist) >= 2:
            if direction == "long" and hist[-2] <= 0 < hist[-1]:
                return near_ema
            if direction == "short" and hist[-2] >= 0 > hist[-1]:
                return near_ema
        open_price = _float(tf15.get("open"), close)
        high = _float(tf15.get("high"), close)
        low = _float(tf15.get("low"), close)
        body = abs(close - open_price)
        wick = high - low
        pin_bar = wick > 0 and body / wick <= 0.35
        bullish = close > open_price
        bearish = close < open_price
        return near_ema and ((direction == "long" and (bullish or pin_bar)) or (direction == "short" and (bearish or pin_bar)))

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
