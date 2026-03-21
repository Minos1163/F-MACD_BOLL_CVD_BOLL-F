"""
技术指标计算
RSI, MACD, EMA, ATR等
"""

from typing import Optional

import pandas as pd


def calculate_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """
    计算RSI指标

    Args:
        prices: 价格序列（通常是收盘价）
        period: RSI周期，默认14

    Returns:
        最新RSI值
    """
    if len(prices) < period + 1:
        return None

    try:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        # ensure float literals to avoid type-checker operator issues with Series
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return float(rsi.iloc[-1])
    except BaseException:
        return None


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """
    计算MACD指标

    Returns:
        (macd, signal, histogram)
        macd: MACD线
        signal: 信号线
        histogram: MACD柱状图（macd - signal）
    """
    if len(prices) < slow + signal:
        return None, None, None

    try:
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return (
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(histogram.iloc[-1]),
        )
    except BaseException:
        return None, None, None


def calculate_macd_histogram_series(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """
    计算MACD柱状图序列（用于背离检测）
    
    Returns:
        histogram序列
    """
    if len(prices) < slow + signal:
        return pd.Series()
    
    try:
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return histogram
    except BaseException:
        return pd.Series()


def detect_macd_divergence(prices: pd.Series, histogram: pd.Series, lookback: int = 20) -> dict:
    """
    MACD柱子背离检测
    
    背离类型：
    - 顶背离：价格新高，但MACD柱子降低 -> 做空信号
    - 底背离：价格新低，但MACD柱子抬高 -> 做多信号
    
    Args:
        prices: 价格序列（收盘价）
        histogram: MACD柱状图序列
        lookback: 回溯周期
    
    Returns:
        {
            'top_divergence': bool,      # 是否存在顶背离
            'bottom_divergence': bool,   # 是否存在底背离
            'strength': float,           # 背离强度 (0-1)
            'price_high': float,         # 价格高点
            'histogram_at_high': float,  # 价格高点时的柱子值
            'details': str               # 详细说明
        }
    """
    result = {
        'top_divergence': False,
        'bottom_divergence': False,
        'strength': 0.0,
        'price_high': 0.0,
        'histogram_at_high': 0.0,
        'details': ''
    }
    
    if len(prices) < lookback or len(histogram) < lookback:
        return result
    
    try:
        # 取最近lookback根K线
        recent_prices = prices.iloc[-lookback:]
        recent_hist = histogram.iloc[-lookback:]
        
        # 找到价格最高点和次高点
        price_max_idx = recent_prices.idxmax()
        price_values = recent_prices.values
        hist_values = recent_hist.values
        
        # 顶背离检测：当前价格接近新高，但柱子值低于之前高点时的柱子值
        current_price = recent_prices.iloc[-1]
        current_hist = recent_hist.iloc[-1]
        
        # 找历史价格高点（排除最近3根）
        if len(recent_prices) > 5:
            hist_high_price = np.max(recent_prices.iloc[:-3])
            hist_high_idx = recent_prices.iloc[:-3].idxmax()
            hist_high_hist = recent_hist.loc[hist_high_idx]
            
            # 顶背离：当前价格 >= 历史高点的95%，但柱子值低于历史高点
            if current_price >= hist_high_price * 0.98 and current_hist < hist_high_hist:
                divergence_pct = (hist_high_hist - current_hist) / abs(hist_high_hist) if hist_high_hist != 0 else 0
                price_pct = (current_price - hist_high_price) / hist_high_price
                
                result['top_divergence'] = True
                result['strength'] = min(1.0, divergence_pct * 2)  # 背离强度
                result['price_high'] = hist_high_price
                result['histogram_at_high'] = hist_high_hist
                result['details'] = f"顶背离: 价格{price_pct*100:.1f}%新高, 柱子降低{divergence_pct*100:.1f}%"
        
        # 底背离检测：当前价格接近新低，但柱子值高于之前低点时的柱子值
        hist_low_price = np.min(recent_prices.iloc[:-3]) if len(recent_prices) > 5 else np.min(recent_prices)
        hist_low_idx = recent_prices.iloc[:-3].idxmin() if len(recent_prices) > 5 else recent_prices.idxmin()
        hist_low_hist = recent_hist.loc[hist_low_idx]
        
        if current_price <= hist_low_price * 1.02 and current_hist > hist_low_hist:
            divergence_pct = (current_hist - hist_low_hist) / abs(hist_low_hist) if hist_low_hist != 0 else 0
            price_pct = (hist_low_price - current_price) / hist_low_price
            
            result['bottom_divergence'] = True
            result['strength'] = min(1.0, divergence_pct * 2)
            result['price_high'] = hist_low_price
            result['histogram_at_high'] = hist_low_hist
            result['details'] = f"底背离: 价格{price_pct*100:.1f}%新低, 柱子抬高{divergence_pct*100:.1f}%"
            
    except Exception:
        pass
    
    return result


def detect_histogram_crossover(histogram: pd.Series, confirm_bars: int = 1) -> dict:
    """
    MACD柱子翻红/翻绿检测（比金叉/死叉提前2-3根K线）
    
    信号说明：
    - 柱子负→正（翻红）：做多信号，比金叉提前2-3根K线
    - 柱子正→负（翻绿）：做空信号，比死叉提前2-3根K线
    
    Args:
        histogram: MACD柱状图序列
        confirm_bars: 确认根数（连续几根确认）
    
    Returns:
        {
            'bullish_cross': bool,       # 翻红信号
            'bearish_cross': bool,       # 翻绿信号
            'bars_since_cross': int,     # 翻红/翻绿后经过几根K线
            'histogram_value': float,    # 当前柱子值
            'strength': float,           # 信号强度
            'details': str
        }
    """
    result = {
        'bullish_cross': False,
        'bearish_cross': False,
        'bars_since_cross': -1,
        'histogram_value': 0.0,
        'strength': 0.0,
        'details': ''
    }
    
    if len(histogram) < 5:
        return result
    
    try:
        hist_values = histogram.values
        current_hist = hist_values[-1]
        result['histogram_value'] = current_hist
        
        # 检测翻红：柱子从负转正
        # 找到最近一次从负转正的位置
        for i in range(len(hist_values) - 2, -1, -1):
            if hist_values[i] < 0 and hist_values[i + 1] >= 0:
                # 找到翻红点
                bars_since = len(hist_values) - 1 - i
                result['bullish_cross'] = True
                result['bars_since_cross'] = bars_since
                
                # 强度：柱子值越大越强
                result['strength'] = min(1.0, abs(current_hist) / abs(hist_values[i]) if hist_values[i] != 0 else 0.5)
                
                result['details'] = f"翻红信号: {bars_since}根K线前柱子负→正, 当前值{current_hist:.4f}"
                break
        
        # 检测翻绿：柱子从正转负
        if not result['bullish_cross']:
            for i in range(len(hist_values) - 2, -1, -1):
                if hist_values[i] > 0 and hist_values[i + 1] <= 0:
                    bars_since = len(hist_values) - 1 - i
                    result['bearish_cross'] = True
                    result['bars_since_cross'] = bars_since
                    result['strength'] = min(1.0, abs(current_hist) / abs(hist_values[i]) if hist_values[i] != 0 else 0.5)
                    result['details'] = f"翻绿信号: {bars_since}根K线前柱子正→负, 当前值{current_hist:.4f}"
                    break
        
        # 柱子趋势分析
        if current_hist > 0:
            # 红柱，检查是否在增强
            if len(hist_values) >= 3:
                if hist_values[-1] > hist_values[-2] > hist_values[-3]:
                    result['strength'] = min(1.0, result['strength'] + 0.3)
                    result['details'] += " | 红柱增强"
                elif hist_values[-1] < hist_values[-2]:
                    result['strength'] *= 0.7
                    result['details'] += " | 红柱减弱"
        else:
            # 绿柱
            if len(hist_values) >= 3:
                if hist_values[-1] < hist_values[-2] < hist_values[-3]:
                    result['strength'] = min(1.0, result['strength'] + 0.3)
                    result['details'] += " | 绿柱增强"
                elif hist_values[-1] > hist_values[-2]:
                    result['strength'] *= 0.7
                    result['details'] += " | 绿柱减弱"
                    
    except Exception:
        pass
    
    return result


def analyze_macd_histogram(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD柱子综合分析（高级技巧）
    
    包含：
    1. 柱子背离检测
    2. 柱子翻红/翻绿信号
    3. 柱子趋势强度
    
    Returns:
        综合分析结果
    """
    histogram = calculate_macd_histogram_series(prices, fast, slow, signal)
    
    if histogram.empty:
        return {
            'valid': False,
            'divergence': {},
            'crossover': {},
            'trend_strength': 0.0,
            'signal': 'none',
            'details': '数据不足'
        }
    
    # 背离检测
    divergence = detect_macd_divergence(prices, histogram)
    
    # 翻红/翻绿检测
    crossover = detect_histogram_crossover(histogram)
    
    # 趋势强度：最近5根柱子的平均斜率
    if len(histogram) >= 5:
        recent_hist = histogram.iloc[-5:].values
        trend_strength = (recent_hist[-1] - recent_hist[0]) / abs(recent_hist[0]) if recent_hist[0] != 0 else 0
    else:
        trend_strength = 0.0
    
    # 综合信号判定
    signal = 'none'
    if divergence['bottom_divergence'] and crossover['bullish_cross']:
        signal = 'strong_buy'  # 底背离 + 翻红 = 强做多
    elif divergence['bottom_divergence']:
        signal = 'buy'         # 底背离
    elif crossover['bullish_cross'] and crossover['bars_since_cross'] <= 3:
        signal = 'buy'         # 刚翻红
    elif divergence['top_divergence'] and crossover['bearish_cross']:
        signal = 'strong_sell' # 顶背离 + 翻绿 = 强做空
    elif divergence['top_divergence']:
        signal = 'sell'        # 顶背离
    elif crossover['bearish_cross'] and crossover['bars_since_cross'] <= 3:
        signal = 'sell'        # 刚翻绿
    
    return {
        'valid': True,
        'divergence': divergence,
        'crossover': crossover,
        'trend_strength': trend_strength,
        'signal': signal,
        'histogram_value': float(histogram.iloc[-1]),
        'details': f"{divergence['details']} | {crossover['details']}" if divergence['details'] or crossover['details'] else '无特殊信号'
    }


def calculate_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 9,
    smooth: int = 3,
) -> tuple:
    """
    计算 KDJ 指标。

    Returns:
        (k, d, j)
    """
    if len(high) < period or len(low) < period or len(close) < period:
        return None, None, None

    try:
        low_n = low.rolling(window=period).min()
        high_n = high.rolling(window=period).max()
        spread = (high_n - low_n).replace(0, pd.NA)
        rsv = ((close - low_n) / spread) * 100.0
        alpha = 1.0 / float(max(1, smooth))
        k = rsv.ewm(alpha=alpha, adjust=False).mean()
        d = k.ewm(alpha=alpha, adjust=False).mean()
        j = 3.0 * k - 2.0 * d
        k_val = k.iloc[-1]
        d_val = d.iloc[-1]
        j_val = j.iloc[-1]
        if pd.isna(k_val) or pd.isna(d_val) or pd.isna(j_val):
            return None, None, None
        return float(k_val), float(d_val), float(j_val)
    except BaseException:
        return None, None, None


def calculate_ema(prices: pd.Series, period: int) -> Optional[float]:
    """
    计算EMA（指数移动平均）

    Args:
        prices: 价格序列
        period: EMA周期

    Returns:
        最新EMA值
    """
    if len(prices) < period:
        return None

    try:
        ema = prices.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])
    except BaseException:
        return None


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
    """
    计算ATR（真实波动幅度）

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: ATR周期

    Returns:
        最新ATR值
    """
    if len(high) < period + 1:
        return None

    try:
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return float(atr.iloc[-1])
    except BaseException:
        return None


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
    """
    计算ADX（平均趋向指数）

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: ADX周期

    Returns:
        最新ADX值
    """
    if len(high) < period + 1 or len(low) < period + 1 or len(close) < period + 1:
        return None

    try:
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.rolling(window=period).mean()
        plus_di = 100.0 * (plus_dm.rolling(window=period).mean() / atr.replace(0, pd.NA))
        minus_di = 100.0 * (minus_dm.rolling(window=period).mean() / atr.replace(0, pd.NA))

        di_sum = (plus_di + minus_di).replace(0, pd.NA)
        dx = ((plus_di - minus_di).abs() / di_sum) * 100.0
        adx = dx.rolling(window=period).mean()
        value = adx.iloc[-1]
        if pd.isna(value):
            return None
        return float(value)
    except BaseException:
        return None


def calculate_volume_ratio(current_volume: float, avg_volume: float) -> float:
    """
    计算成交量比率

    Returns:
        当前成交量相对于平均成交量的百分比
    """
    if avg_volume == 0:
        return 0.0
    return (current_volume / avg_volume) * 100


def calculate_change_percent(current: float, previous: float) -> float:
    """
    计算涨跌百分比

    Returns:
        涨跌百分比
    """
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def calculate_sma(prices: pd.Series, period: int) -> Optional[float]:
    """
    计算SMA（简单移动平均）

    Args:
        prices: 价格序列
        period: SMA周期

    Returns:
        最新SMA值
    """
    if len(prices) < period:
        return None

    try:
        sma = prices.rolling(window=period).mean()
        return float(sma.iloc[-1])
    except BaseException:
        return None


def calculate_bollinger_bands(prices: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple:
    """
    计算布林带

    Args:
        prices: 价格序列
        period: 周期
        num_std: 标准差倍数

    Returns:
        (middle, upper, lower)
    """
    if len(prices) < period:
        return None, None, None

    try:
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()

        upper = sma + (std * num_std)
        lower = sma - (std * num_std)

        return (
            float(sma.iloc[-1]),
            float(upper.iloc[-1]),
            float(lower.iloc[-1]),
        )
    except BaseException:
        return None, None, None


def calculate_bbi(prices: pd.Series, periods: Optional[list] = None) -> Optional[float]:
    """
    计算BBI（多空指标）
    BBI = (MA3 + MA6 + MA12 + MA24) / 4
    价格在BBI上方为多头市场，下方为空头市场

    Args:
        prices: 价格序列
        periods: 均线周期列表，默认[3, 6, 12, 24]

    Returns:
        最新BBI值
    """
    if periods is None:
        periods = [3, 6, 12, 24]

    min_len = max(periods)
    if len(prices) < min_len:
        return None

    try:
        ma_sum = 0.0
        for p in periods:
            ma = prices.rolling(window=p).mean()
            ma_sum += float(ma.iloc[-1])
        return ma_sum / len(periods)
    except BaseException:
        return None


def calculate_ema_slope(prices: pd.Series, period: int = 20, slope_period: int = 3) -> Optional[float]:
    """
    计算EMA斜率（用于判断趋势强度）

    Args:
        prices: 价格序列
        period: EMA周期
        slope_period: 斜率计算周期（用几根K线计算斜率）

    Returns:
        斜率百分比（每根K线的变化率）
    """
    if len(prices) < period + slope_period:
        return None

    try:
        ema = prices.ewm(span=period, adjust=False).mean()
        # 取最近slope_period根K线的EMA值
        recent_ema = ema.iloc[-slope_period:]
        if len(recent_ema) < 2:
            return None
        # 计算斜率：(最新EMA - slope_period根前EMA) / slope_period根前EMA
        slope = (float(recent_ema.iloc[-1]) - float(recent_ema.iloc[0])) / float(recent_ema.iloc[0])
        return slope
    except BaseException:
        return None


def calculate_ema_diff_pct(prices: pd.Series, fast_period: int = 20, slow_period: int = 50) -> Optional[float]:
    """
    计算快慢EMA差值百分比

    Args:
        prices: 价格序列
        fast_period: 快EMA周期
        slow_period: 慢EMA周期

    Returns:
        (快EMA - 慢EMA) / 慢EMA 百分比
    """
    if len(prices) < slow_period:
        return None

    try:
        ema_fast = prices.ewm(span=fast_period, adjust=False).mean()
        ema_slow = prices.ewm(span=slow_period, adjust=False).mean()

        fast_val = float(ema_fast.iloc[-1])
        slow_val = float(ema_slow.iloc[-1])

        if slow_val == 0:
            return None

        return (fast_val - slow_val) / slow_val
    except BaseException:
        return None
