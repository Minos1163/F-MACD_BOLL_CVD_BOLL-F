# AI2 资金流量化交易系统 — 策略交易逻辑说明

**版本**: V3.0（2026-03）  
**审阅用途**: 专家组技术审核  
**核心文件**: `src/fund_flow/decision_engine.py`, `config/trading_config_fund_flow.json`

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [信号生成层：多时间框架评分](#2-信号生成层多时间框架评分)
3. [市场状态识别（Regime）](#3-市场状态识别regime)
4. [方向判断层（Direction Guide）](#4-方向判断层direction-guide)
5. [分数融合层（Score Fusion）](#5-分数融合层score-fusion)
6. [动态权重路由（Weight Router）](#6-动态权重路由weight-router)
7. [趋势捕捉机制（Trend Capture）](#7-趋势捕捉机制trend-capture)
8. [信号池过滤（Signal Pool）](#8-信号池过滤signal-pool)
9. [开仓决策逻辑](#9-开仓决策逻辑)
10. [平仓决策逻辑](#10-平仓决策逻辑)
11. [执行层与风控层](#11-执行层与风控层)
12. [浮盈保护机制](#12-浮盈保护机制)
13. [重入抑制机制](#13-重入抑制机制)
14. [关键参数汇总](#14-关键参数汇总)

---

## 1. 系统架构总览

系统采用**四层流水线**结构，从市场数据到成交执行：

```
市场数据（Binance WebSocket）
        ↓
[数据采集层] MarketIngestionService — 多时间框架指标计算
        ↓
[决策层] FundFlowDecisionEngine — 评分/融合/方向/Regime判断
        ↓
[路由层] FundFlowExecutionRouter — 信号池过滤/去重/执行决策
        ↓
[执行层] OrderGateway — IOC/GTC下单 + TP/SL挂单
        ↓
[风控层] RiskManager — 冲突保护/浮盈保护/止损
```

**交易标的**: BTCUSDT、ETHUSDT、BNBUSDT、SOLUSDT、XAGUSDT、LTCUSDT  
**最大同时持仓标的数**: 2  
**仓位比例**: 单标的最大 60%，默认 60%  
**杠杆**: 最小 3x，默认 4x，最大 5x

---

## 2. 信号生成层：多时间框架评分

### 2.1 输入指标（来自 MarketIngestionService）

系统在多个时间框架（1m/3m/5m/15m/30m/1h/2h/4h）上计算以下资金流指标：

| 指标字段 | 含义 |
|---------|------|
| `cvd_ratio` | 累积成交量差（买-卖方向比） |
| `cvd_momentum` | CVD 动量（短期变化率） |
| `oi_delta_ratio` | 持仓量变化率 |
| `funding_rate` | 资金费率 |
| `depth_ratio` | 买卖深度比（盘口厚度） |
| `imbalance` | 订单流失衡度 |
| `liquidity_delta_norm` | 流动性增量归一化 |
| `micro_delta_last` | 微结构末位变化 |

同时计算技术指标（在 5m/15m 时间框架）：

| 技术指标 | 用途 |
|---------|------|
| MACD（8/21/5）| 趋势方向主判 |
| KDJ（J值）| 买卖时机辅助 |
| Bollinger Bands | 趋势延续/突破判断 |
| ADX | 趋势强度量化 |
| ATR | 波动率量化 |
| EMA（20/50，1H）| Regime方向判断 |

### 2.2 TREND 模式评分公式

**当前静态权重（Pack E 调整后）**:

```
long_score  = 0.20 × max(cvd, 0)
             + 0.10 × max(cvd_momentum, 0)
             + 0.25 × max(oi_delta, 0)
             + 0.08 × max(-funding, 0)
             + 0.18 × max(depth-1, 0)
             + 0.07 × max(imbalance, 0)
             + 0.10 × max(liquidity_delta_norm, 0)
             + 0.12 × max(liquidity_delta_norm, 0)  [liquidity_norm_factor_weight]

short_score = 对应负方向的镜像计算
```

**权重设计逻辑**:
- **弱化** CVD/CVD动量（0.30→0.30 总计）: 短线摆动噪声大，易在假突破中追错
- **强化** OI持仓量（0.22→0.25）: OI 增加伴随方向 = 真实建仓，信号更可靠
- **强化** 深度比率（0.15→0.18）: 盘口厚度反映做市商意图
- **强化** 流动性增量（0.08→0.10）: 大资金入场特征
- **减少** 微结构变化（0.06→0.02）: 高频噪声，干扰趋势判断

### 2.3 RANGE 模式评分公式

```
long_score  = 0.55 × max(-imbalance, 0)   # 失衡反转
             + 0.35 × max(-cvd_momentum, 0)  # 动量反转
             + 0.10 × max(-depth+1, 0)

short_score = 镜像

OI惩罚项: score -= min(|oi_delta|, 1.0) × 0.20   # 趋势扩张时压制区间信号
```

---

## 3. 市场状态识别（Regime）

**时间框架**: 1H  
**方法**: ADX + ATR + EMA 排列综合判断

### 3.1 Regime 分类规则

```
ADX >= 15.0  →  TREND（趋势模式）
ADX <  14.5  →  RANGE（区间模式）
14.5 ≤ ADX < 15.0  →  NO_TRADE 过渡区（禁止开仓）

ATR%  <  0.08%  →  NO_TRADE（波动率过低）
ATR%  >  2.0%   →  EXTREME_VOLATILITY（极端波动冷却）
```

### 3.2 趋势挂起状态（Trend Pending）

当 ADX 尚未达到趋势阈值但具备启动迹象时，进入 `TREND_PENDING` 状态：

```
条件：
  ADX >= 18.0 (trend_pending_adx_min)
  AND ADX 斜率 >= 0.05 (每小时变化)
  AND EMA 扩张度 >= 0.00015
```

Trend Pending 状态允许以较小仓位（`trial_position_mult`）先行入场。

### 3.3 方向锁定（Direction Lock）

在 TREND 模式下，根据 1H EMA 排列锁定交易方向：

```
EMA_fast (20) > EMA_slow (50)  →  LONG_ONLY
EMA_fast (20) < EMA_slow (50)  →  SHORT_ONLY
|EMA_spread| < neutral_zone    →  BOTH（不限方向）
```

- `direction_lock_mode = "soft"`: EMA 穿越时设置缓冲期，不立即切换
- `neutral_zone = 0.005`（Pack D 调整后）: 减少方向抖动

---

## 4. 方向判断层（Direction Guide）

### 4.1 三层特征架构

**第一层: 特征计算** — 将技术指标归一化到 [-1, 1]

```
macd        = clip(macd_hist_norm, -1, 1)          # MACD柱状图
macd_cross  = +1(金叉) / -1(死叉) / 0
macd_hist_mom = MACD柱状图斜率
kdj         = (KDJ_J - 50) / 50                    # KDJ归一化
kdj_cross   = +1(金叉) / -1(死叉)
kdj_zone    = +0.5(超卖区) / -0.5(超买区)
bb_pos      = (close - BB_mid) / (BB_band/2)        # 布林位置
cvd         = tanh(cvd_momentum × 300)              # CVD归一化
imbalance   = tanh(imbalance × 5)                   # 失衡归一化
```

**第二层: 双组合评分**（MACD_KDJ 模式）

| 组合 | 偏重 | 权重配置 |
|------|------|---------|
| MACD+KDJ | 拐点确认 | MACD:0.45, KDJ:0.25, MACD金叉:0.10, KDJ金叉:0.08, 动量:0.07, KDJ区间:0.05 |
| MACD+BB | 趋势延续 | MACD:0.40, BB:0.20, MACD金叉:0.14, BB突破:0.10, BB趋势:0.10, 动量:0.06 |

两组合同向时取 80%权重组合 + 20%辅助组合；反向时纯用胜者。  
BB 压缩时对 MACD+BB 施加 0.5 惩罚系数（避免横盘误判）。

**第三层: 方向判定**

```
|score| < neutral_zone (0.03)  →  BOTH
score > 0                       →  LONG_ONLY
score < 0                       →  SHORT_ONLY
```

### 4.2 MACD+KDJ+资金流混合评分（direction_guide）

```
得分 = MACD趋势分(×0.45) + KDJ时机分(×0.25) + 资金流分(×0.30)

MACD趋势: macd>0 → +1.0, macd<0 → -1.0, |macd|≈0 → RANGE模式
KDJ时机:
  J < 25 (超卖)  → 做多信号 +0.2~1.0
  J > 75 (超买)  → 做空信号 -0.2~-1.0
  金叉/死叉加权  → ×0.3
资金流: (cvd + imbalance) / 2

特殊: TREND_UP + KDJ超卖 → 背离加成 +0.15 (强趋势回踩做多)
```

---

## 5. 分数融合层（Score Fusion）

### 5.1 融合机制

将 15m 时间框架分数与 5m 执行框架分数加权融合：

```
fused_long  = (0.32 × score_15m_long  + 0.68 × score_5m_long)  × consistency_weight
fused_short = (0.32 × score_15m_short + 0.68 × score_5m_short) × consistency_weight
```

**配置**: `score_fusion.enabled = true`, `score_15m_weight = 0.32`, `score_5m_weight = 0.68`

### 5.2 一致性加权（Consistency Weight）

统计最近 3 根 15m K 线的方向一致性：

```
consistency_window = 3
若最近 N 根 15m 方向全部一致 → consistency_weight = 1.0 + 0.1 × (N - window + 1)
否则 → consistency_weight = 1.0
```

**逻辑**: 连续方向一致的趋势信号更可靠，给予额外权重奖励。

### 5.3 修复说明

> **历史缺陷（已修复）**: 原代码 `_fuse_scores` 方法中，无论 `score_fusion.enabled` 如何配置，始终以 5m_only 模式运行，导致 15m 趋势参数完全失效。已修复为根据配置项动态选择融合路径。

---

## 6. 动态权重路由（Weight Router）

### 6.1 架构说明

系统支持两套权重路径：

```
本地静态权重（deepseek_ai.default_weights）  ←  Pack E 调整目标
          ↓ 缓存 TTL 5分钟
DeepSeek AI 动态权重调度（deepseek_weight_router）
          ↓ AI 失败时降级回 本地权重
最终 WeightMap → _score_with_weights()
```

### 6.2 DeepSeekWeightRouter 工作原理

- **输入**: `regime + z_scores + micro_trap_active + adx_bucket`
- **输出**: 各因子权重 + 置信度（不输出交易方向）
- **约束**: 权重范围 [0.05, 0.50]，禁止输出方向/阈值/仓位指令（禁词扫描）
- **缓存**: 按 `symbol:regime:context_hash` 缓存 5~15 分钟
- **降级**: AI 调用失败 → 自动回退到本地静态权重

---

## 7. 趋势捕捉机制（Trend Capture）

### 7.1 标准入场条件（TREND 模式）

```
当前 Regime = TREND
AND 融合分数 >= 0.12 (min_score)
AND long_score - short_score >= 0.03 (min_gap)
AND CVD归一化 >= 0.08
AND 方向锁定允许（LONG_ONLY 或 BOTH）
AND 无极端波动冷却
```

### 7.2 趋势挂起入场（Trend Pending Entry）

```
当前 Regime = TREND_PENDING
AND 融合分数 >= 0.22 (trend_pending_min_score)
AND 方向确认
→ 以 trial_position_mult = 0.35 (35% 标准仓位) 入场试单
→ 后续确认 → 以 confirm_position_mult = 0.65 加仓至完整仓位
```

### 7.3 BOTH 方向试单（两侧允许时）

当方向锁定为 `BOTH`（中性区间）时，可根据资金流方向做较小的试探性入场：

```
当前 Regime = TREND + 方向 = BOTH
AND 融合分数 >= 0.12 (trend_both_trial_min_score)
AND 分差 >= 0.03
AND Regime 原始分 >= 0.03
AND 资金流确认 >= 0.0
→ 以试单仓位入场（不超过标准仓位 35%）
```

### 7.4 反转确认降噪

避免单根 K 线触发平仓（反转噪声过滤）：

```
需要连续 2 根 K 线确认反转信号
AND 反转方向分差 >= 0.08
AND （可选）需要方向锁定也确认反转
```

---

## 8. 信号池过滤（Signal Pool）

### 8.1 信号定义

| 信号名称 | 方向 | 指标 | 阈值 |
|---------|------|------|------|
| trend_long_cvd | LONG | cvd_momentum(5m) | >= 0.0005 |
| trend_long_imb | LONG | imbalance(5m) | >= 0.06 |
| trend_short_cvd | SHORT | cvd_momentum(5m) | <= -0.0005 |
| trend_short_imb | SHORT | imbalance(5m) | <= -0.06 |
| range_long_extreme | LONG | imbalance(5m) | <= -0.14 |
| range_short_extreme | SHORT | imbalance(5m) | >= 0.14 |

### 8.2 信号池配置

| 池名称 | 用途 | 最小分数 | 边沿冷却 |
|-------|------|---------|---------|
| trend_pool | 标准趋势信号 | 0.06 | 1200s |
| trend_pool_major | 主流币种趋势 | 0.10 | 900s |
| trend_pool_short_only | 强制空单限制（long_score=999屏蔽多） | 0.06 | 1200s |
| range_pool | 区间极端反转 | 0.30 | 600s |

### 8.3 边沿触发机制（Edge Trigger）

防止同一信号在单次趋势中多次触发：

```
条件满足时：rising_edge → 触发一次
条件维持时：steady_true → 不再重复触发
条件消失时：falling_edge → 重置状态
冷却期内再次触发：rising_edge_in_cooldown → 拒绝
```

### 8.4 去重机制（Trigger Dedupe）

```
trigger_dedupe_seconds = 180
同一 symbol + trigger_type 在 180 秒内：只允许触发一次
```

---

## 9. 开仓决策逻辑

### 9.1 完整决策流程

```
1. 计算 5m 原始分数（_score_trend / _score_range / _score_with_weights）
2. 计算 15m 框架分数
3. _fuse_scores() → 融合得到最终评分
4. _compute_direction_features() → 提取技术特征
5. _score_macd_kdj_fund_flow_hybrid() → 方向判断
6. _apply_direction_lock() → 过滤禁止方向的信号
7. check_trend_capture_conditions() → 趋势捕捉条件检验
8. evaluate_signal_pool() → 信号池规则过滤
9. 分数 >= 开仓阈值 → 生成 FundFlowDecision(BUY/SELL)
10. FundFlowRiskEngine.validate_decision() → 参数边界验证
11. 执行路由 → IOC 下单
```

### 9.2 开仓阈值

| 模式 | 多头阈值 | 空头阈值 |
|------|---------|---------|
| 主配置 | 0.07 | 0.06 |
| TREND 引擎 | 0.085 | 0.075 |
| RANGE 引擎 | 0.48 | 0.40 |

> 注：TREND 引擎阈值覆盖主配置（engine_params 优先级更高）

### 9.3 仓位与杠杆计算

```
仓位大小 = default_target_portion × trial_position_mult (试单时)
         = default_target_portion × confirm_position_mult (确认时)

杠杆 = f(score, threshold):
  strength = (score - threshold) / (1 - threshold)
  leverage = levels[int(strength × len(levels))]
  levels = [3, 4, 5] (min/default/max)
```

---

## 10. 平仓决策逻辑

### 10.1 主动平仓触发条件

1. **反向信号超阈值**: 反方向分数 >= close_threshold (0.30)，且连续确认 2 根 K 线
2. **Stop Loss 触发**: 亏损超过 stop_loss_pct (0.45%)
3. **Take Profit 触发**: 盈利超过 tp_level (0.25% / 0.55% 两档减仓)
4. **方向锁定切换**: 1H EMA 反转切换方向锁定
5. **MACD 锚定退出**: 15m MACD 柱状图扩张确认反转

### 10.2 TP/SL 分档止盈

```
止盈档位配置（TREND）:
  档位1: 盈利 0.25% → 减仓 40%
  档位2: 盈利 0.55% → 减仓 30%

移动止损:
  激活条件: MFE >= 0.55%
  追踪距离: 0.16%（价格回撤即锁定）
```

### 10.3 收益保本（Breakeven）

```
保本激活: 浮盈 >= breakeven_fee_buffer (0.08%)
保本锁定: 入场价 + arm_buffer (0.03%)
```

---

## 11. 执行层与风控层

### 11.1 执行降级策略

```
开仓:
  1. IOC 限价单（价格容差 1%）
  2. IOC 失败 → 价格步进 10bps 重试
  3. 全部 IOC 失败 → GTC 限价单（兜底）
  4. 可选 Market 市价单（默认关闭）

平仓:
  1. IOC 重试 4 次
  2. 全部失败 → GTC reduce-only 兜底
  3. 可选 Market 市价平仓（默认关闭）
```

### 11.2 账户级别风控

| 风控项 | 参数 |
|-------|------|
| 日最大亏损 | 5% |
| 连续亏损次数 | 2次 |
| 日亏损冷却 | 8小时 |
| 连续亏损冷却 | 30分钟 |
| 极端波动冷却 | ATR% > 2.0%，持续 2 根 5m K 线 → 冷却 30 分钟 |

### 11.3 冲突保护（Conflict Protection）

当持仓产生方向冲突信号时：

```
轻冲突（conflict_light）:
  EV 冲突分 >= 0.14 → 收紧止损
  浮盈足够（MFE >= 0.25%）→ 轻度减仓 75%

硬冲突（conflict_hard）:
  EV 冲突分 >= 0.40 + 增量 >= 0.12 → 强制减仓 35%
  TRAP 分 >= 0.92 → 触发熔断平仓

冲突确认:
  EV方向 与 LW方向 同时反向 → CIRCUIT_EXIT
  连续 5 根确认 K 线 → 硬退出
```

---

## 12. 浮盈保护机制

### 12.1 轻止盈（Light Take Profit）

在冲突信号出现时，若浮盈已足够，提前锁定部分收益：

```
触发条件（Pack B 调整后）:
  light_take_profit_only_range = false  (趋势/区间均可触发)
  持仓时间 >= 180 秒
  MFE (最大有利偏移) >= 0.25%
  当前浮盈 >= 0.10%

执行: 减仓 75%（light_take_profit_pct）
```

### 12.2 浮盈收紧止损（Light Tighten）

```
触发条件:
  轻冲突信号 + 趋势模式
  持仓时间 >= 600 秒
  MFE >= 0.25%

执行: ATR × 2.2 倍作为新止损距离
```

---

## 13. 重入抑制机制

防止频繁重入导致"来回打脸"：

| 参数 | 值 | 作用 |
|-----|-----|------|
| `hard_exit_new_pos_buffer_minutes` | 10 分钟 | 硬退出后保护期（新开仓条件更严格）|
| `edge_cooldown_seconds`（trend_pool）| 1200 秒 | 信号池边沿触发冷却 20 分钟 |
| `trigger_dedupe_seconds` | 180 秒 | 触发器去重 3 分钟 |

**新仓保护期内更严格的条件**:
- 止损触发阈值乘以 1.35
- TRAP 触发阈值提升到 0.95
- 需要 3 根确认 K 线（正常 2 根）

---

## 14. 关键参数汇总

### 14.1 开仓控制

| 参数 | 值 | 说明 |
|-----|-----|------|
| long_open_threshold | 0.07 | 多单开仓最低分数 |
| short_open_threshold | 0.06 | 空单开仓最低分数 |
| trend_pending_min_score | 0.22 | 趋势挂起入场最低分 |
| min_score (trend_capture) | 0.12 | 趋势捕捉最低分 |
| min_gap | 0.03 | 多空分差要求 |
| direction_guide.neutral_zone | 0.03 | 方向中性区（< 此值为BOTH）|

### 14.2 仓位控制

| 参数 | 值 | 说明 |
|-----|-----|------|
| default_target_portion | 0.60 | 默认仓位比例 |
| trial_position_mult | 0.35 | 试单仓位系数 |
| confirm_position_mult | 0.65 | 确认仓位系数 |
| max_active_symbols | 2 | 最大同时持仓标的 |

### 14.3 止损止盈

| 参数 | 值 | 说明 |
|-----|-----|------|
| stop_loss_pct | 0.45% | 基础止损 |
| dynamic_stop_loss | 0.35%~0.45% | ATR动态止损（TREND引擎）|
| take_profit 档位1 | 0.25% / 减仓40% | 第一档止盈 |
| take_profit 档位2 | 0.55% / 减仓30% | 第二档止盈 |
| trailing_stop 激活 | MFE >= 0.55% | 移动止损激活 |
| trailing_stop 距离 | 0.16% | 移动止损回撤距离 |

### 14.4 TREND 静态权重（Pack E）

| 因子 | 权重 | 调整方向 |
|-----|------|---------|
| OI 持仓量 | 0.25 | ↑（强化真实建仓确认）|
| 深度比率 | 0.18 | ↑（强化盘口做市意图）|
| CVD | 0.20 | ↓（弱化短线摆动）|
| 流动性增量 | 0.10 | ↑（强化大资金入场）|
| CVD动量 | 0.10 | ↓（弱化追涨杀跌）|
| 资金费率 | 0.08 | ↓（降权）|
| 订单流失衡 | 0.07 | ↓（弱化噪声）|
| 微结构变化 | 0.02 | ↓（高频噪声最小化）|

---

*文档生成时间：2026-03，基于当前代码与配置实际状态*
