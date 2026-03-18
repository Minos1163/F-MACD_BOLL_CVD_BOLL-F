"""
多时间框架交易系统测试
"""

import pytest
import numpy as np
from src.fund_flow.mtf_trading_system import (
    MTFTradingSystem,
    MTFConfig,
    MTFSignal,
    MacroLayer,
    CoreLayer,
    MicroLayer,
    ScoreFusionEngine,
    TechnicalIndicators,
    TrendDirection,
    SignalGrade,
    SignalType,
    MarketRegime,
    create_mtf_system
)


class TestTechnicalIndicators:
    """测试技术指标"""
    
    def test_calculate_ema(self):
        """测试 EMA 计算"""
        prices = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
        ema = TechnicalIndicators.calculate_ema(prices, 5)
        
        assert len(ema) == len(prices)
        assert not np.array_equal(ema, prices)
    
    def test_calculate_macd(self):
        """测试 MACD 计算"""
        prices = np.linspace(100, 150, 100)
        
        macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(
            prices, 12, 26, 9
        )
        
        assert len(macd_line) == len(prices)
        assert len(signal_line) == len(prices)
        assert len(histogram) == len(prices)
        np.testing.assert_array_almost_equal(histogram, macd_line - signal_line)
    
    def test_calculate_vwap(self):
        """测试 VWAP 计算"""
        high = np.array([101, 102, 103, 104, 105])
        low = np.array([99, 100, 101, 102, 103])
        close = np.array([100, 101, 102, 103, 104])
        volume = np.array([1000, 1100, 1200, 1300, 1400])
        
        vwap = TechnicalIndicators.calculate_vwap(high, low, close, volume)
        
        assert len(vwap) == len(close)
        for i in range(len(vwap)):
            assert low[i] <= vwap[i] <= high[i]


class TestMacroLayer:
    """测试宏观层 (4H)"""
    
    @pytest.fixture
    def macro_layer(self):
        return MacroLayer(MTFConfig())
    
    def test_bullish_permission(self, macro_layer):
        """测试多头许可"""
        # 创建上涨趋势数据
        close = np.linspace(100, 150, 100)
        
        _, _, histogram = TechnicalIndicators.calculate_macd(close, 12, 26, 9)
        macd_line, signal_line, _ = TechnicalIndicators.calculate_macd(close, 12, 26, 9)
        
        permission = macro_layer.get_direction_permission(
            close, macd_line, signal_line, histogram
        )
        
        assert permission["long_allowed"] is True
        assert permission["short_allowed"] is False
    
    def test_bearish_permission(self, macro_layer):
        """测试空头许可"""
        # 创建下跌趋势数据
        close = np.linspace(150, 100, 100)
        
        _, _, histogram = TechnicalIndicators.calculate_macd(close, 12, 26, 9)
        macd_line, signal_line, _ = TechnicalIndicators.calculate_macd(close, 12, 26, 9)
        
        permission = macro_layer.get_direction_permission(
            close, macd_line, signal_line, histogram
        )
        
        assert permission["long_allowed"] is False
        assert permission["short_allowed"] is True


class TestCoreLayer:
    """测试执行层 (1H)"""
    
    @pytest.fixture
    def core_layer(self):
        return CoreLayer(MTFConfig())
    
    def test_identify_trend_regime(self, core_layer):
        """测试强趋势识别"""
        # 创建强趋势数据
        close = np.linspace(100, 150, 200)
        vwap = np.linspace(110, 140, 200)
        
        regime = core_layer.identify_regime(close, vwap)
        
        assert regime in [MarketRegime.TREND_ON, MarketRegime.PULLBACK]
    
    def test_identify_chop_regime(self, core_layer):
        """测试震荡识别"""
        # 创建震荡数据
        close = np.random.normal(125, 2, 200)
        vwap = np.full(200, 125)
        
        regime = core_layer.identify_regime(close, vwap)
        
        assert regime == MarketRegime.CHOP
    
    def test_calculate_trend_score(self, core_layer):
        """测试趋势得分计算"""
        # 多头排列
        close = np.linspace(100, 150, 200)
        vwap = np.linspace(110, 140, 200)
        
        score = core_layer.calculate_trend_score(close, vwap)
        
        assert 0 <= score <= 40
        assert score > 30  # 应该是高分
    
    def test_calculate_pullback_score(self, core_layer):
        """测试回撤得分计算"""
        # 创建回踩结构
        close = np.linspace(100, 140, 150)
        close = np.append(close, np.linspace(138, 139, 50))  # 回踩
        
        score = core_layer.calculate_pullback_score(close)
        
        assert 0 <= score <= 20


class TestMicroLayer:
    """测试微观层 (15m)"""
    
    @pytest.fixture
    def micro_layer(self):
        return MicroLayer(MTFConfig())
    
    def test_calculate_momentum_score_golden_cross(self, micro_layer):
        """测试金叉动能得分"""
        # 创建 MACD 金叉数据
        close = np.linspace(100, 150, 100)
        _, _, histogram = TechnicalIndicators.calculate_macd(close, 8, 21, 5)
        
        score = micro_layer.calculate_momentum_score(close, histogram)
        
        assert 0 <= score <= 20
    
    def test_check_exhaustion_signal(self, micro_layer):
        """测试衰竭信号检测"""
        close = np.linspace(100, 150, 100)
        _, _, histogram = TechnicalIndicators.calculate_macd(close, 8, 21, 5)
        
        exhaustion = micro_layer.check_exhaustion_signal(close, histogram)
        
        assert "has_exhaustion" in exhaustion
        assert "action" in exhaustion


class TestScoreFusionEngine:
    """测试分数融合引擎"""
    
    @pytest.fixture
    def score_engine(self):
        return ScoreFusionEngine(MTFConfig())
    
    def test_s_grade_signal(self, score_engine):
        """测试 S 级信号"""
        total_score, grade = score_engine.fuse_scores(
            trend_score=40,
            pullback_score=20,
            momentum_score=20,
            macro_alignment_score=20,
            regime=MarketRegime.TREND_ON
        )
        
        assert total_score == 100
        assert grade == SignalGrade.S_GRADE
    
    def test_a_grade_signal(self, score_engine):
        """测试 A 级信号"""
        total_score, grade = score_engine.fuse_scores(
            trend_score=30,
            pullback_score=15,
            momentum_score=15,
            macro_alignment_score=15,
            regime=MarketRegime.PULLBACK
        )
        
        assert 70 <= total_score < 90
        assert grade == SignalGrade.A_GRADE
    
    def test_b_grade_signal(self, score_engine):
        """测试 B 级信号"""
        total_score, grade = score_engine.fuse_scores(
            trend_score=20,
            pullback_score=10,
            momentum_score=10,
            macro_alignment_score=10,
            regime=MarketRegime.CHOP
        )
        
        assert total_score < 70
        assert grade == SignalGrade.B_GRADE


class TestMTFTradingSystem:
    """测试完整 MTF 系统"""
    
    @pytest.fixture
    def system(self):
        return create_mtf_system()
    
    def test_full_analysis_bullish(self, system):
        """测试完整多头分析"""
        # 4H 数据 - 多头趋势
        close_4h = np.linspace(100, 150, 200)
        
        # 1H 数据 - 强趋势
        close_1h = np.linspace(140, 150, 200)
        high_1h = close_1h + 2
        low_1h = close_1h - 2
        volume_1h = np.random.uniform(800, 1200, 200)
        
        # 15m 数据 - 动能启动
        close_15m = np.linspace(145, 150, 200)
        
        signal = system.analyze(
            close_4h=close_4h,
            high_1h=high_1h,
            low_1h=low_1h,
            close_1h=close_1h,
            volume_1h=volume_1h,
            close_15m=close_15m
        )
        
        if signal:
            assert signal.direction == TrendDirection.BULLISH
            assert signal.grade in [SignalGrade.S_GRADE, SignalGrade.A_GRADE]
            assert signal.score >= 70
            assert signal.risk_reward >= 2.0
    
    def test_full_analysis_chop_rejection(self, system):
        """测试震荡市场拒绝"""
        # 4H 数据
        close_4h = np.random.normal(125, 5, 200)
        
        # 1H 数据 - 震荡
        close_1h = np.random.normal(125, 2, 200)
        high_1h = close_1h + 2
        low_1h = close_1h - 2
        volume_1h = np.random.uniform(800, 1200, 200)
        
        # 15m 数据
        close_15m = np.random.normal(125, 1, 200)
        
        signal = system.analyze(
            close_4h=close_4h,
            high_1h=high_1h,
            low_1h=low_1h,
            close_1h=close_1h,
            volume_1h=volume_1h,
            close_15m=close_15m
        )
        
        # 震荡市场应该返回 None 或低分信号
        if signal:
            assert signal.grade == SignalGrade.B_GRADE
    
    def test_4h_veto(self, system):
        """测试 4H 一票否决"""
        # 4H 数据 - 空头趋势
        close_4h = np.linspace(150, 100, 200)
        
        # 1H 数据 - 假装多头
        close_1h = np.linspace(110, 120, 200)
        high_1h = close_1h + 2
        low_1h = close_1h - 2
        volume_1h = np.random.uniform(800, 1200, 200)
        
        # 15m 数据
        close_15m = np.linspace(115, 120, 200)
        
        signal = system.analyze(
            close_4h=close_4h,
            high_1h=high_1h,
            low_1h=low_1h,
            close_1h=close_1h,
            volume_1h=volume_1h,
            close_15m=close_15m
        )
        
        # 4H 空头时，不应该有做多信号
        if signal:
            assert signal.direction != TrendDirection.BULLISH


class TestMTFConfig:
    """测试配置"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = MTFConfig()
        
        assert config.ema_fast == 21
        assert config.ema_medium == 55
        assert config.ema_slow == 200
        assert config.score_pass_threshold == 70
        assert config.max_risk_per_trade == 0.015
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = MTFConfig(
            ema_fast=20,
            max_risk_per_trade=0.02
        )
        
        assert config.ema_fast == 20
        assert config.max_risk_per_trade == 0.02


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
