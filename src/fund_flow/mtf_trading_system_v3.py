"""
BTC 完整交易系统 V3.0
核心逻辑：4H 定方向 → 1H 主操作周期 → 15m 找机会 → 5m 精准入场 → 分批加仓 → 规则化出场

关键特性：
- 1H 作为主操作层，承担结构过滤、止损锚定、加仓基准三项核心功能
- Anchored VWAP 锚定波段高低点作为价值中枢
- 分批建仓系统：首仓40% + 确认仓30% + 加速仓30%
- 三阶段移动止损：保本 → 锁利 → 跟踪
- 时间止损机制：3-5根1H K线未启动减仓

适用标的：BTC / ETH / BNB 主流合约
策略类型：趋势跟随 + 回调二次启动
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


# ==================== 枚举定义 ====================

class TrendDirection(Enum):
    """趋势方向"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalGrade(Enum):
    """信号等级 - 基于共振层数"""
    S_GRADE = "S"  # 四层全共振，开首仓40%
    A_GRADE = "A"  # 三层共振，开首仓20%
    B_GRADE = "B"  # 两层共振，等待或放弃


class PositionType(Enum):
    """仓位类型"""
    FIRST = "first"        # 首仓 40%
    CONFIRM = "confirm"    # 确认仓 30%
    ACCELERATE = "accelerate"  # 加速仓 30%


class TrailingStage(Enum):
    """移动止损阶段"""
    BREAKEVEN = "breakeven"  # 保本阶段
    LOCK_PROFIT = "lock_profit"  # 锁利阶段
    TRACKING = "tracking"  # 跟踪阶段


class MarketPhase(Enum):
    """市场阶段"""
    TREND_START = "trend_start"    # 趋势启动
    PULLBACK = "pullback"          # 回调中
    STRUCTURE_STABLE = "structure_stable"  # 结构企稳
    ACCELERATION = "acceleration"  # 加速中
    EXHAUSTION = "exhaustion"      # 动能衰竭


# ==================== 配置类 ====================

@dataclass
class MTFConfigV3:
    """多时间框架配置 V3.0"""
    
    # ============ EMA参数 ============
    # 4H 趋势结构判断
    ema_4h_fast: int = 21
    ema_4h_medium: int = 55
    ema_4h_slow: int = 200
    
    # 1H 主操作层
    ema_1h_fast: int = 21
    ema_1h_medium: int = 55
    
    # 15m 触发层
    ema_15m_fast: int = 21
    ema_15m_medium: int = 55
    
    # ============ MACD参数 ============
    # 4H 方向确认
    macd_4h_fast: int = 12
    macd_4h_slow: int = 26
    macd_4h_signal: int = 9
    
    # 1H 动能强弱判断
    macd_1h_fast: int = 12
    macd_1h_slow: int = 26
    macd_1h_signal: int = 9
    
    # 15m 灵敏动能变化
    macd_15m_fast: int = 8
    macd_15m_slow: int = 21
    macd_15m_signal: int = 5
    
    # 5m 超灵敏入场信号
    macd_5m_fast: int = 6
    macd_5m_slow: int = 20
    macd_5m_signal: int = 4
    
    # ============ VWAP参数 ============
    vwap_anchor_method: str = "swing"  # swing(波段高低点) / session / daily
    
    # ============ 分批建仓比例 ============
    first_position_pct: float = 0.40   # 首仓 40%
    confirm_position_pct: float = 0.30  # 确认仓 30%
    accelerate_position_pct: float = 0.30  # 加速仓 30%
    
    # ============ 风控参数 ============
    max_risk_per_trade: float = 0.015   # 单笔最大风险 1.5%
    min_risk_reward: float = 2.0         # 最小盈亏比
    time_stop_1h_bars: int = 5           # 1H时间止损K线数
    time_stop_15m_bars: int = 5          # 15m时间止损K线数
    
    # ============ 移动止损参数 ============
    breakeven_trigger_pct: float = 0.005  # 浮盈0.5%触发保本
    ema_deviation_max: float = 0.02        # 价格偏离EMA21超过2%不追
    
    # ============ 加仓过滤参数 ============
    min_profit_for_add: float = 0.0      # 加仓要求最小浮盈
    volume_ma_period: int = 20            # 成交量均线周期
    
    # ============ 评分权重 ============
    layer_4h_weight: int = 30  # 4H定方向权重最高
    layer_1h_weight: int = 35  # 1H主操作层核心
    layer_15m_weight: int = 20  # 15m触发层
    layer_5m_weight: int = 15   # 5m入场层
    
    # ============ 方向判断阈值 ============
    direction_condition_threshold: int = 3  # 4条满足3条确认方向


# ==================== 信号数据类 ====================

@dataclass
class LayerResult:
    """单层分析结果"""
    layer_name: str
    passed: bool
    score: int
    max_score: int
    conditions_met: Dict[str, bool]
    reason: str
    details: Dict[str, any] = field(default_factory=dict)


@dataclass
class TradingSignalV3:
    """完整交易信号 V3.0"""
    signal_type: str  # open_long, open_short, add_long, add_short, close
    direction: TrendDirection
    grade: SignalGrade
    
    # 仓位信息
    position_type: PositionType
    position_pct: float
    
    # 价格信息
    entry_price: float
    stop_loss: float
    take_profit_targets: List[Dict[str, any]]  # 分批止盈目标
    
    # 层级分析结果
    layer_results: Dict[str, LayerResult]
    total_score: int
    
    # VWAP信息
    vwap_values: Dict[str, float]
    
    # 风险管理
    risk_reward: float
    risk_amount: float
    
    # 理由
    reason: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class PositionState:
    """持仓状态"""
    direction: TrendDirection
    total_position_pct: float
    avg_entry_price: float
    current_stop_loss: float
    trailing_stage: TrailingStage
    unrealized_pnl_pct: float
    bars_held: int  # 持仓K线数
    add_count: int  # 已加仓次数
    high_water_mark: float  # 最高浮盈价


# ==================== 技术指标工具 ====================

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
                      fast: int, slow: int, signal: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算 MACD"""
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_vwap(high: np.ndarray, low: np.ndarray,
                       close: np.ndarray, volume: np.ndarray,
                       anchor_point: int = 0) -> np.ndarray:
        """
        计算日内 VWAP
        
        VWAP = Σ(Price × Volume) / ΣVolume
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
    def calculate_anchored_vwap(high: np.ndarray, low: np.ndarray,
                                  close: np.ndarray, volume: np.ndarray,
                                  anchor_idx: int) -> np.ndarray:
        """
        计算 Anchored VWAP (锚定波段高低点)
        
        用于4H周期的价值中枢判断
        """
        typical_price = (high + low + close) / 3
        tp_volume = typical_price * volume
        
        # 从锚定点开始累计
        vwap = np.zeros_like(close, dtype=float)
        cum_tp_volume = 0.0
        cum_volume = 0.0
        
        for i in range(anchor_idx, len(close)):
            cum_tp_volume += tp_volume[i]
            cum_volume += volume[i]
            if cum_volume != 0:
                vwap[i] = cum_tp_volume / cum_volume
            else:
                vwap[i] = close[i]
        
        # 锚定点之前使用锚定点值
        for i in range(anchor_idx):
            vwap[i] = vwap[anchor_idx]
        
        return vwap
    
    @staticmethod
    def calculate_atr(high: np.ndarray, low: np.ndarray,
                      close: np.ndarray, period: int = 14) -> np.ndarray:
        """计算 ATR"""
        tr = np.zeros(len(close))
        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        return TechnicalIndicators.calculate_ema(tr, period)
    
    @staticmethod
    def calculate_volume_ma(volume: np.ndarray, period: int = 20) -> np.ndarray:
        """计算成交量均线"""
        return np.convolve(volume, np.ones(period)/period, mode='same')


# ==================== 第一层：4H 定方向 ====================

class Layer4H:
    """
    第一层：4H 定方向层
    
    没有方向，不做任何交易。
    
    做多条件（满足4条中至少3条）：
    1. 价格 > EMA55
    2. EMA21 > EMA55
    3. MACD柱子 > 0
    4. 价格 > Anchored VWAP
    
    强多结构（优先做多）：
    价格 > EMA21 > EMA55 > EMA200
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def analyze(self, close: np.ndarray, high: np.ndarray, 
                low: np.ndarray, volume: np.ndarray,
                swing_anchor_idx: int = 0) -> LayerResult:
        """4H 方向分析"""
        
        # 计算EMA
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_4h_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_4h_medium)
        ema200 = TechnicalIndicators.calculate_ema(close, self.config.ema_4h_slow)
        
        current_price = close[-1]
        
        # 计算MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close, self.config.macd_4h_fast, 
            self.config.macd_4h_slow, self.config.macd_4h_signal
        )
        
        # 计算Anchored VWAP
        avwap = TechnicalIndicators.calculate_anchored_vwap(
            high, low, close, volume, swing_anchor_idx
        )
        
        # 检查做多条件
        long_conditions = {
            "price_above_ema55": current_price > ema55[-1],
            "ema21_above_ema55": ema21[-1] > ema55[-1],
            "macd_positive": histogram[-1] > 0,
            "price_above_avwap": current_price > avwap[-1]
        }
        
        # 检查做空条件
        short_conditions = {
            "price_below_ema55": current_price < ema55[-1],
            "ema21_below_ema55": ema21[-1] < ema55[-1],
            "macd_negative": histogram[-1] < 0,
            "price_below_avwap": current_price < avwap[-1]
        }
        
        # 统计满足条件数
        long_count = sum(long_conditions.values())
        short_count = sum(short_conditions.values())
        
        # 判断方向
        threshold = self.config.direction_condition_threshold
        
        if long_count >= threshold:
            direction = TrendDirection.BULLISH
            passed = True
            score = int(long_count / 4 * self.config.layer_4h_weight)
            reason = f"4H多头方向 ({long_count}/4条件满足)"
        elif short_count >= threshold:
            direction = TrendDirection.BEARISH
            passed = True
            score = int(short_count / 4 * self.config.layer_4h_weight)
            reason = f"4H空头方向 ({short_count}/4条件满足)"
        else:
            direction = TrendDirection.NEUTRAL
            passed = False
            score = 0
            reason = f"4H方向不明确 (多{long_count}/空{short_count})"
        
        # 检查强结构
        strong_bullish = (current_price > ema21[-1] > ema55[-1] > ema200[-1])
        strong_bearish = (current_price < ema21[-1] < ema55[-1] < ema200[-1])
        
        if strong_bullish and direction == TrendDirection.BULLISH:
            score = self.config.layer_4h_weight  # 满分
            reason = f"4H强多结构 (价格>EMA21>EMA55>EMA200)"
        elif strong_bearish and direction == TrendDirection.BEARISH:
            score = self.config.layer_4h_weight
            reason = f"4H强空结构 (价格<EMA21<EMA55<EMA200)"
        
        return LayerResult(
            layer_name="4H",
            passed=passed,
            score=score,
            max_score=self.config.layer_4h_weight,
            conditions_met=long_conditions if direction == TrendDirection.BULLISH else short_conditions,
            reason=reason,
            details={
                "direction": direction.value,
                "long_count": long_count,
                "short_count": short_count,
                "strong_bullish": strong_bullish,
                "strong_bearish": strong_bearish,
                "avwap_value": avwap[-1],
                "ema21": ema21[-1],
                "ema55": ema55[-1],
                "ema200": ema200[-1],
                "macd_histogram": histogram[-1]
            }
        )


# ==================== 第二层：1H 主操作层（核心）====================

# 导入五维度打分器
from .stabilization_scorer import StabilizationScorer, StabilizationResult, SignalLevel


class Layer1H:
    """
    第二层：1H 主操作层 ⭐ 核心
    
    1H 是连接 4H 方向与 15m 入场的枢纽，承担三项核心功能：
    
    ① 结构过滤器：4H做多背景下，1H必须同样维持多头结构
    ② 止损锚点：主止损锚定1H关键结构低点下方
    ③ 加仓基准：第二笔确认仓等待1H层面结构突破
    
    做多等待形态（五维度量化模型）：
    - MACD动能：连续缩短 + 衰减幅度 + 斜率趋平 + 未死叉 (满分30)
    - 价格结构：EMA21偏差率 + EMA55不破 + VWAP上方 (满分30)
    - 成交量：回调量比 + 连续萎缩 + 量能水平 (满分20)
    - K线形态：下影线承接 + 十字星 + 横盘收敛 (满分12)
    - 时间结构：回调根数 + 低点抬高 + 回调幅度 (满分8)
    
    入场条件：总分 ≥ 70 且无否决项
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
        self.stabilization_scorer = StabilizationScorer()
    
    def analyze_structure(self, close: np.ndarray, high: np.ndarray,
                          low: np.ndarray, volume: np.ndarray,
                          expected_direction: TrendDirection) -> LayerResult:
        """
        1H 结构分析 - 五维度量化判定
        
        使用五维度打分模型替代原有的简单判定：
        - MACD动能(30分) + 价格结构(30分) + 成交量(20分) + K线形态(12分) + 时间结构(8分)
        - 总分 ≥ 70 且无否决项 = 结构企稳
        """
        
        # 调用五维度打分器
        direction_str = "long" if expected_direction == TrendDirection.BULLISH else "short"
        stabilization_result = self.stabilization_scorer.analyze(
            close, high, low, volume, direction_str
        )
        
        # 提取结果
        total_score = stabilization_result.total_score
        level = stabilization_result.level
        passed = stabilization_result.passed
        veto_reasons = stabilization_result.veto_reasons
        
        # 构建条件字典
        conditions = {
            "total_score_qualified": total_score >= 70,
            "no_veto": not any(stabilization_result.veto_flags.values()),
            "macd_dimension_passed": stabilization_result.macd_score.actual_score >= 15,
            "price_dimension_passed": stabilization_result.price_score.actual_score >= 15,
            "level_a_or_b": level in [SignalLevel.A_GRADE, SignalLevel.B_GRADE]
        }
        
        # 生成原因
        reason = stabilization_result.reason
        
        if veto_reasons:
            reason = f"1H结构未企稳 | {stabilization_result.reason}"
        elif passed:
            reason = f"1H结构企稳({level.value}级) | {stabilization_result.reason}"
        else:
            reason = f"1H结构未企稳({level.value}级) | 得分{total_score}/100 < 70"
        
        # 计算调整后的得分（映射到35分权重）
        adjusted_score = int(total_score / 100 * self.config.layer_1h_weight)
        
        # 构建详细数据
        details = {
            "total_score": total_score,
            "level": level.value,
            "passed": passed,
            "position_pct": stabilization_result.position_pct,
            "veto_flags": stabilization_result.veto_flags,
            "veto_reasons": veto_reasons,
            "macd_score": stabilization_result.macd_score.actual_score,
            "price_score": stabilization_result.price_score.actual_score,
            "volume_score": stabilization_result.volume_score.actual_score,
            "candle_score": stabilization_result.candle_score.actual_score,
            "time_score": stabilization_result.time_score.actual_score,
            "macd_details": stabilization_result.macd_score.details,
            "price_details": stabilization_result.price_score.details,
            "volume_details": stabilization_result.volume_score.details,
            # 保留兼容字段
            "ema21": stabilization_result.price_score.details.get("EMA21", 0),
            "ema55": stabilization_result.price_score.details.get("EMA55", 0),
            "vwap": stabilization_result.price_score.details.get("VWAP", 0),
            "macd_histogram": stabilization_result.macd_score.details.get("最新柱值", 0),
            "volume_ratio": stabilization_result.volume_score.details.get("量比", 1.0)
        }
        
        return LayerResult(
            layer_name="1H",
            passed=passed,
            score=adjusted_score,
            max_score=self.config.layer_1h_weight,
            conditions_met=conditions,
            reason=reason,
            details=details
        )
    
    def analyze_structure_legacy(self, close: np.ndarray, high: np.ndarray,
                          low: np.ndarray, volume: np.ndarray,
                          expected_direction: TrendDirection) -> LayerResult:
        """1H 结构分析 - 原有逻辑（保留备用）"""
        
        # 计算EMA
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_1h_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_1h_medium)
        
        current_price = close[-1]
        
        # 计算MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close, self.config.macd_1h_fast,
            self.config.macd_1h_slow, self.config.macd_1h_signal
        )
        
        # 计算日内VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        
        # 计算成交量均线
        volume_ma = TechnicalIndicators.calculate_volume_ma(volume, self.config.volume_ma_period)
        
        # 成交量缩减判断
        volume_shrinking = volume[-1] < volume_ma[-1]
        
        if expected_direction == TrendDirection.BULLISH:
            # 做多结构检查
            conditions = {
                "price_above_ema21": current_price > ema21[-1],
                "price_above_vwap": current_price > vwap[-1],
                "macd_not_declining": histogram[-1] >= histogram[-2],  # 红柱停止缩短
                "volume_shrinking": volume_shrinking
            }
            
            # EMA支撑检查
            near_ema21 = abs(current_price - ema21[-1]) / ema21[-1] < 0.02
            near_vwap = abs(current_price - vwap[-1]) / vwap[-1] < 0.02
            
            conditions["near_support"] = near_ema21 or near_vwap
            
            # 检查是否结构企稳
            structure_stable = (
                conditions["price_above_ema21"] and
                conditions["macd_not_declining"]
            )
            
            passed = structure_stable
            
            # 计算得分
            score = sum(conditions.values()) / len(conditions) * self.config.layer_1h_weight
            
            reason = f"1H结构{'企稳' if structure_stable else '未企稳'}"
            if near_ema21:
                reason += " | 接近EMA21支撑"
            if near_vwap:
                reason += " | 接近VWAP支撑"
                
        else:  # BEARISH
            # 做空结构检查
            conditions = {
                "price_below_ema21": current_price < ema21[-1],
                "price_below_vwap": current_price < vwap[-1],
                "macd_not_improving": histogram[-1] <= histogram[-2],  # 绿柱停止缩短
                "volume_shrinking": volume_shrinking
            }
            
            near_ema21 = abs(current_price - ema21[-1]) / ema21[-1] < 0.02
            near_vwap = abs(current_price - vwap[-1]) / vwap[-1] < 0.02
            
            conditions["near_resistance"] = near_ema21 or near_vwap
            
            structure_stable = (
                conditions["price_below_ema21"] and
                conditions["macd_not_improving"]
            )
            
            passed = structure_stable
            score = sum(conditions.values()) / len(conditions) * self.config.layer_1h_weight
            
            reason = f"1H结构{'企稳' if structure_stable else '未企稳'}"
            if near_ema21:
                reason += " | 接近EMA21压制"
            if near_vwap:
                reason += " | 接近VWAP压制"
        
        return LayerResult(
            layer_name="1H",
            passed=passed,
            score=int(score),
            max_score=self.config.layer_1h_weight,
            conditions_met=conditions,
            reason=reason,
            details={
                "structure_stable": structure_stable,
                "ema21": ema21[-1],
                "ema55": ema55[-1],
                "vwap": vwap[-1],
                "macd_histogram": histogram[-1],
                "volume_ratio": volume[-1] / volume_ma[-1] if volume_ma[-1] > 0 else 1
            }
        )
    
    def get_stop_loss_level(self, close: np.ndarray, low: np.ndarray,
                            high: np.ndarray, direction: TrendDirection,
                            lookback: int = 20) -> Tuple[float, str]:
        """
        获取1H止损锚定点
        
        首选：1H关键结构低点
        次选：1H EMA55
        """
        if direction == TrendDirection.BULLISH:
            # 做多止损：1H最近关键结构低点下方
            structure_low = np.min(low[-lookback:])
            ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_1h_medium)
            ema55_stop = ema55[-1] * 0.99
            
            # 选择更合理的止损位
            if structure_low > ema55_stop:
                stop_loss = structure_low * 0.995  # 结构低点下方0.5%
                stop_type = "1H结构低点"
            else:
                stop_loss = ema55_stop
                stop_type = "1H EMA55下方"
        else:
            # 做空止损
            structure_high = np.max(high[-lookback:])
            ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_1h_medium)
            ema55_stop = ema55[-1] * 1.01
            
            if structure_high < ema55_stop:
                stop_loss = structure_high * 1.005
                stop_type = "1H结构高点"
            else:
                stop_loss = ema55_stop
                stop_type = "1H EMA55上方"
        
        return stop_loss, stop_type


# ==================== 第三层：15m 触发层 ====================

class Layer15m:
    """
    第三层：15m 触发层
    
    4H方向明确 + 1H结构企稳 之后，用15m确认具体回踩质量。
    
    理想做多回踩形态：
    - 价格回踩15m EMA21或VWAP
    - 15m MACD红柱缩短（但未死叉）
    - 回调成交量明显缩减
    - 出现K线承接形态（小阴线缩量、十字星、下影线）
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def analyze_pullback(self, close: np.ndarray, high: np.ndarray,
                         low: np.ndarray, volume: np.ndarray,
                         expected_direction: TrendDirection) -> LayerResult:
        """15m 回踩质量分析"""
        
        # 计算EMA
        ema21 = TechnicalIndicators.calculate_ema(close, self.config.ema_15m_fast)
        ema55 = TechnicalIndicators.calculate_ema(close, self.config.ema_15m_medium)
        
        current_price = close[-1]
        
        # 计算MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close, self.config.macd_15m_fast,
            self.config.macd_15m_slow, self.config.macd_15m_signal
        )
        
        # 计算VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        
        # 成交量分析
        volume_ma = TechnicalIndicators.calculate_volume_ma(volume, self.config.volume_ma_period)
        volume_shrinking = volume[-1] < volume_ma[-1] * 0.8  # 缩量20%以上
        
        if expected_direction == TrendDirection.BULLISH:
            # 做多回踩质量检查
            near_ema21 = abs(current_price - ema21[-1]) / ema21[-1] < 0.015
            near_vwap = abs(current_price - vwap[-1]) / vwap[-1] < 0.015
            near_ema55 = current_price > ema55[-1] * 0.995  # 未破EMA55
            
            # MACD状态：红柱缩短但未死叉
            macd_pullback = histogram[-1] > 0 and histogram[-1] < histogram[-2]
            
            # K线形态分析
            candle_body = abs(close[-1] - close[-2])
            candle_range = high[-1] - low[-1]
            is_doji = candle_body < candle_range * 0.1  # 十字星
            has_lower_wick = (close[-1] > low[-1] + candle_range * 0.6)  # 下影线
            
            conditions = {
                "near_ema21_or_vwap": near_ema21 or near_vwap,
                "above_ema55": near_ema55,
                "macd_pullback": macd_pullback,
                "volume_shrinking": volume_shrinking,
                "candle_support": is_doji or has_lower_wick
            }
            
            passed = conditions["near_ema21_or_vwap"] and conditions["above_ema55"]
            score = sum(conditions.values()) / len(conditions) * self.config.layer_15m_weight
            
            reason = f"15m回踩{'质量良好' if passed else '质量不足'}"
            if conditions["candle_support"]:
                reason += " | K线有承接"
            if volume_shrinking:
                reason += " | 缩量"
                
        else:  # BEARISH
            near_ema21 = abs(current_price - ema21[-1]) / ema21[-1] < 0.015
            near_vwap = abs(current_price - vwap[-1]) / vwap[-1] < 0.015
            above_ema55 = current_price < ema55[-1] * 1.005
            
            macd_pullback = histogram[-1] < 0 and histogram[-1] > histogram[-2]
            
            candle_body = abs(close[-1] - close[-2])
            candle_range = high[-1] - low[-1]
            is_doji = candle_body < candle_range * 0.1
            has_upper_wick = (close[-1] < high[-1] - candle_range * 0.6)
            
            conditions = {
                "near_ema21_or_vwap": near_ema21 or near_vwap,
                "below_ema55": above_ema55,
                "macd_pullback": macd_pullback,
                "volume_shrinking": volume_shrinking,
                "candle_resistance": is_doji or has_upper_wick
            }
            
            passed = conditions["near_ema21_or_vwap"] and conditions["below_ema55"]
            score = sum(conditions.values()) / len(conditions) * self.config.layer_15m_weight
            
            reason = f"15m反弹{'质量良好' if passed else '质量不足'}"
            if conditions["candle_resistance"]:
                reason += " | K线受压"
            if volume_shrinking:
                reason += " | 缩量"
        
        return LayerResult(
            layer_name="15m",
            passed=passed,
            score=int(score),
            max_score=self.config.layer_15m_weight,
            conditions_met=conditions,
            reason=reason,
            details={
                "ema21": ema21[-1],
                "ema55": ema55[-1],
                "vwap": vwap[-1],
                "macd_histogram": histogram[-1],
                "volume_ratio": volume[-1] / volume_ma[-1] if volume_ma[-1] > 0 else 1
            }
        )


# ==================== 第四层：5m 精准入场 ====================

class Layer5m:
    """
    第四层：5m 精准入场层
    
    不要只看15m，等5m给出触发信号再入场。
    
    最优做多入场触发（满足任一组合）：
    - 组合A：5m MACD金叉 + 价格站上VWAP
    - 组合B：5m MACD柱子翻红 + 放量突破15m小结构高点
    - 组合C：5m价格有效突破15m关键小高点（带量）
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def analyze_entry(self, close: np.ndarray, high: np.ndarray,
                      low: np.ndarray, volume: np.ndarray,
                      expected_direction: TrendDirection,
                      structure_high_15m: float = None,
                      structure_low_15m: float = None) -> LayerResult:
        """5m 精准入场分析"""
        
        current_price = close[-1]
        
        # 计算MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close, self.config.macd_5m_fast,
            self.config.macd_5m_slow, self.config.macd_5m_signal
        )
        
        # 计算VWAP
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        
        # 成交量分析
        volume_ma = TechnicalIndicators.calculate_volume_ma(volume, self.config.volume_ma_period)
        volume_increasing = volume[-1] > volume_ma[-1] * 1.2  # 放量20%以上
        
        if expected_direction == TrendDirection.BULLISH:
            # 做多入场信号
            macd_golden_cross = histogram[-2] <= 0 and histogram[-1] > 0
            macd_turning_red = histogram[-2] < 0 and histogram[-1] > 0
            price_above_vwap = current_price > vwap[-1]
            
            # 结构突破判断
            if structure_high_15m is not None:
                break_structure = current_price > structure_high_15m
            else:
                break_structure = False
            
            # 组合判断
            combo_a = macd_golden_cross and price_above_vwap
            combo_b = macd_turning_red and volume_increasing and break_structure
            combo_c = break_structure and volume_increasing
            
            conditions = {
                "macd_golden_cross": macd_golden_cross,
                "price_above_vwap": price_above_vwap,
                "volume_increasing": volume_increasing,
                "break_structure": break_structure
            }
            
            passed = combo_a or combo_b or combo_c
            
            if combo_a:
                reason = "5m入场: MACD金叉 + 站上VWAP (组合A)"
            elif combo_b:
                reason = "5m入场: MACD翻红 + 放量突破 (组合B)"
            elif combo_c:
                reason = "5m入场: 带量突破结构高点 (组合C)"
            else:
                reason = "5m入场: 等待触发信号"
            
            score = self.config.layer_5m_weight if passed else 0
            
        else:  # BEARISH
            macd_death_cross = histogram[-2] >= 0 and histogram[-1] < 0
            macd_turning_green = histogram[-2] > 0 and histogram[-1] < 0
            price_below_vwap = current_price < vwap[-1]
            
            if structure_low_15m is not None:
                break_structure = current_price < structure_low_15m
            else:
                break_structure = False
            
            combo_a = macd_death_cross and price_below_vwap
            combo_b = macd_turning_green and volume_increasing and break_structure
            combo_c = break_structure and volume_increasing
            
            conditions = {
                "macd_death_cross": macd_death_cross,
                "price_below_vwap": price_below_vwap,
                "volume_increasing": volume_increasing,
                "break_structure": break_structure
            }
            
            passed = combo_a or combo_b or combo_c
            
            if combo_a:
                reason = "5m入场: MACD死叉 + 跌破VWAP (组合A)"
            elif combo_b:
                reason = "5m入场: MACD翻绿 + 放量跌破 (组合B)"
            elif combo_c:
                reason = "5m入场: 带量跌破结构低点 (组合C)"
            else:
                reason = "5m入场: 等待触发信号"
            
            score = self.config.layer_5m_weight if passed else 0
        
        return LayerResult(
            layer_name="5m",
            passed=passed,
            score=int(score),
            max_score=self.config.layer_5m_weight,
            conditions_met=conditions,
            reason=reason,
            details={
                "vwap": vwap[-1],
                "macd_histogram": histogram[-1],
                "volume_ratio": volume[-1] / volume_ma[-1] if volume_ma[-1] > 0 else 1,
                "entry_price": current_price
            }
        )


# ==================== 加仓管理器 ====================

class PositionManager:
    """
    仓位管理器
    
    分批建仓：首仓40% + 确认仓30% + 加速仓30%
    
    加仓规则：
    - 只允许盈利后加仓
    - 第一次加仓：突破1H小结构前高 + MACD放大 + 量能跟上
    - 第二次加仓：主升浪加速 + 放量突破
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def check_add_position(self,
                          position_state: PositionState,
                          close_1h: np.ndarray,
                          high_1h: np.ndarray,
                          low_1h: np.ndarray,
                          volume_1h: np.ndarray,
                          current_price: float) -> Tuple[bool, PositionType, str]:
        """检查是否满足加仓条件"""
        
        if position_state is None:
            return False, None, "无持仓"
        
        # 禁止加仓检查
        warnings = []
        
        # 检查是否盈利
        if position_state.unrealized_pnl_pct <= self.config.min_profit_for_add:
            return False, None, "未盈利，禁止加仓"
        
        # 检查价格偏离EMA21
        ema21 = TechnicalIndicators.calculate_ema(close_1h, self.config.ema_1h_fast)
        deviation = abs(current_price - ema21[-1]) / ema21[-1]
        
        if deviation > self.config.ema_deviation_max:
            warnings.append(f"价格偏离EMA21超过{deviation*100:.1f}%，不建议追")
        
        # 计算MACD
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close_1h, self.config.macd_1h_fast,
            self.config.macd_1h_slow, self.config.macd_1h_signal
        )
        
        # 成交量分析
        volume_ma = TechnicalIndicators.calculate_volume_ma(volume_1h, self.config.volume_ma_period)
        volume_increasing = volume_1h[-1] > volume_ma[-1]
        
        # MACD放大
        macd_expanding = abs(histogram[-1]) > abs(histogram[-2])
        
        # 结构突破判断
        recent_high = np.max(high_1h[-20:])
        recent_low = np.min(low_1h[-20:])
        
        if position_state.direction == TrendDirection.BULLISH:
            break_structure = current_price > recent_high * 1.001
            vwap = TechnicalIndicators.calculate_vwap(high_1h, low_1h, close_1h, volume_1h)
            above_vwap = current_price > vwap[-1]
        else:
            break_structure = current_price < recent_low * 0.999
            vwap = TechnicalIndicators.calculate_vwap(high_1h, low_1h, close_1h, volume_1h)
            above_vwap = current_price < vwap[-1]  # 对于空头，在VWAP下方
        
        # 第一次加仓（确认仓）
        if position_state.add_count == 0:
            conditions_met = (
                break_structure and
                macd_expanding and
                volume_increasing and
                above_vwap
            )
            
            if conditions_met:
                return True, PositionType.CONFIRM, "确认仓: 1H结构突破 + MACD放大 + 量能跟上"
            else:
                reason = f"确认仓条件: 结构突破={break_structure}, MACD放大={macd_expanding}, 量能={volume_increasing}"
                return False, PositionType.CONFIRM, reason
        
        # 第二次加仓（加速仓）
        elif position_state.add_count == 1:
            # 更严格的条件：主升浪加速
            # 检查低点抬高
            low_1 = np.min(low_1h[-30:-15])
            low_2 = np.min(low_1h[-15:])
            higher_low = low_2 > low_1 if position_state.direction == TrendDirection.BULLISH else True
            
            conditions_met = (
                break_structure and
                macd_expanding and
                volume_increasing and
                higher_low
            )
            
            if conditions_met:
                return True, PositionType.ACCELERATE, "加速仓: 主升浪加速 + 放量突破 + 低点抬高"
            else:
                return False, PositionType.ACCELERATE, "加速仓条件未满足"
        
        return False, None, "已达最大加仓次数"
    
    def check_no_add_conditions(self,
                                close_1h: np.ndarray,
                                current_price: float,
                                direction: TrendDirection) -> List[str]:
        """检查禁止加仓的情况"""
        warnings = []
        
        ema21 = TechnicalIndicators.calculate_ema(close_1h, self.config.ema_1h_fast)
        deviation = abs(current_price - ema21[-1]) / ema21[-1]
        
        # 偏离EMA21过远
        if deviation > self.config.ema_deviation_max:
            warnings.append(f"价格偏离EMA21超过{deviation*100:.1f}%")
        
        # 连续大阳/阴线（简单检查）
        recent_change = abs(close_1h[-1] - close_1h[-4]) / close_1h[-4]
        if recent_change > 0.05:  # 4根K线涨跌超5%
            warnings.append("近期连续大幅波动，不建议追")
        
        return warnings


# ==================== 移动止损管理器 ====================

class TrailingStopManager:
    """
    移动止损管理器
    
    三阶段移动止损：
    阶段1：保本 - 浮盈≥0.5%时止损提至开仓价
    阶段2：锁利 - 1H形成新低点抬高时止损提至前一结构低点
    阶段3：跟踪 - 主升浪时沿1H EMA21动态跟踪
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def update_trailing_stop(self,
                            position_state: PositionState,
                            close_1h: np.ndarray,
                            low_1h: np.ndarray,
                            high_1h: np.ndarray,
                            current_price: float) -> Tuple[float, TrailingStage, str]:
        """更新移动止损"""
        
        if position_state is None:
            return None, None, "无持仓"
        
        ema21 = TechnicalIndicators.calculate_ema(close_1h, self.config.ema_1h_fast)
        unrealized_pnl = position_state.unrealized_pnl_pct
        
        new_stop = position_state.current_stop_loss
        new_stage = position_state.trailing_stage
        reason = ""
        
        if position_state.direction == TrendDirection.BULLISH:
            # 阶段1：保本
            if unrealized_pnl >= self.config.breakeven_trigger_pct:
                if position_state.trailing_stage == TrailingStage.BREAKEVEN:
                    new_stop = max(new_stop, position_state.avg_entry_price)
                    new_stage = TrailingStage.LOCK_PROFIT
                    reason = f"保本止损触发 (浮盈{unrealized_pnl*100:.2f}%)"
            
            # 阶段2：锁利
            if position_state.trailing_stage in [TrailingStage.LOCK_PROFIT, TrailingStage.TRACKING]:
                # 检查是否形成新的低点抬高
                recent_low = np.min(low_1h[-10:])
                if recent_low > position_state.current_stop_loss:
                    new_stop = recent_low * 0.995
                    reason = f"锁利止损更新至{new_stop:.2f}"
            
            # 阶段3：跟踪
            if position_state.trailing_stage == TrailingStage.TRACKING:
                # 沿EMA21跟踪
                ema_stop = ema21[-1] * 0.99
                if ema_stop > new_stop:
                    new_stop = ema_stop
                    reason = f"EMA21跟踪止损更新至{new_stop:.2f}"
        
        else:  # BEARISH
            if unrealized_pnl >= self.config.breakeven_trigger_pct:
                if position_state.trailing_stage == TrailingStage.BREAKEVEN:
                    new_stop = min(new_stop, position_state.avg_entry_price)
                    new_stage = TrailingStage.LOCK_PROFIT
                    reason = f"保本止损触发 (浮盈{unrealized_pnl*100:.2f}%)"
            
            if position_state.trailing_stage in [TrailingStage.LOCK_PROFIT, TrailingStage.TRACKING]:
                recent_high = np.max(high_1h[-10:])
                if recent_high < position_state.current_stop_loss:
                    new_stop = recent_high * 1.005
                    reason = f"锁利止损更新至{new_stop:.2f}"
            
            if position_state.trailing_stage == TrailingStage.TRACKING:
                ema_stop = ema21[-1] * 1.01
                if ema_stop < new_stop:
                    new_stop = ema_stop
                    reason = f"EMA21跟踪止损更新至{new_stop:.2f}"
        
        return new_stop, new_stage, reason
    
    def check_stage_upgrade(self, position_state: PositionState,
                           current_price: float) -> Tuple[bool, TrailingStage]:
        """检查是否升级止损阶段"""
        
        if position_state.unrealized_pnl_pct >= 0.03:  # 浮盈3%以上
            return True, TrailingStage.TRACKING
        elif position_state.unrealized_pnl_pct >= 0.015:  # 浮盈1.5%以上
            return True, TrailingStage.LOCK_PROFIT
        elif position_state.unrealized_pnl_pct >= self.config.breakeven_trigger_pct:
            return True, TrailingStage.BREAKEVEN
        
        return False, position_state.trailing_stage


# ==================== 出场管理器 ====================

class ExitManager:
    """
    出场管理器
    
    分批止盈：
    - +1%~+1.5%: 减1/3
    - +2%~+3%: 再减1/3
    - +3%以上: 剩余让跑，移动止损跟踪
    
    动能衰减止盈：
    - 1H MACD红柱开始缩短
    - 15m/5m出现顶背离
    - 放量冲高后快速回落
    - 1H价格跌破EMA21（清仓信号）
    """
    
    def __init__(self, config: MTFConfigV3):
        self.config = config
    
    def check_take_profit(self,
                         position_state: PositionState,
                         close_1h: np.ndarray,
                         high_1h: np.ndarray,
                         low_1h: np.ndarray) -> Tuple[bool, float, str]:
        """检查止盈条件"""
        
        if position_state is None:
            return False, 0, "无持仓"
        
        pnl_pct = position_state.unrealized_pnl_pct
        reduce_pct = 0
        reason = ""
        
        # 分批止盈
        if pnl_pct >= 0.03:
            reduce_pct = 1.0  # 清仓
            reason = f"浮盈{pnl_pct*100:.1f}%，移动止损跟踪中"
        elif pnl_pct >= 0.02:
            reduce_pct = 1/3
            reason = f"浮盈{pnl_pct*100:.1f}%，减仓1/3"
        elif pnl_pct >= 0.01:
            reduce_pct = 1/3
            reason = f"浮盈{pnl_pct*100:.1f}%，减仓1/3锁定初步利润"
        
        # 动能衰减止盈
        _, _, histogram = TechnicalIndicators.calculate_macd(
            close_1h, self.config.macd_1h_fast,
            self.config.macd_1h_slow, self.config.macd_1h_signal
        )
        
        ema21 = TechnicalIndicators.calculate_ema(close_1h, self.config.ema_1h_fast)
        
        if position_state.direction == TrendDirection.BULLISH:
            # MACD红柱缩短
            macd_declining = histogram[-1] < histogram[-2] and histogram[-1] > 0
            
            # 跌破EMA21
            below_ema21 = close_1h[-1] < ema21[-1]
            
            if below_ema21:
                reduce_pct = 1.0
                reason = "1H价格跌破EMA21，清仓信号"
            elif macd_declining:
                reduce_pct = max(reduce_pct, 0.5)
                reason = "1H MACD红柱缩短，动能衰减"
        
        else:  # BEARISH
            macd_improving = histogram[-1] > histogram[-2] and histogram[-1] < 0
            above_ema21 = close_1h[-1] > ema21[-1]
            
            if above_ema21:
                reduce_pct = 1.0
                reason = "1H价格突破EMA21，清仓信号"
            elif macd_improving:
                reduce_pct = max(reduce_pct, 0.5)
                reason = "1H MACD绿柱缩短，动能衰减"
        
        return reduce_pct > 0, reduce_pct, reason
    
    def check_time_stop(self, position_state: PositionState) -> Tuple[bool, str]:
        """检查时间止损"""
        if position_state is None:
            return False, "无持仓"
        
        bars_held = position_state.bars_held
        
        if bars_held >= self.config.time_stop_1h_bars:
            if position_state.unrealized_pnl_pct < 0.005:
                return True, f"持仓{bars_held}根1H K线未启动，时间止损"
        
        return False, ""


# ==================== 主交易系统 ====================

class MTFTradingSystemV3:
    """
    多时间框架交易系统 V3.0
    
    执行口诀：
    4H 告诉你能做什么方向
    1H 告诉你现在能不能做
    15m 告诉你大概在哪里做
    5m 告诉你精确的触发点
    
    核心流程：
    Step 1: 4H 确认方向
    Step 2: 1H 等待结构企稳
    Step 3: 15m 确认回踩质量
    Step 4: 5m 精准入场
    Step 5: 第一次加仓
    Step 6: 第二次加仓
    Step 7: 分批出场
    """
    
    def __init__(self, config: Optional[MTFConfigV3] = None):
        self.config = config or MTFConfigV3()
        
        # 初始化各层分析器
        self.layer_4h = Layer4H(self.config)
        self.layer_1h = Layer1H(self.config)
        self.layer_15m = Layer15m(self.config)
        self.layer_5m = Layer5m(self.config)
        
        # 初始化管理器
        self.position_manager = PositionManager(self.config)
        self.trailing_stop_manager = TrailingStopManager(self.config)
        self.exit_manager = ExitManager(self.config)
    
    def analyze(self,
               # 4H 数据
               close_4h: np.ndarray, high_4h: np.ndarray,
               low_4h: np.ndarray, volume_4h: np.ndarray,
               # 1H 数据
               close_1h: np.ndarray, high_1h: np.ndarray,
               low_1h: np.ndarray, volume_1h: np.ndarray,
               # 15m 数据
               close_15m: np.ndarray, high_15m: np.ndarray,
               low_15m: np.ndarray, volume_15m: np.ndarray,
               # 5m 数据
               close_5m: np.ndarray, high_5m: np.ndarray,
               low_5m: np.ndarray, volume_5m: np.ndarray,
               # 可选参数
               swing_anchor_idx: int = 0,
               position_state: PositionState = None) -> Optional[TradingSignalV3]:
        """
        四层共振分析
        
        流程：
        1. 4H 定方向（必须通过）
        2. 1H 等结构企稳（必须通过）
        3. 15m 找回踩机会
        4. 5m 精准入场
        """
        
        # ============ Step 1: 4H 定方向 ============
        result_4h = self.layer_4h.analyze(
            close_4h, high_4h, low_4h, volume_4h, swing_anchor_idx
        )
        
        if not result_4h.passed:
            return None  # 4H方向不明确，禁止交易
        
        direction = TrendDirection(result_4h.details["direction"])
        
        # ============ Step 2: 1H 等结构企稳 ============
        result_1h = self.layer_1h.analyze_structure(
            close_1h, high_1h, low_1h, volume_1h, direction
        )
        
        if not result_1h.passed:
            return None  # 1H结构未企稳，等待
        
        # ============ Step 3: 15m 找回踩机会 ============
        result_15m = self.layer_15m.analyze_pullback(
            close_15m, high_15m, low_15m, volume_15m, direction
        )
        
        # ============ Step 4: 5m 精准入场 ============
        # 获取15m结构高低点
        structure_high_15m = np.max(high_15m[-20:])
        structure_low_15m = np.min(low_15m[-20:])
        
        result_5m = self.layer_5m.analyze_entry(
            close_5m, high_5m, low_5m, volume_5m, direction,
            structure_high_15m, structure_low_15m
        )
        
        # ============ 融合得分 ============
        total_score = (
            result_4h.score + 
            result_1h.score + 
            result_15m.score + 
            result_5m.score
        )
        
        # 计算通过的层数
        passed_layers = sum([
            result_4h.passed,
            result_1h.passed,
            result_15m.passed,
            result_5m.passed
        ])
        
        # 确定信号等级
        if passed_layers >= 4:
            grade = SignalGrade.S_GRADE
            position_pct = self.config.first_position_pct
        elif passed_layers >= 3:
            grade = SignalGrade.A_GRADE
            position_pct = self.config.first_position_pct / 2  # 减半
        else:
            return None  # 分数不足
        
        # ============ 计算止损止盈 ============
        stop_loss, stop_type = self.layer_1h.get_stop_loss_level(
            close_1h, low_1h, high_1h, direction
        )
        
        entry_price = close_5m[-1]
        risk = abs(entry_price - stop_loss)
        take_profit_1 = entry_price + risk * 2 if direction == TrendDirection.BULLISH else entry_price - risk * 2
        take_profit_2 = entry_price + risk * 3 if direction == TrendDirection.BULLISH else entry_price - risk * 3
        
        # 分批止盈目标
        take_profit_targets = [
            {"target_pct": 0.01, "reduce_pct": 1/3, "reason": "+1%减仓1/3"},
            {"target_pct": 0.02, "reduce_pct": 1/3, "reason": "+2%再减1/3"},
            {"target_price": take_profit_2, "reduce_pct": 1.0, "reason": "风险回报比3:1清仓"}
        ]
        
        risk_reward = 2.0  # 默认盈亏比
        
        # 收集VWAP值
        vwap_values = {
            "4h_avwap": result_4h.details.get("avwap_value", 0),
            "1h_vwap": result_1h.details.get("vwap", 0),
            "15m_vwap": result_15m.details.get("vwap", 0),
            "5m_vwap": result_5m.details.get("vwap", 0)
        }
        
        # 构建信号
        layer_results = {
            "4h": result_4h,
            "1h": result_1h,
            "15m": result_15m,
            "5m": result_5m
        }
        
        reason = f"四层共振 {passed_layers}/4 | 得分:{total_score} | {grade.value}级 | 止损:{stop_type}"
        
        # 警告检查
        warnings = []
        ema21_1h = TechnicalIndicators.calculate_ema(close_1h, self.config.ema_1h_fast)
        deviation = abs(entry_price - ema21_1h[-1]) / ema21_1h[-1]
        if deviation > self.config.ema_deviation_max:
            warnings.append(f"价格偏离1H EMA21超过{deviation*100:.1f}%")
        
        return TradingSignalV3(
            signal_type="open_long" if direction == TrendDirection.BULLISH else "open_short",
            direction=direction,
            grade=grade,
            position_type=PositionType.FIRST,
            position_pct=position_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_targets=take_profit_targets,
            layer_results=layer_results,
            total_score=total_score,
            vwap_values=vwap_values,
            risk_reward=risk_reward,
            risk_amount=risk,
            reason=reason,
            warnings=warnings
        )
    
    def check_add_position(self,
                          position_state: PositionState,
                          close_1h: np.ndarray, high_1h: np.ndarray,
                          low_1h: np.ndarray, volume_1h: np.ndarray,
                          current_price: float) -> Tuple[bool, Optional[TradingSignalV3]]:
        """检查加仓"""
        can_add, pos_type, reason = self.position_manager.check_add_position(
            position_state, close_1h, high_1h, low_1h, volume_1h, current_price
        )
        
        if not can_add:
            return False, None
        
        # 生成加仓信号
        stop_loss, _ = self.layer_1h.get_stop_loss_level(
            close_1h, low_1h, high_1h, position_state.direction
        )
        
        position_pct = (
            self.config.confirm_position_pct if pos_type == PositionType.CONFIRM
            else self.config.accelerate_position_pct
        )
        
        signal = TradingSignalV3(
            signal_type="add_long" if position_state.direction == TrendDirection.BULLISH else "add_short",
            direction=position_state.direction,
            grade=SignalGrade.A_GRADE,
            position_type=pos_type,
            position_pct=position_pct,
            entry_price=current_price,
            stop_loss=max(stop_loss, position_state.avg_entry_price),  # 加仓止损至少保本
            take_profit_targets=[],
            layer_results={},
            total_score=0,
            vwap_values={},
            risk_reward=0,
            risk_amount=abs(current_price - stop_loss),
            reason=reason,
            warnings=[]
        )
        
        return True, signal


def create_mtf_system_v3() -> MTFTradingSystemV3:
    """创建V3.0交易系统实例"""
    return MTFTradingSystemV3(MTFConfigV3())
