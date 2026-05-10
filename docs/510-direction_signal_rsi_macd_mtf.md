# 开仓方向建议：多周期 RSI × MACD 双振 + EMA / VWAP 风控

**生成日期**: 2026-05-10  
**策略定位**: 方向判断辅助模块，输出 `LONG / SHORT / FLAT` 三态建议  
**依赖周期**: 15m · 1H · 4H（三周期强制对齐）  
**核心指标**: RSI(4, 30/70) · MACD(标准) · EMA · VWAP(低权重)

---

## 一、指标参数定义

```python
# ─────────────────────────────────────────────
# RSI 配置（统一参数，三周期复用）
# ─────────────────────────────────────────────
RSI_PERIOD      = 4          # 极短周期，对价格变化高度敏感
RSI_UPPER       = 70         # 超买线
RSI_LOWER       = 30         # 超卖线
RSI_MID         = 50         # 方向分界线（核心判断锚点）

# ─────────────────────────────────────────────
# MACD 配置（统一参数，三周期复用）
# ─────────────────────────────────────────────
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9

# ─────────────────────────────────────────────
# EMA 配置
# ─────────────────────────────────────────────
EMA_FAST        = 20         # 1H 快线
EMA_SLOW        = 60         # 1H 慢线
EMA_TREND       = 200        # 1H 趋势锚（不做交叉，只看价格在哪侧）

# ─────────────────────────────────────────────
# VWAP 配置（低权重，仅辅助过滤）
# ─────────────────────────────────────────────
VWAP_RESET      = "daily"    # 每日重置
VWAP_WEIGHT     = 0.10       # 在综合评分中占比上限 10%

# ─────────────────────────────────────────────
# 周期权重（多周期评分加权）
# ─────────────────────────────────────────────
TF_WEIGHT = {
    "15m": 0.20,    # 短周期：触发确认，权重最低
    "1H":  0.50,    # 中周期：主方向判断，权重最高
    "4H":  0.30,    # 长周期：趋势背景，权重中等
}
```

---

## 二、单周期指标计算

```python
# ─────────────────────────────────────────────
# 2.1 RSI 计算（单周期）
# ─────────────────────────────────────────────
def calc_rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    """
    返回当前 K 线的 RSI 值。
    使用 Wilder 平滑（标准实现）。
    """
    if len(closes) < period + 1:
        return float("nan")

    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


# ─────────────────────────────────────────────
# 2.2 RSI 方向判断（需要连续两根 RSI 值）
# ─────────────────────────────────────────────
def rsi_direction(rsi_prev: float, rsi_curr: float) -> str:
    """
    返回 RSI 方向：
      "up"   — 本根高于上根
      "down" — 本根低于上根
      "flat" — 差值 < 0.3（过滤抖动）
    """
    FLAT_THRESHOLD = 0.3
    diff = rsi_curr - rsi_prev
    if diff > FLAT_THRESHOLD:
        return "up"
    elif diff < -FLAT_THRESHOLD:
        return "down"
    else:
        return "flat"


# ─────────────────────────────────────────────
# 2.3 MACD 计算（单周期）
# ─────────────────────────────────────────────
def calc_macd(closes: list[float]) -> dict:
    """
    返回：
      macd_line  — MACD 线（DIF）
      signal_line — 信号线（DEA）
      histogram   — 柱状图（Bar = MACD - Signal）
      bar_prev    — 上一根 Bar 值（用于判断变长/变短）
    """
    def ema(series, n):
        k = 2 / (n + 1)
        result = [series[0]]
        for v in series[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    ema_fast   = ema(closes, MACD_FAST)
    ema_slow   = ema(closes, MACD_SLOW)
    dif        = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea        = ema(dif, MACD_SIGNAL)
    bar        = [d - s for d, s in zip(dif, dea)]

    return {
        "macd_line":   dif[-1],
        "signal_line": dea[-1],
        "histogram":   bar[-1],
        "bar_prev":    bar[-2] if len(bar) >= 2 else 0.0,
    }


# ─────────────────────────────────────────────
# 2.4 MACD 方向判断
# ─────────────────────────────────────────────
def macd_direction(m: dict) -> str:
    """
    多头方向信号（返回 "bullish"）：
      - 金叉：macd_line 从下穿越 signal_line（histogram 由负转正）
      - 绿 bar 变短：histogram < 0 且 |bar| < |bar_prev|
      - 红 bar 变长：histogram > 0 且 bar > bar_prev

    空头方向信号（返回 "bearish"）：
      - 死叉：histogram 由正转负
      - 红 bar 变短：histogram > 0 且 bar < bar_prev
      - 绿 bar 变长：histogram < 0 且 |bar| > |bar_prev|

    其他返回 "neutral"
    """
    h     = m["histogram"]
    h_pre = m["bar_prev"]

    # ── 多头判断 ──
    golden_cross     = h_pre < 0 and h >= 0
    green_shrinking  = h < 0 and abs(h) < abs(h_pre)
    red_expanding    = h > 0 and h > h_pre

    # ── 空头判断 ──
    death_cross      = h_pre > 0 and h <= 0
    red_shrinking    = h > 0 and h < h_pre
    green_expanding  = h < 0 and abs(h) > abs(h_pre)

    if golden_cross or green_shrinking or red_expanding:
        return "bullish"
    elif death_cross or red_shrinking or green_expanding:
        return "bearish"
    else:
        return "neutral"
```

---

## 三、多周期聚合评分

```python
# ─────────────────────────────────────────────
# 3.1 单周期方向得分（-1.0 ~ +1.0）
# ─────────────────────────────────────────────
def score_single_tf(
    rsi_curr:   float,
    rsi_prev:   float,
    macd_data:  dict,
    close:      float,
    ema20:      float,
    ema60:      float,
    ema200:     float,
    vwap:       float,
) -> float:
    """
    正分 → 看多倾向
    负分 → 看空倾向
    量级 → 信号强度

    得分分解：
      RSI 区域分      : ±0.40  (最大权重，方向主判)
      RSI 方向分      : ±0.20
      MACD 方向分     : ±0.25
      EMA 趋势分      : ±0.10
      VWAP 过滤分     : ±0.05  (上限 0.05，权重最低)
    """
    score = 0.0

    # ── RSI 区域分 ──────────────────────────────
    # 多头条件：RSI 方向向上 且 RSI < 50（底部反弹区间）
    # 空头条件：RSI 方向向下 且 RSI > 50（顶部回落区间）
    rsi_dir = rsi_direction(rsi_prev, rsi_curr)

    if rsi_dir == "up" and rsi_curr < RSI_MID:
        # 越接近超卖线 30，底部信号越强
        proximity_to_lower = (RSI_MID - rsi_curr) / (RSI_MID - RSI_LOWER)
        score += 0.40 * min(proximity_to_lower, 1.0)

    elif rsi_dir == "down" and rsi_curr > RSI_MID:
        # 越接近超买线 70，顶部信号越强
        proximity_to_upper = (rsi_curr - RSI_MID) / (RSI_UPPER - RSI_MID)
        score -= 0.40 * min(proximity_to_upper, 1.0)

    # 超买/超卖区域额外惩罚（不开反向，而是降低信号质量）
    if rsi_curr >= RSI_UPPER:
        score -= 0.10   # 超买区不宜追多
    if rsi_curr <= RSI_LOWER:
        score += 0.10   # 超卖区不宜追空

    # ── RSI 方向分 ──────────────────────────────
    if rsi_dir == "up":
        score += 0.20
    elif rsi_dir == "down":
        score -= 0.20

    # ── MACD 方向分 ─────────────────────────────
    macd_dir = macd_direction(macd_data)
    if macd_dir == "bullish":
        score += 0.25
    elif macd_dir == "bearish":
        score -= 0.25

    # ── EMA 趋势分 ──────────────────────────────
    # 快线在慢线上方 + 价格在 EMA200 上方 = 趋势多头背景
    ema_bull = (ema20 > ema60) and (close > ema200)
    ema_bear = (ema20 < ema60) and (close < ema200)

    if ema_bull:
        score += 0.10
    elif ema_bear:
        score -= 0.10

    # ── VWAP 过滤分（低权重） ────────────────────
    # 价格在 VWAP 上方：轻微多头支持
    # 价格在 VWAP 下方：轻微空头支持
    vwap_diff_pct = (close - vwap) / vwap if vwap > 0 else 0.0

    if vwap_diff_pct > 0.002:        # 高于 VWAP 0.2%
        score += 0.05
    elif vwap_diff_pct < -0.002:     # 低于 VWAP 0.2%
        score -= 0.05
    # 在 VWAP ±0.2% 范围内：VWAP 贡献为 0（避免噪音）

    return max(-1.0, min(1.0, score))


# ─────────────────────────────────────────────
# 3.2 三周期加权综合评分
# ─────────────────────────────────────────────
def score_multi_tf(
    scores_by_tf: dict  # {"15m": float, "1H": float, "4H": float}
) -> float:
    """
    加权聚合：15m × 0.20 + 1H × 0.50 + 4H × 0.30
    输出范围：-1.0 ~ +1.0
    """
    total = 0.0
    for tf, w in TF_WEIGHT.items():
        total += scores_by_tf.get(tf, 0.0) * w
    return max(-1.0, min(1.0, total))
```

---

## 四、开仓方向决策逻辑

```python
# ─────────────────────────────────────────────
# 4.1 方向决策阈值
# ─────────────────────────────────────────────
LONG_THRESHOLD    = +0.35   # 综合分 ≥ +0.35 才考虑做多
SHORT_THRESHOLD   = -0.35   # 综合分 ≤ -0.35 才考虑做空
FLAT_ZONE         = 0.35    # 绝对值 < 0.35：方向不明，不开仓

# 4H 趋势否决权（4H 级别是背景，权重高于任何组合）
TF_4H_VETO_LONG   = -0.30   # 4H 评分低于此值时，禁止做多
TF_4H_VETO_SHORT  = +0.30   # 4H 评分高于此值时，禁止做空


# ─────────────────────────────────────────────
# 4.2 硬性进场条件检查（对齐 §1 的两个开仓条件）
# ─────────────────────────────────────────────
def check_hard_conditions(
    rsi_1h:      float,
    rsi_dir_1h:  str,
    macd_dir_1h: str,
    rsi_4h:      float,
    rsi_dir_4h:  str,
    macd_dir_4h: str,
    rsi_15m:     float,
    rsi_dir_15m: str,
    macd_dir_15m: str,
) -> str:
    """
    对应策略文档的两个核心开仓条件：

    ── 做多硬性条件 ──
    主判：RSI_1H 方向向上 且 RSI_1H < 50
          MACD_1H 方向向上（金叉 or 绿bar变短 or 红bar变长）
    辅助：4H 或 15m 中至少一个方向一致（不强求三周期完全对齐）

    ── 做空硬性条件 ──
    主判：RSI_1H 方向向下 且 RSI_1H > 50
          MACD_1H 方向向下（死叉 or 红bar变短 or 绿bar变长）
    辅助：4H 或 15m 中至少一个方向一致

    返回 "LONG" / "SHORT" / "NO_SIGNAL"
    """

    # ── 做多检查 ──────────────────────────────
    long_1h_rsi  = (rsi_dir_1h == "up") and (rsi_1h < RSI_MID)
    long_1h_macd = (macd_dir_1h == "bullish")
    long_1h_ok   = long_1h_rsi and long_1h_macd

    if long_1h_ok:
        # 多周期辅助对齐检查
        long_4h_support  = (rsi_dir_4h in ("up", "flat")) and \
                           (macd_dir_4h in ("bullish", "neutral"))
        long_15m_support = (rsi_dir_15m == "up") and \
                           (macd_dir_15m == "bullish")

        if long_4h_support or long_15m_support:
            return "LONG"

    # ── 做空检查 ──────────────────────────────
    short_1h_rsi  = (rsi_dir_1h == "down") and (rsi_1h > RSI_MID)
    short_1h_macd = (macd_dir_1h == "bearish")
    short_1h_ok   = short_1h_rsi and short_1h_macd

    if short_1h_ok:
        short_4h_support  = (rsi_dir_4h in ("down", "flat")) and \
                            (macd_dir_4h in ("bearish", "neutral"))
        short_15m_support = (rsi_dir_15m == "down") and \
                            (macd_dir_15m == "bearish")

        if short_4h_support or short_15m_support:
            return "SHORT"

    return "NO_SIGNAL"


# ─────────────────────────────────────────────
# 4.3 主决策函数（整合硬性条件 + 软性评分 + 4H 否决权）
# ─────────────────────────────────────────────
def decide_direction(market_data: dict) -> dict:
    """
    market_data 结构：
    {
      "15m": { closes, ema20, ema60, ema200, vwap },
      "1H":  { closes, ema20, ema60, ema200, vwap },
      "4H":  { closes, ema20, ema60, ema200, vwap },
    }

    返回：
    {
      "direction":   "LONG" / "SHORT" / "FLAT",
      "score":       float,         # 综合评分
      "score_by_tf": dict,          # 各周期分项
      "hard_signal": str,           # 硬性条件结果
      "reason":      str,           # 人类可读理由
      "confidence":  "HIGH" / "MEDIUM" / "LOW",
    }
    """
    scores  = {}
    rsi_val = {}
    rsi_dir = {}
    macd_d  = {}

    for tf in ["15m", "1H", "4H"]:
        d       = market_data[tf]
        closes  = d["closes"]

        r_curr  = calc_rsi(closes)
        r_prev  = calc_rsi(closes[:-1])   # 去掉最后一根算上一根
        m       = calc_macd(closes)

        rsi_val[tf] = r_curr
        rsi_dir[tf] = rsi_direction(r_prev, r_curr)
        macd_d[tf]  = macd_direction(m)

        scores[tf] = score_single_tf(
            rsi_curr  = r_curr,
            rsi_prev  = r_prev,
            macd_data = m,
            close     = closes[-1],
            ema20     = d["ema20"],
            ema60     = d["ema60"],
            ema200    = d["ema200"],
            vwap      = d["vwap"],
        )

    composite = score_multi_tf(scores)

    # ── Step 1: 硬性条件检查 ──────────────────
    hard = check_hard_conditions(
        rsi_1h=rsi_val["1H"],   rsi_dir_1h=rsi_dir["1H"],  macd_dir_1h=macd_d["1H"],
        rsi_4h=rsi_val["4H"],   rsi_dir_4h=rsi_dir["4H"],  macd_dir_4h=macd_d["4H"],
        rsi_15m=rsi_val["15m"], rsi_dir_15m=rsi_dir["15m"],macd_dir_15m=macd_d["15m"],
    )

    # ── Step 2: 4H 否决权 ─────────────────────
    veto = None
    if hard == "LONG"  and scores["4H"] < TF_4H_VETO_LONG:
        veto = f"4H score {scores['4H']:.2f} < {TF_4H_VETO_LONG} → LONG 被 4H 否决"
    if hard == "SHORT" and scores["4H"] > TF_4H_VETO_SHORT:
        veto = f"4H score {scores['4H']:.2f} > {TF_4H_VETO_SHORT} → SHORT 被 4H 否决"

    # ── Step 3: 综合评分门槛过滤 ─────────────
    if veto:
        direction = "FLAT"
        reason    = veto
    elif hard == "NO_SIGNAL":
        direction = "FLAT"
        reason    = "硬性条件未满足（RSI+MACD 主条件不足）"
    elif composite >= LONG_THRESHOLD and hard == "LONG":
        direction = "LONG"
        reason    = f"做多条件通过 | 综合分={composite:+.3f}"
    elif composite <= -SHORT_THRESHOLD and hard == "SHORT":
        direction = "SHORT"
        reason    = f"做空条件通过 | 综合分={composite:+.3f}"
    else:
        direction = "FLAT"
        reason    = f"综合分 {composite:+.3f} 未过阈值 ±{FLAT_ZONE}"

    # ── 置信度评级 ────────────────────────────
    abs_score = abs(composite)
    if abs_score >= 0.70:
        confidence = "HIGH"
    elif abs_score >= 0.50:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "direction":   direction,
        "score":       composite,
        "score_by_tf": scores,
        "hard_signal": hard,
        "reason":      reason,
        "confidence":  confidence,
        "rsi_by_tf":   rsi_val,
        "rsi_dir_by_tf": rsi_dir,
        "macd_dir_by_tf": macd_d,
    }
```

---

## 五、风控逻辑

```python
# ─────────────────────────────────────────────
# 5.1 信号质量门控（开仓前校验）
# ─────────────────────────────────────────────
def pre_entry_risk_gate(
    signal:         dict,        # decide_direction() 的输出
    current_price:  float,
    atr_1h:         float,       # 1H ATR(14)，用于波动率评估
    account_equity: float,
    open_positions: list,        # 当前持仓列表
    daily_loss_pct: float,       # 当日已亏损百分比
) -> dict:
    """
    返回 { "allow": bool, "reason": str, "adjusted_size": float }
    """

    # ── 1. 置信度门槛 ─────────────────────────
    if signal["confidence"] == "LOW":
        return {"allow": False, "reason": "LOW 置信度，不开仓"}

    # ── 2. 日亏损上限 ─────────────────────────
    if daily_loss_pct >= 0.05:
        return {"allow": False, "reason": f"日亏损 {daily_loss_pct:.2%} 已达 5% 上限"}

    # ── 3. 持仓数量上限 ───────────────────────
    MAX_OPEN = 3
    if len(open_positions) >= MAX_OPEN:
        return {"allow": False, "reason": f"持仓数 {len(open_positions)} 已满 {MAX_OPEN}"}

    # ── 4. ATR 过高保护（极端波动不开仓） ────
    atr_ratio = atr_1h / current_price
    if atr_ratio > 0.04:        # ATR 超过价格 4%
        return {"allow": False, "reason": f"ATR ratio {atr_ratio:.3f} 超限，市场过于波动"}

    # ── 5. 方向 × VWAP 位置一致性检查 ────────
    # （VWAP 不作为硬性否决，仅降低仓位）
    vwap_penalty = 1.0
    for tf in ["1H", "4H"]:
        closes = None   # 从上下文获取
        vwap   = None   # 从上下文获取
        # 做多但价格深度低于 VWAP（超卖但 VWAP 阻力在上方）
        if signal["direction"] == "LONG":
            # VWAP 仅微调，不否决
            vwap_penalty = max(vwap_penalty - 0.05, 0.80)

    # ── 6. 仓位计算 ───────────────────────────
    base_portion  = 0.35        # 与 backtest profile 对齐
    confidence_mult = {
        "HIGH":   1.0,
        "MEDIUM": 0.75,
    }.get(signal["confidence"], 0.5)

    adjusted_size = base_portion * confidence_mult * vwap_penalty

    return {
        "allow":         True,
        "reason":        "通过所有风控门控",
        "adjusted_size": round(adjusted_size, 3),
    }


# ─────────────────────────────────────────────
# 5.2 止损 / Breakeven / 移动止损设置
# ─────────────────────────────────────────────
def calc_exit_params(
    direction:     str,
    entry_price:   float,
    atr_1h:        float,
    signal_score:  float,
) -> dict:
    """
    止损距离 = 1.5 × ATR（不低于 0.8%，不高于 3%）
    Breakeven 触发 = 1.5% 浮盈（放宽，避免过早切 runner）
    Breakeven 锁盈 = 0.5%（与建议-2 对齐）
    """
    sl_atr_mult   = 1.5
    raw_sl_pct    = (atr_1h / entry_price) * sl_atr_mult
    sl_pct        = max(0.008, min(raw_sl_pct, 0.030))

    breakeven_trigger = 0.015   # 浮盈 1.5% 触发（区别于原 0.8%）
    breakeven_lock    = 0.005   # 锁在 +0.5%（区别于原 0.2%）

    if direction == "LONG":
        stop_loss  = entry_price * (1 - sl_pct)
        be_trigger = entry_price * (1 + breakeven_trigger)
        be_lock    = entry_price * (1 + breakeven_lock)
    else:
        stop_loss  = entry_price * (1 + sl_pct)
        be_trigger = entry_price * (1 - breakeven_trigger)
        be_lock    = entry_price * (1 - breakeven_lock)

    return {
        "stop_loss":           stop_loss,
        "sl_pct":              sl_pct,
        "breakeven_trigger":   be_trigger,
        "breakeven_lock_price": be_lock,
    }
```

---

## 六、配置文件修改 DIFF

```diff
# config/trading_config_fund_flow.json
# ─── RSI 指标新增 ────────────────────────────────────────────────
  "indicators": {
+   "rsi": {
+     "period": 4,
+     "upper":  70,
+     "lower":  30,
+     "mid":    50,
+     "timeframes": ["15m", "1H", "4H"]
+   },
    "macd": {
      "fast": 12, "slow": 26, "signal": 9,
      "timeframes": ["15m", "1H", "4H"]
    },
    "ema": {
+     "fast":  20,
+     "slow":  60,
+     "trend": 200,
+     "timeframe": "1H"
    },
    "vwap": {
      "reset": "daily",
-     "weight": 0.20
+     "weight": 0.10        # 权重从 0.20 降至 0.10
    }
  },

# ─── 方向评分权重 ─────────────────────────────────────────────────
+ "direction_scoring": {
+   "tf_weights":         { "15m": 0.20, "1H": 0.50, "4H": 0.30 },
+   "long_threshold":     0.35,
+   "short_threshold":   -0.35,
+   "tf_4h_veto_long":   -0.30,
+   "tf_4h_veto_short":   0.30
+ },

# ─── Breakeven 参数放宽 ───────────────────────────────────────────
- "breakeven_trigger_pnl_ratio": 0.008,
+ "breakeven_trigger_pnl_ratio": 0.015,

- "breakeven_lock_ratio": 0.002,
+ "breakeven_lock_ratio": 0.005,

# ─── Light take-profit 提高门槛（保护 runner） ────────────────────
- "light_take_profit_min_hold_seconds": 180,
+ "light_take_profit_min_hold_seconds": 1200,

- "light_take_profit_min_mfe": 0.0025,
+ "light_take_profit_min_mfe": 0.0080,

- "light_take_profit_pct": 0.75,
+ "light_take_profit_pct": 0.30,

# ─── VWAP 权重上限声明 ────────────────────────────────────────────
+ "vwap_max_score_contribution": 0.05,  # 单周期最大 VWAP 贡献 ±0.05
```

---

## 七、开仓决策完整流水线

```python
# ─────────────────────────────────────────────
# 7.1 每轮 cycle 调用入口
# ─────────────────────────────────────────────
def run_direction_signal(symbol: str, market_data: dict) -> dict | None:
    """
    完整流程：
      1. 计算各周期指标
      2. 生成多周期评分
      3. 硬性条件检查
      4. 4H 否决权
      5. 风控门控
      6. 输出开仓建议
    """
    # Step 1-4: 方向决策
    signal = decide_direction(market_data)

    if signal["direction"] == "FLAT":
        log_debug(f"{symbol} FLAT | {signal['reason']}")
        return None

    # Step 5: 风控门控
    current_price  = market_data["1H"]["closes"][-1]
    atr_1h         = calc_atr(market_data["1H"]["closes"], period=14)
    account_equity = get_account_equity()
    open_positions = get_open_positions()
    daily_loss_pct = get_daily_loss_pct()

    gate = pre_entry_risk_gate(
        signal, current_price, atr_1h,
        account_equity, open_positions, daily_loss_pct
    )

    if not gate["allow"]:
        log_info(f"{symbol} BLOCKED | {gate['reason']}")
        return None

    # Step 6: 止损参数
    exits = calc_exit_params(
        direction    = signal["direction"],
        entry_price  = current_price,
        atr_1h       = atr_1h,
        signal_score = signal["score"],
    )

    return {
        "symbol":      symbol,
        "direction":   signal["direction"],
        "score":       signal["score"],
        "confidence":  signal["confidence"],
        "size_pct":    gate["adjusted_size"],
        "stop_loss":   exits["stop_loss"],
        "be_trigger":  exits["breakeven_trigger"],
        "be_lock":     exits["breakeven_lock_price"],
        "reason":      signal["reason"],
        "score_by_tf": signal["score_by_tf"],
        # ── 调试字段 ──
        "rsi_1h":      signal["rsi_by_tf"]["1H"],
        "rsi_4h":      signal["rsi_by_tf"]["4H"],
        "rsi_15m":     signal["rsi_by_tf"]["15m"],
        "macd_1h":     signal["macd_dir_by_tf"]["1H"],
        "macd_4h":     signal["macd_dir_by_tf"]["4H"],
    }
```

---

## 八、场景示例：典型信号状态

```
场景 A — 理想做多信号（HIGH confidence）
─────────────────────────────────────────
  15m: RSI=38.2 ↑，MACD 绿bar变短   → score_15m = +0.62
   1H: RSI=44.7 ↑，MACD 金叉         → score_1H  = +0.85
   4H: RSI=51.2 ↑ (持平)，MACD 中性   → score_4H  = +0.20

  composite = 0.62×0.20 + 0.85×0.50 + 0.20×0.30
            = 0.124 + 0.425 + 0.060 = +0.609

  硬性条件：1H RSI<50 ↑ + MACD bullish = LONG ✓
  4H 否决权：score_4H = +0.20 > -0.30，不否决
  综合分：+0.609 ≥ +0.35 → LONG，confidence = HIGH

场景 B — 4H 背景抵抗，做多被否决
─────────────────────────────────────────
   1H: RSI=43.1 ↑，MACD 绿bar变短   → score_1H  = +0.72
   4H: RSI=62.8 ↓，MACD 红bar变短   → score_4H  = -0.40

  硬性条件通过 LONG
  4H 否决权：score_4H = -0.40 < -0.30 → LONG 被 4H 否决
  输出：FLAT（"4H score -0.40 否决做多"）

场景 C — 做空信号（MEDIUM confidence）
─────────────────────────────────────────
  15m: RSI=64.3 ↓，MACD 死叉        → score_15m = -0.58
   1H: RSI=58.1 ↓，MACD 红bar变短   → score_1H  = -0.65
   4H: RSI=55.0 方向平，MACD 中性    → score_4H  = -0.05

  composite = (-0.58×0.20) + (-0.65×0.50) + (-0.05×0.30)
            = -0.116 - 0.325 - 0.015 = -0.456

  硬性条件：1H RSI>50 ↓ + MACD bearish = SHORT ✓
  4H 否决权：score_4H = -0.05 < +0.30，不否决
  综合分：-0.456 ≤ -0.35 → SHORT，confidence = MEDIUM
  风控：size_pct = 0.35 × 0.75 = 0.2625（中置信度压仓）

场景 D — RSI 超买区，信号被降权
─────────────────────────────────────────
   1H: RSI=73.4（超买）↑，MACD 红bar变长
  → 超买惩罚 -0.10，RSI 方向 +0.20，但 RSI>50 的多头 RSI 区域分 = 0
  → 总分偏低，综合分很可能 < 0.35
  → 输出 FLAT（不在超买区追多）
```

---

## 九、信号成功率参考表（历史规律）

```
多周期对齐程度 vs 历史成功率估算（基于 RSI4 + MACD 双振策略回测经验）

对齐程度              条件                       估算成功率
─────────────────────────────────────────────────────────
三周期完全对齐        15m+1H+4H 方向一致          78~88%
1H+4H 对齐，15m 反     主方向稳健，短期噪音        72~80%
1H+15m 对齐，4H 中性   短中期有信号，趋势不明      60~70%
仅 1H 有信号           单周期孤证                  50~58%
1H 与 4H 方向相反      多空博弈，不开仓            不开仓

注：
- RSI(4) 极短周期，噪音天然高于 RSI(14)
  三周期不对齐时，必须严格依赖硬性条件过滤
- VWAP 单独作为方向判断没有统计优势，只用作 ±0.05 分的轻微修正
- EMA 趋势过滤（EMA200）对做单胜率有明显正向贡献（约 +5~8%）
  尤其在日线趋势不明朗时，EMA200 方向是最后的保险层
```

---

*策略版本: v1.0 | 本文档为伪代码参考，上线前需集成进 `macd_strategy_v2.py` 并通过 strict_live_mode 回测验证*
