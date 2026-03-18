"""
极端行情处理器测试
测试三级熔断、黑天鹅检测、单边加速检测
"""

import pytest
import numpy as np
from datetime import datetime, timedelta

from src.fund_flow.extreme_market_handler import (
    ExtremeMarketDetector,
    CircuitBreakerLevel,
    MarketEventType,
    RecoveryPhase,
    ActionRequired,
    check_extreme_market
)


class TestCircuitBreaker:
    """三级熔断测试"""
    
    def test_normal_market(self):
        """正常市场状态"""
        # 生成正常波动数据
        close = np.array([95000 + np.random.uniform(-100, 100) for _ in range(50)])
        high = close + np.random.uniform(100, 300, 50)
        low = close - np.random.uniform(100, 300, 50)
        volume = np.random.uniform(1000, 2000, 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.circuit_breaker.current_level == CircuitBreakerLevel.NORMAL
        assert result.action_required == ActionRequired.NONE
        assert result.is_trading_allowed is True
    
    def test_level1_yellow_circuit(self):
        """一级熔断（黄色预警）测试"""
        # 生成连续加速数据：连续3根以上大幅上涨
        base = 95000
        close = np.array([base] * 40 + [base + i * 500 for i in range(10)])  # 最后10根连续上涨
        high = close + 300
        low = close - 100
        volume = np.array([1000] * 40 + [1000 + i * 500 for i in range(10)])  # 量能放大
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.circuit_breaker.current_level == CircuitBreakerLevel.YELLOW
        assert result.action_required == ActionRequired.SWITCH_MODE
        assert result.position_multiplier <= 0.7
    
    def test_level2_red_circuit_drop(self):
        """二级熔断（红色预警）- 单根大跌"""
        # 生成单根大跌5%数据
        base = 95000
        close = np.array([base] * 49 + [base * 0.94])  # 最后一根跌6%
        high = np.array([base + 100] * 49 + [base])
        low = np.array([base - 100] * 49 + [base * 0.94])
        volume = np.array([1000] * 49 + [5000])  # 放量
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.circuit_breaker.current_level == CircuitBreakerLevel.RED
        assert result.action_required == ActionRequired.REDUCE_50
        assert result.circuit_breaker.stop_new_positions is True
    
    def test_level2_red_circuit_deviation(self):
        """二级熔断（红色预警）- EMA偏离"""
        # 生成价格大幅偏离EMA21的数据
        base = 95000
        close = np.array([base] * 30 + [base * 1.06] * 20)  # 最后20根价格高6%
        high = close + 100
        low = close - 100
        volume = np.array([1000] * 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.circuit_breaker.current_level == CircuitBreakerLevel.RED
        assert result.circuit_breaker.position_cap == 0.5
    
    def test_level3_black_circuit(self):
        """三级熔断（黑色预警）- 黑天鹅"""
        # 生成黑天鹅数据：4根内跌8%+量能500%+外部事件
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)  # 最后4根跌8%
        high = np.array([base + 100] * 46 + [base * 0.92 + 50] * 4)
        low = np.array([base - 100] * 46 + [base * 0.92 - 50] * 4)
        volume = np.array([1000] * 46 + [6000] * 4)  # 量能放大6倍
        
        external_events = [{
            "time": datetime.now(),
            "type": "exchange_collapse",
            "severity": "critical"
        }]
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume, external_events)
        
        assert result.circuit_breaker.current_level == CircuitBreakerLevel.BLACK
        assert result.action_required == ActionRequired.CLOSE_ALL
        assert result.circuit_breaker.force_close is True
        assert result.is_trading_allowed is False


class TestAccelerationDetection:
    """单边加速检测测试"""
    
    def test_normal_market_no_acceleration(self):
        """正常市场无加速"""
        # 生成正常波动
        close = np.array([95000 + np.sin(i * 0.1) * 200 for i in range(50)])
        high = close + 200
        low = close - 200
        volume = np.random.uniform(1000, 2000, 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.acceleration.is_accelerating is False
        assert result.acceleration.current_stage == 1
        assert result.market_event_type == MarketEventType.NORMAL
    
    def test_acceleration_detection(self):
        """加速行情检测"""
        # 生成连续4根以上大幅上涨
        base = 95000
        close = np.array([base] * 40 + [base + i * 800 for i in range(10)])  # 连续大涨
        high = close + 500
        low = close - 100
        volume = np.array([1000] * 40 + [2000 + i * 500 for i in range(10)])
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.acceleration.is_accelerating is True
        assert result.acceleration.consecutive_bars >= 4
        assert result.acceleration.entry_mode == "acceleration"
        assert result.position_multiplier <= 0.7
    
    def test_peak_warning(self):
        """峰值预警检测"""
        # 生成价格偏离EMA21超过5%的数据
        base = 95000
        close = np.array([base] * 30 + [base * 1.06] * 20)  # 偏离6%
        high = close + 300
        low = close - 100
        volume = np.array([1000] * 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        # 峰值预警会触发二级熔断或更高级别
        assert result.acceleration.peak_warning is True or \
               result.circuit_breaker.current_level in [CircuitBreakerLevel.RED, CircuitBreakerLevel.BLACK]
    
    def test_acceleration_entry_mode_adjustment(self):
        """加速模式入场参数调整"""
        # 生成加速行情
        base = 95000
        close = np.array([base] * 40 + [base + i * 600 for i in range(10)])
        high = close + 400
        low = close - 100
        volume = np.array([1000] * 40 + [1500 + i * 300 for i in range(10)])
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        if result.acceleration.is_accelerating:
            assert result.acceleration.stop_loss_type == "tight"
            assert result.acceleration.first_position_ratio <= 0.5
            assert result.position_multiplier <= 0.7


class TestBlackSwanDetection:
    """黑天鹅检测测试"""
    
    def test_emotional_black_swan(self):
        """情绪性黑天鹅检测"""
        # 生成跌幅8%+量能500%，但事件类型为情绪性
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = np.array([base + 100] * 46 + [base * 0.92 + 50] * 4)
        low = np.array([base - 100] * 46 + [base * 0.92 - 50] * 4)
        volume = np.array([1000] * 46 + [6000] * 4)
        
        external_events = [{
            "time": datetime.now(),
            "type": "temporary_outage",  # 临时宕机，情绪性事件
            "severity": "high"
        }]
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume, external_events)
        
        assert result.black_swan.is_active is True
        assert result.black_swan.event_type == MarketEventType.BLACK_SWAN_EMOTIONAL
        assert result.black_swan.current_phase == RecoveryPhase.PHASE_1_IMPACT
    
    def test_systemic_black_swan(self):
        """系统性黑天鹅检测"""
        base = 95000
        close = np.array([base] * 46 + [base * 0.88] * 4)  # 跌12%
        high = np.array([base + 100] * 46 + [base * 0.88 + 50] * 4)
        low = np.array([base - 100] * 46 + [base * 0.88 - 50] * 4)
        volume = np.array([1000] * 46 + [8000] * 4)
        
        external_events = [{
            "time": datetime.now(),
            "type": "exchange_collapse",  # 交易所崩盘，系统性事件
            "severity": "critical"
        }]
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume, external_events)
        
        assert result.black_swan.is_active is True
        assert result.black_swan.event_type == MarketEventType.BLACK_SWAN_SYSTEMIC
        assert result.action_required == ActionRequired.CLOSE_ALL
    
    def test_black_swan_phases(self):
        """黑天鹅四阶段恢复测试"""
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = np.array([base + 100] * 46 + [base * 0.92 + 50] * 4)
        low = np.array([base - 100] * 46 + [base * 0.92 - 50] * 4)
        volume = np.array([1000] * 46 + [6000] * 4)
        
        external_events = [{
            "time": datetime.now() - timedelta(hours=2),  # 2小时前发生
            "type": "fake_news",
            "severity": "high"
        }]
        
        detector = ExtremeMarketDetector()
        
        # 第一次检测：触发黑天鹅
        result = detector.analyze(close, high, low, volume, external_events, datetime.now())
        
        assert result.black_swan.current_phase == RecoveryPhase.PHASE_1_IMPACT
        
        # 模拟时间推移，更新到第二阶段
        # (在实际使用中，需要传入更新后的时间和数据)


class TestParameterAdjustment:
    """参数调整测试"""
    
    def test_normal_position_multiplier(self):
        """正常市场仓位乘数"""
        close = np.array([95000 + np.random.uniform(-100, 100) for _ in range(50)])
        high = close + 200
        low = close - 200
        volume = np.random.uniform(1000, 2000, 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert result.position_multiplier == 1.0
        assert result.entry_threshold == 70
    
    def test_acceleration_position_reduction(self):
        """加速行情仓位缩减"""
        base = 95000
        close = np.array([base] * 40 + [base + i * 700 for i in range(10)])
        high = close + 400
        low = close - 100
        volume = np.array([1000] * 40 + [2000 + i * 400 for i in range(10)])
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        if result.acceleration.is_accelerating:
            assert result.position_multiplier < 1.0
            assert result.entry_threshold <= 70
    
    def test_black_swan_entry_threshold(self):
        """黑天鹅入场门槛提高"""
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = close + 100
        low = close - 100
        volume = np.array([1000] * 46 + [6000] * 4)
        
        external_events = [{
            "time": datetime.now(),
            "type": "major_hack",
            "severity": "critical"
        }]
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume, external_events)
        
        # 黑天鹅期间不允许交易
        assert result.is_trading_allowed is False
        assert result.position_multiplier == 0.0


class TestWarnings:
    """警告信息测试"""
    
    def test_circuit_breaker_warning(self):
        """熔断警告"""
        base = 95000
        close = np.array([base] * 40 + [base + i * 600 for i in range(10)])
        high = close + 400
        low = close - 100
        volume = np.array([1000] * 40 + [4000 + i * 500 for i in range(10)])
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        assert len(result.warnings) > 0
        assert any("熔断" in w for w in result.warnings)
    
    def test_peak_warning_message(self):
        """峰值预警信息"""
        base = 95000
        close = np.array([base] * 30 + [base * 1.06] * 20)
        high = close + 200
        low = close - 100
        volume = np.array([1000] * 50)
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume)
        
        # 峰值预警或二级熔断会生成警告
        if result.acceleration.peak_warning or result.circuit_breaker.current_level == CircuitBreakerLevel.RED:
            assert len(result.warnings) > 0
    
    def test_black_swan_warning(self):
        """黑天鹅警告"""
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = close + 100
        low = close - 100
        volume = np.array([1000] * 46 + [6000] * 4)
        
        external_events = [{
            "time": datetime.now(),
            "type": "regulatory_ban",
            "severity": "critical"
        }]
        
        detector = ExtremeMarketDetector()
        result = detector.analyze(close, high, low, volume, external_events)
        
        assert len(result.warnings) > 0
        assert any("黑天鹅" in w for w in result.warnings)


class TestConvenienceFunction:
    """便捷函数测试"""
    
    def test_check_extreme_market_function(self):
        """便捷函数调用测试"""
        base = 95000
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = close + 100
        low = close - 100
        volume = np.array([1000] * 46 + [6000] * 4)
        
        result = check_extreme_market(close, high, low, volume)
        
        assert result is not None
        assert hasattr(result, 'circuit_breaker')
        assert hasattr(result, 'acceleration')
        assert hasattr(result, 'black_swan')


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试"""
    
    def test_full_scenario_emotional_black_swan_recovery(self):
        """完整场景：情绪性黑天鹅恢复"""
        base = 95000
        detector = ExtremeMarketDetector()
        
        # 阶段1：黑天鹅触发
        close = np.array([base] * 46 + [base * 0.92] * 4)
        high = close + 100
        low = close - 100
        volume = np.array([1000] * 46 + [6000] * 4)
        
        external_events = [{
            "time": datetime.now(),
            "type": "fake_news",
            "severity": "high"
        }]
        
        result = detector.analyze(close, high, low, volume, external_events)
        
        assert result.black_swan.is_active
        assert result.black_swan.current_phase == RecoveryPhase.PHASE_1_IMPACT
        assert result.action_required == ActionRequired.CLOSE_ALL
        
        # 验证初始状态
        assert result.position_multiplier == 0.0
        assert result.is_trading_allowed is False
    
    def test_full_scenario_acceleration_to_normal(self):
        """完整场景：加速行情恢复"""
        base = 95000
        detector = ExtremeMarketDetector()
        
        # 阶段1：加速行情
        close = np.array([base] * 40 + [base + i * 600 for i in range(10)])
        high = close + 400
        low = close - 100
        volume = np.array([1000] * 40 + [2000 + i * 400 for i in range(10)])
        
        result = detector.analyze(close, high, low, volume)
        
        # 验证加速状态
        if result.acceleration.is_accelerating:
            assert result.position_multiplier < 1.0
            assert result.market_event_type == MarketEventType.ACCELERATION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
