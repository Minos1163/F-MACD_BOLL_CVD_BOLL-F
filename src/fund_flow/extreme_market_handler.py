"""
极端行情处理器
针对插针、黑天鹅、单边加速行情的完整应对系统

核心功能：
- 三级熔断机制（黄色/红色/黑色预警）
- 黑天鹅事件检测与四阶段应对
- 单边加速行情检测与四阶段应对
- 动态恢复评估系统
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import numpy as np


# ==================== 枚举定义 ====================

class CircuitBreakerLevel(Enum):
    """熔断级别"""
    NORMAL = "normal"           # 正常运行
    YELLOW = "yellow"           # 一级熔断：系统切换
    RED = "red"                 # 二级熔断：停止新仓
    BLACK = "black"             # 三级熔断：全面清仓


class MarketEventType(Enum):
    """市场事件类型"""
    NORMAL = "normal"                       # 正常行情
    ACCELERATION = "acceleration"           # 单边加速
    BLACK_SWAN_EMOTIONAL = "black_swan_emotional"   # 情绪性黑天鹅
    BLACK_SWAN_SYSTEMIC = "black_swan_systemic"     # 系统性黑天鹅


class RecoveryPhase(Enum):
    """恢复阶段"""
    NOT_IN_RECOVERY = "not_in_recovery"     # 未在恢复期
    PHASE_1_IMPACT = "phase_1_impact"        # 第一阶段：冲击发生
    PHASE_2_DIGEST = "phase_2_digest"        # 第二阶段：震荡消化
    PHASE_3_REBUILD = "phase_3_rebuild"      # 第三阶段：结构重建
    PHASE_4_RESTART = "phase_4_restart"      # 第四阶段：系统重启


class ActionRequired(Enum):
    """需要执行的动作"""
    NONE = "none"                   # 无需特殊动作
    SWITCH_MODE = "switch_mode"     # 切换加速模式
    REDUCE_50 = "reduce_50"         # 减仓50%
    CLOSE_ALL = "close_all"         # 清仓
    WAIT_OBSERVE = "wait_observe"   # 等待观察
    TRIAL_ENTRY = "trial_entry"     # 试探入场
    NORMAL_RESUME = "normal_resume" # 正常恢复


# ==================== 数据结构 ====================

@dataclass
class AccelerationState:
    """单边加速状态"""
    is_accelerating: bool = False
    consecutive_bars: int = 0          # 连续单向K线数
    peak_warning: bool = False         # 峰值预警
    deviation_from_ema21: float = 0.0  # 偏离EMA21百分比
    current_stage: int = 1             # 当前阶段 1-4
    entry_mode: str = "normal"         # 入场模式: normal/acceleration
    
    # 加速模式参数
    position_cap: float = 0.70         # 仓位上限70%
    stop_loss_type: str = "tight"      # 止损类型: normal/tight
    first_position_ratio: float = 0.50 # 首仓比例50%


@dataclass
class BlackSwanState:
    """黑天鹅状态"""
    is_active: bool = False
    event_type: MarketEventType = MarketEventType.NORMAL
    start_time: Optional[datetime] = None
    current_phase: RecoveryPhase = RecoveryPhase.NOT_IN_RECOVERY
    
    # 冲击数据
    drop_pct: float = 0.0              # 跌幅百分比
    volume_spike: float = 1.0          # 量能倍数
    external_event: bool = False       # 是否有外部事件
    
    # 恢复数据
    bars_since_event: int = 0          # 事件后K线数
    price_stabilized: bool = False     # 价格是否企稳
    volume_normalized: bool = False    # 量能是否回归正常
    structure_rebuilt: bool = False    # 结构是否重建
    
    # 入场参数
    trial_position_pct: float = 0.0    # 试探仓位
    recovery_threshold: int = 70       # 恢复期企稳门槛


@dataclass
class CircuitBreakerState:
    """熔断状态"""
    current_level: CircuitBreakerLevel = CircuitBreakerLevel.NORMAL
    trigger_reason: str = ""
    trigger_time: Optional[datetime] = None
    triggered_conditions: List[str] = field(default_factory=list)
    
    # 自动执行动作
    action_required: ActionRequired = ActionRequired.NONE
    position_cap: float = 1.0          # 仓位上限
    stop_new_positions: bool = False   # 禁止新开仓
    force_close: bool = False          # 强制清仓


@dataclass
class ExtremeMarketResult:
    """极端行情检测结果"""
    # 状态
    circuit_breaker: CircuitBreakerState
    acceleration: AccelerationState
    black_swan: BlackSwanState
    
    # 诊断
    market_event_type: MarketEventType
    action_required: ActionRequired
    
    # 参数调整
    position_multiplier: float = 1.0   # 仓位乘数
    entry_threshold: int = 70          # 入场门槛
    stop_loss_multiplier: float = 1.0  # 止损宽度乘数
    
    # 详细信息
    details: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def is_trading_allowed(self) -> bool:
        """是否允许交易"""
        if self.circuit_breaker.force_close:
            return False
        if self.circuit_breaker.current_level == CircuitBreakerLevel.BLACK:
            return False
        if self.black_swan.is_active and self.black_swan.current_phase in [
            RecoveryPhase.PHASE_1_IMPACT, 
            RecoveryPhase.PHASE_2_DIGEST
        ]:
            return False
        return True


# ==================== 核心检测器 ====================

class ExtremeMarketDetector:
    """
    极端行情检测器
    
    三级熔断触发条件：
    - 一级（黄色）：连续3根1H K线涨跌幅 > ATR×1.5 或 15m量能放大
    - 二级（红色）：单根跌幅>5% 或 偏差>5% 或 量能>MA20×500%
    - 三级（黑色）：4根内累计跌幅>8% + 量能>MA20×500% + 外部事件
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
        
        # 状态追踪
        self._acceleration_state = AccelerationState()
        self._black_swan_state = BlackSwanState()
        self._circuit_state = CircuitBreakerState()
        
        # 历史记录
        self._event_history: List[Dict] = []
        self._recovery_trades_count = 0
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            # ATR倍数阈值
            "atr_multiplier_level1": 1.5,   # 一级熔断ATR倍数
            "atr_multiplier_level2": 2.0,   # 二级熔断ATR倍数
            "atr_multiplier_level3": 3.0,   # 峰值预警ATR倍数
            
            # 连续K线数
            "consecutive_bars_acceleration": 4,  # 加速判定K线数
            "consecutive_bars_warning": 3,       # 警告K线数
            
            # 价格偏离
            "ema_deviation_acceleration": 0.03,  # 加速偏离 3%
            "ema_deviation_warning": 0.05,       # 峰值预警偏离 5%
            
            # 量能阈值
            "volume_spike_level1": 1.5,     # 一级量能倍数
            "volume_spike_level2": 3.0,     # 二级量能倍数
            "volume_spike_level3": 5.0,     # 三级量能倍数（500%）
            
            # 黑天鹅阈值
            "black_swan_drop_threshold": 0.08,  # 黑天鹅跌幅 8%
            "black_swan_bars": 4,               # 黑天鹅K线数
            "black_swan_volume_spike": 5.0,     # 黑天鹅量能倍数
            
            # 恢复参数
            "recovery_hours_black_swan": 48,          # 黑天鹅恢复小时数
            "recovery_hours_systemic": 336,           # 系统性黑天鹅恢复小时数（2周）
            "recovery_trades_limit": 5,               # 恢复期交易笔数限制
            "recovery_position_cap": 0.20,            # 恢复期仓位上限
            "recovery_entry_threshold": 80,           # 恢复期入场门槛
            
            # 峰值预警
            "peak_warning_deviation": 0.05,    # 峰值预警偏离
            "peak_warning_atr_multiplier": 3.0,  # 峰值预警ATR倍数
        }
    
    # ==================== 核心检测入口 ====================
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray,
                external_events: Optional[List[Dict]] = None,
                current_time: Optional[datetime] = None) -> ExtremeMarketResult:
        """
        完整极端行情分析
        
        Args:
            close, high, low, volume: OHLCV数据
            external_events: 外部事件列表 [{"time": datetime, "type": str, "severity": str}]
            current_time: 当前时间
        """
        current_time = current_time or datetime.now()
        
        # 1. 计算基础指标
        atr = self._calculate_atr(high, low, close, period=14)
        volume_ma = self._calculate_volume_ma(volume, period=20)
        ema21 = self._calculate_ema(close, period=21)
        ema55 = self._calculate_ema(close, period=55)
        
        # 2. 检测三级熔断
        circuit_result = self._detect_circuit_breaker(
            close, high, low, volume, atr, volume_ma, ema21, 
            external_events, current_time
        )
        
        # 3. 检测单边加速行情
        acceleration_result = self._detect_acceleration(
            close, high, low, volume, atr, volume_ma, ema21,
            current_time
        )
        
        # 4. 检测黑天鹅事件
        black_swan_result = self._detect_black_swan(
            close, high, low, volume, atr, volume_ma, ema21, ema55,
            external_events, current_time
        )
        
        # 5. 判断市场事件类型
        market_event_type = self._determine_market_event(
            circuit_result, acceleration_result, black_swan_result
        )
        
        # 6. 决定需要执行的动作
        action_required = self._determine_action(
            circuit_result, acceleration_result, black_swan_result, market_event_type
        )
        
        # 7. 计算参数调整
        position_multiplier, entry_threshold, stop_loss_multiplier = self._calculate_adjustments(
            circuit_result, acceleration_result, black_swan_result, market_event_type
        )
        
        # 8. 更新状态
        self._circuit_state = circuit_result
        self._acceleration_state = acceleration_result
        self._black_swan_state = black_swan_result
        
        # 9. 生成警告信息
        warnings = self._generate_warnings(
            circuit_result, acceleration_result, black_swan_result
        )
        
        return ExtremeMarketResult(
            circuit_breaker=circuit_result,
            acceleration=acceleration_result,
            black_swan=black_swan_result,
            market_event_type=market_event_type,
            action_required=action_required,
            position_multiplier=position_multiplier,
            entry_threshold=entry_threshold,
            stop_loss_multiplier=stop_loss_multiplier,
            details={
                "atr": atr,
                "volume_ma": volume_ma,
                "ema21": ema21,
                "ema55": ema55,
                "current_price": close[-1],
                "volume_ratio": volume[-1] / volume_ma if volume_ma > 0 else 1.0,
                "ema21_deviation": abs(close[-1] - ema21) / ema21 if ema21 > 0 else 0,
            },
            warnings=warnings
        )
    
    # ==================== 三级熔断检测 ====================
    
    def _detect_circuit_breaker(self,
                                close: np.ndarray,
                                high: np.ndarray,
                                low: np.ndarray,
                                volume: np.ndarray,
                                atr: float,
                                volume_ma: float,
                                ema21: float,
                                external_events: Optional[List[Dict]],
                                current_time: datetime) -> CircuitBreakerState:
        """检测三级熔断"""
        
        state = CircuitBreakerState()
        triggered_conditions = []
        
        # 计算关键指标
        current_price = close[-1]
        bar_change = abs(close[-1] - close[-2])
        bar_change_pct = bar_change / close[-2] if close[-2] > 0 else 0
        volume_ratio = volume[-1] / volume_ma if volume_ma > 0 else 1.0
        ema_deviation = abs(current_price - ema21) / ema21 if ema21 > 0 else 0
        
        # 检测连续单向K线
        consecutive_unidirectional = self._count_consecutive_unidirectional(close)
        
        # 计算累计跌幅
        cumulative_drop = self._calculate_cumulative_drop(close, bars=4)
        
        # 判断外部事件
        has_external_event = self._check_external_event(external_events, current_time)
        
        # ========== 三级熔断判定（黑色预警）==========
        if (abs(cumulative_drop) > self.config["black_swan_drop_threshold"] and
            volume_ratio > self.config["black_swan_volume_spike"] and
            has_external_event):
            
            state.current_level = CircuitBreakerLevel.BLACK
            state.trigger_reason = "黑天鹅三级熔断：4根内跌幅>{:.1%} + 量能>{:.0f}倍 + 外部事件".format(
                abs(cumulative_drop), volume_ratio
            )
            state.trigger_time = current_time
            triggered_conditions.append("black_swan_triple_condition")
            state.action_required = ActionRequired.CLOSE_ALL
            state.position_cap = 0.0
            state.stop_new_positions = True
            state.force_close = True
            
            return state
        
        # ========== 二级熔断判定（红色预警）==========
        level2_triggers = []
        
        # 条件1：单根跌幅超过5%
        if bar_change_pct > 0.05:
            level2_triggers.append(f"单根跌幅{bar_change_pct:.1%}")
        
        # 条件2：价格偏离EMA21超过5%
        if ema_deviation > self.config["ema_deviation_warning"]:
            level2_triggers.append(f"EMA21偏离{ema_deviation:.1%}")
        
        # 条件3：量能突放超过500%
        if volume_ratio > self.config["volume_spike_level3"]:
            level2_triggers.append(f"量能突放{volume_ratio:.1f}倍")
        
        if level2_triggers:
            state.current_level = CircuitBreakerLevel.RED
            state.trigger_reason = "二级熔断：" + " | ".join(level2_triggers)
            state.trigger_time = current_time
            triggered_conditions.extend(level2_triggers)
            state.action_required = ActionRequired.REDUCE_50
            state.position_cap = 0.5
            state.stop_new_positions = True
            state.force_close = False
            
            return state
        
        # ========== 一级熔断判定（黄色预警）==========
        level1_triggers = []
        
        # 条件1：连续3根K线涨跌幅 > ATR×1.5
        if consecutive_unidirectional >= self.config["consecutive_bars_warning"]:
            avg_change = self._calculate_avg_bar_change(close, consecutive_unidirectional)
            if avg_change > atr * self.config["atr_multiplier_level1"]:
                level1_triggers.append(f"连续{consecutive_unidirectional}根K线加速")
        
        # 条件2：15m量能连续放大
        if len(volume) >= 12:  # 至少12根15m K线
            volume_escalation = self._check_volume_escalation(volume[-12:])
            if volume_escalation:
                level1_triggers.append("量能阶梯式放大")
        
        if level1_triggers:
            state.current_level = CircuitBreakerLevel.YELLOW
            state.trigger_reason = "一级熔断：" + " | ".join(level1_triggers)
            state.trigger_time = current_time
            triggered_conditions.extend(level1_triggers)
            state.action_required = ActionRequired.SWITCH_MODE
            state.position_cap = 0.7
            state.stop_new_positions = False
            state.force_close = False
            
            return state
        
        # 正常状态
        state.current_level = CircuitBreakerLevel.NORMAL
        state.trigger_reason = "正常运行"
        state.action_required = ActionRequired.NONE
        state.position_cap = 1.0
        
        return state
    
    # ==================== 单边加速检测 ====================
    
    def _detect_acceleration(self,
                             close: np.ndarray,
                             high: np.ndarray,
                             low: np.ndarray,
                             volume: np.ndarray,
                             atr: float,
                             volume_ma: float,
                             ema21: float,
                             current_time: datetime) -> AccelerationState:
        """检测单边加速行情"""
        
        state = AccelerationState()
        
        # 计算连续单向K线数
        consecutive_bars = self._count_consecutive_unidirectional(close)
        state.consecutive_bars = consecutive_bars
        
        # 计算EMA偏离
        current_price = close[-1]
        ema_deviation = (current_price - ema21) / ema21 if ema21 > 0 else 0
        state.deviation_from_ema21 = ema_deviation
        
        # 判断是否加速
        # 条件1：连续4根以上无回踩
        # 条件2：每根涨跌幅 > ATR×1.5
        avg_change = self._calculate_avg_bar_change(close, min(consecutive_bars, 4))
        
        is_accelerating = (
            consecutive_bars >= self.config["consecutive_bars_acceleration"] and
            avg_change > atr * self.config["atr_multiplier_level1"]
        )
        
        state.is_accelerating = is_accelerating
        
        # 判断峰值预警
        peak_warning = (
            abs(ema_deviation) > self.config["peak_warning_deviation"] or
            self._has_extreme_bar(close, high, low, atr, multiplier=3.0)
        )
        state.peak_warning = peak_warning
        
        # 判断阶段
        if peak_warning:
            state.current_stage = 3  # 峰值预警阶段
            state.entry_mode = "peak_warning"
            state.position_cap = 0.5
        elif is_accelerating:
            state.current_stage = 2  # 加速阶段
            state.entry_mode = "acceleration"
            state.position_cap = 0.7
            state.stop_loss_type = "tight"
            state.first_position_ratio = 0.5
        else:
            state.current_stage = 1  # 正常阶段
            state.entry_mode = "normal"
        
        return state
    
    # ==================== 黑天鹅检测 ====================
    
    def _detect_black_swan(self,
                           close: np.ndarray,
                           high: np.ndarray,
                           low: np.ndarray,
                           volume: np.ndarray,
                           atr: float,
                           volume_ma: float,
                           ema21: float,
                           ema55: float,
                           external_events: Optional[List[Dict]],
                           current_time: datetime) -> BlackSwanState:
        """检测黑天鹅事件"""
        
        state = BlackSwanState()
        
        # 如果已经在恢复期，更新恢复状态
        if self._black_swan_state.is_active:
            state = self._update_black_swan_recovery(
                close, high, low, volume, ema21, ema55,
                volume_ma, current_time
            )
            return state
        
        # 检测新的黑天鹅事件
        cumulative_drop = self._calculate_cumulative_drop(close, bars=4)
        volume_ratio = volume[-1] / volume_ma if volume_ma > 0 else 1.0
        has_external_event = self._check_external_event(external_events, current_time)
        
        # 黑天鹅判定条件
        is_black_swan = (
            abs(cumulative_drop) > self.config["black_swan_drop_threshold"] and
            volume_ratio > self.config["black_swan_volume_spike"] and
            has_external_event
        )
        
        if is_black_swan:
            state.is_active = True
            state.start_time = current_time
            state.current_phase = RecoveryPhase.PHASE_1_IMPACT
            state.drop_pct = abs(cumulative_drop)
            state.volume_spike = volume_ratio
            state.external_event = has_external_event
            
            # 判断黑天鹅类型
            state.event_type = self._determine_black_swan_type(
                external_events, cumulative_drop
            )
            
            # 记录事件
            self._event_history.append({
                "time": current_time,
                "type": "black_swan",
                "subtype": state.event_type.value,
                "drop_pct": abs(cumulative_drop),
                "volume_spike": volume_ratio
            })
        
        return state
    
    def _update_black_swan_recovery(self,
                                    close: np.ndarray,
                                    high: np.ndarray,
                                    low: np.ndarray,
                                    volume: np.ndarray,
                                    ema21: float,
                                    ema55: float,
                                    volume_ma: float,
                                    current_time: datetime) -> BlackSwanState:
        """更新黑天鹅恢复状态"""
        
        state = self._black_swan_state
        state.bars_since_event += 1
        
        # 计算时间差（小时）
        hours_since_event = 0
        if state.start_time:
            hours_since_event = (current_time - state.start_time).total_seconds() / 3600
        
        # 计算恢复指标
        volume_ratio = volume[-1] / volume_ma if volume_ma > 0 else 1.0
        current_price = close[-1]
        
        # 更新阶段
        if hours_since_event < 0.5:  # 0-30分钟
            state.current_phase = RecoveryPhase.PHASE_1_IMPACT
            
        elif hours_since_event < 4:  # 30分钟-4小时
            state.current_phase = RecoveryPhase.PHASE_2_DIGEST
            # 检查价格是否开始稳定
            state.price_stabilized = self._check_price_stabilization(close[-4:])
            
        elif hours_since_event < 48:  # 4-48小时
            state.current_phase = RecoveryPhase.PHASE_3_REBUILD
            
            # 检查恢复条件
            state.volume_normalized = volume_ratio < 1.5
            state.structure_rebuilt = self._check_structure_rebuilt(
                close, ema21, ema55, volume_ratio
            )
            
            # 判断是否可以试探入场
            if state.volume_normalized and state.structure_rebuilt:
                state.trial_position_pct = 0.20
                state.recovery_threshold = 80
                
        else:  # 48小时后
            state.current_phase = RecoveryPhase.PHASE_4_RESTART
            
            # 判断是否可以正常恢复
            if (state.event_type == MarketEventType.BLACK_SWAN_EMOTIONAL and
                state.volume_normalized and state.structure_rebuilt):
                state.trial_position_pct = 0.40
                state.recovery_threshold = 70
            else:
                state.trial_position_pct = 0.10
                state.recovery_threshold = 85
        
        return state
    
    # ==================== 辅助判断方法 ====================
    
    def _determine_market_event(self,
                                circuit: CircuitBreakerState,
                                acceleration: AccelerationState,
                                black_swan: BlackSwanState) -> MarketEventType:
        """判断市场事件类型"""
        
        if black_swan.is_active:
            return black_swan.event_type
        
        if acceleration.is_accelerating:
            return MarketEventType.ACCELERATION
        
        return MarketEventType.NORMAL
    
    def _determine_action(self,
                          circuit: CircuitBreakerState,
                          acceleration: AccelerationState,
                          black_swan: BlackSwanState,
                          market_event: MarketEventType) -> ActionRequired:
        """决定需要执行的动作"""
        
        # 黑天鹅优先级最高
        if black_swan.is_active:
            if black_swan.current_phase == RecoveryPhase.PHASE_1_IMPACT:
                return ActionRequired.CLOSE_ALL
            elif black_swan.current_phase == RecoveryPhase.PHASE_2_DIGEST:
                return ActionRequired.WAIT_OBSERVE
            elif black_swan.current_phase == RecoveryPhase.PHASE_3_REBUILD:
                if black_swan.trial_position_pct > 0:
                    return ActionRequired.TRIAL_ENTRY
                return ActionRequired.WAIT_OBSERVE
            else:  # PHASE_4_RESTART
                return ActionRequired.NORMAL_RESUME
        
        # 熔断级别次之
        if circuit.current_level == CircuitBreakerLevel.BLACK:
            return ActionRequired.CLOSE_ALL
        elif circuit.current_level == CircuitBreakerLevel.RED:
            return ActionRequired.REDUCE_50
        elif circuit.current_level == CircuitBreakerLevel.YELLOW:
            return ActionRequired.SWITCH_MODE
        
        # 加速行情
        if acceleration.peak_warning:
            return ActionRequired.REDUCE_50
        elif acceleration.is_accelerating:
            return ActionRequired.SWITCH_MODE
        
        return ActionRequired.NONE
    
    def _calculate_adjustments(self,
                               circuit: CircuitBreakerState,
                               acceleration: AccelerationState,
                               black_swan: BlackSwanState,
                               market_event: MarketEventType) -> Tuple[float, int, float]:
        """计算参数调整"""
        
        position_multiplier = 1.0
        entry_threshold = 70
        stop_loss_multiplier = 1.0
        
        # 黑天鹅调整
        if black_swan.is_active:
            if black_swan.current_phase == RecoveryPhase.PHASE_3_REBUILD:
                position_multiplier = 0.5
                entry_threshold = black_swan.recovery_threshold
                stop_loss_multiplier = 1.2
            elif black_swan.current_phase == RecoveryPhase.PHASE_4_RESTART:
                position_multiplier = 0.5 if self._recovery_trades_count < 5 else 1.0
                entry_threshold = black_swan.recovery_threshold
                stop_loss_multiplier = 1.2
            else:
                position_multiplier = 0.0
                entry_threshold = 100
        
        # 加速行情调整
        elif acceleration.is_accelerating:
            position_multiplier = acceleration.position_cap
            if acceleration.peak_warning:
                entry_threshold = 85
                stop_loss_multiplier = 0.5  # 收紧止损
            else:
                entry_threshold = 65  # 加速期降低门槛
                stop_loss_multiplier = 0.7
        
        # 熔断调整
        elif circuit.current_level == CircuitBreakerLevel.YELLOW:
            position_multiplier = 0.7
            entry_threshold = 65
        
        return position_multiplier, entry_threshold, stop_loss_multiplier
    
    def _generate_warnings(self,
                          circuit: CircuitBreakerState,
                          acceleration: AccelerationState,
                          black_swan: BlackSwanState) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        if circuit.current_level != CircuitBreakerLevel.NORMAL:
            level_names = {
                CircuitBreakerLevel.YELLOW: "一级（黄色）",
                CircuitBreakerLevel.RED: "二级（红色）",
                CircuitBreakerLevel.BLACK: "三级（黑色）"
            }
            warnings.append(f"⚠️ 熔断{level_names[circuit.current_level]}: {circuit.trigger_reason}")
        
        if acceleration.peak_warning:
            warnings.append(f"⚠️ 峰值预警：EMA21偏离{acceleration.deviation_from_ema21:.1%}，禁止追高")
        elif acceleration.is_accelerating:
            warnings.append(f"⚡ 加速模式：连续{acceleration.consecutive_bars}根无回踩，仓位上限{acceleration.position_cap:.0%}")
        
        if black_swan.is_active:
            phase_names = {
                RecoveryPhase.PHASE_1_IMPACT: "冲击发生",
                RecoveryPhase.PHASE_2_DIGEST: "震荡消化",
                RecoveryPhase.PHASE_3_REBUILD: "结构重建",
                RecoveryPhase.PHASE_4_RESTART: "系统重启"
            }
            warnings.append(f"🚨 黑天鹅事件({black_swan.event_type.value}): {phase_names[black_swan.current_phase]}阶段")
        
        return warnings
    
    # ==================== 技术指标计算 ====================
    
    def _calculate_atr(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray, period: int = 14) -> float:
        """计算ATR"""
        if len(close) < period + 1:
            return 0.0
        
        tr = np.maximum(
            high[-period:] - low[-period:],
            np.maximum(
                abs(high[-period:] - close[-period-1:-1]),
                abs(low[-period:] - close[-period-1:-1])
            )
        )
        return float(np.mean(tr))
    
    def _calculate_volume_ma(self, volume: np.ndarray, period: int = 20) -> float:
        """计算成交量均线"""
        if len(volume) < period:
            return float(np.mean(volume))
        return float(np.mean(volume[-period:]))
    
    def _calculate_ema(self, data: np.ndarray, period: int = 21) -> float:
        """计算EMA"""
        if len(data) < period:
            return float(data[-1])
        
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema
    
    def _count_consecutive_unidirectional(self, close: np.ndarray) -> int:
        """计算连续单向K线数"""
        if len(close) < 2:
            return 0
        
        count = 1
        direction = 1 if close[-1] > close[-2] else -1
        
        for i in range(len(close) - 2, max(0, len(close) - 10), -1):
            current_direction = 1 if close[i+1] > close[i] else -1
            if current_direction == direction:
                count += 1
            else:
                break
        
        return count
    
    def _calculate_avg_bar_change(self, close: np.ndarray, bars: int) -> float:
        """计算平均K线变化"""
        if len(close) < bars + 1:
            return 0.0
        
        changes = np.abs(np.diff(close[-bars-1:]))
        return float(np.mean(changes))
    
    def _calculate_cumulative_drop(self, close: np.ndarray, bars: int = 4) -> float:
        """计算累计跌幅"""
        if len(close) < bars + 1:
            return 0.0
        
        return (close[-1] - close[-bars-1]) / close[-bars-1]
    
    def _has_extreme_bar(self, close: np.ndarray, high: np.ndarray, 
                         low: np.ndarray, atr: float, multiplier: float = 3.0) -> bool:
        """判断是否有极端K线"""
        if atr <= 0:
            return False
        
        bar_range = high[-1] - low[-1]
        return bar_range > atr * multiplier
    
    def _check_volume_escalation(self, volume: np.ndarray) -> bool:
        """检查量能是否阶梯式放大"""
        if len(volume) < 3:
            return False
        
        # 检查最近3根是否逐根放大
        return volume[-1] > volume[-2] > volume[-3]
    
    def _check_external_event(self, events: Optional[List[Dict]], 
                               current_time: datetime) -> bool:
        """检查是否有外部事件"""
        if not events:
            return False
        
        for event in events:
            event_time = event.get("time")
            if event_time:
                # 检查事件是否在最近1小时内
                time_diff = abs((current_time - event_time).total_seconds())
                if time_diff < 3600:  # 1小时内
                    severity = event.get("severity", "low")
                    if severity in ["high", "critical"]:
                        return True
        
        return False
    
    def _determine_black_swan_type(self, events: Optional[List[Dict]], 
                                   drop_pct: float) -> MarketEventType:
        """判断黑天鹅类型"""
        if not events:
            return MarketEventType.BLACK_SWAN_EMOTIONAL
        
        for event in events:
            event_type = event.get("type", "")
            severity = event.get("severity", "low")
            
            # 系统性事件判断
            systemic_keywords = [
                "exchange_collapse", "regulatory_ban", "stablecoin_depeg",
                "major_hack", "nation_ban", "ftx_level"
            ]
            
            if event_type in systemic_keywords or severity == "critical":
                return MarketEventType.BLACK_SWAN_SYSTEMIC
        
        return MarketEventType.BLACK_SWAN_EMOTIONAL
    
    def _check_price_stabilization(self, close: np.ndarray) -> bool:
        """检查价格是否企稳"""
        if len(close) < 2:
            return False
        
        # 检查最近K线振幅是否收窄
        ranges = [abs(close[i] - close[i-1]) / close[i-1] for i in range(1, len(close))]
        
        if len(ranges) >= 2:
            return ranges[-1] < ranges[-2] and ranges[-1] < 0.02
        
        return False
    
    def _check_structure_rebuilt(self, close: np.ndarray, ema21: float, 
                                  ema55: float, volume_ratio: float) -> bool:
        """检查结构是否重建"""
        current_price = close[-1]
        
        # 条件1：价格重新站上EMA55
        above_ema55 = current_price > ema55
        
        # 条件2：价格接近EMA21
        near_ema21 = abs(current_price - ema21) / ema21 < 0.02
        
        # 条件3：量能回归正常
        volume_normal = volume_ratio < 1.5
        
        return above_ema55 and near_ema21 and volume_normal
    
    # ==================== 恢复管理 ====================
    
    def reset_black_swan_state(self):
        """重置黑天鹅状态（恢复完成后调用）"""
        self._black_swan_state = BlackSwanState()
        self._recovery_trades_count = 0
    
    def increment_recovery_trade(self):
        """增加恢复期交易计数"""
        self._recovery_trades_count += 1
        
        # 如果达到限制，重置状态
        if self._recovery_trades_count >= self.config["recovery_trades_limit"]:
            self.reset_black_swan_state()
    
    def get_current_state(self) -> Tuple[CircuitBreakerState, AccelerationState, BlackSwanState]:
        """获取当前状态"""
        return self._circuit_state, self._acceleration_state, self._black_swan_state


# ==================== 便捷函数 ====================

def check_extreme_market(close: np.ndarray,
                         high: np.ndarray,
                         low: np.ndarray,
                         volume: np.ndarray,
                         external_events: Optional[List[Dict]] = None) -> ExtremeMarketResult:
    """
    便捷函数：检查极端行情
    
    Returns:
        ExtremeMarketResult: 包含熔断状态、加速状态、黑天鹅状态及建议动作
    """
    detector = ExtremeMarketDetector()
    return detector.analyze(close, high, low, volume, external_events)
