"""
1H 企稳量化判定器
五维度打分模型：MACD动能(30) + 价格结构(30) + 成交量(20) + K线形态(12) + 时间结构(8)

入场条件：总分 ≥ 70 且无否决项
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class SignalLevel(Enum):
    """信号等级"""
    A_GRADE = "A"  # 85~100分，强企稳
    B_GRADE = "B"  # 70~84分，标准企稳
    C_GRADE = "C"  # 55~69分，弱企稳
    D_GRADE = "D"  # <55分，未企稳


@dataclass
class DimensionScore:
    """单维度得分"""
    dimension_name: str
    max_score: int
    actual_score: int
    conditions: Dict[str, bool]
    details: Dict[str, float] = field(default_factory=dict)


@dataclass
class StabilizationResult:
    """企稳判定结果"""
    total_score: int
    max_score: int
    level: SignalLevel
    passed: bool
    
    # 五维度得分
    macd_score: DimensionScore
    price_score: DimensionScore
    volume_score: DimensionScore
    candle_score: DimensionScore
    time_score: DimensionScore
    
    # 否决项
    veto_flags: Dict[str, bool]
    veto_reasons: List[str]
    
    # 入场建议
    position_pct: float
    reason: str
    
    # 冲突等级调整
    conflict_level: Optional[str] = None      # 冲突等级: None / 'weak' / 'medium' / 'strong'
    effective_threshold: int = 70             # 实际使用的门槛
    conflict_adjusted: bool = False           # 是否因冲突调整了门槛


class StabilizationScorer:
    """
    1H 企稳量化判定器
    
    核心公式：
    总分 = MACD动能分 + 价格结构分 + 成交量分 + K线形态分 + 时间结构分
    入场条件 = 总分 ≥ 70 AND 否决项全部为空
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            # 阈值配置
            "macd_decay_threshold": 0.5,      # MACD衰减率阈值
            "ema21_deviation_max": 0.005,     # EMA21偏差率阈值 0.5%
            "pullback_volume_ratio_max": 0.6, # 回调量比阈值
            
            # 动态门槛
            "strong_trend_threshold": 65,      # 强趋势市场门槛
            "normal_threshold": 70,            # 正常市场门槛
            "volatile_threshold": 80,          # 震荡市场门槛
            
            # ATR倍数
            "big_candle_atr_multiplier": 2.0,  # 大阴线ATR倍数
            "volume_spike_multiplier": 2.0,    # 量能突放倍数
        }
    
    # ==================== 核心入口 ====================
    
    # 默认企稳门槛
    DEFAULT_THRESHOLD = 70
    
    def get_effective_threshold(self, conflict_level: Optional[str] = None) -> int:
        """
        根据跨周期冲突强度返回有效的入场门槛
        
        冲突解除后的入场门槛根据冲突强度动态提高：
        - 无冲突/弱冲突解除: 企稳打分门槛 ≥ 70分（标准）
        - 中冲突解除: 企稳打分门槛 ≥ 75分（提高5分）
        - 强冲突解除: 企稳打分门槛 ≥ 80分（提高10分）
        
        Args:
            conflict_level: None / 'weak' / 'medium' / 'strong'
        
        Returns:
            有效的企稳打分门槛
        """
        threshold_map = {
            None:     70,    # 无冲突，标准门槛
            "weak":   70,    # 弱冲突，标准门槛
            "medium": 75,    # 中冲突，+5分
            "strong": 80,    # 强冲突，+10分
        }
        return threshold_map.get(conflict_level, 70)
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray,
                direction: str = "long",
                conflict_level: Optional[str] = None) -> StabilizationResult:
        """
        完整企稳分析
        
        Args:
            close, high, low, volume: OHLCV数据
            direction: "long" 或 "short"
            conflict_level: 冲突等级 (由 TimeframeConflictResolver 传入)
        
        Returns:
            StabilizationResult: 企稳判定结果
        """
        # 计算五维度得分
        macd_score = self._score_macd_dimension(close)
        price_score = self._score_price_dimension(close, high, low, volume)  # 传入volume用于VWAP计算
        volume_score = self._score_volume_dimension(close, volume, high, low)
        candle_score = self._score_candle_dimension(close, high, low)
        time_score = self._score_time_dimension(close, high, low)
        
        # 检查否决项
        veto_flags, veto_reasons = self._check_veto_conditions(
            close, high, low, volume, direction
        )
        
        # 计算总分
        total_score = (
            macd_score.actual_score +
            price_score.actual_score +
            volume_score.actual_score +
            candle_score.actual_score +
            time_score.actual_score
        )
        
        # 确定信号等级
        level = self._determine_signal_level(total_score, veto_flags)
        
        # 获取有效门槛（根据冲突等级调整）
        effective_threshold = self.get_effective_threshold(conflict_level)
        
        # 判定是否通过（使用调整后的门槛）
        passed = (total_score >= effective_threshold) and (not any(veto_flags.values()))
        
        # 计算入场仓位
        position_pct = self._calculate_position_pct(level, total_score)
        
        # 生成原因
        reason = self._generate_reason(
            total_score, level, veto_reasons,
            macd_score, price_score, volume_score,
            effective_threshold, conflict_level
        )
        
        return StabilizationResult(
            total_score=total_score,
            max_score=100,
            level=level,
            passed=passed,
            macd_score=macd_score,
            price_score=price_score,
            volume_score=volume_score,
            candle_score=candle_score,
            time_score=time_score,
            veto_flags=veto_flags,
            veto_reasons=veto_reasons,
            position_pct=position_pct,
            reason=reason,
            conflict_level=conflict_level,
            effective_threshold=effective_threshold,
            conflict_adjusted=(conflict_level is not None)
        )
    
    # ==================== 维度一：MACD动能 (30分) ====================
    
    def _score_macd_dimension(self, close: np.ndarray) -> DimensionScore:
        """
        MACD动能评分（优化版 - 重点关注柱子背离和翻红信号）
        
        评分细则（新版）：
        - 柱子翻红信号（比金叉早2-3根）: +10
        - 柱子底背离（价格新低但柱子抬高）: +10
        - 连续缩短(≥2根): +5
        - 衰减幅度(ratio < 0.5): +5
        - 红柱增强: +5
        - 未死叉（柱子>0）: +5
        """
        score = 0
        conditions = {}
        details = {}
        
        # 计算MACD
        ema_fast = self._calculate_ema(close, 12)
        ema_slow = self._calculate_ema(close, 26)
        macd_line = ema_fast - ema_slow
        signal_line = self._calculate_ema(macd_line, 9)
        histogram = macd_line - signal_line
        
        # 取最近几根柱子
        h = histogram[-10:]  # 最近10根用于分析
        
        if len(h) < 5:
            return DimensionScore(
                dimension_name="MACD动能",
                max_score=30,
                actual_score=0,
                conditions={"数据不足": True},
                details={}
            )
        
        # ==================== 新增：柱子翻红信号检测 ====================
        bullish_cross = False
        bars_since_cross = -1
        
        # 检测翻红：柱子从负转正
        for i in range(len(h) - 2, -1, -1):
            if h[i] < 0 and h[i + 1] >= 0:
                bullish_cross = True
                bars_since_cross = len(h) - 1 - i
                break
        
        # 翻红信号评分（比金叉提前2-3根K线）
        if bullish_cross:
            if bars_since_cross <= 2:
                score += 10  # 刚翻红，最强信号
                conditions["柱子翻红(强)"] = True
                details["翻红K线数"] = bars_since_cross
            elif bars_since_cross <= 4:
                score += 7   # 翻红后1-2根
                conditions["柱子翻红(中)"] = True
                details["翻红K线数"] = bars_since_cross
            else:
                score += 3   # 翻红较久
                conditions["柱子翻红(弱)"] = True
                details["翻红K线数"] = bars_since_cross
        
        # ==================== 新增：底背离检测 ====================
        bottom_divergence = False
        divergence_strength = 0.0
        
        if len(close) >= 20 and len(histogram) >= 20:
            # 找价格低点
            recent_low = np.min(close[-15:-3])
            current_price = close[-1]
            recent_low_idx = np.argmin(close[-15:-3])
            
            # 当前价格接近新低（在低点2%以内）
            if current_price <= recent_low * 1.02:
                # 检查柱子是否抬高
                hist_at_low = histogram[-15 + recent_low_idx]
                current_hist = histogram[-1]
                
                # 底背离：价格新低但柱子值更高
                if hist_at_low < 0 and current_hist > hist_at_low:
                    divergence_pct = (current_hist - hist_at_low) / abs(hist_at_low) if hist_at_low != 0 else 0
                    if divergence_pct > 0.3:  # 柱子抬高30%以上
                        bottom_divergence = True
                        divergence_strength = min(1.0, divergence_pct)
                        score += 10
                        conditions["底背离"] = True
                        details["背离强度"] = f"{divergence_pct*100:.1f}%"
        
        # ==================== 原有评分项（权重降低）====================
        
        # 1. 连续缩短判定 (≥2根柱子绝对值递减)
        if len(h) >= 3:
            consecutive_decline = (
                abs(h[-1]) < abs(h[-2]) and 
                abs(h[-2]) < abs(h[-3])
            )
            if consecutive_decline:
                score += 5  # 降低权重
                conditions["连续缩短"] = True
            else:
                conditions["连续缩短"] = False
        else:
            conditions["连续缩短"] = False
        
        # 2. 衰减幅度判定
        if len(h) >= 2 and abs(h[-2]) > 0:
            ratio = abs(h[-1]) / abs(h[-2])
            details["衰减率"] = ratio
            
            if ratio < 0.50:
                score += 5  # 降低权重
                conditions["衰减幅度"] = True
            elif ratio < 0.70:
                score += 2
                conditions["衰减幅度"] = "partial"
            else:
                conditions["衰减幅度"] = False
        else:
            conditions["衰减幅度"] = False
            details["衰减率"] = 1.0
        
        # 3. 红柱增强判定
        if h[-1] > 0 and len(h) >= 3:
            if h[-1] > h[-2] > h[-3]:
                score += 5
                conditions["红柱增强"] = True
            else:
                conditions["红柱增强"] = False
        else:
            conditions["红柱增强"] = False
        
        # 4. 未死叉判定 (柱子仍为正值)
        if histogram[-1] > 0:
            score += 5
            conditions["未死叉"] = True
        else:
            conditions["未死叉"] = False
        
        details["最新柱值"] = float(histogram[-1])
        details["前柱值"] = float(histogram[-2]) if len(histogram) >= 2 else 0
        
        # 综合信号说明
        if bullish_cross and bottom_divergence:
            details["综合信号"] = "强做多信号: 翻红+底背离"
        elif bullish_cross:
            details["综合信号"] = "做多信号: 柱子翻红"
        elif bottom_divergence:
            details["综合信号"] = "做多信号: 底背离"
        
        return DimensionScore(
            dimension_name="MACD动能",
            max_score=30,
            actual_score=min(30, score),  # 上限30分
            conditions=conditions,
            details=details
        )
    
    # ==================== 维度二：价格结构 (30分) ====================
    
    def _score_price_dimension(self, 
                               close: np.ndarray,
                               high: np.ndarray,
                               low: np.ndarray,
                               volume: Optional[np.ndarray] = None) -> DimensionScore:
        """
        价格结构评分（优化版 - 增强做多趋势确认）
        
        评分细则：
        - EMA21偏差率 ≤ 0.5%: +8
        - EMA55不破: +6
        - VWAP上方: +4
        - EMA21斜率向上: +3
        - **新增做多趋势确认**:
          - EMA多头排列(21>55且价格>21): +4
          - 价格突破EMA21: +3
          - 连续3根K线高于EMA21: +2
        
        Args:
            close: 收盘价数组
            high: 最高价数组
            low: 最低价数组
            volume: 成交量数组（用于VWAP计算）
        """
        score = 0
        conditions = {}
        details = {}
        
        # 计算EMA
        ema21 = self._calculate_ema(close, 21)
        ema55 = self._calculate_ema(close, 55)
        current_price = close[-1]
        
        # 1. EMA21偏差率判定
        deviation = abs(current_price - ema21[-1]) / ema21[-1]
        details["EMA21偏差率"] = deviation
        
        if deviation <= 0.005:  # ≤ 0.5%
            score += 8
            conditions["EMA21偏差≤0.5%"] = True
        elif deviation <= 0.01:  # 0.5%~1.0%
            score += 4
            conditions["EMA21偏差≤0.5%"] = "partial"
        else:
            conditions["EMA21偏差≤0.5%"] = False
        
        # 2. EMA55不破判定
        if current_price > ema55[-1]:
            score += 6
            conditions["EMA55不破"] = True
        else:
            conditions["EMA55不破"] = False
        
        # 3. VWAP上方判定（使用修正后的计算，传入成交量）
        vwap = self._calculate_vwap(high, low, close, volume)
        if current_price > vwap[-1]:
            score += 4
            conditions["VWAP上方"] = True
        else:
            conditions["VWAP上方"] = False
        
        details["VWAP"] = vwap[-1]
        
        # 4. EMA21斜率向上判定
        if len(ema21) >= 4:
            ema21_slope_up = ema21[-1] >= ema21[-3]
            if ema21_slope_up:
                score += 3
                conditions["EMA21斜率向上"] = True
            else:
                conditions["EMA21斜率向上"] = False
        else:
            conditions["EMA21斜率向上"] = False
        
        # ==================== 新增：做多趋势确认 ====================
        
        # 5. EMA多头排列判定 (EMA21 > EMA55 且 价格 > EMA21)
        ema_bullish_alignment = ema21[-1] > ema55[-1] and current_price > ema21[-1]
        if ema_bullish_alignment:
            score += 4
            conditions["EMA多头排列"] = True
        else:
            conditions["EMA多头排列"] = False
        
        # 6. 价格突破EMA21判定
        if len(close) >= 3:
            # 当前价格 > EMA21，且前一根K线在EMA21下方或刚好在EMA21上
            price_breakout_ema21 = (current_price > ema21[-1] and 
                                    close[-2] <= ema21[-2] * 1.002)  # 允许0.2%误差
            if price_breakout_ema21:
                score += 3
                conditions["价格突破EMA21"] = True
            else:
                conditions["价格突破EMA21"] = False
        else:
            conditions["价格突破EMA21"] = False
        
        # 7. 连续站稳EMA21判定（连续3根K线高于EMA21）
        if len(close) >= 4:
            bars_above_ema21 = sum(1 for i in range(-3, 0) if close[i] > ema21[i])
            if bars_above_ema21 >= 3:
                score += 2
                conditions["连续站稳EMA21"] = True
            else:
                conditions["连续站稳EMA21"] = False
        else:
            conditions["连续站稳EMA21"] = False
        
        details["EMA21"] = ema21[-1]
        details["EMA55"] = ema55[-1]
        details["EMA排列"] = "多头" if ema_bullish_alignment else "空头/中性"
        
        return DimensionScore(
            dimension_name="价格结构",
            max_score=30,
            actual_score=min(30, score),  # 上限30分
            conditions=conditions,
            details=details
        )
    
    # ==================== 维度三：成交量 (20分) ====================
    
    def _score_volume_dimension(self,
                                 close: np.ndarray,
                                 volume: np.ndarray,
                                 high: np.ndarray,
                                 low: np.ndarray) -> DimensionScore:
        """
        成交量评分
        
        评分细则：
        - 回调量比 < 0.6: +10
        - 连续3根量能萎缩: +6
        - 当前量 < 量MA20: +4
        """
        score = 0
        conditions = {}
        details = {}
        
        # 计算量MA
        volume_ma = self._calculate_sma(volume, 20)
        
        # 1. 回调量比判定 (需要识别回调段)
        pullback_volume_ratio = self._calculate_pullback_volume_ratio(close, volume)
        details["回调量比"] = pullback_volume_ratio
        
        if pullback_volume_ratio < 0.60:
            score += 10
            conditions["回调量比<0.6"] = True
        elif pullback_volume_ratio < 0.80:
            score += 5
            conditions["回调量比<0.6"] = "partial"
        else:
            conditions["回调量比<0.6"] = False
        
        # 2. 连续萎缩判定
        if len(volume) >= 4:
            vol_declining = (
                volume[-1] < volume[-2] and
                volume[-2] < volume[-3] and
                volume[-3] < volume[-4]
            )
            if vol_declining:
                score += 6
                conditions["连续3根萎缩"] = True
            elif volume[-1] < volume[-2] and volume[-2] < volume[-3]:
                score += 3
                conditions["连续3根萎缩"] = "partial"
            else:
                conditions["连续3根萎缩"] = False
        else:
            conditions["连续3根萎缩"] = False
        
        # 3. 当前量 < 量MA20判定
        if volume[-1] < volume_ma[-1]:
            score += 4
            conditions["量能<MA20"] = True
        else:
            conditions["量能<MA20"] = False
        
        details["当前量"] = volume[-1]
        details["量MA20"] = volume_ma[-1]
        details["量比"] = volume[-1] / volume_ma[-1] if volume_ma[-1] > 0 else 1.0
        
        return DimensionScore(
            dimension_name="成交量",
            max_score=20,
            actual_score=score,
            conditions=conditions,
            details=details
        )
    
    # ==================== 维度四：K线形态 (12分) ====================
    
    def _score_candle_dimension(self,
                                close: np.ndarray,
                                high: np.ndarray,
                                low: np.ndarray) -> DimensionScore:
        """
        K线形态评分
        
        评分细则：
        - 下影线承接: +5
        - 十字星/小实体: +4
        - 横盘收敛: +3
        """
        score = 0
        conditions = {}
        details = {}
        
        # 计算ATR
        atr = self._calculate_atr(high, low, close, 14)
        
        # 分析最近K线
        candle_body = abs(close[-1] - close[-2])
        candle_range = high[-1] - low[-1]
        lower_wick = min(close[-1], close[-2]) - low[-1]
        upper_wick = high[-1] - max(close[-1], close[-2])
        
        # 1. 下影线承接判定
        if candle_body > 0 and lower_wick >= candle_body * 1.5 and lower_wick > upper_wick:
            score += 5
            conditions["下影线承接"] = True
        else:
            conditions["下影线承接"] = False
        
        # 2. 十字星/小实体判定
        details["ATR"] = atr[-1]
        if atr[-1] > 0 and candle_body < atr[-1] * 0.3:
            score += 4
            conditions["十字星/小实体"] = True
        else:
            conditions["十字星/小实体"] = False
        
        # 3. 横盘收敛判定
        if len(close) >= 3:
            body_1 = abs(close[-1] - close[-2])
            body_2 = abs(close[-2] - close[-3])
            if body_1 < body_2 and body_1 > 0:  # 实体逐步缩小
                score += 3
                conditions["横盘收敛"] = True
            else:
                conditions["横盘收敛"] = False
        else:
            conditions["横盘收敛"] = False
        
        details["实体大小"] = candle_body
        details["下影线"] = lower_wick
        details["上影线"] = upper_wick
        
        return DimensionScore(
            dimension_name="K线形态",
            max_score=12,
            actual_score=score,
            conditions=conditions,
            details=details
        )
    
    # ==================== 维度五：时间结构 (8分) ====================
    
    def _score_time_dimension(self,
                              close: np.ndarray,
                              high: np.ndarray,
                              low: np.ndarray) -> DimensionScore:
        """
        时间结构评分
        
        评分细则：
        - 回调根数3~5根: +4
        - 低点抬高: +2
        - 回调幅度<50%: +2
        """
        score = 0
        conditions = {}
        details = {}
        
        # 1. 回调根数判定 (简化：检测连续下跌K线数)
        pullback_bars = self._detect_pullback_bars(close)
        details["回调根数"] = pullback_bars
        
        if 3 <= pullback_bars <= 5:
            score += 4
            conditions["回调3~5根"] = True
        elif pullback_bars in [2, 6, 7, 8]:
            score += 2
            conditions["回调3~5根"] = "partial"
        else:
            conditions["回调3~5根"] = False
        
        # 2. 低点抬高判定
        if len(low) >= 20:
            recent_low = np.min(low[-10:])
            prev_low = np.min(low[-20:-10])
            if recent_low > prev_low:
                score += 2
                conditions["低点抬高"] = True
            else:
                conditions["低点抬高"] = False
        else:
            conditions["低点抬高"] = False
        
        # 3. 回调幅度判定
        if len(high) >= 20 and len(low) >= 20:
            recent_high = np.max(high[-20:])
            recent_low = np.min(low[-20:])
            prev_low = np.min(low[-40:-20]) if len(low) >= 40 else np.min(low[-20:])
            
            pullback_depth = (recent_high - recent_low) / (recent_high - prev_low) if (recent_high - prev_low) > 0 else 0
            details["回调深度"] = pullback_depth
            
            if pullback_depth < 0.5:
                score += 2
                conditions["回调<50%"] = True
            elif pullback_depth < 0.618:
                score += 1
                conditions["回调<50%"] = "partial"
            else:
                conditions["回调<50%"] = False
        else:
            conditions["回调<50%"] = False
        
        return DimensionScore(
            dimension_name="时间结构",
            max_score=8,
            actual_score=score,
            conditions=conditions,
            details=details
        )
    
    # ==================== 否决项检查 ====================
    
    def _check_veto_conditions(self,
                               close: np.ndarray,
                               high: np.ndarray,
                               low: np.ndarray,
                               volume: np.ndarray,
                               direction: str) -> Tuple[Dict[str, bool], List[str]]:
        """
        检查否决项（优化版 - 增加MACD柱子顶背离和翻绿检测）
        
        否决项：
        1. EMA55跌破
        2. MACD柱子翻绿（比死叉更早）
        3. MACD顶背离（价格新高但柱子降低）
        4. 大阴线出现
        5. 量能突放
        """
        veto_flags = {
            "EMA55跌破": False,
            "MACD翻绿": False,
            "MACD顶背离": False,
            "大阴线出现": False,
            "量能突放": False
        }
        veto_reasons = []
        
        # 1. EMA55跌破
        ema55 = self._calculate_ema(close, 55)
        if close[-1] < ema55[-1]:
            veto_flags["EMA55跌破"] = True
            veto_reasons.append(f"EMA55跌破: 收盘价{close[-1]:.2f} < EMA55{ema55[-1]:.2f}")
        
        # 2. MACD柱子翻绿检测（比死叉更早的做空信号）
        ema_fast = self._calculate_ema(close, 12)
        ema_slow = self._calculate_ema(close, 26)
        macd_line = ema_fast - ema_slow
        signal_line = self._calculate_ema(macd_line, 9)
        histogram = macd_line - signal_line
        
        # 检测刚翻绿（最近1-3根K线内）
        if len(histogram) >= 3:
            # 柱子从正转负
            if histogram[-1] < 0:
                # 检查是否最近刚转负
                for i in range(len(histogram) - 2, max(0, len(histogram) - 5), -1):
                    if histogram[i] > 0 and histogram[i + 1] <= 0:
                        bars_since = len(histogram) - 1 - i
                        veto_flags["MACD翻绿"] = True
                        veto_reasons.append(f"MACD翻绿: {bars_since}根K线前柱子正→负")
                        break
                else:
                    # 已经翻绿超过5根，检查是否绿柱增强
                    if histogram[-1] < histogram[-2] < 0:
                        veto_flags["MACD翻绿"] = True
                        veto_reasons.append(f"MACD绿柱增强: 柱子值{histogram[-1]:.4f}")
        
        # 3. MACD顶背离检测（价格新高但柱子降低）
        if len(close) >= 20 and len(histogram) >= 20:
            # 找价格高点
            recent_high = np.max(close[-15:-3])
            current_price = close[-1]
            
            # 当前价格接近新高（在高点2%以内或已超过）
            if current_price >= recent_high * 0.98:
                recent_high_idx = np.argmax(close[-15:-3])
                hist_at_high = histogram[-15 + recent_high_idx]
                current_hist = histogram[-1]
                
                # 顶背离：价格新高但柱子值更低
                if hist_at_high > 0 and current_hist < hist_at_high:
                    divergence_pct = (hist_at_high - current_hist) / abs(hist_at_high) if hist_at_high != 0 else 0
                    if divergence_pct > 0.3:  # 柱子降低30%以上
                        veto_flags["MACD顶背离"] = True
                        veto_reasons.append(f"MACD顶背离: 价格新高但柱子降低{divergence_pct*100:.1f}%")
        
        # 4. 大阴线判定
        atr = self._calculate_atr(high, low, close, 14)
        candle_body = close[-2] - close[-1]  # 阴线实体
        
        if atr[-1] > 0 and candle_body > atr[-1] * self.config["big_candle_atr_multiplier"]:
            veto_flags["大阴线出现"] = True
            veto_reasons.append(f"大阴线: 实体{candle_body:.2f} > ATR×2 {atr[-1]*2:.2f}")
        
        # 5. 量能突放
        volume_ma = self._calculate_sma(volume, 20)
        if volume[-1] > volume_ma[-1] * self.config["volume_spike_multiplier"]:
            veto_flags["量能突放"] = True
            veto_reasons.append(f"量能突放: 当前量{volume[-1]:.0f} > MA20×2 {volume_ma[-1]*2:.0f}")
        
        return veto_flags, veto_reasons
    
    # ==================== 辅助方法 ====================
    
    def _determine_signal_level(self, total_score: int, veto_flags: Dict[str, bool]) -> SignalLevel:
        """确定信号等级"""
        # 有否决项直接D级
        if any(veto_flags.values()):
            return SignalLevel.D_GRADE
        
        if total_score >= 85:
            return SignalLevel.A_GRADE
        elif total_score >= 70:
            return SignalLevel.B_GRADE
        elif total_score >= 55:
            return SignalLevel.C_GRADE
        else:
            return SignalLevel.D_GRADE
    
    def _calculate_position_pct(self, level: SignalLevel, total_score: int) -> float:
        """计算入场仓位比例"""
        if level == SignalLevel.A_GRADE:
            return 0.40  # 40%首仓
        elif level == SignalLevel.B_GRADE:
            return 0.40  # 40%首仓
        elif level == SignalLevel.C_GRADE:
            return 0.20  # 减半首仓
        else:
            return 0.0   # 禁止入场
    
    def _generate_reason(self,
                        total_score: int,
                        level: SignalLevel,
                        veto_reasons: List[str],
                        macd_score: DimensionScore,
                        price_score: DimensionScore,
                        volume_score: DimensionScore,
                        effective_threshold: int = 70,
                        conflict_level: Optional[str] = None) -> str:
        """生成判定原因"""
        reason = f"总分{total_score}/100 | {level.value}级 | "
        
        # 如果有冲突等级调整，显示门槛变化
        if conflict_level and conflict_level in ["medium", "strong"]:
            reason += f"门槛{effective_threshold}分(冲突调整) | "
        
        if veto_reasons:
            reason += f"否决: {'; '.join(veto_reasons)}"
        else:
            reason += f"MACD{macd_score.actual_score}分 | 价格{price_score.actual_score}分 | 量能{volume_score.actual_score}分"
        
        return reason
    
    # ==================== 技术指标计算 ====================
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        multiplier = 2 / (period + 1)
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = (data[i] * multiplier) + (ema[i-1] * (1 - multiplier))
        return ema
    
    def _calculate_sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算SMA"""
        return np.convolve(data, np.ones(period)/period, mode='same')
    
    def _calculate_vwap(self, high: np.ndarray, low: np.ndarray, 
                        close: np.ndarray, volume: Optional[np.ndarray] = None) -> np.ndarray:
        """
        计算VWAP（成交量加权平均价格）
        
        修复说明：
        原实现只用典型价格，缺少成交量权重，导致VWAP计算错误。
        VWAP = Σ(典型价格 × 成交量) / Σ成交量
        
        策略影响：
        VWAP被用于企稳打分的"价格结构"维度（+6分），错误的VWAP计算会导致该维度评分失真。
        
        Args:
            high: 最高价数组
            low: 最低价数组
            close: 收盘价数组
            volume: 成交量数组（可选，如不提供则退化为典型价格）
        
        Returns:
            VWAP数组
        """
        typical_price = (high + low + close) / 3
        
        # 如果有成交量数据，使用正确的VWAP计算
        if volume is not None and len(volume) == len(close):
            # 累积计算
            cum_tp_vol = np.cumsum(typical_price * volume)
            cum_vol = np.cumsum(volume)
            
            # 避免除零
            vwap = np.where(cum_vol > 0, cum_tp_vol / cum_vol, typical_price)
            return vwap
        
        # 回退：如果没有成交量，返回典型价格（简化版）
        return typical_price
    
    def _calculate_atr(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray, period: int = 14) -> np.ndarray:
        """计算ATR"""
        tr = np.zeros(len(close))
        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        return self._calculate_ema(tr, period)
    
    def _calculate_pullback_volume_ratio(self, close: np.ndarray, volume: np.ndarray) -> float:
        """计算回调量比"""
        # 简化实现：识别最近的回调段和上涨段
        if len(close) < 20:
            return 1.0
        
        # 检测最近的价格变化方向
        recent_close = close[-20:]
        recent_volume = volume[-20:]
        
        # 简单判断：最近5根K线是否在回调
        if recent_close[-1] < recent_close[-5]:
            pullback_vol = np.sum(recent_volume[-5:])
            rally_vol = np.sum(recent_volume[-15:-5])
            if rally_vol > 0:
                return pullback_vol / rally_vol
        
        return 0.5  # 默认值
    
    def _detect_pullback_bars(self, close: np.ndarray) -> int:
        """检测回调K线根数"""
        if len(close) < 10:
            return 0
        
        count = 0
        for i in range(len(close) - 1, max(0, len(close) - 10), -1):
            if close[i] < close[i-1]:
                count += 1
            else:
                break
        
        return count


# ==================== 使用示例 ====================

def example_usage():
    """使用示例"""
    import numpy as np
    
    # 模拟数据
    np.random.seed(42)
    n = 100
    
    close = 95000 + np.cumsum(np.random.randn(n) * 100)
    high = close + np.random.rand(n) * 200
    low = close - np.random.rand(n) * 200
    volume = np.random.randint(1000, 5000, n)
    
    # 创建评分器
    scorer = StabilizationScorer()
    
    # 分析
    result = scorer.analyze(close, high, low, volume, direction="long")
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"1H 企稳量化判定结果")
    print(f"{'='*60}")
    print(f"总分: {result.total_score}/100")
    print(f"等级: {result.level.value}级")
    print(f"通过: {result.passed}")
    print(f"建议仓位: {result.position_pct*100:.0f}%")
    print(f"\n维度得分:")
    print(f"  MACD动能: {result.macd_score.actual_score}/{result.macd_score.max_score}")
    print(f"  价格结构: {result.price_score.actual_score}/{result.price_score.max_score}")
    print(f"  成交量:   {result.volume_score.actual_score}/{result.volume_score.max_score}")
    print(f"  K线形态:  {result.candle_score.actual_score}/{result.candle_score.max_score}")
    print(f"  时间结构: {result.time_score.actual_score}/{result.time_score.max_score}")
    
    if result.veto_reasons:
        print(f"\n否决项:")
        for reason in result.veto_reasons:
            print(f"  ❌ {reason}")
    
    print(f"\n判定原因: {result.reason}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    example_usage()
