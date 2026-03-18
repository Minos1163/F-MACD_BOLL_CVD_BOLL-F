"""
MACD多时间框架策略模块 V1.0

策略架构：
- MACD_1H 定方向（柱子翻红/翻绿/缩短等确认买卖方向）
- MACD_4H 确认增强（同向增强信号，不作为买卖点）
- MACD_15M 跟随入场（跟随1H方向执行买卖）

扫描周期：每15分钟
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import numpy as np


@dataclass
class MACDStrategyConfig:
    """MACD策略配置"""
    # 1H MACD参数
    macd_1h_fast: int = 12
    macd_1h_slow: int = 26
    macd_1h_signal: int = 9
    
    # 4H MACD参数
    macd_4h_fast: int = 12
    macd_4h_slow: int = 26
    macd_4h_signal: int = 9
    
    # 15M MACD参数
    macd_15m_fast: int = 12
    macd_15m_slow: int = 26
    macd_15m_signal: int = 9
    
    # 入场评分阈值
    min_entry_score: float = 0.3
    min_signal_score: float = 0.45
    
    # 评分权重
    weight_1h_direction: float = 0.40  # 1H定方向权重
    weight_4h_enhancement: float = 0.20  # 4H增强权重
    weight_15m_entry: float = 0.25  # 15M入场权重
    weight_volume: float = 0.15  # 成交量权重


@dataclass
class MACDSignal:
    """MACD信号"""
    direction: str  # 'long', 'short', 'neutral'
    signal_score: float  # 0-1
    signal_type_1h: Optional[str] = None  # 1H信号类型
    signal_strength_1h: float = 0.0
    is_4h_enhanced: bool = False
    enhancement_score: float = 0.0
    entry_type_15m: Optional[str] = None
    entry_score_15m: float = 0.0
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class MACDStrategyEngine:
    """MACD策略引擎"""
    
    def __init__(self, config: MACDStrategyConfig = None):
        self.config = config or MACDStrategyConfig()
        self._last_analysis: Dict = {}
    
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
    def calculate_macd(
        prices: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算MACD"""
        ema_fast = MACDStrategyEngine.calculate_ema(prices, fast)
        ema_slow = MACDStrategyEngine.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = MACDStrategyEngine.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def detect_1h_macd_direction(
        self,
        macd_hist_1h: np.ndarray,
        idx: int
    ) -> Tuple[Optional[str], Dict]:
        """
        MACD_1H定方向（核心方向判断）
        
        检测柱子翻红/翻绿/缩短等确认买卖方向：
        - 翻红（负转正）: 做多信号 (强度1.0)
        - 翻绿（正转负）: 做空信号 (强度1.0)
        - 红柱增长（0轴上）: 多头增强 (强度0.8)
        - 绿柱增长（0轴下）: 空头增强 (强度0.8)
        - 红柱缩短（仍在0轴上）: 多头减弱，不入场
        - 绿柱缩短（仍在0轴下）: 空头减弱，不入场
        
        Returns:
            direction: 'long'/'short'/None
            details: 详细信息
        """
        if idx < 3:
            return None, {}
        
        details = {}
        
        # 当前和前一根K线的MACD柱
        hist_0 = macd_hist_1h[idx]
        hist_1 = macd_hist_1h[idx - 1]
        
        direction = None
        signal_type = None
        signal_strength = 0.0
        
        # 1. 翻红检测（负转正）- 强做多信号
        if hist_1 <= 0 and hist_0 > 0:
            direction = 'long'
            signal_type = 'flip_bullish'
            signal_strength = 1.0
            
        # 2. 翻绿检测（正转负）- 强做空信号
        elif hist_1 >= 0 and hist_0 < 0:
            direction = 'short'
            signal_type = 'flip_bearish'
            signal_strength = 1.0
            
        # 3. 红柱增长（0轴上）- 多头增强
        elif hist_0 > 0 and hist_1 > 0 and hist_0 > hist_1:
            direction = 'long'
            signal_type = 'red_bar_growing'
            signal_strength = 0.8
            
        # 4. 绿柱增长（0轴下）- 空头增强
        elif hist_0 < 0 and hist_1 < 0 and hist_0 < hist_1:
            direction = 'short'
            signal_type = 'green_bar_growing'
            signal_strength = 0.8
            
        # 5. 红柱缩短（0轴上）- 多头减弱，不入场
        elif hist_0 > 0 and hist_1 > 0 and hist_0 < hist_1:
            direction = None
            signal_type = 'red_bar_shrinking'
            signal_strength = 0.0
            
        # 6. 绿柱缩短（0轴下）- 空头减弱，不入场
        elif hist_0 < 0 and hist_1 < 0 and hist_0 > hist_1:
            direction = None
            signal_type = 'green_bar_shrinking'
            signal_strength = 0.0
        
        details['signal_type'] = signal_type
        details['signal_strength'] = signal_strength
        details['hist_current'] = hist_0
        details['hist_prev'] = hist_1
        
        return direction, details
    
    def check_4h_macd_enhancement(
        self,
        macd_hist_4h: np.ndarray,
        idx: int,
        direction: str
    ) -> Tuple[bool, float]:
        """
        MACD_4H确认方向增强（不能作为买卖点，只确认增强）
        
        Args:
            direction: 1H确定的方向
        
        Returns:
            is_enhanced: 是否增强
            enhancement_score: 增强评分 (0-1)
        """
        if idx < 2:
            return False, 0.0
        
        hist_0 = macd_hist_4h[idx]
        hist_1 = macd_hist_4h[idx - 1]
        
        enhancement_score = 0.0
        is_enhanced = False
        
        if direction == 'long':
            # 4H MACD柱>0 且在增长 = 多头增强
            if hist_0 > 0:
                enhancement_score += 0.5
                if hist_0 > hist_1:
                    enhancement_score += 0.3
                    is_enhanced = True
                elif hist_0 < hist_1:
                    enhancement_score += 0.1
                    
        elif direction == 'short':
            # 4H MACD柱<0 且在下降 = 空头增强
            if hist_0 < 0:
                enhancement_score += 0.5
                if hist_0 < hist_1:
                    enhancement_score += 0.3
                    is_enhanced = True
                elif hist_0 > hist_1:
                    enhancement_score += 0.1
        
        return is_enhanced, enhancement_score
    
    def check_15m_macd_follow(
        self,
        macd_hist_15m: np.ndarray,
        idx: int,
        direction: str
    ) -> Tuple[bool, float, Dict]:
        """
        MACD_15M跟随1H方向执行买卖
        
        15M不能作为方向的关键点，只是跟随1H方向找入场点
        
        Args:
            direction: 1H确定的方向
        
        Returns:
            can_enter: 是否可以入场
            entry_score: 入场评分 (0-1)
            details: 详细信息
        """
        if idx < 2:
            return False, 0.0, {}
        
        details = {}
        hist_0 = macd_hist_15m[idx]
        hist_1 = macd_hist_15m[idx - 1]
        
        entry_score = 0.0
        can_enter = False
        
        # MACD阈值，避免震荡区
        macd_threshold = 0.00005
        
        if direction == 'long':
            # 跟随做多：15M MACD柱需要>0（或刚翻红）
            
            # 情况1：刚翻红（最强入场）
            if hist_1 <= 0 and hist_0 > 0:
                entry_score = 1.0
                can_enter = True
                details['entry_type'] = 'flip_bullish'
                
            # 情况2：红柱增长
            elif hist_0 > 0 and hist_1 > 0 and hist_0 > hist_1:
                entry_score = 0.85
                can_enter = True
                details['entry_type'] = 'red_bar_growing'
                
            # 情况3：红柱稳定（仍可入场，但评分较低）
            elif hist_0 > macd_threshold and hist_0 > 0:
                entry_score = 0.6
                can_enter = True
                details['entry_type'] = 'red_bar_stable'
                
            # 情况4：红柱缩短 - 入场评分降低
            elif hist_0 > 0 and hist_1 > 0 and hist_0 < hist_1:
                entry_score = 0.3
                can_enter = True
                details['entry_type'] = 'red_bar_shrinking'
                
        elif direction == 'short':
            # 跟随做空：15M MACD柱需要<0（或刚翻绿）
            
            # 情况1：刚翻绿（最强入场）
            if hist_1 >= 0 and hist_0 < 0:
                entry_score = 1.0
                can_enter = True
                details['entry_type'] = 'flip_bearish'
                
            # 情况2：绿柱增长
            elif hist_0 < 0 and hist_1 < 0 and hist_0 < hist_1:
                entry_score = 0.85
                can_enter = True
                details['entry_type'] = 'green_bar_growing'
                
            # 情况3：绿柱稳定
            elif hist_0 < -macd_threshold and hist_0 < 0:
                entry_score = 0.6
                can_enter = True
                details['entry_type'] = 'green_bar_stable'
                
            # 情况4：绿柱缩短
            elif hist_0 < 0 and hist_1 < 0 and hist_0 > hist_1:
                entry_score = 0.3
                can_enter = True
                details['entry_type'] = 'green_bar_shrinking'
        
        details['hist_current'] = hist_0
        details['hist_prev'] = hist_1
        
        return can_enter, entry_score, details
    
    def analyze(
        self,
        macd_hist_15m: np.ndarray,
        macd_hist_1h: np.ndarray,
        macd_hist_4h: np.ndarray,
        idx_15m: int,
        idx_1h: int,
        idx_4h: int,
        volume_ratio: float = 1.0
    ) -> MACDSignal:
        """
        综合分析MACD信号
        
        Args:
            macd_hist_15m: 15分钟MACD柱状图
            macd_hist_1h: 1小时MACD柱状图
            macd_hist_4h: 4小时MACD柱状图
            idx_15m: 当前15分钟索引
            idx_1h: 对应1小时索引
            idx_4h: 对应4小时索引
            volume_ratio: 成交量比率（当前/平均）
        
        Returns:
            MACDSignal: 信号结果
        """
        # ========== 第1步：MACD_1H 定方向 ==========
        direction_1h, details_1h = self.detect_1h_macd_direction(
            macd_hist_1h, idx_1h
        )
        if direction_1h is None:
            return MACDSignal(
                direction='neutral',
                signal_score=0.0,
                details={'reason': '1H无明确方向'}
            )
        
        # ========== 第2步：MACD_4H 确认增强 ==========
        is_4h_enhanced, enhancement_score = self.check_4h_macd_enhancement(
            macd_hist_4h, idx_4h, direction_1h
        )
        
        # ========== 第3步：MACD_15M 跟随入场 ==========
        can_enter, entry_score_15m, details_15m = self.check_15m_macd_follow(
            macd_hist_15m, idx_15m, direction_1h
        )
        
        if not can_enter:
            return MACDSignal(
                direction='neutral',
                signal_score=0.0,
                details={'reason': '15M未确认入场'}
            )
        
        # 最低入场评分要求
        if entry_score_15m < self.config.min_entry_score:
            return MACDSignal(
                direction='neutral',
                signal_score=0.0,
                details={'reason': f'15M入场评分过低: {entry_score_15m:.2f}'}
            )
        
        # ========== 综合评分 ==========
        score = 0.0
        
        # 1H定方向评分 (40%)
        signal_strength_1h = details_1h.get('signal_strength', 0.5)
        signal_type_1h = details_1h.get('signal_type', '')
        
        if signal_type_1h in ['flip_bullish', 'flip_bearish']:
            score += self.config.weight_1h_direction
        elif signal_type_1h in ['red_bar_growing', 'green_bar_growing']:
            score += self.config.weight_1h_direction * 0.875
        else:
            score += self.config.weight_1h_direction * signal_strength_1h
        
        # 4H增强评分 (20%)
        if is_4h_enhanced:
            score += self.config.weight_4h_enhancement * enhancement_score
        elif enhancement_score > 0:
            score += self.config.weight_4h_enhancement * 0.5 * enhancement_score
        
        # 15M入场评分 (25%)
        entry_type_15m = details_15m.get('entry_type', '')
        
        if entry_type_15m in ['flip_bullish', 'flip_bearish']:
            score += self.config.weight_15m_entry
        elif entry_type_15m in ['red_bar_growing', 'green_bar_growing']:
            score += self.config.weight_15m_entry * 0.88
        elif entry_type_15m in ['red_bar_stable', 'green_bar_stable']:
            score += self.config.weight_15m_entry * 0.72
        else:
            score += self.config.weight_15m_entry * 0.4
        
        # 成交量评分 (15%)
        if volume_ratio > 1.5:
            score += self.config.weight_volume
        elif volume_ratio > 1.0:
            score += self.config.weight_volume * 0.67
        else:
            score += self.config.weight_volume * 0.33
        
        # 归一化
        final_score = min(score, 1.0)
        
        # 最低信号评分过滤
        if final_score < self.config.min_signal_score:
            return MACDSignal(
                direction='neutral',
                signal_score=final_score,
                details={'reason': f'信号评分过低: {final_score:.2f}'}
            )
        
        # 存储分析结果
        self._last_analysis = {
            'direction_1h': direction_1h,
            'signal_type_1h': signal_type_1h,
            'signal_strength_1h': signal_strength_1h,
            'is_4h_enhanced': is_4h_enhanced,
            'enhancement_score': enhancement_score,
            'entry_type_15m': entry_type_15m,
            'entry_score_15m': entry_score_15m,
            'volume_ratio': volume_ratio
        }
        
        return MACDSignal(
            direction=direction_1h,
            signal_score=final_score,
            signal_type_1h=signal_type_1h,
            signal_strength_1h=signal_strength_1h,
            is_4h_enhanced=is_4h_enhanced,
            enhancement_score=enhancement_score,
            entry_type_15m=entry_type_15m,
            entry_score_15m=entry_score_15m,
            details=self._last_analysis
        )
    
    def get_last_analysis(self) -> Dict:
        """获取最近一次分析结果"""
        return self._last_analysis.copy()
