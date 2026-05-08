"""
MACD多时间框架交易策略模块 V2.0 - VWAP + BOLL 增强版

策略架构：
- BOLL结构层（4H + 1H）→ 过滤逆势交易，确认价格在布林带中的位置
- MACD_4H 主方向层（权重40%）→ 负责主趋势打分，折叠 4H 增强信息
- MACD_1H 趋势健康层（权重15%）→ 判断方向一致性与趋势状态
- RSI 节奏层（权重25%）→ 负责 4H/1H/15m 共振、尾段风险与节奏敏捷性
- VWAP 价值过滤层（权重10%）→ 判断多空偏向，偏离过滤
- 成交量确认（权重10%）→ 入场质量验证

扫描周期：每15分钟
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging
import numpy as np


logger = logging.getLogger(__name__)


DEFAULT_COMPETITION_CLUSTER_BONUS_MAP = {
    "flip_bullish": 0.12,
}


class VetoType(Enum):
    """否决类型"""
    NONE = "none"
    VWAP_HARD_BLOCK = "vwap_hard_block"  # VWAP偏离超过3%
    VWAP_SCORE_FILTER = "vwap_score_filter"  # VWAP评分低于入场阈值
    VWAP_MISSING_HARD_BLOCK = "vwap_missing_hard_block"  # 缺少VWAP数据时禁止入场
    VWAP_OPPOSITE_DAYS = "vwap_opposite_days"  # VWAP方向连续相反
    EMA_1H_BREAK = "ema_1h_break"  # 兼容旧枚举值：1H跌破/突破BOLL中轨
    EMA_4H_REVERSE = "ema_4h_reverse"  # 兼容旧枚举值：4H结构完全反向
    MACD_HIGH_DEVIATION = "macd_high_deviation"  # 兼容旧枚举值：MACD翻色时价格远离BOLL中轨
    VOLUME_VWAP_BOTH_LOW = "volume_vwap_both_low"  # 量价双低
    WEAK_SIGNAL_COMBO = "weak_combo_veto"  # 1H shrinking + 15m soft_* 弱组合
    SHORT_QUALITY_FILTER = "short_quality_filter"  # 空头质量过滤（V3专家组建议）
    CVD_CONTINUATION_RISK = "cvd_continuation_risk"  # session-reset CVD 显示短线买盘延续风险
    RESONANCE_GATE = "resonance_gate"  # MACD+EMA+RSI 非VWAP谐振门


@dataclass
class MACDStrategyV2Config:
    """MACD策略V2.0配置"""
    # MACD参数
    macd_1h_fast: int = 12
    macd_1h_slow: int = 26
    macd_1h_signal: int = 9
    macd_4h_fast: int = 12
    macd_4h_slow: int = 26
    macd_4h_signal: int = 9
    macd_15m_fast: int = 12
    macd_15m_slow: int = 26
    macd_15m_signal: int = 9
    macd_threshold: float = 0.00005
    
    # BOLL参数
    boll_period: int = 20
    boll_std_dev: float = 2.0
    ema_multiplier_strong: float = 1.2
    ema_multiplier_normal: float = 1.0
    ema_multiplier_weak: float = 0.6
    ema_55_1h_hard_block: bool = True  # 兼容旧配置：等价于1H跌破/突破BOLL中轨硬性否决
    
    # VWAP参数
    vwap_deviation_optimal: float = 0.005  # 最优偏离区间 ±0.5%
    vwap_deviation_warning: float = 0.015  # 警告偏离 ±1.5%
    vwap_deviation_hard_block: float = 0.030  # 硬性否决偏离 ±3.0%
    structural_vwap_mode: str = "anchored_weekly"
    structural_vwap_rolling_window: int = 20
    vwap_retest_tolerance: float = 0.003
    
    # 评分权重
    weight_1h_direction: float = 0.15  # 1H趋势健康评分权重
    weight_4h_direction: float = 0.40  # 4H主趋势评分权重
    weight_4h_enhancement: float = 0.10  # 兼容旧配置：运行时折叠进 4H 主方向
    weight_rsi_rhythm: float = 0.30  # RSI节奏评分权重
    weight_vwap: float = 0.05  # VWAP评分权重
    weight_15m_entry: float = 0.05
    weight_volume: float = 0.10  # 成交量确认评分权重
    
    # 入场阈值
    min_entry_score: float = 0.25  # 兼容旧配置：RSI rhythm 版本不再单独使用
    min_signal_score: float = 0.850
    red_bar_growing_min_signal_score: float = 0.900
    green_bar_growing_min_signal_score: float = 0.870
    flip_bearish_min_signal_score: float = 0.840
    flip_bullish_min_signal_score: float = 0.820
    soft_long_min_signal_score: float = 0.0
    primary_4h_long_without_1h_growth_min_signal_score: float = 0.0

    # 1H flip_bullish 严格过滤
    enable_flip_bullish_strict_filter: bool = True
    disable_flip_bullish_entries: bool = False
    flip_bullish_min_vwap_score: float = 0.12
    flip_bullish_require_pullback_bounce: bool = True
    flip_bullish_require_15m_growing: bool = True
    flip_bullish_no_momentum_reset_penalty: float = 0.06
    flip_bullish_spring_confirmation_bonus: float = 0.08
    flip_bullish_no_spring_penalty: float = 0.05
    enable_flip_bullish_cvd_context_filter: bool = False
    flip_bullish_max_cvd_upper_wick_ratio: float = 0.0
    flip_bullish_min_cvd_1h_delta_ratio: float = 0.0
    enable_flip_bullish_sniper: bool = True
    flip_bullish_require_momentum_reset: bool = True
    flip_bullish_momentum_reset_max_bars_ago: int = 12
    flip_bullish_require_spring_confirmation: bool = True
    flip_bullish_spring_min_rsi_low: float = 35.0
    flip_bullish_spring_require_price_break: bool = True
    flip_bullish_require_trend_alignment: bool = True
    flip_bullish_sniper_perfect_score_bonus: float = 0.08
    enable_flip_bullish_cooling: bool = True
    flip_bullish_cooling_reject_if_1h_rsi_above: float = 72.0
    flip_bullish_cooling_soft_rsi_above: float = 72.0
    flip_bullish_cooling_soft_discount: float = 0.90
    flip_bullish_cooling_hard_rsi_buffer: float = 3.0
    flip_bullish_cooling_reject_if_15m_no_spring_and_rsi_high: bool = True
    flip_bullish_cooling_reject_if_15m_rsi_above: float = 65.0
    flip_bearish_min_ema_multiplier: float = 0.0
    flip_bearish_normal_ema_min_signal_score: float = 0.0
    flip_bearish_normal_ema_max_leverage: int = 0
    flip_bearish_min_adx_1h: float = 18.0
    flip_bearish_retest_reject_min_vwap_score: float = 0.0
    flip_bearish_max_ema21_slope_1h: float = 0.0  # 兼容旧配置：等价于BOLL中轨斜率
    flip_bearish_max_ema21_slope_4h: float = 0.0001  # 兼容旧配置：等价于BOLL中轨斜率
    ema_slope_lookback_1h: int = 3  # 兼容旧配置：等价于BOLL中轨斜率lookback
    ema_slope_lookback_4h: int = 2  # 兼容旧配置：等价于BOLL中轨斜率lookback
    disable_red_bar_growing_long_entries: bool = False
    disable_green_bar_growing_entries: bool = True
    disable_green_bar_shrinking_short_dual_pressure_entries: bool = True
    disable_red_bar_shrinking_long_dual_support_entries: bool = True
    primary_direction_timeframe: str = "4h"  # 默认使用4H主趋势，兼容旧配置时可显式切回1h
    require_1h_confirmation_when_4h_primary: bool = False
    allow_neutral_1h_confirmation: bool = False
    light_1h_confirmation_when_4h_primary: bool = False
    enable_soft_15m_confirmation_when_4h_primary: bool = True  # 兼容旧配置：运行时忽略
    enable_weak_combo_veto: bool = True  # 兼容旧配置：soft_* 路径退役后忽略
    soft_15m_entry_score: float = 0.28  # 兼容旧配置：运行时忽略
    soft_15m_neutral_hist_multiple: float = 3.0  # 兼容旧配置：运行时忽略
    soft_15m_max_adverse_hist_multiple: float = 8.0  # 兼容旧配置：运行时忽略
    enable_rsi_entry_refinement: bool = True  # 兼容旧配置：运行时忽略
    rsi_period: int = 14
    enable_priority_execution: bool = True
    priority_exec_min_score: float = 0.90
    priority_exec_expire_seconds: int = 15
    priority_exec_vip_min_score: float = 0.92
    priority_exec_vip_expire_seconds: int = 30
    priority_exec_vip_allow_retry: bool = True
    competition_ranking_enabled: bool = False
    competition_cluster_bonus_map: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COMPETITION_CLUSTER_BONUS_MAP))
    entry_market_fallback_min_score: float = 0.68
    entry_market_fallback_timeout_ms: int = 2000
    entry_market_fallback_max_slippage_bps: int = 5
    enable_vwap_flip_exemption: bool = True
    enable_neutral_upgrade: bool = True
    neutral_upgrade_min_rsi_score: float = 0.35
    neutral_upgrade_probe_rsi_score: float = 0.20
    neutral_upgrade_probe_threshold_score: float = 0.82
    neutral_upgrade_penalty_mult: float = 0.90
    enable_rsi_rhythm_scoring: bool = True
    enable_rsi_hard_veto: bool = True
    enable_leading_rsi_conflict_pass: bool = True
    leading_rsi_slope_threshold: float = 2.0
    rsi_conflict_penalty_mult: float = 0.95
    rsi_conflict_threshold: float = 0.20
    rsi_leading_conflict_portion_mult: float = 0.80
    rsi_divergence_conflict_portion_mult: float = 0.85
    rsi_rhythm_high_score_min: float = 0.30
    rsi_rhythm_block_score: float = -0.30
    rsi_probe_exposure_mult: float = 0.20
    rsi_probe_portion_scale: float = 0.25
    rsi_probe_forced_leverage: int = 2
    short_rsi_probe_only_below: float = 40.0
    enable_15m_spring_threshold_override: bool = True
    spring_override_min_signal_score: float = 0.82
    spring_override_score_bonus: float = 0.10
    enable_priority_allocation: bool = True
    priority_allocation_overdraft_pct: float = 0.08
    enable_red_bar_growing_probe_overlay: bool = False
    red_bar_growing_probe_position_penalty: float = 0.50
    red_bar_growing_probe_max_leverage: int = 2
    enable_green_bar_growing_probe_overlay: bool = True
    green_bar_growing_probe_position_penalty: float = 0.10
    green_bar_growing_probe_max_leverage: int = 2
    rsi_4h_long_support: float = 55.0
    rsi_4h_short_support: float = 45.0
    rsi_4h_long_against: float = 40.0
    rsi_4h_short_against: float = 60.0
    rsi_1h_launch_slope: float = 1.5
    rsi_1h_trend_long_min: float = 55.0
    rsi_1h_trend_long_max: float = 70.0
    rsi_1h_trend_short_min: float = 30.0
    rsi_1h_trend_short_max: float = 45.0
    rsi_1h_extreme_long: float = 75.0
    rsi_1h_extreme_short: float = 25.0
    rsi_1h_extreme_flat_slope_max: float = 0.5
    rsi_1h_relaunch_lookback: int = 5
    rsi_1h_relaunch_long_floor: float = 40.0
    rsi_1h_relaunch_short_ceiling: float = 60.0
    rsi_15m_spring_lookback: int = 5
    rsi_15m_spring_long_extreme: float = 35.0
    rsi_15m_spring_short_extreme: float = 65.0
    rsi_15m_extreme_long_veto: float = 75.0
    rsi_15m_extreme_short_veto: float = 25.0
    rsi_15m_neutral_low: float = 45.0
    rsi_15m_neutral_high: float = 55.0
    rsi_spring_recent_extreme_lookback: int = 6
    rsi_spring_recent_oversold: float = 40.0
    rsi_spring_recent_overbought: float = 60.0
    rsi_spring_prev_max: float = 50.0
    rsi_spring_confirm: float = 50.0
    rsi_1h_long_support: float = 52.0
    rsi_1h_short_support: float = 48.0
    rsi_extension_penalty_threshold_long: float = 62.0
    rsi_extension_penalty_threshold_short: float = 38.0
    rsi_extension_penalty_multiplier: float = 0.60
    enable_rsi_launch_sovereign_mode: bool = True
    rsi_launch_sovereign_score_bonus: float = 0.12
    rsi_launch_sovereign_min_signal_score: float = 0.80
    rsi_launch_sovereign_competition_multiplier: float = 1.15
    rsi_launch_sovereign_reset_lookback: int = 12
    rsi_launch_sovereign_long_reset_ceiling: float = 45.0
    rsi_launch_sovereign_short_reset_floor: float = 55.0
    rsi_launch_sovereign_long_4h_rsi_min: float = 50.0
    rsi_launch_sovereign_short_4h_rsi_max: float = 50.0
    rsi_launch_sovereign_long_1h_rsi_max: float = 78.0
    rsi_launch_sovereign_short_1h_rsi_min: float = 22.0
    rsi_launch_sovereign_priority_expire_seconds: int = 30
    rsi_launch_sovereign_allow_retry: bool = True
    enable_green_bar_growing_short_adx_1h_range_filter: bool = False
    green_bar_growing_short_min_adx_1h: float = 0.0
    green_bar_growing_short_max_adx_1h: float = 0.0
    enable_4h_preflip_trial_entries: bool = False
    preflip_trial_min_shrink_pct_long: float = 0.75
    preflip_trial_min_shrink_pct_short: float = 0.30
    preflip_trial_min_signal_score: float = 0.78
    preflip_trial_min_vwap_score: float = 0.06
    preflip_trial_entry_scale: float = 0.35
    preflip_trial_max_leverage: int = 2
    short_min_vwap_score_for_entry: float = 0.06
    flip_bearish_short_min_vwap_score_for_entry: float = 0.08
    flip_bearish_require_enhancement_or_15m_confirmation: bool = True
    enable_trial_short_below_structure_continuation_promotion: bool = False
    trial_short_below_structure_promotion_min_signal_score: float = 0.82
    trial_short_below_structure_promotion_min_vwap_score: float = 0.075
    trial_short_below_structure_promotion_min_adx_1h: float = 25.0
    trial_short_below_structure_promotion_min_4h_shrink_pct: float = 0.80
    trial_short_below_structure_promotion_min_4h_shrink_bars: int = 6
    enable_stable_bear_continuation: bool = True
    stable_bear_continuation_min_signal_score: float = 0.82
    stable_bear_continuation_min_vwap_score: float = 0.10
    stable_bear_continuation_min_adx_1h: float = 20.0
    stable_bear_continuation_min_4h_bars: int = 2
    enable_stable_bull_continuation: bool = False
    stable_bull_continuation_min_signal_score: float = 0.82
    stable_bull_continuation_min_vwap_score: float = 0.10
    stable_bull_continuation_min_adx_1h: float = 20.0
    stable_bull_continuation_min_4h_bars: int = 2
    enable_stable_continuation_slow_4h_shrink_exit: bool = True
    stable_continuation_exit_4h_shrink_bars: int = 3
    stable_continuation_exit_4h_min_shrink_pct: float = 0.35
    enable_4h_shrink_exit: bool = False
    exit_4h_shrink_bars: int = 2
    exit_4h_min_shrink_pct: float = 0.20
    enable_priority_signal_shrink_exit: bool = True
    priority_signal_shrink_exit_required_bars: int = 3
    priority_signal_shrink_exit_required_pct: float = 0.40
    enable_macd_1h_flip_exit: bool = False
    macd_1h_flip_exit_confirm_bars: int = 2
    macd_1h_flip_exit_min_magnitude: float = 0.0003
    macd_1h_flip_exit_min_profit_to_exit: float = 0.006
    enable_rsi_overheat_exit: bool = False
    rsi_overheat_exit_threshold: float = 78.0
    rsi_overheat_exit_min_mfe: float = 0.012
    rsi_overheat_exit_partial_ratio: float = 0.50
    enable_holding_time_exit: bool = False
    holding_time_exit_max_hours: float = 96.0
    holding_time_exit_min_pnl_to_hold: float = 0.005
    exit_4h_require_profit: bool = True
    exit_4h_weak_loss_threshold: float = -1.0
    session_risk_control_enabled: bool = False
    session_risk_high_risk_sessions: List[Dict[str, Any]] = field(default_factory=list)
    session_risk_apply_to_states: List[str] = field(default_factory=list)
    vwap_score_tier_apply_to_states: List[str] = field(default_factory=list)
    vwap_score_position_tiers: List[Dict[str, Any]] = field(default_factory=list)
    symbol_risk_watchlist_symbols: List[str] = field(default_factory=list)
    symbol_risk_watchlist_max_position_portion: float = 0.0
    symbol_risk_watchlist_max_leverage: int = 0
    symbol_risk_watchlist_apply_session_scale_double: bool = False
    symbol_risk_watchlist_session_scale_multiplier: float = 0.80
    symbol_risk_max_stop_loss_pct_by_symbol: Dict[str, float] = field(default_factory=dict)
    vol_vwap_warn_position_scale: float = 0.50

    # 过热惩罚
    overheat_growing_penalty: float = 0.12
    overheat_ema_multiplier_threshold: float = 1.2
    overheat_vwap_score_threshold: float = 0.10
    min_vwap_score_for_entry: float = 0.10  # VWAP全局过滤
    vol_vwap_warn_min_score_vol: float = 0.05
    vol_vwap_warn_min_vwap_score: float = 0.10
    require_vwap_for_entry: bool = False
    
    # 止损配置
    use_dynamic_stop: bool = True
    ema_stop_atr_multiplier: float = 0.5
    max_stop_loss_pct: float = 0.025
    vwap_alert_deviation: float = 0.005

    # BOLL强趋势处理（新增）
    ema_strong_trend_leverage_mult: float = 0.8  # 强趋势时杠杆降低20%
    dual_pressure_target_portion_bonus: float = 0.0
    dual_pressure_max_symbol_position_portion: float = 0.0
    use_cvd_bonus_filter: bool = False
    cvd_1h_slope_lookback: int = 3
    cvd_15m_slope_lookback: int = 3
    cvd_positive_delta_ratio_threshold: float = 0.05
    cvd_negative_delta_ratio_threshold: float = -0.05
    cvd_bullish_bonus_multiplier: float = 0.0
    cvd_neutral_bonus_multiplier: float = 0.7
    cvd_bearish_bonus_multiplier: float = 1.0
    use_cvd_veto_filter: bool = False
    cvd_veto_session_reset: str = "daily_utc0"
    cvd_veto_lookback_15m: int = 3
    cvd_veto_positive_delta_ratio_threshold: float = 0.10
    cvd_veto_positive_pressure_threshold: float = 0.0
    cvd_veto_session_ratio_change_threshold: float = -0.003
    cvd_veto_session_price_change_threshold: float = -0.005
    cvd_veto_strong_close_pos_threshold: float = 0.72
    cvd_veto_upper_wick_ratio_max: float = 0.25
    cvd_absorption_delta_ratio_threshold: float = 0.05
    cvd_absorption_close_pos_threshold: float = 0.45
    cvd_absorption_upper_wick_ratio_threshold: float = 0.35
    cvd_absorption_structure_gap_threshold: float = 0.002
    cvd_divergence_price_change_threshold: float = 0.003
    cvd_divergence_session_change_threshold: float = -0.005
    
    # 空头质量过滤器（V3专家组建议）
    enable_short_quality_filter: bool = True  # 启用空头质量过滤
    flip_bearish_independent_short_quality_filter_enabled: bool = False
    short_filter_min_funding_rate: float = 0.0005  # funding_rate > 0.05%
    short_filter_max_oi_delta_ratio: float = 0.0  # oi_delta_ratio < 0 (多头减仓)
    short_filter_min_vwap_deviation: float = 0.005  # price > vwap * 1.005

    # MACD+EMA+RSI 谐振门（VWAP移除候选C）
    resonance_gate_enabled: bool = False
    resonance_long_rsi_rhythm_min: float = 0.35
    resonance_short_rsi_rhythm_min: float = 0.35
    flip_bearish_resonance_rsi_rhythm_min: float = 0.40
    flip_bullish_resonance_rsi_rhythm_min: float = 0.30
    trial_resonance_rsi_rhythm_min: float = 0.30
    resonance_require_ema_not_against: bool = True
    resonance_require_4h_align: bool = True
    resonance_volume_warn_ratio: float = 0.80
    resonance_volume_warn_position_scale: float = 0.50
    structural_vwap_telemetry_position_scale_threshold: float = 0.05
    structural_vwap_telemetry_position_scale: float = 0.70

    def resolve_signal_score_threshold(
        self,
        signal_type_1h: Optional[str],
        stable_continuation_side: Optional[str] = None,
    ) -> float:
        continuation_side = str(stable_continuation_side or "").strip().lower()
        if continuation_side == "short" and self.enable_stable_bear_continuation:
            threshold = float(self.stable_bear_continuation_min_signal_score)
            if threshold > 0:
                return threshold
        if continuation_side == "long" and self.enable_stable_bull_continuation:
            threshold = float(self.stable_bull_continuation_min_signal_score)
            if threshold > 0:
                return threshold
        signal_type = str(signal_type_1h or "").strip().lower()
        thresholds = {
            "red_bar_growing": self.red_bar_growing_min_signal_score,
            "green_bar_growing": self.green_bar_growing_min_signal_score,
            "flip_bearish": self.flip_bearish_min_signal_score,
            "flip_bullish": self.flip_bullish_min_signal_score,
        }
        threshold = thresholds.get(signal_type)
        if threshold is None or threshold <= 0:
            return self.min_signal_score
        return threshold

    def resolve_entry_threshold(
        self,
        *,
        signal_type: Optional[str],
        signal_type_1h: Optional[str] = None,
        trade_direction: Optional[str] = None,
        entry_type_15m: Optional[str],
        primary_mode: str,
        is_trial_entry: bool,
        stable_continuation_active: bool,
        stable_continuation_side: Optional[str],
    ) -> Tuple[float, str]:
        threshold_source = "signal_type_1h_default"
        threshold = self.resolve_signal_score_threshold(
            signal_type,
            stable_continuation_side=stable_continuation_side if stable_continuation_active else None,
        )

        if stable_continuation_active and stable_continuation_side:
            threshold_source = f"stable_continuation_{stable_continuation_side}"
        elif primary_mode == "4h":
            threshold_source = f"primary_4h_{str(signal_type or 'default').strip().lower()}"
        elif signal_type:
            threshold_source = f"signal_type_1h_{str(signal_type).strip().lower()}"

        if is_trial_entry and not stable_continuation_active:
            return float(self.preflip_trial_min_signal_score), "preflip_trial"

        soft_long_threshold = float(self.soft_long_min_signal_score or 0.0)
        entry_type = str(entry_type_15m or "").strip().lower()
        if (
            primary_mode == "4h"
            and not stable_continuation_active
            and entry_type.startswith("soft_long_")
            and soft_long_threshold > 0
            and threshold > soft_long_threshold
        ):
            threshold = soft_long_threshold
            threshold_source = f"soft_long_override({threshold_source})"

        primary_4h_weak_1h_threshold = float(
            self.primary_4h_long_without_1h_growth_min_signal_score or 0.0
        )
        if (
            primary_mode == "4h"
            and not stable_continuation_active
            and not is_trial_entry
            and str(trade_direction or "").strip().lower() == "long"
            and signal_type == "red_bar_growing"
            and str(signal_type_1h or "").strip().lower() != "red_bar_growing"
            and primary_4h_weak_1h_threshold > threshold
        ):
            threshold = primary_4h_weak_1h_threshold
            threshold_source = f"primary_4h_long_without_1h_growth({threshold_source})"

        return threshold, threshold_source

    def resolve_competition_score(
        self,
        signal_type_1h: Optional[str],
        signal_score: float,
        entry_type_15m: Optional[str] = None,
    ) -> float:
        score = float(signal_score or 0.0)
        signal_type = str(signal_type_1h or "").strip().lower()
        if self.competition_ranking_enabled:
            bonus_map = self.competition_cluster_bonus_map or {}
            if signal_type in bonus_map:
                return score + float(bonus_map.get(signal_type, 0.0) or 0.0)
            return score
        if signal_type == "flip_bullish":
            multiplier = 1.10
            if str(entry_type_15m or "").strip().lower() in {"rsi_spring", "rsi_neutral_resume"}:
                multiplier += 0.05
            return score * multiplier
        return score

    def is_flip_bearish_normal_ema(self, signal_type_1h: Optional[str], ema_multiplier: float) -> bool:
        if str(signal_type_1h or "").strip().lower() != "flip_bearish":
            return False
        return abs(float(ema_multiplier) - float(self.ema_multiplier_normal)) < 1e-9

@dataclass
class MACDSignalV2:
    """MACD信号V2.0"""
    direction: str  # 'long', 'short', 'neutral'
    signal_score: float  # 0-1
    signal_type_1h: Optional[str] = None
    signal_strength_1h: float = 0.0
    is_4h_enhanced: bool = False
    enhancement_score: float = 0.0
    entry_type_15m: Optional[str] = None
    entry_score_15m: float = 0.0
    
    # V2.0 新增字段
    vwap_score: float = 0.0
    vwap_deviation: float = 0.0
    vwap_state: str = "unknown"
    vwap_location_score: float = 0.0
    ema_multiplier: float = 1.0
    ema_structure_status: str = "normal"  # strong/normal/weak/against
    
    # 否决信息
    veto_type: VetoType = VetoType.NONE
    veto_reason: str = ""
    
    # 止损信息
    suggested_stop_price: Optional[float] = None
    stop_loss_pct: float = 0.02
    is_trial_entry: bool = False
    entry_scale: float = 1.0

    details: Dict = field(default_factory=dict)


class MACDStrategyV2Engine:
    """MACD策略V2.0引擎"""
    
    def __init__(self, config: MACDStrategyV2Config = None):
        self.config = config or MACDStrategyV2Config()
        self._last_analysis: Dict = {}

    def _build_debug_details(self, **kwargs: Any) -> Dict[str, Any]:
        details = dict(kwargs)
        details["stage_path"] = self._normalize_stage_path(details.get("stage_path"))
        stage = str(details.get("stage") or "").strip()
        if stage and (not details["stage_path"] or details["stage_path"][-1] != stage):
            details["stage_path"].append(stage)
        details["stage_path_text"] = " > ".join(details["stage_path"]) if details["stage_path"] else ""
        details["min_signal_score"] = self.config.min_signal_score
        details["min_entry_score"] = self.config.min_entry_score
        details.setdefault("min_vwap_score_for_entry", self.config.min_vwap_score_for_entry)
        return details

    def _should_apply_short_quality_filter(
        self,
        signal_type_1h: Optional[str],
        *,
        strict_1h_filters_enabled: bool,
    ) -> bool:
        if not strict_1h_filters_enabled:
            return False
        if str(signal_type_1h or "").strip().lower() != "flip_bearish":
            return False
        return bool(
            self.config.enable_short_quality_filter
            or self.config.flip_bearish_independent_short_quality_filter_enabled
        )

    def _check_resonance_gate(
        self,
        *,
        signal_type_1h: Optional[str],
        trade_direction: Optional[str],
        is_trial_entry: bool,
        direction_4h: Optional[str],
        signal_type_4h: Optional[str],
        direction_1h: Optional[str],
        entry_type_15m: Optional[str],
        ema_status: Optional[str],
        rsi_rhythm: Optional[Dict[str, Any]],
        rsi_conflict_type: Optional[str],
        adx_1h: float,
        is_4h_enhanced: bool,
        funding_rate: float,
        oi_delta_ratio: float,
        volume_ratio: float,
        structural_vwap_deviation: float = 0.0,
    ) -> Dict[str, Any]:
        direction = str(trade_direction or "").strip().lower()
        signal_type = str(signal_type_1h or "").strip().lower()
        dir_4h = str(direction_4h or "").strip().lower()
        dir_1h = str(direction_1h or "").strip().lower()
        entry_15m = str(entry_type_15m or "").strip().lower()
        ema = str(ema_status or "").strip().lower()
        rhythm = rsi_rhythm or {}
        raw_rsi = float(rhythm.get("raw_score", 0.0) or 0.0)
        conflict = str(rsi_conflict_type or rhythm.get("veto_reason") or "").strip().lower()
        scale = 1.0
        volume_warn = False
        vwap_telemetry_warn = False

        structural_dev = float(structural_vwap_deviation or 0.0)
        if (
            float(self.config.structural_vwap_telemetry_position_scale_threshold) > 0
            and abs(structural_dev) > float(self.config.structural_vwap_telemetry_position_scale_threshold)
        ):
            scale *= max(0.0, min(1.0, float(self.config.structural_vwap_telemetry_position_scale)))
            vwap_telemetry_warn = True

        if (
            float(self.config.resonance_volume_warn_ratio) > 0
            and float(volume_ratio or 0.0) < float(self.config.resonance_volume_warn_ratio)
        ):
            scale *= max(0.0, min(1.0, float(self.config.resonance_volume_warn_position_scale)))
            volume_warn = True

        def blocked(reason: str) -> Dict[str, Any]:
            return {
                "passed": False,
                "reason": reason,
                "position_scale": 0.0,
                "volume_warn": volume_warn,
                "vwap_telemetry_warn": vwap_telemetry_warn,
            }

        def passed(reason: str) -> Dict[str, Any]:
            return {
                "passed": True,
                "reason": reason,
                "position_scale": scale,
                "volume_warn": volume_warn,
                "vwap_telemetry_warn": vwap_telemetry_warn,
            }

        if self.config.resonance_require_ema_not_against and ema == "against":
            if is_trial_entry:
                return blocked("trial_resonance_ema_against")
            if signal_type == "flip_bearish" and direction == "short":
                return blocked("flip_bearish_resonance_ema_against")
            if signal_type == "flip_bullish" and direction == "long":
                return blocked("flip_bullish_resonance_ema_against")
            return blocked(f"resonance_gate_{direction}_ema_against")

        if is_trial_entry:
            if raw_rsi < float(self.config.trial_resonance_rsi_rhythm_min):
                return blocked("trial_resonance_rsi_fail")
            return passed("trial_resonance_gate_pass")

        if signal_type == "flip_bearish" and direction == "short":
            min_flip_bearish_adx = max(30.0, float(self.config.flip_bearish_min_adx_1h))
            if float(adx_1h or 0.0) < min_flip_bearish_adx:
                return blocked("flip_bearish_resonance_adx_fail")
            if self.config.resonance_require_4h_align and dir_4h != "short":
                return blocked("flip_bearish_resonance_4h_fail")
            if (
                self.config.flip_bearish_require_enhancement_or_15m_confirmation
                and not bool(is_4h_enhanced)
                and entry_15m not in {"green_bar_growing", "flip_bearish", "rsi_spring", "rsi_neutral_resume"}
            ):
                return blocked("flip_bearish_resonance_confirmation_fail")
            if raw_rsi < float(self.config.flip_bearish_resonance_rsi_rhythm_min):
                return blocked("flip_bearish_resonance_rsi_fail")
            if conflict in {"divergence", "extreme_oppose", "rebound_conflict", "spring_conflict"}:
                return blocked("flip_bearish_resonance_rsi_conflict")
            if float(funding_rate or 0.0) <= float(self.config.short_filter_min_funding_rate):
                return blocked("flip_bearish_resonance_funding_fail")
            if float(oi_delta_ratio or 0.0) >= float(self.config.short_filter_max_oi_delta_ratio):
                return blocked("flip_bearish_resonance_oi_fail")
            return passed("flip_bearish_resonance_pass")

        if signal_type == "flip_bullish" and direction == "long":
            if self.config.resonance_require_4h_align and dir_4h != "long":
                return blocked("flip_bullish_resonance_4h_fail")
            if raw_rsi < float(self.config.flip_bullish_resonance_rsi_rhythm_min):
                return blocked("flip_bullish_resonance_rsi_fail")
            if conflict in {"divergence", "extreme_oppose", "late_overheat"}:
                return blocked("flip_bullish_resonance_rsi_conflict")
            return passed("flip_bullish_resonance_pass")

        if direction == "long":
            if self.config.resonance_require_4h_align and dir_4h != "long":
                return blocked("resonance_gate_long_4h_fail")
            if dir_1h not in {"long", "neutral", ""}:
                return blocked("resonance_gate_long_1h_fail")
            if raw_rsi < float(self.config.resonance_long_rsi_rhythm_min):
                return blocked("resonance_gate_long_rsi_fail")
            if conflict in {"divergence", "extreme_oppose", "late_overheat"}:
                return blocked("resonance_gate_long_rsi_conflict")
            return passed("resonance_gate_long_pass")

        if direction == "short":
            if self.config.resonance_require_4h_align and dir_4h != "short":
                return blocked("resonance_gate_short_4h_fail")
            if dir_1h not in {"short", "neutral", ""}:
                return blocked("resonance_gate_short_1h_fail")
            if raw_rsi < float(self.config.resonance_short_rsi_rhythm_min):
                return blocked("resonance_gate_short_rsi_fail")
            if conflict in {"divergence", "extreme_oppose", "rebound_conflict", "spring_conflict"}:
                return blocked("resonance_gate_short_rsi_conflict")
            return passed("resonance_gate_short_pass")

        return blocked("resonance_gate_unknown_direction")

    @staticmethod
    def _normalize_stage_path(stage_path: Any) -> List[str]:
        if isinstance(stage_path, list):
            seen: List[str] = []
            for item in stage_path:
                stage = str(item or "").strip()
                if stage and (not seen or seen[-1] != stage):
                    seen.append(stage)
            return seen
        return []

    def _set_stage(self, details: Dict[str, Any], stage: str, **extra: Any) -> Dict[str, Any]:
        payload = dict(details or {})
        normalized = self._normalize_stage_path(payload.get("stage_path"))
        stage_name = str(stage or "").strip()
        if stage_name and (not normalized or normalized[-1] != stage_name):
            normalized.append(stage_name)
        payload["stage"] = stage_name
        payload["stage_path"] = normalized
        payload["stage_path_text"] = " > ".join(normalized) if normalized else ""
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _extract_reject_reason_metadata(reason: str) -> Tuple[str, str]:
        text = str(reason or "").strip()
        if not text:
            return "unknown_reject", ""
        open_idx = text.find("(")
        close_idx = text.rfind(")")
        if open_idx > 0 and close_idx > open_idx:
            return text[:open_idx].strip(), text[open_idx + 1:close_idx].strip()
        if ":" in text:
            code, detail = text.split(":", 1)
            return code.strip(), detail.strip()
        return text, ""

    def _default_rsi_launch_sovereign_details(self) -> Dict[str, Any]:
        return {
            "rsi_launch_sovereign_applies": False,
            "rsi_launch_sovereign_applied": False,
            "rsi_launch_sovereign_active": False,
            "rsi_launch_sovereign_direction": "",
            "rsi_launch_sovereign_side": "",
            "rsi_launch_sovereign_reason": "inactive",
            "rsi_launch_sovereign_score_bonus": 0.0,
            "rsi_launch_sovereign_threshold_override": 0.0,
            "rsi_launch_sovereign_competition_multiplier": 1.0,
            "rsi_launch_sovereign_force_priority_execution": False,
            "rsi_launch_sovereign_price_break_confirmed": False,
            "rsi_launch_sovereign_momentum_reset_found": False,
            "rsi_launch_sovereign_background_aligned": False,
            "rsi_launch_sovereign_non_overheated": False,
            "rsi_launch_sovereign_conflict_override": False,
        }

    def resolve_competition_score(
        self,
        signal_score: float,
        *,
        rsi_launch_sovereign_applied: bool = False,
    ) -> float:
        base_score = max(0.0, float(signal_score))
        if rsi_launch_sovereign_applied:
            return base_score * float(self.config.rsi_launch_sovereign_competition_multiplier)
        return base_score

    def _neutral_signal(
        self,
        *,
        reason: str,
        score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
        veto_type: VetoType = VetoType.NONE,
        veto_reason: str = "",
        signal_type_1h: Optional[str] = None,
        entry_type_15m: Optional[str] = None,
        entry_score_15m: float = 0.0,
        vwap_score: float = 0.0,
        vwap_deviation: float = 0.0,
        vwap_state: str = "unknown",
        vwap_location_score: float = 0.0,
        ema_multiplier: float = 1.0,
        ema_structure_status: str = "normal",
        enhancement_score: float = 0.0,
        is_4h_enhanced: bool = False,
        is_trial_entry: bool = False,
        entry_scale: float = 1.0,
    ) -> MACDSignalV2:
        payload = dict(details or {})
        sovereign_defaults = self._default_rsi_launch_sovereign_details()
        for key, value in sovereign_defaults.items():
            payload.setdefault(key, value)
        payload["reason"] = reason
        payload["reject_stage"] = payload.get("stage") or "unknown"
        reject_code, reject_detail = self._extract_reject_reason_metadata(reason)
        payload["reject_reason_code"] = reject_code
        payload["reject_reason_detail"] = reject_detail
        payload["final_block_reason"] = veto_reason or reject_code or reason
        payload["neutral_upgrade_considered"] = bool(payload.get("neutral_upgrade_considered", False))
        payload["neutral_upgrade_applied"] = bool(payload.get("neutral_upgrade_applied", False))
        payload["neutral_upgrade_penalty_mult"] = float(payload.get("neutral_upgrade_penalty_mult", 1.0) or 1.0)
        payload["neutral_original_reason"] = str(payload.get("neutral_original_reason") or "")
        payload["priority_signal"] = bool(payload.get("priority_signal", False))
        payload["priority_execution_applied"] = bool(payload.get("priority_execution_applied", False))
        payload["rsi_probe_mode"] = bool(payload.get("rsi_probe_mode", False))
        payload["competition_score"] = float(payload.get("competition_score", self.config.resolve_competition_score(signal_type_1h, score, entry_type_15m)) or 0.0)
        if bool(payload.get("rsi_launch_sovereign_applied", False)):
            payload["competition_score"] = self.resolve_competition_score(
                payload["competition_score"],
                rsi_launch_sovereign_applied=True,
            )
        payload["stage_path"] = self._normalize_stage_path(payload.get("stage_path"))
        payload["stage_path_text"] = " > ".join(payload["stage_path"]) if payload["stage_path"] else ""
        payload.setdefault("priority_execution_tier", "")
        payload.setdefault("execution_route", "standard")
        payload.setdefault("entry_time_in_force", "IOC")
        payload.setdefault("entry_expire_seconds", 0)
        payload.setdefault("entry_price_mode", "ioc_limit")
        payload.setdefault("entry_retry_enabled", False)
        payload.setdefault("entry_retry_max_attempts", 0)
        payload.setdefault("entry_market_fallback_enabled", False)
        payload.setdefault("entry_market_fallback_timeout_ms", 0)
        payload.setdefault("entry_market_fallback_max_slippage_bps", 0)
        payload.setdefault("entry_execution_policy", "ioc")
        payload.setdefault("final_leverage_after_rsi", 1.0)
        payload.setdefault("final_portion_after_rsi", 1.0)
        if veto_type != VetoType.NONE and "veto_type" not in payload:
            payload["veto_type"] = veto_type.value
        self._last_analysis = payload.copy()
        return MACDSignalV2(
            direction='neutral',
            signal_score=score,
            signal_type_1h=signal_type_1h,
            is_4h_enhanced=is_4h_enhanced,
            enhancement_score=enhancement_score,
            entry_type_15m=entry_type_15m,
            entry_score_15m=entry_score_15m,
            vwap_score=vwap_score,
            vwap_deviation=vwap_deviation,
            vwap_state=vwap_state,
            vwap_location_score=vwap_location_score,
            ema_multiplier=ema_multiplier,
            ema_structure_status=ema_structure_status,
            veto_type=veto_type,
            veto_reason=veto_reason,
            is_trial_entry=is_trial_entry,
            entry_scale=entry_scale,
            details=payload,
        )
    
    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        multiplier = 2 / (period + 1)
        ema = np.zeros_like(prices, dtype=float)
        ema[0] = prices[0]
        for i in range(1, len(prices)):
            ema[i] = (prices[i] * multiplier) + (ema[i-1] * (1 - multiplier))
        return ema
    
    @staticmethod
    def calculate_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        """计算ATR"""
        tr = np.zeros(len(close))
        tr[0] = high[0] - low[0]
        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        atr = np.zeros(len(close))
        atr[:period] = np.mean(tr[:period])
        for i in range(period, len(close)):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
        return atr
    
    @staticmethod
    def calculate_macd(
        prices: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算MACD"""
        ema_fast = MACDStrategyV2Engine.calculate_ema(prices, fast)
        ema_slow = MACDStrategyV2Engine.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = MACDStrategyV2Engine.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_bollinger_bands(
        prices: np.ndarray,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算布林带（中轨/上轨/下轨）"""
        values = np.asarray(prices, dtype=float)
        middle = np.zeros_like(values, dtype=float)
        upper = np.zeros_like(values, dtype=float)
        lower = np.zeros_like(values, dtype=float)
        for i in range(len(values)):
            start = max(0, i - period + 1)
            window = values[start:i + 1]
            mid = float(np.mean(window))
            sigma = float(np.std(window))
            middle[i] = mid
            upper[i] = mid + sigma * std_dev
            lower[i] = mid - sigma * std_dev
        return middle, upper, lower

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))

    @staticmethod
    def _parse_hhmm_to_minutes(value: object) -> Optional[int]:
        text = str(value or "").strip()
        if not text or ":" not in text:
            return None
        hour_raw, minute_raw = text.split(":", 1)
        try:
            hour = int(hour_raw)
            minute = int(minute_raw)
        except (TypeError, ValueError):
            return None
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour * 60 + minute

    @staticmethod
    def _timestamp_to_utc_minutes(timestamp: object) -> Optional[int]:
        if timestamp is None:
            return None
        dt_obj: Optional[datetime] = None
        if isinstance(timestamp, datetime):
            dt_obj = timestamp
        elif hasattr(timestamp, "to_pydatetime"):
            try:
                dt_obj = timestamp.to_pydatetime()
            except Exception:
                dt_obj = None
        if dt_obj is None:
            hour = getattr(timestamp, "hour", None)
            minute = getattr(timestamp, "minute", None)
            if hour is None or minute is None:
                return None
            return int(hour) * 60 + int(minute)
        if dt_obj.tzinfo is not None:
            dt_obj = dt_obj.astimezone(timezone.utc)
        return int(dt_obj.hour) * 60 + int(dt_obj.minute)

    @staticmethod
    def _minute_in_window(current_minute: int, start_minute: int, end_minute: int) -> bool:
        if start_minute == end_minute:
            return True
        if start_minute < end_minute:
            return start_minute <= current_minute < end_minute
        return current_minute >= start_minute or current_minute < end_minute

    def resolve_session_position_scale(
        self,
        timestamp: object,
        signal_type_1h: Optional[str] = None,
        vwap_state: Optional[str] = None,
    ) -> float:
        if not bool(self.config.session_risk_control_enabled):
            return 1.0

        target_states = {
            str(state or "").strip().lower()
            for state in (self.config.session_risk_apply_to_states or [])
            if str(state or "").strip()
        }
        signal_state = str(signal_type_1h or "").strip().lower()
        vwap_state_norm = str(vwap_state or "").strip().lower()
        if target_states and signal_state not in target_states and vwap_state_norm not in target_states:
            return 1.0

        current_minute = self._timestamp_to_utc_minutes(timestamp)
        if current_minute is None:
            return 1.0

        matched_scale = 1.0
        for session in self.config.session_risk_high_risk_sessions or []:
            if not isinstance(session, dict):
                continue
            start_minute = self._parse_hhmm_to_minutes(session.get("utc_start"))
            end_minute = self._parse_hhmm_to_minutes(session.get("utc_end"))
            if start_minute is None or end_minute is None:
                continue
            if not self._minute_in_window(current_minute, start_minute, end_minute):
                continue
            scale = self._clamp(float(session.get("position_scale", 1.0) or 1.0), 0.05, 1.0)
            matched_scale = min(matched_scale, scale)
        return matched_scale

    @staticmethod
    def _normalize_symbol(symbol: object) -> str:
        return str(symbol or "").strip().upper()

    def is_watchlist_symbol(self, symbol: object) -> bool:
        symbol_up = self._normalize_symbol(symbol)
        if not symbol_up:
            return False
        watchlist = {
            self._normalize_symbol(item)
            for item in (self.config.symbol_risk_watchlist_symbols or [])
            if self._normalize_symbol(item)
        }
        return symbol_up in watchlist

    def resolve_symbol_risk_session_scale(
        self,
        symbol: object,
        session_scale: float,
    ) -> float:
        scale = self._clamp(session_scale, 0.05, 1.0)
        if not self.is_watchlist_symbol(symbol):
            return scale
        if self.config.symbol_risk_watchlist_apply_session_scale_double and scale < 0.999999:
            scale *= self._clamp(
                float(self.config.symbol_risk_watchlist_session_scale_multiplier or 1.0),
                0.05,
                1.0,
            )
        return self._clamp(scale, 0.05, 1.0)

    def resolve_symbol_max_stop_loss_pct(self, symbol: object) -> Tuple[float, bool]:
        global_max = max(0.0, float(self.config.max_stop_loss_pct or 0.0))
        symbol_up = self._normalize_symbol(symbol)
        if not symbol_up:
            return global_max, False

        raw_map = self.config.symbol_risk_max_stop_loss_pct_by_symbol or {}
        try:
            symbol_max = float(raw_map.get(symbol_up, 0.0) or 0.0)
        except (TypeError, ValueError):
            return global_max, False

        if symbol_max <= 0.0:
            return global_max, False
        effective = min(global_max, symbol_max) if global_max > 0 else symbol_max
        return effective, effective < global_max

    def resolve_vwap_score_position_multiplier(
        self,
        vwap_score: float,
        signal_type_1h: Optional[str] = None,
        vwap_state: Optional[str] = None,
    ) -> float:
        apply_states = {
            str(item or "").strip().lower()
            for item in (self.config.vwap_score_tier_apply_to_states or [])
            if str(item or "").strip()
        }
        signal_state = str(signal_type_1h or "").strip().lower()
        vwap_state_norm = str(vwap_state or "").strip().lower()
        if apply_states and signal_state not in apply_states and vwap_state_norm not in apply_states:
            return 1.0

        score = float(vwap_score or 0.0)
        for raw_tier in self.config.vwap_score_position_tiers or []:
            if not isinstance(raw_tier, dict):
                continue
            tier_min = float(raw_tier.get("min", 0.0) or 0.0)
            tier_max = float(raw_tier.get("max", 1.0) or 1.0)
            if tier_max <= tier_min:
                continue
            is_last = abs(tier_max - 1.0) < 1e-12 or tier_max >= 0.999999
            in_tier = (tier_min <= score <= tier_max) if is_last else (tier_min <= score < tier_max)
            if not in_tier:
                continue
            return self._clamp(float(raw_tier.get("position_mult", 1.0) or 1.0), 0.05, 1.5)
        return 1.0

    @classmethod
    def _normalized_change(cls, current: float, previous: float) -> float:
        if abs(previous) < 1e-12:
            return 0.0
        return cls._clamp((current - previous) / abs(previous), -1.0, 1.0)

    def _ema_slope_from_series(
        self,
        prices: Optional[np.ndarray],
        period: int,
        lookback: int,
    ) -> float:
        if prices is None:
            return 0.0
        values = np.asarray(prices, dtype=float)
        if len(values) < max(period + 1, lookback + 1):
            return 0.0
        ema_series = self.calculate_ema(values, period)
        current = float(ema_series[-1])
        previous = float(ema_series[-1 - lookback])
        return self._normalized_change(current, previous)

    def _boll_middle_slope_from_series(
        self,
        prices: Optional[np.ndarray],
        period: int,
        std_dev: float,
        lookback: int,
    ) -> float:
        if prices is None:
            return 0.0
        values = np.asarray(prices, dtype=float)
        if len(values) < max(period, lookback + 1):
            return 0.0
        middle, _, _ = self.calculate_bollinger_bands(values, period=period, std_dev=std_dev)
        current = float(middle[-1])
        previous = float(middle[-1 - lookback])
        return self._normalized_change(current, previous)

    @staticmethod
    def _series_value(series: Optional[np.ndarray], offset: int = -1, default: float = 0.0) -> float:
        if series is None:
            return default
        values = np.asarray(series, dtype=float)
        if values.size == 0:
            return default
        try:
            return float(values[offset])
        except (IndexError, ValueError, TypeError):
            return default

    @staticmethod
    def calculate_rsi_series(prices: Optional[np.ndarray], period: int = 14) -> np.ndarray:
        if prices is None:
            return np.array([], dtype=float)
        values = np.asarray(prices, dtype=float)
        if values.size < max(2, period + 1):
            return np.array([], dtype=float)

        deltas = np.diff(values)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        rsi = np.full(values.shape, np.nan, dtype=float)

        for idx in range(period, values.size):
            avg_gain = float(np.mean(gains[idx - period : idx]))
            avg_loss = float(np.mean(losses[idx - period : idx]))
            if avg_loss <= 1e-12:
                rsi[idx] = 100.0 if avg_gain > 1e-12 else 50.0
                continue
            rs = avg_gain / avg_loss
            rsi[idx] = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    @staticmethod
    def _finite_tail(values: np.ndarray, lookback: int) -> np.ndarray:
        if values.size == 0 or lookback <= 0:
            return np.array([], dtype=float)
        tail = values[-lookback:]
        return tail[np.isfinite(tail)]

    @staticmethod
    def _detect_rsi_divergence(
        *,
        direction: str,
        price_series: Optional[np.ndarray],
        rsi_series: Optional[np.ndarray],
        lookback: int = 4,
    ) -> bool:
        prices = np.asarray(price_series, dtype=float) if price_series is not None else np.array([], dtype=float)
        rsis = np.asarray(rsi_series, dtype=float) if rsi_series is not None else np.array([], dtype=float)
        if prices.size < lookback or rsis.size < lookback:
            return False

        price_tail = prices[-lookback:]
        rsi_tail = rsis[-lookback:]
        if not np.all(np.isfinite(price_tail)) or not np.all(np.isfinite(rsi_tail)):
            return False

        current_price = float(price_tail[-1])
        current_rsi = float(rsi_tail[-1])
        prev_prices = price_tail[:-1]
        prev_rsis = rsi_tail[:-1]

        if direction == "long":
            return current_price >= float(np.max(prev_prices)) and current_rsi < float(np.max(prev_rsis))
        if direction == "short":
            return current_price <= float(np.min(prev_prices)) and current_rsi > float(np.min(prev_rsis))
        return False

    @staticmethod
    def _resolve_rsi_exposure_multiplier(raw_score: float) -> float:
        if raw_score >= 0.30:
            return 1.2
        if raw_score >= 0.10:
            return 1.0
        if raw_score >= -0.10:
            return 0.8
        if raw_score >= -0.30:
            return 0.5
        return 0.2

    def _resolve_min_vwap_score_for_entry(
        self,
        *,
        trade_direction: Optional[str],
        signal_type_1h: Optional[str],
        is_trial_entry: bool,
    ) -> float:
        direction = str(trade_direction or "").strip().lower()
        signal_type = str(signal_type_1h or "").strip().lower()
        global_floor = max(0.0, float(self.config.min_vwap_score_for_entry))
        short_floor = max(global_floor, float(self.config.short_min_vwap_score_for_entry))

        if is_trial_entry:
            trial_floor = max(0.0, float(self.config.preflip_trial_min_vwap_score))
            if direction == "short":
                if signal_type == "flip_bearish":
                    return max(
                        trial_floor,
                        short_floor,
                        float(self.config.flip_bearish_short_min_vwap_score_for_entry),
                    )
                return max(trial_floor, short_floor)
            return max(trial_floor, global_floor)

        if direction == "long":
            if self.config.enable_vwap_flip_exemption and signal_type == "flip_bullish":
                return max(global_floor, float(self.config.flip_bullish_min_vwap_score))
            return global_floor

        if direction == "short":
            if signal_type == "flip_bearish":
                return max(short_floor, float(self.config.flip_bearish_short_min_vwap_score_for_entry))
            return short_floor

        if self.config.enable_vwap_flip_exemption and signal_type in {"flip_bullish", "flip_bearish"}:
            return short_floor if signal_type == "flip_bearish" else global_floor
        return global_floor

    @staticmethod
    def _resolve_priority_signal(signal_type_1h: Optional[str], vwap_state: Optional[str]) -> bool:
        signal_type = str(signal_type_1h or "").strip().lower()
        state = str(vwap_state or "").strip().lower()
        return (
            signal_type == "flip_bullish" and state == "long_dual_support"
        ) or (
            signal_type == "flip_bearish" and state == "short_dual_pressure"
        )

    def _is_red_bar_growing_probe_overlay(self, signal_type_1h: Optional[str]) -> bool:
        return bool(
            self.config.enable_red_bar_growing_probe_overlay
            and str(signal_type_1h or "").strip().lower() == "red_bar_growing"
        )

    def _is_green_bar_growing_probe_overlay(self, signal_type_1h: Optional[str]) -> bool:
        return bool(
            self.config.enable_green_bar_growing_probe_overlay
            and str(signal_type_1h or "").strip().lower() == "green_bar_growing"
        )

    def _has_meaningful_short_15m_confirmation(
        self,
        *,
        trade_direction: str,
        entry_type_15m: Optional[str],
        entry_score_15m: float,
    ) -> bool:
        if str(trade_direction or "").strip().lower() != "short":
            return False

        entry_type = str(entry_type_15m or "").strip().lower()
        if entry_type in {"flip_bearish", "green_bar_growing", "rsi_spring", "rsi_neutral_resume"}:
            return True
        return float(entry_score_15m or 0.0) > 0

    def _is_weak_signal_probe_overlay(self, signal_type_1h: Optional[str]) -> bool:
        return bool(
            self._is_red_bar_growing_probe_overlay(signal_type_1h)
            or self._is_green_bar_growing_probe_overlay(signal_type_1h)
        )

    def _resolve_effective_probe_mode(self, signal_type_1h: Optional[str], base_probe_mode: bool = False) -> bool:
        return bool(base_probe_mode or self._is_weak_signal_probe_overlay(signal_type_1h))

    def _evaluate_flip_bullish_sniper(
        self,
        *,
        signal_type_1h: Optional[str],
        trade_direction: Optional[str],
        rsi_rhythm: Optional[Dict[str, Any]],
        rsi_1h_series: Optional[np.ndarray],
        macd_hist_4h: Optional[np.ndarray],
        idx_4h: int,
    ) -> Dict[str, Any]:
        result = {
            "applies": False,
            "passed": True,
            "reason": "not_applicable",
            "bonus_score": 0.0,
            "momentum_reset_found": False,
            "spring_confirmed": False,
            "trend_aligned": False,
            "quality_matches": 0,
            "required_matches": 1,
        }
        if not self.config.enable_flip_bullish_sniper:
            return result
        if str(signal_type_1h or "").strip().lower() != "flip_bullish" or str(trade_direction or "").strip().lower() != "long":
            return result
        result["applies"] = True
        rhythm = rsi_rhythm or {}

        recent_1h = self._finite_tail(
            np.asarray(rsi_1h_series, dtype=float) if rsi_1h_series is not None else np.array([], dtype=float),
            max(1, int(self.config.flip_bullish_momentum_reset_max_bars_ago)),
        )
        momentum_reset_found = bool(
            recent_1h.size and float(np.min(recent_1h)) < 40.0
        ) if self.config.flip_bullish_require_momentum_reset else True
        result["momentum_reset_found"] = momentum_reset_found

        spring_confirmed = True
        if self.config.flip_bullish_require_spring_confirmation:
            spring_confirmed = False
            entry_type = str(rhythm.get("entry_type") or "").strip().lower()
            recent_low_15m = float(rhythm.get("rsi_15m_recent_low", np.nan) or np.nan)
            current_rsi_15m = float(rhythm.get("rsi_15m_current", np.nan) or np.nan)
            prev_rsi_15m = float(rhythm.get("rsi_15m_prev", np.nan) or np.nan)
            spring_min_rsi_low = float(self.config.flip_bullish_spring_min_rsi_low)
            spring_like = entry_type in {"rsi_spring", "rsi_neutral_resume"}
            if entry_type == "rsi_spring":
                spring_confirmed = (
                    spring_like
                    and np.isfinite(recent_low_15m)
                    and recent_low_15m <= spring_min_rsi_low
                )
                if self.config.flip_bullish_spring_require_price_break:
                    spring_confirmed = spring_confirmed and bool(rhythm.get("price_break_high", False))
            elif entry_type == "rsi_neutral_resume":
                spring_confirmed = (
                    spring_like
                    and np.isfinite(recent_low_15m)
                    and recent_low_15m <= max(spring_min_rsi_low, 40.0)
                    and np.isfinite(current_rsi_15m)
                    and np.isfinite(prev_rsi_15m)
                    and current_rsi_15m >= 50.0
                    and current_rsi_15m > prev_rsi_15m
                )
        result["spring_confirmed"] = spring_confirmed

        current_4h_hist = self._series_value(
            np.asarray(macd_hist_4h[: idx_4h + 1], dtype=float) if macd_hist_4h is not None and idx_4h >= 0 else None,
            default=0.0,
        )
        trend_aligned = bool(current_4h_hist > 0) if self.config.flip_bullish_require_trend_alignment else True
        result["trend_aligned"] = trend_aligned
        if not trend_aligned:
            result.update(
                passed=False,
                reason="no_trend_alignment",
            )
            return result

        quality_matches = int(momentum_reset_found) + int(spring_confirmed) + int(trend_aligned)
        result["quality_matches"] = quality_matches
        score_adjustment = 0.0
        if self.config.flip_bullish_require_momentum_reset and not momentum_reset_found:
            score_adjustment -= float(self.config.flip_bullish_no_momentum_reset_penalty)
        if spring_confirmed:
            score_adjustment += float(self.config.flip_bullish_spring_confirmation_bonus)
        elif self.config.flip_bullish_require_spring_confirmation:
            score_adjustment -= float(self.config.flip_bullish_no_spring_penalty)

        if quality_matches >= 3:
            result.update(
                passed=True,
                reason="perfect_launch",
                bonus_score=float(self.config.flip_bullish_sniper_perfect_score_bonus),
            )
            return result

        if quality_matches >= 2:
            result.update(
                passed=True,
                reason="qualified_launch",
                bonus_score=score_adjustment,
            )
            return result

        result.update(
            passed=True,
            reason="soft_launch_profile",
            bonus_score=score_adjustment,
        )
        return result

    def _evaluate_flip_bullish_cooling(
        self,
        *,
        signal_type_1h: Optional[str],
        trade_direction: Optional[str],
        rsi_rhythm: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = {
            "applies": False,
            "passed": True,
            "reason": "not_applicable",
            "score_multiplier": 1.0,
        }
        if not self.config.enable_flip_bullish_cooling:
            return result
        if str(signal_type_1h or "").strip().lower() != "flip_bullish" or str(trade_direction or "").strip().lower() != "long":
            return result
        result["applies"] = True
        rhythm = rsi_rhythm or {}
        rsi_1h_current = float(rhythm.get("rsi_1h_current", np.nan) or np.nan)
        rsi_15m_current = float(rhythm.get("rsi_15m_current", np.nan) or np.nan)
        entry_type = str(rhythm.get("entry_type") or "").strip().lower()
        spring_like_entry = entry_type in {"rsi_spring", "rsi_neutral_resume"}
        soft_threshold = float(self.config.flip_bullish_cooling_soft_rsi_above)
        hard_threshold = max(
            float(self.config.flip_bullish_cooling_reject_if_1h_rsi_above),
            soft_threshold + max(0.0, float(self.config.flip_bullish_cooling_hard_rsi_buffer)),
        )

        if (
            np.isfinite(rsi_1h_current)
            and not spring_like_entry
            and rsi_1h_current > hard_threshold
        ):
            result.update(passed=False, reason="overheated_launch")
            return result
        if (
            np.isfinite(rsi_1h_current)
            and not spring_like_entry
            and rsi_1h_current > soft_threshold
        ):
            result.update(
                passed=True,
                reason="soft_launch_profile",
                score_multiplier=float(self.config.flip_bullish_cooling_soft_discount),
            )
            return result
        if (
            self.config.flip_bullish_cooling_reject_if_15m_no_spring_and_rsi_high
            and not spring_like_entry
            and np.isfinite(rsi_15m_current)
            and rsi_15m_current > float(self.config.flip_bullish_cooling_reject_if_15m_rsi_above)
        ):
            result.update(passed=False, reason="no_spring_high_rsi")
            return result
        if result["reason"] == "not_applicable":
            result["reason"] = "passed"
        return result

    def _evaluate_flip_bullish_strict_filter(
        self,
        *,
        signal_type_1h: Optional[str],
        trade_direction: Optional[str],
        entry_type_15m: Optional[str],
        entry_refine_15m: Optional[str],
        vwap_score: float,
    ) -> Dict[str, Any]:
        result = {
            "applies": False,
            "passed": True,
            "reasons": [],
            "score_multiplier": 1.0,
        }
        if not self.config.enable_flip_bullish_strict_filter:
            return result
        if str(signal_type_1h or "").strip().lower() != "flip_bullish" or str(trade_direction or "").strip().lower() != "long":
            return result
        result["applies"] = True
        reasons: List[str] = []
        if self.config.flip_bullish_require_15m_growing and entry_type_15m not in {"rsi_spring", "rsi_neutral_resume"}:
            reasons.append(f"15m_entry={entry_type_15m or 'none'}")
        if self.config.flip_bullish_require_pullback_bounce and entry_refine_15m not in {"rsi_spring", "rsi_neutral_resume"}:
            reasons.append(f"15m_refine={entry_refine_15m or 'none'}")
        if vwap_score < self.config.flip_bullish_min_vwap_score:
            reasons.append(f"vwap_score={vwap_score:.2f}<{self.config.flip_bullish_min_vwap_score:.2f}")
        result["reasons"] = reasons
        if reasons:
            result["score_multiplier"] = max(0.0, 1.0 - 0.05 * len(reasons))
        return result

    def _evaluate_neutral_upgrade(
        self,
        *,
        neutral_upgrade_candidate: Optional[str],
        neutral_upgrade_raw: float,
        hard_veto: bool,
    ) -> Dict[str, Any]:
        result = {
            "applies": bool(neutral_upgrade_candidate),
            "applied": False,
            "mode": "reject",
            "probe_mode": False,
            "penalty_mult": 1.0,
            "threshold_override": 0.0,
        }
        if not neutral_upgrade_candidate or hard_veto:
            return result
        threshold_override = float(self.config.neutral_upgrade_probe_threshold_score)
        if str(neutral_upgrade_candidate).strip().lower() == "short":
            threshold_override = max(threshold_override, float(self.config.flip_bearish_min_signal_score))
        result["threshold_override"] = threshold_override
        if neutral_upgrade_raw >= float(self.config.neutral_upgrade_min_rsi_score):
            result.update(
                applied=True,
                mode="full",
                penalty_mult=float(self.config.neutral_upgrade_penalty_mult),
            )
            return result
        if neutral_upgrade_raw >= float(self.config.neutral_upgrade_probe_rsi_score):
            result.update(
                applied=True,
                mode="probe",
                probe_mode=True,
                penalty_mult=float(self.config.neutral_upgrade_penalty_mult),
            )
        return result

    def _classify_rsi_macd_conflict(
        self,
        *,
        trade_direction: str,
        direction_1h: Optional[str],
        direction_4h: Optional[str],
        score_rsi_rhythm_raw: float,
        rsi_rhythm: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = {
            "type": "none",
            "active": False,
            "score_penalty_mult": 1.0,
            "portion_penalty_mult": 1.0,
            "reduce_leverage_one_step": False,
            "force_probe": False,
        }
        rhythm = rsi_rhythm or {}
        raw_score = float(score_rsi_rhythm_raw or 0.0)
        threshold = float(self.config.rsi_conflict_threshold)
        mismatch = bool(
            (trade_direction == "long" and raw_score < -threshold)
            or (trade_direction == "short" and raw_score > threshold)
        )
        leading_candidate = bool(
            self.config.enable_leading_rsi_conflict_pass
            and str(rhythm.get("entry_type") or "").strip().lower() == "rsi_spring"
            and str(rhythm.get("rsi_1h_phase") or "").strip().lower() in {"launch", "relaunch"}
            and abs(float(rhythm.get("rsi_1h_slope", 0.0) or 0.0)) >= float(self.config.leading_rsi_slope_threshold)
            and str(direction_4h or "").strip().lower() == trade_direction
            and str(direction_1h or "").strip().lower() != trade_direction
        )
        if leading_candidate:
            result.update(
                type="leading",
                active=True,
                portion_penalty_mult=float(self.config.rsi_leading_conflict_portion_mult),
                reduce_leverage_one_step=True,
            )
            return result
        if mismatch and (
            bool(rhythm.get("probe_mode", False))
            or str(rhythm.get("rsi_1h_phase") or "").strip().lower() in {"divergence_warning", "flat_extreme"}
        ):
            result.update(
                type="extreme_oppose",
                active=True,
                force_probe=True,
            )
            return result
        if mismatch:
            result.update(
                type="divergence",
                active=True,
                score_penalty_mult=float(self.config.rsi_conflict_penalty_mult),
                portion_penalty_mult=float(self.config.rsi_divergence_conflict_portion_mult),
                reduce_leverage_one_step=True,
            )
        return result

    def _resolve_rsi_spring_threshold_override(
        self,
        *,
        trade_direction: str,
        rsi_rhythm: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = {
            "applied": False,
            "threshold": 0.0,
            "score_bonus": 0.0,
        }
        if not self.config.enable_15m_spring_threshold_override:
            return result
        rhythm = rsi_rhythm or {}
        entry_type = str(rhythm.get("entry_type") or "").strip().lower()
        phase = str(rhythm.get("rsi_1h_phase") or "").strip().lower()
        if entry_type != "rsi_spring" or phase not in {"launch", "relaunch"}:
            return result

        current_rsi_1h = float(rhythm.get("rsi_1h_current", np.nan))
        recent_low_1h = float(rhythm.get("rsi_1h_recent_low", np.nan))
        recent_high_1h = float(rhythm.get("rsi_1h_recent_high", np.nan))

        if trade_direction == "long" and np.isfinite(current_rsi_1h) and np.isfinite(recent_low_1h):
            if recent_low_1h <= 45.0 and current_rsi_1h >= 50.0:
                result.update(
                    applied=True,
                    threshold=float(self.config.spring_override_min_signal_score),
                    score_bonus=float(self.config.spring_override_score_bonus),
                )
        elif trade_direction == "short" and np.isfinite(current_rsi_1h) and np.isfinite(recent_high_1h):
            if recent_high_1h >= 55.0 and current_rsi_1h <= 50.0:
                result.update(
                    applied=True,
                    threshold=float(self.config.spring_override_min_signal_score),
                    score_bonus=float(self.config.spring_override_score_bonus),
                )
        return result

    def _resolve_flip_bullish_rsi_spring_weight_floor(
        self,
        *,
        signal_type_1h: Optional[str],
        trade_direction: Optional[str],
        rsi_rhythm: Optional[Dict[str, Any]],
        score_rsi_rhythm_weighted: float,
    ) -> Dict[str, Any]:
        result = {
            "applied": False,
            "rsi_spring_weighted_floor_applied": False,
            "rsi_spring_weighted_floor_value": 0.0,
            "score_rsi_rhythm_weighted": float(score_rsi_rhythm_weighted or 0.0),
        }
        if str(trade_direction or "").strip().lower() != "long":
            return result
        if str(signal_type_1h or "").strip().lower() != "flip_bullish":
            return result

        rhythm = rsi_rhythm or {}
        entry_type = str(rhythm.get("entry_type") or "").strip().lower()
        if entry_type not in {"rsi_spring", "rsi_neutral_resume"}:
            return result

        spring_confirmed = False
        if entry_type == "rsi_spring":
            spring_confirmed = bool(rhythm.get("price_break_high", False))
        else:
            phase = str(rhythm.get("rsi_1h_phase") or "").strip().lower()
            spring_confirmed = phase in {"launch", "relaunch", "trend_health"}
        if not spring_confirmed:
            return result

        floor_value = 0.20
        result.update(
            applied=True,
            rsi_spring_weighted_floor_applied=True,
            rsi_spring_weighted_floor_value=floor_value,
            score_rsi_rhythm_weighted=max(float(score_rsi_rhythm_weighted or 0.0), floor_value),
        )
        return result

    def _resolve_priority_execution_plan(self, score: float) -> Dict[str, Any]:
        priority_execution_applied = bool(
            self.config.enable_priority_execution and float(score) >= float(self.config.priority_exec_min_score)
        )
        vip_applied = bool(
            priority_execution_applied and float(score) >= float(self.config.priority_exec_vip_min_score)
        )
        retry_enabled = bool(vip_applied and self.config.priority_exec_vip_allow_retry)
        standard_market_fallback = bool(
            not priority_execution_applied
            and float(score) >= float(self.config.entry_market_fallback_min_score)
        )
        return {
            "execution_route": (
                "priority_execution_vip"
                if vip_applied
                else (
                    "priority_execution"
                    if priority_execution_applied
                    else ("ioc_market_fallback" if standard_market_fallback else "ioc")
                )
            ),
            "priority_execution_applied": priority_execution_applied,
            "priority_execution_tier": "vip" if vip_applied else ("standard" if priority_execution_applied else "none"),
            "entry_time_in_force": "GTC" if priority_execution_applied else "IOC",
            "entry_expire_seconds": (
                int(self.config.priority_exec_vip_expire_seconds)
                if vip_applied
                else (int(self.config.priority_exec_expire_seconds) if priority_execution_applied else 0)
            ),
            "entry_price_mode": "elastic_limit" if priority_execution_applied else "ioc_limit",
            "entry_retry_enabled": retry_enabled,
            "entry_retry_max_attempts": 1 if retry_enabled else 0,
            "entry_market_fallback_enabled": standard_market_fallback,
            "entry_market_fallback_timeout_ms": (
                int(self.config.entry_market_fallback_timeout_ms) if standard_market_fallback else 0
            ),
            "entry_market_fallback_max_slippage_bps": (
                int(self.config.entry_market_fallback_max_slippage_bps) if standard_market_fallback else 0
            ),
            "entry_execution_policy": (
                "priority_execution_vip"
                if vip_applied
                else (
                    "priority_execution"
                    if priority_execution_applied
                    else ("ioc_market_fallback" if standard_market_fallback else "ioc")
                )
            ),
        }

    def evaluate_rsi_rhythm(
        self,
        *,
        direction: str,
        rsi_15m_series: Optional[np.ndarray],
        rsi_1h_series: Optional[np.ndarray],
        rsi_4h_series: Optional[np.ndarray],
        close_15m_series: Optional[np.ndarray],
        close_1h_series: Optional[np.ndarray],
        close_4h_series: Optional[np.ndarray],
        macd_hist_1h_current: float = 0.0,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "raw_score": 0.0,
            "weighted_score": 0.0,
            "entry_type": "",
            "hard_veto": False,
            "veto_reason": "",
            "rsi_4h_regime": "neutral",
            "rsi_1h_phase": "neutral",
            "rsi_macd_conflict": False,
            "exposure_mult": 0.8,
            "probe_mode": False,
            "rsi_15m_current": np.nan,
            "rsi_15m_prev": np.nan,
            "rsi_15m_recent_low": np.nan,
            "rsi_15m_recent_high": np.nan,
            "price_break_high": False,
            "price_break_low": False,
            "rsi_1h_current": np.nan,
            "rsi_1h_prev": np.nan,
            "rsi_1h_slope": 0.0,
            "rsi_1h_recent_low": np.nan,
            "rsi_1h_recent_high": np.nan,
        }
        if not self.config.enable_rsi_rhythm_scoring:
            return result

        current_rsi_15m = self._series_value(rsi_15m_series, default=np.nan)
        prev_rsi_15m = self._series_value(rsi_15m_series, offset=-2, default=np.nan)
        current_rsi_1h = self._series_value(rsi_1h_series, default=np.nan)
        prev_rsi_1h = self._series_value(rsi_1h_series, offset=-2, default=np.nan)
        current_rsi_4h = self._series_value(rsi_4h_series, default=np.nan)
        if not all(np.isfinite(x) for x in (current_rsi_15m, prev_rsi_15m, current_rsi_1h, prev_rsi_1h, current_rsi_4h)):
            return result

        raw_score = 0.0
        current_close_15m = self._series_value(close_15m_series, default=np.nan)
        prev_high_15m = float(np.max(np.asarray(close_15m_series[:-1], dtype=float))) if close_15m_series is not None and len(close_15m_series) > 1 else np.nan
        prev_low_15m = float(np.min(np.asarray(close_15m_series[:-1], dtype=float))) if close_15m_series is not None and len(close_15m_series) > 1 else np.nan
        result["rsi_15m_current"] = current_rsi_15m
        result["rsi_15m_prev"] = prev_rsi_15m

        tail_4h = self._finite_tail(np.asarray(rsi_4h_series, dtype=float), 4)
        slope_4h = current_rsi_4h - float(np.mean(tail_4h[:-1])) if tail_4h.size >= 2 else 0.0
        if direction == "long":
            if current_rsi_4h > float(self.config.rsi_4h_long_support):
                raw_score += 0.3
                result["rsi_4h_regime"] = "supportive"
                raw_score += 0.1 if slope_4h > 0 else -0.1
            elif current_rsi_4h < float(self.config.rsi_4h_long_against):
                raw_score -= 0.2
                result["rsi_4h_regime"] = "against"
        elif direction == "short":
            if current_rsi_4h < float(self.config.rsi_4h_short_support):
                raw_score += 0.3
                result["rsi_4h_regime"] = "supportive"
                raw_score += 0.1 if slope_4h < 0 else -0.1
            elif current_rsi_4h > float(self.config.rsi_4h_short_against):
                raw_score -= 0.2
                result["rsi_4h_regime"] = "against"

        slope_1h = current_rsi_1h - prev_rsi_1h
        tail_1h = self._finite_tail(np.asarray(rsi_1h_series, dtype=float), 4)
        flat_tail = np.diff(tail_1h) if tail_1h.size >= 2 else np.array([], dtype=float)
        recent_1h = self._finite_tail(np.asarray(rsi_1h_series, dtype=float), max(2, int(self.config.rsi_1h_relaunch_lookback)))
        result["rsi_1h_current"] = current_rsi_1h
        result["rsi_1h_prev"] = prev_rsi_1h
        result["rsi_1h_slope"] = slope_1h
        if recent_1h.size:
            result["rsi_1h_recent_low"] = float(np.min(recent_1h))
            result["rsi_1h_recent_high"] = float(np.max(recent_1h))
        if direction == "long":
            if prev_rsi_1h < 50.0 <= current_rsi_1h and slope_1h > float(self.config.rsi_1h_launch_slope):
                raw_score += 0.5
                result["rsi_1h_phase"] = "launch"
            elif float(self.config.rsi_1h_trend_long_min) <= current_rsi_1h <= float(self.config.rsi_1h_trend_long_max) and slope_1h >= 0:
                raw_score += 0.3
                result["rsi_1h_phase"] = "trend_health"
            if (
                recent_1h.size
                and float(np.min(recent_1h)) < float(self.config.rsi_1h_relaunch_long_floor)
                and current_rsi_1h > 50.0
                and macd_hist_1h_current > 0
            ):
                raw_score += 0.4
                result["rsi_1h_phase"] = "relaunch"
            if (
                current_rsi_1h > float(self.config.rsi_1h_extreme_long)
                and self._detect_rsi_divergence(direction="long", price_series=close_1h_series, rsi_series=rsi_1h_series)
            ):
                raw_score -= 0.5
                result["rsi_1h_phase"] = "divergence_warning"
            elif (
                current_rsi_1h > float(self.config.rsi_1h_extreme_long)
                and flat_tail.size >= 3
                and np.all(np.abs(flat_tail[-3:]) < float(self.config.rsi_1h_extreme_flat_slope_max))
            ):
                raw_score -= 0.3
                result["rsi_1h_phase"] = "flat_extreme"
        elif direction == "short":
            if prev_rsi_1h > 50.0 >= current_rsi_1h and slope_1h < -float(self.config.rsi_1h_launch_slope):
                raw_score += 0.5
                result["rsi_1h_phase"] = "launch"
            elif float(self.config.rsi_1h_trend_short_min) <= current_rsi_1h <= float(self.config.rsi_1h_trend_short_max) and slope_1h <= 0:
                raw_score += 0.3
                result["rsi_1h_phase"] = "trend_health"
            if (
                recent_1h.size
                and float(np.max(recent_1h)) > float(self.config.rsi_1h_relaunch_short_ceiling)
                and current_rsi_1h < 50.0
                and macd_hist_1h_current < 0
            ):
                raw_score += 0.4
                result["rsi_1h_phase"] = "relaunch"
            if (
                current_rsi_1h < float(self.config.rsi_1h_extreme_short)
                and self._detect_rsi_divergence(direction="short", price_series=close_1h_series, rsi_series=rsi_1h_series)
            ):
                raw_score -= 0.5
                result["rsi_1h_phase"] = "divergence_warning"
            elif (
                current_rsi_1h < float(self.config.rsi_1h_extreme_short)
                and flat_tail.size >= 3
                and np.all(np.abs(flat_tail[-3:]) < float(self.config.rsi_1h_extreme_flat_slope_max))
            ):
                raw_score -= 0.3
                result["rsi_1h_phase"] = "flat_extreme"

        recent_15m = self._finite_tail(np.asarray(rsi_15m_series, dtype=float), max(2, int(self.config.rsi_15m_spring_lookback)))
        if recent_15m.size:
            result["rsi_15m_recent_low"] = float(np.min(recent_15m))
            result["rsi_15m_recent_high"] = float(np.max(recent_15m))
        if direction == "long":
            price_break_high = bool(np.isfinite(current_close_15m) and np.isfinite(prev_high_15m) and current_close_15m > prev_high_15m)
            result["price_break_high"] = price_break_high
            if (
                recent_15m.size
                and float(np.min(recent_15m)) < float(self.config.rsi_15m_spring_long_extreme)
                and prev_rsi_15m < 50.0
                and current_rsi_15m >= 50.0
                and price_break_high
            ):
                raw_score += 0.4
                result["entry_type"] = "rsi_spring"
            elif (
                float(self.config.rsi_15m_neutral_low) <= current_rsi_15m <= float(self.config.rsi_15m_neutral_high)
                and current_rsi_15m > prev_rsi_15m
            ):
                raw_score += 0.2
                result["entry_type"] = "rsi_neutral_resume"
            elif (
                self.config.enable_rsi_hard_veto
                and current_rsi_15m > float(self.config.rsi_15m_extreme_long_veto)
                and not price_break_high
            ):
                result.update(
                    hard_veto=True,
                    veto_reason="rsi_15m_extreme_veto",
                    entry_type="rsi_extreme_block",
                    exposure_mult=0.0,
                )
                return result
        elif direction == "short":
            price_break_low = bool(np.isfinite(current_close_15m) and np.isfinite(prev_low_15m) and current_close_15m < prev_low_15m)
            result["price_break_low"] = price_break_low
            if (
                recent_15m.size
                and float(np.max(recent_15m)) > float(self.config.rsi_15m_spring_short_extreme)
                and prev_rsi_15m > 50.0
                and current_rsi_15m <= 50.0
                and price_break_low
            ):
                raw_score += 0.4
                result["entry_type"] = "rsi_spring"
            elif (
                float(self.config.rsi_15m_neutral_low) <= current_rsi_15m <= float(self.config.rsi_15m_neutral_high)
                and current_rsi_15m < prev_rsi_15m
            ):
                raw_score += 0.2
                result["entry_type"] = "rsi_neutral_resume"
            elif (
                self.config.enable_rsi_hard_veto
                and current_rsi_15m < float(self.config.rsi_15m_extreme_short_veto)
                and not price_break_low
            ):
                result.update(
                    hard_veto=True,
                    veto_reason="rsi_15m_extreme_veto",
                    entry_type="rsi_extreme_block",
                    exposure_mult=0.0,
                )
                return result

        raw_score = self._clamp(raw_score, -1.0, 1.0)
        result["raw_score"] = raw_score
        result["weighted_score"] = raw_score * float(self.config.weight_rsi_rhythm)
        result["exposure_mult"] = self._resolve_rsi_exposure_multiplier(raw_score)
        result["probe_mode"] = raw_score < float(self.config.rsi_rhythm_block_score)
        if (
            direction == "short"
            and np.isfinite(current_rsi_1h)
            and current_rsi_1h < float(self.config.short_rsi_probe_only_below)
        ):
            result["probe_mode"] = True
            result["exposure_mult"] = min(
                float(result.get("exposure_mult", 1.0)),
                float(self.config.rsi_probe_exposure_mult),
            )
        return result

    def _resolve_rsi_entry_refinement(
        self,
        *,
        direction: str,
        entry_score: float,
        close_15m_series: Optional[np.ndarray],
        close_1h_series: Optional[np.ndarray],
        close_4h_series: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "entry_score": entry_score,
            "refine": None,
        }
        if not self.config.enable_rsi_entry_refinement:
            return out

        rsi_period = max(2, int(self.config.rsi_period))
        rsi_15m_series = self.calculate_rsi_series(close_15m_series, period=rsi_period)
        rsi_1h_series = self.calculate_rsi_series(close_1h_series, period=rsi_period)
        rsi_4h_series = self.calculate_rsi_series(close_4h_series, period=rsi_period)
        current_rsi_15m = self._series_value(rsi_15m_series, default=np.nan)
        prev_rsi_15m = self._series_value(rsi_15m_series, offset=-2, default=np.nan)
        current_rsi_1h = self._series_value(rsi_1h_series, default=np.nan)
        current_rsi_4h = self._series_value(rsi_4h_series, default=np.nan)
        recent_window = self._finite_tail(rsi_15m_series, max(1, int(self.config.rsi_spring_recent_extreme_lookback)))
        recent_min = float(np.min(recent_window)) if recent_window.size else np.nan
        recent_max = float(np.max(recent_window)) if recent_window.size else np.nan
        reset_lookback = max(1, int(self.config.rsi_launch_sovereign_reset_lookback))
        reset_window = self._finite_tail(rsi_1h_series, reset_lookback)
        reset_min = float(np.min(reset_window)) if reset_window.size else np.nan
        reset_max = float(np.max(reset_window)) if reset_window.size else np.nan
        price_window_size = max(3, int(self.config.rsi_spring_recent_extreme_lookback))
        price_values = np.asarray(close_15m_series, dtype=float) if close_15m_series is not None else np.array([], dtype=float)
        price_window = self._finite_tail(price_values, price_window_size)
        current_close_15m = self._series_value(close_15m_series, default=np.nan)
        prior_prices = price_window[:-1] if price_window.size > 1 else np.array([], dtype=float)
        price_break_high = bool(np.isfinite(current_close_15m) and prior_prices.size > 0 and current_close_15m > float(np.max(prior_prices)))
        price_break_low = bool(np.isfinite(current_close_15m) and prior_prices.size > 0 and current_close_15m < float(np.min(prior_prices)))

        out.update(
            rsi_15m=current_rsi_15m,
            rsi_15m_prev=prev_rsi_15m,
            rsi_1h=current_rsi_1h,
            rsi_4h=current_rsi_4h,
            rsi_15m_recent_min=recent_min,
            rsi_15m_recent_max=recent_max,
            rsi_1h_recent_reset_min=reset_min,
            rsi_1h_recent_reset_max=reset_max,
            price_break_high=price_break_high,
            price_break_low=price_break_low,
        )

        if not (np.isfinite(current_rsi_15m) and np.isfinite(prev_rsi_15m) and np.isfinite(current_rsi_1h)):
            return out

        if direction == "long":
            if (
                current_rsi_1h >= float(self.config.rsi_1h_long_support)
                and np.isfinite(recent_min)
                and recent_min <= float(self.config.rsi_spring_recent_oversold)
                and prev_rsi_15m < float(self.config.rsi_spring_prev_max)
                and current_rsi_15m >= float(self.config.rsi_spring_confirm)
            ):
                out["entry_score"] = min(1.0, entry_score + 0.15)
                out["refine"] = "rsi_spring"
                return out
            if (
                current_rsi_1h >= 50.0
                and 45.0 <= current_rsi_15m <= 55.0
                and current_rsi_15m > prev_rsi_15m
            ):
                out["entry_score"] = min(1.0, entry_score + 0.05)
                out["refine"] = "rsi_neutral_resume"
                return out
            if current_rsi_15m >= float(self.config.rsi_extension_penalty_threshold_long):
                out["entry_score"] = entry_score * float(self.config.rsi_extension_penalty_multiplier)
                out["refine"] = "rsi_extension_penalty"
                return out

        if direction == "short":
            short_prev_min = 100.0 - float(self.config.rsi_spring_prev_max)
            short_confirm = 100.0 - float(self.config.rsi_spring_confirm)
            if (
                current_rsi_1h <= float(self.config.rsi_1h_short_support)
                and np.isfinite(recent_max)
                and recent_max >= float(self.config.rsi_spring_recent_overbought)
                and prev_rsi_15m > short_prev_min
                and current_rsi_15m <= short_confirm
            ):
                out["entry_score"] = min(1.0, entry_score + 0.15)
                out["refine"] = "rsi_reject"
                return out
            if (
                current_rsi_1h <= 50.0
                and 45.0 <= current_rsi_15m <= 55.0
                and current_rsi_15m < prev_rsi_15m
            ):
                out["entry_score"] = min(1.0, entry_score + 0.05)
                out["refine"] = "rsi_neutral_resume"
                return out
            if current_rsi_15m <= float(self.config.rsi_extension_penalty_threshold_short):
                out["entry_score"] = entry_score * float(self.config.rsi_extension_penalty_multiplier)
                out["refine"] = "rsi_extension_penalty"
                return out

        return out

    def _evaluate_rsi_launch_sovereign_mode(
        self,
        *,
        trade_direction: str,
        signal_type_1h: Optional[str],
        signal_type_4h: Optional[str],
        macd_hist_4h_current: float,
        rsi_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = self._default_rsi_launch_sovereign_details()
        result.update(
            score_bonus=0.0,
            threshold_override=0.0,
            competition_multiplier=1.0,
            priority_execution_applied=False,
            applied=False,
        )
        if not bool(self.config.enable_rsi_launch_sovereign_mode):
            result["rsi_launch_sovereign_reason"] = "disabled"
            return result

        ctx = dict(rsi_context or {})
        direction = str(trade_direction or "").strip().lower()
        signal_1h = str(signal_type_1h or "").strip().lower()
        refine = str(ctx.get("refine") or ctx.get("ema_15m_refine") or "").strip().lower()
        rsi_1h = float(ctx.get("rsi_1h", np.nan))
        rsi_4h = float(ctx.get("rsi_4h", np.nan))
        reset_min = float(ctx.get("rsi_1h_recent_reset_min", np.nan))
        reset_max = float(ctx.get("rsi_1h_recent_reset_max", np.nan))
        price_break_high = bool(ctx.get("price_break_high", False))
        price_break_low = bool(ctx.get("price_break_low", False))

        background_aligned = False
        price_break_confirmed = False
        momentum_reset_found = False
        non_overheated = False
        reason = "direction_not_supported"

        if direction == "long" and signal_1h == "flip_bullish":
            price_break_confirmed = price_break_high
            momentum_reset_found = np.isfinite(reset_min) and reset_min <= float(self.config.rsi_launch_sovereign_long_reset_ceiling)
            background_aligned = (
                macd_hist_4h_current > 0
                and np.isfinite(rsi_4h)
                and rsi_4h >= float(self.config.rsi_launch_sovereign_long_4h_rsi_min)
            )
            non_overheated = np.isfinite(rsi_1h) and rsi_1h < float(self.config.rsi_launch_sovereign_long_1h_rsi_max)
            if refine != "rsi_spring":
                reason = "long_refine_not_eligible"
            elif not price_break_confirmed:
                reason = "long_price_break_missing"
            elif not momentum_reset_found:
                reason = "long_reset_missing"
            elif not background_aligned:
                reason = "long_background_not_aligned"
            elif not non_overheated:
                reason = "long_overheated"
            else:
                reason = "long_sovereign_confirmed"
        elif direction == "short" and signal_1h == "flip_bearish":
            price_break_confirmed = price_break_low
            momentum_reset_found = np.isfinite(reset_max) and reset_max >= float(self.config.rsi_launch_sovereign_short_reset_floor)
            background_aligned = (
                macd_hist_4h_current < 0
                and np.isfinite(rsi_4h)
                and rsi_4h <= float(self.config.rsi_launch_sovereign_short_4h_rsi_max)
            )
            non_overheated = np.isfinite(rsi_1h) and rsi_1h > float(self.config.rsi_launch_sovereign_short_1h_rsi_min)
            if refine != "rsi_reject":
                reason = "short_refine_not_eligible"
            elif not price_break_confirmed:
                reason = "short_price_break_missing"
            elif not momentum_reset_found:
                reason = "short_reset_missing"
            elif not background_aligned:
                reason = "short_background_not_aligned"
            elif not non_overheated:
                reason = "short_overheated"
            else:
                reason = "short_sovereign_confirmed"
        else:
            reason = "signal_not_supported"

        applied = reason in {"long_sovereign_confirmed", "short_sovereign_confirmed"}
        result.update(
            rsi_launch_sovereign_applies=applied,
            rsi_launch_sovereign_applied=applied,
            rsi_launch_sovereign_active=applied,
            rsi_launch_sovereign_direction=direction if applied else "",
            rsi_launch_sovereign_side=direction if applied else "",
            rsi_launch_sovereign_reason=reason,
            rsi_launch_sovereign_score_bonus=float(self.config.rsi_launch_sovereign_score_bonus) if applied else 0.0,
            rsi_launch_sovereign_threshold_override=float(self.config.rsi_launch_sovereign_min_signal_score) if applied else 0.0,
            rsi_launch_sovereign_competition_multiplier=float(self.config.rsi_launch_sovereign_competition_multiplier) if applied else 1.0,
            rsi_launch_sovereign_force_priority_execution=applied,
            rsi_launch_sovereign_price_break_confirmed=price_break_confirmed,
            rsi_launch_sovereign_momentum_reset_found=momentum_reset_found,
            rsi_launch_sovereign_background_aligned=background_aligned,
            rsi_launch_sovereign_non_overheated=non_overheated,
            rsi_launch_sovereign_conflict_override=applied,
            score_bonus=float(self.config.rsi_launch_sovereign_score_bonus) if applied else 0.0,
            threshold_override=float(self.config.rsi_launch_sovereign_min_signal_score) if applied else 0.0,
            competition_multiplier=float(self.config.rsi_launch_sovereign_competition_multiplier) if applied else 1.0,
            priority_execution_applied=applied,
            direction=direction if applied else "",
            applied=applied,
        )
        return result

    @staticmethod
    def _calculate_macd_shrink_pct(macd_hist: np.ndarray, idx: int) -> float:
        values = np.asarray(macd_hist[: idx + 1], dtype=float)
        if values.size < 10:
            return 0.0
        recent = values[-10:-2] if values.size >= 12 else values[:-2]
        if recent.size == 0:
            return 0.0
        peak_value = float(np.max(np.abs(recent)))
        current_value = abs(float(values[-1]))
        if peak_value <= 1e-12:
            return 0.0
        if current_value > peak_value:
            return -(current_value / peak_value - 1.0)
        return 1.0 - (current_value / peak_value)

    @staticmethod
    def _count_consecutive_macd_shrinking_bars(macd_hist: np.ndarray, idx: int) -> int:
        values = np.asarray(macd_hist[: idx + 1], dtype=float)
        if values.size < 2:
            return 0

        count = 0
        cursor = values.size - 1
        while cursor > 0:
            current = float(values[cursor])
            previous = float(values[cursor - 1])
            if abs(current) >= abs(previous):
                break
            if abs(current) <= 1e-12 or abs(previous) <= 1e-12:
                break
            if np.sign(current) != np.sign(previous):
                break
            count += 1
            cursor -= 1
        return count

    @staticmethod
    def _count_consecutive_macd_same_sign_bars(
        macd_hist: np.ndarray,
        idx: int,
        *,
        positive: bool,
        min_abs_value: float = 0.0,
    ) -> int:
        values = np.asarray(macd_hist[: idx + 1], dtype=float)
        if values.size <= 0:
            return 0

        count = 0
        cursor = values.size - 1
        while cursor >= 0:
            current = float(values[cursor])
            if abs(current) <= min_abs_value:
                break
            if positive and current <= 0:
                break
            if not positive and current >= 0:
                break
            count += 1
            cursor -= 1
        return count

    def _build_4h_shrink_context(
        self,
        macd_hist_4h: np.ndarray,
        idx_4h: int,
        signal_type_4h: str,
    ) -> Dict[str, Any]:
        signal_type = str(signal_type_4h or "").strip().lower()
        shrink_pct = self._calculate_macd_shrink_pct(macd_hist_4h, idx_4h)
        shrink_bars = self._count_consecutive_macd_shrinking_bars(macd_hist_4h, idx_4h)
        preflip_direction: Optional[str] = None
        exit_direction: Optional[str] = None
        if signal_type == "green_bar_shrinking":
            preflip_direction = "long"
            exit_direction = "short"
        elif signal_type == "red_bar_shrinking":
            preflip_direction = "short"
            exit_direction = "long"

        return {
            "signal_type_4h": signal_type,
            "shrink_pct": shrink_pct,
            "shrink_bars": shrink_bars,
            "preflip_direction": preflip_direction,
            "exit_direction": exit_direction,
            "shrink_exit_ready": bool(
                exit_direction
                and shrink_bars >= max(1, int(self.config.exit_4h_shrink_bars))
                and shrink_pct >= max(0.0, float(self.config.exit_4h_min_shrink_pct))
            ),
        }

    def _build_stable_trend_context(
        self,
        macd_hist_4h: np.ndarray,
        idx_4h: int,
    ) -> Dict[str, Any]:
        values = np.asarray(macd_hist_4h[: idx_4h + 1], dtype=float)
        current_hist = float(values[-1]) if values.size > 0 else 0.0
        min_abs_value = max(float(self.config.macd_threshold), 1e-8)
        positive_bars = self._count_consecutive_macd_same_sign_bars(
            macd_hist_4h,
            idx_4h,
            positive=True,
            min_abs_value=min_abs_value,
        )
        negative_bars = self._count_consecutive_macd_same_sign_bars(
            macd_hist_4h,
            idx_4h,
            positive=False,
            min_abs_value=min_abs_value,
        )
        return {
            "hist_current": current_hist,
            "positive_bars": positive_bars,
            "negative_bars": negative_bars,
            "bull_active": bool(
                current_hist > min_abs_value
                and positive_bars >= max(1, int(self.config.stable_bull_continuation_min_4h_bars))
            ),
            "bear_active": bool(
                current_hist < -min_abs_value
                and negative_bars >= max(1, int(self.config.stable_bear_continuation_min_4h_bars))
            ),
        }

    def _resolve_stable_continuation_direction(
        self,
        *,
        primary_mode: str,
        direction_1h: Optional[str],
        details_1h: Dict[str, Any],
        stable_trend_context: Dict[str, Any],
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        debug: Dict[str, Any] = {
            "stable_continuation_direction_recovered": False,
        }
        if primary_mode != "4h" or direction_1h not in {"long", "short"}:
            debug["stable_continuation_direction_reason"] = "primary_mode_or_1h_not_eligible"
            return None, debug

        signal_type_1h = str(details_1h.get("signal_type") or "").strip().lower()
        if direction_1h == "short":
            if not self.config.enable_stable_bear_continuation:
                debug["stable_continuation_direction_reason"] = "stable_bear_disabled"
                return None, debug
            if not bool(stable_trend_context.get("bear_active", False)):
                debug["stable_continuation_direction_reason"] = "4h_bear_not_persistent"
                return None, debug
            if signal_type_1h not in {"flip_bearish", "green_bar_growing"}:
                debug["stable_continuation_direction_reason"] = "1h_short_signal_not_supported"
                return None, debug
        else:
            if not self.config.enable_stable_bull_continuation:
                debug["stable_continuation_direction_reason"] = "stable_bull_disabled"
                return None, debug
            if not bool(stable_trend_context.get("bull_active", False)):
                debug["stable_continuation_direction_reason"] = "4h_bull_not_persistent"
                return None, debug
            if signal_type_1h not in {"flip_bullish", "red_bar_growing"}:
                debug["stable_continuation_direction_reason"] = "1h_long_signal_not_supported"
                return None, debug

        debug.update(
            stable_continuation_direction_recovered=True,
            stable_continuation_direction_reason="stable_4h_hist_persistence",
            stable_continuation_direction_side=direction_1h,
        )
        return direction_1h, debug

    def _evaluate_stable_continuation(
        self,
        *,
        primary_mode: str,
        trade_direction: Optional[str],
        signal_type_1h: Optional[str],
        entry_type_15m: Optional[str],
        vwap_score: float,
        vwap_state: str,
        adx_1h: float,
        stable_trend_context: Dict[str, Any],
        is_trial_entry: bool,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "stable_continuation_active": False,
            "stable_continuation_side": None,
            "stable_continuation_reason": "inactive",
        }
        if primary_mode != "4h" or trade_direction not in {"long", "short"} or is_trial_entry:
            result["stable_continuation_reason"] = "primary_mode_or_trial_not_eligible"
            return result

        side = str(trade_direction)
        signal_type = str(signal_type_1h or "").strip().lower()
        entry_type = str(entry_type_15m or "").strip().lower()
        state = str(vwap_state or "").strip().lower()

        if side == "short":
            enabled = bool(self.config.enable_stable_bear_continuation)
            min_vwap_score = max(
                float(self.config.stable_bear_continuation_min_vwap_score),
                float(self.config.short_min_vwap_score_for_entry),
                float(self.config.min_vwap_score_for_entry),
            )
            min_adx_1h = float(self.config.stable_bear_continuation_min_adx_1h)
            min_4h_bars = max(1, int(self.config.stable_bear_continuation_min_4h_bars))
            hist_bars = int(stable_trend_context.get("negative_bars", 0) or 0)
            stable_active = bool(stable_trend_context.get("bear_active", False))
            allowed_states = {
                "short_dual_pressure",
                "short_retest_reject",
                "short_below_session_above_structure",
            }
            allowed_signal_types = {"flip_bearish", "green_bar_growing"}
            allowed_entry_types = {"green_bar_growing", "rsi_spring", "rsi_neutral_resume"}
        else:
            enabled = bool(self.config.enable_stable_bull_continuation)
            min_vwap_score = max(
                float(self.config.stable_bull_continuation_min_vwap_score),
                float(self.config.min_vwap_score_for_entry),
            )
            min_adx_1h = float(self.config.stable_bull_continuation_min_adx_1h)
            min_4h_bars = max(1, int(self.config.stable_bull_continuation_min_4h_bars))
            hist_bars = int(stable_trend_context.get("positive_bars", 0) or 0)
            stable_active = bool(stable_trend_context.get("bull_active", False))
            allowed_states = {"long_dual_support", "long_reclaim_confirmed"}
            allowed_signal_types = {"flip_bullish", "red_bar_growing"}
            allowed_entry_types = {"red_bar_growing", "rsi_spring", "rsi_neutral_resume"}

        result.update(
            stable_continuation_side=side,
            stable_continuation_hist_bars=hist_bars,
            stable_continuation_min_4h_bars=min_4h_bars,
            stable_continuation_min_adx_1h=min_adx_1h,
            stable_continuation_min_vwap_score=min_vwap_score,
            stable_continuation_signal_type_1h=signal_type,
            stable_continuation_entry_type_15m=entry_type,
            stable_continuation_vwap_state=state,
        )

        if not enabled:
            result["stable_continuation_reason"] = "continuation_disabled"
            return result
        if not stable_active or hist_bars < min_4h_bars:
            result["stable_continuation_reason"] = "4h_hist_not_persistent"
            return result
        if signal_type not in allowed_signal_types:
            result["stable_continuation_reason"] = "1h_signal_not_supported"
            return result
        if entry_type not in allowed_entry_types:
            result["stable_continuation_reason"] = "15m_entry_not_supported"
            return result
        if float(adx_1h) < min_adx_1h:
            result["stable_continuation_reason"] = "adx_1h_too_low"
            return result
        if float(vwap_score) < min_vwap_score:
            result["stable_continuation_reason"] = "vwap_score_too_low"
            return result
        if state not in allowed_states:
            result["stable_continuation_reason"] = "vwap_state_not_supported"
            return result

        result.update(
            stable_continuation_active=True,
            stable_continuation_reason="stable_continuation_active",
        )
        return result

    def _evaluate_trial_short_below_structure_continuation_promotion(
        self,
        *,
        primary_mode: str,
        trade_direction: Optional[str],
        signal_type_1h: Optional[str],
        entry_type_15m: Optional[str],
        vwap_state: str,
        vwap_score: float,
        adx_1h: float,
        signal_score: float,
        shrink_4h_context: Dict[str, Any],
        is_trial_entry: bool,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "trial_short_below_structure_promotion_active": False,
            "trial_short_below_structure_promotion_reason": "inactive",
        }
        if not bool(self.config.enable_trial_short_below_structure_continuation_promotion):
            result["trial_short_below_structure_promotion_reason"] = "promotion_disabled"
            return result
        if not is_trial_entry:
            result["trial_short_below_structure_promotion_reason"] = "not_trial_entry"
            return result
        if primary_mode != "4h" or trade_direction != "short":
            result["trial_short_below_structure_promotion_reason"] = "direction_not_eligible"
            return result

        signal_type = str(signal_type_1h or "").strip().lower()
        entry_type = str(entry_type_15m or "").strip().lower()
        state = str(vwap_state or "").strip().lower()
        shrink_pct = max(0.0, float(shrink_4h_context.get("shrink_pct", 0.0) or 0.0))
        shrink_bars = max(0, int(shrink_4h_context.get("shrink_bars", 0) or 0))
        min_signal_score = float(self.config.trial_short_below_structure_promotion_min_signal_score)
        min_vwap_score = max(
            float(self.config.trial_short_below_structure_promotion_min_vwap_score),
            float(self.config.short_min_vwap_score_for_entry),
            float(self.config.min_vwap_score_for_entry),
        )
        min_adx_1h = float(self.config.trial_short_below_structure_promotion_min_adx_1h)
        min_shrink_pct = float(self.config.trial_short_below_structure_promotion_min_4h_shrink_pct)
        min_shrink_bars = max(1, int(self.config.trial_short_below_structure_promotion_min_4h_shrink_bars))

        result.update(
            trial_short_below_structure_promotion_signal_type_1h=signal_type,
            trial_short_below_structure_promotion_entry_type_15m=entry_type,
            trial_short_below_structure_promotion_vwap_state=state,
            trial_short_below_structure_promotion_signal_score=signal_score,
            trial_short_below_structure_promotion_vwap_score=vwap_score,
            trial_short_below_structure_promotion_adx_1h=adx_1h,
            trial_short_below_structure_promotion_shrink_pct=shrink_pct,
            trial_short_below_structure_promotion_shrink_bars=shrink_bars,
            trial_short_below_structure_promotion_min_signal_score=min_signal_score,
            trial_short_below_structure_promotion_min_vwap_score=min_vwap_score,
            trial_short_below_structure_promotion_min_adx_1h=min_adx_1h,
            trial_short_below_structure_promotion_min_shrink_pct=min_shrink_pct,
            trial_short_below_structure_promotion_min_shrink_bars=min_shrink_bars,
        )

        if signal_type != "green_bar_growing":
            result["trial_short_below_structure_promotion_reason"] = "1h_signal_not_supported"
            return result
        if entry_type not in {"flip_bearish", "green_bar_growing", "rsi_spring", "rsi_neutral_resume"}:
            result["trial_short_below_structure_promotion_reason"] = "15m_entry_not_supported"
            return result
        if state != "short_below_session_above_structure":
            result["trial_short_below_structure_promotion_reason"] = "vwap_state_not_supported"
            return result
        if float(signal_score) < min_signal_score:
            result["trial_short_below_structure_promotion_reason"] = "signal_score_too_low"
            return result
        if float(vwap_score) < min_vwap_score:
            result["trial_short_below_structure_promotion_reason"] = "vwap_score_too_low"
            return result
        if float(adx_1h) < min_adx_1h:
            result["trial_short_below_structure_promotion_reason"] = "adx_1h_too_low"
            return result
        if shrink_pct < min_shrink_pct:
            result["trial_short_below_structure_promotion_reason"] = "4h_shrink_pct_too_low"
            return result
        if shrink_bars < min_shrink_bars:
            result["trial_short_below_structure_promotion_reason"] = "4h_shrink_bars_too_low"
            return result

        result.update(
            trial_short_below_structure_promotion_active=True,
            trial_short_below_structure_promotion_reason="trial_short_below_structure_promoted",
        )
        return result

    def resolve_4h_shrink_exit_policy(
        self,
        *,
        signal_details: Optional[Dict[str, Any]],
        position_side: str,
        position_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        details = signal_details if isinstance(signal_details, dict) else {}
        pos = position_context if isinstance(position_context, dict) else {}
        side = str(position_side or "").strip().upper()
        shrink_exit_direction = str(details.get("shrink_exit_direction", "") or "").strip().upper()
        shrink_pct = max(0.0, float(details.get("macd_4h_shrink_pct", 0.0) or 0.0))
        shrink_bars = max(0, int(details.get("macd_4h_shrink_bars", 0) or 0))

        default_required_bars = max(1, int(self.config.exit_4h_shrink_bars))
        default_required_pct = max(0.0, float(self.config.exit_4h_min_shrink_pct))
        continuation_required_bars = max(
            default_required_bars,
            int(self.config.stable_continuation_exit_4h_shrink_bars),
        )
        continuation_required_pct = max(
            default_required_pct,
            float(self.config.stable_continuation_exit_4h_min_shrink_pct),
        )

        stable_continuation_active = False
        continuation_source = ""
        pos_continuation_active = bool(pos.get("stable_continuation_active", False))
        pos_continuation_side = str(pos.get("stable_continuation_side", "") or "").strip().upper()
        if pos_continuation_active and pos_continuation_side == side:
            stable_continuation_active = True
            continuation_source = "position_context"

        required_bars = default_required_bars
        required_pct = default_required_pct
        mode = "default"
        priority_long_signal = bool(
            self.config.enable_priority_signal_shrink_exit
            and side == "LONG"
            and self._resolve_priority_signal(details.get("signal_type_1h"), details.get("vwap_state"))
            and str(details.get("signal_type_1h") or "").strip().lower() == "flip_bullish"
        )
        if priority_long_signal:
            required_bars = max(default_required_bars, int(self.config.priority_signal_shrink_exit_required_bars))
            required_pct = max(default_required_pct, float(self.config.priority_signal_shrink_exit_required_pct))
            mode = "priority_signal_slow"
        elif self.config.enable_stable_continuation_slow_4h_shrink_exit and stable_continuation_active:
            required_bars = continuation_required_bars
            required_pct = continuation_required_pct
            mode = "stable_continuation_slow"

        direction_match = bool(side and shrink_exit_direction == side)
        active = bool(
            direction_match
            and shrink_bars >= required_bars
            and shrink_pct >= required_pct
        )
        return {
            "active": active,
            "mode": mode,
            "direction_match": direction_match,
            "shrink_exit_direction": shrink_exit_direction,
            "shrink_pct": shrink_pct,
            "shrink_bars": shrink_bars,
            "required_bars": required_bars,
            "required_pct": required_pct,
            "stable_continuation_active": stable_continuation_active,
            "continuation_source": continuation_source,
        }
    
    # ==================== MACD 方向检测 ====================
    
    def detect_macd_direction(
        self,
        macd_hist: np.ndarray,
        idx: int
    ) -> Tuple[Optional[str], Dict]:
        """
        通用MACD方向检测。

        信号类型：
        - flip_bullish: 翻红（负转正），强度1.0
        - flip_bearish: 翻绿（正转负），强度1.0
        - red_bar_growing: 红柱增长，强度0.8
        - green_bar_growing: 绿柱增长，强度0.8
        - red_bar_shrinking: 红柱缩短，不入场
        - green_bar_shrinking: 绿柱缩短，不入场
        """
        if idx < 3:
            return None, {}
        
        details = {}
        hist_0 = macd_hist[idx]
        hist_1 = macd_hist[idx - 1]
        
        direction = None
        signal_type = None
        signal_strength = 0.0
        
        # 翻红检测（负转正）
        if hist_1 <= 0 and hist_0 > 0:
            direction = 'long'
            signal_type = 'flip_bullish'
            signal_strength = 1.0
            
        # 翻绿检测（正转负）
        elif hist_1 >= 0 and hist_0 < 0:
            direction = 'short'
            signal_type = 'flip_bearish'
            signal_strength = 1.0
            
        # 红柱增长
        elif hist_0 > 0 and hist_1 > 0 and hist_0 > hist_1:
            direction = 'long'
            signal_type = 'red_bar_growing'
            signal_strength = 0.8
            
        # 绿柱增长
        elif hist_0 < 0 and hist_1 < 0 and hist_0 < hist_1:
            direction = 'short'
            signal_type = 'green_bar_growing'
            signal_strength = 0.8
            
        # 红柱缩短（不入场）
        elif hist_0 > 0 and hist_1 > 0 and hist_0 < hist_1:
            direction = None
            signal_type = 'red_bar_shrinking'
            signal_strength = 0.0
            
        # 绿柱缩短（不入场）
        elif hist_0 < 0 and hist_1 < 0 and hist_0 > hist_1:
            direction = None
            signal_type = 'green_bar_shrinking'
            signal_strength = 0.0
        
        details['signal_type'] = signal_type
        details['signal_strength'] = signal_strength
        details['hist_current'] = hist_0
        details['hist_prev'] = hist_1
        
        return direction, details

    def detect_1h_macd_direction(
        self,
        macd_hist_1h: np.ndarray,
        idx: int
    ) -> Tuple[Optional[str], Dict]:
        """兼容旧调用：1H MACD方向检测。"""
        return self.detect_macd_direction(macd_hist_1h, idx)

    def resolve_primary_direction(
        self,
        *,
        direction_1h: Optional[str],
        details_1h: Dict[str, Any],
        direction_4h: Optional[str],
        details_4h: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
        """根据配置决定交易主方向，并在 4H 主方向模式下检查 1H 辅助确认。"""
        mode = str(self.config.primary_direction_timeframe or "4h").strip().lower()
        debug: Dict[str, Any] = {
            "primary_direction_timeframe": mode,
            "direction_1h": direction_1h or "neutral",
            "direction_4h": direction_4h or "neutral",
        }

        if mode != "4h":
            return direction_1h, None, debug

        if direction_4h is None:
            return None, "4H无明确方向", debug

        if not self.config.require_1h_confirmation_when_4h_primary:
            return direction_4h, None, debug

        if direction_1h is None:
            if self.config.allow_neutral_1h_confirmation:
                debug["confirmation_status"] = "neutral_allowed"
                return direction_4h, None, debug
            debug["confirmation_status"] = "missing"
            return None, "1H无确认信号", debug

        if direction_1h != direction_4h:
            if self.use_light_1h_confirmation():
                debug["confirmation_status"] = "opposite_light_allowed"
                debug["confirmation_signal_type_1h"] = details_1h.get("signal_type")
                debug["light_confirmation_soft_pass"] = True
                debug["light_confirmation_opposite_direction"] = direction_1h
                return direction_4h, None, debug
            debug["confirmation_status"] = "opposite"
            return None, f"1H方向反向({direction_1h}->{direction_4h})", debug

        debug["confirmation_status"] = "aligned"
        debug["confirmation_signal_type_1h"] = details_1h.get("signal_type")
        return direction_4h, None, debug

    def use_light_1h_confirmation(self) -> bool:
        mode = str(self.config.primary_direction_timeframe or "4h").strip().lower()
        return mode == "4h" and bool(self.config.light_1h_confirmation_when_4h_primary)

    def use_soft_15m_confirmation(self) -> bool:
        mode = str(self.config.primary_direction_timeframe or "4h").strip().lower()
        return mode == "4h" and bool(self.config.enable_soft_15m_confirmation_when_4h_primary)

    def soften_15m_entry_when_4h_primary(
        self,
        can_enter: bool,
        entry_score_15m: float,
        details_15m: Dict[str, Any],
        direction: str,
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """4H 主周期下放宽 15m 准入，只保留弱逆势和近零轴容忍。"""
        if can_enter or not self.use_soft_15m_confirmation():
            return can_enter, entry_score_15m, details_15m

        details = dict(details_15m or {})
        hist_0 = float(details.get("hist_current", 0.0) or 0.0)
        hist_1 = float(details.get("hist_prev", hist_0) or hist_0)
        neutral_band = max(
            abs(self.config.macd_threshold) * max(float(self.config.soft_15m_neutral_hist_multiple), 1.0),
            1e-9,
        )
        max_adverse = neutral_band * max(float(self.config.soft_15m_max_adverse_hist_multiple), 1.0)
        soft_score = max(entry_score_15m, float(self.config.soft_15m_entry_score))

        if direction == "long":
            near_neutral = hist_0 >= -neutral_band
            recovering = hist_0 > hist_1 and hist_0 >= -max_adverse
            if near_neutral or recovering:
                details["soft_15m_confirmation"] = True
                details["soft_15m_confirmation_reason"] = "near_neutral" if near_neutral else "recovering"
                details["entry_type"] = "soft_long_neutral" if near_neutral else "soft_long_recovery"
                details["base_entry_score"] = soft_score
                return True, soft_score, details

        elif direction == "short":
            near_neutral = hist_0 <= neutral_band
            recovering = hist_0 < hist_1 and hist_0 <= max_adverse
            if near_neutral or recovering:
                details["soft_15m_confirmation"] = True
                details["soft_15m_confirmation_reason"] = "near_neutral" if near_neutral else "recovering"
                details["entry_type"] = "soft_short_neutral" if near_neutral else "soft_short_recovery"
                details["base_entry_score"] = soft_score
                return True, soft_score, details

        return can_enter, entry_score_15m, details

    def check_weak_signal_combo_veto(
        self,
        *,
        trade_direction: str,
        signal_type_1h: Optional[str],
        entry_type_15m: Optional[str],
    ) -> Tuple[VetoType, Dict[str, Any]]:
        signal_type = str(signal_type_1h or "").strip().lower()
        entry_type = str(entry_type_15m or "").strip().lower()
        details = {
            "weak_combo_veto": False,
            "signal_type_1h": signal_type,
            "entry_type_15m": entry_type,
            "veto_reason": "",
        }

        if (
            trade_direction == "short"
            and signal_type == "green_bar_shrinking"
            and entry_type.startswith("soft_short_")
        ):
            details["weak_combo_veto"] = True
            details["veto_reason"] = "green_bar_shrinking_soft_short"
            return VetoType.WEAK_SIGNAL_COMBO, details

        if (
            trade_direction == "long"
            and signal_type == "red_bar_shrinking"
            and entry_type.startswith("soft_long_")
        ):
            details["weak_combo_veto"] = True
            details["veto_reason"] = "red_bar_shrinking_soft_long"
            return VetoType.WEAK_SIGNAL_COMBO, details

        return VetoType.NONE, details
    
    # ==================== MACD_4H 确认增强 ====================
    
    def check_4h_macd_enhancement(
        self,
        macd_hist_4h: np.ndarray,
        idx: int,
        direction: str
    ) -> Tuple[bool, float]:
        """MACD_4H确认方向增强"""
        if idx < 2:
            return False, 0.0
        
        hist_0 = macd_hist_4h[idx]
        hist_1 = macd_hist_4h[idx - 1]
        
        enhancement_score = 0.0
        is_enhanced = False
        
        if direction == 'long':
            if hist_0 > 0:
                enhancement_score += 0.5
                if hist_0 > hist_1:
                    enhancement_score += 0.3
                    is_enhanced = True
                elif hist_0 < hist_1:
                    enhancement_score += 0.1
                    
        elif direction == 'short':
            if hist_0 < 0:
                enhancement_score += 0.5
                if hist_1 < 0 and hist_0 < hist_1:
                    enhancement_score += 0.3
                    is_enhanced = True
                elif hist_0 > hist_1:
                    enhancement_score += 0.1
        
        return is_enhanced, enhancement_score
    
    # ==================== MACD_15M 跟随入场 ====================
    
    def check_15m_macd_follow(
        self,
        macd_hist_15m: np.ndarray,
        idx: int,
        direction: str,
        bb_middle_15m: float = None,
        bb_upper_15m: float = None,
        bb_lower_15m: float = None,
        close_15m: float = None,
        close_15m_series: Optional[np.ndarray] = None,
        close_1h_series: Optional[np.ndarray] = None,
        close_4h_series: Optional[np.ndarray] = None,
    ) -> Tuple[bool, float, Dict]:
        """
        MACD_15M跟随1H方向执行买卖
        
        V2.0新增：BOLL中轨精化入场点位
        """
        if idx < 2:
            return False, 0.0, {}
        
        details = {}
        hist_0 = macd_hist_15m[idx]
        hist_1 = macd_hist_15m[idx - 1]
        
        entry_score = 0.0
        can_enter = False
        
        if direction == 'long':
            # 刚翻红（最强入场）
            if hist_1 <= 0 and hist_0 > 0:
                entry_score = 1.0
                can_enter = True
                details['entry_type'] = 'flip_bullish'
                
            # 红柱增长
            elif hist_0 > 0 and hist_1 > 0 and hist_0 > hist_1:
                entry_score = 0.85
                can_enter = True
                details['entry_type'] = 'red_bar_growing'
                
            # 红柱稳定
            elif hist_0 > self.config.macd_threshold and hist_0 > 0:
                entry_score = 0.6
                can_enter = True
                details['entry_type'] = 'red_bar_stable'
                
            # 红柱缩短
            elif hist_0 > 0 and hist_1 > 0 and hist_0 < hist_1:
                entry_score = 0.3
                can_enter = True
                details['entry_type'] = 'red_bar_shrinking'
                
        elif direction == 'short':
            # 刚翻绿
            if hist_1 >= 0 and hist_0 < 0:
                entry_score = 1.0
                can_enter = True
                details['entry_type'] = 'flip_bearish'
                
            # 绿柱增长
            elif hist_0 < 0 and hist_1 < 0 and hist_0 < hist_1:
                entry_score = 0.85
                can_enter = True
                details['entry_type'] = 'green_bar_growing'
                
            # 绿柱稳定
            elif hist_0 < -self.config.macd_threshold and hist_0 < 0:
                entry_score = 0.6
                can_enter = True
                details['entry_type'] = 'green_bar_stable'
                
            # 绿柱缩短
            elif hist_0 < 0 and hist_1 < 0 and hist_0 > hist_1:
                entry_score = 0.3
                can_enter = True
                details['entry_type'] = 'green_bar_shrinking'
        
        if can_enter and self.config.enable_rsi_entry_refinement:
            rsi_refine = self._resolve_rsi_entry_refinement(
                direction=direction,
                entry_score=entry_score,
                close_15m_series=close_15m_series,
                close_1h_series=close_1h_series,
                close_4h_series=close_4h_series,
            )
            entry_score = float(rsi_refine.get("entry_score", entry_score))
            details['ema_15m_refine'] = rsi_refine.get("refine")
            details['rsi_15m'] = rsi_refine.get("rsi_15m")
            details['rsi_15m_prev'] = rsi_refine.get("rsi_15m_prev")
            details['rsi_1h'] = rsi_refine.get("rsi_1h")
            details['rsi_4h'] = rsi_refine.get("rsi_4h")
            details['rsi_15m_recent_min'] = rsi_refine.get("rsi_15m_recent_min")
            details['rsi_15m_recent_max'] = rsi_refine.get("rsi_15m_recent_max")
            details['rsi_1h_recent_reset_min'] = rsi_refine.get("rsi_1h_recent_reset_min")
            details['rsi_1h_recent_reset_max'] = rsi_refine.get("rsi_1h_recent_reset_max")
            details['price_break_high'] = rsi_refine.get("price_break_high")
            details['price_break_low'] = rsi_refine.get("price_break_low")
        elif can_enter and bb_middle_15m is not None and bb_middle_15m > 0 and close_15m is not None:
            # 兼容旧版：仅在未启用 RSI 精化时回退到 BOLL 中轨逻辑
            band_half_width = 0.0
            if bb_upper_15m is not None and bb_lower_15m is not None and bb_upper_15m > bb_lower_15m:
                band_half_width = max((bb_upper_15m - bb_lower_15m) * 0.5, bb_middle_15m * 0.002)
            else:
                band_half_width = bb_middle_15m * 0.003
            near_middle = abs(close_15m - bb_middle_15m) <= band_half_width
            if direction == 'long':
                if near_middle:
                    entry_score = min(entry_score * 1.15, 1.0)
                    details['ema_15m_refine'] = 'midline_bounce'
                elif close_15m < bb_middle_15m:
                    entry_score *= 0.7
                    details['ema_15m_refine'] = 'below_midline'
            elif direction == 'short':
                if near_middle:
                    entry_score = min(entry_score * 1.15, 1.0)
                    details['ema_15m_refine'] = 'midline_reject'
                elif close_15m > bb_middle_15m:
                    entry_score *= 0.7
                    details['ema_15m_refine'] = 'above_midline'
        
        details['hist_current'] = hist_0
        details['hist_prev'] = hist_1
        details['base_entry_score'] = entry_score
        
        return can_enter, entry_score, details
    
    # ==================== VWAP 过滤层（新增） ====================

    def _vwap_score_result(
        self,
        location_score: float,
        veto_type: VetoType,
        details: Dict[str, Any],
    ) -> Tuple[float, VetoType, Dict[str, Any]]:
        quality_score = round(max(0.0, min(1.0, float(location_score or 0.0))), 4)
        alpha_score = round(float(self.config.weight_vwap) * quality_score, 4)
        payload = dict(details)
        payload.setdefault("location_score", quality_score)
        payload["vwap_quality_score"] = quality_score
        payload["vwap_alpha_score"] = alpha_score
        payload["vwap_missing"] = bool(payload.get("vwap_missing", False))
        return quality_score, veto_type, payload
    
    def calculate_vwap_score(
        self,
        price: float,
        vwap: float,
        direction: str,
        *,
        structural_vwap: Optional[float] = None,
        price_series: Optional[np.ndarray] = None,
        session_vwap_series: Optional[np.ndarray] = None,
        structural_vwap_series: Optional[np.ndarray] = None,
    ) -> Tuple[float, VetoType, Dict[str, Any]]:
        """
        VWAP评分计算（位置状态 + 连续分数）
        
        返回：
        - score: raw location quality 0-1
        - veto_type: 是否触发否决
        - details: 位置状态与连续评分细节
        """
        structural_vwap_value = float(structural_vwap) if structural_vwap is not None else 0.0
        if structural_vwap_value <= 0.0:
            structural_vwap_value = self._series_value(structural_vwap_series, default=0.0)

        if vwap <= 0:
            location_score = 0.0
            veto_type = VetoType.VWAP_MISSING_HARD_BLOCK if self.config.require_vwap_for_entry else VetoType.NONE
            return self._vwap_score_result(location_score, veto_type, {
                "state": "no_vwap",
                "location_score": location_score,
                "entry_edge": 0.0,
                "directional_extension": 0.0,
                "entry_edge_quality": 0.0,
                "value_proximity_quality": 0.0,
                "extension_quality": 0.0,
                "session_vwap": vwap,
                "structural_vwap": structural_vwap_value,
                "session_deviation": 0.0,
                "structural_deviation": 0.0,
                "vwap_missing": True,
            })

        deviation = (price - vwap) / vwap
        if structural_vwap_value <= 0:
            if direction == 'long':
                directional_extension = deviation
                entry_edge = -deviation
                if directional_extension > self.config.vwap_deviation_hard_block:
                    return self._vwap_score_result(0.0, VetoType.VWAP_HARD_BLOCK, {
                        "state": "long_overextended_above_value",
                        "location_score": 0.0,
                        "entry_edge": entry_edge,
                        "directional_extension": directional_extension,
                        "session_vwap": vwap,
                        "structural_vwap": structural_vwap_value,
                        "session_deviation": deviation,
                        "structural_deviation": deviation,
                    })
                if deviation >= self.config.vwap_deviation_warning:
                    state = "long_above_value_extension"
                elif deviation >= self.config.vwap_deviation_optimal:
                    state = "long_above_value"
                elif deviation >= -self.config.vwap_deviation_optimal:
                    state = "long_value_reclaim"
                elif deviation >= -self.config.vwap_deviation_warning:
                    state = "long_discount_pullback"
                else:
                    state = "long_deep_discount"
            elif direction == 'short':
                directional_extension = -deviation
                entry_edge = deviation
                if directional_extension > self.config.vwap_deviation_hard_block:
                    return self._vwap_score_result(0.0, VetoType.VWAP_HARD_BLOCK, {
                        "state": "short_overextended_below_value",
                        "location_score": 0.0,
                        "entry_edge": entry_edge,
                        "directional_extension": directional_extension,
                        "session_vwap": vwap,
                        "structural_vwap": structural_vwap_value,
                        "session_deviation": deviation,
                        "structural_deviation": deviation,
                    })
                if deviation <= -self.config.vwap_deviation_warning:
                    state = "short_below_value_extension"
                elif deviation <= -self.config.vwap_deviation_optimal:
                    state = "short_below_value"
                elif deviation <= self.config.vwap_deviation_optimal:
                    state = "short_value_reject"
                elif deviation <= self.config.vwap_deviation_warning:
                    state = "short_premium_retest"
                else:
                    state = "short_stretched_premium"
            else:
                location_score = 0.5
                return self._vwap_score_result(location_score, VetoType.NONE, {
                    "state": "neutral",
                    "location_score": location_score,
                    "entry_edge": 0.0,
                    "directional_extension": 0.0,
                    "entry_edge_quality": 0.5,
                    "value_proximity_quality": 0.5,
                    "extension_quality": 0.5,
                    "session_vwap": vwap,
                    "structural_vwap": structural_vwap_value,
                    "session_deviation": deviation,
                    "structural_deviation": deviation,
                })

            hard_block = max(self.config.vwap_deviation_hard_block, 1e-9)
            warning = max(self.config.vwap_deviation_warning, 1e-9)
            entry_edge_quality = 0.5 + 0.5 * self._clamp(entry_edge / warning, -1.0, 1.0)
            value_proximity_quality = 1.0 - self._clamp(abs(deviation) / hard_block, 0.0, 1.0)
            extension_quality = 1.0 - self._clamp(max(0.0, directional_extension) / hard_block, 0.0, 1.0)
            location_score = self._clamp(
                0.75 * entry_edge_quality
                + 0.15 * value_proximity_quality
                + 0.10 * extension_quality,
                0.0,
                1.0,
            )
            return self._vwap_score_result(location_score, VetoType.NONE, {
                "state": state,
                "location_score": location_score,
                "entry_edge": entry_edge,
                "directional_extension": directional_extension,
                "entry_edge_quality": entry_edge_quality,
                "value_proximity_quality": value_proximity_quality,
                "extension_quality": extension_quality,
                "session_vwap": vwap,
                "structural_vwap": structural_vwap_value,
                "session_deviation": deviation,
                "structural_deviation": deviation,
            })

        structural_deviation = (price - structural_vwap_value) / structural_vwap_value
        tolerance = max(self.config.vwap_retest_tolerance, 1e-4)
        warning = max(self.config.vwap_deviation_warning, tolerance * 2.0)
        hard_block = max(self.config.vwap_deviation_hard_block, warning + 1e-6)
        prev_price = self._series_value(price_series, offset=-2, default=price)
        prev_session_vwap = self._series_value(session_vwap_series, offset=-2, default=vwap)
        prev_structural_vwap = self._series_value(
            structural_vwap_series,
            offset=-2,
            default=structural_vwap_value,
        )

        session_below = deviation < -tolerance
        session_above = deviation > tolerance
        structure_below = structural_deviation < -tolerance
        structure_above = structural_deviation > tolerance
        session_near = abs(deviation) <= tolerance
        structure_near = abs(structural_deviation) <= tolerance

        short_retest_reject = (
            prev_session_vwap > 0
            and prev_price >= prev_session_vwap * (1.0 - tolerance)
            and price < vwap * (1.0 - tolerance)
            and (structure_below or structure_near)
            and prev_price <= prev_structural_vwap * (1.0 + warning)
        )
        long_reclaim_confirmed = (
            prev_session_vwap > 0
            and prev_price <= prev_session_vwap * (1.0 + tolerance)
            and price > vwap * (1.0 + tolerance)
            and (not structure_above or price >= structural_vwap_value * (1.0 - tolerance))
            and prev_price >= prev_structural_vwap * (1.0 - warning)
        )

        if direction == 'short':
            directional_extension = -deviation
            entry_edge = deviation
            if directional_extension > self.config.vwap_deviation_hard_block:
                return self._vwap_score_result(0.0, VetoType.VWAP_HARD_BLOCK, {
                    "state": "short_overextended_below_value",
                    "location_score": 0.0,
                    "entry_edge": entry_edge,
                    "directional_extension": directional_extension,
                    "session_vwap": vwap,
                    "structural_vwap": structural_vwap_value,
                    "session_deviation": deviation,
                    "structural_deviation": structural_deviation,
                })
            if short_retest_reject:
                state = "short_retest_reject"
            elif session_below and structure_below:
                state = "short_dual_pressure"
            elif structure_below and (session_near or session_above):
                state = "short_under_structure_wait_reject"
            elif session_below and (structure_near or structure_above):
                state = "short_below_session_above_structure"
            else:
                state = "short_above_both"

            session_pressure_quality = self._clamp((-deviation + tolerance) / (warning + tolerance), 0.0, 1.0)
            structural_pressure_quality = self._clamp(
                (-structural_deviation + tolerance) / (warning + tolerance),
                0.0,
                1.0,
            )
            extension_penalty = self._clamp(
                max(0.0, -deviation - warning) / max(hard_block - warning, 1e-9),
                0.0,
                1.0,
            )
            retest_quality = 1.0 if short_retest_reject else 0.0
            dual_pressure_quality = 1.0 if (session_below and structure_below) else 0.0
            value_proximity_quality = 1.0 - self._clamp(abs(deviation) / hard_block, 0.0, 1.0)
            extension_quality = 1.0 - extension_penalty
            location_score = self._clamp(
                0.36 * session_pressure_quality
                + 0.26 * structural_pressure_quality
                + 0.18 * retest_quality
                + 0.12 * dual_pressure_quality
                + 0.08 * value_proximity_quality
                - 0.12 * extension_penalty,
                0.0,
                1.0,
            )
            return self._vwap_score_result(location_score, VetoType.NONE, {
                "state": state,
                "location_score": location_score,
                "entry_edge": entry_edge,
                "directional_extension": directional_extension,
                "entry_edge_quality": session_pressure_quality,
                "value_proximity_quality": value_proximity_quality,
                "extension_quality": extension_quality,
                "structure_quality": structural_pressure_quality,
                "retest_quality": retest_quality,
                "dual_pressure_quality": dual_pressure_quality,
                "session_vwap": vwap,
                "structural_vwap": structural_vwap_value,
                "session_deviation": deviation,
                "structural_deviation": structural_deviation,
            })

        if direction == 'long':
            directional_extension = deviation
            entry_edge = -deviation
            if directional_extension > self.config.vwap_deviation_hard_block:
                return self._vwap_score_result(0.0, VetoType.VWAP_HARD_BLOCK, {
                    "state": "long_overextended_above_value",
                    "location_score": 0.0,
                    "entry_edge": entry_edge,
                    "directional_extension": directional_extension,
                    "session_vwap": vwap,
                    "structural_vwap": structural_vwap_value,
                    "session_deviation": deviation,
                    "structural_deviation": structural_deviation,
                })
            if long_reclaim_confirmed:
                state = "long_reclaim_confirmed"
            elif session_above and structure_above:
                state = "long_dual_support"
            elif structure_above and (session_near or session_below):
                state = "long_above_structure_wait_reclaim"
            elif session_above and (structure_near or structure_below):
                state = "long_above_session_below_structure"
            else:
                state = "long_below_both"

            session_support_quality = self._clamp((deviation + tolerance) / (warning + tolerance), 0.0, 1.0)
            structural_support_quality = self._clamp(
                (structural_deviation + tolerance) / (warning + tolerance),
                0.0,
                1.0,
            )
            extension_penalty = self._clamp(
                max(0.0, deviation - warning) / max(hard_block - warning, 1e-9),
                0.0,
                1.0,
            )
            reclaim_quality = 1.0 if long_reclaim_confirmed else 0.0
            dual_support_quality = 1.0 if (session_above and structure_above) else 0.0
            value_proximity_quality = 1.0 - self._clamp(abs(deviation) / hard_block, 0.0, 1.0)
            extension_quality = 1.0 - extension_penalty
            location_score = self._clamp(
                0.36 * session_support_quality
                + 0.26 * structural_support_quality
                + 0.18 * reclaim_quality
                + 0.12 * dual_support_quality
                + 0.08 * value_proximity_quality
                - 0.12 * extension_penalty,
                0.0,
                1.0,
            )
            return self._vwap_score_result(location_score, VetoType.NONE, {
                "state": state,
                "location_score": location_score,
                "entry_edge": entry_edge,
                "directional_extension": directional_extension,
                "entry_edge_quality": session_support_quality,
                "value_proximity_quality": value_proximity_quality,
                "extension_quality": extension_quality,
                "structure_quality": structural_support_quality,
                "reclaim_quality": reclaim_quality,
                "dual_support_quality": dual_support_quality,
                "session_vwap": vwap,
                "structural_vwap": structural_vwap_value,
                "session_deviation": deviation,
                "structural_deviation": structural_deviation,
            })

        location_score = 0.5
        return self._vwap_score_result(location_score, VetoType.NONE, {
            "state": "neutral",
            "location_score": location_score,
            "entry_edge": 0.0,
            "directional_extension": 0.0,
            "entry_edge_quality": 0.5,
            "value_proximity_quality": 0.5,
            "extension_quality": 0.5,
            "session_vwap": vwap,
            "structural_vwap": structural_vwap_value,
            "session_deviation": deviation,
            "structural_deviation": structural_deviation,
        })

    def check_flip_bearish_structure(
        self,
        signal_type_1h: str,
        adx_1h: float,
        bb_middle_slope_1h: float,
        bb_middle_slope_4h: float,
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        if signal_type_1h != 'flip_bearish':
            return True, [], {}

        reasons: List[str] = []
        details = {
            "adx_1h": adx_1h,
            "bb_middle_slope_1h": bb_middle_slope_1h,
            "bb_middle_slope_4h": bb_middle_slope_4h,
            "flip_bearish_min_adx_1h": self.config.flip_bearish_min_adx_1h,
            "flip_bearish_max_bb_middle_slope_1h": self.config.flip_bearish_max_ema21_slope_1h,
            "flip_bearish_max_bb_middle_slope_4h": self.config.flip_bearish_max_ema21_slope_4h,
        }

        if self.config.flip_bearish_min_adx_1h > 0 and adx_1h < self.config.flip_bearish_min_adx_1h:
            reasons.append(f"adx_1h={adx_1h:.2f}<{self.config.flip_bearish_min_adx_1h:.2f}")
        if bb_middle_slope_1h > self.config.flip_bearish_max_ema21_slope_1h:
            reasons.append(
                f"bb_middle_slope_1h={bb_middle_slope_1h:.4f}>{self.config.flip_bearish_max_ema21_slope_1h:.4f}"
            )
        if bb_middle_slope_4h > self.config.flip_bearish_max_ema21_slope_4h:
            reasons.append(
                f"bb_middle_slope_4h={bb_middle_slope_4h:.4f}>{self.config.flip_bearish_max_ema21_slope_4h:.4f}"
            )

        return len(reasons) == 0, reasons, details

    def check_flip_bearish_vwap_context(
        self,
        signal_type_1h: str,
        vwap_state: str,
        vwap_score: float,
        structural_vwap: float,
        session_deviation: float,
        structural_deviation: float,
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        if signal_type_1h != 'flip_bearish':
            return True, [], {}

        reasons: List[str] = []
        allowed_states = {"short_retest_reject", "short_dual_pressure"}
        if structural_vwap <= 0:
            reasons.append("structural_vwap_missing")
        if vwap_state not in allowed_states:
            reasons.append(f"vwap_state={vwap_state}")
        retest_reject_min_vwap_score = max(0.0, self.config.flip_bearish_retest_reject_min_vwap_score)
        if (
            vwap_state == "short_retest_reject"
            and retest_reject_min_vwap_score > 0
            and vwap_score < retest_reject_min_vwap_score
        ):
            reasons.append(
                f"short_retest_reject_vwap_score={vwap_score:.2f}<{retest_reject_min_vwap_score:.2f}"
            )

        details = {
            "flip_bearish_allowed_vwap_states": sorted(allowed_states),
            "vwap_state": vwap_state,
            "vwap_score": vwap_score,
            "flip_bearish_retest_reject_min_vwap_score": retest_reject_min_vwap_score,
            "structural_vwap": structural_vwap,
            "session_vwap_deviation": session_deviation,
            "structural_vwap_deviation": structural_deviation,
        }
        return len(reasons) == 0, reasons, details

    # ==================== BOLL 结构层（新增） ====================
    
    def check_boll_structure(
        self,
        close_1h: float,
        bb_middle_1h: float,
        bb_upper_1h: float,
        bb_lower_1h: float,
        bb_middle_4h: float = 0.0,
        bb_upper_4h: float = 0.0,
        bb_lower_4h: float = 0.0,
        direction: str = None
    ) -> Tuple[float, str, VetoType]:
        """
        BOLL结构检查

        返回：
        - multiplier: 结构修正系数 (0.6/1.0/1.2)
        - status: 结构状态
        - veto_type: 否决类型
        """
        if bb_middle_1h <= 0 or bb_upper_1h <= bb_lower_1h:
            return self.config.ema_multiplier_normal, 'neutral', VetoType.NONE

        band_half_1h = max((bb_upper_1h - bb_lower_1h) * 0.5, 1e-9)
        pos_1h = (close_1h - bb_middle_1h) / band_half_1h

        pos_4h = 0.0
        if bb_middle_4h > 0 and bb_upper_4h > bb_lower_4h:
            band_half_4h = max((bb_upper_4h - bb_lower_4h) * 0.5, 1e-9)
            pos_4h = (close_1h - bb_middle_4h) / band_half_4h

        if direction == 'long':
            if pos_1h >= 0.20 and pos_4h >= 0.10:
                return self.config.ema_multiplier_strong, 'strong', VetoType.NONE
            if pos_1h >= 0.0:
                return self.config.ema_multiplier_normal, 'normal', VetoType.NONE
            if close_1h >= bb_lower_1h:
                return self.config.ema_multiplier_weak, 'weak', VetoType.NONE
            return self.config.ema_multiplier_weak, 'against', VetoType.NONE

        if direction == 'short':
            if pos_1h <= -0.20 and pos_4h <= -0.10:
                return self.config.ema_multiplier_strong, 'strong', VetoType.NONE
            if pos_1h <= 0.0:
                return self.config.ema_multiplier_normal, 'normal', VetoType.NONE
            if close_1h <= bb_upper_1h:
                return self.config.ema_multiplier_weak, 'weak', VetoType.NONE
            return self.config.ema_multiplier_weak, 'against', VetoType.NONE

        return self.config.ema_multiplier_normal, 'neutral', VetoType.NONE
    
    def check_boll_deviation_veto(
        self,
        close_1h: float,
        bb_middle_1h: float,
        bb_upper_1h: float,
        bb_lower_1h: float,
        signal_type_1h: str
    ) -> VetoType:
        """
        否决项V5：MACD翻色时价格已远离BOLL中轨且明显超带，不追单
        """
        if signal_type_1h not in ['flip_bullish', 'flip_bearish']:
            return VetoType.NONE
        
        if bb_middle_1h <= 0 or bb_upper_1h <= bb_lower_1h:
            return VetoType.NONE
        
        band_half = max((bb_upper_1h - bb_lower_1h) * 0.5, 1e-9)
        band_extension = abs(close_1h - bb_middle_1h) / band_half
        
        if band_extension > 1.8:
            return VetoType.MACD_HIGH_DEVIATION
        
        return VetoType.NONE

    # ==================== 止损计算 ====================
    
    def calculate_dynamic_stop(
        self,
        entry_price: float,
        close_1h: float,
        bb_middle_1h: float,
        bb_upper_1h: float,
        bb_lower_1h: float,
        atr_1h: float,
        vwap: float,
        direction: str,
        symbol: Optional[str] = None,
    ) -> Tuple[float, float, Dict]:
        """
        计算动态止损
        
        返回：
        - stop_price: 止损价格
        - stop_pct: 止损百分比
        - details: 详情
        """
        details = {}
        max_stop_loss_pct, symbol_override_applied = self.resolve_symbol_max_stop_loss_pct(symbol)
        details['effective_max_stop_loss_pct'] = max_stop_loss_pct
        details['symbol_stop_override_applied'] = symbol_override_applied
        
        if direction == 'long':
            if bb_middle_1h > 0 and close_1h >= bb_middle_1h:
                stop = bb_middle_1h - atr_1h * self.config.ema_stop_atr_multiplier
                details['stop_anchor'] = 'bb_middle'
            elif bb_lower_1h > 0:
                stop = bb_lower_1h - atr_1h * 0.2
                details['stop_anchor'] = 'bb_lower'
            else:
                stop = entry_price * (1 - max_stop_loss_pct)
                details['stop_anchor'] = 'default'
            
            max_stop = entry_price * (1 - max_stop_loss_pct)
            stop = max(stop, max_stop)
            
            if vwap > 0:
                vwap_alert = vwap * (1 - self.config.vwap_alert_deviation)
                details['vwap_alert_price'] = vwap_alert
            
        elif direction == 'short':
            if bb_middle_1h > 0 and close_1h <= bb_middle_1h:
                stop = bb_middle_1h + atr_1h * self.config.ema_stop_atr_multiplier
                details['stop_anchor'] = 'bb_middle'
            elif bb_upper_1h > 0:
                stop = bb_upper_1h + atr_1h * 0.2
                details['stop_anchor'] = 'bb_upper'
            else:
                stop = entry_price * (1 + max_stop_loss_pct)
                details['stop_anchor'] = 'default'
            
            max_stop = entry_price * (1 + max_stop_loss_pct)
            stop = min(stop, max_stop)
            
            if vwap > 0:
                vwap_alert = vwap * (1 + self.config.vwap_alert_deviation)
                details['vwap_alert_price'] = vwap_alert
        else:
            stop = entry_price * (1 - max_stop_loss_pct)
            details['stop_anchor'] = 'default'
        
        stop_pct = abs(entry_price - stop) / entry_price
        details['stop_price'] = stop
        details['stop_pct'] = stop_pct
        
        return stop, stop_pct, details
    
    # ==================== 综合分析 ====================
    
    def analyze(
        self,
        macd_hist_15m: np.ndarray,
        macd_hist_1h: np.ndarray,
        macd_hist_4h: np.ndarray,
        idx_15m: int,
        idx_1h: int,
        idx_4h: int,
        volume_ratio: float = 1.0,
        # VWAP数据
        vwap: float = 0.0,
        structural_vwap: float = 0.0,
        close_price: float = 0.0,
        # BOLL数据
        bb_middle_1h: float = 0.0,
        bb_upper_1h: float = 0.0,
        bb_lower_1h: float = 0.0,
        bb_middle_4h: float = 0.0,
        bb_upper_4h: float = 0.0,
        bb_lower_4h: float = 0.0,
        bb_middle_15m: float = 0.0,
        bb_upper_15m: float = 0.0,
        bb_lower_15m: float = 0.0,
        close_15m: float = 0.0,
        close_15m_series: Optional[np.ndarray] = None,
        close_1h_series: Optional[np.ndarray] = None,
        close_4h_series: Optional[np.ndarray] = None,
        vwap_1h_series: Optional[np.ndarray] = None,
        structural_vwap_1h_series: Optional[np.ndarray] = None,
        adx_1h: float = 0.0,
        adx_4h: float = 0.0,
        bb_middle_slope_1h: Optional[float] = None,
        bb_middle_slope_4h: Optional[float] = None,
        cvd_upper_wick_ratio: Optional[float] = None,
        cvd_1h_delta_ratio: Optional[float] = None,
        # ATR
        atr_1h: float = 0.0,
        # 空头质量过滤参数（V3专家组建议）
        funding_rate: float = 0.0,
        oi_delta_ratio: float = 0.0,
        symbol: Optional[str] = None,
    ) -> MACDSignalV2:
        """
        V2.0综合分析
        """
        debug_details = self._build_debug_details(
            strategy="macd_mtf_strategy_v2",
            stage="1h_direction",
            close_price=close_price,
            close_15m=close_15m,
            vwap=vwap,
            session_vwap=vwap,
            structural_vwap=structural_vwap,
            atr_1h=atr_1h,
            volume_ratio=volume_ratio,
            adx_1h=adx_1h,
            adx_4h=adx_4h,
        )
        if cvd_upper_wick_ratio is not None:
            debug_details["cvd_upper_wick_ratio"] = float(cvd_upper_wick_ratio)
        if cvd_1h_delta_ratio is not None:
            debug_details["cvd_1h_delta_ratio"] = float(cvd_1h_delta_ratio)
        if structural_vwap <= 0 and structural_vwap_1h_series is not None:
            structural_vwap = self._series_value(structural_vwap_1h_series, default=0.0)
        if bb_middle_1h <= 0 and close_1h_series is not None:
            middle_1h, upper_1h, lower_1h = self.calculate_bollinger_bands(
                np.asarray(close_1h_series, dtype=float),
                period=self.config.boll_period,
                std_dev=self.config.boll_std_dev,
            )
            bb_middle_1h = float(middle_1h[-1])
            bb_upper_1h = float(upper_1h[-1])
            bb_lower_1h = float(lower_1h[-1])
        if bb_middle_4h <= 0 and close_4h_series is not None:
            middle_4h, upper_4h, lower_4h = self.calculate_bollinger_bands(
                np.asarray(close_4h_series, dtype=float),
                period=self.config.boll_period,
                std_dev=self.config.boll_std_dev,
            )
            bb_middle_4h = float(middle_4h[-1])
            bb_upper_4h = float(upper_4h[-1])
            bb_lower_4h = float(lower_4h[-1])

        primary_mode = str(self.config.primary_direction_timeframe or "4h").strip().lower()
        light_1h_confirmation = self.use_light_1h_confirmation()
        rsi_period = max(2, int(self.config.rsi_period))
        rsi_15m_series = self.calculate_rsi_series(close_15m_series, period=rsi_period)
        rsi_1h_series = self.calculate_rsi_series(close_1h_series, period=rsi_period)
        rsi_4h_series = self.calculate_rsi_series(close_4h_series, period=rsi_period)
        rsi_rhythm: Optional[Dict[str, Any]] = None
        rsi_launch_sovereign = self._default_rsi_launch_sovereign_details()
        neutral_upgrade_considered = False
        neutral_upgrade_applied = False
        neutral_upgrade_penalty_mult = 1.0
        neutral_original_reason = ""
        neutral_upgrade_direction: Optional[str] = None
        neutral_upgrade_mode = "none"
        neutral_upgrade_threshold_override = 0.0

        # ========== Step 1: MACD_1H 辅助方向状态 ==========
        direction_1h, details_1h = self.detect_1h_macd_direction(macd_hist_1h, idx_1h)
        debug_details.update(
            direction_1h=direction_1h or "neutral",
            signal_type_1h=details_1h.get("signal_type"),
            signal_strength_1h=details_1h.get("signal_strength", 0.0),
            macd_1h_hist_current=details_1h.get("hist_current"),
            macd_1h_hist_prev=details_1h.get("hist_prev"),
        )

        # ========== Step 1.5: MACD_4H 主方向/主评分状态 ==========
        direction_4h, details_4h = self.detect_macd_direction(macd_hist_4h, idx_4h)
        signal_type_4h = str(details_4h.get("signal_type", ""))
        signal_strength_4h = float(details_4h.get("signal_strength", 0.0) or 0.0)
        shrink_4h_context = self._build_4h_shrink_context(macd_hist_4h, idx_4h, signal_type_4h)
        stable_trend_context = self._build_stable_trend_context(macd_hist_4h, idx_4h)
        debug_details.update(
            primary_timeframe=primary_mode,
            direction_4h=direction_4h or "neutral",
            signal_type_4h=signal_type_4h,
            signal_strength_4h=signal_strength_4h,
            macd_4h_hist_current=details_4h.get("hist_current"),
            macd_4h_hist_prev=details_4h.get("hist_prev"),
            macd_4h_shrink_pct=shrink_4h_context["shrink_pct"],
            macd_4h_shrink_bars=shrink_4h_context["shrink_bars"],
            macd_4h_preflip_direction=shrink_4h_context["preflip_direction"],
            macd_4h_exit_direction=shrink_4h_context["exit_direction"],
            macd_4h_shrink_exit_ready=shrink_4h_context["shrink_exit_ready"],
            shrink_exit_direction=shrink_4h_context["exit_direction"],
            shrink_exit_ready=shrink_4h_context["shrink_exit_ready"],
            stable_4h_hist_current=stable_trend_context["hist_current"],
            stable_4h_positive_bars=stable_trend_context["positive_bars"],
            stable_4h_negative_bars=stable_trend_context["negative_bars"],
            stable_4h_bull_active=stable_trend_context["bull_active"],
            stable_4h_bear_active=stable_trend_context["bear_active"],
        )

        trade_direction: Optional[str] = None
        direction_reject_reason: Optional[str] = None
        direction_debug: Dict[str, Any] = {}
        is_trial_entry = False
        entry_scale = 1.0
        stable_continuation_active = False
        stable_continuation_side: Optional[str] = None

        preflip_candidate_direction = shrink_4h_context.get("preflip_direction")
        preflip_enabled = (
            primary_mode == "4h"
            and bool(self.config.enable_4h_preflip_trial_entries)
            and preflip_candidate_direction is not None
        )
        preflip_trial_active = False
        if preflip_enabled and direction_4h is None:
            shrink_pct = float(shrink_4h_context["shrink_pct"])
            shrink_bars = int(shrink_4h_context.get("shrink_bars", 0) or 0)
            min_preflip_shrink_pct = (
                float(self.config.preflip_trial_min_shrink_pct_long)
                if preflip_candidate_direction == "long"
                else float(self.config.preflip_trial_min_shrink_pct_short)
            )
            direction_debug = {
                "preflip_trial_enabled": True,
                "preflip_candidate_direction": preflip_candidate_direction,
                "preflip_min_shrink_pct": min_preflip_shrink_pct,
            }
            if shrink_pct > 0.0 and shrink_bars > 0:
                if direction_1h is None:
                    if self.config.allow_neutral_1h_confirmation:
                        direction_debug["preflip_confirmation_status"] = "neutral_allowed"
                    else:
                        direction_debug["preflip_confirmation_status"] = "missing"
                elif direction_1h != preflip_candidate_direction:
                    direction_debug["preflip_confirmation_status"] = "opposite"
                elif shrink_pct < min_preflip_shrink_pct:
                    direction_debug["preflip_confirmation_status"] = "insufficient_shrink"
                else:
                    preflip_trial_active = True
                    trade_direction = preflip_candidate_direction
                    is_trial_entry = True
                    entry_scale = self._clamp(self.config.preflip_trial_entry_scale, 0.05, 1.0)
                    direction_debug.update(
                        preflip_confirmation_status="aligned",
                        preflip_trial_entry=True,
                        preflip_entry_scale=entry_scale,
                    )
            else:
                direction_debug.update(
                    preflip_confirmation_status="inactive_zero_shrink",
                    preflip_zero_shrink_fallback=True,
                )
        if not preflip_trial_active:
            preflip_fallback_debug = dict(direction_debug)
            trade_direction, direction_reject_reason, primary_direction_debug = self.resolve_primary_direction(
                direction_1h=direction_1h,
                details_1h=details_1h,
                direction_4h=direction_4h,
                details_4h=details_4h,
            )
            preflip_fallback_debug.update(primary_direction_debug)
            direction_debug = preflip_fallback_debug
            if trade_direction is None:
                recovered_direction, continuation_direction_debug = self._resolve_stable_continuation_direction(
                    primary_mode=primary_mode,
                    direction_1h=direction_1h,
                    details_1h=details_1h,
                    stable_trend_context=stable_trend_context,
                )
                direction_debug.update(continuation_direction_debug)
                if recovered_direction is not None:
                    trade_direction = recovered_direction
                    direction_reject_reason = None
        debug_details.update(
            **direction_debug,
            trade_direction=trade_direction or "neutral",
            light_1h_confirmation=light_1h_confirmation,
            is_trial_entry=is_trial_entry,
            entry_scale=entry_scale,
        )
        if trade_direction is None:
            neutral_original_reason = direction_reject_reason or "主方向无明确结论"
            neutral_upgrade_candidate = next((d for d in (direction_4h, direction_1h) if d in {"long", "short"}), None)
            neutral_upgrade_considered = bool(self.config.enable_neutral_upgrade and neutral_upgrade_candidate)
            debug_details = self._set_stage(
                debug_details,
                "neutral_upgrade_gate",
                neutral_upgrade_considered=neutral_upgrade_considered,
                neutral_original_reason=neutral_original_reason,
                neutral_upgrade_direction=neutral_upgrade_candidate,
            )
            if neutral_upgrade_considered and neutral_upgrade_candidate:
                neutral_rsi_rhythm = self.evaluate_rsi_rhythm(
                    direction=neutral_upgrade_candidate,
                    rsi_15m_series=rsi_15m_series,
                    rsi_1h_series=rsi_1h_series,
                    rsi_4h_series=rsi_4h_series,
                    close_15m_series=close_15m_series,
                    close_1h_series=close_1h_series,
                    close_4h_series=close_4h_series,
                    macd_hist_1h_current=self._series_value(macd_hist_1h[: idx_1h + 1], default=0.0),
                )
                rsi_rhythm = neutral_rsi_rhythm
                neutral_upgrade_direction = neutral_upgrade_candidate
                neutral_upgrade_raw = float(neutral_rsi_rhythm.get("raw_score", 0.0))
                debug_details = self._set_stage(
                    debug_details,
                    "neutral_upgrade_rsi",
                    neutral_upgrade_considered=True,
                    neutral_upgrade_raw_score=neutral_upgrade_raw,
                    neutral_upgrade_min_rsi_score=float(self.config.neutral_upgrade_min_rsi_score),
                    neutral_upgrade_hard_veto=bool(neutral_rsi_rhythm.get("hard_veto", False)),
                    neutral_upgrade_veto_reason=neutral_rsi_rhythm.get("veto_reason"),
                    neutral_upgrade_direction=neutral_upgrade_candidate,
                )
                neutral_upgrade_eval = self._evaluate_neutral_upgrade(
                    neutral_upgrade_candidate=neutral_upgrade_candidate,
                    neutral_upgrade_raw=neutral_upgrade_raw,
                    hard_veto=bool(neutral_rsi_rhythm.get("hard_veto", False)),
                )
                debug_details = self._set_stage(
                    debug_details,
                    "neutral_upgrade_mode",
                    neutral_upgrade_mode=neutral_upgrade_eval.get("mode"),
                    neutral_upgrade_probe_mode=bool(neutral_upgrade_eval.get("probe_mode", False)),
                    neutral_upgrade_threshold_override=float(neutral_upgrade_eval.get("threshold_override", 0.0)),
                )
                if bool(neutral_upgrade_eval.get("applied", False)):
                    trade_direction = neutral_upgrade_candidate
                    neutral_upgrade_applied = True
                    neutral_upgrade_penalty_mult = float(neutral_upgrade_eval.get("penalty_mult", self.config.neutral_upgrade_penalty_mult))
                    neutral_upgrade_mode = str(neutral_upgrade_eval.get("mode", "full"))
                    neutral_upgrade_threshold_override = float(neutral_upgrade_eval.get("threshold_override", 0.0))
                    if bool(neutral_upgrade_eval.get("probe_mode", False)):
                        neutral_rsi_rhythm["probe_mode"] = True
                    direction_reject_reason = None
                    debug_details.update(
                        trade_direction=trade_direction,
                        neutral_upgrade_applied=True,
                        neutral_upgrade_penalty_mult=neutral_upgrade_penalty_mult,
                        neutral_upgrade_mode=neutral_upgrade_mode,
                        neutral_upgrade_threshold_override=neutral_upgrade_threshold_override,
                        rsi_probe_mode=bool(neutral_rsi_rhythm.get("probe_mode", False)),
                    )
                else:
                    neutral_debug_details = dict(debug_details)
                    neutral_debug_details.update(
                        neutral_upgrade_applied=False,
                        neutral_upgrade_penalty_mult=1.0,
                        neutral_upgrade_mode=str(neutral_upgrade_eval.get("mode", "reject")),
                        neutral_upgrade_threshold_override=float(neutral_upgrade_eval.get("threshold_override", 0.0)),
                        neutral_upgrade_direction=neutral_upgrade_candidate,
                        neutral_upgrade_raw_score=neutral_upgrade_raw,
                        neutral_upgrade_veto_reason=neutral_rsi_rhythm.get("veto_reason"),
                        rsi_probe_mode=bool(neutral_rsi_rhythm.get("probe_mode", False)),
                        rsi_exposure_mult=float(neutral_rsi_rhythm.get("exposure_mult", 0.8)),
                    )
                    return self._neutral_signal(
                        reason=neutral_original_reason,
                        score=float(neutral_rsi_rhythm.get("weighted_score", 0.0)),
                        signal_type_1h=details_1h.get('signal_type'),
                        entry_type_15m=str(neutral_rsi_rhythm.get("entry_type") or ""),
                        entry_score_15m=float(neutral_rsi_rhythm.get("weighted_score", 0.0)),
                        vwap_score=0.0,
                        vwap_deviation=0.0,
                        ema_multiplier=1.0,
                        ema_structure_status="normal",
                        details=self._build_debug_details(**neutral_debug_details),
                    )
            else:
                neutral_debug_details = dict(debug_details)
                neutral_debug_details.update(
                    neutral_upgrade_considered=neutral_upgrade_considered,
                    neutral_upgrade_applied=False,
                    neutral_upgrade_penalty_mult=1.0,
                    neutral_upgrade_direction=neutral_upgrade_candidate,
                    neutral_original_reason=neutral_original_reason,
                )
                return self._neutral_signal(
                    reason=neutral_original_reason,
                    signal_type_1h=details_1h.get('signal_type'),
                    details=self._build_debug_details(**neutral_debug_details),
                )
        strict_1h_filters_enabled = not (light_1h_confirmation or is_trial_entry)
        
        # ========== Step 2: BOLL结构检查 ==========
        ema_multiplier, ema_status, ema_veto = self.check_boll_structure(
            close_1h=close_price,
            bb_middle_1h=bb_middle_1h,
            bb_upper_1h=bb_upper_1h,
            bb_lower_1h=bb_lower_1h,
            bb_middle_4h=bb_middle_4h,
            bb_upper_4h=bb_upper_4h,
            bb_lower_4h=bb_lower_4h,
            direction=trade_direction
        )
        debug_details = self._set_stage(
            debug_details,
            "boll_structure",
            ema_multiplier=ema_multiplier,
            ema_status=ema_status,
            ema_veto=ema_veto.value if ema_veto else VetoType.NONE.value,
            bb_middle_1h=bb_middle_1h,
            bb_upper_1h=bb_upper_1h,
            bb_lower_1h=bb_lower_1h,
            bb_middle_4h=bb_middle_4h,
            bb_upper_4h=bb_upper_4h,
            bb_lower_4h=bb_lower_4h,
        )
        
        # BOLL硬性否决
        if ema_veto == VetoType.EMA_1H_BREAK and self.config.ema_55_1h_hard_block:
            return self._neutral_signal(
                reason='boll_structure_veto',
                veto_type=ema_veto,
                veto_reason=f"BOLL结构反向：价格{'跌破' if trade_direction == 'long' else '突破'}BOLL中轨",
                ema_structure_status=ema_status,
                signal_type_1h=details_1h.get('signal_type'),
                ema_multiplier=ema_multiplier,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )
        
        # 检查高偏离否决
        deviation_veto = VetoType.NONE
        if strict_1h_filters_enabled:
            deviation_veto = self.check_boll_deviation_veto(
                close_price,
                bb_middle_1h,
                bb_upper_1h,
                bb_lower_1h,
                details_1h.get('signal_type', '')
            )
            debug_details = self._set_stage(
                debug_details,
                "boll_deviation",
                bb_middle_deviation=abs(close_price - bb_middle_1h) / bb_middle_1h if bb_middle_1h > 0 else 0.0,
                deviation_veto=deviation_veto.value if deviation_veto else VetoType.NONE.value,
            )
            if deviation_veto != VetoType.NONE:
                return self._neutral_signal(
                    reason='high_deviation_veto',
                    veto_type=deviation_veto,
                    veto_reason="MACD翻色时价格已远离BOLL中轨",
                    signal_type_1h=details_1h.get('signal_type'),
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )
        else:
            debug_details = self._set_stage(
                debug_details,
                "boll_deviation",
                bb_middle_deviation=abs(close_price - bb_middle_1h) / bb_middle_1h if bb_middle_1h > 0 else 0.0,
                deviation_veto=VetoType.NONE.value,
                deviation_filter_skipped=True,
            )
        
        bb_middle_slope_1h = (
            float(bb_middle_slope_1h)
            if bb_middle_slope_1h is not None
            else self._boll_middle_slope_from_series(
                close_1h_series,
                self.config.boll_period,
                self.config.boll_std_dev,
                max(1, int(self.config.ema_slope_lookback_1h)),
            )
        )
        bb_middle_slope_4h = (
            float(bb_middle_slope_4h)
            if bb_middle_slope_4h is not None
            else self._boll_middle_slope_from_series(
                close_4h_series,
                self.config.boll_period,
                self.config.boll_std_dev,
                max(1, int(self.config.ema_slope_lookback_4h)),
            )
        )
        debug_details.update(
            bb_middle_slope_1h=bb_middle_slope_1h,
            bb_middle_slope_4h=bb_middle_slope_4h,
        )

        # ========== Step 3: VWAP评分 ==========
        vwap_score, vwap_veto, vwap_details = self.calculate_vwap_score(
            close_price,
            vwap,
            trade_direction,
            structural_vwap=structural_vwap,
            price_series=close_1h_series,
            session_vwap_series=vwap_1h_series,
            structural_vwap_series=structural_vwap_1h_series,
        )
        vwap_deviation = (close_price - vwap) / vwap if vwap > 0 else 0.0
        vwap_state = str(vwap_details.get("state", "unknown"))
        vwap_location_score = float(vwap_details.get("location_score", 0.0))
        structural_vwap_deviation = float(vwap_details.get("structural_deviation", 0.0))
        debug_details = self._set_stage(
            debug_details,
            "vwap",
            vwap_score=vwap_score,
            vwap_quality_score=vwap_details.get("vwap_quality_score", vwap_score),
            vwap_alpha_score=vwap_details.get("vwap_alpha_score", 0.0),
            vwap_missing=bool(vwap_details.get("vwap_missing", False)),
            vwap_deviation=vwap_deviation,
            vwap_state=vwap_state,
            vwap_location_score=vwap_location_score,
            session_vwap=vwap_details.get("session_vwap", vwap),
            structural_vwap=vwap_details.get("structural_vwap", structural_vwap),
            session_vwap_deviation=vwap_details.get("session_deviation", vwap_deviation),
            structural_vwap_deviation=structural_vwap_deviation,
            vwap_entry_edge=vwap_details.get("entry_edge", 0.0),
            vwap_directional_extension=vwap_details.get("directional_extension", 0.0),
            vwap_entry_edge_quality=vwap_details.get("entry_edge_quality", 0.0),
            vwap_value_proximity_quality=vwap_details.get("value_proximity_quality", 0.0),
            vwap_extension_quality=vwap_details.get("extension_quality", 0.0),
            vwap_structure_quality=vwap_details.get("structure_quality", 0.0),
            vwap_retest_quality=vwap_details.get("retest_quality", vwap_details.get("reclaim_quality", 0.0)),
            vwap_dual_pressure_quality=vwap_details.get(
                "dual_pressure_quality",
                vwap_details.get("dual_support_quality", 0.0),
            ),
            vwap_veto=vwap_veto.value if vwap_veto else VetoType.NONE.value,
        )
        
        # VWAP硬性否决
        if vwap_veto in {VetoType.VWAP_HARD_BLOCK, VetoType.VWAP_MISSING_HARD_BLOCK}:
            missing_vwap_block = vwap_veto == VetoType.VWAP_MISSING_HARD_BLOCK
            return self._neutral_signal(
                reason='vwap_missing_hard_block' if missing_vwap_block else 'vwap_hard_block',
                veto_type=vwap_veto,
                veto_reason=(
                    "VWAP数据缺失"
                    if missing_vwap_block
                    else f"VWAP偏离超过{self.config.vwap_deviation_hard_block*100:.1f}%"
                ),
                signal_type_1h=details_1h.get('signal_type'),
                vwap_score=0.0,
                vwap_deviation=vwap_deviation,
                vwap_state=vwap_state,
                vwap_location_score=vwap_location_score,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if strict_1h_filters_enabled:
            vwap_context_ok, vwap_context_reasons, vwap_context_details = self.check_flip_bearish_vwap_context(
                signal_type_1h=details_1h.get('signal_type', ''),
                vwap_state=vwap_state,
                vwap_score=vwap_score,
                structural_vwap=float(vwap_details.get("structural_vwap", structural_vwap)),
                session_deviation=float(vwap_details.get("session_deviation", vwap_deviation)),
                structural_deviation=structural_vwap_deviation,
            )
            if not vwap_context_ok:
                debug_details = self._set_stage(
                    debug_details,
                    "flip_bearish_vwap_filter",
                    flip_bearish_vwap_context_passed=False,
                    flip_bearish_vwap_context_reasons=vwap_context_reasons,
                    **vwap_context_details,
                )
                return self._neutral_signal(
                    reason=f'flip_bearish_vwap_filter({"; ".join(vwap_context_reasons)})',
                    signal_type_1h=details_1h.get('signal_type'),
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    vwap_state=vwap_state,
                    vwap_location_score=vwap_location_score,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )
        else:
            debug_details = self._set_stage(
                debug_details,
                "flip_bearish_vwap_filter",
                flip_bearish_vwap_context_skipped=True,
            )

        if (
            trade_direction == 'short'
            and details_1h.get('signal_type') == 'green_bar_shrinking'
            and vwap_state == 'short_dual_pressure'
            and self.config.disable_green_bar_shrinking_short_dual_pressure_entries
        ):
            debug_details = self._set_stage(
                debug_details,
                "shrinking_state_filter",
                shrinking_state_filter_reason="green_bar_shrinking_short_dual_pressure",
            )
            return self._neutral_signal(
                reason='green_bar_shrinking_short_dual_pressure_disabled',
                signal_type_1h=details_1h.get('signal_type'),
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                vwap_state=vwap_state,
                vwap_location_score=vwap_location_score,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if (
            trade_direction == 'long'
            and details_1h.get('signal_type') == 'red_bar_shrinking'
            and vwap_state == 'long_dual_support'
            and self.config.disable_red_bar_shrinking_long_dual_support_entries
        ):
            debug_details = self._set_stage(
                debug_details,
                "shrinking_state_filter",
                shrinking_state_filter_reason="red_bar_shrinking_long_dual_support",
            )
            return self._neutral_signal(
                reason='red_bar_shrinking_long_dual_support_disabled',
                signal_type_1h=details_1h.get('signal_type'),
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                vwap_state=vwap_state,
                vwap_location_score=vwap_location_score,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        # ========== Step 4: MACD_4H 确认增强 ==========
        is_4h_enhanced, enhancement_score = self.check_4h_macd_enhancement(
            macd_hist_4h, idx_4h, trade_direction
        )
        debug_details = self._set_stage(
            debug_details,
            "4h_enhancement",
            is_4h_enhanced=is_4h_enhanced,
            enhancement_score=enhancement_score,
        )
        
        # ========== Step 5: RSI 节奏层 ==========
        if rsi_rhythm is None:
            rsi_rhythm = self.evaluate_rsi_rhythm(
                direction=trade_direction,
                rsi_15m_series=rsi_15m_series,
                rsi_1h_series=rsi_1h_series,
                rsi_4h_series=rsi_4h_series,
                close_15m_series=close_15m_series,
                close_1h_series=close_1h_series,
                close_4h_series=close_4h_series,
                macd_hist_1h_current=self._series_value(macd_hist_1h[: idx_1h + 1], default=0.0),
            )
        rsi_rhythm = dict(rsi_rhythm or {})
        rsi_entry_refine = self._resolve_rsi_entry_refinement(
            direction=trade_direction,
            entry_score=max(0.0, float(rsi_rhythm.get("weighted_score", 0.0))),
            close_15m_series=close_15m_series,
            close_1h_series=close_1h_series,
            close_4h_series=close_4h_series,
        )
        if not str(rsi_rhythm.get("entry_type") or "").strip():
            refine_entry_type = str(rsi_entry_refine.get("refine") or "").strip()
            if refine_entry_type:
                rsi_rhythm["entry_type"] = refine_entry_type
        for key in (
            "rsi_15m",
            "rsi_15m_prev",
            "rsi_1h",
            "rsi_4h",
            "rsi_15m_recent_min",
            "rsi_15m_recent_max",
            "rsi_1h_recent_reset_min",
            "rsi_1h_recent_reset_max",
            "price_break_high",
            "price_break_low",
            "refine",
        ):
            value = rsi_entry_refine.get(key)
            if value is None:
                continue
            if key in {"price_break_high", "price_break_low"}:
                rsi_rhythm[key] = bool(value)
            elif key == "refine":
                rsi_rhythm["refine"] = value
                rsi_rhythm["ema_15m_refine"] = value
            elif key not in rsi_rhythm or not np.isfinite(rsi_rhythm.get(key, np.nan)):
                rsi_rhythm[key] = value
        can_enter = not bool(rsi_rhythm.get("hard_veto", False))
        entry_score_15m = max(0.0, float(rsi_rhythm.get("weighted_score", 0.0)))
        entry_type_15m = str(rsi_rhythm.get("entry_type") or "")
        details_15m = {
            "entry_type": entry_type_15m,
            "refine": str(rsi_rhythm.get("refine") or entry_type_15m),
            "ema_15m_refine": str(rsi_rhythm.get("ema_15m_refine") or rsi_rhythm.get("refine") or entry_type_15m),
            "rsi_15m_entry_type": entry_type_15m,
            "rsi_15m": float(rsi_rhythm.get("rsi_15m", self._series_value(rsi_15m_series, default=np.nan))),
            "rsi_15m_prev": float(rsi_rhythm.get("rsi_15m_prev", self._series_value(rsi_15m_series, offset=-2, default=np.nan))),
            "rsi_1h": float(rsi_rhythm.get("rsi_1h", self._series_value(rsi_1h_series, default=np.nan))),
            "rsi_4h": float(rsi_rhythm.get("rsi_4h", self._series_value(rsi_4h_series, default=np.nan))),
            "raw_score": float(rsi_rhythm.get("raw_score", 0.0)),
            "weighted_score": float(rsi_rhythm.get("weighted_score", 0.0)),
            "hard_veto": bool(rsi_rhythm.get("hard_veto", False)),
            "veto_reason": str(rsi_rhythm.get("veto_reason") or ""),
            "exposure_mult": float(rsi_rhythm.get("exposure_mult", 0.8)),
            "rsi_15m_recent_min": float(rsi_rhythm.get("rsi_15m_recent_min", np.nan)),
            "rsi_15m_recent_max": float(rsi_rhythm.get("rsi_15m_recent_max", np.nan)),
            "rsi_1h_recent_reset_min": float(rsi_rhythm.get("rsi_1h_recent_reset_min", np.nan)),
            "rsi_1h_recent_reset_max": float(rsi_rhythm.get("rsi_1h_recent_reset_max", np.nan)),
            "price_break_high": bool(rsi_rhythm.get("price_break_high", False)),
            "price_break_low": bool(rsi_rhythm.get("price_break_low", False)),
        }
        debug_details = self._set_stage(
            debug_details,
            "rsi_rhythm",
            entry_type_15m=entry_type_15m,
            entry_score_15m=entry_score_15m,
            score_rsi_rhythm_raw=rsi_rhythm.get("raw_score", 0.0),
            score_rsi_rhythm_weighted=rsi_rhythm.get("weighted_score", 0.0),
            rsi_4h_regime=rsi_rhythm.get("rsi_4h_regime"),
            rsi_1h_phase=rsi_rhythm.get("rsi_1h_phase"),
            rsi_15m_entry_type=rsi_rhythm.get("entry_type"),
            rsi_exposure_mult=rsi_rhythm.get("exposure_mult", 0.8),
            rsi_hard_veto=bool(rsi_rhythm.get("hard_veto", False)),
            rsi_hard_veto_reason=rsi_rhythm.get("veto_reason"),
            bb_middle_15m=bb_middle_15m,
            bb_upper_15m=bb_upper_15m,
            bb_lower_15m=bb_lower_15m,
        )
        rsi_launch_sovereign = self._evaluate_rsi_launch_sovereign_mode(
            trade_direction=trade_direction,
            signal_type_1h=details_1h.get('signal_type'),
            signal_type_4h=signal_type_4h,
            macd_hist_4h_current=float(details_4h.get("hist_current", 0.0) or 0.0),
            rsi_context=details_15m,
        )
        debug_details.update(self._default_rsi_launch_sovereign_details())
        debug_details.update(rsi_launch_sovereign)

        if not can_enter:
            return self._neutral_signal(
                reason=str(rsi_rhythm.get("veto_reason") or "rsi_15m_extreme_veto"),
                veto_type=VetoType.WEAK_SIGNAL_COMBO if str(rsi_rhythm.get("veto_reason") or "") == "weak_combo_veto" else VetoType.NONE,
                veto_reason=str(rsi_rhythm.get("veto_reason") or "rsi_15m_extreme_veto"),
                signal_type_1h=details_1h.get('signal_type'),
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        signal_type_1h = details_1h.get('signal_type', '')
        entry_refine_15m = entry_type_15m
        stable_continuation_eval = self._evaluate_stable_continuation(
            primary_mode=primary_mode,
            trade_direction=trade_direction,
            signal_type_1h=signal_type_1h,
            entry_type_15m=entry_type_15m,
            vwap_score=vwap_score,
            vwap_state=vwap_state,
            adx_1h=adx_1h,
            stable_trend_context=stable_trend_context,
            is_trial_entry=is_trial_entry,
        )
        stable_continuation_active = bool(stable_continuation_eval.get("stable_continuation_active", False))
        stable_continuation_side = (
            str(stable_continuation_eval.get("stable_continuation_side") or "").strip().lower() or None
        )
        debug_details.update(**stable_continuation_eval)
        if float(rsi_rhythm.get("exposure_mult", 0.8)) <= 0.0:
            debug_details = self._set_stage(
                debug_details,
                "rsi_rhythm_block",
                final_block_reason="rsi_rhythm_block",
            )
            return self._neutral_signal(
                reason="rsi_rhythm_block",
                veto_reason="rsi_rhythm_block",
                entry_score_15m=entry_score_15m,
                signal_type_1h=details_1h.get('signal_type'),
                entry_type_15m=entry_type_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        flip_bullish_sniper_eval = self._evaluate_flip_bullish_sniper(
            signal_type_1h=signal_type_1h,
            trade_direction=trade_direction,
            rsi_rhythm=rsi_rhythm,
            rsi_1h_series=rsi_1h_series,
            macd_hist_4h=macd_hist_4h,
            idx_4h=idx_4h,
        )
        flip_bullish_sniper_bonus = float(flip_bullish_sniper_eval.get("bonus_score", 0.0))
        debug_details = self._set_stage(
            debug_details,
            "flip_bullish_sniper_gate",
            flip_bullish_sniper_applies=bool(flip_bullish_sniper_eval.get("applies", False)),
            flip_bullish_sniper_passed=bool(flip_bullish_sniper_eval.get("passed", True)),
            flip_bullish_sniper_reason=flip_bullish_sniper_eval.get("reason"),
            flip_bullish_sniper_bonus=flip_bullish_sniper_bonus,
            flip_bullish_sniper_quality_matches=int(flip_bullish_sniper_eval.get("quality_matches", 0)),
            flip_bullish_sniper_required_matches=int(flip_bullish_sniper_eval.get("required_matches", 0)),
        )
        if bool(flip_bullish_sniper_eval.get("applies", False)) and not bool(flip_bullish_sniper_eval.get("passed", True)):
            return self._neutral_signal(
                reason=f'flip_bullish_sniper_{flip_bullish_sniper_eval.get("reason")}',
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(**debug_details),
            )

        flip_bullish_cooling_eval = self._evaluate_flip_bullish_cooling(
            signal_type_1h=signal_type_1h,
            trade_direction=trade_direction,
            rsi_rhythm=rsi_rhythm,
        )
        debug_details = self._set_stage(
            debug_details,
            "flip_bullish_cooling_gate",
            flip_bullish_cooling_applies=bool(flip_bullish_cooling_eval.get("applies", False)),
            flip_bullish_cooling_passed=bool(flip_bullish_cooling_eval.get("passed", True)),
            flip_bullish_cooling_reason=flip_bullish_cooling_eval.get("reason"),
            flip_bullish_cooling_score_multiplier=float(flip_bullish_cooling_eval.get("score_multiplier", 1.0)),
        )
        if bool(flip_bullish_cooling_eval.get("applies", False)) and not bool(flip_bullish_cooling_eval.get("passed", True)):
            return self._neutral_signal(
                reason=f'flip_bullish_cooling_{flip_bullish_cooling_eval.get("reason")}',
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(**debug_details),
            )

        flip_bullish_strict_filter_eval = self._evaluate_flip_bullish_strict_filter(
            signal_type_1h=signal_type_1h,
            trade_direction=trade_direction,
            entry_type_15m=entry_type_15m,
            entry_refine_15m=entry_refine_15m,
            vwap_score=vwap_score,
        )
        debug_details = self._set_stage(
            debug_details,
            "flip_bullish_strict_filter",
            flip_bullish_strict_filter_applies=bool(flip_bullish_strict_filter_eval.get("applies", False)),
            flip_bullish_strict_filter_passed=bool(flip_bullish_strict_filter_eval.get("passed", True)),
            flip_bullish_filter_reasons=list(flip_bullish_strict_filter_eval.get("reasons", [])),
            flip_bullish_strict_filter_score_multiplier=float(flip_bullish_strict_filter_eval.get("score_multiplier", 1.0)),
            entry_refine_15m=entry_refine_15m,
        )

        if (
            not stable_continuation_active
            and self.config.disable_flip_bullish_entries
            and signal_type_1h == 'flip_bullish'
        ):
            debug_details = self._set_stage(
                debug_details,
                "flip_bullish_disabled",
                flip_bullish_disabled=True,
            )
            return self._neutral_signal(
                reason='flip_bullish_disabled',
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if (
            not is_trial_entry
            and trade_direction == 'long'
            and signal_type_1h == 'flip_bullish'
            and self.config.enable_flip_bullish_cvd_context_filter
            and not stable_continuation_active
        ):
            cvd_context_reasons: List[str] = []
            max_upper_wick_ratio = float(self.config.flip_bullish_max_cvd_upper_wick_ratio)
            min_cvd_1h_delta_ratio = float(self.config.flip_bullish_min_cvd_1h_delta_ratio)
            if (
                max_upper_wick_ratio > 0
                and cvd_upper_wick_ratio is not None
                and float(cvd_upper_wick_ratio) >= max_upper_wick_ratio
            ):
                cvd_context_reasons.append(
                    f"cvd_upper_wick_ratio={float(cvd_upper_wick_ratio):.4f}>={max_upper_wick_ratio:.4f}"
                )
            if (
                min_cvd_1h_delta_ratio > 0
                and cvd_1h_delta_ratio is not None
                and float(cvd_1h_delta_ratio) < min_cvd_1h_delta_ratio
            ):
                cvd_context_reasons.append(
                    f"cvd_1h_delta_ratio={float(cvd_1h_delta_ratio):.4f}<{min_cvd_1h_delta_ratio:.4f}"
                )
            if cvd_context_reasons:
                debug_details = self._set_stage(
                    debug_details,
                    "flip_bullish_cvd_context_filter",
                    flip_bullish_cvd_context_filter_reasons=cvd_context_reasons,
                )
                return self._neutral_signal(
                    reason=f'flip_bullish_cvd_context_filter({"; ".join(cvd_context_reasons)})',
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )

        if (
            strict_1h_filters_enabled
            and not stable_continuation_active
            and self.config.disable_green_bar_growing_entries
            and signal_type_1h == 'green_bar_growing'
        ):
            debug_details = self._set_stage(
                debug_details,
                "green_bar_growing_disabled",
                green_bar_growing_disabled=True,
            )
            return self._neutral_signal(
                reason='green_bar_growing_disabled',
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )

        if (
            not is_trial_entry
            and trade_direction == 'short'
            and signal_type_1h == 'green_bar_growing'
            and self.config.enable_green_bar_growing_short_adx_1h_range_filter
            and not stable_continuation_active
        ):
            min_adx_1h = float(self.config.green_bar_growing_short_min_adx_1h)
            max_adx_1h = float(self.config.green_bar_growing_short_max_adx_1h)
            if max_adx_1h > min_adx_1h and min_adx_1h <= float(adx_1h) < max_adx_1h:
                debug_details = self._set_stage(
                    debug_details,
                    "green_bar_growing_short_adx_1h_range_filter",
                    green_bar_growing_short_min_adx_1h=min_adx_1h,
                    green_bar_growing_short_max_adx_1h=max_adx_1h,
                )
                return self._neutral_signal(
                    reason=(
                        f'green_bar_growing_short_adx_1h_range_filter('
                        f'{adx_1h:.2f} in [{min_adx_1h:.2f}, {max_adx_1h:.2f}))'
                    ),
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )

        if (
            strict_1h_filters_enabled
            and
            not stable_continuation_active
            and self.config.disable_red_bar_growing_long_entries
            and signal_type_1h == 'red_bar_growing'
            and trade_direction == 'long'
        ):
            debug_details = self._set_stage(
                debug_details,
                "red_bar_growing_long_disabled",
                red_bar_growing_long_disabled=True,
            )
            return self._neutral_signal(
                reason='red_bar_growing_long_disabled',
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if (
            strict_1h_filters_enabled
            and signal_type_1h == 'flip_bearish'
            and ema_multiplier < self.config.flip_bearish_min_ema_multiplier
        ):
            debug_details = self._set_stage(
                debug_details,
                "flip_bearish_ema_filter",
                flip_bearish_min_ema_multiplier=self.config.flip_bearish_min_ema_multiplier,
            )
            return self._neutral_signal(
                reason=(
                    f'flip_bearish_ema_filter('
                    f'{ema_multiplier:.1f}<'
                    f'{self.config.flip_bearish_min_ema_multiplier:.1f})'
                ),
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if strict_1h_filters_enabled:
            structure_ok, structure_reasons, structure_details = self.check_flip_bearish_structure(
                signal_type_1h,
                adx_1h=adx_1h,
                bb_middle_slope_1h=bb_middle_slope_1h,
                bb_middle_slope_4h=bb_middle_slope_4h,
            )
            if not structure_ok:
                debug_details = self._set_stage(
                    debug_details,
                    "flip_bearish_structure_filter",
                    flip_bearish_structure_passed=False,
                    flip_bearish_structure_reasons=structure_reasons,
                    **structure_details,
                )
                return self._neutral_signal(
                    reason=f'flip_bearish_structure_filter({"; ".join(structure_reasons)})',
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    vwap_state=vwap_state,
                    vwap_location_score=vwap_location_score,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )
        else:
            debug_details = self._set_stage(
                debug_details,
                "flip_bearish_structure_filter",
                flip_bearish_structure_skipped=True,
            )

        min_vwap_score_for_entry = max(
            0.0,
            self._resolve_min_vwap_score_for_entry(
                trade_direction=trade_direction,
                signal_type_1h=signal_type_1h,
                is_trial_entry=is_trial_entry,
            ),
        )
        if min_vwap_score_for_entry > 0 and vwap_score < min_vwap_score_for_entry:
            debug_details = self._set_stage(
                debug_details,
                "vwap_score_filter",
                min_vwap_score_for_entry=min_vwap_score_for_entry,
            )
            return self._neutral_signal(
                reason=f'vwap_score_filter({vwap_score:.4f}<{min_vwap_score_for_entry:.4f})',
                score=0.0,
                veto_type=VetoType.VWAP_SCORE_FILTER,
                veto_reason="VWAP评分低于入场阈值",
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )

        if strict_1h_filters_enabled and signal_type_1h == 'red_bar_growing' and trade_direction == 'long':
            if ema_status == 'against':
                debug_details = self._set_stage(
                    debug_details,
                    "red_bar_long_filter",
                    red_bar_long_filter_reason="ema_against",
                )
                return self._neutral_signal(
                    reason='red_bar_long_blocked(ema_against)',
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )
            if vwap_deviation < -self.config.vwap_deviation_hard_block:
                debug_details = self._set_stage(
                    debug_details,
                    "red_bar_long_filter",
                    red_bar_long_filter_reason="vwap_dev_too_low",
                )
                return self._neutral_signal(
                    reason=(
                        f'red_bar_long_blocked('
                        f'vwap_dev={vwap_deviation * 100:.1f}%<'
                        f'-{self.config.vwap_deviation_hard_block * 100:.1f}%)'
                    ),
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )
        
        # ========== Step 6: 综合评分 ==========
        score = 0.0

        signal_strength_1h = details_1h.get('signal_strength', 0.5)
        meaningful_short_15m_confirmation = self._has_meaningful_short_15m_confirmation(
            trade_direction=trade_direction,
            entry_type_15m=entry_type_15m,
            entry_score_15m=entry_score_15m,
        )
        score_1h_base = 0.0
        if direction_1h == trade_direction and signal_type_1h in ['flip_bullish', 'flip_bearish']:
            score_1h_base = self.config.weight_1h_direction
        elif direction_1h == trade_direction and signal_type_1h in ['red_bar_growing', 'green_bar_growing']:
            score_1h_base = self.config.weight_1h_direction * 0.85
        elif direction_1h == trade_direction:
            score_1h_base = self.config.weight_1h_direction * max(0.0, float(signal_strength_1h))
        score_1h = min(score_1h_base, self.config.weight_1h_direction)
        score += score_1h

        if is_trial_entry:
            shrink_pct = max(0.0, float(shrink_4h_context["shrink_pct"]))
            preflip_4h_strength = self._clamp(0.56 + shrink_pct * 0.38, 0.0, 0.92)
            score_4h_base = self.config.weight_4h_direction * preflip_4h_strength
        elif direction_4h == trade_direction and signal_type_4h in ['flip_bullish', 'flip_bearish']:
            score_4h_base = self.config.weight_4h_direction
            if (
                trade_direction == "short"
                and signal_type_4h == "flip_bearish"
                and self.config.flip_bearish_require_enhancement_or_15m_confirmation
                and not is_4h_enhanced
                and not meaningful_short_15m_confirmation
            ):
                score_4h_base = self.config.weight_4h_direction * 0.5
        elif direction_4h == trade_direction and signal_type_4h in ['red_bar_growing', 'green_bar_growing']:
            score_4h_base = self.config.weight_4h_direction * 0.875
        elif direction_4h == trade_direction:
            score_4h_base = self.config.weight_4h_direction * signal_strength_4h
        else:
            score_4h_base = 0.0

        legacy_4h_boost = entry_type_15m not in ['rsi_spring']
        effective_4h_score = enhancement_score
        if legacy_4h_boost:
            if is_4h_enhanced:
                effective_4h_score = 0.84
            elif enhancement_score > 0:
                effective_4h_score = 2.0 / 3.0
        folded_4h_bonus = 0.0
        if self.config.weight_4h_enhancement > 0 and effective_4h_score > 0:
            folded_4h_bonus = min(
                self.config.weight_4h_direction * 0.25 * effective_4h_score,
                self.config.weight_4h_direction,
            )
        score_4h_trend = min((score_4h_base * ema_multiplier) + folded_4h_bonus, self.config.weight_4h_direction)
        score_4h = score_4h_trend
        score += score_4h
        score_4h_enhancement_base = 0.0
        score_4h_enhancement = 0.0

        score_rsi_rhythm_raw = float(rsi_rhythm.get("raw_score", 0.0))
        score_rsi_rhythm = float(rsi_rhythm.get("weighted_score", 0.0))
        rsi_spring_weight_floor = self._resolve_flip_bullish_rsi_spring_weight_floor(
            signal_type_1h=signal_type_1h,
            trade_direction=trade_direction,
            rsi_rhythm=rsi_rhythm,
            score_rsi_rhythm_weighted=score_rsi_rhythm,
        )
        score_rsi_rhythm = float(rsi_spring_weight_floor["score_rsi_rhythm_weighted"])
        score += score_rsi_rhythm
        score += float(flip_bullish_sniper_bonus)

        # VWAP评分
        score_vwap = float(vwap_details.get("vwap_alpha_score", 0.0))
        score += score_vwap

        score_15m = 0.0
        if self.config.weight_15m_entry > 0:
            score_15m = min(
                self.config.weight_15m_entry,
                max(0.0, float(entry_score_15m or 0.0)) * self.config.weight_15m_entry,
            )
            if score_15m == 0.0 and meaningful_short_15m_confirmation:
                score_15m = self.config.weight_15m_entry
        score += score_15m

        # 成交量评分
        if volume_ratio > 1.5:
            score_vol = self.config.weight_volume
        elif volume_ratio > 1.0:
            score_vol = self.config.weight_volume * 0.67
        else:
            score_vol = self.config.weight_volume * 0.33
        score += score_vol

        overheat_penalty = 0.0
        confirmation_signal_type = signal_type_4h if light_1h_confirmation else signal_type_1h
        growing_signal = confirmation_signal_type in ['red_bar_growing', 'green_bar_growing']
        growing_entry = entry_type_15m in ['red_bar_growing', 'green_bar_growing']
        if (
            self.config.overheat_growing_penalty > 0
            and ema_multiplier >= self.config.overheat_ema_multiplier_threshold
            and vwap_score <= self.config.overheat_vwap_score_threshold
            and (growing_signal or growing_entry)
        ):
            overheat_penalty = self.config.overheat_growing_penalty
            score = max(0.0, score - overheat_penalty)

        conflict_state = self._classify_rsi_macd_conflict(
            trade_direction=trade_direction,
            direction_1h=direction_1h,
            direction_4h=direction_4h,
            score_rsi_rhythm_raw=score_rsi_rhythm_raw,
            rsi_rhythm=rsi_rhythm,
        )
        rsi_macd_conflict = bool(conflict_state["active"])
        rsi_conflict_type = str(conflict_state["type"])
        conflict_penalty_mult = float(conflict_state["score_penalty_mult"])
        rsi_conflict_portion_mult = float(conflict_state["portion_penalty_mult"])
        if bool(conflict_state["force_probe"]):
            rsi_rhythm["probe_mode"] = True
        flip_bullish_cooling_score_multiplier = float(flip_bullish_cooling_eval.get("score_multiplier", 1.0))
        if flip_bullish_cooling_score_multiplier != 1.0:
            score *= max(0.0, flip_bullish_cooling_score_multiplier)
        flip_bullish_strict_filter_score_multiplier = float(flip_bullish_strict_filter_eval.get("score_multiplier", 1.0))
        if flip_bullish_strict_filter_score_multiplier != 1.0:
            score *= max(0.0, flip_bullish_strict_filter_score_multiplier)
        if conflict_penalty_mult != 1.0:
            score *= max(0.0, conflict_penalty_mult)
        if neutral_upgrade_applied:
            score *= float(neutral_upgrade_penalty_mult)
        spring_override = self._resolve_rsi_spring_threshold_override(
            trade_direction=trade_direction,
            rsi_rhythm=rsi_rhythm,
        )
        if spring_override["applied"]:
            score += float(spring_override["score_bonus"])

        sovereign_bonus = float(rsi_launch_sovereign.get("score_bonus", 0.0) or 0.0)
        if bool(rsi_launch_sovereign.get("rsi_launch_sovereign_applied", False)) and sovereign_bonus > 0:
            score += sovereign_bonus

        debug_details = self._set_stage(
            debug_details,
            "score_aggregation",
            primary_timeframe="4h",
            primary_signal_type=signal_type_4h,
            primary_signal_strength=signal_strength_4h,
            score_1h_base=score_1h_base,
            score_1h=score_1h,
            score_4h_base=score_4h_base,
            score_4h=score_4h,
            score_4h_trend=score_4h_trend,
            score_4h_enhancement_base=score_4h_enhancement_base,
            score_4h_enhancement=score_4h_enhancement,
            score_rsi_rhythm_raw=score_rsi_rhythm_raw,
            score_rsi_rhythm_weighted=score_rsi_rhythm,
            rsi_spring_weighted_floor_applied=bool(rsi_spring_weight_floor["rsi_spring_weighted_floor_applied"]),
            rsi_spring_weighted_floor_value=float(rsi_spring_weight_floor["rsi_spring_weighted_floor_value"]),
            flip_bullish_sniper_bonus=float(flip_bullish_sniper_bonus),
            score_vwap=score_vwap,
            score_15m=score_15m,
            score_volume=score_vol,
            overheat_penalty=overheat_penalty,
            overheat_triggered=bool(overheat_penalty > 0),
            total_score=score,
            legacy_4h_boost=legacy_4h_boost,
            effective_4h_score=effective_4h_score,
            sovereign_score_bonus=sovereign_bonus,
            rsi_macd_conflict=rsi_macd_conflict,
            rsi_conflict_type=rsi_conflict_type,
            conflict_penalty_mult=conflict_penalty_mult,
            rsi_conflict_portion_mult=rsi_conflict_portion_mult,
            rsi_exposure_mult=rsi_rhythm.get("exposure_mult", 0.8),
            rsi_conflict_reduce_leverage_one_step=bool(conflict_state["reduce_leverage_one_step"]),
            neutral_upgrade_considered=neutral_upgrade_considered,
            neutral_upgrade_applied=neutral_upgrade_applied,
            neutral_upgrade_penalty_mult=neutral_upgrade_penalty_mult,
            neutral_upgrade_mode=neutral_upgrade_mode,
            neutral_upgrade_threshold_override=neutral_upgrade_threshold_override,
            neutral_original_reason=neutral_original_reason,
            neutral_upgrade_direction=neutral_upgrade_direction,
            flip_bullish_cooling_score_multiplier=flip_bullish_cooling_score_multiplier,
            flip_bullish_strict_filter_score_multiplier=flip_bullish_strict_filter_score_multiplier,
            rsi_spring_threshold_override_applied=bool(spring_override["applied"]),
            rsi_spring_threshold_override_score_bonus=float(spring_override["score_bonus"]),
            rsi_spring_threshold_override_min_signal_score=float(spring_override["threshold"]),
        )
        vol_vwap_warn = (
            score_vol < float(self.config.vol_vwap_warn_min_score_vol)
            and vwap_score <= float(self.config.vol_vwap_warn_min_vwap_score)
        )
        debug_details.update(
            vol_vwap_warn=bool(vol_vwap_warn),
            vol_vwap_warn_min_score_vol=float(self.config.vol_vwap_warn_min_score_vol),
            vol_vwap_warn_min_vwap_score=float(self.config.vol_vwap_warn_min_vwap_score),
        )
        trial_short_promotion_eval = self._evaluate_trial_short_below_structure_continuation_promotion(
            primary_mode=primary_mode,
            trade_direction=trade_direction,
            signal_type_1h=signal_type_1h,
            entry_type_15m=entry_type_15m,
            vwap_state=vwap_state,
            vwap_score=vwap_score,
            adx_1h=adx_1h,
            signal_score=score,
            shrink_4h_context=shrink_4h_context,
            is_trial_entry=is_trial_entry,
        )
        debug_details.update(**trial_short_promotion_eval)
        if bool(trial_short_promotion_eval.get("trial_short_below_structure_promotion_active", False)):
            stable_continuation_active = True
            stable_continuation_side = "short"
            stable_continuation_eval.update(
                stable_continuation_active=True,
                stable_continuation_side="short",
                stable_continuation_reason="trial_short_below_structure_promoted",
                stable_continuation_hist_bars=int(stable_trend_context.get("negative_bars", 0) or 0),
                stable_continuation_promoted_from_trial=True,
                stable_continuation_promoted_vwap_state=vwap_state,
            )
            debug_details.update(**stable_continuation_eval)
        if self.config.weight_4h_enhancement > 0 and score_4h_enhancement == 0.0:
            logger.debug(
                "[MACD_V2_SCORE] 4H enhancement=0.0 but weight=%.2f, check 4H data source",
                self.config.weight_4h_enhancement,
            )

        if self.config.resonance_gate_enabled:
            resonance_eval = self._check_resonance_gate(
                signal_type_1h=signal_type_1h,
                trade_direction=trade_direction,
                is_trial_entry=is_trial_entry,
                direction_4h=direction_4h,
                signal_type_4h=signal_type_4h,
                direction_1h=direction_1h,
                entry_type_15m=entry_type_15m,
                ema_status=ema_status,
                rsi_rhythm=rsi_rhythm,
                rsi_conflict_type=rsi_conflict_type,
                adx_1h=adx_1h,
                is_4h_enhanced=is_4h_enhanced,
                funding_rate=funding_rate,
                oi_delta_ratio=oi_delta_ratio,
                volume_ratio=volume_ratio,
                structural_vwap_deviation=structural_vwap_deviation,
            )
            debug_details.update(
                resonance_gate_enabled=True,
                resonance_gate_passed=bool(resonance_eval.get("passed", False)),
                resonance_gate_reason=str(resonance_eval.get("reason", "")),
                resonance_gate_position_scale=float(resonance_eval.get("position_scale", 0.0) or 0.0),
                resonance_volume_warn=bool(resonance_eval.get("volume_warn", False)),
                resonance_vwap_telemetry_warn=bool(resonance_eval.get("vwap_telemetry_warn", False)),
            )
            if not bool(resonance_eval.get("passed", False)):
                return self._neutral_signal(
                    reason=str(resonance_eval.get("reason") or "resonance_gate_block"),
                    score=score,
                    veto_type=VetoType.RESONANCE_GATE,
                    veto_reason=str(resonance_eval.get("reason") or "resonance_gate_block"),
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                    ),
                )

        if (
            strict_1h_filters_enabled
            and
            self.config.is_flip_bearish_normal_ema(signal_type_1h, ema_multiplier)
            and self.config.flip_bearish_normal_ema_min_signal_score > 0
            and score < self.config.flip_bearish_normal_ema_min_signal_score
        ):
            debug_details = self._set_stage(
                debug_details,
                "flip_bearish_normal_ema_score_filter",
                flip_bearish_normal_ema_min_signal_score=self.config.flip_bearish_normal_ema_min_signal_score,
            )
            return self._neutral_signal(
                reason=(
                    f'flip_bearish_normal_ema_score_filter('
                    f'{score:.2f}<'
                    f'{self.config.flip_bearish_normal_ema_min_signal_score:.2f})'
                ),
                score=score,
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )
        
        # ========== Step 7.5: 空头质量过滤（V3专家组建议）==========
        if self._should_apply_short_quality_filter(
            signal_type_1h,
            strict_1h_filters_enabled=strict_1h_filters_enabled,
        ):
            short_filter_passed = True
            short_filter_reasons = []
            
            # 条件1: funding_rate > 0.0005 (市场偏多，反转空头有挤多背景)
            if funding_rate <= self.config.short_filter_min_funding_rate:
                short_filter_passed = False
                short_filter_reasons.append(f'funding_rate({funding_rate:.6f}) <= {self.config.short_filter_min_funding_rate}')
            
            # 条件2: oi_delta_ratio < 0 (多头减仓，而非低位追空)
            if oi_delta_ratio >= self.config.short_filter_max_oi_delta_ratio:
                short_filter_passed = False
                short_filter_reasons.append(f'oi_delta_ratio({oi_delta_ratio:.4f}) >= {self.config.short_filter_max_oi_delta_ratio}')
            
            # 条件3: price > vwap * 1.005 (价格偏高位置，不在过低位置追击)
            if vwap > 0 and close_price <= vwap * (1 + self.config.short_filter_min_vwap_deviation):
                short_filter_passed = False
                short_filter_reasons.append(f'price({close_price:.2f}) <= vwap*{1+self.config.short_filter_min_vwap_deviation:.3f}')
            
            if not short_filter_passed:
                return self._neutral_signal(
                    reason=f'空头质量过滤未通过: {"; ".join(short_filter_reasons)}',
                    score=score,
                    veto_type=VetoType.SHORT_QUALITY_FILTER,
                    veto_reason='空头质量过滤',
                    signal_type_1h=signal_type_1h,
                    entry_type_15m=entry_type_15m,
                    entry_score_15m=entry_score_15m,
                    vwap_score=vwap_score,
                    vwap_deviation=vwap_deviation,
                    ema_multiplier=ema_multiplier,
                    ema_structure_status=ema_status,
                    enhancement_score=enhancement_score,
                    is_4h_enhanced=is_4h_enhanced,
                    details=self._build_debug_details(
                        **debug_details,
                        short_filter_passed=False,
                        short_filter_reasons=short_filter_reasons,
                        funding_rate=funding_rate,
                        oi_delta_ratio=oi_delta_ratio,
                    ),
                )
        
        # ========== Step 8: 入场阈值检查 ==========
        threshold_signal_type = (signal_type_4h or signal_type_1h) if primary_mode == "4h" else (signal_type_1h or signal_type_4h)
        threshold, threshold_source = self.config.resolve_entry_threshold(
            signal_type=threshold_signal_type,
            signal_type_1h=signal_type_1h,
            trade_direction=trade_direction,
            entry_type_15m=entry_type_15m,
            primary_mode=primary_mode,
            is_trial_entry=is_trial_entry,
            stable_continuation_active=stable_continuation_active,
            stable_continuation_side=stable_continuation_side,
        )
        threshold_before_override = threshold
        if neutral_upgrade_applied and neutral_upgrade_threshold_override > 0:
            threshold = min(float(threshold), float(neutral_upgrade_threshold_override))
            threshold_source = f"neutral_upgrade_override({threshold_source})"
        if spring_override["applied"]:
            threshold = min(float(threshold), float(spring_override["threshold"]))
            threshold_source = f"rsi_spring_override({threshold_source})"
        sovereign_threshold = float(rsi_launch_sovereign.get("threshold_override", 0.0) or 0.0)
        if (
            bool(rsi_launch_sovereign.get("rsi_launch_sovereign_applied", False))
            and sovereign_threshold > 0
            and threshold > sovereign_threshold
        ):
            threshold = sovereign_threshold
            threshold_source = f"rsi_launch_sovereign_override({threshold_source})"
        debug_details = self._set_stage(
            debug_details,
            "threshold_check",
            signal_score_threshold=threshold,
            signal_score_threshold_before_override=threshold_before_override,
            threshold_source=threshold_source,
            is_trial_entry=is_trial_entry,
            entry_scale=entry_scale,
            stable_continuation_active=stable_continuation_active,
            stable_continuation_side=stable_continuation_side,
            rsi_spring_threshold_override_applied=bool(spring_override["applied"]),
            neutral_upgrade_threshold_override=neutral_upgrade_threshold_override,
        )
        if score < threshold:
            return self._neutral_signal(
                reason=f'信号评分低于阈值: {score:.2f} < {threshold:.2f}',
                score=score,
                signal_type_1h=signal_type_1h,
                entry_type_15m=entry_type_15m,
                entry_score_15m=entry_score_15m,
                vwap_score=vwap_score,
                vwap_deviation=vwap_deviation,
                ema_multiplier=ema_multiplier,
                ema_structure_status=ema_status,
                enhancement_score=enhancement_score,
                is_4h_enhanced=is_4h_enhanced,
                is_trial_entry=is_trial_entry,
                entry_scale=entry_scale,
                details=self._build_debug_details(
                    **debug_details,
                ),
            )
        
        # ========== Step 9: 计算止损 ==========
        stop_price, stop_pct, stop_details = self.calculate_dynamic_stop(
            entry_price=close_price,
            close_1h=close_price,
            bb_middle_1h=bb_middle_1h,
            bb_upper_1h=bb_upper_1h,
            bb_lower_1h=bb_lower_1h,
            atr_1h=atr_1h,
            vwap=vwap,
            direction=trade_direction,
            symbol=symbol,
        )
        
        # ========== Step 10: 返回结果 ==========
        final_score = min(score, 1.0)
        priority_signal = self._resolve_priority_signal(signal_type_1h, vwap_state)
        priority_execution_plan = self._resolve_priority_execution_plan(final_score)
        competition_score = self.config.resolve_competition_score(signal_type_1h, final_score, entry_type_15m)
        sovereign_applied = bool(rsi_launch_sovereign.get("rsi_launch_sovereign_applied", False))
        if sovereign_applied:
            competition_score = self.resolve_competition_score(
                competition_score,
                rsi_launch_sovereign_applied=True,
            )
            priority_signal = True
            priority_execution_plan = {
                "priority_execution_applied": True,
                "priority_execution_tier": "sovereign",
                "execution_route": "priority_execution",
                "entry_time_in_force": "GTC",
                "entry_expire_seconds": int(self.config.rsi_launch_sovereign_priority_expire_seconds),
                "entry_price_mode": "elastic_limit",
                "entry_retry_enabled": bool(self.config.rsi_launch_sovereign_allow_retry),
                "entry_retry_max_attempts": 1 if bool(self.config.rsi_launch_sovereign_allow_retry) else 0,
                "entry_market_fallback_enabled": False,
                "entry_market_fallback_timeout_ms": 0,
                "entry_market_fallback_max_slippage_bps": 0,
                "entry_execution_policy": "priority_execution_vip",
            }
        rsi_probe_mode = self._resolve_effective_probe_mode(
            signal_type_1h,
            bool(rsi_rhythm.get("probe_mode", False)),
        )
        red_bar_growing_probe_overlay_applied = self._is_red_bar_growing_probe_overlay(signal_type_1h)
        green_bar_growing_probe_overlay_applied = self._is_green_bar_growing_probe_overlay(signal_type_1h)

        final_stage_path = self._normalize_stage_path(debug_details.get("stage_path"))
        final_stage_path = self._set_stage({"stage_path": final_stage_path}, "final")["stage_path"]
        self._last_analysis = {
            'strategy': 'macd_mtf_strategy_v2',
            'stage': 'final',
            'stage_path': final_stage_path,
            'stage_path_text': " > ".join(final_stage_path),
            'primary_timeframe': primary_mode,
            'trade_direction': trade_direction,
            'direction_1h': direction_1h,
            'signal_type_1h': signal_type_1h,
            'signal_strength_1h': signal_strength_1h,
            'direction_4h': direction_4h,
            'signal_type_4h': signal_type_4h,
            'signal_strength_4h': signal_strength_4h,
            'is_4h_enhanced': is_4h_enhanced,
            'is_trial_entry': is_trial_entry,
            'entry_scale': entry_scale,
            'stable_continuation_active': stable_continuation_active,
            'stable_continuation_side': stable_continuation_side,
            'stable_continuation_reason': stable_continuation_eval.get("stable_continuation_reason"),
            'stable_continuation_hist_bars': stable_continuation_eval.get("stable_continuation_hist_bars"),
            'enhancement_score': enhancement_score,
            'entry_type_15m': entry_type_15m,
            'entry_score_15m': entry_score_15m,
            'macd_4h_shrink_pct': shrink_4h_context["shrink_pct"],
            'macd_4h_shrink_bars': shrink_4h_context["shrink_bars"],
            'shrink_exit_direction': shrink_4h_context["exit_direction"],
            'shrink_exit_ready': shrink_4h_context["shrink_exit_ready"],
            'vwap_score': vwap_score,
            'vwap_quality_score': float(vwap_details.get("vwap_quality_score", vwap_score)),
            'vwap_alpha_score': float(vwap_details.get("vwap_alpha_score", score_vwap)),
            'vwap_missing': bool(vwap_details.get("vwap_missing", False)),
            'vwap_deviation': (close_price - vwap) / vwap if vwap > 0 else 0,
            'vwap_state': vwap_state,
            'vwap_location_score': vwap_location_score,
            'session_vwap': vwap_details.get("session_vwap", vwap),
            'structural_vwap': vwap_details.get("structural_vwap", structural_vwap),
            'session_vwap_deviation': vwap_details.get("session_deviation", vwap_deviation),
            'structural_vwap_deviation': structural_vwap_deviation,
            'ema_multiplier': ema_multiplier,
            'ema_status': ema_status,
            'adx_1h': adx_1h,
            'adx_4h': adx_4h,
            'bb_middle_slope_1h': bb_middle_slope_1h,
            'bb_middle_slope_4h': bb_middle_slope_4h,
            'volume_ratio': volume_ratio,
            'score_1h_base': score_1h_base,
            'score_1h': score_1h,
            'score_4h_base': score_4h_base,
            'score_4h': score_4h,
            'score_4h_trend': score_4h_trend,
            'meaningful_short_15m_confirmation': meaningful_short_15m_confirmation,
            'flip_bearish_4h_guard_applied': bool(
                trade_direction == "short"
                and signal_type_4h == "flip_bearish"
                and self.config.flip_bearish_require_enhancement_or_15m_confirmation
                and not is_4h_enhanced
                and not meaningful_short_15m_confirmation
            ),
            'score_4h_enhancement_base': score_4h_enhancement_base,
            'score_4h_enhancement': score_4h_enhancement,
            'score_rsi_rhythm_raw': score_rsi_rhythm_raw,
            'score_rsi_rhythm_weighted': score_rsi_rhythm,
            'rsi_spring_weighted_floor_applied': bool(rsi_spring_weight_floor["rsi_spring_weighted_floor_applied"]),
            'rsi_spring_weighted_floor_value': float(rsi_spring_weight_floor["rsi_spring_weighted_floor_value"]),
            'flip_bullish_sniper_bonus': float(flip_bullish_sniper_bonus),
            'rsi_4h_regime': rsi_rhythm.get("rsi_4h_regime"),
            'rsi_1h_phase': rsi_rhythm.get("rsi_1h_phase"),
            'rsi_15m_entry_type': rsi_rhythm.get("entry_type"),
            'rsi_macd_conflict': rsi_macd_conflict,
            'rsi_conflict_type': rsi_conflict_type,
            'conflict_penalty_mult': conflict_penalty_mult,
            'rsi_conflict_portion_mult': rsi_conflict_portion_mult,
            'rsi_exposure_mult': rsi_rhythm.get("exposure_mult", 0.8),
            'rsi_probe_mode': rsi_probe_mode,
            'rsi_probe_forced_leverage': int(self.config.rsi_probe_forced_leverage),
            'rsi_probe_portion_scale': float(self.config.rsi_probe_portion_scale),
            'red_bar_growing_probe_overlay_applied': red_bar_growing_probe_overlay_applied,
            'green_bar_growing_probe_overlay_applied': green_bar_growing_probe_overlay_applied,
            'rsi_spring_threshold_override_applied': bool(spring_override["applied"]),
            'rsi_spring_threshold_override_score_bonus': float(spring_override["score_bonus"]),
            'rsi_spring_threshold_override_min_signal_score': float(spring_override["threshold"]),
            'flip_bullish_sniper_applies': bool(flip_bullish_sniper_eval.get("applies", False)),
            'flip_bullish_sniper_passed': bool(flip_bullish_sniper_eval.get("passed", True)),
            'flip_bullish_sniper_reason': flip_bullish_sniper_eval.get("reason"),
            'flip_bullish_sniper_quality_matches': int(flip_bullish_sniper_eval.get("quality_matches", 0)),
            'flip_bullish_sniper_required_matches': int(flip_bullish_sniper_eval.get("required_matches", 0)),
            'flip_bullish_cooling_applies': bool(flip_bullish_cooling_eval.get("applies", False)),
            'flip_bullish_cooling_passed': bool(flip_bullish_cooling_eval.get("passed", True)),
            'flip_bullish_cooling_reason': flip_bullish_cooling_eval.get("reason"),
            'flip_bullish_cooling_score_multiplier': float(flip_bullish_cooling_eval.get("score_multiplier", 1.0)),
            'flip_bullish_strict_filter_applies': bool(flip_bullish_strict_filter_eval.get("applies", False)),
            'flip_bullish_strict_filter_passed': bool(flip_bullish_strict_filter_eval.get("passed", True)),
            'flip_bullish_filter_reasons': list(flip_bullish_strict_filter_eval.get("reasons", [])),
            'flip_bullish_strict_filter_score_multiplier': float(flip_bullish_strict_filter_eval.get("score_multiplier", 1.0)),
            'competition_score': competition_score,
            'score_vwap': score_vwap,
            'score_15m': score_15m,
            'score_volume': score_vol,
            'vol_vwap_warn': bool(vol_vwap_warn),
            'vol_vwap_warn_min_score_vol': float(self.config.vol_vwap_warn_min_score_vol),
            'vol_vwap_warn_min_vwap_score': float(self.config.vol_vwap_warn_min_vwap_score),
            'resonance_gate_enabled': bool(debug_details.get("resonance_gate_enabled", False)),
            'resonance_gate_passed': bool(debug_details.get("resonance_gate_passed", False)),
            'resonance_gate_reason': str(debug_details.get("resonance_gate_reason", "")),
            'resonance_gate_position_scale': float(debug_details.get("resonance_gate_position_scale", 1.0) or 1.0),
            'resonance_volume_warn': bool(debug_details.get("resonance_volume_warn", False)),
            'resonance_vwap_telemetry_warn': bool(debug_details.get("resonance_vwap_telemetry_warn", False)),
            'overheat_penalty': overheat_penalty,
            'legacy_4h_boost': legacy_4h_boost,
            'effective_4h_score': effective_4h_score,
            'entry_refine_15m': entry_refine_15m,
            'signal_score_threshold': threshold,
            'threshold_source': None if is_trial_entry else threshold_source,
            'competition_score': competition_score,
            'priority_signal': priority_signal,
            'priority_execution_applied': priority_execution_plan['priority_execution_applied'],
            'priority_execution_tier': priority_execution_plan['priority_execution_tier'],
            'priority_portion_bonus_mult': 1.10 if priority_signal and self.config.enable_priority_allocation else 1.0,
            'priority_soft_cap': None,
            'execution_route': priority_execution_plan['execution_route'],
            'entry_time_in_force': priority_execution_plan['entry_time_in_force'],
            'entry_expire_seconds': priority_execution_plan['entry_expire_seconds'],
            'entry_price_mode': priority_execution_plan['entry_price_mode'],
            'entry_retry_enabled': priority_execution_plan['entry_retry_enabled'],
            'entry_retry_max_attempts': priority_execution_plan['entry_retry_max_attempts'],
            'entry_market_fallback_enabled': priority_execution_plan['entry_market_fallback_enabled'],
            'entry_market_fallback_timeout_ms': priority_execution_plan['entry_market_fallback_timeout_ms'],
            'entry_market_fallback_max_slippage_bps': priority_execution_plan['entry_market_fallback_max_slippage_bps'],
            'entry_execution_policy': priority_execution_plan['entry_execution_policy'],
            'neutral_upgrade_considered': neutral_upgrade_considered,
            'neutral_upgrade_applied': neutral_upgrade_applied,
            'neutral_upgrade_penalty_mult': neutral_upgrade_penalty_mult,
            'neutral_upgrade_mode': neutral_upgrade_mode,
            'neutral_upgrade_threshold_override': neutral_upgrade_threshold_override,
            'neutral_original_reason': neutral_original_reason,
            'neutral_upgrade_direction': neutral_upgrade_direction,
            'veto_type': VetoType.NONE.value,
            'reject_stage': '',
            'reject_reason_code': '',
            'reject_reason_detail': '',
            'final_block_reason': '',
            'final_leverage_after_rsi': 1.0,
            'final_portion_after_rsi': 1.0,
            'total_score': final_score,
            'stop_price': stop_price,
            'stop_loss_pct': stop_pct,
            'stop_details': stop_details,
        }
        self._last_analysis.update(self._default_rsi_launch_sovereign_details())
        self._last_analysis.update(rsi_launch_sovereign)

        return MACDSignalV2(
            direction=trade_direction,
            signal_score=final_score,
            signal_type_1h=signal_type_1h,
            signal_strength_1h=signal_strength_1h,
            is_4h_enhanced=is_4h_enhanced,
            enhancement_score=enhancement_score,
            entry_type_15m=entry_type_15m,
            entry_score_15m=entry_score_15m,
            vwap_score=vwap_score,
            vwap_deviation=(close_price - vwap) / vwap if vwap > 0 else 0,
            vwap_state=vwap_state,
            vwap_location_score=vwap_location_score,
            ema_multiplier=ema_multiplier,
            ema_structure_status=ema_status,
            veto_type=VetoType.NONE,
            veto_reason="",
            suggested_stop_price=stop_price,
            stop_loss_pct=stop_pct,
            is_trial_entry=is_trial_entry,
            entry_scale=entry_scale,
            details=self._last_analysis
        )
    
    def get_last_analysis(self) -> Dict:
        """获取最近一次分析结果"""
        return self._last_analysis.copy()
    
    def calculate_leverage(
        self,
        score: float,
        ema_multiplier: float = 1.0,
        signal_type_1h: Optional[str] = None,
        symbol: Optional[str] = None,
        is_trial_entry: bool = False,
        rsi_conflict: bool = False,
        rsi_probe_mode: bool = False,
    ) -> int:
        """
        根据评分计算杠杆（实盘配置：2X/3X/4X）
        
        Args:
            score: 信号评分
            ema_multiplier: BOLL结构修正系数，强趋势(1.2)时降杠杆
        
        Returns:
            杠杆倍数
        """
        if score >= 0.90:
            base_leverage = 4
        elif score >= 0.85:
            base_leverage = 3
        elif score >= 0.75:
            base_leverage = 2
        else:
            return 0
        
        # BOLL强趋势降杠杆（强趋势可能已运行较长时间）
        if ema_multiplier >= 1.2:
            leverage = max(2, int(base_leverage * self.config.ema_strong_trend_leverage_mult))
        else:
            leverage = base_leverage

        red_bar_probe_mode = self._is_red_bar_growing_probe_overlay(signal_type_1h)
        green_bar_probe_mode = self._is_green_bar_growing_probe_overlay(signal_type_1h)
        if red_bar_probe_mode:
            leverage = min(leverage, max(1, int(self.config.red_bar_growing_probe_max_leverage or 2)))
        if green_bar_probe_mode:
            leverage = min(leverage, max(1, int(self.config.green_bar_growing_probe_max_leverage or 2)))
        if rsi_probe_mode or red_bar_probe_mode:
            leverage = min(leverage, max(1, int(self.config.rsi_probe_forced_leverage or 2)))
        elif rsi_conflict and leverage > 2:
            leverage -= 1

        if (
            self.config.is_flip_bearish_normal_ema(signal_type_1h, ema_multiplier)
            and self.config.flip_bearish_normal_ema_max_leverage > 0
        ):
            leverage = min(leverage, int(self.config.flip_bearish_normal_ema_max_leverage))

        if is_trial_entry and self.config.preflip_trial_max_leverage > 0:
            leverage = min(leverage, int(self.config.preflip_trial_max_leverage))

        if self.is_watchlist_symbol(symbol) and self.config.symbol_risk_watchlist_max_leverage > 0:
            leverage = min(leverage, int(self.config.symbol_risk_watchlist_max_leverage))
        
        return leverage
    
    def calculate_portion_multiplier(self, score: float) -> float:
        """根据评分计算仓位乘数"""
        if score >= 0.90:
            return 1.2
        elif score >= 0.80:
            return 1.0
        elif score >= 0.65:
            return 0.8
        elif score >= 0.55:
            return 0.6
        return 0.0

    def calculate_position_portion(
        self,
        score: float,
        base_default_portion: float,
        base_max_symbol_position_portion: float,
        symbol: Optional[str] = None,
        signal_type_1h: Optional[str] = None,
        vwap_score: float = 0.0,
        vwap_state: Optional[str] = None,
        bonus_multiplier: float = 1.0,
        is_trial_entry: bool = False,
        entry_scale: float = 1.0,
        session_scale: float = 1.0,
        rsi_exposure_mult: float = 1.0,
        rsi_conflict: bool = False,
        rsi_conflict_portion_mult: float = 0.70,
        priority_signal: bool = False,
        rsi_probe_mode: bool = False,
    ) -> float:
        portion_mult = self.calculate_portion_multiplier(score)
        if portion_mult <= 0:
            return 0.0

        if not priority_signal:
            priority_signal = self._resolve_priority_signal(signal_type_1h, vwap_state)

        target_portion = float(base_default_portion)
        max_symbol_position_portion = float(base_max_symbol_position_portion)

        if priority_signal and self.config.enable_priority_allocation:
            target_portion *= 1.10
            max_symbol_position_portion = min(
                1.0,
                max(
                    max_symbol_position_portion,
                    float(base_max_symbol_position_portion) + float(self.config.priority_allocation_overdraft_pct),
                ),
            )

        if str(vwap_state or "").strip().lower() == "short_dual_pressure":
            target_portion += float(self.config.dual_pressure_target_portion_bonus) * max(0.0, float(bonus_multiplier))
            if self.config.dual_pressure_max_symbol_position_portion > 0:
                max_symbol_position_portion = max(
                    max_symbol_position_portion,
                    float(self.config.dual_pressure_max_symbol_position_portion),
                )

        if self.is_watchlist_symbol(symbol) and self.config.symbol_risk_watchlist_max_position_portion > 0:
            max_symbol_position_portion = min(
                max_symbol_position_portion,
                float(self.config.symbol_risk_watchlist_max_position_portion),
            )

        portion = min(max_symbol_position_portion, target_portion * portion_mult)
        portion *= self.resolve_vwap_score_position_multiplier(
            vwap_score=vwap_score,
            signal_type_1h=signal_type_1h,
            vwap_state=vwap_state,
        )
        portion = min(max_symbol_position_portion, portion)
        if is_trial_entry:
            portion *= self._clamp(entry_scale, 0.05, 1.0)
        portion *= self._clamp(rsi_exposure_mult, 0.0, 1.2)
        red_bar_probe_mode = self._is_red_bar_growing_probe_overlay(signal_type_1h)
        green_bar_probe_mode = self._is_green_bar_growing_probe_overlay(signal_type_1h)
        if rsi_probe_mode or red_bar_probe_mode:
            portion *= self._clamp(float(self.config.rsi_probe_portion_scale), 0.0, 1.0)
        if red_bar_probe_mode:
            portion *= self._clamp(float(self.config.red_bar_growing_probe_position_penalty), 0.0, 1.0)
        if green_bar_probe_mode:
            green_penalty = self._clamp(float(self.config.green_bar_growing_probe_position_penalty), 0.0, 1.0)
            if green_penalty > 0.10:
                green_penalty *= self._clamp(float(self.config.rsi_probe_portion_scale), 0.0, 1.0)
            portion *= green_penalty
        if rsi_conflict:
            portion *= self._clamp(float(rsi_conflict_portion_mult), 0.0, 1.0)
        portion *= self.resolve_symbol_risk_session_scale(symbol, session_scale)
        return portion
