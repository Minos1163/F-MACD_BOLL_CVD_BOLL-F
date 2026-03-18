"""
极端行情处理器集成模块
展示如何将极端行情处理集成到MTF交易系统V3
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import numpy as np

from .extreme_market_handler import (
    ExtremeMarketDetector,
    ExtremeMarketResult,
    CircuitBreakerLevel,
    MarketEventType,
    ActionRequired
)
from .stabilization_scorer import StabilizationScorer, StabilizationResult, SignalLevel


@dataclass
class IntegratedSignal:
    """集成信号 - 包含企稳判定和极端行情处理"""
    # 基础信号
    direction: str
    entry_price: float
    
    # 企稳判定
    stabilization_score: int
    stabilization_level: str
    stabilization_passed: bool
    
    # 极端行情状态
    circuit_breaker_level: str
    market_event_type: str
    action_required: str
    
    # 参数调整
    adjusted_position_pct: float
    adjusted_entry_threshold: int
    adjusted_stop_loss_multiplier: float
    
    # 最终决策
    is_trading_allowed: bool
    final_position_pct: float
    
    # 详细信息
    warnings: List[str]
    reason: str


class IntegratedTradingSystem:
    """
    集成极端行情处理的交易系统
    
    核心逻辑：
    1. 先检测极端行情（熔断优先级最高）
    2. 再进行企稳判定（正常分析流程）
    3. 综合两者决定最终动作
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 初始化两个核心模块
        self.extreme_detector = ExtremeMarketDetector(config.get("extreme_market", {}))
        self.stabilization_scorer = StabilizationScorer(config.get("stabilization", {}))
    
    def analyze(self,
                close: np.ndarray,
                high: np.ndarray,
                low: np.ndarray,
                volume: np.ndarray,
                direction: str = "long",
                external_events: Optional[List[Dict]] = None) -> IntegratedSignal:
        """
        完整分析流程
        
        执行顺序：
        1. 极端行情检测（熔断优先）
        2. 企稳判定（正常流程）
        3. 综合决策
        """
        
        # ========== 第一步：极端行情检测 ==========
        extreme_result = self.extreme_detector.analyze(
            close, high, low, volume, external_events, datetime.now()
        )
        
        # ========== 第二步：企稳判定 ==========
        stabilization_result = self.stabilization_scorer.analyze(
            close, high, low, volume, direction
        )
        
        # ========== 第三步：综合决策 ==========
        integrated_signal = self._make_integrated_decision(
            extreme_result, stabilization_result, direction
        )
        
        return integrated_signal
    
    def _make_integrated_decision(self,
                                   extreme: ExtremeMarketResult,
                                   stabilization: StabilizationResult,
                                   direction: str) -> IntegratedSignal:
        """综合决策"""
        
        # 基础参数
        entry_price = stabilization.price_score.details.get("当前价格", 0)
        base_position_pct = stabilization.position_pct
        
        # 根据极端行情调整参数
        if not extreme.is_trading_allowed:
            # 禁止交易的情况
            final_position_pct = 0.0
            is_trading_allowed = False
            reason = f"极端行情禁止交易: {extreme.circuit_breaker.trigger_reason}"
        
        elif extreme.action_required == ActionRequired.SWITCH_MODE:
            # 切换加速模式
            final_position_pct = base_position_pct * extreme.position_multiplier
            is_trading_allowed = True
            reason = f"加速模式: 仓位调整为{extreme.position_multiplier:.0%}"
        
        elif extreme.action_required == ActionRequired.REDUCE_50:
            # 减仓50%
            final_position_pct = base_position_pct * 0.5
            is_trading_allowed = stabilization.passed  # 仍需企稳判定通过
            reason = f"二级熔断: 仓位上限50%"
        
        elif extreme.action_required == ActionRequired.TRIAL_ENTRY:
            # 试探入场（黑天鹅恢复期）
            final_position_pct = extreme.black_swan.trial_position_pct
            is_trading_allowed = stabilization.total_score >= extreme.black_swan.recovery_threshold
            reason = f"恢复期试探入场: 仓位{final_position_pct:.0%}"
        
        else:
            # 正常交易
            final_position_pct = base_position_pct * extreme.position_multiplier
            is_trading_allowed = stabilization.passed
            reason = f"正常交易: {stabilization.reason}"
        
        # 调整入场门槛
        adjusted_threshold = max(stabilization.total_score, extreme.entry_threshold)
        
        return IntegratedSignal(
            direction=direction,
            entry_price=entry_price,
            
            # 企稳判定
            stabilization_score=stabilization.total_score,
            stabilization_level=stabilization.level.value,
            stabilization_passed=stabilization.passed,
            
            # 极端行情
            circuit_breaker_level=extreme.circuit_breaker.current_level.value,
            market_event_type=extreme.market_event_type.value,
            action_required=extreme.action_required.value,
            
            # 参数调整
            adjusted_position_pct=base_position_pct,
            adjusted_entry_threshold=adjusted_threshold,
            adjusted_stop_loss_multiplier=extreme.stop_loss_multiplier,
            
            # 最终决策
            is_trading_allowed=is_trading_allowed,
            final_position_pct=final_position_pct,
            
            # 详细信息
            warnings=extreme.warnings,
            reason=reason
        )


# ==================== 使用示例 ====================

def example_normal_market():
    """正常市场示例"""
    print("\n" + "="*60)
    print("示例1：正常市场")
    print("="*60)
    
    # 生成正常波动数据
    base = 95000
    close = np.array([base + np.sin(i * 0.1) * 200 for i in range(50)])
    high = close + np.random.uniform(100, 300, 50)
    low = close - np.random.uniform(100, 300, 50)
    volume = np.random.uniform(1000, 2000, 50)
    
    # 创建集成系统
    system = IntegratedTradingSystem()
    
    # 分析
    signal = system.analyze(close, high, low, volume, direction="long")
    
    # 打印结果
    print(f"企稳得分: {signal.stabilization_score}/100")
    print(f"企稳等级: {signal.stabilization_level}")
    print(f"熔断级别: {signal.circuit_breaker_level}")
    print(f"市场类型: {signal.market_event_type}")
    print(f"是否允许交易: {signal.is_trading_allowed}")
    print(f"最终仓位: {signal.final_position_pct:.0%}")
    print(f"原因: {signal.reason}")


def example_acceleration_market():
    """加速行情示例"""
    print("\n" + "="*60)
    print("示例2：单边加速行情")
    print("="*60)
    
    # 生成连续加速数据
    base = 95000
    close = np.array([base] * 40 + [base + i * 600 for i in range(10)])  # 连续大涨
    high = close + 400
    low = close - 100
    volume = np.array([1000] * 40 + [2000 + i * 500 for i in range(10)])
    
    system = IntegratedTradingSystem()
    signal = system.analyze(close, high, low, volume, direction="long")
    
    print(f"企稳得分: {signal.stabilization_score}/100")
    print(f"熔断级别: {signal.circuit_breaker_level}")
    print(f"市场类型: {signal.market_event_type}")
    print(f"动作要求: {signal.action_required}")
    print(f"仓位乘数: {signal.adjusted_position_pct:.0%}")
    print(f"最终仓位: {signal.final_position_pct:.0%}")
    print(f"警告: {signal.warnings}")
    print(f"原因: {signal.reason}")


def example_black_swan():
    """黑天鹅事件示例"""
    print("\n" + "="*60)
    print("示例3：黑天鹅事件")
    print("="*60)
    
    # 生成黑天鹅数据
    base = 95000
    close = np.array([base] * 46 + [base * 0.92] * 4)  # 4根跌8%
    high = close + 100
    low = close - 100
    volume = np.array([1000] * 46 + [6000] * 4)  # 量能放大6倍
    
    # 外部事件
    external_events = [{
        "time": datetime.now(),
        "type": "exchange_collapse",
        "severity": "critical"
    }]
    
    system = IntegratedTradingSystem()
    signal = system.analyze(close, high, low, volume, "long", external_events)
    
    print(f"企稳得分: {signal.stabilization_score}/100")
    print(f"熔断级别: {signal.circuit_breaker_level}")
    print(f"市场类型: {signal.market_event_type}")
    print(f"动作要求: {signal.action_required}")
    print(f"是否允许交易: {signal.is_trading_allowed}")
    print(f"最终仓位: {signal.final_position_pct:.0%}")
    print(f"警告: {signal.warnings}")
    print(f"原因: {signal.reason}")


def example_peak_warning():
    """峰值预警示例"""
    print("\n" + "="*60)
    print("示例4：峰值预警")
    print("="*60)
    
    # 生成价格偏离EMA21超过5%的数据
    base = 95000
    close = np.array([base] * 30 + [base * 1.06] * 20)  # 偏离6%
    high = close + 200
    low = close - 100
    volume = np.array([1000] * 50)
    
    system = IntegratedTradingSystem()
    signal = system.analyze(close, high, low, volume, direction="long")
    
    print(f"企稳得分: {signal.stabilization_score}/100")
    print(f"熔断级别: {signal.circuit_breaker_level}")
    print(f"动作要求: {signal.action_required}")
    print(f"是否允许交易: {signal.is_trading_allowed}")
    print(f"警告: {signal.warnings}")
    print(f"原因: {signal.reason}")


# ==================== 快速使用指南 ====================

def quick_start():
    """快速使用指南"""
    print("\n" + "="*60)
    print("极端行情处理器 - 快速使用指南")
    print("="*60)
    
    code = '''
from src.fund_flow.extreme_market_handler import ExtremeMarketDetector, check_extreme_market

# 方式1：使用便捷函数
result = check_extreme_market(close, high, low, volume)

# 方式2：使用完整检测器
detector = ExtremeMarketDetector()
result = detector.analyze(close, high, low, volume, external_events)

# 检查关键属性
print(f"熔断级别: {result.circuit_breaker.current_level.value}")
print(f"是否允许交易: {result.is_trading_allowed}")
print(f"仓位乘数: {result.position_multiplier}")
print(f"建议动作: {result.action_required.value}")
print(f"警告: {result.warnings}")

# 根据结果调整策略
if result.action_required.value == "close_all":
    # 立即清仓
    execute_close_all()
elif result.action_required.value == "reduce_50":
    # 减仓50%
    execute_reduce_position(0.5)
elif result.action_required.value == "switch_mode":
    # 切换加速模式，收紧止损
    switch_to_acceleration_mode()
'''
    print(code)
    
    print("\n关键属性说明：")
    print("- is_trading_allowed: 是否允许交易（综合判断）")
    print("- position_multiplier: 仓位调整乘数（0.0~1.0）")
    print("- entry_threshold: 入场门槛分数")
    print("- stop_loss_multiplier: 止损宽度乘数")
    print("- warnings: 警告信息列表")


if __name__ == "__main__":
    # 运行所有示例
    example_normal_market()
    example_acceleration_market()
    example_black_swan()
    example_peak_warning()
    quick_start()
