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
    """信号等级 - 基于共振层数"""
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
    """VWAP状态 - 机构成本线"""
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
    
    # 五层共振评分权重
    layer_4h_weight: int = 20   # 宏观层权重
    layer_1h_weight: int = 25   # 趋势层权重
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
class FiveLayerSignal:
    """五层共振交易信号"""
    signal_type: SignalType
    grade: SignalGrade
    score: int
    direction: TrendDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    position_size_pct: float
    reason: str
    layer_scores: Dict[str, int] = field(default_factory=dict)
    layer_passed: Dict[str, bool] = field(default_factory=dict)
    vwap_values: Dict[str, float] = field(default_factory=dict)
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
        """
        计算 VWAP (成交量加权平均价格)
        
        VWAP = Σ(Price × Volume) / ΣVolume
        
        机构成本线，用于判断多空控制权：
        - 价格 > VWAP: 多头控制
        - 价格 < VWAP: 空头控制
        """
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
    """
    第一层：宏观层 (4H) - 趋势定调
    
    做多条件：
    1. 价格 > EMA200 (市场长期偏多)
    2. MACD柱 > 0 (动能向上)
    """
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze(self, close: np.ndarray) -> Dict[str, any]:
        """4H 宏观趋势分析"""
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
        
        # 计算得分 (满分20分)
        score = 0
        if price_above_ema200:
            score += 10
        if macd_positive:
            score += 10
        
        passed = price_above_ema200 and macd_positive
        
        return {
            "layer": "4H",
            "passed": passed,
            "score": score,
            "max_score": self.config.layer_4h_weight,
            "price_above_ema200": price_above_ema200,
            "macd_positive": macd_positive,
            "ema200_value": current_ema200,
            "reason": f"4H宏观: 价格{'>' if price_above_ema200 else '<'}EMA200, MACD柱{'>' if macd_positive else '<'}0"
        }


class CoreLayer1H:
    """
    第二层：趋势确认层 (1H) - 信号生成核心
    
    做多条件：
    1. 价格 > EMA55 (趋势稳定)
    2. MACD向上 (动能向上)
    3. 价格 > VWAP (多头控制)
    """
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray) -> Dict[str, any]:
        """1H 趋势确认分析"""
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
        
        # MACD 向上判断 (柱子增长)
        macd_rising = histogram[-1] > histogram[-2]
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        
        # VWAP 状态
        vwap_state = VWAPAnalyzer.get_vwap_state(current_price, current_vwap)
        
        # 检查条件
        price_above_ema55 = current_price > current_ema55
        
        # 计算得分 (满分25分)
        score = 0
        if price_above_ema55:
            score += 10
        if macd_rising:
            score += 8
        if vwap_state == VWAPState.ABOVE:
            score += 7
        
        passed = price_above_ema55 and macd_rising and vwap_state == VWAPState.ABOVE
        
        return {
            "layer": "1H",
            "passed": passed,
            "score": score,
            "max_score": self.config.layer_1h_weight,
            "price_above_ema55": price_above_ema55,
            "macd_rising": macd_rising,
            "vwap_state": vwap_state.value,
            "vwap_value": current_vwap,
            "ema55_value": current_ema55,
            "reason": f"1H趋势: 价格{'>' if price_above_ema55 else '<'}EMA55, MACD{'向上' if macd_rising else '向下'}, VWAP={vwap_state.value}"
        }


class PullbackLayer15m:
    """
    第三层：回调买点层 (15m) - 寻找趋势中的回调买点
    
    做多条件：
    1. MACD金叉 (动能转强)
    2. 价格回踩EMA21 (趋势中的回调买点)
    """
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze(self, close: np.ndarray) -> Dict[str, any]:
        """15m 回调买点分析"""
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
        
        # 计算得分 (满分20分)
        score = 0
        if macd_golden_cross:
            score += 12
        if price_near_ema21:
            score += 8
        
        passed = macd_golden_cross and price_near_ema21
        
        return {
            "layer": "15m",
            "passed": passed,
            "score": score,
            "max_score": self.config.layer_15m_weight,
            "macd_golden_cross": macd_golden_cross,
            "price_near_ema21": price_near_ema21,
            "ema21_value": current_ema21,
            "reason": f"15m回调: MACD{'金叉' if macd_golden_cross else '无金叉'}, 价格{'接近' if price_near_ema21 else '远离'}EMA21"
        }


class LaunchLayer5m:
    """
    第四层：启动确认层 (5m) - 资金推动确认
    
    做多条件：
    1. MACD金叉 (动能启动)
    2. 价格突破VWAP (资金开始推动行情)
    """
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray) -> Dict[str, any]:
        """5m 启动确认分析"""
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_5m_fast,
            self.config.macd_5m_slow,
            self.config.macd_5m_signal
        )
        
        # MACD 金叉判断
        macd_golden_cross = histogram[-2] <= 0 and histogram[-1] > 0
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格突破 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分 (满分20分)
        score = 0
        if macd_golden_cross:
            score += 10
        if price_above_vwap:
            score += 10
        
        passed = macd_golden_cross and price_above_vwap
        
        return {
            "layer": "5m",
            "passed": passed,
            "score": score,
            "max_score": self.config.layer_5m_weight,
            "macd_golden_cross": macd_golden_cross,
            "price_above_vwap": price_above_vwap,
            "vwap_value": current_vwap,
            "reason": f"5m启动: MACD{'金叉' if macd_golden_cross else '无金叉'}, 价格{'>' if price_above_vwap else '<'}VWAP"
        }


class EntryLayer1m:
    """
    第五层：精准入场层 (1m) - 启动瞬间捕捉
    
    做多条件：
    1. MACD金叉 (启动信号)
    2. 价格站上VWAP (确认启动)
    
    这通常是启动瞬间！
    """
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray) -> Dict[str, any]:
        """1m 精准入场分析"""
        # 计算 MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close,
            self.config.macd_1m_fast,
            self.config.macd_1m_slow,
            self.config.macd_1m_signal
        )
        
        # MACD 金叉判断
        macd_golden_cross = histogram[-2] <= 0 and histogram[-1] > 0
        
        # 计算 VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        current_vwap = vwap[-1]
        current_price = close[-1]
        
        # 价格站上 VWAP 判断
        price_above_vwap = current_price > current_vwap
        
        # 计算得分 (满分15分)
        score = 0
        if macd_golden_cross:
            score += 8
        if price_above_vwap:
            score += 7
        
        passed = macd_golden_cross and price_above_vwap
        
        return {
            "layer": "1m",
            "passed": passed,
            "score": score,
            "max_score": self.config.layer_1m_weight,
            "macd_golden_cross": macd_golden_cross,
            "price_above_vwap": price_above_vwap,
            "entry_price": current_price,
            "vwap_value": current_vwap,
            "reason": f"1m入场: MACD{'金叉' if macd_golden_cross else '无金叉'}, 价格{'站上' if price_above_vwap else '未站上'}VWAP"
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


class FiveLayerResonanceEngine:
    """五层共振引擎 - 融合所有层级得分"""
    
    def __init__(self, config: MTFConfig):
        self.config = config
    
    def fuse(self, layer_results: Dict[str, Dict]) -> Tuple[int, SignalGrade, int]:
        """
        融合五层得分
        
        返回：(总分, 信号等级, 共振层数)
        """
        # 统计通过的层数
        passed_layers = sum(1 for r in layer_results.values() if r.get("passed", False))
        
        # 计算总分
        total_score = sum(r.get("score", 0) for r in layer_results.values())
        
        # 确定等级
        if passed_layers >= 5 and total_score >= self.config.score_s_grade_min:
            grade = SignalGrade.S_GRADE  # 五层全共振
        elif passed_layers >= 4 and total_score >= self.config.score_a_grade_min:
            grade = SignalGrade.A_GRADE  # 四层共振
        else:
            grade = SignalGrade.B_GRADE  # 三层及以下
        
        return total_score, grade, passed_layers
    
    def calculate_position_size(self,
                               grade: SignalGrade,
                               risk_distance: float,
                               total_capital: float) -> float:
        """根据信号等级计算仓位"""
        max_risk = total_capital * self.config.max_risk_per_trade
        position_size = max_risk / risk_distance
        
        if grade == SignalGrade.S_GRADE:
            position_pct = 1.0  # 全仓
        elif grade == SignalGrade.A_GRADE:
            position_pct = 0.5  # 半仓
        else:
            position_pct = 0.0
        
        return position_size * position_pct


class MTFTradingSystemV2:
    """
    多时间框架交易系统 V2.0
    
    五层共振系统：
    第一层 4H：宏观定调 (价格>EMA200 + MACD柱>0)
    第二层 1H：趋势确认 (价格>EMA55 + MACD向上 + 价格>VWAP)
    第三层 15m：回调买点 (MACD金叉 + 价格回踩EMA21)
    第四层 5m：启动确认 (MACD金叉 + 价格突破VWAP)
    第五层 1m：精准入场 (MACD金叉 + 价格站上VWAP)
    """
    
    def __init__(self, config: Optional[MTFConfig] = None):
        self.config = config or MTFConfig()
        
        # 初始化五层分析器
        self.layer_4h = MacroLayer4H(self.config)
        self.layer_1h = CoreLayer1H(self.config)
        self.layer_15m = PullbackLayer15m(self.config)
        self.layer_5m = LaunchLayer5m(self.config)
        self.layer_1m = EntryLayer1m(self.config)
        self.engine = FiveLayerResonanceEngine(self.config)
    
    def analyze(self,
               # 4H 数据
               close_4h: np.ndarray,
               # 1H 数据
               high_1h: np.ndarray,
               low_1h: np.ndarray,
               close_1h: np.ndarray,
               volume_1h: np.ndarray,
               # 15m 数据
               close_15m: np.ndarray,
               # 5m 数据
               high_5m: np.ndarray,
               low_5m: np.ndarray,
               close_5m: np.ndarray,
               volume_5m: np.ndarray,
               # 1m 数据
               high_1m: np.ndarray,
               low_1m: np.ndarray,
               close_1m: np.ndarray,
               volume_1m: np.ndarray) -> Optional[FiveLayerSignal]:
        """
        五层共振分析
        
        流程：
        1. 4H 宏观定调 (必须通过)
        2. 1H 趋势确认 (必须通过)
        3. 15m 回调买点
        4. 5m 启动确认
        5. 1m 精准入场
        """
        
        # 第一层：4H 宏观定调
        result_4h = self.layer_4h.analyze(close_4h)
        
        if not result_4h["passed"]:
            return None  # 4H 宏观不通过，一票否决
        
        # 第二层：1H 趋势确认
        result_1h = self.layer_1h.analyze(close_1h, high_1h, low_1h, volume_1h)
        
        if not result_1h["passed"]:
            return None  # 1H 趋势不通过
        
        # 第三层：15m 回调买点
        result_15m = self.layer_15m.analyze(close_15m)
        
        # 第四层：5m 启动确认
        result_5m = self.layer_5m.analyze(close_5m, high_5m, low_5m, volume_5m)
        
        # 第五层：1m 精准入场
        result_1m = self.layer_1m.analyze(close_1m, high_1m, low_1m, volume_1m)
        
        # 融合得分
        layer_results = {
            "4h": result_4h,
            "1h": result_1h,
            "15m": result_15m,
            "5m": result_5m,
            "1m": result_1m
        }
        
        total_score, grade, passed_layers = self.engine.fuse(layer_results)
        
        if grade == SignalGrade.B_GRADE:
            return None  # 分数不足
        
        # 确定方向
        direction = TrendDirection.BULLISH  # 基于4H和1H的多头条件
        
        # 计算入场价 (使用1m的VWAP作为参考)
        entry_price = result_1m.get("entry_price", close_1m[-1])
        vwap_1m = result_1m.get("vwap_value", entry_price)
        
        # 计算止损止盈
        stop_loss, take_profit = self._calculate_exit_levels(
            close_1h, entry_price, direction
        )
        
        risk_reward = abs(take_profit - entry_price) / max(abs(stop_loss - entry_price), 0.0001)
        
        if risk_reward < self.config.min_risk_reward:
            return None
        
        # 收集VWAP值
        vwap_values = {
            "1h": result_1h.get("vwap_value", 0),
            "5m": result_5m.get("vwap_value", 0),
            "1m": result_1m.get("vwap_value", 0)
        }
        
        # 构建结构说明
        structure = self._build_structure(layer_results, passed_layers, total_score)
        
        reason = f"五层共振 {passed_layers}/5 层通过 | 得分:{total_score} | {grade.value}级信号"
        
        return FiveLayerSignal(
            signal_type=SignalType.OPEN_LONG,
            grade=grade,
            score=total_score,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            position_size_pct=1.0 if grade == SignalGrade.S_GRADE else 0.5,
            reason=reason,
            layer_scores={k: v.get("score", 0) for k, v in layer_results.items()},
            layer_passed={k: v.get("passed", False) for k, v in layer_results.items()},
            vwap_values=vwap_values,
            structure=structure
        )
    
    def _calculate_exit_levels(self,
                              close: np.ndarray,
                              entry_price: float,
                              direction: TrendDirection) -> Tuple[float, float]:
        """计算止损止盈"""
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_medium)
        current_ema55 = ema55[-1]
        
        recent_low = np.min(close[-20:])
        recent_high = np.max(close[-20:])
        
        if direction == TrendDirection.BULLISH:
            stop_loss = max(current_ema55 * 0.99, recent_low)
            risk = entry_price - stop_loss
            take_profit = entry_price + (risk * 2.5)
        else:
            stop_loss = min(current_ema55 * 1.01, recent_high)
            risk = stop_loss - entry_price
            take_profit = entry_price - (risk * 2.5)
        
        return stop_loss, take_profit
    
    def _build_structure(self,
                        layer_results: Dict[str, Dict],
                        passed_layers: int,
                        total_score: int) -> List[str]:
        """构建结构说明"""
        structure = []
        
        structure.append(f"=== 五层共振分析 ===")
        structure.append(f"共振层数: {passed_layers}/5")
        structure.append(f"总得分: {total_score}")
        
        for layer_name, result in layer_results.items():
            status = "✓" if result.get("passed", False) else "✗"
            score = result.get("score", 0)
            max_score = result.get("max_score", 0)
            reason = result.get("reason", "")
            structure.append(f"{result.get('layer', layer_name)}: {status} {score}/{max_score} - {reason}")
        
        return structure


def create_mtf_system_v2() -> MTFTradingSystemV2:
    """创建五层共振交易系统实例"""
    return MTFTradingSystemV2(MTFConfig())
