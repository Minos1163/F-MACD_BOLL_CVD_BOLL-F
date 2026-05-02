"""
多时间框架（MTF）交易系统 V2.0
核心逻辑：五层共振系统 - 4H宏观定调 → 1H趋势确认 → 15m回调买点 → 5m启动确认 → 1m精准入场
VWAP作为机构成本线贯穿全流程
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
    S_GRADE = "S"  # 五层全共振，全仓
    A_GRADE = "A"  # 四层共振，半仓
    B_GRADE = "B"  # 三层共振，忽略


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


class VWAPState(Enum):
    """VWAP状态"""
    ABOVE = "above"    # 价格 > VWAP，多头控制
    BELOW = "below"    # 价格 < VWAP，空头控制
    NEUTRAL = "neutral"  # 价格接近VWAP


@dataclass
class MTFConfig:
    """多时间框架配置 - 五层共振系统"""
    # EMA参数
    ema_fast: int = 21      # 15m/5m回踩参考
    ema_medium: int = 55    # 1H趋势确认
    ema_slow: int = 200     # 4H宏观趋势
    
    # MACD参数 - 4H (宏观定调)
    macd_4h_fast: int = 12
    macd_4h_slow: int = 26
    macd_4h_signal: int = 9
    
    # MACD参数 - 1H (趋势确认)
    macd_1h_fast: int = 12
    macd_1h_slow: int = 26
    macd_1h_signal: int = 9
    
    # MACD参数 - 15m (回调买点)
    macd_15m_fast: int = 8
    macd_15m_slow: int = 21
    macd_15m_signal: int = 5
    
    # MACD参数 - 5m (启动确认)
    macd_5m_fast: int = 8
    macd_5m_slow: int = 21
    macd_5m_signal: int = 5
    
    # MACD参数 - 1m (精准入场)
    macd_1m_fast: int = 8
    macd_1m_slow: int = 21
    macd_1m_signal: int = 5
    
    # VWAP参数
    vwap_anchor: str = "session"  # session/daily/weekly
    
    # 五层共振评分
    layer_4h_weight: int = 20  # 宏观层权重
    layer_1h_weight: int = 25  # 趋势层权重
    layer_15m_weight: int = 20  # 回调层权重
    layer_5m_weight: int = 20   # 启动层权重
    layer_1m_weight: int = 15   # 入场层权重
    
    # 评分阈值
    score_pass_threshold: int = 70
    score_s_grade_min: int = 90  # 五层全共振
    score_a_grade_min: int = 70  # 四层共振
    
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


class MacroLayer4H:
    """第一层：宏观层 (4H) - 趋势定调"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_4h_trend(self, close: np.ndarray) -> Dict[str, any]:
        """
        4H 趋势分析 - 做多条件：
        1. 价格 > EMA200 (长期偏多)
        2. MACD柱 > 0 (动能向上)
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "price_above_ema200": bool,
            "macd_histogram_positive": bool,
            "reason": str
        }
        """
        # 计算 EMA200
        ema200 = TechnicalIndicators.calculate_ema(close, self.config.ema_slow)
        current_price = close[-1]
        current_ema200 = ema200[-1]
        
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_4h_fast,
            self.config.macd_4h_slow,
            self.config.macd_4h_signal
        )
        current_hist = histogram[-1]
        
        # 检查条件
        price_above_ema200 = current_price > current_ema200
        macd_positive = current_hist > 0
        
        # 计算得分
        score = 0
        if price_above_ema200:
            score += 10
        if macd_positive:
            score += 10
        
        passed = price_above_ema200 and macd_positive
        
        return {
            "passed": passed,
            "score": score,
            "price_above_ema200": price_above_ema200,
            "macd_histogram_positive": macd_positive,
            "reason": f"4H宏观: 价格{'>' if price_above_ema200 else '<'}EMA200, MACD柱{'>' if macd_positive else '<'}0"
        }
    
    def get_direction_permission(self,
                                close: np.ndarray,
                                macd_line: np.ndarray,
                                signal_line: np.ndarray,
                                histogram: np.ndarray) -> Dict[str, any]:
        """获取方向许可（4H 一票否决制）- 保持兼容"""
        ema200 = TechnicalIndicators.calculate_ema(close, self.config.ema_slow)
        current_price = close[-1]
        current_ema200 = ema200[-1]
        
        current_hist = histogram[-1]
        is_death_cross = (histogram[-2] > 0 and histogram[-1] < 0)
        is_golden_cross = (histogram[-2] < 0 and histogram[-1] > 0)
        
        divergence = self._check_divergence(close, histogram)
        
        result = {
            "long_allowed": False,
            "short_allowed": False,
            "reason": "",
            "macd_state": "neutral"
        }
        
        if current_hist > 0:
            result["macd_state"] = "bullish"
        elif current_hist < 0:
            result["macd_state"] = "bearish"
        
        # 做多许可：价格 > EMA200 且 MACD柱 > 0
        if current_price > current_ema200 and current_hist > 0:
            if not (divergence == "bearish" or is_death_cross):
                result["long_allowed"] = True
                result["reason"] = "4H 多头许可通过 (价格>EMA200 + MACD柱>0)"
            else:
                result["reason"] = f"4H 做多被否决: {divergence} 或死叉"
        
        # 做空许可：价格 < EMA200 且 MACD柱 < 0
        if current_price < current_ema200 and current_hist < 0:
            if not (divergence == "bullish" or is_golden_cross):
                result["short_allowed"] = True
                result["reason"] = "4H 空头许可通过 (价格<EMA200 + MACD柱<0)"
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


class LaunchLayer5m:
    """第四层：启动确认层 (5m) - 资金推动确认"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_5m_launch(self,
                         close: np.ndarray,
                         high: np.ndarray,
                         low: np.ndarray,
                         volume: np.ndarray) -> Dict[str, any]:
        """
        5m 启动确认 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格突破VWAP (资金推动)
        
        优化说明：
        - 柱子翻红信号比金叉提前2-3根K线
        - 翻红后红柱增强信号更强
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_5m_fast,
            self.config.macd_5m_slow,
            self.config.macd_5m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                # 红柱增强
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格突破 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分（柱子翻红权重更高）
        score = 0
        if histogram_cross:
            if bars_since_cross <= 2:
                score += 12  # 刚翻红，强信号
            elif bars_since_cross <= 4:
                score += 10  # 翻红后1-2根
            else:
                score += 6   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 3)
        
        if price_above_vwap:
            score += 10
        
        # 通过条件：柱子翻红（或当前红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(20, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "vwap_value": current_vwap,
            "reason": f"5m启动: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'>' if price_above_vwap else '<'}VWAP"
        }


class EntryLayer1m:
    """第五层：精准入场层 (1m) - 启动瞬间捕捉"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_1m_entry(self,
                        close: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        volume: np.ndarray) -> Dict[str, any]:
        """
        1m 精准入场 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格站上VWAP (确认启动)
        
        优化说明：
        - 柱子翻红比金叉提前2-3根K线，捕捉启动瞬间
        - 翻红后红柱增强 = 更强入场信号
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-15分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "entry_price": float,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1m_fast,
            self.config.macd_1m_slow,
            self.config.macd_1m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格站上 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分
        score = 0
        if histogram_cross:
            if bars_since_cross <= 1:
                score += 10  # 刚翻红，最强入场
            elif bars_since_cross <= 3:
                score += 8   # 翻红后1-2根
            else:
                score += 5   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 2)
        
        if price_above_vwap:
            score += 7
        
        # 通过条件：柱子翻红（或红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(15, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "entry_price": current_price,
            "vwap_value": current_vwap,
            "reason": f"1m入场: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'站上' if price_above_vwap else '未站上'}VWAP"
        }


class VWAPAnalyzer:
    """VWAP 分析工具 - 机构成本线"""
    
    @staticmethod
    def get_vwap_state(price: float, vwap: float) -> VWAPState:
        """
        获取 VWAP 状态
        
        价格 > VWAP: 多头控制
        价格 < VWAP: 空头控制
        """
        distance_pct = (price - vwap) / vwap
        if distance_pct > 0.005:
            return VWAPState.ABOVE
        elif distance_pct < -0.005:
            return VWAPState.BELOW
        else:
            return VWAPState.NEUTRAL
    
    @staticmethod
    def calculate_session_vwap(high: np.ndarray,
                                low: np.ndarray,
                                close: np.ndarray,
                                volume: np.ndarray,
                                session_start: int = 0) -> np.ndarray:
        """
        计算会话 VWAP
        
        VWAP = Σ(Price × Volume) / ΣVolume
        """
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        cum_tp_volume = np.cumsum(tp_volume[session_start:])
        cum_volume = np.cumsum(volume[session_start:])
        
        vwap = np.zeros_like(close, dtype=float)
        for i in range(session_start, len(close)):
            rel_idx = i - session_start
            if cum_volume[rel_idx] != 0:
                vwap[i] = cum_tp_volume[rel_idx] / cum_volume[rel_idx]
            else:
                vwap[i] = close[i]
        
        return vwap


class LaunchLayer5m:
    """第四层：启动确认层 (5m) - 资金推动确认"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_5m_launch(self,
                         close: np.ndarray,
                         high: np.ndarray,
                         low: np.ndarray,
                         volume: np.ndarray) -> Dict[str, any]:
        """
        5m 启动确认 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格突破VWAP (资金推动)
        
        优化说明：
        - 柱子翻红信号比金叉提前2-3根K线
        - 翻红后红柱增强信号更强
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_5m_fast,
            self.config.macd_5m_slow,
            self.config.macd_5m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                # 红柱增强
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格突破 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分（柱子翻红权重更高）
        score = 0
        if histogram_cross:
            if bars_since_cross <= 2:
                score += 12  # 刚翻红，强信号
            elif bars_since_cross <= 4:
                score += 10  # 翻红后1-2根
            else:
                score += 6   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 3)
        
        if price_above_vwap:
            score += 10
        
        # 通过条件：柱子翻红（或当前红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(20, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "vwap_value": current_vwap,
            "reason": f"5m启动: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'>' if price_above_vwap else '<'}VWAP"
        }


class EntryLayer1m:
    """第五层：精准入场层 (1m) - 启动瞬间捕捉"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_1m_entry(self,
                        close: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        volume: np.ndarray) -> Dict[str, any]:
        """
        1m 精准入场 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格站上VWAP (确认启动)
        
        优化说明：
        - 柱子翻红比金叉提前2-3根K线，捕捉启动瞬间
        - 翻红后红柱增强 = 更强入场信号
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-15分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "entry_price": float,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1m_fast,
            self.config.macd_1m_slow,
            self.config.macd_1m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格站上 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分
        score = 0
        if histogram_cross:
            if bars_since_cross <= 1:
                score += 10  # 刚翻红，最强入场
            elif bars_since_cross <= 3:
                score += 8   # 翻红后1-2根
            else:
                score += 5   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 2)
        
        if price_above_vwap:
            score += 7
        
        # 通过条件：柱子翻红（或红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(15, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "entry_price": current_price,
            "vwap_value": current_vwap,
            "reason": f"1m入场: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'站上' if price_above_vwap else '未站上'}VWAP"
        }


class VWAPAnalyzer:
    """VWAP 分析工具 - 机构成本线"""
    
    @staticmethod
    def get_vwap_state(price: float, vwap: float) -> VWAPState:
        """
        获取 VWAP 状态
        
        价格 > VWAP: 多头控制
        价格 < VWAP: 空头控制
        """
        distance_pct = (price - vwap) / vwap
        if distance_pct > 0.005:
            return VWAPState.ABOVE
        elif distance_pct < -0.005:
            return VWAPState.BELOW
        else:
            return VWAPState.NEUTRAL
    
    @staticmethod
    def calculate_session_vwap(high: np.ndarray,
                                low: np.ndarray,
                                close: np.ndarray,
                                volume: np.ndarray,
                                session_start: int = 0) -> np.ndarray:
        """
        计算会话 VWAP
        
        VWAP = Σ(Price × Volume) / ΣVolume
        """
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        cum_tp_volume = np.cumsum(tp_volume[session_start:])
        cum_volume = np.cumsum(volume[session_start:])
        
        vwap = np.zeros_like(close, dtype=float)
        for i in range(session_start, len(close)):
            rel_idx = i - session_start
            if cum_volume[rel_idx] != 0:
                vwap[i] = cum_tp_volume[rel_idx] / cum_volume[rel_idx]
            else:
                vwap[i] = close[i]
        
        return vwap


class CoreLayer1H:
    """第二层：趋势确认层 (1H) - 信号生成核心"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_1h_trend(self,
                        close: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        volume: np.ndarray) -> Dict[str, any]:
        """
        1H 趋势确认 - 做多条件：
        1. 价格 > EMA55 (趋势稳定)
        2. MACD向上 (动能向上)
        3. 价格 > VWAP (多头控制)
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-25分
            "price_above_ema55": bool,
            "macd_rising": bool,
            "vwap_state": VWAPState,
            "reason": str
        }
        """
        # 计算 EMA55
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        current_price = close[-1]
        current_ema55 = ema55[-1]
        
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1h_fast,
            self.config.macd_1h_slow,
            self.config.macd_1h_signal
        )
        
        # MACD 向上判断
        macd_rising = histogram[-1] > histogram[-2]
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        
        # VWAP 状态
        vwap_distance_pct = (current_price - current_vwap) / current_vwap
        if vwap_distance_pct > 0.005:
            vwap_state = VWAPState.ABOVE
        elif vwap_distance_pct < -0.005:
            vwap_state = VWAPState.BELOW
        else:
            vwap_state = VWAPState.NEUTRAL
        
        # 检查条件
        price_above_ema55 = current_price > current_ema55
        
        # 计算得分
        score = 0
        if price_above_ema55:
            score += 10
        if macd_rising:
            score += 8
        if vwap_state == VWAPState.ABOVE:
            score += 7
        
        passed = price_above_ema55 and macd_rising and vwap_state == VWAPState.ABOVE
        
        return {
            "passed": passed,
            "score": score,
            "price_above_ema55": price_above_ema55,
            "macd_rising": macd_rising,
            "vwap_state": vwap_state,
            "vwap_value": current_vwap,
            "reason": f"1H趋势: 价格{'>' if price_above_ema55 else '<'}EMA55, MACD{'向上' if macd_rising else '向下'}, VWAP状态={vwap_state.value}"
        }
    
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


class MicroLayer15m:
    """第三层：回调买点层 (15m) - 寻找趋势中的回调买点"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_15m_pullback(self, close: np.ndarray) -> Dict[str, any]:
        """
        15m 回调买点 - 做多条件：
        1. MACD金叉 (动能转强)
        2. 价格回踩EMA21 (趋势中的回调)
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "macd_golden_cross": bool,
            "price_near_ema21": bool,
            "reason": str
        }
        """
        # 计算 EMA21
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_fast)
        current_price = close[-1]
        current_ema21 = ema21[-1]
        
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_15m_fast,
            self.config.macd_15m_slow,
            self.config.macd_15m_signal
        )
        
        # MACD 金叉判断
        macd_golden_cross = histogram[-2] <= 0 and histogram[-1] > 0
        
        # 价格回踩 EMA21 判断 (价格在 EMA21 附近 ±2%)
        distance_to_ema21 = abs(current_price - current_ema21) / current_ema21
        price_near_ema21 = distance_to_ema21 < 0.02
        
        # 计算得分
        score = 0
        if macd_golden_cross:
            score += 12
        if price_near_ema21:
            score += 8
        
        passed = macd_golden_cross and price_near_ema21
        
        return {
            "passed": passed,
            "score": score,
            "macd_golden_cross": macd_golden_cross,
            "price_near_ema21": price_near_ema21,
            "ema21_value": current_ema21,
            "reason": f"15m回调: MACD{'金叉' if macd_golden_cross else '无金叉'}, 价格{'接近' if price_near_ema21 else '远离'}EMA21"
        }
    
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


class LaunchLayer5m:
    """第四层：启动确认层 (5m) - 资金推动确认"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_5m_launch(self,
                         close: np.ndarray,
                         high: np.ndarray,
                         low: np.ndarray,
                         volume: np.ndarray) -> Dict[str, any]:
        """
        5m 启动确认 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格突破VWAP (资金推动)
        
        优化说明：
        - 柱子翻红信号比金叉提前2-3根K线
        - 翻红后红柱增强信号更强
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_5m_fast,
            self.config.macd_5m_slow,
            self.config.macd_5m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                # 红柱增强
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格突破 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分（柱子翻红权重更高）
        score = 0
        if histogram_cross:
            if bars_since_cross <= 2:
                score += 12  # 刚翻红，强信号
            elif bars_since_cross <= 4:
                score += 10  # 翻红后1-2根
            else:
                score += 6   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 3)
        
        if price_above_vwap:
            score += 10
        
        # 通过条件：柱子翻红（或当前红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(20, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "vwap_value": current_vwap,
            "reason": f"5m启动: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'>' if price_above_vwap else '<'}VWAP"
        }


class EntryLayer1m:
    """第五层：精准入场层 (1m) - 启动瞬间捕捉"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_1m_entry(self,
                        close: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        volume: np.ndarray) -> Dict[str, any]:
        """
        1m 精准入场 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格站上VWAP (确认启动)
        
        优化说明：
        - 柱子翻红比金叉提前2-3根K线，捕捉启动瞬间
        - 翻红后红柱增强 = 更强入场信号
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-15分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "entry_price": float,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1m_fast,
            self.config.macd_1m_slow,
            self.config.macd_1m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格站上 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分
        score = 0
        if histogram_cross:
            if bars_since_cross <= 1:
                score += 10  # 刚翻红，最强入场
            elif bars_since_cross <= 3:
                score += 8   # 翻红后1-2根
            else:
                score += 5   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 2)
        
        if price_above_vwap:
            score += 7
        
        # 通过条件：柱子翻红（或红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(15, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "entry_price": current_price,
            "vwap_value": current_vwap,
            "reason": f"1m入场: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'站上' if price_above_vwap else '未站上'}VWAP"
        }


class VWAPAnalyzer:
    """VWAP 分析工具 - 机构成本线"""
    
    @staticmethod
    def get_vwap_state(price: float, vwap: float) -> VWAPState:
        """
        获取 VWAP 状态
        
        价格 > VWAP: 多头控制
        价格 < VWAP: 空头控制
        """
        distance_pct = (price - vwap) / vwap
        if distance_pct > 0.005:
            return VWAPState.ABOVE
        elif distance_pct < -0.005:
            return VWAPState.BELOW
        else:
            return VWAPState.NEUTRAL
    
    @staticmethod
    def calculate_session_vwap(high: np.ndarray,
                                low: np.ndarray,
                                close: np.ndarray,
                                volume: np.ndarray,
                                session_start: int = 0) -> np.ndarray:
        """
        计算会话 VWAP
        
        VWAP = Σ(Price × Volume) / ΣVolume
        """
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        cum_tp_volume = np.cumsum(tp_volume[session_start:])
        cum_volume = np.cumsum(volume[session_start:])
        
        vwap = np.zeros_like(close, dtype=float)
        for i in range(session_start, len(close)):
            rel_idx = i - session_start
            if cum_volume[rel_idx] != 0:
                vwap[i] = cum_tp_volume[rel_idx] / cum_volume[rel_idx]
            else:
                vwap[i] = close[i]
        
        return vwap


class LaunchLayer5m:
    """第四层：启动确认层 (5m) - 资金推动确认"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_5m_launch(self,
                         close: np.ndarray,
                         high: np.ndarray,
                         low: np.ndarray,
                         volume: np.ndarray) -> Dict[str, any]:
        """
        5m 启动确认 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格突破VWAP (资金推动)
        
        优化说明：
        - 柱子翻红信号比金叉提前2-3根K线
        - 翻红后红柱增强信号更强
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-20分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_5m_fast,
            self.config.macd_5m_slow,
            self.config.macd_5m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                # 红柱增强
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格突破 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分（柱子翻红权重更高）
        score = 0
        if histogram_cross:
            if bars_since_cross <= 2:
                score += 12  # 刚翻红，强信号
            elif bars_since_cross <= 4:
                score += 10  # 翻红后1-2根
            else:
                score += 6   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 3)
        
        if price_above_vwap:
            score += 10
        
        # 通过条件：柱子翻红（或当前红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(20, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "vwap_value": current_vwap,
            "reason": f"5m启动: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'>' if price_above_vwap else '<'}VWAP"
        }


class EntryLayer1m:
    """第五层：精准入场层 (1m) - 启动瞬间捕捉"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze_1m_entry(self,
                        close: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        volume: np.ndarray) -> Dict[str, any]:
        """
        1m 精准入场 - 做多条件：
        1. MACD柱子翻红（比金叉提前2-3根K线）
        2. 价格站上VWAP (确认启动)
        
        优化说明：
        - 柱子翻红比金叉提前2-3根K线，捕捉启动瞬间
        - 翻红后红柱增强 = 更强入场信号
        
        返回：
        {
            "passed": bool,
            "score": int,  # 0-15分
            "histogram_cross": bool,       # 柱子翻红信号
            "bars_since_cross": int,       # 翻红后几根K线
            "price_above_vwap": bool,
            "entry_price": float,
            "vwap_value": float,
            "reason": str
        }
        """
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1m_fast,
            self.config.macd_1m_slow,
            self.config.macd_1m_signal
        )
        
        # MACD 柱子翻红检测（比金叉提前2-3根K线）
        histogram_cross = False
        bars_since_cross = -1
        red_bar_strength = 0.0
        
        if len(histogram) >= 5:
            # 检测柱子从负转正
            for i in range(len(histogram) - 2, max(0, len(histogram) - 6), -1):
                if histogram[i] < 0 and histogram[i + 1] >= 0:
                    histogram_cross = True
                    bars_since_cross = len(histogram) - 1 - i
                    break
            
            # 计算红柱强度
            if histogram[-1] > 0 and len(histogram) >= 3:
                if histogram[-1] > histogram[-2] > histogram[-3]:
                    red_bar_strength = 1.0  # 强
                elif histogram[-1] > histogram[-2]:
                    red_bar_strength = 0.7  # 中
                else:
                    red_bar_strength = 0.3  # 弱
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格站上 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分
        score = 0
        if histogram_cross:
            if bars_since_cross <= 1:
                score += 10  # 刚翻红，最强入场
            elif bars_since_cross <= 3:
                score += 8   # 翻红后1-2根
            else:
                score += 5   # 翻红较久
        
        # 红柱增强加分
        if histogram[-1] > 0 and red_bar_strength > 0.5:
            score += int(red_bar_strength * 2)
        
        if price_above_vwap:
            score += 7
        
        # 通过条件：柱子翻红（或红柱增强）且价格在VWAP上方
        passed = (histogram_cross or (histogram[-1] > 0 and red_bar_strength > 0.5)) and price_above_vwap
        
        return {
            "passed": passed,
            "score": min(15, score),
            "histogram_cross": histogram_cross,
            "bars_since_cross": bars_since_cross,
            "red_bar_strength": red_bar_strength,
            "price_above_vwap": price_above_vwap,
            "entry_price": current_price,
            "vwap_value": current_vwap,
            "reason": f"1m入场: MACD柱{'翻红(' + str(bars_since_cross) + '根前)' if histogram_cross else '红柱增强' if histogram[-1] > 0 else '无信号'}, 价格{'站上' if price_above_vwap else '未站上'}VWAP"
        }


class VWAPAnalyzer:
    """VWAP 分析工具 - 机构成本线"""
    
    @staticmethod
    def get_vwap_state(price: float, vwap: float) -> VWAPState:
        """
        获取 VWAP 状态
        
        价格 > VWAP: 多头控制
        价格 < VWAP: 空头控制
        """
        distance_pct = (price - vwap) / vwap
        if distance_pct > 0.005:
            return VWAPState.ABOVE
        elif distance_pct < -0.005:
            return VWAPState.BELOW
        else:
            return VWAPState.NEUTRAL
    
    @staticmethod
    def calculate_session_vwap(high: np.ndarray,
                                low: np.ndarray,
                                close: np.ndarray,
                                volume: np.ndarray,
                                session_start: int = 0) -> np.ndarray:
        """
        计算会话 VWAP
        
        VWAP = Σ(Price × Volume) / ΣVolume
        """
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        cum_tp_volume = np.cumsum(tp_volume[session_start:])
        cum_volume = np.cumsum(volume[session_start:])
        
        vwap = np.zeros_like(close, dtype=float)
        for i in range(session_start, len(close)):
            rel_idx = i - session_start
            if cum_volume[rel_idx] != 0:
                vwap[i] = cum_tp_volume[rel_idx] / cum_volume[rel_idx]
            else:
                vwap[i] = close[i]
        
        return vwap


# Backward-compatible exports for callers and tests that still import the
# original generic layer names.
MacroLayer = MacroLayer4H
CoreLayer = CoreLayer1H
MicroLayer = MicroLayer15m


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

        total_score = max(0, min(100, total_score))
        
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
