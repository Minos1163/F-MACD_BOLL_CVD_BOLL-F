# 2026-05-26 21:45 后四象限策略未开仓归因报告

**评审对象**：实盘 `quadrant_resonance` 最新策略日志  
**分析窗口**：北京时间 `2026-05-26 21:45:00` 至 `2026-05-27 09:15:15`  
**对应 UTC**：`2026-05-26 13:45:00` 至 `2026-05-27 01:15:15`  
**日志目录**：`D:\AIDCA\AI2\logs\2026-05`  
**结论类型**：生产日志归因，不涉及本报告内修改实盘策略

---

## 1. 结论先行

从北京时间 `2026-05-26 21:45` 开始至当前最新日志，最新 `quadrant_resonance` 策略确实没有新增开仓。

本次不开仓不是执行层拒单、不是保证金 `<1U` 阻断、不是容量满、不是风控熔断，也没有看到 API 崩溃或异常堆栈。根因发生在**信号层第一道四小时主象限判定**：

```text
reason = quadrant_defense_no_entry
```

在该窗口内，所有被扫描 symbol 都被四象限引擎判定为 `DEFENSE`，因此没有任何候选进入后续评分、仓位、风控、执行链路。

更关键的是：窗口内市场宽度并非一直很差，慢牛检测曾多次成立，最后三个周期也连续显示 `is_bull=True`。但新四象限策略不再使用旧的 slow-bull continuation 作为旁路入口；即使市场宽度强，只要 4H 主象限没有进入 Q1/Q2/Q3/Q4，仍然全量 HOLD。

---

## 2. 证据汇总

### 2.1 runtime 主日志统计

统计文件：

- `logs\2026-05\2026-05-26\runtime.out.18.log`
- `logs\2026-05\2026-05-27\runtime.out.00.log`
- `logs\2026-05\2026-05-27\runtime.out.06.log`

窗口：UTC `2026-05-26 13:45:00` 起。

| 指标 | 结果 |
|---|---:|
| FUND_FLOW cycles | 48 |
| 首个周期 | `2026-05-26T13:45:03Z` |
| 最新周期 | `2026-05-27T01:15:03Z` |
| `logic=quadrant_resonance` | 1316 |
| `决策=HOLD` | 1316 |
| `状态=noop` | 1316 |
| `决策原因=quadrant_defense_no_entry` | 1316 |
| `HOLD归因=waiting_rule_confirmation` | 1316 |
| BUY/SELL/CLOSE 行数 | 0 |
| ERROR/Traceback/Exception/拒单/失败 行数 | 0 |

这说明最新策略没有生成任何真实开仓动作；执行层收到的是 HOLD，所以执行结果自然是 noop。

### 2.2 entry/exit 审计日志统计

统计文件：

- `logs\2026-05\2026-05-26\fund_flow\fund_flow_entry_exit_audit.jsonl`

窗口内审计记录：

| 指标 | 结果 |
|---|---:|
| 总审计记录 | 2632 |
| `pre_execution` | 1316 |
| `post_execution` | 1316 |
| `operation=hold` | 2632 |
| `operation!=hold` | 0 |
| `execution.status=noop` | 1316 |
| `strategy.source=blocked` | 2632 |
| `reason=quadrant_defense_no_entry` | 2632 |
| 覆盖 symbol 数 | 28 |

样本审计特征：

```json
{
  "operation": "hold",
  "reason": "quadrant_defense_no_entry",
  "strategy_source": "blocked",
  "strategy": {
    "source": "blocked",
    "method": "blocked",
    "decision_reason": "quadrant_defense_no_entry",
    "stage": "blocked"
  },
  "sizing": {
    "target_portion_of_balance": 0.0,
    "estimated_notional_usdt": 0.0
  },
  "execution": {
    "status": "noop",
    "message": "hold"
  }
}
```

这进一步证明：未开仓不是订单提交后失败，而是策略在提交订单前已经全部阻断。

---

## 3. `quadrant_defense_no_entry` 的代码含义

代码位置：

- `src\fund_flow\quadrant_resonance.py`

四象限判定逻辑：

```python
ema_state = self._ema_state(tf_4h)
hist = self._series(tf_4h, "macd_hist_series", "macd_hist_array", "macd_hist")
pos_strength = self._hist_strengthening(hist, "long", bars=2)
neg_strength = self._hist_strengthening(hist, "short", bars=2)

if ema_state == 1 and pos_strength:
    return Quadrant.Q1
if ema_state == -1 and pos_strength:
    return Quadrant.Q2
if ema_state == -1 and neg_strength:
    return Quadrant.Q3
if ema_state == 1 and neg_strength:
    return Quadrant.Q4
return Quadrant.DEFENSE
```

EMA 状态定义：

```python
if ema20 > ema50 > ema200:
    return 1
if ema20 < ema50 < ema200:
    return -1
return 0
```

MACD 柱增强定义：

```python
long:  hist[-1] > 0 且最近 bars 根逐根升高
short: hist[-1] < 0 且最近 bars 根逐根降低
```

因此，`quadrant_defense_no_entry` 精确定义为：

1. 4H EMA20/EMA50/EMA200 没有严格多头或空头排列；或
2. 4H MACD histogram 没有连续 2 根同向增强；或
3. 4H 指标序列缺失/长度不足，导致增强判定为 false。

一旦进入 `DEFENSE`，策略直接返回 HOLD，不再继续检查 RSI、1H EMA、15m 入场形态、评分阈值、仓位、风控、执行层。

---

## 4. 市场宽度与四象限冲突

窗口内 slow bull 检测结果：

| 指标 | 结果 |
|---|---:|
| `SLOW_BULL is_bull=True` cycles | 6 |
| `SLOW_BULL is_bull=False` cycles | 42 |

典型强宽度周期：

```text
2026-05-26T14:30:03Z is_bull=True breadth=0.96 btc30=0.933% alt_med60=1.337% confirm=2
2026-05-26T20:30:03Z is_bull=True breadth=0.93 btc30=0.141% alt_med60=0.553% confirm=2
2026-05-27T00:45:03Z is_bull=True breadth=0.93 btc30=-0.028% alt_med60=0.339% confirm=2
2026-05-27T01:00:04Z is_bull=True breadth=0.96 btc30=0.193% alt_med60=0.892% confirm=2
2026-05-27T01:15:03Z is_bull=True breadth=0.89 btc30=0.153% alt_med60=0.490% confirm=2
```

最后一个周期审计中，market breadth 明确为慢牛：

```json
{
  "is_slow_bull": true,
  "mode": "alt_breadth_led",
  "breadth_ratio": 0.8928571428571429,
  "btc_ret_30m": 0.0015328274102050948,
  "alt_median_60m": 0.00489972205635931,
  "confirm_count": 2
}
```

但这些周期仍全部是：

```text
operation=hold
reason=quadrant_defense_no_entry
```

归因：当前新策略的首要准入条件是 4H 四象限，不是市场宽度。市场宽度强只能说明当前环境可能适合寻找机会，但不能绕过 4H EMA+MACD 象限门槛。

---

## 5. 排除项

### 5.1 不是执行层拒单

窗口内没有 BUY/SELL/CLOSE 决策行。审计中 `post_execution` 均为：

```text
execution.status = noop
execution.message = hold
```

执行层没有收到开仓单。

### 5.2 不是保证金 `<1U` 或最小名义价值阻断

审计中所有 HOLD 的 sizing 为：

```text
target_portion_of_balance = 0
estimated_notional_usdt = 0
```

且 gate 字段中 `micro_margin_gate`、`micro_notional_gate`、`min_open_notional_gate` 均为空。这说明订单连仓位计算都没有进入，无法归因到低保证金拦截。

### 5.3 不是容量满

窗口内账户权益基本空仓：

```text
first: equity=98.45 available=98.45
last:  equity=98.43 available=98.43
```

审计中 position notional 为 0。没有证据显示 active symbol capacity 满。

### 5.4 不是崩溃或异常

窗口内 runtime 主日志未出现 `ERROR`、`Traceback`、`Exception`、`拒单`、`失败`。`runtime.err` 只有旧 MACD_V2 废弃配置提示，不是新策略异常。

---

## 6. 二级根因边界

目前可以确定的根因层级：

```text
无开仓
└── 信号层全量 HOLD
    └── quadrant_resonance 第一关阻断
        └── 4H 主象限 = DEFENSE
```

但现有日志还不能区分下面两种二级原因：

### A. 策略按设计防守

市场虽然短线宽度变强，但多数 symbol 的 4H EMA20/50/200 可能仍未形成严格排列，或 4H MACD histogram 尚未连续增强。按当前策略定义，这属于防御区，不开仓是预期行为。

### B. 指标输入或审计缺失导致误判

日志里没有输出每个 symbol 的：

- 4H `ema20`
- 4H `ema50`
- 4H `ema200`
- 4H `macd_hist_series` 最近 3 根
- `ema_state`
- `pos_strength`
- `neg_strength`
- 最终 `quadrant`

因此无法仅凭现有日志确认 `DEFENSE` 是真实市场状态，还是 4H 指标序列缺失、预热不足、字段映射错误、hist series 长度不足导致的 false negative。

特别需要注意：runtime 文本里反复出现：

```text
ema_cross=NONE, macd=NONE/NEAR_ZERO
```

这可能只是旧通用日志字段没有适配新策略，也可能提示新策略输入的指标摘要不充分。需要通过新增 quadrant 原始指标审计才能定性。

---

## 7. 对实盘策略设计的影响

当前新策略有一个结构性行为：

```text
4H 四象限未成立 => 所有 symbol 直接 HOLD
```

这个设计很防守，但会在两类行情中空仓：

1. **短线/中线慢牛启动初期**：市场宽度和 15m/1H 动量已经变强，但 4H EMA200 仍滞后，EMA20/50/200 尚未严格排列。
2. **强势反弹但 4H 仍处过渡状态**：个别强势币已经明显启动，但 4H MACD 柱没有连续 2 根增强，或 EMA 排列仍无序。

这解释了用户观察到的现象：行情看起来不错，但系统没有开仓。并不一定是程序崩溃，而是新四象限入口过度依赖 4H 主趋势确认。

---

## 8. 建议给 DeepSeek 评审的关键问题

请重点评审以下问题，而不是先调执行层：

1. `quadrant_defense_no_entry` 是否应该作为绝对硬阻断？
2. 在 100U 小资金实盘中，是否允许 slow-bull breadth 成立时引入一个小仓位 Q0/Q2 过渡象限入口？
3. 4H EMA200 严格排列是否过慢，是否应允许 `EMA20 > EMA50 且 price > EMA50/EMA200` 的早期趋势结构？
4. 4H MACD histogram 连续 2 根增强是否过于离散，是否应改为 “hist > 0 且斜率非负/近 3 根均值上升”？
5. 新策略日志是否必须补齐每个 HOLD 的 4H 原始指标，以避免下次只能看到最终 reason？

---

## 9. 建议的下一步诊断改动

本报告不直接改实盘策略，但建议先补审计，不先放宽开仓：

### 9.1 给 `quadrant_defense_no_entry` 增加二级原因

建议将当前单一 reason 拆成：

```text
quadrant_defense_ema_disorder
quadrant_defense_macd_not_strengthening
quadrant_defense_missing_4h_indicators
```

### 9.2 每次 HOLD 写入 quadrant debug metadata

每个 symbol 每个 cycle 至少记录：

```json
{
  "symbol": "ICPUSDT",
  "quadrant_4h": "DEFENSE",
  "ema20_4h": 0.0,
  "ema50_4h": 0.0,
  "ema200_4h": 0.0,
  "ema_state_4h": 0,
  "macd_hist_4h_last3": [0.0, 0.0, 0.0],
  "macd_pos_strength_4h": false,
  "macd_neg_strength_4h": false,
  "blocked_reason_detail": "ema_disorder|macd_not_strengthening|missing_indicators"
}
```

### 9.3 慢牛旁路只做 shadow 评估

在 slow bull 成立但 quadrant DEFENSE 的周期，记录 shadow candidate：

```text
slow_bull_shadow_candidate
```

字段包括 30m/60m 动量、1H EMA、15m RSI、后续 4/8/12 bar MFE/MAE。先验证这些被 DEFENSE 拦下的强势币后续是否真的赚钱，再决定是否开放小仓位实盘入口。

---

## 10. 最终归因

本次“昨晚 21:45 后没有开仓”的直接原因是：

```text
quadrant_resonance 新策略把所有 symbol 判定为 4H DEFENSE，
在第一道四象限主趋势门槛处全部 HOLD，
没有任何信号进入评分、仓位、风控和执行层。
```

这不是低保证金订单阻断，也不是执行 BUG。更准确地说，这是**新四象限策略入口过于严格或 4H 指标输入缺少可审计细节**导致的全量空仓。

当前最需要的不是盲目放宽阈值，而是先补齐 4H EMA/MACD 原始指标审计，确认 DEFENSE 是真实市场结构还是指标输入/预热/字段映射问题。若确认是真实结构，再评估是否为 slow-bull 市场增加 shadow 过渡入口。
