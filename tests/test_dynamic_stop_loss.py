"""
动态止损系统测试
测试ATR计算、市场状态识别、动态止损计算、移动止损
"""

import pytest
import numpy as np
from datetime import datetime

from src.fund_flow.dynamic_stop_loss import (
    ATRCalculator,
    ATRInfo,
    MarketStateDetector,
    MarketState,
    MarketStateResult,
    DynamicStopLossCalculator,
    StopLossResult,
    TrailingStopManager,
    StopLossStage,
    TrailingStopState,
    StopLossCircuitBreaker,
    EntryPosition,
    calculate_dynamic_stop_loss,
    get_market_state
)


class TestATRCalculator:
    """ATR计算器测试"""
    
    def test_atr_calculation(self):
        """ATR计算测试"""
        # 生成模拟数据
        np.random.seed(42)
        base = 95000
        close = np.array([base + np.random.uniform(-500, 500) for _ in range(50)])
        high = close + np.random.uniform(200, 600, 50)
        low = close - np.random.uniform(200, 600, 50)
        
        atr = ATRCalculator.calculate(high, low, close, period=14)
        
        assert len(atr) == len(close)
        assert atr[-1] > 0
        print(f"ATR(14): {atr[-1]:.2f}")
    
    def test_atr_info(self):
        """ATR信息获取测试"""
        base = 95000
        close = np.array([base] * 30 + [base + i * 100 for i in range(20)])
        high = close + 400
        low = close - 400
        
        info = ATRCalculator.get_info(high, low, close, period=14, lookback=20)
        
        assert info.current_atr > 0
        assert info.atr_mean_20 > 0
        assert 0 < info.atr_ratio < 10
        assert 0 < info.atr_percentage < 0.1
        
        print(f"当前ATR: {info.current_atr:.2f}")
        print(f"ATR均值(20): {info.atr_mean_20:.2f}")
        print(f"ATR比例: {info.atr_ratio:.2f}")
        print(f"ATR占比: {info.atr_percentage:.4f}")
    
    def test_extreme_volatility_detection(self):
        """极端波动检测测试"""
        # 生成极端波动数据
        base = 95000
        close = np.array([base] * 40 + [base - i * 500 for i in range(10)])  # 突然大跌
        high = close + 1000  # 大振幅
        low = close - 1000
        
        info = ATRCalculator.get_info(high, low, close, period=14, lookback=20)
        
        # 极端波动后ATR比例应该升高
        print(f"极端波动ATR比例: {info.atr_ratio:.2f}")


class TestMarketStateDetector:
    """市场状态识别器测试"""
    
    def test_bull_market_detection(self):
        """牛市识别测试"""
        # 生成牛市数据：连续上涨
        base = 95000
        close = np.array([base - 2000 + i * 150 for i in range(50)])  # 连续上涨
        high = close + 300
        low = close - 200
        volume = np.random.uniform(1000, 3000, 50)
        
        atr_info = ATRCalculator.get_info(high, low, close)
        detector = MarketStateDetector()
        result = detector.detect(close, high, low, volume, atr_info)
        
        print(f"市场状态: {result.state.value}")
        print(f"EMA排列: {result.ema_alignment}")
        print(f"MACD方向: {result.macd_direction}")
        print(f"置信度: {result.confidence:.2f}")
        
        # 连续上涨应该被识别为牛市或至少不是熊市
        assert result.state in [MarketState.BULL_MARKET, MarketState.RANGE_MARKET]
    
    def test_bear_market_detection(self):
        """熊市识别测试"""
        # 生成熊市数据：连续下跌
        base = 95000
        close = np.array([base + 2000 - i * 150 for i in range(50)])  # 连续下跌
        high = close + 200
        low = close - 300
        volume = np.random.uniform(1000, 3000, 50)
        
        atr_info = ATRCalculator.get_info(high, low, close)
        detector = MarketStateDetector()
        result = detector.detect(close, high, low, volume, atr_info)
        
        print(f"市场状态: {result.state.value}")
        print(f"EMA排列: {result.ema_alignment}")
        print(f"MACD方向: {result.macd_direction}")
        
        # 连续下跌应该被识别为熊市或至少不是牛市
        assert result.state in [MarketState.BEAR_MARKET, MarketState.RANGE_MARKET]
    
    def test_range_market_detection(self):
        """震荡市识别测试"""
        # 生成震荡数据
        base = 95000
        close = np.array([base + np.sin(i * 0.3) * 500 for i in range(50)])  # 震荡
        high = close + 200
        low = close - 200
        volume = np.random.uniform(500, 1500, 50)
        
        atr_info = ATRCalculator.get_info(high, low, close)
        detector = MarketStateDetector()
        result = detector.detect(close, high, low, volume, atr_info)
        
        print(f"市场状态: {result.state.value}")
        print(f"ATR水平: {result.atr_level}")
        print(f"置信度: {result.confidence:.2f}")


class TestDynamicStopLossCalculator:
    """动态止损计算器测试"""
    
    def test_standard_stop_loss_long(self):
        """标准做多止损计算"""
        base = 95000
        close = np.array([base - 1000 + i * 50 for i in range(50)])
        high = close + 400
        low = close - 300
        volume = np.random.uniform(1000, 2000, 50)
        
        entry_price = close[-1]
        
        result = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            entry_position="standard",
            account_size=10000,
            risk_pct=0.01
        )
        
        print(f"\n止损价格: {result.stop_price:.2f}")
        print(f"止损距离: {result.stop_distance:.2f} USDT")
        print(f"止损距离%: {result.stop_distance_pct:.4%}")
        print(f"止损系数K: {result.stop_coefficient:.2f}")
        print(f"VAF修正: {result.vaf_adjustment:.2f}")
        print(f"市场状态: {result.market_state.value}")
        print(f"建议仓位: {result.suggested_position:.6f} BTC")
        print(f"仓位价值: {result.position_value_usdt:.2f} USDT")
        
        assert result.stop_price < entry_price
        assert result.stop_distance > 0
        assert result.suggested_position > 0
    
    def test_standard_stop_loss_short(self):
        """标准做空止损计算"""
        base = 95000
        close = np.array([base + 1000 - i * 50 for i in range(50)])
        high = close + 300
        low = close - 400
        volume = np.random.uniform(1000, 2000, 50)
        
        entry_price = close[-1]
        
        result = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="short",
            entry_position="standard",
            account_size=10000,
            risk_pct=0.01
        )
        
        print(f"\n止损价格: {result.stop_price:.2f}")
        print(f"止损距离: {result.stop_distance:.2f} USDT")
        
        assert result.stop_price > entry_price  # 做空止损在上方
        assert result.stop_distance > 0
    
    def test_acceleration_entry_stop_loss(self):
        """加速段入场止损计算"""
        base = 95000
        # 加速行情
        close = np.array([base] * 40 + [base + i * 600 for i in range(10)])
        high = close + 400
        low = close - 200
        volume = np.array([1000] * 40 + [2000 + i * 300 for i in range(10)])
        
        entry_price = close[-1]
        
        result = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            entry_position="acceleration",
            account_size=10000,
            risk_pct=0.01
        )
        
        print(f"\n加速段止损系数: {result.stop_coefficient:.2f}")
        print(f"市场状态: {result.market_state.value}")
        
        # 加速段止损系数应该较小
        assert result.stop_coefficient <= 1.5
    
    def test_range_market_stop_loss(self):
        """震荡市止损计算"""
        base = 95000
        # 震荡行情
        close = np.array([base + np.sin(i * 0.2) * 300 for i in range(50)])
        high = close + 150
        low = close - 150
        volume = np.random.uniform(500, 1000, 50)
        
        entry_price = close[-1]
        
        result = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            entry_position="range_boundary",
            account_size=10000,
            risk_pct=0.01
        )
        
        print(f"\n震荡市止损系数: {result.stop_coefficient:.2f}")
        print(f"市场状态: {result.market_state.value}")
        
        # 震荡市止损系数应该较小
        if result.market_state == MarketState.RANGE_MARKET:
            assert result.stop_coefficient <= 1.0
    
    def test_position_calculation(self):
        """仓位计算测试"""
        base = 95000
        close = np.array([base + i * 20 for i in range(50)])
        high = close + 300
        low = close - 300
        volume = np.random.uniform(1000, 2000, 50)
        
        entry_price = close[-1]
        
        # 测试不同账户大小
        result_10k = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            account_size=10000,
            risk_pct=0.01
        )
        
        result_50k = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            account_size=50000,
            risk_pct=0.01
        )
        
        # 仓位应该与账户大小成正比
        ratio = result_50k.suggested_position / result_10k.suggested_position
        print(f"\n仓位比例(50k/10k): {ratio:.2f}")
        
        # 理论上应该是5倍
        assert 4 < ratio < 6


class TestTrailingStopManager:
    """移动止损管理器测试"""
    
    def test_stage_1_breakeven(self):
        """保本止损阶段测试"""
        manager = TrailingStopManager()
        
        state = TrailingStopState(
            current_stage=StopLossStage.INITIAL,
            current_stop_price=93000,
            unrealized_pnl_pct=0.0,
            bars_held=0,
            stage_1_trigger_price=94500,
            stage_2_trigger_price=95000,
            stage_3_trigger_price=95500,
            last_update_reason="",
            last_update_price=0
        )
        
        # 当前价格达到保本触发条件
        current_price = 94600
        ema21 = 94000
        atr = 800
        
        new_stop, new_stage, reason = manager.update(
            state, current_price, ema21, atr,
            recent_low=93500, recent_high=94600,
            direction="long"
        )
        
        print(f"\n保本止损: {new_stop:.2f}")
        print(f"阶段: {new_stage.value}")
        print(f"原因: {reason}")
    
    def test_stage_3_trailing(self):
        """跟踪止损阶段测试"""
        manager = TrailingStopManager()
        
        state = TrailingStopState(
            current_stage=StopLossStage.LOCK_PROFIT,
            current_stop_price=94000,
            unrealized_pnl_pct=0.03,
            bars_held=10,
            stage_1_trigger_price=94500,
            stage_2_trigger_price=95000,
            stage_3_trigger_price=95500,
            last_update_reason="锁利止损",
            last_update_price=94000
        )
        
        # 价格继续上涨，进入跟踪阶段
        current_price = 96000
        ema21 = 95500
        atr = 800
        
        new_stop, new_stage, reason = manager.update(
            state, current_price, ema21, atr,
            recent_low=95000, recent_high=96100,
            direction="long"
        )
        
        print(f"\n跟踪止损: {new_stop:.2f}")
        print(f"阶段: {new_stage.value}")
        print(f"原因: {reason}")


class TestStopLossCircuitBreaker:
    """止损熔断测试"""
    
    def test_circuit_trigger(self):
        """熔断触发测试"""
        breaker = StopLossCircuitBreaker()
        
        # 创建极端ATR信息
        atr_info = ATRInfo(
            current_atr=2000,
            atr_mean_20=700,
            atr_ratio=2.86,  # 超过2.5阈值
            atr_percentage=0.021
        )
        
        is_triggered, reason = breaker.check_circuit(atr_info, candle_body=5000)
        
        print(f"\n熔断触发: {is_triggered}")
        print(f"原因: {reason}")
        
        assert is_triggered is True
    
    def test_circuit_not_triggered(self):
        """正常情况不触发熔断"""
        breaker = StopLossCircuitBreaker()
        
        atr_info = ATRInfo(
            current_atr=600,
            atr_mean_20=550,
            atr_ratio=1.09,  # 正常范围
            atr_percentage=0.006
        )
        
        is_triggered, reason = breaker.check_circuit(atr_info, candle_body=500)
        
        print(f"\n熔断触发: {is_triggered}")
        
        assert is_triggered is False


class TestIntegration:
    """集成测试"""
    
    def test_full_stop_loss_workflow(self):
        """完整止损流程测试"""
        print("\n" + "="*60)
        print("完整止损流程测试")
        print("="*60)
        
        # 1. 生成市场数据
        base = 95000
        close = np.array([base - 500 + i * 80 for i in range(50)])
        high = close + np.random.uniform(200, 400, 50)
        low = close - np.random.uniform(200, 400, 50)
        volume = np.random.uniform(1000, 2000, 50)
        
        entry_price = close[-1]
        
        # 2. 计算动态止损
        result = calculate_dynamic_stop_loss(
            close, high, low, volume,
            entry_price=entry_price,
            direction="long",
            entry_position="standard",
            account_size=10000,
            risk_pct=0.01
        )
        
        # 3. 输出结果
        print(f"\n入场价格: {entry_price:.2f} USDT")
        print(f"止损价格: {result.stop_price:.2f} USDT")
        print(f"止损距离: {result.stop_distance:.2f} USDT ({result.stop_distance_pct:.2%})")
        print(f"止损系数: {result.stop_coefficient:.2f}")
        print(f"VAF修正: {result.vaf_adjustment:.2f}")
        print(f"市场状态: {result.market_state.value}")
        print(f"止损锚点: {result.stop_anchor}")
        print(f"建议仓位: {result.suggested_position:.6f} BTC")
        print(f"仓位价值: {result.position_value_usdt:.2f} USDT")
        print(f"风险金额: {result.risk_amount_usdt:.2f} USDT")
        
        print(f"\n移动止损计划:")
        for stage, details in result.trailing_plan.items():
            print(f"  {stage}: {details}")
        
        # 4. 验证
        assert result.is_valid or len(result.validation_warnings) > 0
        assert result.suggested_position > 0
    
    def test_different_market_conditions(self):
        """不同市场条件对比测试"""
        print("\n" + "="*60)
        print("不同市场条件对比")
        print("="*60)
        
        account_size = 10000
        risk_pct = 0.01
        
        # 牛市
        bull_close = np.array([93000 + i * 100 for i in range(50)])
        bull_high = bull_close + 400
        bull_low = bull_close - 300
        bull_volume = np.random.uniform(1500, 3000, 50)
        
        bull_result = calculate_dynamic_stop_loss(
            bull_close, bull_high, bull_low, bull_volume,
            entry_price=bull_close[-1],
            direction="long",
            account_size=account_size,
            risk_pct=risk_pct
        )
        
        # 震荡市
        range_close = np.array([95000 + np.sin(i * 0.2) * 300 for i in range(50)])
        range_high = range_close + 150
        range_low = range_close - 150
        range_volume = np.random.uniform(500, 1000, 50)
        
        range_result = calculate_dynamic_stop_loss(
            range_close, range_high, range_low, range_volume,
            entry_price=range_close[-1],
            direction="long",
            account_size=account_size,
            risk_pct=risk_pct
        )
        
        # 熊市
        bear_close = np.array([97000 - i * 100 for i in range(50)])
        bear_high = bear_close + 300
        bear_low = bear_close - 500
        bear_volume = np.random.uniform(2000, 4000, 50)
        
        bear_result = calculate_dynamic_stop_loss(
            bear_close, bear_high, bear_low, bear_volume,
            entry_price=bear_close[-1],
            direction="short",  # 熊市做空
            account_size=account_size,
            risk_pct=risk_pct
        )
        
        print(f"\n{'市场':<10} {'止损系数':<10} {'止损距离':<15} {'建议仓位':<15}")
        print("-" * 50)
        print(f"{'牛市':<10} {bull_result.stop_coefficient:<10.2f} {bull_result.stop_distance:<15.0f} {bull_result.suggested_position:<15.6f}")
        print(f"{'震荡市':<10} {range_result.stop_coefficient:<10.2f} {range_result.stop_distance:<15.0f} {range_result.suggested_position:<15.6f}")
        print(f"{'熊市做空':<10} {bear_result.stop_coefficient:<10.2f} {bear_result.stop_distance:<15.0f} {bear_result.suggested_position:<15.6f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
