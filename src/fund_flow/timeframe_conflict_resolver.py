"""
跨周期冲突处理方案
BTC 交易系统配套模块

核心问题：4H 多头 + 1H 空头时，既不能盲目入场，也不能无限等待，需要明确的判断框架

解决方案：冲突性质分类 × 量化等待窗口 × 三条解除路径

关键特性：
- 冲突强度评分（0-12分）
- 四种典型冲突形态识别
- 等待窗口三维量化（时间/价格/动能）
- 三条解除路径（恢复/超时/转空）
- 主动观察清单
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import numpy as np


# ==================== 枚举定义 ====================

class ConflictIntensity(Enum):
    """冲突强度"""
    WEAK = "weak"          # 弱冲突 (0-3分)
    MEDIUM = "medium"      # 中冲突 (4-7分)
    STRONG = "strong"      # 强冲突 (8-12分)


class ConflictPattern(Enum):
    """冲突形态"""
    SHORT_TERM_PULLBACK = "short_term_pullback"      # 形态一：1H短期回调型
    DEEP_PULLBACK = "deep_pullback"                   # 形态二：1H深度回调型
    TREND_REVERSAL = "trend_reversal"                 # 形态三：1H趋势反转型
    TIMEFRAME_SPLIT = "timeframe_split"               # 形态四：周期割裂型


class ResolutionPath(Enum):
    """解除路径"""
    PATH_1_RECOVERY = "path_1_recovery"              # 路径一：1H顺势恢复
    PATH_2_TIMEOUT = "path_2_timeout"                  # 路径二：方向等待超时
    PATH_3_REVERSAL = "path_3_reversal"               # 路径三：方向升级转空


class ConflictState(Enum):
    """冲突状态"""
    DETECTED = "detected"           # 刚检测到冲突
    WAITING = "waiting"             # 等待窗口中
    PAUSED = "paused"               # 等待窗口暂停（重大事件期间）
    RESOLVED = "resolved"           # 已解除
    TIMEOUT = "timeout"             # 等待超时
    ESCALATED = "escalated"         # 升级为转空


class WindowState(Enum):
    """
    等待窗口状态机
    
    状态转换：
    ACTIVE -> PAUSED (重大事件触发暂停)
    PAUSED -> ACTIVE (事件结束恢复)
    ACTIVE -> EXPIRED (超时)
    ACTIVE -> RESOLVED (路径一解除)
    """
    ACTIVE = "active"      # 正常运行
    PAUSED = "paused"      # 因外部事件暂停
    EXPIRED = "expired"    # 正常超时（路径二）
    RESOLVED = "resolved"  # 路径一或路径三解除


class MACDPosition(Enum):
    """MACD位置状态"""
    PULLBACK = "pullback"           # 红柱缩短（回调）
    STAGNANT = "stagnant"           # 零轴附近钝化
    REVERSAL = "reversal"           # 绿柱扩大（趋势反转）


class PriceVsEMA55(Enum):
    """价格与EMA55关系"""
    ABOVE = "above"                 # 价格在EMA55上方
    TOUCHING = "touching"           # 触碰EMA55
    BELOW = "below"                 # 收盘于EMA55下方


class VolumeState(Enum):
    """成交量状态"""
    SHRINKING = "shrinking"         # 下跌缩量（健康）
    FLAT = "flat"                   # 下跌量平
    EXPANDING = "expanding"         # 下跌放量（主动抛售）


class MACDState4H(Enum):
    """4H MACD状态"""
    EXPANDING = "expanding"         # 红柱仍在扩大
    SHRINKING = "shrinking"         # 红柱开始缩短
    DIVERGENCE = "divergence"       # 顶背离或接近死叉


# ==================== 配置类 ====================

@dataclass
class ConflictResolverConfig:
    """冲突处理配置"""
    
    # ============ ATR参数 ============
    atr_period: int = 14
    
    # ============ 冲突强度评分阈值 ============
    weak_threshold: int = 3         # 0-3分为弱冲突
    medium_threshold: int = 7       # 4-7分为中冲突
    # 8-12分为强冲突
    
    # ============ 等待窗口参数 ============
    # 弱冲突等待窗口
    weak_time_limit_1h: int = 5                    # 5根1H K线
    weak_price_limit_pct: float = 0.003            # EMA55下方0.3%
    weak_momentum_limit_pct: float = 0.30          # 4H红柱缩短<30%
    
    # 中冲突等待窗口
    medium_time_limit_1h: int = 8                  # 8根1H K线
    medium_price_limit_pct: float = 0.005          # 4H EMA55下方0.5%
    medium_momentum_limit_pct: float = 0.50        # 4H红柱缩短<50%
    
    # 强冲突等待窗口
    strong_time_limit_4h: int = 3                  # 3根4H K线
    strong_price_limit_pct: float = 0.005          # 4H EMA200下方0.5%
    strong_momentum_limit_pct: float = 0.70        # 4H红柱缩短<70%
    
    # ============ 企稳打分门槛 ============
    weak_stabilization_threshold: int = 70
    medium_stabilization_threshold: int = 75
    strong_stabilization_threshold: int = 80
    
    # ============ 首仓比例 ============
    weak_position_pct: float = 0.40
    medium_position_pct: float = 0.20
    strong_position_pct: float = 0.15
    
    # ============ 止损系数 ============
    weak_stop_coefficient: float = 1.5
    medium_stop_coefficient: float = 1.2
    strong_stop_coefficient: float = 1.0
    
    # ============ 路径三参数 ============
    path3_min_conditions: int = 3                  # 路径三需要满足的最小条件数
    path3_position_pct: float = 0.50               # 路径三首仓为标准空单的50%
    path3_stop_atr_multiplier: float = 1.5         # 路径三止损ATR倍数
    
    # ============ 特殊情况参数 ============
    max_daily_conflicts: int = 2                   # 单日内冲突超过2次停止做多
    event_buffer_hours: int = 2                    # 重大事件前暂停等待的缓冲时间


# ==================== 评分维度 ====================

@dataclass
class ConflictScoreDimension:
    """
    冲突评分维度
    
    分组说明（满分12分，等权重设计）：
    - 动能组（合计4分）：4H MACD状态(2) + 1H MACD位置(2)
    - 结构组（合计4分）：1H价格与EMA55(2) + 1H下跌幅度ATR(2)
    - 时序组（合计4分）：1H下跌持续时间(2) + 1H成交量变化(2)
    
    设计原则：
    跨周期冲突判断的核心是"多维度证据的综合"，单一维度（包括4H MACD）
    不应获得压倒性权重，等权重设计具有更强的鲁棒性。
    """
    name: str
    score: int          # 0, 1, 或 2
    max_score: int = 2
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    group: str = ""     # 分组标签: "momentum" / "structure" / "timing"


@dataclass
class ConflictScore:
    """冲突评分结果"""
    total_score: int
    intensity: ConflictIntensity
    dimensions: List[ConflictScoreDimension]
    pattern: ConflictPattern
    reason: str


# ==================== 等待窗口 ====================

@dataclass
class WaitingWindow:
    """
    等待窗口
    
    支持状态机模式：
    - ACTIVE: 正常运行，bars_elapsed递增
    - PAUSED: 重大事件期间暂停，不递增计数
    - EXPIRED/RESOLVED: 终态
    """
    time_limit: int                           # 时间上限（K线根数）
    time_limit_unit: str                      # 时间单位 ('1h' 或 '4h')
    price_limit: float                        # 价格下限
    price_limit_type: str                     # 价格下限类型描述
    momentum_limit: float                     # 动能上限（MACD缩短百分比）
    
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    bars_elapsed: int = 0
    
    # 状态机支持
    state: WindowState = WindowState.ACTIVE
    pause_reason: str = ""
    paused_at: Optional[datetime] = None
    
    def tick(self) -> None:
        """
        每根K线收盘后调用
        只在ACTIVE状态时计数
        """
        if self.state == WindowState.ACTIVE:
            self.bars_elapsed += 1
    
    def pause(self, reason: str) -> bool:
        """
        外部事件触发暂停
        
        Args:
            reason: 暂停原因（如"美联储决议"、"CPI数据发布"等）
        
        Returns:
            是否成功暂停
        """
        if self.state == WindowState.ACTIVE:
            self.state = WindowState.PAUSED
            self.pause_reason = reason
            self.paused_at = datetime.now()
            return True
        return False
    
    def resume(self) -> bool:
        """
        外部事件结束后恢复
        
        Returns:
            是否成功恢复
        """
        if self.state == WindowState.PAUSED:
            self.state = WindowState.ACTIVE
            self.pause_reason = ""
            self.paused_at = None
            return True
        return False
    
    def is_expired(self) -> bool:
        """检查是否超时"""
        return self.bars_elapsed >= self.time_limit
    
    def remaining_bars(self) -> int:
        """剩余K线数"""
        return max(0, self.time_limit - self.bars_elapsed)
    
    def is_paused(self) -> bool:
        """检查是否暂停中"""
        return self.state == WindowState.PAUSED


@dataclass
class ObservationSignal:
    """观察信号"""
    supports_trend: bool              # 支持趋势延续
    signal_type: str                  # 信号类型描述
    weight: int                       # 权重
    description: str = ""             # 详细描述
    triggered: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActiveObservation:
    """主动观察状态"""
    support_signals: List[ObservationSignal]      # 支持信号
    denial_signals: List[ObservationSignal]       # 否定信号
    support_count: int = 0
    denial_count: int = 0
    
    def update_counts(self):
        """更新计数"""
        self.support_count = sum(1 for s in self.support_signals if s.triggered)
        self.denial_count = sum(1 for s in self.denial_signals if s.triggered)


# ==================== 冲突状态 ====================

@dataclass
class ConflictContext:
    """冲突上下文"""
    # 基本信息
    conflict_id: str
    detected_time: datetime
    state: ConflictState
    
    # 评分信息
    score: ConflictScore
    
    # 等待窗口
    waiting_window: WaitingWindow
    
    # 观察状态
    observation: ActiveObservation
    
    # 4H方向
    direction_4h: str                  # 'bullish' 或 'bearish'
    
    # 当前价格信息
    current_price: float
    ema55_1h: float
    ema55_4h: float
    ema200_4h: float
    
    # MACD信息
    macd_1h_histogram: float
    macd_4h_histogram: float
    
    # ATR
    atr_value: float
    
    # 解除路径
    resolution_path: Optional[ResolutionPath] = None
    
    # 冲突区
    conflict_high: float = 0.0
    conflict_low: float = 0.0
    
    # 当日冲突次数
    daily_conflict_count: int = 0


@dataclass
class ResolutionResult:
    """解除结果"""
    resolved: bool
    path: ResolutionPath
    action: str                         # 'entry', 'abandon', 'reverse'
    position_pct: float = 0.0
    stop_loss: float = 0.0
    stabilization_score: int = 0
    reason: str = ""
    warnings: List[str] = field(default_factory=list)


# ==================== 技术指标工具 ====================

class TechnicalTools:
    """技术分析工具"""
    
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
                      fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算 MACD"""
        ema_fast = TechnicalTools.calculate_ema(prices, fast)
        ema_slow = TechnicalTools.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalTools.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
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
        return TechnicalTools.calculate_ema(tr, period)
    
    @staticmethod
    def detect_divergence(prices: np.ndarray, histogram: np.ndarray,
                          lookback: int = 20) -> str:
        """
        检测背离
        
        顶背离：价格创新高，但MACD柱状图未创新高
        底背离：价格创新低，但MACD柱状图未创新低
        """
        if len(prices) < lookback + 2:
            return "none"
        
        recent_prices = prices[-lookback:]
        recent_hist = histogram[-lookback:]
        
        # 找价格高点和MACD高点
        price_high_idx = np.argmax(recent_prices)
        hist_high_idx = np.argmax(recent_hist)
        
        # 顶背离：价格高点在后，但MACD高点在前，且价格创新高时MACD更低
        if price_high_idx > hist_high_idx:
            if recent_prices[price_high_idx] > recent_prices[hist_high_idx]:
                if recent_hist[price_high_idx] < recent_hist[hist_high_idx]:
                    return "bearish"
        
        # 找价格低点和MACD低点
        price_low_idx = np.argmin(recent_prices)
        hist_low_idx = np.argmin(recent_hist)
        
        # 底背离：价格低点在后，但MACD低点在前，且价格创新低时MACD更高
        if price_low_idx > hist_low_idx:
            if recent_prices[price_low_idx] < recent_prices[hist_low_idx]:
                if recent_hist[price_low_idx] > recent_hist[hist_low_idx]:
                    return "bullish"
        
        return "none"
    
    @staticmethod
    def count_consecutive_bars(prices: np.ndarray, ema: np.ndarray,
                               below: bool = True) -> int:
        """
        计算连续在EMA下方/上方的K线数
        
        Args:
            prices: 收盘价数组
            ema: EMA数组
            below: True计算在EMA下方的连续根数，False计算在上方
        """
        count = 0
        for i in range(len(prices) - 1, -1, -1):
            if below:
                if prices[i] < ema[i]:
                    count += 1
                else:
                    break
            else:
                if prices[i] > ema[i]:
                    count += 1
                else:
                    break
        return count


# ==================== 冲突强度评分器 ====================

class ConflictScorer:
    """
    冲突强度评分器
    
    评分维度（满分12分）：
    1. 1H MACD 位置 (0-2分)
    2. 1H 价格与 EMA55 关系 (0-2分)
    3. 1H 下跌持续时间 (0-2分)
    4. 1H 下跌幅度相对ATR (0-2分)
    5. 4H MACD 状态 (0-2分)
    6. 1H 成交量变化 (0-2分)
    """
    
    def __init__(self, config: ConflictResolverConfig):
        self.config = config
    
    def calculate_score(self,
                       close_1h: np.ndarray, high_1h: np.ndarray, low_1h: np.ndarray,
                       volume_1h: np.ndarray, close_4h: np.ndarray,
                       high_4h: np.ndarray, low_4h: np.ndarray) -> ConflictScore:
        """
        计算冲突强度评分
        """
        dimensions = []
        
        # 计算1H指标
        _, _, histogram_1h = TechnicalTools.calculate_macd(close_1h)
        ema55_1h = TechnicalTools.calculate_ema(close_1h, 55)
        atr_1h = TechnicalTools.calculate_atr(high_1h, low_1h, close_1h, self.config.atr_period)
        
        # 计算4H指标
        _, _, histogram_4h = TechnicalTools.calculate_macd(close_4h)
        ema21_4h = TechnicalTools.calculate_ema(close_4h, 21)
        ema55_4h = TechnicalTools.calculate_ema(close_4h, 55)
        
        # 维度1: 1H MACD位置 (动能组)
        macd_pos_score, macd_pos_desc, macd_pos_type = self._score_macd_position(histogram_1h)
        dimensions.append(ConflictScoreDimension(
            name="1H MACD位置",
            score=macd_pos_score,
            description=macd_pos_desc,
            details={"type": macd_pos_type},
            group="momentum"  # 动能组
        ))
        
        # 维度2: 1H价格与EMA55关系 (结构组)
        price_ema_score, price_ema_desc, price_ema_type = self._score_price_vs_ema55(
            close_1h, ema55_1h
        )
        dimensions.append(ConflictScoreDimension(
            name="1H价格与EMA55关系",
            score=price_ema_score,
            description=price_ema_desc,
            details={"type": price_ema_type},
            group="structure"  # 结构组
        ))
        
        # 维度3: 1H下跌持续时间 (时序组)
        duration_score, duration_desc = self._score_down_duration(close_1h, ema55_1h)
        dimensions.append(ConflictScoreDimension(
            name="1H下跌持续时间",
            score=duration_score,
            description=duration_desc,
            group="timing"  # 时序组
        ))
        
        # 维度4: 1H下跌幅度相对ATR (结构组)
        amplitude_score, amplitude_desc = self._score_down_amplitude(
            close_1h, high_1h, low_1h, atr_1h
        )
        dimensions.append(ConflictScoreDimension(
            name="1H下跌幅度",
            score=amplitude_score,
            description=amplitude_desc,
            group="structure"  # 结构组
        ))
        
        # 维度5: 4H MACD状态 (动能组)
        macd_4h_score, macd_4h_desc, macd_4h_type = self._score_4h_macd_state(
            close_4h, histogram_4h
        )
        dimensions.append(ConflictScoreDimension(
            name="4H MACD状态",
            score=macd_4h_score,
            description=macd_4h_desc,
            details={"type": macd_4h_type},
            group="momentum"  # 动能组
        ))
        
        # 维度6: 1H成交量变化 (时序组)
        volume_score, volume_desc, volume_type = self._score_volume_state(volume_1h)
        dimensions.append(ConflictScoreDimension(
            name="1H成交量变化",
            score=volume_score,
            description=volume_desc,
            details={"type": volume_type},
            group="timing"  # 时序组
        ))
        
        # 计算总分
        total_score = sum(d.score for d in dimensions)
        
        # 确定冲突强度
        if total_score <= self.config.weak_threshold:
            intensity = ConflictIntensity.WEAK
        elif total_score <= self.config.medium_threshold:
            intensity = ConflictIntensity.MEDIUM
        else:
            intensity = ConflictIntensity.STRONG
        
        # 确定冲突形态
        pattern = self._determine_pattern(
            dimensions, close_1h, ema55_1h, histogram_1h, histogram_4h
        )
        
        reason = f"冲突评分: {total_score}/12 | 强度: {intensity.value} | 形态: {pattern.value}"
        
        return ConflictScore(
            total_score=total_score,
            intensity=intensity,
            dimensions=dimensions,
            pattern=pattern,
            reason=reason
        )
    
    def _score_macd_position(self, histogram: np.ndarray) -> Tuple[int, str, str]:
        """评分维度1: 1H MACD位置"""
        current = histogram[-1]
        prev = histogram[-2]
        
        if current > 0:
            # 红柱缩短（回调）
            if current < prev:
                return 0, "红柱缩短（回调）", MACDPosition.PULLBACK.value
            else:
                return 0, "红柱扩大（回调减弱）", MACDPosition.PULLBACK.value
        elif abs(current) < abs(histogram[-5]) * 0.3 if len(histogram) > 5 else False:
            # 零轴附近钝化
            return 1, "零轴附近钝化", MACDPosition.STAGNANT.value
        else:
            # 绿柱扩大（趋势反转）
            if current < prev:
                return 2, "绿柱扩大（趋势反转）", MACDPosition.REVERSAL.value
            else:
                return 1, "绿柱缩短（回调中）", MACDPosition.STAGNANT.value
    
    def _score_price_vs_ema55(self, close: np.ndarray, ema55: np.ndarray) -> Tuple[int, str, str]:
        """评分维度2: 1H价格与EMA55关系"""
        current_price = close[-1]
        current_ema55 = ema55[-1]
        distance_pct = abs(current_price - current_ema55) / current_ema55
        
        if current_price > current_ema55:
            if distance_pct < 0.005:
                return 1, "触碰EMA55", PriceVsEMA55.TOUCHING.value
            return 0, "价格在EMA55上方", PriceVsEMA55.ABOVE.value
        else:
            return 2, "收盘于EMA55下方", PriceVsEMA55.BELOW.value
    
    def _score_down_duration(self, close: np.ndarray, ema55: np.ndarray) -> Tuple[int, str]:
        """评分维度3: 1H下跌持续时间"""
        # 计算连续在EMA55下方的K线数
        down_bars = TechnicalTools.count_consecutive_bars(close, ema55, below=True)
        
        if down_bars <= 3:
            return 0, f"≤3根1H K线 ({down_bars}根)"
        elif down_bars <= 7:
            return 1, f"4-7根1H K线 ({down_bars}根)"
        else:
            return 2, f"≥8根1H K线 ({down_bars}根)"
    
    def _score_down_amplitude(self, close: np.ndarray, high: np.ndarray,
                              low: np.ndarray, atr: np.ndarray) -> Tuple[int, str]:
        """评分维度4: 1H下跌幅度相对ATR"""
        # 计算从最近高点到当前价格的跌幅
        recent_high = np.max(high[-30:])
        current_price = close[-1]
        current_atr = atr[-1] if len(atr) > 0 else (high[-1] - low[-1])
        
        down_amplitude = (recent_high - current_price) / current_atr if current_atr > 0 else 0
        
        if down_amplitude < 1.5:
            return 0, f"<1.5×ATR ({down_amplitude:.2f}×ATR)"
        elif down_amplitude <= 3.0:
            return 1, f"1.5-3.0×ATR ({down_amplitude:.2f}×ATR)"
        else:
            return 2, f">3.0×ATR ({down_amplitude:.2f}×ATR)"
    
    def _score_4h_macd_state(self, close: np.ndarray, histogram: np.ndarray) -> Tuple[int, str, str]:
        """评分维度5: 4H MACD状态"""
        current = histogram[-1]
        prev = histogram[-2]
        
        if current > 0:
            if current > prev:
                return 0, "红柱仍在扩大", MACDState4H.EXPANDING.value
            else:
                # 检查顶背离
                divergence = TechnicalTools.detect_divergence(close, histogram)
                if divergence == "bearish":
                    return 2, "顶背离或接近死叉", MACDState4H.DIVERGENCE.value
                return 1, "红柱开始缩短", MACDState4H.SHRINKING.value
        else:
            return 2, "MACD死叉或绿柱", MACDState4H.DIVERGENCE.value
    
    def _score_volume_state(self, volume: np.ndarray) -> Tuple[int, str, str]:
        """评分维度6: 1H成交量变化"""
        if len(volume) < 20:
            return 0, "数据不足", VolumeState.FLAT.value
        
        current_vol = volume[-1]
        avg_vol = np.mean(volume[-20:])
        ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        
        if ratio < 0.8:
            return 0, f"下跌缩量 ({ratio:.2f})", VolumeState.SHRINKING.value
        elif ratio < 1.2:
            return 1, f"下跌量平 ({ratio:.2f})", VolumeState.FLAT.value
        else:
            return 2, f"下跌放量 ({ratio:.2f})", VolumeState.EXPANDING.value
    
    def _determine_pattern(self, dimensions: List[ConflictScoreDimension],
                          close: np.ndarray, ema55: np.ndarray,
                          histogram_1h: np.ndarray, histogram_4h: np.ndarray) -> ConflictPattern:
        """确定冲突形态"""
        total_score = sum(d.score for d in dimensions)
        
        # 检查各种形态特征
        
        # 形态一：1H短期回调型
        if total_score <= 3:
            return ConflictPattern.SHORT_TERM_PULLBACK
        
        # 检查4H是否仍然强势
        macd_4h_dim = next((d for d in dimensions if d.name == "4H MACD状态"), None)
        macd_4h_ok = macd_4h_dim and macd_4h_dim.score <= 1
        
        # 检查价格是否在EMA55上方
        price_ema_dim = next((d for d in dimensions if d.name == "1H价格与EMA55关系"), None)
        price_above_ema55 = price_ema_dim and price_ema_dim.score == 0
        
        # 形态二：1H深度回调型
        if 4 <= total_score <= 7 and price_above_ema55:
            return ConflictPattern.DEEP_PULLBACK
        
        # 形态三：1H趋势反转型
        if total_score >= 8:
            if macd_4h_dim and macd_4h_dim.score == 2:
                return ConflictPattern.TREND_REVERSAL
            return ConflictPattern.DEEP_PULLBACK
        
        # 形态四：周期割裂型
        if 6 <= total_score <= 10 and not macd_4h_ok:
            return ConflictPattern.TIMEFRAME_SPLIT
        
        # 默认返回深度回调
        return ConflictPattern.DEEP_PULLBACK


# ==================== 等待窗口管理器 ====================

class WaitingWindowManager:
    """
    等待窗口管理器
    
    按冲突强度划分等待窗口：
    - 弱冲突：5根1H K线
    - 中冲突：8根1H K线
    - 强冲突：3根4H K线
    """
    
    def __init__(self, config: ConflictResolverConfig):
        self.config = config
    
    def create_window(self,
                     intensity: ConflictIntensity,
                     ema55_1h: float,
                     ema55_4h: float,
                     ema200_4h: float,
                     current_time: datetime = None) -> WaitingWindow:
        """创建等待窗口"""
        
        if current_time is None:
            current_time = datetime.now()
        
        if intensity == ConflictIntensity.WEAK:
            window = WaitingWindow(
                time_limit=self.config.weak_time_limit_1h,
                time_limit_unit='1h',
                price_limit=ema55_1h * (1 - self.config.weak_price_limit_pct),
                price_limit_type=f"1H EMA55下方{self.config.weak_price_limit_pct*100:.1f}%",
                momentum_limit=self.config.weak_momentum_limit_pct,
                start_time=current_time
            )
        elif intensity == ConflictIntensity.MEDIUM:
            window = WaitingWindow(
                time_limit=self.config.medium_time_limit_1h,
                time_limit_unit='1h',
                price_limit=ema55_4h * (1 - self.config.medium_price_limit_pct),
                price_limit_type=f"4H EMA55下方{self.config.medium_price_limit_pct*100:.1f}%",
                momentum_limit=self.config.medium_momentum_limit_pct,
                start_time=current_time
            )
        else:  # STRONG
            window = WaitingWindow(
                time_limit=self.config.strong_time_limit_4h,
                time_limit_unit='4h',
                price_limit=ema200_4h * (1 - self.config.strong_price_limit_pct),
                price_limit_type=f"4H EMA200下方{self.config.strong_price_limit_pct*100:.1f}%",
                momentum_limit=self.config.strong_momentum_limit_pct,
                start_time=current_time
            )
        
        return window
    
    def check_window_limits(self,
                           window: WaitingWindow,
                           current_price: float,
                           current_bars: int,
                           macd_shrink_pct: float) -> Tuple[bool, str]:
        """
        检查等待窗口上限是否触发
        
        Returns:
            (是否触发上限, 触发原因)
        """
        # 检查时间上限
        if current_bars >= window.time_limit:
            return True, f"时间上限触发: {current_bars}/{window.time_limit}根K线"
        
        # 检查价格下限
        if current_price < window.price_limit:
            return True, f"价格下限触发: {current_price:.2f} < {window.price_limit:.2f}"
        
        # 检查动能上限
        if macd_shrink_pct > window.momentum_limit:
            return True, f"动能上限触发: MACD缩短{macd_shrink_pct*100:.1f}% > {window.momentum_limit*100:.1f}%"
        
        return False, ""


# ==================== 观察信号管理器 ====================

class ObservationManager:
    """
    观察信号管理器
    
    管理等待期间的主动观察清单
    """
    
    def __init__(self, config: ConflictResolverConfig):
        self.config = config
    
    def create_observation(self) -> ActiveObservation:
        """创建观察状态"""
        
        # 支持趋势延续的信号
        support_signals = [
            ObservationSignal(
                supports_trend=True,
                signal_type="下影线承接",
                weight=1,
                description="本根1H K线出现下影线承接（下影 > 实体 × 1.5）"
            ),
            ObservationSignal(
                supports_trend=True,
                signal_type="回调缩量",
                weight=1,
                description="本根1H K线成交量相对前根缩减"
            ),
            ObservationSignal(
                supports_trend=True,
                signal_type="MACD绿柱缩短",
                weight=1,
                description="1H MACD绿柱在缩短（空头动能衰减）"
            ),
            ObservationSignal(
                supports_trend=True,
                signal_type="4H EMA21支撑有效",
                weight=1,
                description="1H价格仍在4H EMA21上方"
            ),
            ObservationSignal(
                supports_trend=True,
                signal_type="链上数据无异常",
                weight=1,
                description="无巨量转出或交易所大额流入"
            ),
        ]
        
        # 否定趋势延续的信号
        denial_signals = [
            ObservationSignal(
                supports_trend=False,
                signal_type="下跌放量",
                weight=1,
                description="1H下跌K线持续放量（主动抛售）"
            ),
            ObservationSignal(
                supports_trend=False,
                signal_type="MACD绿柱扩大",
                weight=1,
                description="1H MACD绿柱持续扩大"
            ),
            ObservationSignal(
                supports_trend=False,
                signal_type="跌破4H EMA21",
                weight=1,
                description="价格已跌破4H EMA21"
            ),
            ObservationSignal(
                supports_trend=False,
                signal_type="4H MACD红柱缩短>40%",
                weight=1,
                description="4H MACD红柱明显缩短"
            ),
            ObservationSignal(
                supports_trend=False,
                signal_type="4H顶背离",
                weight=2,
                description="出现4H级别的顶背离信号"
            ),
        ]
        
        return ActiveObservation(
            support_signals=support_signals,
            denial_signals=denial_signals
        )
    
    def update_observation(self,
                          observation: ActiveObservation,
                          candle_1h: Dict[str, float],
                          macd_1h_histogram: float,
                          macd_1h_prev: float,
                          price: float,
                          ema21_4h: float,
                          macd_4h_shrink_pct: float,
                          has_4h_divergence: bool) -> ActiveObservation:
        """
        更新观察信号
        
        Args:
            candle_1h: {'open', 'high', 'low', 'close', 'volume'}
        """
        # 重置所有信号
        for signal in observation.support_signals:
            signal.triggered = False
        for signal in observation.denial_signals:
            signal.triggered = False
        
        # 检查支持信号
        # 1. 下影线承接
        body = abs(candle_1h['close'] - candle_1h['open'])
        lower_wick = min(candle_1h['open'], candle_1h['close']) - candle_1h['low']
        observation.support_signals[0].triggered = (lower_wick > body * 1.5 if body > 0 else False)
        observation.support_signals[0].details = {"lower_wick": lower_wick, "body": body}
        
        # 2. 回调缩量
        observation.support_signals[1].triggered = candle_1h.get('volume_shrinking', False)
        
        # 3. MACD绿柱缩短
        observation.support_signals[2].triggered = (
            macd_1h_histogram < 0 and macd_1h_histogram > macd_1h_prev
        )
        
        # 4. 4H EMA21支撑有效
        observation.support_signals[3].triggered = price > ema21_4h
        
        # 5. 链上数据（暂时设为True，需要外部数据源）
        observation.support_signals[4].triggered = True
        
        # 检查否定信号
        # 1. 下跌放量
        observation.denial_signals[0].triggered = candle_1h.get('volume_expanding', False)
        
        # 2. MACD绿柱扩大
        observation.denial_signals[1].triggered = (
            macd_1h_histogram < 0 and macd_1h_histogram < macd_1h_prev
        )
        
        # 3. 跌破4H EMA21
        observation.denial_signals[2].triggered = price < ema21_4h
        
        # 4. 4H MACD红柱缩短>40%
        observation.denial_signals[3].triggered = macd_4h_shrink_pct > 0.4
        
        # 5. 4H顶背离
        observation.denial_signals[4].triggered = has_4h_divergence
        
        # 更新计数
        observation.update_counts()
        
        return observation
    
    def evaluate_observation(self, observation: ActiveObservation) -> Tuple[str, str]:
        """
        评估观察结果
        
        Returns:
            (建议动作, 详细原因)
        """
        support = observation.support_count
        denial = observation.denial_count
        
        if support >= 3:
            return "continue_wait", f"支持信号{support}项 ≥ 3，继续等待，趋势延续概率高"
        elif denial >= 3:
            return "consider_path3", f"否定信号{denial}项 ≥ 3，考虑启动路径三评估"
        elif denial >= 2 and support <= 1:
            return "cautious", f"否定信号{denial}项，支持信号仅{support}项，需谨慎"
        else:
            return "continue_wait", f"支持{support}项/否定{denial}项，继续观察"


# ==================== 路径评估器 ====================

class PathEvaluator:
    """
    解除路径评估器
    
    三条路径：
    1. 路径一：1H顺势恢复（冲突正常解除）
    2. 路径二：方向等待超时（冲突未解除）
    3. 路径三：方向升级转空（冲突演变为反向机会）
    """
    
    def __init__(self, config: ConflictResolverConfig):
        self.config = config
    
    def evaluate_path1_recovery(self,
                               context: ConflictContext,
                               stabilization_score: int,
                               macd_4h_shrink_pct: float) -> ResolutionResult:
        """
        评估路径一：1H顺势恢复
        
        触发标准（须全部满足）：
        1. 1H价格重新站上EMA21，且收盘于EMA21上方
        2. 1H MACD红柱重新出现
        3. 1H企稳打分达到门槛
        4. 1H成交量健康
        5. 4H MACD状态未继续恶化
        """
        warnings = []
        
        # 检查企稳打分门槛
        threshold = self._get_stabilization_threshold(context.score.intensity)
        if stabilization_score < threshold:
            return ResolutionResult(
                resolved=False,
                path=ResolutionPath.PATH_1_RECOVERY,
                action="wait",
                stabilization_score=stabilization_score,
                reason=f"企稳打分{stabilization_score} < 门槛{threshold}"
            )
        
        # 检查4H动能状态
        if macd_4h_shrink_pct > context.waiting_window.momentum_limit:
            return ResolutionResult(
                resolved=False,
                path=ResolutionPath.PATH_1_RECOVERY,
                action="wait",
                stabilization_score=stabilization_score,
                reason=f"4H MACD恶化超过上限: {macd_4h_shrink_pct*100:.1f}%"
            )
        
        # 计算首仓比例和止损
        position_pct = self._get_position_pct(context.score.intensity)
        stop_coefficient = self._get_stop_coefficient(context.score.intensity)
        stop_loss = context.current_price - context.atr_value * stop_coefficient
        
        reason = f"路径一解除 | 企稳{stabilization_score}分 | 首仓{position_pct*100:.0f}%"
        
        return ResolutionResult(
            resolved=True,
            path=ResolutionPath.PATH_1_RECOVERY,
            action="entry",
            position_pct=position_pct,
            stop_loss=stop_loss,
            stabilization_score=stabilization_score,
            reason=reason,
            warnings=warnings
        )
    
    def evaluate_path2_timeout(self,
                              context: ConflictContext,
                              current_price: float,
                              current_bars: int,
                              macd_4h_shrink_pct: float) -> ResolutionResult:
        """
        评估路径二：方向等待超时
        
        触发条件（满足任一）：
        1. 时间触发：等待根数超过上限
        2. 价格触发：触碰对应等待窗口的价格下限
        3. 动能触发：4H MACD恶化超过动能上限
        """
        window = context.waiting_window
        
        # 检查各项上限
        limit_hit, limit_reason = WaitingWindowManager(self.config).check_window_limits(
            window, current_price, current_bars, macd_4h_shrink_pct
        )
        
        if limit_hit:
            return ResolutionResult(
                resolved=True,
                path=ResolutionPath.PATH_2_TIMEOUT,
                action="abandon",
                reason=f"路径二超时 | {limit_reason}"
            )
        
        return ResolutionResult(
            resolved=False,
            path=ResolutionPath.PATH_2_TIMEOUT,
            action="wait",
            reason="等待窗口未超时"
        )
    
    def evaluate_path3_reversal(self,
                               context: ConflictContext,
                               close_4h: np.ndarray,
                               histogram_4h: np.ndarray,
                               ema21_4h: float,
                               ema55_4h: float,
                               consecutive_below_ema55: int,
                               short_signal_count: int,
                               path1_resolved: bool = False) -> ResolutionResult:
        """
        评估路径三：方向升级转空
        
        前序条件（必须先满足）：
        1. 冲突强度达到"强冲突"（8-12分）
        2. 等待窗口已经开启（不是第一次看到冲突就转空）
        3. 等待窗口内没有出现路径一的解除信号
        
        识别标准（满足≥3/4即考虑转空）：
        1. 4H MACD出现顶背离
        2. 4H价格跌破EMA21
        3. 1H连续3根以上下跌K线且在EMA55下方收盘
        4. 1H做空条件满足≥3/4
        
        Returns:
            ResolutionResult: 解除结果
        """
        # ==================== 前序条件校验 ====================
        
        # 前序条件1: 必须是强冲突（8-12分）
        if context.score.intensity != ConflictIntensity.STRONG:
            return ResolutionResult(
                resolved=False,
                path=ResolutionPath.PATH_3_REVERSAL,
                action="wait",
                reason=f"路径三前序条件不满足: 非强冲突 ({context.score.intensity.value})"
            )
        
        # 前序条件2: 等待窗口必须已开启（至少经过1根K线）
        if context.waiting_window.bars_elapsed < 1:
            return ResolutionResult(
                resolved=False,
                path=ResolutionPath.PATH_3_REVERSAL,
                action="wait",
                reason="路径三前序条件不满足: 等待窗口未开启，需要先观察等待"
            )
        
        # 前序条件3: 路径一未解除
        if path1_resolved:
            return ResolutionResult(
                resolved=False,
                path=ResolutionPath.PATH_3_REVERSAL,
                action="wait",
                reason="路径三前序条件不满足: 路径一已解除，不需要评估路径三"
            )
        
        # ==================== 4项条件评估 ====================
        
        conditions_met = 0
        condition_details = []
        
        # 条件1: 4H MACD顶背离
        divergence = TechnicalTools.detect_divergence(close_4h, histogram_4h)
        has_divergence = divergence == "bearish"
        if has_divergence:
            conditions_met += 1
            condition_details.append("4H MACD顶背离")
        
        # 条件2: 4H价格跌破EMA21
        current_price_4h = close_4h[-1]
        below_ema21_4h = current_price_4h < ema21_4h
        if below_ema21_4h:
            conditions_met += 1
            condition_details.append("4H跌破EMA21")
        
        # 条件3: 1H连续下跌且在EMA55下方
        if consecutive_below_ema55 >= 3:
            conditions_met += 1
            condition_details.append(f"1H连续{consecutive_below_ema55}根在EMA55下方")
        
        # 条件4: 1H做空条件
        if short_signal_count >= 3:
            conditions_met += 1
            condition_details.append(f"1H做空条件{short_signal_count}/4")
        
        # 判断是否触发路径三
        if conditions_met >= self.config.path3_min_conditions:
            """
            路径三做空止损计算
            
            逻辑说明：
            路径三是做空方向，止损必须设在价格上方（止损 > 当前价）
            止损 = 冲突期间最高价 + ATR × 1.5
            
            含义：
            1. 冲突期间最高价是多头最后一次有效防守的价格
            2. 若价格收复此高点，说明4H多头未被破坏，做空判断错误
            3. ATR × 1.5 的缓冲防止高点处的插针假突破触发止损
            
            注意：这是做空止损，值大于入场价，与做多止损方向相反
            """
            stop_loss = context.conflict_high + context.atr_value * self.config.path3_stop_atr_multiplier
            position_pct = self.config.path3_position_pct
            
            reason = f"路径三转空 | 满足{conditions_met}/4条件 | {', '.join(condition_details)}"
            
            return ResolutionResult(
                resolved=True,
                path=ResolutionPath.PATH_3_REVERSAL,
                action="reverse",
                position_pct=position_pct,
                stop_loss=stop_loss,
                reason=reason
            )
        
        return ResolutionResult(
            resolved=False,
            path=ResolutionPath.PATH_3_REVERSAL,
            action="wait",
            reason=f"路径三条件不足: {conditions_met}/4"
        )
    
    def _get_stabilization_threshold(self, intensity: ConflictIntensity) -> int:
        """获取企稳打分门槛"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_stabilization_threshold
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_stabilization_threshold
        else:
            return self.config.strong_stabilization_threshold
    
    def _get_position_pct(self, intensity: ConflictIntensity) -> float:
        """获取首仓比例"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_position_pct
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_position_pct
        else:
            return self.config.strong_position_pct
    
    def _get_stop_coefficient(self, intensity: ConflictIntensity) -> float:
        """获取止损系数"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_stop_coefficient
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_stop_coefficient
        else:
            return self.config.strong_stop_coefficient


# ==================== 主冲突处理系统 ====================

class TimeframeConflictResolver:
    """
    跨周期冲突处理系统
    
    核心流程：
    1. 检测冲突
    2. 计算冲突强度评分
    3. 确定冲突形态
    4. 创建等待窗口
    5. 执行主动观察
    6. 评估解除路径
    7. 生成操作建议
    """
    
    def __init__(self, config: Optional[ConflictResolverConfig] = None):
        self.config = config or ConflictResolverConfig()
        
        # 初始化子组件
        self.scorer = ConflictScorer(self.config)
        self.window_manager = WaitingWindowManager(self.config)
        self.observation_manager = ObservationManager(self.config)
        self.path_evaluator = PathEvaluator(self.config)
        
        # 当前活跃的冲突
        self._active_conflict: Optional[ConflictContext] = None
        self._daily_conflict_count: Dict[str, int] = {}
        
        # 4H方向确信度降级标志
        self._4h_confidence_degraded: bool = False
        self._degraded_date: Optional[str] = None
    
    def update_daily_count(self, today: str) -> int:
        """
        更新当日冲突次数，返回当前次数，超限时触发降级
        
        降级规则：
        单日内冲突超过2次，应将4H方向确信度降级，原本满足4/4的多头条件
        降为"3/4边缘状态"，对应等待窗口切换为"强冲突"模式。
        
        Args:
            today: 当前日期字符串 (YYYY-MM-DD)
        
        Returns:
            当日冲突次数
        """
        # 清理旧数据（只保留当天）
        self._daily_conflict_count = {
            k: v for k, v in self._daily_conflict_count.items()
            if k == today
        }
        
        # 递增计数
        self._daily_conflict_count[today] = self._daily_conflict_count.get(today, 0) + 1
        count = self._daily_conflict_count[today]
        
        # 策略降级触发
        if count >= self.config.max_daily_conflicts:
            self._4h_confidence_degraded = True
            self._degraded_date = today
        
        return count
    
    def get_effective_conflict_level(self, raw_score: int) -> ConflictIntensity:
        """
        考虑降级后的有效冲突强度
        
        降级后：
        - 弱冲突(0-3分) -> 中冲突
        - 中冲突(4-7分) -> 强冲突
        - 强冲突(8-12分) -> 强冲突（不变）
        
        Args:
            raw_score: 原始评分
        
        Returns:
            有效的冲突强度等级
        """
        if self._4h_confidence_degraded:
            # 降级映射
            if raw_score <= 3:
                return ConflictIntensity.MEDIUM
            return ConflictIntensity.STRONG
        
        # 正常判断
        if raw_score <= self.config.weak_threshold:
            return ConflictIntensity.WEAK
        elif raw_score <= self.config.medium_threshold:
            return ConflictIntensity.MEDIUM
        else:
            return ConflictIntensity.STRONG
    
    def reset_daily_state(self, today: str) -> None:
        """
        重置当日状态（通常在交易日开始时调用）
        
        Args:
            today: 当前日期字符串
        """
        # 如果是新的一天，重置降级标志
        if self._degraded_date and self._degraded_date != today:
            self._4h_confidence_degraded = False
            self._degraded_date = None
    
    @property
    def is_confidence_degraded(self) -> bool:
        """检查当前是否处于降级状态"""
        return self._4h_confidence_degraded
    
    def detect_conflict(self,
                       close_4h: np.ndarray, high_4h: np.ndarray,
                       low_4h: np.ndarray, volume_4h: np.ndarray,
                       close_1h: np.ndarray, high_1h: np.ndarray,
                       low_1h: np.ndarray, volume_1h: np.ndarray,
                       direction_4h: str) -> Optional[ConflictContext]:
        """
        检测跨周期冲突
        
        Args:
            direction_4h: 'bullish' 或 'bearish'
        
        Returns:
            如果检测到冲突，返回ConflictContext；否则返回None
        """
        # 计算1H MACD
        _, _, histogram_1h = TechnicalTools.calculate_macd(close_1h)
        
        # 计算1H EMA55
        ema55_1h = TechnicalTools.calculate_ema(close_1h, 55)
        
        # 检查是否存在冲突
        # 4H多头 + 1H空头 = 冲突
        if direction_4h == 'bullish':
            # 1H空头特征：价格在EMA55下方 或 MACD绿柱
            price_below_ema55 = close_1h[-1] < ema55_1h[-1]
            macd_bearish = histogram_1h[-1] < 0
            
            if not (price_below_ema55 or macd_bearish):
                return None  # 无冲突
        else:
            # 4H空头 + 1H多头 = 冲突
            price_above_ema55 = close_1h[-1] > ema55_1h[-1]
            macd_bullish = histogram_1h[-1] > 0
            
            if not (price_above_ema55 or macd_bullish):
                return None  # 无冲突
        
        # 检测到冲突，计算评分
        conflict_score = self.scorer.calculate_score(
            close_1h, high_1h, low_1h, volume_1h,
            close_4h, high_4h, low_4h
        )
        
        # 计算技术指标
        ema55_4h = TechnicalTools.calculate_ema(close_4h, 55)
        ema200_4h = TechnicalTools.calculate_ema(close_4h, 200)
        _, _, histogram_4h = TechnicalTools.calculate_macd(close_4h)
        atr_1h = TechnicalTools.calculate_atr(high_1h, low_1h, close_1h, self.config.atr_period)
        
        # 创建等待窗口
        waiting_window = self.window_manager.create_window(
            conflict_score.intensity,
            ema55_1h[-1], ema55_4h[-1], ema200_4h[-1]
        )
        
        # 创建观察状态
        observation = self.observation_manager.create_observation()
        
        # 更新当日冲突次数
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily_conflict_count[today] = self._daily_conflict_count.get(today, 0) + 1
        
        # 创建冲突上下文
        conflict = ConflictContext(
            conflict_id=f"conflict_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            detected_time=datetime.now(),
            state=ConflictState.DETECTED,
            score=conflict_score,
            waiting_window=waiting_window,
            observation=observation,
            direction_4h=direction_4h,
            current_price=close_1h[-1],
            ema55_1h=ema55_1h[-1],
            ema55_4h=ema55_4h[-1],
            ema200_4h=ema200_4h[-1],
            macd_1h_histogram=histogram_1h[-1],
            macd_4h_histogram=histogram_4h[-1],
            atr_value=atr_1h[-1] if len(atr_1h) > 0 else 0,
            conflict_high=high_1h[-20:].max(),
            conflict_low=low_1h[-20:].min(),
            daily_conflict_count=self._daily_conflict_count[today]
        )
        
        self._active_conflict = conflict
        
        return conflict
    
    def update_conflict(self,
                       context: ConflictContext,
                       candle_1h: Dict[str, float],
                       close_4h: np.ndarray,
                       histogram_4h: np.ndarray,
                       ema21_4h: float,
                       stabilization_score: int = 0,
                       short_signal_count: int = 0,
                       close_1h_history: np.ndarray = None,
                       ema55_1h_history: np.ndarray = None) -> ResolutionResult:
        """
        更新冲突状态并评估解除路径
        
        Args:
            context: 冲突上下文
            candle_1h: 当前1H K线数据 {'open', 'high', 'low', 'close', 'volume'}
            close_4h: 4H收盘价历史数据
            histogram_4h: 4H MACD柱状图历史数据
            ema21_4h: 4H EMA21当前值
            stabilization_score: 1H企稳打分
            short_signal_count: 1H做空信号计数
            close_1h_history: 1H收盘价历史数据（用于计算连续下跌根数）
            ema55_1h_history: 1H EMA55历史数据
            
        Returns:
            ResolutionResult: 解除结果
        """
        # 更新等待窗口计数
        context.waiting_window.bars_elapsed += 1
        
        # 计算4H MACD缩短百分比
        macd_4h_shrink_pct = self._calculate_macd_shrink_pct(histogram_4h)
        
        # 检查4H背离
        has_4h_divergence = TechnicalTools.detect_divergence(close_4h, histogram_4h) == "bearish"
        
        # 更新观察信号
        context.observation = self.observation_manager.update_observation(
            context.observation,
            candle_1h,
            context.macd_1h_histogram,
            context.macd_1h_histogram,  # 简化处理
            context.current_price,
            ema21_4h,
            macd_4h_shrink_pct,
            has_4h_divergence
        )
        
        # 更新冲突状态
        context.state = ConflictState.WAITING
        
        # 计算连续在EMA55下方的K线数 - 修复：使用历史数据
        if close_1h_history is not None and ema55_1h_history is not None:
            consecutive_below = TechnicalTools.count_consecutive_bars(
                close_1h_history, ema55_1h_history, below=True
            )
        else:
            # 回退逻辑：如果没有历史数据，使用当前状态判断
            consecutive_below = 1 if context.current_price < context.ema55_1h else 0
        
        # 评估三条路径（优先级：路径一 > 路径三 > 路径二）
        
        # 1. 首先评估路径一（恢复）
        path1_result = self.path_evaluator.evaluate_path1_recovery(
            context, stabilization_score, macd_4h_shrink_pct
        )
        
        if path1_result.resolved:
            context.state = ConflictState.RESOLVED
            context.resolution_path = ResolutionPath.PATH_1_RECOVERY
            return path1_result
        
        # 2. 评估路径三（转空）- 仅在强冲突时
        if context.score.intensity == ConflictIntensity.STRONG:
            path3_result = self.path_evaluator.evaluate_path3_reversal(
                context, close_4h, histogram_4h,
                ema21_4h, context.ema55_4h,
                consecutive_below, short_signal_count
            )
            
            if path3_result.resolved:
                context.state = ConflictState.ESCALATED
                context.resolution_path = ResolutionPath.PATH_3_REVERSAL
                return path3_result
        
        # 3. 最后评估路径二（超时）
        path2_result = self.path_evaluator.evaluate_path2_timeout(
            context, context.current_price,
            context.waiting_window.bars_elapsed,
            macd_4h_shrink_pct
        )
        
        if path2_result.resolved:
            context.state = ConflictState.TIMEOUT
            context.resolution_path = ResolutionPath.PATH_2_TIMEOUT
            return path2_result
        
        # 评估观察结果
        obs_action, obs_reason = self.observation_manager.evaluate_observation(context.observation)
        
        return ResolutionResult(
            resolved=False,
            path=None,
            action=obs_action,
            reason=obs_reason
        )
    
    def check_special_case(self,
                          context: ConflictContext,
                           special_type: str,
                           data: Dict[str, Any]) -> Tuple[str, str]:
        """
        检查特殊情况
        
        Args:
            special_type: 特殊情况类型
                - 'continuous_new_low': 1H持续创新低但4H仍强势
                - 'window_ending_weak_stabilization': 等待窗口即将超时，微弱企稳迹象
                - 'multiple_daily_conflicts': 同一交易日内多次出现冲突
                - 'major_event': 重要数据发布/宏观事件窗口
        """
        if special_type == 'continuous_new_low':
            return self._handle_continuous_new_low(context, data)
        elif special_type == 'window_ending_weak_stabilization':
            return self._handle_window_ending(context, data)
        elif special_type == 'multiple_daily_conflicts':
            return self._handle_multiple_conflicts(context, data)
        elif special_type == 'major_event':
            return self._handle_major_event(context, data)
        else:
            return "continue", "未知特殊情况类型"
    
    def _handle_continuous_new_low(self,
                                  context: ConflictContext,
                                  data: Dict[str, Any]) -> Tuple[str, str]:
        """
        特殊情况1：1H持续创新低但4H仍强势
        """
        volume_shrinking = data.get('volume_shrinking', False)
        down_speed_slowing = data.get('down_speed_slowing', False)
        
        if volume_shrinking and down_speed_slowing:
            return "reset_window", "成交量缩减 + 下跌速度放缓，重置等待窗口"
        else:
            return "upgrade_conflict", "成交量放大或加速下跌，升级冲突强度，进入路径二/三评估"
    
    def _handle_window_ending(self,
                             context: ConflictContext,
                             data: Dict[str, Any]) -> Tuple[str, str]:
        """
        特殊情况2：等待窗口即将超时，微弱企稳迹象
        """
        stabilization_score = data.get('stabilization_score', 0)
        threshold = self._get_stabilization_threshold(context.score.intensity)
        
        if stabilization_score < threshold:
            return "abandon", f"企稳打分{stabilization_score} < 门槛{threshold}，不降低标准，放弃本次机会"
        
        return "continue", "继续等待"
    
    def _handle_multiple_conflicts(self,
                                  context: ConflictContext,
                                  data: Dict[str, Any]) -> Tuple[str, str]:
        """
        特殊情况3：同一交易日内多次出现冲突
        """
        if context.daily_conflict_count > self.config.max_daily_conflicts:
            return "stop_day_trading", f"当日冲突已{context.daily_conflict_count}次，停止做多方向操作"
        
        return "continue", f"当日冲突{context.daily_conflict_count}次，继续监控"
    
    def _handle_major_event(self,
                           context: ConflictContext,
                           data: Dict[str, Any]) -> Tuple[str, str]:
        """
        特殊情况4：重要数据发布/宏观事件窗口
        """
        event_type = data.get('event_type', 'unknown')
        
        return "pause", f"重大事件({event_type})前{self.config.event_buffer_hours}小时，暂停等待窗口倒计时"
    
    def quick_decision(self,
                      context: ConflictContext,
                      close_1h: np.ndarray,
                      histogram_4h: np.ndarray) -> Tuple[str, str]:
        """
        快速决策（30秒内）
        
        用于快速判断当前冲突的处理方式
        """
        # 计算连续下跌K线数
        ema55_1h = TechnicalTools.calculate_ema(close_1h, 55)
        down_bars = TechnicalTools.count_consecutive_bars(close_1h, ema55_1h, below=True)
        
        # Q1: 1H空头持续了多少根K线？
        if down_bars <= 3:
            return "weak_conflict", "弱冲突 | 按标准1H企稳打分流程等待 | 窗口：5根1H K线"
        
        elif 4 <= down_bars <= 7:
            # Q2: 1H价格是否仍在EMA55上方？
            price_above_ema55 = close_1h[-1] > ema55_1h[-1]
            
            if price_above_ema55:
                return "medium_conflict", "中冲突 | 标准等待窗口 | 窗口：8根1H K线"
            else:
                # Q3: 4H MACD红柱缩短是否>40%？
                macd_shrink_pct = self._calculate_macd_shrink_pct(histogram_4h)
                
                if macd_shrink_pct <= 0.4:
                    return "medium_strong_conflict", "中冲突（偏强）| 等待窗口缩短30% | 首仓降至20%"
                else:
                    return "strong_conflict", "强冲突 | 等待窗口：3根4H K线 | 开始路径三评估"
        
        else:  # down_bars >= 8
            # Q4: 4H是否出现顶背离或EMA21跌破？
            ema21_4h = TechnicalTools.calculate_ema(close_1h, 21)
            has_divergence = TechnicalTools.detect_divergence(close_1h, histogram_4h) == "bearish"
            below_ema21 = close_1h[-1] < ema21_4h[-1]
            
            if not (has_divergence or below_ema21):
                return "strong_conservative", "强冲突（但4H未破坏）| 极度保守等待 | 首仓15%，门槛≥80分"
            else:
                return "abandon_evaluate_path3", "放弃做多 | 评估路径三（转空机会）"
    
    def get_entry_parameters(self, context: ConflictContext) -> Dict[str, Any]:
        """
        获取入场参数
        
        Returns:
            {
                'position_pct': 首仓比例,
                'stop_coefficient': 止损ATR系数,
                'stabilization_threshold': 企稳打分门槛,
                'wait_window_bars': 等待窗口K线数
            }
        """
        intensity = context.score.intensity
        
        return {
            'position_pct': self._get_position_pct(intensity),
            'stop_coefficient': self._get_stop_coefficient(intensity),
            'stabilization_threshold': self._get_stabilization_threshold(intensity),
            'wait_window_bars': context.waiting_window.time_limit
        }
    
    def get_speed_reference_card(self) -> Dict[str, Any]:
        """
        获取速查卡
        """
        return {
            'conflict_intensity': {
                'weak': '0-3分',
                'medium': '4-7分',
                'strong': '8-12分'
            },
            'waiting_window': {
                'weak': {
                    'time': '5根1H',
                    'price': 'EMA55下方0.3%',
                    'momentum': '4H红柱缩<30%'
                },
                'medium': {
                    'time': '8根1H',
                    'price': '4H EMA55下方0.5%',
                    'momentum': '4H红柱缩<50%'
                },
                'strong': {
                    'time': '3根4H',
                    'price': '4H EMA200下方0.5%',
                    'momentum': '4H红柱缩<70%'
                }
            },
            'entry_standard': {
                'weak': {
                    'threshold': '≥70分',
                    'position': '40%',
                    'stop': 'ATR×1.5'
                },
                'medium': {
                    'threshold': '≥75分',
                    'position': '20%',
                    'stop': 'ATR×1.2'
                },
                'strong': {
                    'threshold': '≥80分',
                    'position': '15%',
                    'stop': 'ATR×1.0'
                }
            }
        }
    
    def _calculate_macd_shrink_pct(self, histogram: np.ndarray) -> float:
        """
        计算MACD缩短百分比
        
        修复说明：
        - 在最近10根柱中找峰值时排除最后2根，确保是历史峰值
        - 如果当前值大于峰值，返回负值表示MACD正在扩大
        
        Returns:
            正值: 缩短百分比 (0~1)
            负值: 扩大百分比 (表示MACD在扩大)
        """
        if len(histogram) < 10:
            return 0.0
        
        # 在最近10根柱中找峰值（排除最后2根，确保是历史峰值而非当前值）
        recent = histogram[-10:-2] if len(histogram) >= 12 else histogram[:-2]
        if len(recent) == 0:
            return 0.0
        
        peak_idx = np.argmax(np.abs(recent))
        peak_value = abs(recent[peak_idx])
        current_value = abs(histogram[-1])
        
        if peak_value == 0:
            return 0.0
        
        # 如果当前值大于峰值，返回负值表示扩大
        if current_value > peak_value:
            return -(current_value / peak_value - 1.0)
        
        return 1.0 - (current_value / peak_value)
    
    def _get_stabilization_threshold(self, intensity: ConflictIntensity) -> int:
        """获取企稳打分门槛"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_stabilization_threshold
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_stabilization_threshold
        else:
            return self.config.strong_stabilization_threshold
    
    def _get_position_pct(self, intensity: ConflictIntensity) -> float:
        """获取首仓比例"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_position_pct
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_position_pct
        else:
            return self.config.strong_position_pct
    
    def _get_stop_coefficient(self, intensity: ConflictIntensity) -> float:
        """获取止损系数"""
        if intensity == ConflictIntensity.WEAK:
            return self.config.weak_stop_coefficient
        elif intensity == ConflictIntensity.MEDIUM:
            return self.config.medium_stop_coefficient
        else:
            return self.config.strong_stop_coefficient


# ==================== 便捷函数 ====================

def create_conflict_resolver(config: Optional[ConflictResolverConfig] = None) -> TimeframeConflictResolver:
    """创建冲突处理系统实例"""
    return TimeframeConflictResolver(config)


def quick_conflict_check(close_4h: np.ndarray, close_1h: np.ndarray) -> bool:
    """
    快速检查是否存在冲突
    
    Returns:
        True if conflict detected
    """
    # 计算1H EMA55
    ema55_1h = TechnicalTools.calculate_ema(close_1h, 55)
    
    # 计算1H MACD
    _, _, histogram_1h = TechnicalTools.calculate_macd(close_1h)
    
    # 检查1H空头特征
    price_below_ema55 = close_1h[-1] < ema55_1h[-1]
    macd_bearish = histogram_1h[-1] < 0
    
    return price_below_ema55 or macd_bearish


# ==================== 补充1：冲突历史记录与学习机制 ====================

@dataclass
class ConflictRecord:
    """
    冲突历史记录
    
    用途：
    1. 记录每一次冲突的处理结果
    2. 用于优化等待窗口参数
    3. 支持事后复盘分析
    
    复盘专属字段（补充3）：
    - 冲突发现时的强度评分、等待时间、最终路径
    - 入场后的价格变化验证
    - 改进点记录
    """
    # 基本信息
    conflict_id: str
    timestamp: datetime
    
    # 冲突评估
    conflict_level: str                          # weak / medium / strong
    conflict_score: int                          # 0-12分
    score_dimensions: List[ConflictScoreDimension]  # 各维度得分详情
    
    # 等待窗口
    wait_bars_actual: int                        # 实际等待了多少根K线
    wait_bars_limit: int                         # 等待窗口上限
    
    # 解除结果
    resolution_path: str                         # path1 / path2 / path3
    resolution_time: Optional[datetime] = None   # 解除时间
    
    # 入场信息
    entry_score_at_resolution: Optional[int] = None    # 解除时的企稳打分
    entry_threshold: Optional[int] = None              # 实际使用的门槛
    entry_price: Optional[float] = None                # 入场价格
    position_pct: Optional[float] = None               # 实际仓位比例
    
    # 验证信息（事后填写）
    subsequent_price_change: Optional[float] = None    # 入场后N根K线的价格变化(%)
    was_correct: Optional[bool] = None                 # 事后验证：判断是否正确
    verification_bars: int = 24                        # 验证周期（K线根数）
    
    # 复盘字段（补充3）
    macd_4h_max_shrink_pct: Optional[float] = None    # 等待期间4H MACD最大缩短幅度
    denial_signal_triggered: bool = False              # 是否出现否定信号
    denial_signal_type: Optional[str] = None           # 否定信号类型
    improvement_notes: str = ""                        # 改进点记录
    
    # 情绪指标（补充2）
    sentiment_driven: bool = False                     # 是否为情绪驱动的冲突
    fear_greed_index: Optional[int] = None             # 恐惧贪婪指数 (0-100)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于序列化"""
        return {
            'conflict_id': self.conflict_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'conflict_level': self.conflict_level,
            'conflict_score': self.conflict_score,
            'wait_bars_actual': self.wait_bars_actual,
            'wait_bars_limit': self.wait_bars_limit,
            'resolution_path': self.resolution_path,
            'resolution_time': self.resolution_time.isoformat() if self.resolution_time else None,
            'entry_score_at_resolution': self.entry_score_at_resolution,
            'entry_threshold': self.entry_threshold,
            'entry_price': self.entry_price,
            'position_pct': self.position_pct,
            'subsequent_price_change': self.subsequent_price_change,
            'was_correct': self.was_correct,
            'verification_bars': self.verification_bars,
            'macd_4h_max_shrink_pct': self.macd_4h_max_shrink_pct,
            'denial_signal_triggered': self.denial_signal_triggered,
            'denial_signal_type': self.denial_signal_type,
            'improvement_notes': self.improvement_notes,
            'sentiment_driven': self.sentiment_driven,
            'fear_greed_index': self.fear_greed_index
        }


class ConflictLearner:
    """
    基于历史记录优化参数
    
    功能：
    1. 分析历史冲突记录
    2. 建议等待窗口参数调整
    3. 建议企稳打分门槛调整
    4. 识别策略改进点
    """
    
    def __init__(self, min_sample_size: int = 20):
        """
        Args:
            min_sample_size: 最小样本数，低于此数量不提供建议
        """
        self.min_sample_size = min_sample_size
        self.records: List[ConflictRecord] = []
    
    def add_record(self, record: ConflictRecord) -> None:
        """添加冲突记录"""
        self.records.append(record)
    
    def load_records(self, records: List[ConflictRecord]) -> None:
        """批量加载记录"""
        self.records.extend(records)
    
    def clear_records(self) -> None:
        """清空记录"""
        self.records = []
    
    def suggest_parameter_adjustment(self) -> Dict[str, Any]:
        """
        分析历史记录，建议参数调整
        
        Returns:
            {
                'sample_size': 样本数量,
                'wait_bars_suggestion': {
                    'weak': 建议值/None,
                    'medium': 建议值/None,
                    'strong': 建议值/None
                },
                'threshold_suggestion': {
                    'weak': 建议值/None,
                    'medium': 建议值/None,
                    'strong': 建议值/None
                },
                'path_distribution': 各路径占比,
                'accuracy_stats': 准确率统计,
                'improvement_points': 改进建议列表
            }
        """
        result = {
            'sample_size': len(self.records),
            'wait_bars_suggestion': {'weak': None, 'medium': None, 'strong': None},
            'threshold_suggestion': {'weak': None, 'medium': None, 'strong': None},
            'path_distribution': {},
            'accuracy_stats': {},
            'improvement_points': []
        }
        
        if len(self.records) < self.min_sample_size:
            result['improvement_points'].append(
                f"样本数不足（当前{len(self.records)}，需要≥{self.min_sample_size}），暂无调整建议"
            )
            return result
        
        # 1. 按冲突等级分层统计
        for level in ['weak', 'medium', 'strong']:
            samples = [r for r in self.records if r.conflict_level == level]
            
            if not samples:
                continue
            
            # 路径一解除的实际等待时间分布
            path1_samples = [r for r in samples if r.resolution_path == 'path1']
            if path1_samples:
                wait_times = [r.wait_bars_actual for r in path1_samples]
                p80 = np.percentile(wait_times, 80)
                p90 = np.percentile(wait_times, 90)
                
                current_limit = path1_samples[0].wait_bars_limit
                coverage = sum(1 for t in wait_times if t <= current_limit) / len(wait_times)
                
                result['wait_bars_suggestion'][level] = {
                    'current_limit': current_limit,
                    'mean_wait': np.mean(wait_times),
                    'p80': p80,
                    'p90': p90,
                    'coverage_rate': coverage,
                    'recommendation': f"建议调整至{int(np.ceil(p80))}根（覆盖80%场景）" if coverage < 0.8 else "当前参数合理"
                }
        
        # 2. 路径分布统计
        path_counts = {}
        for r in self.records:
            path = r.resolution_path
            path_counts[path] = path_counts.get(path, 0) + 1
        
        total = len(self.records)
        result['path_distribution'] = {
            path: {'count': count, 'rate': count / total}
            for path, count in path_counts.items()
        }
        
        # 3. 准确率统计（仅统计有验证结果的记录）
        verified = [r for r in self.records if r.was_correct is not None]
        if verified:
            correct = sum(1 for r in verified if r.was_correct)
            result['accuracy_stats'] = {
                'verified_count': len(verified),
                'correct_count': correct,
                'accuracy': correct / len(verified) if verified else 0
            }
            
            # 按路径分层的准确率
            for path in ['path1', 'path2', 'path3']:
                path_verified = [r for r in verified if r.resolution_path == path]
                if path_verified:
                    path_correct = sum(1 for r in path_verified if r.was_correct)
                    result['accuracy_stats'][f'{path}_accuracy'] = path_correct / len(path_verified)
        
        # 4. 改进建议
        self._generate_improvement_points(result)
        
        return result
    
    def _generate_improvement_points(self, result: Dict[str, Any]) -> None:
        """生成改进建议"""
        path_dist = result.get('path_distribution', {})
        accuracy = result.get('accuracy_stats', {})
        
        # 检查路径分布
        if path_dist.get('path2', {}).get('rate', 0) > 0.5:
            result['improvement_points'].append(
                "路径二（超时放弃）占比过高（>50%），考虑延长等待窗口或降低企稳门槛"
            )
        
        if path_dist.get('path3', {}).get('rate', 0) > 0.3:
            result['improvement_points'].append(
                "路径三（转空）占比较高（>30%），4H趋势判断可能存在滞后"
            )
        
        # 检查准确率
        if accuracy.get('accuracy', 1) < 0.5:
            result['improvement_points'].append(
                f"整体准确率偏低（{accuracy['accuracy']:.1%}），建议审查入场条件"
            )
        
        # 检查各路径准确率
        for path in ['path1', 'path2', 'path3']:
            path_acc = accuracy.get(f'{path}_accuracy')
            if path_acc is not None and path_acc < 0.4:
                result['improvement_points'].append(
                    f"{path}准确率偏低（{path_acc:.1%}），需要针对性优化"
                )
    
    def get_level_statistics(self) -> Dict[str, Any]:
        """
        获取各冲突等级的统计信息
        
        用于验证冲突强度分级是否有效：
        - 弱冲突：路径一占比应 > 70%
        - 中冲突：路径一占比应 40%~70%
        - 强冲突：路径一占比应 < 40%，路径三占比应明显更高
        """
        stats = {}
        
        for level in ['weak', 'medium', 'strong']:
            samples = [r for r in self.records if r.conflict_level == level]
            
            if not samples:
                stats[level] = {'sample_count': 0}
                continue
            
            path1_rate = len([r for r in samples if r.resolution_path == 'path1']) / len(samples)
            path2_rate = len([r for r in samples if r.resolution_path == 'path2']) / len(samples)
            path3_rate = len([r for r in samples if r.resolution_path == 'path3']) / len(samples)
            
            stats[level] = {
                'sample_count': len(samples),
                'path1_rate': path1_rate,
                'path2_rate': path2_rate,
                'path3_rate': path3_rate,
                'validation': {
                    'weak': path1_rate > 0.7,
                    'medium': 0.4 <= path1_rate <= 0.7,
                    'strong': path1_rate < 0.4 and path3_rate > 0.2
                }.get(level, None)
            }
        
        return stats


# ==================== 补充2：冲突场景的情绪指标过滤 ====================

@dataclass
class SentimentCheckResult:
    """情绪检查结果"""
    is_sentiment_driven: bool              # 是否为情绪驱动
    fear_greed_index: Optional[int]        # 恐惧贪婪指数
    sentiment_type: str                    # 'fear' / 'greed' / 'neutral'
    confidence: float                      # 判断确信度 0-1
    volume_spike_detected: bool            # 是否检测到成交量异常
    wick_ratio: Optional[float]            # 插针比例（影线/实体）
    adjustment_suggestion: str             # 参数调整建议


class SentimentFilter:
    """
    情绪指标过滤器
    
    用途：
    1. 判断冲突是否主要由情绪驱动
    2. 对情绪驱动冲突调整等待窗口参数
    3. 降低假信号干扰
    
    BTC市场的跨周期冲突有时是情绪驱动的（恐慌/贪婪），
    纯技术面的冲突与情绪驱动的冲突，其解除时间和路径分布有显著差异。
    """
    
    # 极端情绪阈值
    EXTREME_FEAR_THRESHOLD = 20     # <20 极度恐惧
    EXTREME_GREED_THRESHOLD = 80    # >80 极度贪婪
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
    
    def check_sentiment_driven(
        self,
        context: Optional[ConflictContext] = None,
        fear_greed_index: Optional[int] = None,
        volume_history: Optional[np.ndarray] = None,
        price_history: Optional[np.ndarray] = None,
        high_history: Optional[np.ndarray] = None,
        low_history: Optional[np.ndarray] = None
    ) -> SentimentCheckResult:
        """
        判断当前冲突是否主要由情绪驱动
        
        情绪驱动冲突的特征：
        1. 恐惧贪婪指数处于极端区间（<20 或 >80）
        2. 成交量在冲突开始后24小时内急剧放大后骤然萎缩
        3. 价格在冲突期间出现明显插针（上下影线 > 实体 × 3）
        
        Args:
            context: 冲突上下文
            fear_greed_index: 恐惧贪婪指数 (0-100, 0=极度恐惧)
            volume_history: 近期成交量历史（用于检测异常）
            price_history: 收盘价历史
            high_history: 最高价历史
            low_history: 最低价历史
        
        Returns:
            SentimentCheckResult: 情绪检查结果
        """
        signals = []  # 收集情绪驱动信号
        
        # 特征1：恐惧贪婪指数极端
        sentiment_type = 'neutral'
        if fear_greed_index is not None:
            if fear_greed_index < self.EXTREME_FEAR_THRESHOLD:
                signals.append('extreme_fear')
                sentiment_type = 'fear'
            elif fear_greed_index > self.EXTREME_GREED_THRESHOLD:
                signals.append('extreme_greed')
                sentiment_type = 'greed'
        
        # 特征2：成交量异常（急剧放大后萎缩）
        volume_spike = False
        if volume_history is not None and len(volume_history) >= 24:
            recent_vol = volume_history[-6:]
            baseline_vol = volume_history[-24:-6]
            
            recent_avg = np.mean(recent_vol)
            baseline_avg = np.mean(baseline_vol)
            
            # 近6根K线成交量比前期放大>2倍后快速萎缩
            if recent_avg > baseline_avg * 2:
                # 检查是否开始萎缩
                if len(recent_vol) >= 3:
                    vol_trend = recent_vol[-1] / np.mean(recent_vol[:-1]) if np.mean(recent_vol[:-1]) > 0 else 0
                    if vol_trend < 0.7:  # 萎缩至前期峰值的70%以下
                        signals.append('volume_spike_and_collapse')
                        volume_spike = True
        
        # 特征3：插针（影线远大于实体）
        wick_ratio = None
        if price_history is not None and high_history is not None and low_history is not None:
            if len(price_history) >= 1:
                body = abs(price_history[-1] - price_history[-2]) if len(price_history) >= 2 else abs(high_history[-1] - low_history[-1])
                upper_wick = high_history[-1] - max(price_history[-1], price_history[-2]) if len(price_history) >= 2 else 0
                lower_wick = min(price_history[-1], price_history[-2]) - low_history[-1] if len(price_history) >= 2 else 0
                total_wick = upper_wick + lower_wick
                
                if body > 0:
                    wick_ratio = total_wick / body
                    if wick_ratio > 3:  # 影线 > 实体 × 3
                        signals.append('large_wick')
        
        # 综合判断
        is_sentiment_driven = len(signals) >= 1
        confidence = min(len(signals) / 3.0, 1.0)  # 最多3个信号
        
        # 生成调整建议
        adjustment = self._generate_adjustment_suggestion(
            is_sentiment_driven, signals, sentiment_type
        )
        
        return SentimentCheckResult(
            is_sentiment_driven=is_sentiment_driven,
            fear_greed_index=fear_greed_index,
            sentiment_type=sentiment_type,
            confidence=confidence,
            volume_spike_detected=volume_spike,
            wick_ratio=wick_ratio,
            adjustment_suggestion=adjustment
        )
    
    def _generate_adjustment_suggestion(
        self,
        is_sentiment_driven: bool,
        signals: List[str],
        sentiment_type: str
    ) -> str:
        """生成参数调整建议"""
        if not is_sentiment_driven:
            return "无情绪干扰，使用标准参数"
        
        suggestions = []
        
        # 根据情绪类型添加特定建议
        if sentiment_type == 'fear':
            suggestions.append("恐慌情绪主导，等待窗口缩短30%，情绪驱动冲突解除更快")
        elif sentiment_type == 'greed':
            suggestions.append("贪婪情绪主导，警惕假突破，企稳门槛提高5分")
        
        if 'volume_spike_and_collapse' in signals:
            suggestions.append("成交量异常波动，谨慎入场，首仓降低10%")
        
        if 'large_wick' in signals:
            suggestions.append("明显插针，等待更多确认，路径一企稳门槛提高至75分")
        
        return " | ".join(suggestions) if suggestions else "使用标准参数"
    
    def get_adjusted_parameters(
        self,
        sentiment_result: SentimentCheckResult,
        base_time_limit: int,
        base_threshold: int,
        base_position_pct: float
    ) -> Dict[str, Any]:
        """
        根据情绪检查结果调整参数
        
        情绪驱动冲突的等待窗口调整：
        - 时间上限缩短 30%（情绪驱动的冲突解除更快）
        - 路径一触发后首仓不降级（情绪驱动回调后趋势更强）
        
        Args:
            sentiment_result: 情绪检查结果
            base_time_limit: 基础等待窗口上限
            base_threshold: 基础企稳门槛
            base_position_pct: 基础首仓比例
        
        Returns:
            调整后的参数
        """
        if not sentiment_result.is_sentiment_driven:
            return {
                'time_limit': base_time_limit,
                'threshold': base_threshold,
                'position_pct': base_position_pct,
                'adjusted': False
            }
        
        # 情绪驱动时的调整
        adjusted_time = int(base_time_limit * 0.7)  # 缩短30%
        adjusted_threshold = base_threshold
        adjusted_position = base_position_pct
        
        # 根据情绪类型微调
        if sentiment_result.sentiment_type == 'fear':
            # 恐惧时首仓可保持（回调后趋势更强）
            pass
        elif sentiment_result.sentiment_type == 'greed':
            # 贪婪时提高门槛、降低仓位
            adjusted_threshold = base_threshold + 5
            adjusted_position = base_position_pct * 0.9
        
        return {
            'time_limit': adjusted_time,
            'threshold': adjusted_threshold,
            'position_pct': adjusted_position,
            'adjusted': True,
            'reason': sentiment_result.adjustment_suggestion
        }


# ==================== 补充3：复盘模板扩展 ====================

def generate_conflict_review_template(record: ConflictRecord) -> str:
    """
    生成冲突专属复盘报告模板
    
    用于在冲突相关的交易中，额外记录以下内容：
    - 冲突最初发现时的强度评分
    - 实际等待K线根数
    - 最终走的路径
    - 等待期间4H MACD变化
    - 否定信号情况
    - 改进点记录
    
    Args:
        record: 冲突历史记录
    
    Returns:
        格式化的复盘报告文本
    """
    template = f"""
========================================
跨周期冲突复盘报告
========================================
冲突ID: {record.conflict_id}
发生时间: {record.timestamp.strftime('%Y-%m-%d %H:%M') if record.timestamp else 'N/A'}

【冲突评估】
[×] 冲突最初发现时的强度评分: {record.conflict_score} 分 ({record.conflict_level} 级)
[×] 实际等待了多少根 1H K线: {record.wait_bars_actual} / {record.wait_bars_limit}
[×] 最终走了哪条路径: {_get_path_chinese_name(record.resolution_path)}
[×] 路径一解除时的企稳打分: {record.entry_score_at_resolution or 'N/A'} 分 (门槛 {record.entry_threshold or 'N/A'} 分)
[×] 等待期间 4H MACD 最大缩短幅度: {f'{record.macd_4h_max_shrink_pct*100:.1f}%' if record.macd_4h_max_shrink_pct else 'N/A'}
[×] 是否出现了策略文档预警的"三类否定信号"之一: {'是' if record.denial_signal_triggered else '否'}
    {f'否定信号类型: {record.denial_signal_type}' if record.denial_signal_triggered else ''}

【情绪指标】
[×] 是否为情绪驱动的冲突: {'是' if record.sentiment_driven else '否'}
[×] 恐惧贪婪指数: {record.fear_greed_index or 'N/A'}

【入场信息】
[×] 入场价格: {record.entry_price or 'N/A'}
[×] 实际仓位: {f'{record.position_pct*100:.0f}%' if record.position_pct else 'N/A'}

【事后验证】
[×] 入场后 {record.verification_bars} 根K线价格变化: {f'{record.subsequent_price_change*100:.2f}%' if record.subsequent_price_change is not None else '待验证'}
[×] 判断是否正确: {_get_correctness_str(record.was_correct)}

【改进记录】
本次冲突处理中最主要的改进点: {record.improvement_notes or '待填写'}

========================================
"""
    return template


def _get_path_chinese_name(path: str) -> str:
    """获取路径的中文名称"""
    path_names = {
        'path1': '路径一（自然解除）',
        'path2': '路径二（超时放弃）',
        'path3': '路径三（转空机会）'
    }
    return path_names.get(path, path)


def _get_correctness_str(was_correct: Optional[bool]) -> str:
    """获取正确性字符串"""
    if was_correct is None:
        return '待验证'
    return '正确 ✓' if was_correct else '错误 ✗'


# ==================== 冲突历史记录管理器 ====================

class ConflictHistoryManager:
    """
    冲突历史记录管理器
    
    功能：
    1. 管理冲突记录的存储和检索
    2. 支持持久化到文件
    3. 提供统计分析接口
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Args:
            storage_path: 记录存储路径（可选，用于持久化）
        """
        self.storage_path = storage_path
        self.records: List[ConflictRecord] = []
        self.learner = ConflictLearner()
    
    def record_conflict(
        self,
        context: ConflictContext,
        resolution_result: ResolutionResult,
        entry_score: Optional[int] = None,
        entry_price: Optional[float] = None
    ) -> ConflictRecord:
        """
        记录一次冲突
        
        Args:
            context: 冲突上下文
            resolution_result: 解除结果
            entry_score: 入场企稳打分
            entry_price: 入场价格
        
        Returns:
            创建的冲突记录
        """
        record = ConflictRecord(
            conflict_id=context.conflict_id,
            timestamp=context.detected_time,
            conflict_level=context.score.intensity.value,
            conflict_score=context.score.total_score,
            score_dimensions=context.score.dimensions,
            wait_bars_actual=context.waiting_window.bars_elapsed,
            wait_bars_limit=context.waiting_window.time_limit,
            resolution_path=resolution_result.path.value,
            resolution_time=datetime.now() if resolution_result.resolved else None,
            entry_score_at_resolution=entry_score,
            entry_threshold=resolution_result.stabilization_threshold if hasattr(resolution_result, 'stabilization_threshold') else None,
            entry_price=entry_price,
            position_pct=resolution_result.position_pct if resolution_result.position_pct else None
        )
        
        self.records.append(record)
        self.learner.add_record(record)
        
        return record
    
    def verify_outcome(
        self,
        conflict_id: str,
        subsequent_price_change: float,
        was_correct: bool,
        improvement_notes: str = ""
    ) -> Optional[ConflictRecord]:
        """
        事后验证冲突处理结果
        
        Args:
            conflict_id: 冲突ID
            subsequent_price_change: 后续价格变化（百分比）
            was_correct: 判断是否正确
            improvement_notes: 改进点记录
        
        Returns:
            更新后的记录，如果未找到则返回None
        """
        for record in self.records:
            if record.conflict_id == conflict_id:
                record.subsequent_price_change = subsequent_price_change
                record.was_correct = was_correct
                record.improvement_notes = improvement_notes
                return record
        
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.learner.suggest_parameter_adjustment()
    
    def get_level_statistics(self) -> Dict[str, Any]:
        """获取各冲突等级的统计信息"""
        return self.learner.get_level_statistics()
    
    def export_to_json(self, filepath: str) -> None:
        """导出记录到JSON文件"""
        import json
        
        data = [record.to_dict() for record in self.records]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    def import_from_json(self, filepath: str) -> int:
        """从JSON文件导入记录，返回导入数量"""
        import json
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for item in data:
            record = ConflictRecord(
                conflict_id=item['conflict_id'],
                timestamp=datetime.fromisoformat(item['timestamp']) if item.get('timestamp') else None,
                conflict_level=item['conflict_level'],
                conflict_score=item['conflict_score'],
                score_dimensions=[],  # 简化导入，不包含详细维度
                wait_bars_actual=item['wait_bars_actual'],
                wait_bars_limit=item['wait_bars_limit'],
                resolution_path=item['resolution_path'],
                resolution_time=datetime.fromisoformat(item['resolution_time']) if item.get('resolution_time') else None,
                entry_score_at_resolution=item.get('entry_score_at_resolution'),
                entry_threshold=item.get('entry_threshold'),
                entry_price=item.get('entry_price'),
                position_pct=item.get('position_pct'),
                subsequent_price_change=item.get('subsequent_price_change'),
                was_correct=item.get('was_correct'),
                verification_bars=item.get('verification_bars', 24),
                macd_4h_max_shrink_pct=item.get('macd_4h_max_shrink_pct'),
                denial_signal_triggered=item.get('denial_signal_triggered', False),
                denial_signal_type=item.get('denial_signal_type'),
                improvement_notes=item.get('improvement_notes', ''),
                sentiment_driven=item.get('sentiment_driven', False),
                fear_greed_index=item.get('fear_greed_index')
            )
            self.records.append(record)
            self.learner.add_record(record)
            count += 1
        
        return count
