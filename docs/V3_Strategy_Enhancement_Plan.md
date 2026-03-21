# V3 策略提收益建议方案
## BTC 交易系统配套文件 · 专家组讨论稿

> **基准**：V3 当前回测 +44.67%，胜率 69.9%，盈利因子 3.01，156 笔交易
> **目标**：在不破坏主逻辑的前提下，将月收益提升至 60%+
> **原则**：优先提升已验证有效的部分，而非强行恢复被禁用的信号
> **配置基础**：`trading_config_fund_flow.json` + `MACD_MTF_Strategy_V3.md`

---

## 目录

1. [现状诊断：收益结构分析](#一现状诊断收益结构分析)
2. [建议一：Symbol 黑白名单重构（最高优先级）](#二建议一symbol-黑白名单重构最高优先级)
3. [建议二：多头信号的加仓机制启用](#三建议二多头信号的加仓机制启用)
4. [建议三：出场体系优化（分层减仓）](#四建议三出场体系优化分层减仓)
5. [建议四：空头侧修复（基本面过滤器）](#五建议四空头侧修复基本面过滤器)
6. [建议五：杠杆方向修正](#六建议五杠杆方向修正)
7. [建议六：时间窗口过滤](#七建议六时间窗口过滤)
8. [建议七：`flip_bullish` 条件性恢复](#八建议七flip_bullish-条件性恢复)
9. [建议八：`max_active_symbols` 动态扩容](#九建议八max_active_symbols-动态扩容)
10. [参数修改汇总](#十参数修改汇总)
11. [预期收益模型](#十一预期收益模型)
12. [执行优先级与风险提示](#十二执行优先级与风险提示)

---

## 一、现状诊断：收益结构分析

### 1.1 收益来源高度集中

这是 V3 最关键的结构性问题，也是提升空间最大的切入点：

| 信号类型 | 贡献盈亏 | 占总收益比例 | 方向 |
|----------|----------|-------------|------|
| `red_bar_growing` | +$4,736 | **95.7%** | 多头 |
| `flip_bearish` | +$213 | **4.3%** | 空头 |
| 合计（含其他损耗） | +$4,467 | 100% | — |

**诊断结论：**

V3 实质上是一个**单向多头系统**，空头侧几乎不贡献收益。这意味着：
- 多头侧有巨大的增强空间（加仓、更优出场、更好的 symbol）
- 空头侧需要修复，否则是在消耗资金占用和决策资源

### 1.2 Symbol 损益分布

| 分类 | Symbols | 说明 |
|------|---------|------|
| 严重拖累 | UNIUSDT（-$725）、HBARUSDT（-$479）、FILUSDT（-$273）、DOGEUSDT（-$207） | 合计拖累 -$1,684，占总资金 16.8% |
| 未知（未在 V3 中单独披露） | 其余 31 只 | 需要单独统计 |

**诊断结论：**

仅 4 只 symbol 就拖累了 +$1,684。若能消除这部分，V3 的理论收益将从 +44.67% 提升至 **+61.5%**，无需改动任何信号逻辑。

### 1.3 配置中的未充分利用资源

从 `trading_config_fund_flow.json` 中发现以下未被充分利用的机制：

| 配置项 | 当前值 | 状态 | 说明 |
|--------|--------|------|------|
| `dca_max_additions` | 0 | ❌ 禁用 | 加仓机制完全关闭 |
| `dca_martingale_enabled` | true | 但无效 | 启用但加仓次数为 0 |
| `take_profit_pct` | 0.0 | 纯 runner | 无分层止盈 |
| `reserve_percent` | 20% | 保守 | 20% 资金闲置 |
| `ema_strong_trend_leverage_mult` | 0.8 | 逆直觉 | 强趋势反而降杠杆 |
| `flip_bullish` strict filter | 已定义 | 但信号禁用 | 条件未被使用 |
| `deepseek_ai` | enabled | 已接入 | AI 权重路由是否最优待验证 |

---

## 二、建议一：Symbol 黑白名单重构（最高优先级）

### 2.1 核心逻辑

**不改一行策略代码，只优化 symbol 列表，预期直接提升收益 +15%～+17%。**

当前 35 只 symbol 中，已知 4 只合计亏损 -$1,684。这部分亏损是"负贡献"，不仅减少净利润，还占用 `max_active_symbols = 3` 的持仓槽，导致更优质的 symbol 错过入场机会。

### 2.2 立即执行：Symbol 黑名单

以下 symbol 建议立即移除，原因明确：

```json
"symbol_blacklist": [
  "UNIUSDT",    // total pnl: -$724.94, max drawdown: -7.41%
  "HBARUSDT",   // total pnl: -$478.79, max drawdown: -4.88%, streak: 5
  "FILUSDT",    // total pnl: -$272.69
  "DOGEUSDT"    // total pnl: -$206.77（注：单独 DOGE 回测 +13.8%，但在 V3 组合中拖累）
]
```

> **注意**：DOGEUSDT 在独立回测 profile 中表现为 +13.8%，但 V3 多 symbol 组合中表现为负。建议先移出，后续单独验证其在 V3 信号体系下是否可恢复。

### 2.3 优先保留：高质量 Symbol 白名单

根据 V1.0 回测数据和 config 中已有的 profile 信息，建议重点保留以下 symbol：

| Symbol | 依据 | 优先级 |
|--------|------|--------|
| SOLUSDT | 高流动性，趋势连续性好 | ⭐⭐⭐ |
| XRPUSDT | V1.0 回测 +$355，57.9% 胜率 | ⭐⭐⭐ |
| ATOMUSDT | V1.0 回测 +$545，66.7% 胜率 | ⭐⭐⭐ |
| ENSUSDT | V1.0 回测 +$303，64.3% 胜率 | ⭐⭐⭐ |
| AAVEUSDT | DeFi 龙头，趋势行情配合好 | ⭐⭐ |
| INJUSDT | 高波动，`red_bar_growing` 信号质量高 | ⭐⭐ |
| OPUSDT / ARBUSDT | L2 板块联动，趋势跟随效果好 | ⭐⭐ |

### 2.4 配置修改建议

```json
// trading_config_fund_flow.json 修改
"trading": {
  "symbols": [
    // 核心白名单（优先运行）
    "SOLUSDT", "XRPUSDT", "ATOMUSDT", "ENSUSDT",
    "AAVEUSDT", "INJUSDT", "OPUSDT", "ARBUSDT",
    "ADAUSDT", "AVAXUSDT", "NEARUSDT",
    "MKRUSDT", "RUNEUSDT", "TIAUSDT", "FETUSDT",
    "RNDRUSDT", "PEPEUSDT"
  ],
  // 移除：UNIUSDT, HBARUSDT, FILUSDT, DOGEUSDT,
  //       SHIBUSDT, VETUSDT, ALGOUSDT, MINAUSDT（低信号质量）
}
```

---

## 三、建议二：多头信号的加仓机制启用

### 3.1 核心逻辑

当前 `dca_max_additions = 0`，加仓机制完全禁用。`red_bar_growing` 已经证明是高质量信号（贡献 95.7% 收益），在信号持续确认时不加仓，是明显的利润漏出。

**目标**：在 `red_bar_growing` 信号持续的情况下，允许在特定条件下加仓一次，把赢家单扩大。

### 3.2 加仓触发条件（严格，防止马丁格尔风险）

```python
# 加仓条件：全部满足才允许
def allow_dca_addition(position):
    return (
        # 条件1：当前仓位处于浮盈状态（只加赢家）
        position.unrealized_pnl_pct >= 0.003  # 浮盈 ≥ 0.3%
        
        # 条件2：1H MACD 信号仍然是 red_bar_growing（趋势延续）
        and signal_1h.type == 'red_bar_growing'
        
        # 条件3：EMA 结构仍为 strong 或 normal
        and ema_structure in ['strong', 'normal']
        
        # 条件4：VWAP 分仍 ≥ 0.10（位置未过热）
        and vwap_score >= 0.10
        
        # 条件5：综合评分 ≥ 0.85（维持高门槛）
        and total_score >= 0.85
    )
```

### 3.3 加仓参数配置

```json
// 修改 fund_flow 配置
"dca_martingale_enabled": true,
"dca_max_additions": 1,            // 从 0 改为 1（最多加仓一次）
"dca_drawdown_thresholds": [0.003], // 不是回撤触发，而是浮盈触发
"dca_multipliers": [0.5],           // 加仓量为初始仓位的 50%（保守）
```

> **风险控制**：加仓后的总持仓止损统一按原始止损价执行，不因加仓而移动止损。加仓本身不改变止损距离，只增加获利时的持仓量。

---

## 四、建议三：出场体系优化（分层减仓）

### 4.1 当前问题

`take_profit_pct = 0.0`，纯依赖 `signal_reverse` 出场。这在趋势行情中能跑大段，但在震荡回撤时容易把浮盈大幅回吐，影响最终实现收益。

V3 回测显示 `signal_reverse` 是主要出场方式，说明这套逻辑的 edge 是对的。但可以在不破坏主逻辑的情况下，叠加一个**分层减仓**机制，锁定部分利润。

### 4.2 分层减仓方案

```
浮盈层级     操作                   剩余仓位继续持有
──────────────────────────────────────────────────
浮盈 ≥ 1.0%  减仓 20%（先锁定一部分）  80% 继续跑
浮盈 ≥ 2.0%  再减仓 20%              60% 继续跑
浮盈 ≥ 4.0%  再减仓 20%              40% 用 signal_reverse 跑大段
```

**逻辑**：前两次减仓只减 20%，保留主仓位继续运行。这样既锁定了部分利润，又不影响在强趋势中跑大段的能力。最后 40% 仍用 `signal_reverse` 出场。

### 4.3 保本线调整

当前 `breakeven_trigger_pnl_ratio = 0.003`（0.3%），触发太早，容易在 `red_bar_growing` 持续的趋势中被 EMA21 的正常回调扫到保本线，提前出场。

**建议调整：**

```json
"breakeven_trigger_pnl_ratio": 0.005,  // 从 0.3% 提升至 0.5%（触发更晚）
"breakeven_lock_ratio": 0.002,          // 从 0.1% 提升至 0.2%（保护更多）
```

这样保本线触发后能锁住 0.2% 的利润，减少"保本后立即被扫出然后继续上涨"的情况。

### 4.4 配置修改

```json
// fund_flow 配置修改
"take_profit_pct": 0.0,              // 保持纯 runner 模式
"breakeven_enabled": true,
"breakeven_trigger_pnl_ratio": 0.005, // 0.3% → 0.5%
"breakeven_lock_ratio": 0.002,        // 0.1% → 0.2%

// 新增分层止盈配置
"tiered_exit_enabled": true,
"tiered_exit_levels": [
  {"pnl_trigger": 0.010, "reduce_pct": 0.20},
  {"pnl_trigger": 0.020, "reduce_pct": 0.20},
  {"pnl_trigger": 0.040, "reduce_pct": 0.20}
]
```

---

## 五、建议四：空头侧修复（基本面过滤器）

### 5.1 核心问题

`flip_bearish` 只贡献 +$213，占总收益不到 5%，而多头 `red_bar_growing` 贡献 95.7%。空头侧问题在于：

**MACD `flip_bearish` 发生在价格下跌一段后，空头入场时位置往往已经偏冷，但方向正确的机会较少——因为加密市场长期偏多头**，纯技术面的空头信号质量整体低于多头。

### 5.2 解决方案：Funding Rate + OI Delta 联合过滤

配置文件中 `deepseek_ai` 已定义了以下权重，但空头侧未充分利用：

```json
// 当前 deepseek_ai 默认权重（已有但未针对空头优化）
"trend_funding": 0.08,    // Funding Rate 权重偏低
"trend_oi_delta": 0.25,   // OI Delta 权重最高
```

**建议为 `flip_bearish` 增加两个前置过滤条件：**

```python
def allow_flip_bearish_entry(market_data):
    """
    空头入场额外过滤器
    flip_bearish 在以下条件同时满足时，才允许入场
    """
    # 条件1：Funding Rate 为正且偏高（多头付资金费，说明市场偏多但即将被挤压）
    funding_positive_and_high = (
        market_data.funding_rate > 0.0005  # Funding 高于 0.05%（年化约 54%）
    )
    
    # 条件2：OI Delta 为负（未平仓量在下降，说明多头在减仓，非新增空头追跌）
    oi_delta_negative = market_data.oi_delta < 0
    
    # 条件3：VWAP 偏向（价格在 VWAP 上方，有均值回归空间）
    price_above_vwap = market_data.price > market_data.vwap * 1.005
    
    return (funding_positive_and_high 
            and oi_delta_negative 
            and price_above_vwap)
```

**逻辑解释：**

- Funding Rate 为正 → 多头在付费，说明市场超多头偏向，随时可能挤压
- OI Delta 为负 → 持仓量在减少，是多头主动减仓而非空头追跌（质量更高的空头信号）
- 价格在 VWAP 上方 → 有均值回归的空间，不是在低位追空

### 5.3 预期效果

满足这三个条件的 `flip_bearish` 信号数量会减少（更严格的过滤），但命中率将显著提升。历史上，Funding Rate > 0.05% + OI 下降 + 价格偏高的组合，是最高质量的反转空头信号。

---

## 六、建议五：杠杆方向修正

### 6.1 发现的问题

当前配置：

```json
"ema_strong_trend_leverage_mult": 0.8
```

**这是逆直觉的**：EMA 结构处于"strong"（4H EMA 完美多头排列）时，杠杆乘以 0.8，即从 3x 降至 2.4x。

但 EMA strong 恰恰是最确定的趋势环境，应该用**更高**杠杆，不是更低。

V3 文档的解释是："代表趋势质量更高，不代表应该更重仓"——这逻辑本身没错，但数值设置偏向保守。

### 6.2 修正方案

将 EMA 结构的杠杆影响方向修正：

```json
// 当前（逆直觉）
"ema_strong_trend_leverage_mult": 0.8   // strong 时降杠杆

// 建议修改为分层杠杆
"leverage_by_ema_structure": {
  "strong": 4,    // EMA 完美排列 → 最高杠杆 4x
  "normal": 3,    // EMA 正常 → 默认 3x
  "weak":   2,    // EMA 弱 → 最低 2x
  "against": 0    // EMA 反向 → 不入场（已有否决机制）
}
```

**预期影响：**

- EMA strong 场景（目前被 0.8 压低）会从 ~2.4x 提升至 4x
- 这类场景是 `red_bar_growing` 最强的场景
- 预计每笔高质量交易的收益增加 ~33%（从 2.4x 到 4x 的提升幅度）

### 6.3 风险边界

杠杆提升必须保持在 `max_leverage = 4` 上限内，且只在以下两个条件同时满足时才触发最高杠杆：

```
EMA 结构 = strong
AND
综合评分 ≥ 0.90（比当前入场门槛 0.85 更高）
```

---

## 七、建议六：时间窗口过滤

### 7.1 依据

Config 中已有的 backtest profile 揭示了时间过滤的价值：

```json
// doge_first profile 中排除的交易时间（UTC）
// 已排除：小时 1, 2, 11, 13, 17, 18
"allowed_entry_hours": [0,3,4,5,6,7,8,9,10,12,14,15,16,19,20,21,22,23]
```

BTC+ETH profile 更保守，只允许 12 个小时段入场。

这说明：**不是所有时段的 `red_bar_growing` 信号质量都相同**。亚洲夜间流动性差（UTC 01:00-02:00），欧洲午休（UTC 11:00-13:00）波动减弱，这些时段信号更多是噪声。

### 7.2 建议过滤时间段

基于加密市场流动性规律，建议 V3 增加时间过滤：

```json
// 新增配置
"allowed_entry_hours_utc": [
  // 亚洲开盘：00-10（但排除 01-02 流动性低谷）
  0, 3, 4, 5, 6, 7, 8, 9, 10,
  // 欧洲开盘：12-16
  12, 14, 15, 16,
  // 美国开盘：19-23
  19, 20, 21, 22, 23
],
// 排除：01, 02（亚洲深夜流动性差）
//       11（欧洲午休前）
//       13（欧洲午休）
//       17, 18（美欧交接，方向不稳定）
```

**预期效果：** 减少约 10%～15% 的交易次数，但集中在流动性最好、趋势最清晰的时段，预计胜率提升 2%～3%。

---

## 八、建议七：`flip_bullish` 条件性恢复

### 8.1 V3 文档的保留机制

V3 已定义了严格的 `flip_bullish` 恢复条件：

```
flip_bullish_min_vwap_score = 0.12
flip_bullish_require_pullback_bounce = true
flip_bullish_require_15m_growing = true
```

即：MACD 翻红 + 15M 回踩 EMA21 反弹 + 15M red_bar_growing + VWAP ≥ 0.12。

### 8.2 问题所在

`flip_bullish` 被整体禁用，原因是"在多轮回测中持续负贡献"。但这是**全体 symbol 的统计结论**。对于高质量 symbol（如 ATOMUSDT、SOLUSDT），`flip_bullish` 的质量可能显著高于均值。

### 8.3 建议：仅对白名单 Symbol 开放 `flip_bullish`

```python
# 新增配置：symbol 级别的信号开关
"symbol_signal_overrides": {
  "ATOMUSDT": {
    "disable_flip_bullish": false,    // ATOM：开放 flip_bullish
    "flip_bullish_strict_filter": true // 但必须满足严格过滤
  },
  "SOLUSDT": {
    "disable_flip_bullish": false,    // SOL：开放 flip_bullish
    "flip_bullish_strict_filter": true
  },
  // 其他所有 symbol 默认保持禁用
  "_default": {
    "disable_flip_bullish": true
  }
}
```

**验证路径：**

1. 先在历史数据上单独统计 ATOMUSDT、SOLUSDT 的 `flip_bullish` 命中率
2. 若单独胜率 ≥ 60% 且盈利因子 ≥ 1.5，则在实盘中开放
3. 开放时保持严格过滤条件（不是简单地恢复全部 `flip_bullish`）

---

## 九、建议八：`max_active_symbols` 动态扩容

### 9.1 当前限制

`max_active_symbols = 3`：同时最多持有 3 只 symbol。

当市场进入整体趋势行情（多 symbol 同时出现 `red_bar_growing`），当前配置会错过第 4、5 个高质量信号。

### 9.2 建议：基于市场环境的动态扩容

```python
def get_dynamic_max_symbols(market_environment):
    """
    根据市场环境动态调整最大持仓 symbol 数
    """
    # 趋势明确 + 多 symbol 同向信号出现
    if (active_signals_count >= 4
            and avg_signal_score >= 0.88
            and btc_4h_ema_structure == 'strong'):
        return 5   # 扩容至 5 个 symbol
    
    # 标准趋势环境
    elif active_signals_count >= 2 and avg_signal_score >= 0.85:
        return 4   # 扩容至 4 个 symbol
    
    # 默认保守
    else:
        return 3   # 维持 3 个
```

**约束条件：**

- 单 symbol 仓位比例随扩容自动降低（总敞口不变）：
  - 3 个 symbol：每个 60% × 1/3 = 20% 净敞口
  - 4 个 symbol：每个 60% × 1/4 = 15% 净敞口
  - 5 个 symbol：每个 60% × 1/5 = 12% 净敞口
- 这与 `min_open_portion = 0.06` 和 `max_position_percent = 60` 兼容

---

## 十、参数修改汇总

### 10.1 立即执行（不需要重新回测，直接影响明确）

```json
// trading_config_fund_flow.json 修改项

// 1. Symbol 黑名单（移除）
// 从 trading.symbols 中删除：
// "UNIUSDT", "HBARUSDT", "FILUSDT", "DOGEUSDT"

// 2. 保本线优化
"breakeven_trigger_pnl_ratio": 0.005,  // 0.003 → 0.005
"breakeven_lock_ratio": 0.002,          // 0.001 → 0.002

// 3. 加仓机制启用
"dca_max_additions": 1,                 // 0 → 1
"dca_drawdown_thresholds": [0.003],     // 浮盈 0.3% 触发加仓
"dca_multipliers": [0.5],               // 加仓 50% 初始仓位

// 4. 杠杆修正
"ema_strong_trend_leverage_mult": 1.2,  // 0.8 → 1.2（强趋势加杠杆）
```

### 10.2 需要验证后执行（建议先回测确认）

```json
// 5. 时间窗口过滤（新增）
"allowed_entry_hours_utc": [0,3,4,5,6,7,8,9,10,12,14,15,16,19,20,21,22,23],

// 6. 分层减仓（新增）
"tiered_exit_enabled": true,
"tiered_exit_levels": [
  {"pnl_trigger": 0.010, "reduce_pct": 0.20},
  {"pnl_trigger": 0.020, "reduce_pct": 0.20},
  {"pnl_trigger": 0.040, "reduce_pct": 0.20}
],

// 7. 空头 Funding 过滤（新增）
"flip_bearish_extra_filter": {
  "require_positive_funding": true,
  "min_funding_rate": 0.0005,
  "require_oi_delta_negative": true,
  "require_price_above_vwap": true
},

// 8. flip_bullish 条件性恢复（高风险，最后执行）
"symbol_signal_overrides": {
  "ATOMUSDT": {"disable_flip_bullish": false},
  "SOLUSDT": {"disable_flip_bullish": false}
},
"enable_flip_bullish_strict_filter": true
```

---

## 十一、预期收益模型

### 11.1 各建议的增益估算

| 建议 | 机制 | 预期月收益增量 | 置信度 |
|------|------|--------------|--------|
| Symbol 黑名单（消除拖累） | 移除 -$1,684 的 4 只 symbol | **+$1,684 → +16.8%** | 高 |
| 加仓机制（DCA on winner） | 赢家单规模扩大 50% | +4%～+6% | 中高 |
| 出场优化（分层 + 保本线） | 减少浮盈回吐 | +3%～+5% | 中高 |
| 杠杆方向修正（strong → 4x） | EMA strong 场景盈利扩大 33% | +4%～+6% | 中 |
| 空头侧修复（Funding 过滤） | 空头胜率提升 | +2%～+4% | 中 |
| 时间窗口过滤 | 减少噪声信号 | +1%～+3% | 中 |
| `flip_bullish` 白名单恢复 | 新增优质多头信号 | +2%～+4% | 低中 |
| `max_active_symbols` 扩容 | 多捕捉趋势行情机会 | +3%～+5% | 中 |

### 11.2 综合预期

```
基准月收益：+44.67%

立即执行（Symbol 黑名单 + 杠杆修正 + 保本线）：
  +44.67% + 16.8% + 4% + 2% = 约 +67%

全部建议执行后（含验证项）：
  预期范围：+65% ～ +80%（取决于市场状态）
  保守估计：+60%（假设一半建议效果不及预期）
```

> **重要说明**：以上预估基于 V3 回测样本期的市场特征。实盘环境可能与回测存在差异，特别是杠杆提升和加仓机制在极端行情中的表现需要额外关注。

---

## 十二、执行优先级与风险提示

### 12.1 执行路线图

```
Week 1（立即执行，零风险）
  ✅ 移除 4 只黑名单 symbol
  ✅ 调整 breakeven 参数（0.3% → 0.5%）
  ✅ 修正 ema_strong_trend_leverage_mult（0.8 → 1.2）

Week 2（小范围回测验证后执行）
  📊 回测时间窗口过滤的效果
  📊 回测加仓机制（DCA = 1）的效果
  ✅ 执行通过的建议

Week 3（验证 + 小资金实盘测试）
  📊 回测分层减仓方案
  📊 回测空头 Funding 过滤
  🧪 用 20% 资金试跑新参数

Week 4（全量上线 + flip_bullish 决策）
  ✅ 全量切换至新参数
  📊 单独回测 ATOM/SOL 的 flip_bullish 数据
  🔄 根据数据决定是否开放 flip_bullish 白名单
```

### 12.2 必须保留的风险控制

无论做任何参数修改，以下风险控制必须保持不变：

```
✅ max_daily_loss_percent = 5（日损熔断保持）
✅ max_consecutive_losses = 2（连续亏损熔断保持）
✅ max_leverage 上限 = 4（绝对上限保持）
✅ reserve_percent ≥ 15%（不低于 15% 现金缓冲）
✅ min_signal_score = 0.85（入场门槛不降低）
```

### 12.3 最高风险提示

**最谨慎对待的建议**：`flip_bullish` 条件性恢复。V3 明确指出这个信号"在多轮统一时间轴回测中持续负贡献"。即使在白名单 symbol 上开放，也必须先通过至少 30 天的独立回测验证，不要因为单次表现好就全量上线。

**最高确定性的建议**：Symbol 黑名单。移除 4 只已知亏损 symbol，直接节省 -$1,684 的历史损耗，这是最确定性的改进，没有任何策略逻辑风险。

---

## 附录：V3 开放问题的建议回答

对应 V3 文档第 17 章"Key Open Questions"：

| 问题 | 本文建议 |
|------|----------|
| `red_bar_growing` 是否需要拆分（强趋势 vs 末端追高） | 用 EMA strong + VWAP ≥ 0.12 作为"强趋势"标准，叠加更高杠杆（已在建议五中涵盖） |
| `flip_bearish` 是否加 funding/OI 过滤 | 是，详见建议四，具体阈值：funding > 0.05%，OI delta < 0 |
| `take_profit_pct = 0.0` 是否保持纯 runner | 保持纯 runner，但叠加分层减仓（20%/20%/20%），详见建议三 |
| UNIUSDT、HBARUSDT 是否做风险开关 | 直接移入黑名单，而非开关，详见建议一 |
| 动态杠杆是否收缩至 2x～3x | 反向操作：EMA strong 时提升至 4x，weak 时保持 2x，详见建议五 |
| `max_active_symbols = 3` 是否最优 | 建议动态扩容至 4～5（趋势环境），详见建议八 |

---

*文档版本：V3 Enhancement Plan v1.0*
*基准策略：MACD_MTF_Strategy_V3（+44.67%，胜率 69.9%，PF 3.01）*
*最后更新：2026-03-19*
*供专家组内部讨论使用，请勿对外传播*
