"""
跨周期冲突处理模块测试

测试覆盖：
- 冲突强度评分
- 四种典型冲突形态识别
- 等待窗口管理
- 三条解除路径评估
- 观察信号管理
- 特殊情况处理
"""

import pytest
import numpy as np
from datetime import datetime, timedelta

from src.fund_flow.timeframe_conflict_resolver import (
    # 枚举
    ConflictIntensity, ConflictPattern, ResolutionPath, ConflictState,
    # 配置
    ConflictResolverConfig,
    # 数据类
    ConflictScore, ConflictScoreDimension, WaitingWindow, ObservationSignal,
    ActiveObservation, ConflictContext, ResolutionResult,
    # 核心类
    TechnicalTools, ConflictScorer, WaitingWindowManager,
    ObservationManager, PathEvaluator, TimeframeConflictResolver,
    # 便捷函数
    create_conflict_resolver, quick_conflict_check,
    # 补充功能
    ConflictRecord, ConflictLearner, SentimentFilter, SentimentCheckResult,
    ConflictHistoryManager, generate_conflict_review_template
)


# ==================== 测试数据生成 ====================

def generate_ohlcv_data(length: int = 100, trend: str = 'up', volatility: float = 0.02) -> dict:
    """
    生成测试用OHLCV数据
    
    Args:
        length: 数据长度
        trend: 趋势方向 ('up', 'down', 'range')
        volatility: 波动率
    """
    np.random.seed(42)
    
    base_price = 50000
    prices = [base_price]
    
    for i in range(length - 1):
        if trend == 'up':
            change = np.random.uniform(-volatility, volatility * 2)
        elif trend == 'down':
            change = np.random.uniform(-volatility * 2, volatility)
        else:  # range
            change = np.random.uniform(-volatility, volatility)
        
        prices.append(prices[-1] * (1 + change))
    
    close = np.array(prices)
    
    # 生成高低价
    high = close * (1 + np.random.uniform(0, volatility * 0.5, length))
    low = close * (1 - np.random.uniform(0, volatility * 0.5, length))
    open_price = close + np.random.uniform(-volatility * 0.3, volatility * 0.3, length) * close
    volume = np.random.uniform(100, 1000, length)
    
    return {
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }


def generate_pullback_scenario(pullback_depth: float = 0.03, pullback_bars: int = 5) -> dict:
    """
    生成回调场景数据
    
    Args:
        pullback_depth: 回调深度（百分比）
        pullback_bars: 回调K线数
    """
    np.random.seed(42)
    
    # 上涨趋势
    length = 50
    close = np.zeros(length)
    close[0] = 50000
    
    # 前30根上涨
    for i in range(1, 30):
        close[i] = close[i-1] * (1 + np.random.uniform(0.001, 0.015))
    
    peak_price = close[29]
    
    # 回调
    pullback_start = 30
    for i in range(pullback_start, pullback_start + pullback_bars):
        if i < length:
            close[i] = close[i-1] * (1 - pullback_depth / pullback_bars)
    
    # 恢复
    for i in range(pullback_start + pullback_bars, length):
        close[i] = close[i-1] * (1 + np.random.uniform(0, 0.01))
    
    high = close * 1.005
    low = close * 0.995
    volume = np.random.uniform(100, 1000, length)
    
    return {
        'close': close,
        'high': high,
        'low': low,
        'volume': volume,
        'peak_price': peak_price,
        'pullback_bars': pullback_bars
    }


# ==================== TechnicalTools 测试 ====================

class TestTechnicalTools:
    """技术工具测试"""
    
    def test_calculate_ema(self):
        """测试EMA计算"""
        prices = np.array([100, 102, 101, 103, 105, 104, 106])
        ema = TechnicalTools.calculate_ema(prices, 5)
        
        assert len(ema) == len(prices)
        assert ema[0] == prices[0]  # 第一个值等于价格本身
        # EMA应该平滑价格
        assert not np.isnan(ema).any()
    
    def test_calculate_macd(self):
        """测试MACD计算"""
        prices = np.array([100 + i + np.random.uniform(-2, 2) for i in range(50)])
        macd_line, signal_line, histogram = TechnicalTools.calculate_macd(prices)
        
        assert len(macd_line) == len(prices)
        assert len(signal_line) == len(prices)
        assert len(histogram) == len(prices)
        # histogram = macd_line - signal_line
        np.testing.assert_array_almost_equal(histogram, macd_line - signal_line, decimal=10)
    
    def test_calculate_atr(self):
        """测试ATR计算"""
        high = np.array([105, 106, 104, 107, 108])
        low = np.array([98, 99, 97, 100, 101])
        close = np.array([102, 103, 101, 104, 105])
        
        atr = TechnicalTools.calculate_atr(high, low, close, period=5)
        
        assert len(atr) == len(close)
        assert atr[-1] > 0  # ATR应该为正
    
    def test_detect_divergence_bullish(self):
        """测试看涨背离检测"""
        # 底背离：价格创新低，但MACD绿柱未创新低（绿柱缩短）
        # 价格序列：先创新低，再创新低
        # MACD序列：先创新低，但第二次价格创新低时MACD更高
        prices = np.array([100, 95, 90, 92, 88, 85, 83])  # 持续下跌
        histogram = np.array([0, -2, -3, -2, -2.5, -2, -1])  # 绿柱先扩大后缩短
        
        divergence = TechnicalTools.detect_divergence(prices, histogram, lookback=7)
        
        # 验证背离检测逻辑正确运行
        assert divergence in ["bullish", "none"]
    
    def test_detect_divergence_bearish(self):
        """测试看跌背离检测"""
        # 顶背离：价格创新高，但MACD红柱未创新高（红柱缩短）
        prices = np.array([85, 88, 92, 90, 95, 98, 100])  # 持续上涨
        histogram = np.array([0, 2, 3, 2, 2.5, 2, 1.5])  # 红柱先扩大后缩短
        
        divergence = TechnicalTools.detect_divergence(prices, histogram, lookback=7)
        
        # 验证背离检测逻辑正确运行
        assert divergence in ["bearish", "none"]
    
    def test_count_consecutive_bars(self):
        """测试连续K线计数"""
        prices = np.array([100, 98, 96, 94, 96, 98, 100])
        ema = np.array([95, 95, 95, 95, 95, 95, 95])
        
        # 计算在EMA下方的连续根数
        count_below = TechnicalTools.count_consecutive_bars(prices, ema, below=True)
        # 从后往前数，最后两根在EMA上方，再往前3根在下方
        assert count_below == 0  # 最后一根在上方
        
        # 修改测试数据 - 所有都在下方
        prices2 = np.array([94, 92, 90, 88, 86, 84, 82])
        count_below2 = TechnicalTools.count_consecutive_bars(prices2, ema, below=True)
        assert count_below2 == 7  # 所有都在下方


# ==================== ConflictScorer 测试 ====================

class TestConflictScorer:
    """冲突评分器测试"""
    
    @pytest.fixture
    def scorer(self):
        return ConflictScorer(ConflictResolverConfig())
    
    @pytest.fixture
    def pullback_data(self):
        return generate_pullback_scenario(pullback_depth=0.02, pullback_bars=4)
    
    def test_weak_conflict_scoring(self, scorer, pullback_data):
        """测试弱冲突评分"""
        # 生成4H数据（上涨趋势）
        data_4h = generate_ohlcv_data(length=100, trend='up')
        
        # 计算1H数据
        close_1h = pullback_data['close']
        high_1h = pullback_data['high']
        low_1h = pullback_data['low']
        volume_1h = pullback_data['volume']
        
        score = scorer.calculate_score(
            close_1h, high_1h, low_1h, volume_1h,
            data_4h['close'], data_4h['high'], data_4h['low']
        )
        
        assert isinstance(score, ConflictScore)
        assert 0 <= score.total_score <= 12
        assert isinstance(score.intensity, ConflictIntensity)
        assert isinstance(score.pattern, ConflictPattern)
        assert len(score.dimensions) == 6
    
    def test_strong_conflict_detection(self, scorer):
        """测试强冲突检测"""
        # 生成深度回调数据
        data = generate_pullback_scenario(pullback_depth=0.08, pullback_bars=10)
        
        # 4H数据（趋势减弱）
        data_4h = generate_ohlcv_data(length=100, trend='range')
        
        score = scorer.calculate_score(
            data['close'], data['high'], data['low'], data['volume'],
            data_4h['close'], data_4h['high'], data_4h['low']
        )
        
        # 深度回调应该产生较高分数
        assert score.total_score >= 4  # 至少中等冲突
    
    def test_pattern_classification(self, scorer):
        """测试形态分类"""
        # 生成短期回调数据
        data = generate_pullback_scenario(pullback_depth=0.015, pullback_bars=2)
        data_4h = generate_ohlcv_data(length=100, trend='up')
        
        score = scorer.calculate_score(
            data['close'], data['high'], data['low'], data['volume'],
            data_4h['close'], data_4h['high'], data_4h['low']
        )
        
        # 短期回调应该是弱冲突
        assert score.intensity in [ConflictIntensity.WEAK, ConflictIntensity.MEDIUM]
    
    def test_score_dimension_breakdown(self, scorer):
        """测试评分维度分解"""
        data = generate_ohlcv_data(length=100, trend='up')
        data_4h = generate_ohlcv_data(length=100, trend='up')
        
        score = scorer.calculate_score(
            data['close'], data['high'], data['low'], data['volume'],
            data_4h['close'], data_4h['high'], data_4h['low']
        )
        
        # 检查各维度
        dimension_names = [d.name for d in score.dimensions]
        expected_names = [
            "1H MACD位置",
            "1H价格与EMA55关系",
            "1H下跌持续时间",
            "1H下跌幅度",
            "4H MACD状态",
            "1H成交量变化"
        ]
        
        for name in expected_names:
            assert name in dimension_names
        
        # 每个维度分数应该在0-2之间
        for dim in score.dimensions:
            assert 0 <= dim.score <= 2


# ==================== WaitingWindowManager 测试 ====================

class TestWaitingWindowManager:
    """等待窗口管理器测试"""
    
    @pytest.fixture
    def manager(self):
        return WaitingWindowManager(ConflictResolverConfig())
    
    def test_create_weak_window(self, manager):
        """测试创建弱冲突窗口"""
        window = manager.create_window(
            ConflictIntensity.WEAK,
            ema55_1h=50000,
            ema55_4h=49000,
            ema200_4h=48000
        )
        
        assert window.time_limit == 5  # 5根1H K线
        assert window.time_limit_unit == '1h'
        assert window.price_limit == 50000 * 0.997  # EMA55下方0.3%
        assert window.momentum_limit == 0.30
    
    def test_create_medium_window(self, manager):
        """测试创建中冲突窗口"""
        window = manager.create_window(
            ConflictIntensity.MEDIUM,
            ema55_1h=50000,
            ema55_4h=49000,
            ema200_4h=48000
        )
        
        assert window.time_limit == 8  # 8根1H K线
        assert window.time_limit_unit == '1h'
        assert window.price_limit == 49000 * 0.995  # 4H EMA55下方0.5%
    
    def test_create_strong_window(self, manager):
        """测试创建强冲突窗口"""
        window = manager.create_window(
            ConflictIntensity.STRONG,
            ema55_1h=50000,
            ema55_4h=49000,
            ema200_4h=48000
        )
        
        assert window.time_limit == 3  # 3根4H K线
        assert window.time_limit_unit == '4h'
        assert window.price_limit == 48000 * 0.995  # 4H EMA200下方0.5%
    
    def test_window_expiration(self, manager):
        """测试窗口过期"""
        window = manager.create_window(
            ConflictIntensity.WEAK,
            ema55_1h=50000,
            ema55_4h=49000,
            ema200_4h=48000
        )
        
        assert not window.is_expired()
        
        window.bars_elapsed = 5
        assert window.is_expired()
        
        window.bars_elapsed = 3
        assert window.remaining_bars() == 2
    
    def test_check_window_limits(self, manager):
        """测试窗口上限检查"""
        window = manager.create_window(
            ConflictIntensity.WEAK,
            ema55_1h=50000,
            ema55_4h=49000,
            ema200_4h=48000
        )
        
        # 检查未触发 - 价格在合理范围，时间未到，动能未恶化
        # 弱冲突窗口价格下限是 EMA55 * (1 - 0.003) = 50000 * 0.997 = 49850
        hit, reason = manager.check_window_limits(
            window, current_price=49900, current_bars=3, macd_shrink_pct=0.2
        )
        assert not hit
        
        # 检查时间触发
        hit, reason = manager.check_window_limits(
            window, current_price=49900, current_bars=5, macd_shrink_pct=0.2
        )
        assert hit
        assert "时间上限" in reason
        
        # 检查价格触发 - 价格低于下限49850
        hit, reason = manager.check_window_limits(
            window, current_price=49000, current_bars=3, macd_shrink_pct=0.2
        )
        assert hit
        assert "价格下限" in reason
        
        # 检查动能触发
        hit, reason = manager.check_window_limits(
            window, current_price=49900, current_bars=3, macd_shrink_pct=0.5
        )
        assert hit
        assert "动能上限" in reason


# ==================== ObservationManager 测试 ====================

class TestObservationManager:
    """观察信号管理器测试"""
    
    @pytest.fixture
    def manager(self):
        return ObservationManager(ConflictResolverConfig())
    
    def test_create_observation(self, manager):
        """测试创建观察状态"""
        obs = manager.create_observation()
        
        assert isinstance(obs, ActiveObservation)
        assert len(obs.support_signals) == 5
        assert len(obs.denial_signals) == 5
        
        # 检查信号属性
        for signal in obs.support_signals:
            assert signal.supports_trend == True
            assert isinstance(signal.signal_type, str)
        
        for signal in obs.denial_signals:
            assert signal.supports_trend == False
    
    def test_update_observation(self, manager):
        """测试更新观察信号"""
        obs = manager.create_observation()
        
        # 模拟K线数据
        candle_1h = {
            'open': 50000,
            'high': 50500,
            'low': 49800,
            'close': 50200,
            'volume': 500,
            'volume_shrinking': True,
            'volume_expanding': False
        }
        
        obs = manager.update_observation(
            obs,
            candle_1h,
            macd_1h_histogram=-0.5,
            macd_1h_prev=-1.0,
            price=50200,
            ema21_4h=49000,
            macd_4h_shrink_pct=0.2,
            has_4h_divergence=False
        )
        
        # 检查更新后的计数
        assert obs.support_count >= 0
        assert obs.denial_count >= 0
    
    def test_evaluate_observation(self, manager):
        """测试观察评估"""
        obs = manager.create_observation()
        
        # 模拟触发多个支持信号
        obs.support_signals[0].triggered = True
        obs.support_signals[1].triggered = True
        obs.support_signals[2].triggered = True
        obs.update_counts()
        
        action, reason = manager.evaluate_observation(obs)
        
        assert action == "continue_wait"
        assert "支持信号3项" in reason
        
        # 重置并模拟触发多个否定信号
        for s in obs.support_signals:
            s.triggered = False
        obs.denial_signals[0].triggered = True
        obs.denial_signals[1].triggered = True
        obs.denial_signals[2].triggered = True
        obs.update_counts()
        
        action, reason = manager.evaluate_observation(obs)
        
        # 根据逻辑，否定信号>=3时应该考虑路径三
        # 但同时支持信号=0，所以结果应该是consider_path3
        assert "否定信号" in reason


# ==================== PathEvaluator 测试 ====================

class TestPathEvaluator:
    """路径评估器测试"""
    
    @pytest.fixture
    def evaluator(self):
        return PathEvaluator(ConflictResolverConfig())
    
    @pytest.fixture
    def mock_context(self):
        """创建模拟冲突上下文"""
        config = ConflictResolverConfig()
        
        score = ConflictScore(
            total_score=5,
            intensity=ConflictIntensity.MEDIUM,
            dimensions=[],
            pattern=ConflictPattern.DEEP_PULLBACK,
            reason="测试"
        )
        
        window = WaitingWindow(
            time_limit=8,
            time_limit_unit='1h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.5
        )
        
        return ConflictContext(
            conflict_id="test_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
    
    def test_evaluate_path1_recovery_success(self, evaluator, mock_context):
        """测试路径一恢复成功"""
        result = evaluator.evaluate_path1_recovery(
            mock_context,
            stabilization_score=80,  # 超过门槛
            macd_4h_shrink_pct=0.3   # 未超过上限
        )
        
        assert result.resolved == True
        assert result.path == ResolutionPath.PATH_1_RECOVERY
        assert result.action == "entry"
        assert result.position_pct == 0.20  # 中冲突首仓20%
    
    def test_evaluate_path1_recovery_fail_score(self, evaluator, mock_context):
        """测试路径一恢复失败（分数不足）"""
        result = evaluator.evaluate_path1_recovery(
            mock_context,
            stabilization_score=60,  # 低于门槛
            macd_4h_shrink_pct=0.3
        )
        
        assert result.resolved == False
        assert "企稳打分" in result.reason
    
    def test_evaluate_path1_recovery_fail_momentum(self, evaluator, mock_context):
        """测试路径一恢复失败（动能恶化）"""
        result = evaluator.evaluate_path1_recovery(
            mock_context,
            stabilization_score=80,
            macd_4h_shrink_pct=0.6   # 超过上限
        )
        
        assert result.resolved == False
        assert "MACD恶化" in result.reason
    
    def test_evaluate_path2_timeout(self, evaluator, mock_context):
        """测试路径二超时"""
        # 时间超时
        mock_context.waiting_window.bars_elapsed = 8
        result = evaluator.evaluate_path2_timeout(
            mock_context,
            current_price=50000,
            current_bars=8,
            macd_4h_shrink_pct=0.3
        )
        
        assert result.resolved == True
        assert result.path == ResolutionPath.PATH_2_TIMEOUT
        assert result.action == "abandon"
    
    def test_evaluate_path3_reversal_prerequisite_not_met(self, evaluator, mock_context):
        """测试路径三前序条件不满足（非强冲突）"""
        close_4h = np.array([52000, 51500, 51000, 50500, 50000])
        histogram_4h = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        
        # mock_context 是 MEDIUM 强度，不满足强冲突前置条件
        result = evaluator.evaluate_path3_reversal(
            mock_context,
            close_4h=close_4h,
            histogram_4h=histogram_4h,
            ema21_4h=51000,
            ema55_4h=50500,
            consecutive_below_ema55=5,
            short_signal_count=4
        )
        
        # 前序条件不满足
        assert result.resolved == False
        assert "前序条件不满足" in result.reason
        assert "非强冲突" in result.reason
    
    def test_evaluate_path3_reversal_success(self, evaluator):
        """测试路径三转空成功（满足所有前序条件）"""
        # 创建强冲突上下文
        config = ConflictResolverConfig()
        
        score = ConflictScore(
            total_score=9,  # 强冲突 (8-12分)
            intensity=ConflictIntensity.STRONG,
            dimensions=[],
            pattern=ConflictPattern.TREND_REVERSAL,
            reason="强冲突测试"
        )
        
        window = WaitingWindow(
            time_limit=3,
            time_limit_unit='4h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.7
        )
        window.bars_elapsed = 2  # 等待窗口已开启
        
        strong_context = ConflictContext(
            conflict_id="test_strong_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
        
        # 创建满足转空条件的数据
        close_4h = np.array([52000, 51500, 51000, 50500, 50000])
        histogram_4h = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        
        result = evaluator.evaluate_path3_reversal(
            strong_context,
            close_4h=close_4h,
            histogram_4h=histogram_4h,
            ema21_4h=51000,  # 价格低于EMA21
            ema55_4h=50500,
            consecutive_below_ema55=5,
            short_signal_count=4,
            path1_resolved=False
        )
        
        # 应该满足转空条件
        assert result.resolved == True
        assert result.path == ResolutionPath.PATH_3_REVERSAL
        assert result.action == "reverse"
    
    def test_evaluate_path3_reversal_window_not_started(self, evaluator):
        """测试路径三前序条件不满足（等待窗口未开启）"""
        config = ConflictResolverConfig()
        
        score = ConflictScore(
            total_score=9,
            intensity=ConflictIntensity.STRONG,
            dimensions=[],
            pattern=ConflictPattern.TREND_REVERSAL,
            reason="强冲突测试"
        )
        
        window = WaitingWindow(
            time_limit=3,
            time_limit_unit='4h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.7
        )
        window.bars_elapsed = 0  # 等待窗口未开启
        
        strong_context = ConflictContext(
            conflict_id="test_strong_002",
            detected_time=datetime.now(),
            state=ConflictState.DETECTED,  # 刚检测到
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
        
        close_4h = np.array([52000, 51500, 51000, 50500, 50000])
        histogram_4h = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        
        result = evaluator.evaluate_path3_reversal(
            strong_context,
            close_4h=close_4h,
            histogram_4h=histogram_4h,
            ema21_4h=51000,
            ema55_4h=50500,
            consecutive_below_ema55=5,
            short_signal_count=4
        )
        
        # 前序条件不满足：等待窗口未开启
        assert result.resolved == False
        assert "等待窗口未开启" in result.reason


# ==================== TimeframeConflictResolver 测试 ====================

class TestTimeframeConflictResolver:
    """主冲突处理系统测试"""
    
    @pytest.fixture
    def resolver(self):
        return create_conflict_resolver()
    
    @pytest.fixture
    def test_data(self):
        """生成测试数据"""
        data_4h = generate_ohlcv_data(length=100, trend='up')
        data_1h = generate_pullback_scenario(pullback_depth=0.03, pullback_bars=5)
        
        return {
            'close_4h': data_4h['close'],
            'high_4h': data_4h['high'],
            'low_4h': data_4h['low'],
            'volume_4h': data_4h['volume'],
            'close_1h': data_1h['close'],
            'high_1h': data_1h['high'],
            'low_1h': data_1h['low'],
            'volume_1h': data_1h['volume']
        }
    
    def test_detect_conflict(self, resolver, test_data):
        """测试冲突检测"""
        # 无冲突场景 - 1H也在上涨
        data_1h_up = generate_ohlcv_data(length=100, trend='up')
        
        conflict = resolver.detect_conflict(
            test_data['close_4h'], test_data['high_4h'],
            test_data['low_4h'], test_data['volume_4h'],
            data_1h_up['close'], data_1h_up['high'],
            data_1h_up['low'], data_1h_up['volume'],
            direction_4h='bullish'
        )
        
        # 无冲突应该返回None
        assert conflict is None
    
    def test_detect_conflict_exists(self, resolver, test_data):
        """测试检测到冲突"""
        # 使用回调数据创建冲突
        conflict = resolver.detect_conflict(
            test_data['close_4h'], test_data['high_4h'],
            test_data['low_4h'], test_data['volume_4h'],
            test_data['close_1h'], test_data['high_1h'],
            test_data['low_1h'], test_data['volume_1h'],
            direction_4h='bullish'
        )
        
        # 可能检测到冲突（取决于数据）
        if conflict is not None:
            assert isinstance(conflict, ConflictContext)
            assert conflict.state in [ConflictState.DETECTED, ConflictState.WAITING]
            assert isinstance(conflict.score, ConflictScore)
    
    def test_update_conflict(self, resolver):
        """测试更新冲突"""
        # 创建模拟冲突上下文
        config = ConflictResolverConfig()
        
        score = ConflictScore(
            total_score=5,
            intensity=ConflictIntensity.MEDIUM,
            dimensions=[],
            pattern=ConflictPattern.DEEP_PULLBACK,
            reason="测试"
        )
        
        window = WaitingWindow(
            time_limit=8,
            time_limit_unit='1h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.5
        )
        
        # 使用ObservationManager创建正确的观察状态
        obs_manager = ObservationManager(config)
        observation = obs_manager.create_observation()
        
        context = ConflictContext(
            conflict_id="test_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=observation,
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
        
        # 模拟4H数据
        close_4h = np.array([52000, 51500, 51000, 50500, 50000])
        histogram_4h = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        
        candle_1h = {
            'open': 50000,
            'high': 50500,
            'low': 49800,
            'close': 50200,
            'volume': 500
        }
        
        result = resolver.update_conflict(
            context,
            candle_1h,
            close_4h,
            histogram_4h,
            ema21_4h=51000,
            stabilization_score=75,
            short_signal_count=2
        )
        
        assert isinstance(result, ResolutionResult)
        assert isinstance(result.resolved, bool)
    
    def test_quick_decision(self, resolver):
        """测试快速决策"""
        # 创建模拟冲突上下文
        score = ConflictScore(
            total_score=5,
            intensity=ConflictIntensity.MEDIUM,
            dimensions=[],
            pattern=ConflictPattern.DEEP_PULLBACK,
            reason="测试"
        )
        
        window = WaitingWindow(
            time_limit=8,
            time_limit_unit='1h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.5
        )
        
        context = ConflictContext(
            conflict_id="test_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
        
        close_1h = np.array([50000, 49800, 49600, 49400, 49200])
        histogram_4h = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        
        decision, reason = resolver.quick_decision(context, close_1h, histogram_4h)
        
        assert isinstance(decision, str)
        assert isinstance(reason, str)
    
    def test_get_entry_parameters(self, resolver):
        """测试获取入场参数"""
        # 创建模拟冲突上下文
        score = ConflictScore(
            total_score=5,
            intensity=ConflictIntensity.MEDIUM,
            dimensions=[],
            pattern=ConflictPattern.DEEP_PULLBACK,
            reason="测试"
        )
        
        window = WaitingWindow(
            time_limit=8,
            time_limit_unit='1h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.5
        )
        
        context = ConflictContext(
            conflict_id="test_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000
        )
        
        params = resolver.get_entry_parameters(context)
        
        assert 'position_pct' in params
        assert 'stop_coefficient' in params
        assert 'stabilization_threshold' in params
        assert 'wait_window_bars' in params
    
    def test_get_speed_reference_card(self, resolver):
        """测试获取速查卡"""
        card = resolver.get_speed_reference_card()
        
        assert 'conflict_intensity' in card
        assert 'waiting_window' in card
        assert 'entry_standard' in card
        
        # 检查结构完整性
        assert 'weak' in card['conflict_intensity']
        assert 'medium' in card['conflict_intensity']
        assert 'strong' in card['conflict_intensity']
    
    def test_special_case_handling(self, resolver):
        """测试特殊情况处理"""
        # 创建模拟冲突上下文
        score = ConflictScore(
            total_score=5,
            intensity=ConflictIntensity.MEDIUM,
            dimensions=[],
            pattern=ConflictPattern.DEEP_PULLBACK,
            reason="测试"
        )
        
        window = WaitingWindow(
            time_limit=8,
            time_limit_unit='1h',
            price_limit=48000,
            price_limit_type="测试",
            momentum_limit=0.5
        )
        
        context = ConflictContext(
            conflict_id="test_001",
            detected_time=datetime.now(),
            state=ConflictState.WAITING,
            score=score,
            waiting_window=window,
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50000,
            ema55_1h=49500,
            ema55_4h=49000,
            ema200_4h=48000,
            macd_1h_histogram=-0.5,
            macd_4h_histogram=0.3,
            atr_value=500,
            conflict_high=51000,
            conflict_low=49000,
            daily_conflict_count=3
        )
        
        # 测试多种冲突
        action, reason = resolver.check_special_case(
            context,
            'multiple_daily_conflicts',
            {}
        )
        
        assert action == "stop_day_trading"
        assert "3次" in reason


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试"""
    
    def test_full_conflict_flow(self):
        """测试完整冲突处理流程"""
        resolver = create_conflict_resolver()
        
        # 生成4H上涨数据
        data_4h = generate_ohlcv_data(length=100, trend='up')
        
        # 生成1H回调数据
        data_1h = generate_pullback_scenario(pullback_depth=0.03, pullback_bars=5)
        
        # 检测冲突
        conflict = resolver.detect_conflict(
            data_4h['close'], data_4h['high'],
            data_4h['low'], data_4h['volume'],
            data_1h['close'], data_1h['high'],
            data_1h['low'], data_1h['volume'],
            direction_4h='bullish'
        )
        
        if conflict is not None:
            # 验证冲突上下文完整性
            assert conflict.conflict_id is not None
            assert conflict.score is not None
            assert conflict.waiting_window is not None
            
            # 获取入场参数
            params = resolver.get_entry_parameters(conflict)
            assert params is not None
            
            # 获取速查卡
            card = resolver.get_speed_reference_card()
            assert card is not None
    
    def test_quick_conflict_check(self):
        """测试快速冲突检查"""
        # 生成上涨数据
        close_4h = np.array([50000 + i * 100 for i in range(50)])
        close_1h_up = np.array([50000 + i * 50 for i in range(50)])
        close_1h_down = np.array([51000 - i * 50 for i in range(50)])
        
        # 无冲突
        assert quick_conflict_check(close_4h, close_1h_up) == False
        
        # 有冲突（1H下跌）
        assert quick_conflict_check(close_4h, close_1h_down) == True


# ==================== 参数验证测试 ====================

class TestConfigValidation:
    """配置验证测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = ConflictResolverConfig()
        
        assert config.weak_threshold == 3
        assert config.medium_threshold == 7
        assert config.weak_time_limit_1h == 5
        assert config.medium_time_limit_1h == 8
        assert config.strong_time_limit_4h == 3
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = ConflictResolverConfig(
            weak_threshold=2,
            medium_threshold=5,
            weak_time_limit_1h=4
        )
        
        assert config.weak_threshold == 2
        assert config.medium_threshold == 5
        assert config.weak_time_limit_1h == 4


# ==================== 补充功能测试：冲突历史记录与学习机制 ====================

class TestConflictRecordAndLearner:
    """冲突历史记录与学习机制测试"""
    
    def test_conflict_record_creation(self):
        """测试冲突记录创建"""
        record = ConflictRecord(
            conflict_id="test_001",
            timestamp=datetime(2026, 3, 18, 10, 0),
            conflict_level="medium",
            conflict_score=5,
            score_dimensions=[],
            wait_bars_actual=6,
            wait_bars_limit=8,
            resolution_path="path1"
        )
        
        assert record.conflict_id == "test_001"
        assert record.conflict_level == "medium"
        assert record.conflict_score == 5
        assert record.wait_bars_actual == 6
        assert record.resolution_path == "path1"
        assert record.was_correct is None  # 待验证
    
    def test_conflict_record_to_dict(self):
        """测试冲突记录序列化"""
        record = ConflictRecord(
            conflict_id="test_002",
            timestamp=datetime(2026, 3, 18, 10, 0),
            conflict_level="strong",
            conflict_score=9,
            score_dimensions=[],
            wait_bars_actual=10,
            wait_bars_limit=12,
            resolution_path="path3",
            entry_score_at_resolution=78,
            subsequent_price_change=-0.025,
            was_correct=True
        )
        
        data = record.to_dict()
        
        assert data['conflict_id'] == "test_002"
        assert data['conflict_level'] == "strong"
        assert data['was_correct'] == True
        assert data['subsequent_price_change'] == -0.025
    
    def test_conflict_learner_suggest_adjustment(self):
        """测试冲突学习器参数建议"""
        learner = ConflictLearner(min_sample_size=3)
        
        # 添加样本记录
        for i in range(5):
            record = ConflictRecord(
                conflict_id=f"test_{i:03d}",
                timestamp=datetime(2026, 3, 18, 10 + i, 0),
                conflict_level="weak",
                conflict_score=2,
                score_dimensions=[],
                wait_bars_actual=3 + i % 3,  # 3, 4, 5, 3, 4
                wait_bars_limit=5,
                resolution_path="path1"
            )
            learner.add_record(record)
        
        suggestion = learner.suggest_parameter_adjustment()
        
        assert suggestion['sample_size'] == 5
        assert 'path1' in suggestion['path_distribution']
        assert suggestion['wait_bars_suggestion']['weak'] is not None
    
    def test_conflict_learner_level_statistics(self):
        """测试冲突等级统计"""
        learner = ConflictLearner(min_sample_size=2)
        
        # 弱冲突 - 应该大部分是 path1
        for i in range(10):
            record = ConflictRecord(
                conflict_id=f"weak_{i:03d}",
                timestamp=datetime(2026, 3, 18, 10 + i, 0),
                conflict_level="weak",
                conflict_score=2,
                score_dimensions=[],
                wait_bars_actual=3,
                wait_bars_limit=5,
                resolution_path="path1" if i < 8 else "path2"  # 80% path1
            )
            learner.add_record(record)
        
        # 强冲突 - 应该 path1 占比低，path3 占比高
        for i in range(10):
            path = "path3" if i < 4 else ("path1" if i < 6 else "path2")
            record = ConflictRecord(
                conflict_id=f"strong_{i:03d}",
                timestamp=datetime(2026, 3, 18, 14 + i, 0),
                conflict_level="strong",
                conflict_score=9,
                score_dimensions=[],
                wait_bars_actual=8,
                wait_bars_limit=12,
                resolution_path=path
            )
            learner.add_record(record)
        
        stats = learner.get_level_statistics()
        
        assert stats['weak']['sample_count'] == 10
        assert stats['weak']['path1_rate'] == 0.8  # 80%
        assert stats['strong']['path3_rate'] == 0.4  # 40%


# ==================== 补充功能测试：情绪指标过滤 ====================

class TestSentimentFilter:
    """情绪指标过滤测试"""
    
    def test_sentiment_filter_extreme_fear(self):
        """测试极度恐惧检测"""
        filter = SentimentFilter()
        
        result = filter.check_sentiment_driven(
            context=None,
            fear_greed_index=15,  # 极度恐惧
            volume_history=None,
            price_history=None
        )
        
        assert result.is_sentiment_driven == True
        assert result.sentiment_type == 'fear'
        assert result.fear_greed_index == 15
    
    def test_sentiment_filter_extreme_greed(self):
        """测试极度贪婪检测"""
        filter = SentimentFilter()
        
        result = filter.check_sentiment_driven(
            context=None,
            fear_greed_index=88,  # 极度贪婪
            volume_history=None,
            price_history=None
        )
        
        assert result.is_sentiment_driven == True
        assert result.sentiment_type == 'greed'
    
    def test_sentiment_filter_neutral(self):
        """测试中性情绪"""
        filter = SentimentFilter()
        
        result = filter.check_sentiment_driven(
            context=None,
            fear_greed_index=55,  # 中性
            volume_history=None,
            price_history=None
        )
        
        assert result.is_sentiment_driven == False
        assert result.sentiment_type == 'neutral'
    
    def test_sentiment_filter_volume_spike(self):
        """测试成交量异常检测"""
        filter = SentimentFilter()
        
        # 构造成交量急剧放大后萎缩的数据
        baseline = np.ones(18) * 100  # 基线成交量
        spike = np.array([250, 280, 300, 260, 120, 80])  # 急剧放大后萎缩
        volume_history = np.concatenate([baseline, spike])
        
        result = filter.check_sentiment_driven(
            context=None,
            fear_greed_index=50,  # 正常情绪
            volume_history=volume_history,
            price_history=None
        )
        
        assert result.volume_spike_detected == True
        assert result.is_sentiment_driven == True
    
    def test_sentiment_filter_adjusted_parameters(self):
        """测试情绪驱动的参数调整"""
        filter = SentimentFilter()
        
        # 极度恐惧场景
        result = SentimentCheckResult(
            is_sentiment_driven=True,
            fear_greed_index=15,
            sentiment_type='fear',
            confidence=0.8,
            volume_spike_detected=False,
            wick_ratio=None,
            adjustment_suggestion="恐慌情绪主导"
        )
        
        params = filter.get_adjusted_parameters(
            result,
            base_time_limit=8,
            base_threshold=70,
            base_position_pct=0.2
        )
        
        assert params['adjusted'] == True
        assert params['time_limit'] == int(8 * 0.7)  # 缩短30%
        assert params['reason'] is not None


# ==================== 补充功能测试：复盘模板 ====================

class TestConflictReviewTemplate:
    """复盘模板测试"""
    
    def test_generate_review_template(self):
        """测试生成复盘报告"""
        record = ConflictRecord(
            conflict_id="review_test_001",
            timestamp=datetime(2026, 3, 18, 10, 30),
            conflict_level="medium",
            conflict_score=6,
            score_dimensions=[],
            wait_bars_actual=5,
            wait_bars_limit=8,
            resolution_path="path1",
            entry_score_at_resolution=76,
            entry_threshold=75,
            macd_4h_max_shrink_pct=0.35,
            denial_signal_triggered=False,
            subsequent_price_change=0.012,
            was_correct=True,
            improvement_notes="等待窗口时间设置合理，企稳打分门槛适当"
        )
        
        template = generate_conflict_review_template(record)
        
        assert "review_test_001" in template
        assert "6 分" in template
        assert "medium 级" in template
        assert "路径一" in template
        assert "正确" in template
    
    def test_generate_review_template_path3(self):
        """测试路径三的复盘报告"""
        record = ConflictRecord(
            conflict_id="review_test_002",
            timestamp=datetime(2026, 3, 18, 14, 0),
            conflict_level="strong",
            conflict_score=10,
            score_dimensions=[],
            wait_bars_actual=8,
            wait_bars_limit=12,
            resolution_path="path3",
            entry_score_at_resolution=None,
            subsequent_price_change=-0.035,
            was_correct=True,
            improvement_notes="转空判断正确，后续可考虑提前入场"
        )
        
        template = generate_conflict_review_template(record)
        
        assert "strong" in template
        assert "路径三" in template or "转空" in template


# ==================== 补充功能测试：历史记录管理器 ====================

class TestConflictHistoryManager:
    """历史记录管理器测试"""
    
    def test_record_conflict(self):
        """测试记录冲突"""
        manager = ConflictHistoryManager()
        
        # 创建模拟上下文
        context = ConflictContext(
            conflict_id="mgr_test_001",
            detected_time=datetime(2026, 3, 18, 10, 0),
            state=ConflictState.RESOLVED,
            score=ConflictScore(
                total_score=5,
                intensity=ConflictIntensity.MEDIUM,
                dimensions=[],
                pattern=ConflictPattern.SHORT_TERM_PULLBACK,
                reason="测试"
            ),
            waiting_window=WaitingWindow(
                time_limit=8,
                time_limit_unit='1h',
                price_limit=50000,
                price_limit_type='EMA55下方',
                momentum_limit=0.5
            ),
            observation=ActiveObservation(
                support_signals=[],
                denial_signals=[]
            ),
            direction_4h='bullish',
            current_price=50500,
            ema55_1h=50300,
            ema55_4h=49800,
            ema200_4h=48500,
            macd_1h_histogram=-50,
            macd_4h_histogram=120,
            atr_value=500
        )
        
        resolution = ResolutionResult(
            resolved=True,
            path=ResolutionPath.PATH_1_RECOVERY,
            action='entry',
            position_pct=0.2,
            stop_loss=49800,
            reason="测试通过"
        )
        
        record = manager.record_conflict(context, resolution, entry_score=76)
        
        assert record is not None
        assert record.conflict_id == "mgr_test_001"
        assert len(manager.records) == 1
    
    def test_verify_outcome(self):
        """测试事后验证"""
        manager = ConflictHistoryManager()
        
        # 添加一条记录
        record = ConflictRecord(
            conflict_id="verify_test_001",
            timestamp=datetime(2026, 3, 18, 10, 0),
            conflict_level="weak",
            conflict_score=2,
            score_dimensions=[],
            wait_bars_actual=3,
            wait_bars_limit=5,
            resolution_path="path1"
        )
        manager.records.append(record)
        manager.learner.add_record(record)
        
        # 验证结果
        updated = manager.verify_outcome(
            conflict_id="verify_test_001",
            subsequent_price_change=0.025,
            was_correct=True,
            improvement_notes="验证通过"
        )
        
        assert updated is not None
        assert updated.was_correct == True
        assert updated.subsequent_price_change == 0.025
    
    def test_get_statistics(self):
        """测试获取统计信息"""
        manager = ConflictHistoryManager()
        
        # 添加多条记录
        for i in range(5):
            record = ConflictRecord(
                conflict_id=f"stats_test_{i:03d}",
                timestamp=datetime(2026, 3, 18, 10 + i, 0),
                conflict_level="medium",
                conflict_score=5,
                score_dimensions=[],
                wait_bars_actual=5,
                wait_bars_limit=8,
                resolution_path="path1"
            )
            manager.records.append(record)
            manager.learner.add_record(record)
        
        stats = manager.get_statistics()
        
        assert stats['sample_size'] == 5
        assert 'path_distribution' in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
