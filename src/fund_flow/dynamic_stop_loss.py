"""
1H 结构止损动态调整系统
基于ATR的三层动态止损体系

核心功能：
- 市场状态识别（牛市/震荡/熊市）
- ATR动态止损计算
- 波动率修正系数(VAF)
- 止损与仓位联动机制
- 三阶段移动止损
- 极端波动止损熔断
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import numpy as np


# ==================== 枚举定义 ====================

class MarketState(Enum):
    """市场状态"""
    BULL_MARKET = "bull_market"       # 牛市（趋势上涨）
    BEAR_MARKET = "bear_market"       # 熊市（趋势下跌）
    RANGE_MARKET = "range_market"     # 震荡市（区间横盘）
    EXTREME_VOLATILITY = "extreme_volatility"  # 极端波动


class EntryPosition(Enum):
    """入场位置类型"""
    STANDARD = "standard"         # 标准入场（EMA21附近）
    DEVIATED_2_3 = "deviated_2_3" # 偏离2%~3%入场
    ACCELERATION = "acceleration" # 加速段入场
    RANGE_BOUNDARY = "range_boundary"  # 区间边界入场


class StopLossStage(Enum):
    """止损阶段"""
    INITIAL = "initial"           # 初始止损
    BREAKEVEN = "breakeven"       # 保本止损
    LOCK_PROFIT = "lock_profit"   # 锁利止损
    TRAILING = "trailing"         # 跟踪止损


class StopLossTrigger(Enum):
    """止损触发类型"""
    NONE = "none"
    CIRCUIT_BREAKER = "circuit_breaker"  # 止损熔断
    STRUCTURE_BREAK = "structure_break"  # 结构破坏
    TIME_STOP = "time_stop"              # 时间止损
    TRAILING_STOP = "trailing_stop"      # 移动止损


# ==================== 数据结构 ====================

@dataclass
class ATRInfo:
    """ATR信息"""
    current_atr: float              # 当前ATR(14)
    atr_mean_20: float              # 过去20根ATR均值
    atr_ratio: float                # 当前ATR/均值比例（VAF）
    atr_percentage: float           # ATR占价格比例
    
    @property
    def is_extreme(self) -> bool:
        """是否极端波动"""
        return self.atr_ratio > 2.0
    
    @property
    def is_high_volatility(self) -> bool:
        """是否高波动"""
        return self.atr_ratio > 1.3


@dataclass
class MarketStateResult:
    """市场状态识别结果"""
    state: MarketState
    confidence: float               # 置信度 0~1
    
    # 判断依据
    ema_alignment: str              # EMA排列状态
    macd_direction: str             # MACD方向
    atr_level: str                  # ATR水平
    candle_pattern: str             # K线形态
    
    # 满足条件数
    conditions_met: int
    total_conditions: int


@dataclass
class StopLossResult:
    """止损计算结果"""
    # 止损价格
    stop_price: float
    stop_distance: float            # 止损距离（点数）
    stop_distance_pct: float        # 止损距离（百分比）
    
    # 止损参数
    stop_coefficient: float         # 止损系数K
    vaf_adjustment: float           # VAF修正系数
    stop_anchor: str                # 止损锚点类型
    
    # 市场信息
    market_state: MarketState
    entry_position: EntryPosition
    atr_info: ATRInfo
    
    # 仓位建议
    suggested_position: float       # 建议仓位（BTC数量）
    position_value_usdt: float      # 仓位价值（USDT）
    risk_amount_usdt: float         # 风险金额（USDT）
    
    # 校验结果
    is_valid: bool
    validation_warnings: List[str] = field(default_factory=list)
    
    # 移动止损计划
    trailing_plan: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrailingStopState:
    """移动止损状态"""
    current_stage: StopLossStage
    current_stop_price: float
    unrealized_pnl_pct: float
    bars_held: int
    
    # 各阶段触发条件
    stage_1_trigger_price: float    # 保本触发价
    stage_2_trigger_price: float    # 锁利触发价
    stage_3_trigger_price: float    # 跟踪触发价
    
    # 最近更新
    last_update_reason: str
    last_update_price: float


# ==================== ATR计算器 ====================

class ATRCalculator:
    """ATR计算器"""
    
    @staticmethod
    def calculate(high: np.ndarray, low: np.ndarray, 
                  close: np.ndarray, period: int = 14) -> np.ndarray:
        """
        计算ATR
        
        True Range = max(H-L, |H-Prev_C|, |L-Prev_C|)
        ATR = SMA(True Range, period)
        """
        if len(close) < period + 1:
            return np.array([0.0])
        
        # 计算True Range
        tr = np.zeros(len(close))
        for i in range(1, len(close)):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr[i] = max(hl, hc, lc)
        
        # 计算ATR（SMA）
        atr = np.zeros(len(close))
        atr[period] = np.mean(tr[1:period+1])
        for i in range(period + 1, len(close)):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
        
        return atr
    
    @staticmethod
    def get_info(high: np.ndarray, low: np.ndarray, 
                 close: np.ndarray, period: int = 14,
                 lookback: int = 20) -> ATRInfo:
        """获取ATR详细信息"""
        
        atr = ATRCalculator.calculate(high, low, close, period)
        current_atr = atr[-1] if len(atr) > 0 else 0.0
        
        # 计算20根ATR均值
        if len(atr) >= period + lookback:
            atr_mean_20 = np.mean(atr[-lookback:])
        else:
            atr_mean_20 = current_atr
        
        # 计算ATR比例
        atr_ratio = current_atr / atr_mean_20 if atr_mean_20 > 0 else 1.0
        
        # 计算ATR占价格比例
        current_price = close[-1]
        atr_percentage = current_atr / current_price if current_price > 0 else 0.0
        
        return ATRInfo(
            current_atr=current_atr,
            atr_mean_20=atr_mean_20,
            atr_ratio=atr_ratio,
            atr_percentage=atr_percentage
        )


# ==================== 市场状态识别器 ====================

class MarketStateDetector:
    """
    市场状态识别器
    
    识别三种市场状态：
    - 牛市：趋势上涨
    - 熊市：趋势下跌
    - 震荡市：区间横盘
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        return {
            "ema_fast": 21,
            "ema_medium": 55,
            "ema_slow": 200,
            "macd_threshold": 0.1,
            "atr_high_threshold": 1.2,
            "atr_low_threshold": 0.9,
            "lookback_candles": 10
        }
    
    def detect(self, close: np.ndarray, high: np.ndarray, 
               low: np.ndarray, volume: np.ndarray,
               atr_info: ATRInfo) -> MarketStateResult:
        """
        检测市场状态
        
        Returns:
            MarketStateResult: 包含市场状态和置信度
        """
        
        conditions_met = 0
        total_conditions = 5
        
        # 1. 计算EMA
        ema21 = self._calculate_ema(close, self.config["ema_fast"])
        ema55 = self._calculate_ema(close, self.config["ema_medium"])
        ema200 = self._calculate_ema(close, self.config["ema_slow"]) if len(close) >= 200 else ema55
        
        current_price = close[-1]
        
        # 2. EMA排列判断
        ema_alignment = self._check_ema_alignment(current_price, ema21[-1], ema55[-1], ema200[-1])
        
        # 3. MACD方向判断
        macd_direction = self._check_macd_direction(close)
        
        # 4. ATR水平判断
        atr_level = self._check_atr_level(atr_info)
        
        # 5. K线形态判断
        candle_pattern = self._check_candle_pattern(close, high, low)
        
        # 综合判断
        bull_score = 0
        bear_score = 0
        range_score = 0
        
        # EMA排列计分
        if ema_alignment == "bullish_perfect":
            bull_score += 3
        elif ema_alignment == "bullish":
            bull_score += 2
        elif ema_alignment == "bearish_perfect":
            bear_score += 3
        elif ema_alignment == "bearish":
            bear_score += 2
        else:
            range_score += 2
        
        # MACD方向计分
        if macd_direction == "bullish":
            bull_score += 2
            conditions_met += 1
        elif macd_direction == "bearish":
            bear_score += 2
            conditions_met += 1
        else:
            range_score += 1
        
        # ATR水平计分
        if atr_level == "high":
            if bull_score > bear_score:
                bull_score += 1
            else:
                bear_score += 1
        elif atr_level == "low":
            range_score += 2
        
        # K线形态计分
        if candle_pattern == "bullish":
            bull_score += 1
            conditions_met += 1
        elif candle_pattern == "bearish":
            bear_score += 1
            conditions_met += 1
        
        # 判断最终状态
        if bull_score >= 4 and bull_score > bear_score + 2:
            state = MarketState.BULL_MARKET
            confidence = min(bull_score / 8, 1.0)
        elif bear_score >= 4 and bear_score > bull_score + 2:
            state = MarketState.BEAR_MARKET
            confidence = min(bear_score / 8, 1.0)
        elif range_score >= 3:
            state = MarketState.RANGE_MARKET
            confidence = min(range_score / 5, 1.0)
        else:
            # 默认判断
            if bull_score > bear_score:
                state = MarketState.BULL_MARKET
                confidence = 0.5
            elif bear_score > bull_score:
                state = MarketState.BEAR_MARKET
                confidence = 0.5
            else:
                state = MarketState.RANGE_MARKET
                confidence = 0.5
        
        # 检查极端波动
        if atr_info.is_extreme:
            state = MarketState.EXTREME_VOLATILITY
            confidence = 0.9
        
        return MarketStateResult(
            state=state,
            confidence=confidence,
            ema_alignment=ema_alignment,
            macd_direction=macd_direction,
            atr_level=atr_level,
            candle_pattern=candle_pattern,
            conditions_met=conditions_met,
            total_conditions=total_conditions
        )
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        if len(data) < period:
            return np.array([data[-1]])
        
        multiplier = 2 / (period + 1)
        ema = np.zeros(len(data))
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        return ema
    
    def _check_ema_alignment(self, price: float, ema21: float, 
                             ema55: float, ema200: float) -> str:
        """检查EMA排列"""
        if price > ema21 > ema55 > ema200:
            return "bullish_perfect"
        elif price > ema21 > ema55:
            return "bullish"
        elif price < ema21 < ema55 < ema200:
            return "bearish_perfect"
        elif price < ema21 < ema55:
            return "bearish"
        else:
            return "neutral"
    
    def _check_macd_direction(self, close: np.ndarray) -> str:
        """检查MACD方向"""
        if len(close) < 35:
            return "neutral"
        
        ema12 = self._calculate_ema(close, 12)
        ema26 = self._calculate_ema(close, 26)
        macd_line = ema12 - ema26
        
        # 检查过去10根K线的MACD方向
        recent_macd = macd_line[-10:]
        
        if all(recent_macd > 0):
            return "bullish"
        elif all(recent_macd < 0):
            return "bearish"
        else:
            return "neutral"
    
    def _check_atr_level(self, atr_info: ATRInfo) -> str:
        """检查ATR水平"""
        if atr_info.atr_ratio > self.config["atr_high_threshold"]:
            return "high"
        elif atr_info.atr_ratio < self.config["atr_low_threshold"]:
            return "low"
        else:
            return "normal"
    
    def _check_candle_pattern(self, close: np.ndarray, 
                              high: np.ndarray, low: np.ndarray) -> str:
        """检查K线形态"""
        if len(close) < 5:
            return "neutral"
        
        # 统计最近5根K线的阴阳
        bullish_count = 0
        bearish_count = 0
        
        for i in range(-5, 0):
            if close[i] > close[i-1]:
                bullish_count += 1
            else:
                bearish_count += 1
        
        if bullish_count >= 4:
            return "bullish"
        elif bearish_count >= 4:
            return "bearish"
        else:
            return "neutral"


# ==================== 动态止损计算器 ====================

class DynamicStopLossCalculator:
    """
    动态止损计算器
    
    核心公式：
    止损价格（做多）= max(结构低点, EMA55) − ATR × K
    其中K根据市场状态和入场位置确定
    """
    
    # 止损系数矩阵
    STOP_COEFFICIENTS = {
        MarketState.BULL_MARKET: {
            EntryPosition.STANDARD: 1.5,
            EntryPosition.DEVIATED_2_3: 1.0,
            EntryPosition.ACCELERATION: 1.0,
            EntryPosition.RANGE_BOUNDARY: 1.2
        },
        MarketState.RANGE_MARKET: {
            EntryPosition.STANDARD: 0.8,
            EntryPosition.DEVIATED_2_3: 0.6,
            EntryPosition.ACCELERATION: 0.6,
            EntryPosition.RANGE_BOUNDARY: 0.8
        },
        MarketState.BEAR_MARKET: {
            EntryPosition.STANDARD: 1.5,
            EntryPosition.DEVIATED_2_3: 1.2,
            EntryPosition.ACCELERATION: 1.0,
            EntryPosition.RANGE_BOUNDARY: 1.3
        },
        MarketState.EXTREME_VOLATILITY: {
            EntryPosition.STANDARD: 2.5,
            EntryPosition.DEVIATED_2_3: 2.0,
            EntryPosition.ACCELERATION: 1.5,
            EntryPosition.RANGE_BOUNDARY: 2.0
        }
    }
    
    # 止损距离限制
    MIN_STOP_MULTIPLIER = 0.6   # 最小止损 = ATR × 0.6
    MAX_STOP_MULTIPLIER = 3.0   # 最大止损 = ATR × 3.0
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
        self.market_detector = MarketStateDetector(config)
    
    def _default_config(self) -> Dict:
        return {
            "default_risk_pct": 0.01,     # 默认单笔风险1%
            "max_risk_pct": 0.015,        # 最大单笔风险1.5%
            "account_size": 10000,        # 账户大小（USDT）
            "atr_period": 14,
            "lookback_period": 20
        }
    
    def calculate(self,
                  close: np.ndarray,
                  high: np.ndarray,
                  low: np.ndarray,
                  volume: np.ndarray,
                  entry_price: float,
                  direction: str = "long",
                  entry_position: EntryPosition = EntryPosition.STANDARD,
                  account_size: Optional[float] = None,
                  risk_pct: Optional[float] = None) -> StopLossResult:
        """
        计算动态止损
        
        Args:
            close, high, low, volume: OHLCV数据
            entry_price: 入场价格
            direction: "long" 或 "short"
            entry_position: 入场位置类型
            account_size: 账户大小（USDT）
            risk_pct: 单笔风险比例
        """
        
        # 1. 计算ATR信息
        atr_info = ATRCalculator.get_info(
            high, low, close, 
            self.config["atr_period"],
            self.config["lookback_period"]
        )
        
        # 2. 识别市场状态
        market_result = self.market_detector.detect(
            close, high, low, volume, atr_info
        )
        
        # 3. 获取止损系数
        base_coefficient = self.STOP_COEFFICIENTS[market_result.state][entry_position]
        
        # 4. 应用VAF修正
        vaf_adjustment = self._calculate_vaf_adjustment(atr_info)
        
        # VAF > 2.0 触发止损熔断
        if vaf_adjustment < 0:
            # 极端波动，触发熔断
            circuit_breaker = StopLossCircuitBreaker()
            is_circuit, reason = circuit_breaker.check_circuit(
                atr_info, 
                abs(high[-1] - low[-1])  # 当前K线实体
            )
            if is_circuit:
                validation_warnings.append(f"止损熔断触发: {reason}")
                # 使用固定百分比止损
                fixed_pct = circuit_breaker.config["fixed_pct_stop"]
                if direction == "long":
                    stop_price = entry_price * (1 - fixed_pct)
                else:
                    stop_price = entry_price * (1 + fixed_pct)
                
                actual_stop_distance = abs(entry_price - stop_price)
                
                # 仓位压缩至30%
                account = account_size or self.config["account_size"]
                risk = risk_pct or self.config["default_risk_pct"]
                risk_amount = account * risk
                
                return StopLossResult(
                    stop_price=stop_price,
                    stop_distance=actual_stop_distance,
                    stop_distance_pct=fixed_pct,
                    stop_coefficient=0,  # 熔断状态，不使用ATR系数
                    vaf_adjustment=vaf,
                    stop_anchor="熔断固定百分比",
                    market_state=MarketState.EXTREME_VOLATILITY,
                    entry_position=entry_position,
                    atr_info=atr_info,
                    suggested_position=(risk_amount / actual_stop_distance) * 0.3,
                    position_value_usdt=entry_price * (risk_amount / actual_stop_distance) * 0.3,
                    risk_amount_usdt=risk_amount,
                    is_valid=False,
                    validation_warnings=validation_warnings + ["极端波动，仓位压缩至30%"],
                    trailing_plan={}
                )
        
        adjusted_coefficient = base_coefficient * vaf_adjustment
        
        # 5. 确定止损锚点
        stop_anchor, anchor_price = self._get_stop_anchor(
            close, low, high, direction, market_result.state
        )
        
        # 6. 计算止损价格
        stop_distance = atr_info.current_atr * adjusted_coefficient
        
        if direction == "long":
            stop_price = anchor_price - stop_distance
        else:
            stop_price = anchor_price + stop_distance
        
        # 7. 校验止损距离
        actual_stop_distance = abs(entry_price - stop_price)
        validation_warnings = []
        is_valid = True
        
        min_stop = atr_info.current_atr * self.MIN_STOP_MULTIPLIER
        max_stop = atr_info.current_atr * self.MAX_STOP_MULTIPLIER
        
        if actual_stop_distance < min_stop:
            validation_warnings.append(f"止损距离过紧({actual_stop_distance:.0f} < {min_stop:.0f})")
            # 调整止损
            if direction == "long":
                stop_price = entry_price - min_stop
            else:
                stop_price = entry_price + min_stop
            actual_stop_distance = min_stop
        
        if actual_stop_distance > max_stop:
            validation_warnings.append(f"止损距离过宽({actual_stop_distance:.0f} > {max_stop:.0f})")
            is_valid = False
        
        # 8. 计算仓位
        account = account_size or self.config["account_size"]
        risk = risk_pct or self.config["default_risk_pct"]
        risk_amount = account * risk
        
        suggested_position = risk_amount / actual_stop_distance
        position_value = suggested_position * entry_price
        
        # 9. 计算移动止损计划
        trailing_plan = self._create_trailing_plan(
            entry_price, stop_price, atr_info, direction, market_result.state
        )
        
        return StopLossResult(
            stop_price=stop_price,
            stop_distance=actual_stop_distance,
            stop_distance_pct=actual_stop_distance / entry_price,
            stop_coefficient=adjusted_coefficient,
            vaf_adjustment=vaf_adjustment,
            stop_anchor=stop_anchor,
            market_state=market_result.state,
            entry_position=entry_position,
            atr_info=atr_info,
            suggested_position=suggested_position,
            position_value_usdt=position_value,
            risk_amount_usdt=risk_amount,
            is_valid=is_valid,
            validation_warnings=validation_warnings,
            trailing_plan=trailing_plan
        )
    
    def _calculate_vaf_adjustment(self, atr_info: ATRInfo) -> float:
        """
        计算VAF修正系数
        
        VAF(波动率修正系数) = 当前ATR(14) / ATR(14)过去20根均值
        
        修正规则：
        - VAF < 0.7: 波动率异常低 → K × 0.8（止损收紧）
        - 0.7 ≤ VAF ≤ 1.3: 正常范围 → K不变
        - 1.3 < VAF ≤ 2.0: 波动率偏高 → K × 1.2（止损放宽）
        - VAF > 2.0: 极端波动 → 触发止损熔断（应在外部处理）
        """
        vaf = atr_info.atr_ratio
        
        if vaf < 0.7:
            return 0.8   # 波动率异常低，止损收紧
        elif vaf <= 1.3:
            return 1.0   # 正常范围，不调整
        elif vaf <= 2.0:
            return 1.2   # 波动率偏高，止损放宽
        else:
            # VAF > 2.0 应触发熔断，这里返回标记值
            # 实际熔断处理在calculate方法中
            return -1.0  # 特殊标记，表示需要熔断
    
    def _get_stop_anchor(self, close: np.ndarray, low: np.ndarray,
                         high: np.ndarray, direction: str,
                         market_state: MarketState) -> Tuple[str, float]:
        """确定止损锚点"""
        
        lookback = min(20, len(close) - 1)
        
        if direction == "long":
            # 做多止损锚点
            structure_low = np.min(low[-lookback:])
            ema55 = self._calculate_ema(close, 55)[-1]
            
            if market_state == MarketState.RANGE_MARKET:
                # 震荡市使用区间低点
                return "区间支撑位", structure_low
            else:
                # 趋势市使用结构低点或EMA55中较高的
                anchor = max(structure_low, ema55 * 0.99)
                if anchor == structure_low:
                    return "1H结构低点", structure_low
                else:
                    return "1H EMA55", ema55
        else:
            # 做空止损锚点
            structure_high = np.max(high[-lookback:])
            ema55 = self._calculate_ema(close, 55)[-1]
            
            if market_state == MarketState.RANGE_MARKET:
                return "区间阻力位", structure_high
            else:
                anchor = min(structure_high, ema55 * 1.01)
                if anchor == structure_high:
                    return "1H结构高点", structure_high
                else:
                    return "1H EMA55", ema55
    
    def _create_trailing_plan(self, entry_price: float, stop_price: float,
                              atr_info: ATRInfo, direction: str,
                              market_state: MarketState) -> Dict[str, Any]:
        """创建移动止损计划"""
        
        stop_distance = abs(entry_price - stop_price)
        atr = atr_info.current_atr
        
        if direction == "long":
            return {
                "stage_1_breakeven": {
                    "trigger": f"浮盈 ≥ ATR × 1.0 ({atr:.0f})",
                    "new_stop": entry_price,
                    "trigger_price": entry_price + atr
                },
                "stage_2_lock_profit": {
                    "trigger": f"浮盈 ≥ ATR × 2.0 ({atr * 2:.0f})",
                    "new_stop": entry_price + atr * 0.3,
                    "trigger_price": entry_price + atr * 2
                },
                "stage_3_trailing": {
                    "trigger": f"浮盈 ≥ ATR × 3.0 ({atr * 3:.0f})",
                    "method": "跟随1H EMA21 - ATR × 0.5",
                    "update_frequency": "每根1H K线收盘"
                }
            }
        else:
            return {
                "stage_1_breakeven": {
                    "trigger": f"浮盈 ≥ ATR × 1.0 ({atr:.0f})",
                    "new_stop": entry_price,
                    "trigger_price": entry_price - atr
                },
                "stage_2_lock_profit": {
                    "trigger": f"浮盈 ≥ ATR × 2.0 ({atr * 2:.0f})",
                    "new_stop": entry_price - atr * 0.3,
                    "trigger_price": entry_price - atr * 2
                },
                "stage_3_trailing": {
                    "trigger": f"浮盈 ≥ ATR × 3.0 ({atr * 3:.0f})",
                    "method": "跟随1H EMA21 + ATR × 0.5",
                    "update_frequency": "每根1H K线收盘"
                }
            }
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        if len(data) < period:
            return np.array([data[-1]])
        
        multiplier = 2 / (period + 1)
        ema = np.zeros(len(data))
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        return ema


# ==================== 移动止损管理器 ====================

class TrailingStopManager:
    """
    移动止损管理器
    
    三阶段移动止损：
    阶段1：保本 - 浮盈≥ATR×1.0时止损提至开仓价
    阶段2：锁利 - 浮盈≥ATR×2.0时止损提至开仓价+ATR×0.3
    阶段3：跟踪 - 浮盈≥ATR×3.0时沿EMA21动态跟踪
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        return {
            "stage_1_trigger": 1.0,   # 浮盈 ≥ ATR × 1.0 → 保本止损
            "stage_2_trigger": 2.0,   # 浮盈 ≥ ATR × 2.0 → 锁利止损
            "stage_3_trigger": 3.0,   # 浮盈 ≥ ATR × 3.0 → 跟踪止损
            "trailing_offset": 0.5,   # 跟踪止损偏移 ATR × 0.5
            "lock_profit_offset": 0.3,  # 锁利止损偏移 ATR × 0.3
            
            # 不同市场状态的参数
            "bull_market": {
                "stage_1_trigger": 1.0,
                "stage_2_trigger": 2.0,
                "stage_3_trigger": 3.0
            },
            "range_market": {
                "stage_1_trigger": 0.7,  # 震荡市更早保本
                "stage_2_trigger": 1.5,
                "stage_3_trigger": 2.5
            },
            "bear_market": {
                "stage_1_trigger": 1.0,
                "stage_2_trigger": 2.0,
                "stage_3_trigger": 3.0
            }
        }
    
    def update(self,
               state: TrailingStopState,
               current_price: float,
               ema21: float,
               atr: float,
               recent_low: float,
               recent_high: float,
               direction: str = "long",
               market_state: MarketState = MarketState.BULL_MARKET,
               entry_price: float = 0.0) -> Tuple[float, StopLossStage, str]:
        """
        更新移动止损
        
        三阶段移动止损：
        阶段1（INITIAL → BREAKEVEN）：
          - 触发条件：浮盈 ≥ ATR × 1.0
          - 动作：止损提至开仓价（保本止损）
        
        阶段2（BREAKEVEN → LOCK_PROFIT）：
          - 触发条件：浮盈 ≥ ATR × 2.0
          - 动作：止损提至开仓价 + ATR × 0.3（锁定部分利润）
        
        阶段3（LOCK_PROFIT → TRAILING）：
          - 触发条件：浮盈 ≥ ATR × 3.0
          - 动作：止损跟随EMA21动态移动（EMA21 ± ATR × 0.5）
        
        Returns:
            (new_stop_price, new_stage, reason)
        """
        
        new_stop = state.current_stop_price
        new_stage = state.current_stage
        reason = ""
        
        # 根据市场状态获取参数
        if market_state == MarketState.RANGE_MARKET:
            stage_1_trigger = self.config["range_market"]["stage_1_trigger"]
            stage_2_trigger = self.config["range_market"]["stage_2_trigger"]
            stage_3_trigger = self.config["range_market"]["stage_3_trigger"]
        elif market_state == MarketState.BEAR_MARKET:
            stage_1_trigger = self.config["bear_market"]["stage_1_trigger"]
            stage_2_trigger = self.config["bear_market"]["stage_2_trigger"]
            stage_3_trigger = self.config["bear_market"]["stage_3_trigger"]
        else:  # BULL_MARKET
            stage_1_trigger = self.config["bull_market"]["stage_1_trigger"]
            stage_2_trigger = self.config["bull_market"]["stage_2_trigger"]
            stage_3_trigger = self.config["bull_market"]["stage_3_trigger"]
        
        # 计算浮盈（以ATR为单位）
        if direction == "long":
            pnl_in_atr = (current_price - entry_price) / atr if atr > 0 else 0
        else:
            pnl_in_atr = (entry_price - current_price) / atr if atr > 0 else 0
        
        # 阶段升级判断
        if state.current_stage == StopLossStage.INITIAL:
            if pnl_in_atr >= stage_1_trigger:
                # 升级到保本阶段
                if direction == "long":
                    new_stop = max(state.current_stop_price, entry_price)
                else:
                    new_stop = min(state.current_stop_price, entry_price)
                new_stage = StopLossStage.BREAKEVEN
                reason = f"保本止损触发 (浮盈 {pnl_in_atr:.1f} ATR ≥ {stage_1_trigger})"
        
        elif state.current_stage == StopLossStage.BREAKEVEN:
            if pnl_in_atr >= stage_2_trigger:
                # 升级到锁利阶段
                lock_offset = atr * self.config["lock_profit_offset"]
                if direction == "long":
                    potential_stop = max(entry_price, recent_low - atr * 0.3)
                    new_stop = max(state.current_stop_price, potential_stop)
                else:
                    potential_stop = min(entry_price, recent_high + atr * 0.3)
                    new_stop = min(state.current_stop_price, potential_stop)
                new_stage = StopLossStage.LOCK_PROFIT
                reason = f"锁利止损触发 (浮盈 {pnl_in_atr:.1f} ATR ≥ {stage_2_trigger})"
        
        elif state.current_stage == StopLossStage.LOCK_PROFIT:
            if pnl_in_atr >= stage_3_trigger:
                # 升级到跟踪阶段
                new_stage = StopLossStage.TRAILING
                reason = f"跟踪止损启动 (浮盈 {pnl_in_atr:.1f} ATR ≥ {stage_3_trigger})"
        
        elif state.current_stage == StopLossStage.TRAILING:
            # 跟踪止损更新（只向有利方向移动，永不后退）
            trailing_offset = atr * self.config["trailing_offset"]
            
            if direction == "long":
                # 做多：止损跟随EMA21下方
                potential_stop = ema21 - trailing_offset
                if potential_stop > state.current_stop_price:
                    new_stop = potential_stop
                    reason = f"跟踪止损更新至 EMA21 - {trailing_offset:.0f} ({ema21:.0f} - {trailing_offset:.0f})"
            else:
                # 做空：止损跟随EMA21上方
                potential_stop = ema21 + trailing_offset
                if potential_stop < state.current_stop_price:
                    new_stop = potential_stop
                    reason = f"跟踪止损更新至 EMA21 + {trailing_offset:.0f} ({ema21:.0f} + {trailing_offset:.0f})"
        
        return new_stop, new_stage, reason
    
    def check_price_deviation_adjustment(self,
                                         current_price: float,
                                         ema21: float,
                                         atr: float,
                                         current_stop: float,
                                         direction: str = "long") -> Tuple[float, str]:
        """
        检查价格偏离调整
        
        当价格偏离EMA21超过ATR×3时，收紧止损
        """
        
        deviation = abs(current_price - ema21) / atr if atr > 0 else 0
        
        if deviation > 3.0:
            # 价格偏离过大，收紧止损
            if direction == "long":
                new_stop = max(current_stop, ema21 - atr * 0.5)
                reason = f"价格偏离EMA21 {deviation:.1f} ATR，收紧止损"
            else:
                new_stop = min(current_stop, ema21 + atr * 0.5)
                reason = f"价格偏离EMA21 {deviation:.1f} ATR，收紧止损"
            
            return new_stop, reason
        
        return current_stop, ""


# ==================== 止损熔断处理器 ====================

class StopLossCircuitBreaker:
    """
    止损熔断处理器
    
    触发条件：
    - ATR(14) > 过去20根ATR均值 × 2.5
    - 单根1H K线实体 > ATR(14) × 3.0
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        return {
            "atr_ratio_trigger": 2.5,
            "candle_atr_multiplier": 3.0,
            "position_cap_on_circuit": 0.5,
            "fixed_pct_stop": 0.015  # 1.5%固定止损
        }
    
    def check_circuit(self, atr_info: ATRInfo, 
                      candle_body: float) -> Tuple[bool, str]:
        """
        检查是否触发止损熔断
        
        Returns:
            (is_triggered, reason)
        """
        
        # 条件1：ATR比例超过阈值
        if atr_info.atr_ratio > self.config["atr_ratio_trigger"]:
            return True, f"ATR比例 {atr_info.atr_ratio:.2f} > {self.config['atr_ratio_trigger']}"
        
        # 条件2：单根K线实体过大
        if candle_body > atr_info.current_atr * self.config["candle_atr_multiplier"]:
            return True, f"K线实体 {candle_body:.0f} > ATR × {self.config['candle_atr_multiplier']}"
        
        return False, ""
    
    def apply_circuit_rules(self,
                            stop_result: StopLossResult,
                            direction: str = "long") -> StopLossResult:
        """
        应用熔断规则
        
        熔断状态下的止损处理：
        - 已持仓：止损收紧至最近1H低点，仓位减至50%
        - 新入场：改用固定百分比止损（1.5%），仓位压缩至30%
        """
        
        # 改用固定百分比止损
        fixed_pct = self.config["fixed_pct_stop"]
        entry_price = stop_result.stop_distance / stop_result.stop_distance_pct
        
        if direction == "long":
            new_stop = entry_price * (1 - fixed_pct)
        else:
            new_stop = entry_price * (1 + fixed_pct)
        
        # 更新结果
        stop_result.stop_price = new_stop
        stop_result.stop_distance = abs(entry_price - new_stop)
        stop_result.stop_distance_pct = fixed_pct
        stop_result.suggested_position *= 0.3  # 仓位压缩至30%
        stop_result.position_value_usdt *= 0.3
        stop_result.validation_warnings.append("止损熔断生效，使用固定百分比止损")
        
        return stop_result
    
    def check_release(self, atr_info: ATRInfo,
                      atr_history: List[float]) -> Tuple[bool, str]:
        """
        检查熔断解除条件
        
        条件：
        - ATR(14)回落至过去20根均值的150%以下
        - 连续5根1H K线ATR持续回落
        - 最大单根K线振幅 < ATR × 2.0
        """
        
        # 条件1：ATR比例回落
        if atr_info.atr_ratio > 1.5:
            return False, f"ATR比例 {atr_info.atr_ratio:.2f} 仍 > 1.5"
        
        # 条件2：ATR持续回落
        if len(atr_history) >= 5:
            is_declining = all(atr_history[i] >= atr_history[i+1] 
                              for i in range(len(atr_history)-1))
            if not is_declining:
                return False, "ATR未持续回落"
        
        return True, "熔断解除条件满足"


# ==================== 便捷函数 ====================

def calculate_dynamic_stop_loss(close: np.ndarray,
                                high: np.ndarray,
                                low: np.ndarray,
                                volume: np.ndarray,
                                entry_price: float,
                                direction: str = "long",
                                entry_position: str = "standard",
                                account_size: float = 10000,
                                risk_pct: float = 0.01) -> StopLossResult:
    """
    便捷函数：计算动态止损
    
    Args:
        close, high, low, volume: OHLCV数据
        entry_price: 入场价格
        direction: "long" 或 "short"
        entry_position: "standard", "deviated_2_3", "acceleration", "range_boundary"
        account_size: 账户大小（USDT）
        risk_pct: 单笔风险比例
    
    Returns:
        StopLossResult: 止损计算结果
    """
    
    # 转换入场位置类型
    position_map = {
        "standard": EntryPosition.STANDARD,
        "deviated_2_3": EntryPosition.DEVIATED_2_3,
        "acceleration": EntryPosition.ACCELERATION,
        "range_boundary": EntryPosition.RANGE_BOUNDARY
    }
    entry_pos = position_map.get(entry_position, EntryPosition.STANDARD)
    
    calculator = DynamicStopLossCalculator()
    return calculator.calculate(
        close, high, low, volume,
        entry_price, direction, entry_pos,
        account_size, risk_pct
    )


def get_market_state(close: np.ndarray,
                     high: np.ndarray,
                     low: np.ndarray,
                     volume: np.ndarray) -> MarketStateResult:
    """
    便捷函数：获取市场状态
    
    Returns:
        MarketStateResult: 市场状态识别结果
    """
    
    atr_info = ATRCalculator.get_info(high, low, close)
    detector = MarketStateDetector()
    return detector.detect(close, high, low, volume, atr_info)
