"""
双周期策略测试
"""

import pytest
import numpy as np
from src.fund_flow.dual_timeframe_strategy import (
    DualTimeframeStrategy,
    EMAConfig,
    MACDConfig,
    VWAPConfig,
    TrendDirection,
    SignalStrength,
    Signal,
    TechnicalIndicators
)
from src.fund_flow.trend_following_engine import (
    TrendFollowingEngine,
    MarketRegime,
    MarketState,
    EMAPullbackStrategy
)


class TestTechnicalIndicators:
    """测试技术指标计算"""

    def test_calculate_ema(self):
        """测试 EMA 计算"""
        prices = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
        ema = TechnicalIndicators.calculate_ema(prices, 5)

        assert len(ema) == len(prices)
        # EMA 应该平滑，但不应该完全等于价格
        assert not np.array_equal(ema, prices)

    def test_calculate_macd(self):
        """测试 MACD 计算"""
        prices = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                          110, 111, 112, 113, 114, 115, 116, 117, 118, 119])

        macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(
            prices, 12, 26, 9
        )

        assert len(macd_line) == len(prices)
        assert len(signal_line) == len(prices)
        assert len(histogram) == len(prices)
        # Histogram = MACD - Signal
        np.testing.assert_array_almost_equal(histogram, macd_line - signal_line)

    def test_calculate_vwap(self):
        """测试 VWAP 计算"""
        high = np.array([101, 102, 103, 104, 105])
        low = np.array([99, 100, 101, 102, 103])
        close = np.array([100, 101, 102, 103, 104])
        volume = np.array([1000, 1100, 1200, 1300, 1400])

        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)

        assert len(vwap) == len(close)
        # 累积 VWAP 应该位于整体价格区间内，且在上涨样本里逐步抬升
        assert vwap.min() >= low.min()
        assert vwap.max() <= high.max()
        assert np.all(np.diff(vwap) >= 0)


class TestDualTimeframeStrategy:
    """测试双周期策略"""

    @pytest.fixture
    def strategy(self):
        """创建策略实例"""
        return DualTimeframeStrategy()

    def test_bullish_signal_generation(self, strategy):
        """测试多头信号生成"""
        # 创建模拟数据：1H 多头趋势
        close_1h = np.linspace(100, 150, 200)  # 上涨趋势
        close_4h = np.linspace(95, 150, 200)

        # 创建模拟数据：15m 回踩后启动
        close_15m = np.linspace(140, 150, 200)
        close_15m[188:194] -= 3  # 临近末端回踩
        close_15m[194:] += 2.5  # 二次启动

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        # 应该生成信号
        assert signal is not None
        assert signal.direction == TrendDirection.BULLISH
        assert signal.entry_price > 0
        assert signal.stop_loss > 0
        assert signal.take_profit > 0
        assert signal.take_profit > signal.entry_price
        assert signal.stop_loss < signal.entry_price

    def test_bearish_signal_generation(self, strategy):
        """测试空头信号生成"""
        # 创建模拟数据：1H 空头趋势 + 4H 风控同向
        close_1h = np.linspace(150, 100, 200)  # 下跌趋势
        close_4h = np.linspace(155, 100, 200)

        # 创建模拟数据：15m 反弹后下跌
        close_15m = np.linspace(110, 100, 200)
        close_15m[188:193] += 2.58  # 临近末端反弹
        close_15m[193:] -= 1.3  # 继续下跌

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        # 应该生成信号
        assert signal is not None
        assert signal.direction == TrendDirection.BEARISH
        assert signal.entry_price > 0
        assert signal.stop_loss > 0
        assert signal.take_profit > 0
        assert signal.take_profit < signal.entry_price
        assert signal.stop_loss > signal.entry_price

    def test_no_signal_in_range(self, strategy):
        """测试震荡市场不生成信号"""
        # 创建模拟数据：震荡
        close_1h = np.random.normal(100, 2, 200)
        close_4h = np.random.normal(100, 3, 200)

        high_15m = np.random.normal(100, 1, 200)
        low_15m = np.random.normal(100, 1, 200)
        close_15m = (high_15m + low_15m) / 2
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        # 震荡市场不应该生成信号
        assert signal is None

    def test_risk_reward_calculation(self, strategy):
        """测试风险回报比计算"""
        # 创建模拟数据
        close_1h = np.linspace(100, 150, 200)
        close_4h = np.linspace(95, 150, 200)
        close_15m = np.linspace(140, 150, 200)
        close_15m[188:194] -= 3
        close_15m[194:] += 2.5

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        if signal:
            # 风险回报比应该 >= 1.5
            assert signal.risk_reward >= 1.5

    def test_4h_macd_risk_filter_blocks_countertrend_long(self, strategy):
        """测试 4H MACD 风控会拦截与高周期动能冲突的多头入场"""
        close_1h = np.linspace(100, 150, 200)
        close_4h = np.linspace(160, 100, 200)  # 4H 明显空头

        close_15m = np.linspace(140, 150, 200)
        close_15m[188:194] -= 3
        close_15m[194:] += 2.5

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        assert signal is None


class TestEMAPullbackStrategy:
    """测试 EMA 回踩策略"""

    @pytest.fixture
    def pullback_strategy(self):
        """创建回踩策略实例"""
        return EMAPullbackStrategy()

    def test_detect_pullback(self, pullback_strategy):
        """测试检测回踩"""
        # 创建回踩数据
        prices = np.linspace(100, 110, 100)
        prices[70:80] -= 2  # 回踩

        result = pullback_strategy.check_pullback_structure(prices)

        # 应该检测到回踩
        assert result is not None
        assert 'distance_to_ema21' in result
        assert 'valid_structure' in result

    def test_detect_secondary_launch(self, pullback_strategy):
        """测试检测二次启动"""
        # 创建启动数据
        prices = np.linspace(100, 110, 100)
        prices[70:80] -= 2  # 回踩
        prices[80:] += 3  # 启动

        result = pullback_strategy.detect_secondary_launch(prices)

        # 应该检测到启动信号
        assert result is not None
        assert 'launch_signal' in result
        assert 'histogram_value' in result


class TestTrendFollowingEngine:
    """测试趋势跟踪引擎"""

    @pytest.fixture
    def engine(self):
        """创建引擎实例"""
        return TrendFollowingEngine()

    def test_detect_bullish_regime(self, engine):
        """测试检测多头市场"""
        close_4h = np.linspace(100, 150, 200)
        close_1h = np.linspace(140, 150, 100)

        market_state = engine.analyze_market("BTCUSDT", close_4h, close_1h)

        assert market_state is not None
        assert market_state.regime in [MarketRegime.TRENDING_BULLISH, MarketRegime.RANGE_BOUND]

    def test_detect_bearish_regime(self, engine):
        """测试检测空头市场"""
        close_4h = np.linspace(150, 100, 200)
        close_1h = np.linspace(110, 100, 100)

        market_state = engine.analyze_market("BTCUSDT", close_4h, close_1h)

        assert market_state is not None
        assert market_state.regime in [MarketRegime.TRENDING_BEARISH, MarketRegime.RANGE_BOUND]

    def test_generate_signal(self, engine):
        """测试生成交易信号"""
        # 创建多头趋势数据
        close_4h = np.linspace(100, 150, 200)
        close_15m = np.linspace(140, 150, 200)
        close_15m[188:194] -= 3
        close_15m[194:] += 2.5

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = engine.generate_signal(
            "BTCUSDT",
            close_4h,
            high_15m,
            low_15m,
            close_15m,
            volume_15m,
            close_4h=close_4h
        )

        # 应该生成信号或返回 None（取决于市场状态）
        # 我们只验证不会崩溃
        assert signal is None or isinstance(signal, Signal)

    def test_get_market_state(self, engine):
        """测试获取市场状态"""
        close_4h = np.linspace(100, 150, 200)
        close_1h = np.linspace(140, 150, 100)

        # 分析市场
        engine.analyze_market("BTCUSDT", close_4h, close_1h)

        # 获取状态
        market_state = engine.get_market_state("BTCUSDT")

        assert market_state is not None
        assert isinstance(market_state, MarketState)
        assert market_state.regime in [
            MarketRegime.TRENDING_BULLISH,
            MarketRegime.TRENDING_BEARISH,
            MarketRegime.RANGE_BOUND,
            MarketRegime.CHOPPY
        ]


class TestSignalQuality:
    """测试信号质量"""

    @pytest.fixture
    def strategy(self):
        """创建策略实例"""
        return DualTimeframeStrategy()

    def test_bullish_signal_has_correct_levels(self, strategy):
        """测试多头信号的止盈止损"""
        close_1h = np.linspace(100, 150, 200)
        close_4h = np.linspace(95, 150, 200)
        close_15m = np.linspace(140, 150, 200)
        close_15m[188:194] -= 3
        close_15m[194:] += 2.5

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        if signal and signal.direction == TrendDirection.BULLISH:
            assert signal.take_profit > signal.entry_price
            assert signal.stop_loss < signal.entry_price
            assert signal.take_profit - signal.entry_price > 0
            assert signal.entry_price - signal.stop_loss > 0

    def test_bearish_signal_has_correct_levels(self, strategy):
        """测试空头信号的止盈止损"""
        close_1h = np.linspace(150, 100, 200)
        close_4h = np.linspace(155, 100, 200)
        close_15m = np.linspace(110, 100, 200)
        close_15m[188:193] += 2.58
        close_15m[193:] -= 1.3

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(200) * 1000

        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )

        if signal and signal.direction == TrendDirection.BEARISH:
            assert signal.take_profit < signal.entry_price
            assert signal.stop_loss > signal.entry_price
            assert signal.entry_price - signal.take_profit > 0
            assert signal.stop_loss - signal.entry_price > 0


class TestStrategyEdgeCases:
    """测试策略边缘情况"""

    @pytest.fixture
    def strategy(self):
        """创建策略实例"""
        return DualTimeframeStrategy()

    def test_insufficient_data(self, strategy):
        """测试数据不足的情况"""
        close_1h = np.random.normal(100, 1, 50)  # 数据不足
        close_4h = np.random.normal(100, 1, 50)
        close_15m = np.random.normal(100, 1, 50)

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.ones(50) * 1000

        # 不应该崩溃
        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )
        # 可能返回 None（数据不足）
        assert signal is None or isinstance(signal, Signal)

    def test_high_volatility(self, strategy):
        """测试高波动市场"""
        close_1h = np.random.normal(100, 10, 200)  # 高波动
        close_4h = np.random.normal(100, 12, 200)
        close_15m = np.random.normal(100, 5, 200)

        high_15m = close_15m + 5
        low_15m = close_15m - 5
        volume_15m = np.random.uniform(500, 1500, 200)

        # 不应该崩溃
        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )
        assert signal is None or isinstance(signal, Signal)

    def test_zero_volume(self, strategy):
        """测试零成交量的情况"""
        close_1h = np.linspace(100, 150, 200)
        close_4h = np.linspace(95, 150, 200)
        close_15m = np.linspace(140, 150, 200)

        high_15m = close_15m + 1
        low_15m = close_15m - 1
        volume_15m = np.zeros(200)  # 零成交量

        # 不应该崩溃（虽然 VWAP 可能异常）
        signal = strategy.analyze(
            close_1h, high_15m, low_15m, close_15m, volume_15m, close_4h=close_4h
        )
        assert signal is None or isinstance(signal, Signal)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
