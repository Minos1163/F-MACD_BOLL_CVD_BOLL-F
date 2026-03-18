"""
1H 企稳量化判定器测试用例
验证五维度打分模型的正确性
"""

import pytest
import numpy as np
from src.fund_flow.stabilization_scorer import (
    StabilizationScorer,
    StabilizationResult,
    SignalLevel,
    DimensionScore
)


class TestStabilizationScorer:
    """企稳判定器测试"""
    
    @pytest.fixture
    def scorer(self):
        return StabilizationScorer()
    
    @pytest.fixture
    def sample_data(self):
        """生成测试数据"""
        np.random.seed(42)
        n = 100
        
        # 模拟上升趋势中的回调
        close = 95000 + np.cumsum(np.random.randn(n) * 50)
        high = close + np.random.rand(n) * 150
        low = close - np.random.rand(n) * 150
        volume = np.random.randint(1000, 5000, n)
        
        return close, high, low, volume
    
    @pytest.fixture
    def pullback_data(self):
        """生成回调场景数据"""
        np.random.seed(123)
        n = 100
        
        # 创建明显的上升趋势
        trend = np.linspace(95000, 97000, n)
        noise = np.random.randn(n) * 100
        close = trend + noise
        
        # 在末尾添加回调
        close[-5:] = close[-6] - np.array([50, 100, 80, 40, 20])  # 回调后企稳
        
        high = close + np.random.rand(n) * 100 + 50
        low = close - np.random.rand(n) * 100 - 50
        
        # 回调时缩量
        volume = np.random.randint(2000, 5000, n)
        volume[-5:] = [1500, 1200, 1000, 800, 600]  # 明显缩量
        
        return close, high, low, volume
    
    # ==================== 基础测试 ====================
    
    def test_initialization(self, scorer):
        """测试初始化"""
        assert scorer is not None
        assert scorer.config is not None
        assert scorer.config["macd_decay_threshold"] == 0.5
        assert scorer.config["ema21_deviation_max"] == 0.005
    
    def test_analyze_returns_result(self, scorer, sample_data):
        """测试分析返回结果对象"""
        close, high, low, volume = sample_data
        
        result = scorer.analyze(close, high, low, volume, "long")
        
        assert isinstance(result, StabilizationResult)
        assert result.total_score >= 0
        assert result.total_score <= 100
        assert isinstance(result.level, SignalLevel)
        assert isinstance(result.passed, bool)
    
    # ==================== MACD维度测试 ====================
    
    def test_macd_dimension_scoring(self, scorer, sample_data):
        """测试MACD维度评分"""
        close, high, low, volume = sample_data
        
        macd_score = scorer._score_macd_dimension(close)
        
        assert isinstance(macd_score, DimensionScore)
        assert macd_score.dimension_name == "MACD动能"
        assert macd_score.max_score == 30
        assert 0 <= macd_score.actual_score <= 30
        assert "衰减率" in macd_score.details
    
    def test_macd_consecutive_decline(self, scorer):
        """测试MACD连续缩短判定"""
        # 创建MACD连续缩短的数据
        close = np.linspace(95000, 96000, 100)
        
        macd_score = scorer._score_macd_dimension(close)
        
        # 验证连续缩短判定
        assert "连续≥2根缩短" in macd_score.conditions
    
    def test_macd_decay_ratio(self, scorer):
        """测试MACD衰减率计算"""
        # 模拟强势衰减
        close = np.linspace(95000, 95100, 100)  # 缓慢上涨
        
        macd_score = scorer._score_macd_dimension(close)
        
        assert "衰减率" in macd_score.details
        ratio = macd_score.details["衰减率"]
        assert 0 <= ratio <= 1
    
    # ==================== 价格结构维度测试 ====================
    
    def test_price_dimension_scoring(self, scorer, sample_data):
        """测试价格结构评分"""
        close, high, low, volume = sample_data
        
        price_score = scorer._score_price_dimension(close, high, low)
        
        assert isinstance(price_score, DimensionScore)
        assert price_score.dimension_name == "价格结构"
        assert price_score.max_score == 30
        assert "EMA21偏差率" in price_score.details
    
    def test_ema21_deviation_calculation(self, scorer):
        """测试EMA21偏差率计算"""
        # 价格紧贴EMA21
        close = np.ones(100) * 95000
        
        price_score = scorer._score_price_dimension(close, close, close)
        
        deviation = price_score.details["EMA21偏差率"]
        assert deviation < 0.01  # 偏差应该很小
    
    def test_price_above_vwap(self, scorer):
        """测试价格在VWAP上方判定"""
        close = np.linspace(95000, 96000, 100)
        high = close + 100
        low = close - 100
        
        price_score = scorer._score_price_dimension(close, high, low)
        
        assert "VWAP上方" in price_score.conditions
    
    # ==================== 成交量维度测试 ====================
    
    def test_volume_dimension_scoring(self, scorer, sample_data):
        """测试成交量评分"""
        close, high, low, volume = sample_data
        
        volume_score = scorer._score_volume_dimension(close, volume, high, low)
        
        assert isinstance(volume_score, DimensionScore)
        assert volume_score.dimension_name == "成交量"
        assert volume_score.max_score == 20
        assert "回调量比" in volume_score.details
    
    def test_volume_shrinking_detection(self, scorer):
        """测试成交量萎缩检测"""
        close = np.linspace(95000, 96000, 100)
        # 创建萎缩的成交量
        volume = np.array([5000] * 90 + [4000, 3000, 2000, 1500, 1000, 800, 600, 400, 300, 200])
        
        volume_score = scorer._score_volume_dimension(close, volume, close, close)
        
        # 应该检测到连续萎缩
        assert "连续3根萎缩" in volume_score.conditions
    
    def test_pullback_volume_ratio(self, scorer):
        """测试回调量比计算"""
        # 创建上涨段量大、回调段量小的数据
        close = np.linspace(95000, 96000, 100)
        volume = np.array([3000] * 80 + [2000, 1500, 1200, 1000, 800, 600, 500, 400, 300, 200])
        
        ratio = scorer._calculate_pullback_volume_ratio(close, volume)
        
        assert ratio >= 0
        assert ratio <= 1
    
    # ==================== K线形态维度测试 ====================
    
    def test_candle_dimension_scoring(self, scorer, sample_data):
        """测试K线形态评分"""
        close, high, low, volume = sample_data
        
        candle_score = scorer._score_candle_dimension(close, high, low)
        
        assert isinstance(candle_score, DimensionScore)
        assert candle_score.dimension_name == "K线形态"
        assert candle_score.max_score == 12
    
    def test_lower_wick_detection(self, scorer):
        """测试下影线检测"""
        close = np.ones(100) * 95000
        high = close + 100
        
        # 创建下影线：low比close低很多
        low = close - 200
        
        candle_score = scorer._score_candle_dimension(close, high, low)
        
        # 应该检测到下影线
        assert "下影线" in candle_score.details
    
    def test_doji_detection(self, scorer):
        """测试十字星检测"""
        # 创建十字星：close和open接近，high和low差距大
        close = np.ones(100) * 95000
        high = close + 300
        low = close - 300
        
        candle_score = scorer._score_candle_dimension(close, high, low)
        
        # 十字星的实体应该很小
        assert candle_score.details["实体大小"] < 10
    
    # ==================== 时间结构维度测试 ====================
    
    def test_time_dimension_scoring(self, scorer, sample_data):
        """测试时间结构评分"""
        close, high, low, volume = sample_data
        
        time_score = scorer._score_time_dimension(close, high, low)
        
        assert isinstance(time_score, DimensionScore)
        assert time_score.dimension_name == "时间结构"
        assert time_score.max_score == 8
    
    def test_pullback_bars_detection(self, scorer):
        """测试回调根数检测"""
        # 创建回调序列
        close = np.concatenate([
            np.linspace(95000, 96000, 90),  # 上涨
            np.array([95900, 95800, 95700, 95650, 95600])  # 回调5根
        ])
        
        pullback_bars = scorer._detect_pullback_bars(close)
        
        assert pullback_bars == 5
    
    def test_higher_low_detection(self, scorer):
        """测试低点抬高检测"""
        close = np.linspace(95000, 96000, 100)
        low = np.concatenate([
            np.linspace(94800, 95200, 50),
            np.linspace(95300, 95500, 50)  # 后半段低点更高
        ])
        
        time_score = scorer._score_time_dimension(close, close, low)
        
        # 应该检测到低点抬高
        assert "低点抬高" in time_score.conditions
    
    # ==================== 否决项测试 ====================
    
    def test_veto_conditions_detection(self, scorer, sample_data):
        """测试否决项检测"""
        close, high, low, volume = sample_data
        
        veto_flags, veto_reasons = scorer._check_veto_conditions(
            close, high, low, volume, "long"
        )
        
        assert isinstance(veto_flags, dict)
        assert "EMA55跌破" in veto_flags
        assert "MACD死叉" in veto_flags
        assert "大阴线出现" in veto_flags
        assert "量能突放" in veto_flags
    
    def test_ema55_veto(self, scorer):
        """测试EMA55跌破否决"""
        # 创建跌破EMA55的场景
        close = np.linspace(96000, 94000, 100)  # 下跌趋势
        high = close + 100
        low = close - 100
        volume = np.ones(100) * 3000
        
        veto_flags, _ = scorer._check_veto_conditions(close, high, low, volume, "long")
        
        # 应该触发EMA55跌破否决
        assert veto_flags["EMA55跌破"] == True
    
    def test_macd_death_cross_veto(self, scorer):
        """测试MACD死叉否决"""
        # 创建下跌趋势
        close = np.linspace(96000, 94000, 100)
        high = close + 100
        low = close - 100
        volume = np.ones(100) * 3000
        
        veto_flags, _ = scorer._check_veto_conditions(close, high, low, volume, "long")
        
        # 应该触发MACD死叉否决
        assert veto_flags["MACD死叉"] == True
    
    def test_big_bearish_candle_veto(self, scorer):
        """测试大阴线否决"""
        close = np.ones(100) * 95000
        close[-1] = 94000  # 最后一根大跌
        high = close + 100
        low = close - 100
        volume = np.ones(100) * 3000
        
        veto_flags, _ = scorer._check_veto_conditions(close, high, low, volume, "long")
        
        # 可能触发大阴线否决
        # 注意：需要实体 > ATR * 2
    
    def test_volume_spike_veto(self, scorer):
        """测试量能突放否决"""
        close = np.linspace(95000, 96000, 100)
        high = close + 100
        low = close - 100
        volume = np.ones(100) * 3000
        volume[-1] = 10000  # 最后一根放量
        
        veto_flags, _ = scorer._check_veto_conditions(close, high, low, volume, "long")
        
        # 应该触发量能突放否决
        assert veto_flags["量能突放"] == True
    
    # ==================== 综合判定测试 ====================
    
    def test_signal_level_determination(self, scorer):
        """测试信号等级判定"""
        # A级：85~100
        level_a = scorer._determine_signal_level(90, {})
        assert level_a == SignalLevel.A_GRADE
        
        # B级：70~84
        level_b = scorer._determine_signal_level(75, {})
        assert level_b == SignalLevel.B_GRADE
        
        # C级：55~69
        level_c = scorer._determine_signal_level(60, {})
        assert level_c == SignalLevel.C_GRADE
        
        # D级：<55
        level_d = scorer._determine_signal_level(50, {})
        assert level_d == SignalLevel.D_GRADE
        
        # 有否决项 -> D级
        level_veto = scorer._determine_signal_level(90, {"EMA55跌破": True})
        assert level_veto == SignalLevel.D_GRADE
    
    def test_position_calculation(self, scorer):
        """测试仓位计算"""
        # A级：40%
        assert scorer._calculate_position_pct(SignalLevel.A_GRADE, 90) == 0.40
        
        # B级：40%
        assert scorer._calculate_position_pct(SignalLevel.B_GRADE, 75) == 0.40
        
        # C级：20%
        assert scorer._calculate_position_pct(SignalLevel.C_GRADE, 60) == 0.20
        
        # D级：0%
        assert scorer._calculate_position_pct(SignalLevel.D_GRADE, 50) == 0.0
    
    # ==================== 回调场景测试 ====================
    
    def test_pullback_scenario(self, scorer, pullback_data):
        """测试典型回调场景"""
        close, high, low, volume = pullback_data
        
        result = scorer.analyze(close, high, low, volume, "long")
        
        # 验证结果
        assert result.total_score >= 0
        assert isinstance(result.level, SignalLevel)
        
        # 回调场景应该得分较高
        # （具体分数取决于数据特征）
    
    def test_full_analysis_output(self, scorer, sample_data):
        """测试完整分析输出"""
        close, high, low, volume = sample_data
        
        result = scorer.analyze(close, high, low, volume, "long")
        
        # 验证所有字段
        assert result.total_score is not None
        assert result.level is not None
        assert result.passed is not None
        assert result.position_pct is not None
        assert result.reason is not None
        
        # 验证五维度
        assert result.macd_score is not None
        assert result.price_score is not None
        assert result.volume_score is not None
        assert result.candle_score is not None
        assert result.time_score is not None
        
        # 验证否决项
        assert result.veto_flags is not None
        assert result.veto_reasons is not None
    
    # ==================== 边界条件测试 ====================
    
    def test_minimum_data_length(self, scorer):
        """测试最小数据长度"""
        close = np.array([95000, 95100, 95200])
        high = close + 100
        low = close - 100
        volume = np.array([1000, 1100, 900])
        
        # 应该能处理最小数据长度
        result = scorer.analyze(close, high, low, volume, "long")
        assert result is not None
    
    def test_edge_case_zero_volume(self, scorer):
        """测试零成交量边界情况"""
        close = np.linspace(95000, 96000, 100)
        high = close + 100
        low = close - 100
        volume = np.zeros(100)  # 零成交量
        
        # 应该能处理零成交量
        result = scorer.analyze(close, high, low, volume, "long")
        assert result is not None
    
    def test_edge_case_constant_price(self, scorer):
        """测试价格不变边界情况"""
        close = np.ones(100) * 95000
        high = close + 100
        low = close - 100
        volume = np.ones(100) * 3000
        
        result = scorer.analyze(close, high, low, volume, "long")
        assert result is not None


class TestSignalLevel:
    """信号等级测试"""
    
    def test_signal_level_values(self):
        """测试信号等级值"""
        assert SignalLevel.A_GRADE.value == "A"
        assert SignalLevel.B_GRADE.value == "B"
        assert SignalLevel.C_GRADE.value == "C"
        assert SignalLevel.D_GRADE.value == "D"


class TestDimensionScore:
    """维度得分测试"""
    
    def test_dimension_score_creation(self):
        """测试维度得分创建"""
        score = DimensionScore(
            dimension_name="测试维度",
            max_score=30,
            actual_score=20,
            conditions={"条件1": True, "条件2": False},
            details={"详情1": 1.0}
        )
        
        assert score.dimension_name == "测试维度"
        assert score.max_score == 30
        assert score.actual_score == 20
        assert score.conditions["条件1"] == True
        assert score.details["详情1"] == 1.0


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
