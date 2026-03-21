# MACD 多时间框架交易策略 V2.0
## VWAP + EMA 增强版

> **升级说明**：在 V1.0 纯 MACD 框架基础上，引入 VWAP（价值中枢过滤）和 EMA（趋势结构确认），目标将胜率从 55% 提升至 63%+，同时改善止损精度、减少假信号
> **向后兼容**：V1.0 的全部逻辑保留，新增指标以"叠加过滤层"的方式嵌入，不破坏原有评分体系

---

## 目录

1. [V2.0 架构总览](#一v20-架构总览)
2. [新增指标参数配置](#二新增指标参数配置)
3. [VWAP 过滤层（新增）](#三vwap-过滤层新增)
4. [EMA 结构层（新增）](#四ema-结构层新增)
5. [V2.0 综合评分系统](#五v20-综合评分系统)
6. [止损系统升级](#六止损系统升级)
7. [入场过滤规则（新增否决项）](#七入场过滤规则新增否决项)
8. [V2.0 信号示例](#八v20-信号示例)
9. [预期效益分析](#九预期效益分析)
10. [配置文件 V2.0](#十配置文件-v20)

---

## 一、V2.0 架构总览

### 层级架构对比

```
┌─────────────────────────────────────────────────────────┐
│              MACD 策略层级架构 V2.0                       │
├─────────────────────────────────────────────────────────┤
│  [新增] EMA 结构层（4H + 1H）                             │
│    → 过滤逆势交易，确认趋势方向有效性                      │
│    → 提供动态止损锚点（替代固定 2% 止损）                  │
├─────────────────────────────────────────────────────────┤
│  MACD_1H 定方向（权重 35%，原 40%）                       │
│    → 核心方向判断逻辑不变                                 │
│    → 权重略降，让渡给 VWAP 和 EMA 层                      │
├─────────────────────────────────────────────────────────┤
│  MACD_4H 确认增强（权重 15%，原 20%）                     │
│    → 原有逻辑不变                                        │
│    → EMA_4H 分担部分趋势确认职责                          │
├─────────────────────────────────────────────────────────┤
│  [新增] VWAP 价值中枢层（权重 15%）                        │
│    → 日内 VWAP 判断多空偏向                              │
│    → 偏离 VWAP 过远时抑制入场                             │
├─────────────────────────────────────────────────────────┤
│  MACD_15M 跟随入场（权重 20%，原 25%）                    │
│    → 原有逻辑不变                                        │
│    → EMA_15M 辅助精确入场点位                             │
├─────────────────────────────────────────────────────────┤
│  成交量确认（权重 15%，不变）                              │
│    → 原有逻辑不变                                        │
└─────────────────────────────────────────────────────────┘
```

### 权重调整说明

| 模块 | V1.0 权重 | V2.0 权重 | 变化原因 |
|------|-----------|-----------|----------|
| MACD_1H 定方向 | 40% | 35% | 让渡 5% 给 VWAP 层 |
| MACD_4H 确认 | 20% | 15% | 让渡 5% 给 VWAP 层 |
| VWAP 价值中枢 | 0% | **15%** | 新增，改善入场质量 |
| MACD_15M 入场 | 25% | 20% | 让渡 5%，EMA 辅助精化 |
| 成交量确认 | 15% | 15% | 不变 |

---

## 二、新增指标参数配置

### 完整指标参数表

| 周期 | 指标 | 参数 | 用途 |
|------|------|------|------|
| 4H | MACD | 12, 26, 9 | 趋势确认（原有） |
| 4H | EMA | 21, 55, 200 | 大趋势结构判断 |
| 1H | MACD | 12, 26, 9 | 定方向（原有） |
| 1H | EMA | 21, 55 | 回踩支撑确认 + 动态止损 |
| 1H | VWAP | 日内锚点 | 价值中枢偏向判断 |
| 15M | MACD | 12, 26, 9 | 跟随入场（原有） |
| 15M | EMA | 21 | 精确入场点位过滤 |

### EMA 关键规则

```python
# 1H EMA 用途分工
EMA_21_1H   →  动态止损基准 + 回踩支撑判断
EMA_55_1H   →  中期趋势方向确认（多头须在上方）
EMA_200_4H  →  大级别趋势过滤（终极过滤，非强制）

# 入场约束
做多约束：1H 收盘价须在 EMA_55_1H 上方
做空约束：1H 收盘价须在 EMA_55_1H 下方
```

### VWAP 关键规则

```python
# VWAP 锚点选择
日内 VWAP：每日 00:00 UTC 重置，用于判断当日多空偏向

# VWAP 偏离率
VWAP_deviation = (price - VWAP) / VWAP × 100%

# 偏离阈值（过远不追）
MAX_VWAP_DEVIATION_LONG  = +1.5%   # 价格高于 VWAP 超过 1.5%，做多降权
MAX_VWAP_DEVIATION_SHORT = -1.5%   # 价格低于 VWAP 超过 1.5%，做空降权
HARD_BLOCK_DEVIATION     = ±3.0%   # 超过 3%，硬性禁止入场
```

---

## 三、VWAP 过滤层（新增）

### 3.1 VWAP 多空偏向判断

| 价格与 VWAP 关系 | 偏向 | 做多影响 | 做空影响 |
|-----------------|------|----------|----------|
| 价格 > VWAP + 0.5% | 多头偏向 | ✅ 正向加分 | ⚠️ 轻微降权 |
| VWAP - 0.5% ≤ 价格 ≤ VWAP + 0.5% | 中性区 | 中性 | 中性 |
| 价格 < VWAP - 0.5% | 空头偏向 | ⚠️ 轻微降权 | ✅ 正向加分 |

### 3.2 VWAP 评分计算

```python
def calculate_vwap_score(price, vwap, direction):
    """
    VWAP 评分：满分 0.15
    direction: 'long' or 'short'
    """
    deviation = (price - vwap) / vwap  # 正数=价格高于VWAP

    if direction == 'long':
        if deviation > 0.03:
            return 0.0   # 硬性否决：偏离超过 3%，不追多
        elif deviation > 0.015:
            return 0.05  # 偏离 1.5%～3%：大幅降权
        elif deviation > 0.005:
            return 0.10  # 价格略高于 VWAP：标准分
        elif deviation > -0.005:
            return 0.12  # 贴近 VWAP：接近满分（最佳入场区）
        else:
            return 0.15  # 价格略低于 VWAP（回踩 VWAP 做多）：满分

    elif direction == 'short':
        if deviation < -0.03:
            return 0.0   # 硬性否决：偏离超过 -3%，不追空
        elif deviation < -0.015:
            return 0.05  # 偏离 -1.5%～-3%：大幅降权
        elif deviation < -0.005:
            return 0.10  # 价格略低于 VWAP：标准分
        elif deviation > -0.005:
            return 0.12  # 贴近 VWAP：接近满分
        else:
            return 0.15  # 价格略高于 VWAP（反弹 VWAP 做空）：满分
```

### 3.3 VWAP 的核心价值

VWAP 解决了 V1.0 的两个主要假信号来源：

**问题一：追高做多（高偏离）**
V1.0 在价格已经远高于均值时，只要 MACD 翻红就可能入场。引入 VWAP 后，偏离超过 1.5% 时评分大幅降低，超过 3% 时硬性禁止，强制等待价格回踩后再入场。

**问题二：逆均值做多（低于 VWAP 做多）**
V1.0 对 MACD 翻红的价格位置无感知。引入 VWAP 后，价格略低于 VWAP 时做多（回踩 VWAP 支撑）反而获得满分，因为此时入场具有最优的风险回报比。

---

## 四、EMA 结构层（新增）

### 4.1 EMA 三项功能

**功能 1：趋势方向过滤（入场前置条件）**

```python
def check_ema_trend_filter(close_1h, ema21_1h, ema55_1h, direction):
    """
    EMA 趋势过滤：作为入场的软性前置条件
    不满足时不硬性拒绝，但大幅降低评分
    """
    if direction == 'long':
        above_ema21 = close_1h > ema21_1h
        above_ema55 = close_1h > ema55_1h
        ema_bullish  = ema21_1h > ema55_1h  # EMA 多头排列
        
        if above_ema55 and ema_bullish:
            return 'strong',  1.0   # 强多头结构
        elif above_ema21:
            return 'normal',  0.7   # 一般多头
        elif above_ema55:
            return 'weak',    0.4   # 价格在 EMA55 上方但 EMA21 下方
        else:
            return 'against', 0.0   # 价格跌破 EMA55，逆势做多，硬性降权
    
    # 做空对称处理
    ...
```

**功能 2：入场点位精化（15M 层辅助）**

```python
def refine_15m_entry(close_15m, ema21_15m, direction, macd_entry_score):
    """
    用 15M EMA21 精化入场时机
    在 MACD 触发后，等待价格与 EMA21 形成更优结构再入场
    """
    if direction == 'long':
        # 最优：价格刚好回踩 15M EMA21 后反弹
        pullback_to_ema = (close_15m >= ema21_15m * 0.999 and
                           close_15m <= ema21_15m * 1.005)
        if pullback_to_ema:
            return macd_entry_score * 1.15  # 加成 15%（上限 0.25）
        
        # 次优：价格在 EMA21 上方合理范围
        elif close_15m > ema21_15m:
            return macd_entry_score          # 不加减分
        
        # 差：价格低于 EMA21（逆 15M 短期趋势做多）
        else:
            return macd_entry_score * 0.7   # 降权 30%
```

**功能 3：动态止损锚点（替代固定 2% 止损）**

详见第六章止损系统升级。

### 4.2 EMA 结构评分

```python
def calculate_ema_score(close_1h, ema21_1h, ema55_1h,
                        ema21_4h, ema55_4h, ema200_4h, direction):
    """
    EMA 结构综合评分
    注意：EMA 评分不单独占权重，而是作为 1H 和 4H MACD 分数的乘数修正
    """
    # 4H EMA 排列检查
    if direction == 'long':
        ema_4h_aligned = (ema21_4h > ema55_4h > ema200_4h)  # 强多排列
        ema_1h_ok      = close_1h > ema55_1h
    
    # 输出修正系数（应用于 MACD_1H 和 MACD_4H 的得分）
    if ema_4h_aligned and ema_1h_ok:
        return 1.2   # EMA 完美排列，MACD 分数放大 20%
    elif ema_1h_ok:
        return 1.0   # EMA 基本支持，不修正
    else:
        return 0.6   # EMA 结构反向，MACD 分数压缩 40%
```

---

## 五、V2.0 综合评分系统

### 5.1 评分权重

| 模块 | 权重 | 最大得分 | 计算方式 |
|------|------|----------|----------|
| MACD_1H × EMA修正 | 35% | 0.35 | V1.0 逻辑 × EMA 系数 |
| MACD_4H × EMA修正 | 15% | 0.15 | V1.0 逻辑 × EMA 系数 |
| VWAP 价值中枢 | 15% | 0.15 | 新增（见第三章） |
| MACD_15M + EMA精化 | 20% | 0.20 | V1.0 逻辑 + EMA 加成 |
| 成交量确认 | 15% | 0.15 | V1.0 逻辑不变 |
| **总计** | **100%** | **1.00** | |

### 5.2 V2.0 评分计算完整流程

```python
def calculate_v2_score(data):
    
    # ── Step 1: 原有 MACD 各层基础分 ──────────────────────────
    score_1h_base  = get_macd_1h_score(data)    # V1.0 逻辑，满分 0.35
    score_4h_base  = get_macd_4h_score(data)    # V1.0 逻辑，满分 0.15
    score_15m_base = get_macd_15m_score(data)   # V1.0 逻辑，满分 0.20
    score_vol      = get_volume_score(data)     # V1.0 逻辑，满分 0.15

    # ── Step 2: EMA 修正系数 ──────────────────────────────────
    ema_multiplier = calculate_ema_score(...)   # 0.6 / 1.0 / 1.2

    # EMA 修正只作用于 1H 和 4H 的 MACD 分数
    score_1h  = min(score_1h_base  * ema_multiplier, 0.35)
    score_4h  = min(score_4h_base  * ema_multiplier, 0.15)

    # ── Step 3: 15M 入场精化（EMA21_15M 加成） ────────────────
    score_15m = refine_15m_entry(
        close_15m=data.close_15m,
        ema21_15m=data.ema21_15m,
        direction=data.direction,
        macd_entry_score=score_15m_base
    )
    score_15m = min(score_15m, 0.20)  # 上限 0.20

    # ── Step 4: VWAP 评分（新增） ────────────────────────────
    score_vwap = calculate_vwap_score(
        price=data.close_1h,
        vwap=data.vwap_daily,
        direction=data.direction
    )

    # ── Step 5: VWAP 硬性否决检查 ────────────────────────────
    if score_vwap == 0.0:
        return 0.0  # VWAP 偏离超过 3%，直接否决

    # ── Step 6: EMA 硬性否决检查 ─────────────────────────────
    if ema_multiplier == 0.0:
        return 0.0  # EMA 结构完全反向，直接否决

    # ── Step 7: 综合总分 ─────────────────────────────────────
    total_score = score_1h + score_4h + score_vwap + score_15m + score_vol

    return total_score
```

### 5.3 入场阈值（调整）

| 参数 | V1.0 | V2.0 | 调整原因 |
|------|------|------|----------|
| `min_entry_score`（15M 最低） | 0.30 | 0.25 | 权重降低，门槛同步调整 |
| `min_signal_score`（综合最低） | 0.45 | **0.50** | 引入 VWAP 后信号质量提升，适当提高总门槛 |

> 综合门槛从 0.5 提高至 0.85，过滤掉低质量信号，预计减少约 15%～20% 的交易次数，但胜率和盈亏比提升。

---

## 六、止损系统升级

### 6.1 V1.0 止损的问题

V1.0 使用固定 2% 初始止损，存在两个结构性问题：

- **牛市中被扫**：强趋势中 2% 止损对应不到 1× ATR，正常回调即触发
- **熊市中亏损大**：高波动率环境下 2% 止损金额过大（按仓位比例计算）

### 6.2 V2.0 双层止损体系

**第一层：EMA 结构止损（替代固定 2%）**

```python
def calculate_ema_stop_loss(close, ema21_1h, ema55_1h, atr_1h, direction):
    """
    动态止损：基于 EMA 结构 + ATR 缓冲
    """
    if direction == 'long':
        # 优先用 EMA21 作为止损锚点
        if close > ema21_1h * 1.005:  # 价格明显高于 EMA21
            stop = ema21_1h - atr_1h * 0.5
        else:  # 价格贴近 EMA21，用 EMA55
            stop = ema55_1h - atr_1h * 0.3
        
        # 安全校验：止损距离不超过入场价的 3%
        max_stop = close * 0.97
        return max(stop, max_stop)
    
    # 做空对称
    ...
```

**第二层：VWAP 止损辅助**

```python
def calculate_vwap_stop(close, vwap, direction):
    """
    VWAP 作为次级止损参考
    做多：价格跌破 VWAP 下方 0.5% 时减仓 50%
    """
    if direction == 'long':
        vwap_alert = vwap * 0.995  # VWAP 下方 0.5%
        return vwap_alert          # 作为预警线，不是硬止损
```

### 6.3 止损升级对比

| 场景 | V1.0 止损 | V2.0 止损 | 改善效果 |
|------|-----------|-----------|----------|
| 强趋势入场 | 固定 -2% | EMA21 - 0.5×ATR（约 -0.8%～-1.2%） | 止损更紧，保留更多利润 |
| 回踩 EMA21 入场 | 固定 -2% | EMA55 - 0.3×ATR（约 -1.5%～-2.0%） | 止损合理，给回调空间 |
| 偏离 VWAP 入场 | 固定 -2% | VWAP 下方 0.5% 预警 + EMA 止损 | 双重保护 |
| 极端行情 | 固定 -2% | 上限约束 max(-3%) + ATR 熔断 | 防止止损过宽 |

### 6.4 动态止损（追踪止损升级）

```python
# V1.0: 盈利超过 3% 后启动追踪止损
# V2.0: 基于 EMA21 的动态追踪

def trailing_stop_v2(current_price, ema21_1h, atr_1h, direction,
                      unrealized_pnl_pct):
    
    if unrealized_pnl_pct < 0.01:  # 浮盈 < 1%，不移动止损
        return None
    
    if direction == 'long':
        # 阶段1（浮盈 1%～2%）：提至开仓价附近
        if unrealized_pnl_pct < 0.02:
            return entry_price * 0.999  # 接近保本
        
        # 阶段2（浮盈 2%～4%）：跟随 EMA21
        elif unrealized_pnl_pct < 0.04:
            return ema21_1h - atr_1h * 0.5
        
        # 阶段3（浮盈 > 4%）：紧跟 EMA21
        else:
            return ema21_1h - atr_1h * 0.3
```

---

## 七、入场过滤规则（新增否决项）

V2.0 在 V1.0 评分基础上，新增以下硬性否决条件，任一触发即禁止入场：

### 7.1 VWAP 否决项

```
否决 1：VWAP 偏离超过 ±3.0%
        → 价格严重偏离价值中枢，均值回归风险过高

否决 2：VWAP 方向与入场方向连续 3 日相反
        → 日内资金成本持续不支持该方向
```

### 7.2 EMA 否决项

```
否决 3：1H 收盘价跌破 EMA55（做多时）
        → 中期趋势结构破坏，不做多

否决 4：4H EMA 排列完全反向
        （做多时：EMA21 < EMA55 < EMA200）
        → 大级别趋势反向，降为软性否决（降权 40%，不硬性禁止）
```

### 7.3 组合否决项

```
否决 5：MACD_1H 翻红 + 价格距 EMA55 偏离超过 5%
        → 追高信号，翻红已经是在大幅偏离后发生的，质量极低

否决 6：成交量评分 < 0.05 + VWAP 评分 < 0.10
        → 量价双重不确认，信号不可信
```

### 7.4 否决项汇总表

| 编号 | 类型 | 条件 | 处理方式 |
|------|------|------|----------|
| V1 | VWAP | 偏离 > ±3% | 硬性否决 |
| V2 | VWAP | 连续 3 日方向相反 | 降权 50% |
| V3 | EMA | 1H 跌破 EMA55（做多） | 硬性否决 |
| V4 | EMA | 4H EMA 完全反向 | 降权 40% |
| V5 | 组合 | 翻红 + EMA55 偏离 > 5% | 硬性否决 |
| V6 | 组合 | 成交量 + VWAP 双低 | 降权 60% |

---

## 八、V2.0 信号示例

### 8.1 理想做多信号（VWAP + EMA 双重加持）

```
时间: 2026-03-18 10:00

价格结构:
  当前价: 95,200 USDT
  日内 VWAP: 95,050 USDT（偏离 +0.16%，贴近 VWAP）
  1H EMA21: 94,950 USDT（价格在上方）
  1H EMA55: 94,200 USDT（价格在上方，EMA21 > EMA55）
  4H EMA 排列: EMA21 > EMA55 > EMA200（强多排列）

MACD_1H（权重 35%）:
  翻红信号 → 基础分 0.35
  EMA 修正系数: 1.2（4H 完美排列 + 1H EMA55 上方）
  最终得分: min(0.35 × 1.2, 0.35) = 0.35 ✅

MACD_4H（权重 15%）:
  红柱增长 → 基础分 0.12
  EMA 修正: 1.2
  最终得分: min(0.12 × 1.2, 0.15) = 0.14

VWAP（权重 15%）:
  偏离 +0.16%（贴近 VWAP，回踩后入场）
  得分: 0.15（满分）✅

MACD_15M（权重 20%）:
  翻红跟随 → 基础分 0.20
  EMA21_15M 精化: 价格贴近 EMA21，× 1.15
  最终得分: min(0.20 × 1.15, 0.20) = 0.20 ✅

成交量（权重 15%）:
  volume_ratio = 1.8 → 得分 0.15

综合评分:
  = 0.35 + 0.14 + 0.15 + 0.20 + 0.15
  = 0.99

止损设置:
  EMA21_1H - 0.5 × ATR = 94,950 - 300 = 94,650 USDT
  止损距离: (95,200 - 94,650) / 95,200 = 0.58%（比 V1.0 的 2% 更精准）

结果: 开多仓 ✅，杠杆 5x
```

---

### 8.2 V2.0 新增过滤的信号（V1.0 会入场，V2.0 拒绝）

```
时间: 2026-03-18 14:30

价格结构:
  当前价: 97,000 USDT
  日内 VWAP: 94,800 USDT（偏离 +2.32%，高于 VWAP 较多）
  1H EMA21: 95,500 USDT（价格偏高）

MACD_1H: 翻红 → V1.0 基础分 0.40

V1.0 综合评分（假设其他项正常）:
  ≈ 0.40 + 0.12 + 0.20 + 0.10 = 0.82
  → V1.0 会入场（评分 > 0.45）✅

V2.0 VWAP 评分:
  偏离 +2.32%（> 1.5%，大幅降权）
  VWAP 得分: 0.05

V2.0 否决检查:
  偏离 2.32% < 3%，未触发硬性否决
  但 EMA 偏离检查：价格距 EMA55 约 +4.8% → 接近否决 V5 阈值

V2.0 综合评分:
  = 0.35 + 0.14 × 0.6（EMA 偏离降权）+ 0.05 + 0.16 + 0.10
  = 0.35 + 0.084 + 0.05 + 0.16 + 0.10
  = 0.744 → 仍会入场（但仓位降级）

实际意义:
  V2.0 不完全拒绝，但通过 VWAP 低分，将杠杆从 5x 降至 4x，
  仓位从 1.2× 降至 1.0×，自动降低了追高风险。
  若偏离 > 3%（如 97,600 USDT），则触发 V1 硬性否决，完全不入场。
```

---

### 8.3 V2.0 新增精化：回踩 EMA21 + 贴近 VWAP 的最优入场

```
时间: 2026-03-18 16:00（1H 回踩后的 15M 信号）

价格结构:
  当前价: 94,980 USDT（正在回踩 1H EMA21）
  日内 VWAP: 95,020 USDT（价格略低于 VWAP，偏离 -0.04%）
  1H EMA21: 95,000 USDT（价格贴近）
  1H EMA55: 94,200 USDT（结构完好）

MACD_1H: 红柱稳定（非翻红，但仍为正）
MACD_15M: 回踩后刚翻红

VWAP 得分: 0.15（满分，贴近 VWAP）
EMA 修正: 1.0（正常，未触发加成）
15M EMA21 精化: 贴近 EMA21 → × 1.15

综合评分:
  = 0.25（1H稳定×1.0）+ 0.10 + 0.15 + min(0.20×1.15,0.20) + 0.12
  = 0.82

这类回踩 EMA21 + 贴近 VWAP 的信号是 V2.0 最鼓励的入场形态：
  - 入场价接近均值（VWAP），风险回报比最优
  - 止损可以放在 EMA55 附近，距离仅约 0.8%
  - 上方空间大（尚未偏离 VWAP）
```

---

## 九、预期效益分析

### 9.1 V2.0 相对 V1.0 的理论改善

| 指标 | V1.0 实测 | V2.0 预期 | 改善逻辑 |
|------|-----------|-----------|----------|
| 胜率 | 55.0% | **62%～65%** | VWAP + EMA 过滤追高追低假信号 |
| 盈亏比 | 2.74 | **3.0～3.5** | EMA 动态止损更精准，减少过早止损 |
| 交易频率 | 340 笔 | **260～290 笔** | 门槛提高至 0.50，约减少 15%～20% 交易 |
| 最大回撤 | 2.10% | **1.5%～1.8%** | VWAP 否决项过滤高偏离追入 |
| 夏普比率 | 24.32 | **28+** | 胜率 + 盈亏比双升，波动率降低 |

### 9.2 各新增机制的贡献来源

**VWAP 过滤的贡献（预期 +4%～5% 胜率）：**

V1.0 的假信号有相当比例发生在价格大幅偏离均值后（追高追低），VWAP 过滤直接针对这类场景。特别是 V1.0 回测中 ADX < 20（弱趋势）时胜率仅 51.7%，这类场景往往是价格在均值附近震荡，VWAP 能有效识别当前价格相对于均值的位置。

**EMA 结构过滤的贡献（预期 +2%～3% 胜率）：**

4H EMA 完全反向排列时，MACD 翻红信号的可信度大幅下降（逆势反弹而非趋势启动）。V1.0 对此无感知，EMA 层将这类信号的权重压缩 40%，配合提高后的综合门槛（0.50），多数逆势信号将不满足入场条件。

**EMA 动态止损的贡献（预期 +0.3～0.5 盈亏比）：**

V1.0 固定 2% 止损在强趋势市场过宽（利润缩水）、在精确结构位入场时又可能过宽（资金利用率低）。EMA21 - 0.5×ATR 的动态止损在强趋势入场时通常只需 0.6%～1.2%，意味着在相同风险预算下可以持有更大仓位，同时减少被扫概率。

### 9.3 主要风险提示

- VWAP 在极端趋势行情中（价格持续偏离均值）会减少参与机会，可能错过部分强势单边行情
- EMA 在市场快速变化时存在滞后性，极端行情（黑天鹅）仍需结合极端行情应对方案
- 回测结果需在实盘中验证，新增参数需要对不同币种分别优化

---

## 十、配置文件 V2.0

```json
{
  "strategy_mode": "macd_mtf_strategy_v2",
  "version": "2.0",
  
  "macd_config": {
    "macd_1h_fast": 12, "macd_1h_slow": 26, "macd_1h_signal": 9,
    "macd_4h_fast": 12, "macd_4h_slow": 26, "macd_4h_signal": 9,
    "macd_15m_fast": 12, "macd_15m_slow": 26, "macd_15m_signal": 9,
    "macd_threshold": 0.00005
  },
  
  "ema_config": {
    "ema_1h_periods": [21, 55],
    "ema_4h_periods": [21, 55, 200],
    "ema_15m_periods": [21],
    "ema_multiplier_strong": 1.2,
    "ema_multiplier_normal": 1.0,
    "ema_multiplier_weak":   0.6,
    "ema_55_1h_hard_block":  true
  },
  
  "vwap_config": {
    "vwap_anchor": "daily_utc0",
    "vwap_deviation_optimal":  0.005,
    "vwap_deviation_warning":  0.015,
    "vwap_deviation_hard_block": 0.030,
    "vwap_weight": 0.15
  },
  
  "scoring_weights": {
    "weight_1h_direction":    0.35,
    "weight_4h_enhancement":  0.15,
    "weight_vwap":            0.15,
    "weight_15m_entry":       0.20,
    "weight_volume":          0.15
  },
  
  "entry_thresholds": {
    "min_entry_score":  0.25,
    "min_signal_score": 0.50
  },
  
  "stop_loss_config": {
    "use_dynamic_stop": true,
    "ema_stop_atr_multiplier": 0.5,
    "max_stop_loss_pct": 0.03,
    "vwap_alert_deviation": 0.005,
    "trailing_stop_mode": "ema21_based"
  },
  
  "leverage_config": {
    "score_0.75_plus": 5,
    "score_0.60_plus": 4,
    "score_0.50_plus": 3,
    "below_threshold": 0
  }
}
```

---

## 附录：V1.0 → V2.0 迁移指南

### 对原有代码的修改范围

| 模块 | 修改类型 | 说明 |
|------|----------|------|
| `macd_1h_scorer.py` | 新增 EMA 修正系数调用 | 在分数计算后乘以 EMA 系数 |
| `macd_4h_scorer.py` | 新增 EMA 修正系数调用 | 同上 |
| `macd_15m_entry.py` | 新增 EMA21_15M 精化 | 可选加成，逻辑独立 |
| `volume_scorer.py` | 不变 | — |
| `signal_aggregator.py` | 新增 VWAP 评分 + 否决项 | 核心新增模块 |
| `stop_loss_manager.py` | 替换为动态止损逻辑 | 原固定 2% 改为 EMA 动态 |
| `config.json` | 参数扩展 | 新增 `ema_config`、`vwap_config` |

### 推荐验证步骤

```
Step 1: 在历史数据上分别计算 V1.0 和 V2.0 的信号列表
Step 2: 对比两个版本的信号差异（新增过滤了哪些，新增捕捉了哪些）
Step 3: 统计 V2.0 被 VWAP 否决的信号，事后验证是否确实应该被过滤
Step 4: 统计 V2.0 被 EMA 结构加成的信号，事后验证胜率是否更高
Step 5: 对比止损触发率（V2.0 动态止损 vs V1.0 固定 2%）
Step 6: 确认效果后切换至实盘
```

---

*文档版本：V2.0*
*基于 V1.0（回测 +52.85%，胜率 55%）升级*
*最后更新：2026-03-18*
