"""
多时间框架（MTF）交易系统 V1.0
核心逻辑：1H为主执行层，4H定宏观边界，15m抓微观动能
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class TrendDirection(Enum):
    """趋势方向"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalGrade(Enum):
    """信号等级"""
    S_GRADE = "S"  # 90-100分，全仓
    A_GRADE = "A"  # 70-89分，半仓
    B_GRADE = "B"  # <70分，忽略


class MarketRegime(Enum):
    """市场状态"""
    TREND_ON = "trend_on"      # 强趋势
    PULLBACK = "pullback"       # 次级回调
    CHOP = "chop"               # 无序震荡


class SignalType(Enum):
    """信号类型"""
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    NONE = "none"


@dataclass
class MTFConfig:
    """多时间框架配置"""
    # EMA参数
    ema_fast: int = 21
    ema_medium: int = 55
    ema_slow: int = 200
    
    # MACD参数 - 4H
    macd_4h_fast: int = 12
    macd_4h_slow: int = 26
    macd_4h_signal: int = 9
    
    # MACD参数 - 15m
    macd_15m_fast: int = 8
    macd_15m_slow: int = 21
    macd_15m_signal: int = 5
    
    # 评分阈值
    score_pass_threshold: int = 70
    score_s_grade_min: int = 90
    score_a_grade_min: int = 70
    
    # 风控参数
    max_risk_per_trade: float = 0.015  # 1.5%
    min_risk_reward: float = 2.0
    
    # 重入抑制
    max_daily_stop_losses: int = 2
    freeze_hours_after_max_loss: int = 24


@dataclass
class MTFSignal:
    """多时间框架交易信号"""
    signal_type: SignalType
    grade: SignalGrade
    score: int
    direction: TrendDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    position_size_pct: float  # 仓位比例
    reason: str
    score_breakdown: Dict[str, int] = field(default_factory=dict)
    structure: List[str] = field(default_factory=list)


class TechnicalIndicators:
    """技术指标计算工具"""
    
    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """计算 EMA"""
        multiplier = 2 / (period + 1)
        ema = np.zeros_like(prices, dtype=float)
        ema[0] = prices[0]
        
        for i in range(1, len(prices)):
            ema[i] = (prices[i] * multiplier) + (ema[i-1] * (1 - multiplier))
        
        return ema
    
    @staticmethod
    def calculate_macd(prices: np.ndarray,
                      fast: int,
                      slow: int,
                      signal: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算 MACD"""
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow)
        
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_vwap(high: np.ndarray,
                       low: np.ndarray,
                       close: np.ndarray,
                       volume: np.ndarray,
                       anchor_point: int = 0) -> np.ndarray:
        """计算 VWAP"""
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        cum_tp_volume = np.cumsum(tp_volume)
        cum_volume = np.cumsum(volume)
        
        vwap = np.zeros_like(close, dtype=float)
        for i in range(anchor_point, len(close)):
            if cum_volume[i] != 0:
                vwap[i] = cum_tp_volume[i] / cum_volume[i]
            else:
                vwap[i] = vwap[i-1] if i > 0 else close[i]
        
        return vwap
    
    @staticmethod
    def calculate_atr(high: np.ndarray,
                     low: np.ndarray,
                     close: np.ndarray,
                     period: int = 14) -> np.ndarray:
        """计算 ATR"""
        tr = np.zeros(len(close))
        
        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        
        atr = TechnicalIndicators.calculate_ema(tr, period)
        return atr


class MacroLayer:
    """宏观层 (4H) - 定调与风控"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def get_direction_permission(self,
                                close: np.ndarray,
                                macd_line: np.ndarray,
                                signal_line: np.ndarray,
                                histogram: np.ndarray) -> Dict[str, any]:
        """
        获取方向许可（4H 一票否决制）
        
        返回：
        {
            "long_allowed": bool,
            "short_allowed": bool,
            "reason": str,
            "macd_state": str  # "bullish", "bearish", "neutral"
        }
        """
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        current_price = close[-1]
        current_ema55 = ema55[-1]
        
        # MACD 状态
        current_hist = histogram[-1]
        prev_hist = histogram[-2]
        
        # 检查死叉/金叉
        is_death_cross = (histogram[-2] > 0 and histogram[-1] < 0)
        is_golden_cross = (histogram[-2] < 0 and histogram[-1] > 0)
        
        # 检查顶背离/底背离
        divergence = self._check_divergence(close, histogram)
        
        result = {
            "long_allowed": False,
            "short_allowed": False,
            "reason": "",
            "macd_state": "neutral"
        }
        
        # 判断 MACD 状态
        if current_hist > 0:
            result["macd_state"] = "bullish"
        elif current_hist < 0:
            result["macd_state"] = "bearish"
        
        # 做多许可
        if current_price > current_ema55:
            if not (divergence == "bearish" or is_death_cross):
                result["long_allowed"] = True
                result["reason"] = "4H 多头许可通过"
            else:
                result["reason"] = f"4H 做多被否决: {divergence} 或死叉"
        
        # 做空许可
        if current_price < current_ema55:
            if not (divergence == "bullish" or is_golden_cross):
                result["short_allowed"] = True
                result["reason"] = "4H 空头许可通过"
            else:
                result["reason"] = f"4H 做空被否决: {divergence} 或金叉"
        
        return result
    
    def _check_divergence(self,
                         prices: np.ndarray,
                         histogram: np.ndarray,
                         lookback: int = 20) -> str:
        """检查背离"""
        if len(prices) < lookback + 2:
            return "none"
        
        recent_prices = prices[-lookback:]
        recent_hist = histogram[-lookback:]
        
        # 找价格高点
        price_high_idx = np.argmax(recent_prices)
        hist_high_idx = np.argmax(recent_hist)
        
        # 顶背离
        if (price_high_idx > hist_high_idx and
            recent_prices[price_high_idx] > recent_prices[hist_high_idx] and
            recent_hist[price_high_idx] < recent_hist[hist_high_idx]):
            return "bearish"
        
        # 找价格低点
        price_low_idx = np.argmin(recent_prices)
        hist_low_idx = np.argmin(recent_hist)
        
        # 底背离
        if (price_low_idx > hist_low_idx and
            recent_prices[price_low_idx] < recent_prices[hist_low_idx] and
            recent_hist[price_low_idx] > recent_hist[hist_low_idx]):
            return "bullish"
        
        return "none"


class CoreLayer:
    """执行层 (1H) - 信号生成核心"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def identify_regime(self, close: np.ndarray, vwap: np.ndarray) -> MarketRegime:
        """
        识别市场状态
        
        1. 强趋势：EMA21 与 EMA55 发散，价格稳定在 VWAP 一侧
        2. 次级回调：价格穿透 EMA21，受 EMA55 和 VWAP 支撑
        3. 无序震荡：均线频繁交叉，价格围绕 VWAP 穿插
        """
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        
        current_price = close[-1]
        current_ema21 = ema21[-1]
        current_ema55 = ema55[-1]
        current_vwap = vwap[-1]
        
        # 检查均线发散度
        ema_spread = abs(current_ema21 - current_ema55) / current_ema55
        
        # 检查最近 20 根 K 线的均线交叉次数
        cross_count = 0
        for i in range(-20, -1):
            if (ema21[i] > ema55[i]) != (ema21[i+1] > ema55[i+1]):
                cross_count += 1
        
        # 检查价格与 VWAP 关系
        price_vs_vwap = np.sum(close[-20:] > vwap[-20:])
        
        # 判断状态
        if ema_spread > 0.01 and cross_count < 2:
            # 均线发散，交叉少
            if (price_vs_vwap >= 15 or price_vs_vwap <= 5):
                return MarketRegime.TREND_ON
        
        if cross_count < 3:
            # 检查是否在回调
            if abs(current_price - current_ema21) / current_ema21 < 0.02:
                # 价格接近 EMA21
                if (current_price > current_ema55 and 
                    abs(current_price - current_vwap) / current_vwap < 0.02):
                    return MarketRegime.PULLBACK
        
        if cross_count >= 3:
            return MarketRegime.CHOP
        
        return MarketRegime.CHOP
    
    def calculate_trend_score(self,
                             close: np.ndarray,
                             vwap: np.ndarray) -> int:
        """
        计算 1H 趋势得分 (40分)
        
        条件：价格 > EMA21 > EMA55 且 价格 > VWAP
        """
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        
        current_price = close[-1]
        current_ema21 = ema21[-1]
        current_ema55 = ema55[-1]
        current_vwap = vwap[-1]
        
        score = 0
        
        # 检查均线排列
        if current_ema21 > current_ema55:
            score += 15
            
            if current_price > current_ema21:
                score += 15
                
                if current_price > current_vwap:
                    score += 10
        
        return min(score, 40)
    
    def calculate_pullback_score(self, close: np.ndarray) -> int:
        """
        计算 1H 回撤得分 (20分)
        
        条件：价格回踩 EMA21 且未跌破 EMA55
        """
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        
        current_price = close[-1]
        current_ema21 = ema21[-1]
        current_ema55 = ema55[-1]
        
        score = 0
        
        # 检查是否回踩 EMA21
        distance_to_ema21 = abs(current_price - current_ema21) / current_ema21
        
        if distance_to_ema21 < 0.02:  # 2% 范围内
            score += 10
            
            # 检查是否守住 EMA55
            if current_price > current_ema55:
                score += 10
        
        return min(score, 20)
    
    def check_ema_pullback_structure(self, close: np.ndarray) -> Dict[str, any]:
        """
        检查 EMA21 回踩二次启动结构
        
        返回：
        {
            "has_structure": bool,
            "pullback_depth": float,
            "support_level": float  # 支撑强度
        }
        """
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        
        current_price = close[-1]
        current_ema21 = ema21[-1]
        current_ema55 = ema55[-1]
        
        # 查找最近的峰值
        recent_high = np.max(close[-30:])
        high_idx = np.argmax(close[-30:])
        
        # 检查是否有回踩
        pullback_low = np.min(close[high_idx:])
        pullback_depth = (recent_high - pullback_low) / recent_high
        
        # 检查当前位置
        distance_to_ema21 = abs(current_price - current_ema21) / current_ema21
        
        has_structure = (
            0.01 <= pullback_depth <= 0.05 and  # 回踩 1%-5%
            distance_to_ema21 < 0.02 and  # 接近 EMA21
            current_price > current_ema55  # 守住 EMA55
        )
        
        support_strength = max(0, 1 - (current_price - current_ema55) / current_ema55 * 10)
        
        return {
            "has_structure": has_structure,
            "pullback_depth": pullback_depth,
            "support_level": support_strength
        }


class MicroLayer:
    """微观层 (15m) - 精准入场与风控"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def calculate_momentum_score(self,
                                close: np.ndarray,
                                histogram: np.ndarray) -> int:
        """
        计算 15m 动能得分 (20分)
        
        条件：MACD 柱子缩短并翻红或金叉
        """
        current_hist = histogram[-1]
        prev_hist = histogram[-2]
        
        score = 0
        
        # 检查金叉
        is_golden_cross = (histogram[-2] <= 0 and histogram[-1] > 0)
        is_death_cross = (histogram[-2] >= 0 and histogram[-1] < 0)
        
        # 检查柱子翻红
        bar_turning_red = (prev_hist < 0 and current_hist > 0)
        
        # 检查柱子缩短
        hist_shortening = abs(current_hist) < abs(prev_hist)
        
        if is_golden_cross:
            score = 20
        elif bar_turning_red:
            score = 18
        elif hist_shortening and current_hist > 0:
            score = 15
        elif current_hist > 0:
            score = 10
        
        return min(score, 20)
    
    def check_exhaustion_signal(self,
                               close: np.ndarray,
                               histogram: np.ndarray) -> Dict[str, any]:
        """
        检查微观衰竭信号
        
        用于持仓中的提前平仓防守
        """
        divergence = self._check_divergence(close, histogram)
        
        current_hist = histogram[-1]
        prev_hist = histogram[-2]
        
        # 检查死叉
        is_death_cross = (histogram[-2] > 0 and histogram[-1] < 0)
        is_golden_cross = (histogram[-2] < 0 and histogram[-1] > 0)
        
        # 检查动能衰退
        momentum_declining = (
            current_hist > 0 and 
            abs(current_hist) < abs(prev_hist) and
            abs(current_hist) < abs(histogram[-3])
        )
        
        exhaustion = divergence != "none" or is_death_cross
        
        return {
            "has_exhaustion": exhaustion,
            "divergence": divergence,
            "is_death_cross": is_death_cross,
            "momentum_declining": momentum_declining,
            "action": "close_partial" if exhaustion else "hold"
        }
    
    def _check_divergence(self,
                         prices: np.ndarray,
                         histogram: np.ndarray,
                         lookback: int = 15) -> str:
        """检查 15m 背离"""
        if len(prices) < lookback + 2:
            return "none"
        
        recent_prices = prices[-lookback:]
        recent_hist = histogram[-lookback:]
        
        # 顶背离
        price_high_idx = np.argmax(recent_prices)
        hist_high_idx = np.argmax(recent_hist)
        
        if (price_high_idx > hist_high_idx and
            recent_prices[price_high_idx] > recent_prices[hist_high_idx] and
            recent_hist[price_high_idx] < recent_hist[hist_high_idx]):
            return "bearish"
        
        # 底背离
        price_low_idx = np.argmin(recent_prices)
        hist_low_idx = np.argmin(recent_hist)
        
        if (price_low_idx > hist_low_idx and
            recent_prices[price_low_idx] < recent_prices[hist_low_idx] and
            recent_hist[price_low_idx] > recent_hist[hist_low_idx]):
            return "bullish"
        
        return "none"


class ScoreFusionEngine:
    """分数融合引擎"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def fuse_scores(self,
                   trend_score: int,
                   pullback_score: int,
                   momentum_score: int,
                   macro_alignment_score: int,
                   regime: MarketRegime) -> Tuple[int, SignalGrade]:
        """
        融合所有得分
        
        返回：(总分, 信号等级)
        """
        # 基础融合
        total_score = trend_score + pullback_score + momentum_score + macro_alignment_score
        
        # 根据市场状态调整
        if regime == MarketRegime.TREND_ON:
            # 强趋势中，提升结构分，弱化动能要求
            if trend_score >= 30:
                total_score += 5
        elif regime == MarketRegime.PULLBACK:
            # 回调中，提升动能分要求
            if momentum_score < 15:
                total_score -= 5
        
        # 确定等级
        if total_score >= self.config.score_s_grade_min:
            grade = SignalGrade.S_GRADE
        elif total_score >= self.config.score_a_grade_min:
            grade = SignalGrade.A_GRADE
        else:
            grade = SignalGrade.B_GRADE
        
        return total_score, grade
    
    def calculate_position_size(self,
                               grade: SignalGrade,
                               risk_distance: float,
                               total_capital: float) -> float:
        """
        根据信号等级计算仓位
        
        S级：全仓（标准仓位）
        A级：半仓
        """
        max_risk = total_capital * self.config.max_risk_per_trade
        
        position_size = max_risk / risk_distance
        
        if grade == SignalGrade.S_GRADE:
            position_pct = 1.0
        elif grade == SignalGrade.A_GRADE:
            position_pct = 0.5
        else:
            position_pct = 0.0
        
        return position_size * position_pct


class MTFTradingSystem:
    """多时间框架交易系统"""
    
    def __init__(self, config: Optional[MTFConfig] = None):
        self.config = config or MTFConfig()
        
        self.macro_layer = MacroLayer(self.config)
        self.core_layer = CoreLayer(self.config)
        self.micro_layer = MicroLayer(self.config)
        self.score_engine = ScoreFusionEngine(self.config)
    
    def analyze(self,
               # 4H 数据
               close_4h: np.ndarray,
               # 1H 数据
               high_1h: np.ndarray,
               low_1h: np.ndarray,
               close_1h: np.ndarray,
               volume_1h: np.ndarray,
               # 15m 数据
               close_15m: np.ndarray) -> Optional[MTFSignal]:
        """
        多时间框架分析
        
        流程：
        1. 4H 获取方向许可
        2. 1H 识别市场状态
        3. 1H 计算结构得分
        4. 15m 计算动能得分
        5. 4H MACD 计算顺势得分
        6. 分数融合
        7. 生成信号
        """
        
        # 步骤 1: 4H 方向许可
        _, _, histogram_4h = TechnicalIndicators.calculate_macd(
            close_4h,
            self.config.macd_4h_fast,
            self.config.macd_4h_slow,
            self.config.macd_4h_signal
        )
        
        macd_line_4h, signal_line_4h, _ = TechnicalIndicators.calculate_macd(
            close_4h,
            self.config.macd_4h_fast,
            self.config.macd_4h_slow,
            self.config.macd_4h_signal
        )
        
        direction_permission = self.macro_layer.get_direction_permission(
            close_4h, macd_line_4h, signal_line_4h, histogram_4h
        )
        
        if not (direction_permission["long_allowed"] or direction_permission["short_allowed"]):
            return None  # 4H 否决
        
        # 步骤 2: 1H 市场状态识别
        vwap_1h = TechnicalIndicators.calculate_vwap(high_1h, low_1h, close_1h, volume_1h)
        regime = self.core_layer.identify_regime(close_1h, vwap_1h)
        
        if regime == MarketRegime.CHOP:
            return None  # 震荡市场不交易
        
        # 步骤 3: 1H 趋势得分 (40分)
        trend_score = self.core_layer.calculate_trend_score(close_1h, vwap_1h)
        
        # 步骤 4: 1H 回撤得分 (20分)
        pullback_score = self.core_layer.calculate_pullback_score(close_1h)
        
        # 步骤 5: 15m 动能得分 (20分)
        _, _, histogram_15m = TechnicalIndicators.calculate_macd(
            close_15m,
            self.config.macd_15m_fast,
            self.config.macd_15m_slow,
            self.config.macd_15m_signal
        )
        
        momentum_score = self.micro_layer.calculate_momentum_score(close_15m, histogram_15m)
        
        # 步骤 6: 4H MACD 顺势得分 (20分)
        macro_alignment_score = self._calculate_macro_alignment_score(histogram_4h)
        
        # 步骤 7: 分数融合
        total_score, grade = self.score_engine.fuse_scores(
            trend_score,
            pullback_score,
            momentum_score,
            macro_alignment_score,
            regime
        )
        
        if grade == SignalGrade.B_GRADE:
            return None  # 分数不足
        
        # 确定方向
        if direction_permission["long_allowed"]:
            direction = TrendDirection.BULLISH
        else:
            direction = TrendDirection.BEARISH
        
        # 计算止损止盈
        entry_price = close_1h[-1]
        stop_loss, take_profit = self._calculate_exit_levels(
            close_1h, entry_price, direction, regime
        )
        
        risk_reward = abs(take_profit - entry_price) / abs(stop_loss - entry_price)
        
        if risk_reward < self.config.min_risk_reward:
            return None  # 风险回报比不足
        
        # 计算仓位
        risk_distance = abs(entry_price - stop_loss)
        position_size_pct = 1.0 if grade == SignalGrade.S_GRADE else 0.5
        
        # 生成信号
        signal_type = SignalType.OPEN_LONG if direction == TrendDirection.BULLISH else SignalType.OPEN_SHORT
        
        score_breakdown = {
            "trend_score": trend_score,
            "pullback_score": pullback_score,
            "momentum_score": momentum_score,
            "macro_alignment_score": macro_alignment_score,
            "total_score": total_score
        }
        
        structure = self._build_structure(
            regime, direction, grade, score_breakdown,
            direction_permission["reason"]
        )
        
        reason = self._generate_reason(direction, grade, total_score, regime)
        
        return MTFSignal(
            signal_type=signal_type,
            grade=grade,
            score=total_score,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            position_size_pct=position_size_pct,
            reason=reason,
            score_breakdown=score_breakdown,
            structure=structure
        )
    
    def _calculate_macro_alignment_score(self, histogram_4h: np.ndarray) -> int:
        """计算 4H MACD 顺势得分 (20分)"""
        current_hist = histogram_4h[-1]
        prev_hist = histogram_4h[-2]
        
        score = 0
        
        if current_hist > 0:
            score += 10
            
            if abs(current_hist) > abs(prev_hist):
                score += 10
        
        return min(score, 20)
    
    def _calculate_exit_levels(self,
                              close: np.ndarray,
                              entry_price: float,
                              direction: TrendDirection,
                              regime: MarketRegime) -> Tuple[float, float]:
        """计算止损止盈"""
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        current_ema55 = ema55[-1]
        
        # 结构止损
        recent_low = np.min(close[-20:])
        recent_high = np.max(close[-20:])
        
        if direction == TrendDirection.BULLISH:
            # 多头止损：EMA55 或最近低点
            stop_loss = max(current_ema55 * 0.99, recent_low)
            # 止盈：前高或 2.5 倍风险
            risk = entry_price - stop_loss
            take_profit = entry_price + (risk * 2.5)
        else:
            # 空头止损
            stop_loss = min(current_ema55 * 1.01, recent_high)
            risk = stop_loss - entry_price
            take_profit = entry_price - (risk * 2.5)
        
        return stop_loss, take_profit
    
    def _build_structure(self,
                        regime: MarketRegime,
                        direction: TrendDirection,
                        grade: SignalGrade,
                        score_breakdown: Dict[str, int],
                        macro_reason: str) -> List[str]:
        """构建结构说明"""
        structure = []
        
        structure.append(f"市场状态: {regime.value}")
        structure.append(f"方向: {direction.value}")
        structure.append(f"信号等级: {grade.value} ({score_breakdown['total_score']}分)")
        structure.append(f"4H 宏观: {macro_reason}")
        structure.append(f"1H 趋势得分: {score_breakdown['trend_score']}/40")
        structure.append(f"1H 回撤得分: {score_breakdown['pullback_score']}/20")
        structure.append(f"15m 动能得分: {score_breakdown['momentum_score']}/20")
        structure.append(f"4H 顺势得分: {score_breakdown['macro_alignment_score']}/20")
        
        return structure
    
    def _generate_reason(self,
                        direction: TrendDirection,
                        grade: SignalGrade,
                        score: int,
                        regime: MarketRegime) -> str:
        """生成交易理由"""
        direction_text = "做多" if direction == TrendDirection.BULLISH else "做空"
        grade_text = {
            SignalGrade.S_GRADE: "S级(全仓)",
            SignalGrade.A_GRADE: "A级(半仓)",
            SignalGrade.B_GRADE: "B级(忽略)"
        }[grade]
        
        return f"{direction_text}信号 | {grade_text} | 得分:{score} | 状态:{regime.value}"


def create_mtf_system() -> MTFTradingSystem:
    """创建 MTF 交易系统实例"""
    return MTFTradingSystem(MTFConfig())
