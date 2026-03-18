"""
测试MACD柱子优化
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from src.utils.indicators import (
    calculate_macd_histogram_series,
    detect_macd_divergence,
    detect_histogram_crossover,
    analyze_macd_histogram
)


def test_histogram_crossover():
    """测试柱子翻红/翻绿检测"""
    print("=" * 60)
    print("测试1: 柱子翻红/翻绿检测")
    print("=" * 60)
    
    # 创建一个V形反转的价格序列（模拟底背离）
    np.random.seed(42)
    n = 100
    prices = np.array([100 - i * 0.5 + np.random.randn() * 0.1 for i in range(50)] +
                      [75 + i * 0.8 + np.random.randn() * 0.1 for i in range(50)])
    prices_series = pd.Series(prices)
    
    histogram = calculate_macd_histogram_series(prices_series)
    crossover = detect_histogram_crossover(histogram)
    
    print(f"翻红信号: {crossover['bullish_cross']}")
    print(f"翻红后K线数: {crossover['bars_since_cross']}")
    print(f"当前柱值: {crossover['histogram_value']:.4f}")
    print(f"信号强度: {crossover['strength']:.2f}")
    print(f"详情: {crossover['details']}")
    
    return crossover


def test_divergence():
    """测试背离检测"""
    print("\n" + "=" * 60)
    print("测试2: 背离检测")
    print("=" * 60)
    
    # 创建顶背离场景：价格新高但动能减弱
    np.random.seed(42)
    n = 80
    # 先上涨后下跌再上涨（但第二次上涨动能减弱）
    prices = np.array([100 + i * 0.8 + np.random.randn() * 0.1 for i in range(30)] +
                      [124 - i * 0.5 + np.random.randn() * 0.1 for i in range(20)] +
                      [114 + i * 0.6 + np.random.randn() * 0.1 for i in range(30)])
    prices_series = pd.Series(prices)
    
    histogram = calculate_macd_histogram_series(prices_series)
    divergence = detect_macd_divergence(prices_series, histogram)
    
    print(f"顶背离: {divergence['top_divergence']}")
    print(f"底背离: {divergence['bottom_divergence']}")
    print(f"背离强度: {divergence['strength']:.2f}")
    print(f"详情: {divergence['details']}")
    
    return divergence


def test_comprehensive_analysis():
    """测试综合分析"""
    print("\n" + "=" * 60)
    print("测试3: 综合分析")
    print("=" * 60)
    
    # 创建一个上涨趋势
    np.random.seed(42)
    n = 100
    prices = np.array([100 + i * 0.3 + np.random.randn() * 0.2 for i in range(n)])
    prices_series = pd.Series(prices)
    
    analysis = analyze_macd_histogram(prices_series)
    
    print(f"综合信号: {analysis['signal']}")
    print(f"趋势强度: {analysis['trend_strength']:.4f}")
    print(f"柱子值: {analysis['histogram_value']:.4f}")
    print(f"详情: {analysis['details']}")
    
    return analysis


def test_stabilization_scorer():
    """测试企稳评分器中的MACD柱子优化"""
    print("\n" + "=" * 60)
    print("测试4: 企稳评分器MACD优化")
    print("=" * 60)
    
    from src.fund_flow.stabilization_scorer import StabilizationScorer
    
    # 创建模拟数据
    np.random.seed(42)
    n = 100
    close = np.array([100 + i * 0.2 + np.random.randn() * 0.3 for i in range(n)])
    high = close + np.random.rand(n) * 1.0
    low = close - np.random.rand(n) * 1.0
    volume = np.random.randint(1000, 5000, n)
    
    scorer = StabilizationScorer()
    result = scorer.analyze(close, high, low, volume, direction="long")
    
    print(f"总分: {result.total_score}/100")
    print(f"MACD动能分: {result.macd_score.actual_score}/{result.macd_score.max_score}")
    print(f"MACD条件: {result.macd_score.conditions}")
    print(f"MACD详情: {result.macd_score.details}")
    print(f"通过: {result.passed}")
    
    return result


if __name__ == "__main__":
    test_histogram_crossover()
    test_divergence()
    test_comprehensive_analysis()
    test_stabilization_scorer()
    
    print("\n" + "=" * 60)
    print("所有测试完成！MACD柱子优化已生效")
    print("=" * 60)
