# 从 2026-05-27 20:00 BJT 起未开仓路径排查

## 结论

从北京时间 `2026-05-27 20:00:00` 到 `2026-05-28 09:15:15`，日志显示开仓没有走到交易所下单失败阶段，而是在策略决策阶段已经被置为 `HOLD`。

最主要的阻断点是 `quadrant_resonance` 策略的 15m 入场形态硬门槛：

- 配置启用了 `require_15m_entry_pattern=true`。
- `QuadrantResonanceEngine.analyze()` 在共振分数达到阈值前后，仍要求 `factor_scores` 中必须有 `entry_15m`。
- 如果 15m 入场形态缺失，直接返回 `allowed=False`、`reason=missing_15m_entry_pattern`。
- `DecisionEngine` 收到 `allowed=False` 后把决策转成 `operation=hold`，因此后续开仓、最小下单、probe rescue、execution router 都不会进入。

如果预期是“高分信号允许 probe 开仓”，那么挡住开仓路径的 BUG/设计缺陷就是：

> `require_15m_entry_pattern` 在策略层把高分信号提前降级为 `HOLD`，导致 `probe_floor_rescue` 无法介入；同时该拒绝路径没有把 15m 形态失败的具体子条件写入审计，排查时只能看到总原因 `missing_15m_entry_pattern`。

如果预期是“必须等 15m 精确形态才开仓”，那这不是交易执行 BUG，而是当前配置过严导致没有任何信号通过。

## 时间窗口

- 用户口径：北京时间昨晚 20 点。
- 对应 UTC：`2026-05-27 12:00:00+00:00`。
- 覆盖日志：
  - `D:\AIDCA\AI2\logs\2026-05\2026-05-27`
  - `D:\AIDCA\AI2\logs\2026-05\2026-05-28`

## 关键统计

### fund_flow_attribution

统计窗口内：

```text
first decision = 2026-05-27 20:00:04 BJT
last decision  = 2026-05-28 09:15:15 BJT
decisions      = 1400
executions     = 1400
```

全部决策都是：

```text
decision.operation = hold
execution.status   = noop
target_portion_of_balance > 0 的记录数 = 0
```

原因分布：

```text
763  missing_15m_entry_pattern
627  quadrant_defense_no_entry
  5  resonance_score_below_threshold
  3  ema20_distance_chase_block
  2  mid_score_needs_3bar_macd
```

这说明不是交易所拒单、余额不足、下单异常、保护单缺失等 execution path 问题，而是 `DecisionEngine -> strategy` 已经没有产生 BUY/SELL。

### entry_exit_audit

`D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow\fund_flow_entry_exit_audit.jsonl` 在窗口内有 `2800` 行审计，即 `1400` 个 pre/post pair：

```text
operation:
2800 hold

stage:
1400 pre_execution
1400 post_execution

target_gt_0 = 0
exec_non_noop = 0
order_nonnull = 0
```

在 `pre_execution` 中，存在 `score >= threshold` 但仍然 hold 的记录：

```text
212  missing_15m_entry_pattern
  2  mid_score_needs_3bar_macd
```

样本：

```text
2026-05-27 20:15:06 BJT ADAUSDT score=0.90 threshold=0.85 entry_15m="" reason=missing_15m_entry_pattern
2026-05-27 20:15:14 BJT JUPUSDT score=0.90 threshold=0.85 entry_15m="" reason=missing_15m_entry_pattern
2026-05-27 20:30:14 BJT JSTUSDT score=0.90 threshold=0.85 entry_15m="" reason=missing_15m_entry_pattern
2026-05-27 21:15:11 BJT POLUSDT score=0.90 threshold=0.85 entry_15m="" reason=missing_15m_entry_pattern
```

这类记录最能说明问题：不是分数低，而是 15m 入场形态缺失导致高分信号也被硬拒。

## 代码路径

### 1. 配置启用硬 15m 入场门槛

文件：`D:\AIDCA\AI2\config\trading_config_fund_flow.json`

```text
542  "strategy_mode": "quadrant_resonance",
555  "standard_threshold": 0.85,
556  "transition_threshold": 0.85,
566  "require_15m_entry_pattern": true,
567  "mid_score_requires_3bar_macd": true,
```

### 2. `missing_15m_entry_pattern` 直接返回 `allowed=False`

文件：`D:\AIDCA\AI2\src\fund_flow\quadrant_resonance.py`

```text
207  factor_scores = self._score_factors(direction, quadrant, tf15, tf1h)
211  score = sum(factor_scores.values())
215  threshold = ...
219  if self.config.require_15m_entry_pattern and "entry_15m" not in factor_scores:
222      return QuadrantSignal(
223          allowed=False,
232          reason="missing_15m_entry_pattern",
233          metadata=metadata,
234      )
```

`entry_15m` 只会在 `_entry_pattern_ok()` 为真时加入：

```text
393  if self._entry_pattern_ok(direction, tf15):
394      out["entry_15m"] = self.config.score_15m_entry
```

而 `_entry_pattern_ok()` 的条件很窄：

```text
572  def _entry_pattern_ok(self, direction, tf15):
576      near_ema = abs(close - ema20) <= atr
579      long 需要 15m MACD hist 由 <=0 穿越到 >0 且 near_ema
581      short 需要 15m MACD hist 由 >=0 穿越到 <0 且 near_ema
591      否则需要 near_ema 且方向 candle/pin bar
```

### 3. `allowed=False` 被 DecisionEngine 转成 HOLD

文件：`D:\AIDCA\AI2\src\fund_flow\decision_engine.py`

```text
5680  signal = self.quadrant_resonance_engine.analyze(...)
5690  if not signal.allowed:
5691      decision = FundFlowDecision(
5692          operation=Operation.HOLD,
5694          reason=signal.reason,
5695          metadata=metadata,
5696      )
5698      return decision
```

所以 `missing_15m_entry_pattern` 一旦出现，后面不会再有新开仓订单。

### 4. probe rescue 不会救 HOLD

配置里 `probe_floor_rescue` 启用但处于 shadow：

```text
333  "probe_floor_rescue": {
334    "enabled": true,
335    "shadow_mode": true,
336    "min_score_threshold": 0.8,
337    "probe_portion": 0.06,
338    "probe_min_open_portion": 0.042
```

代码上它只处理 BUY/SELL：

文件：`D:\AIDCA\AI2\src\app\fund_flow_bot.py`

```text
3657  if decision.operation not in (FundFlowOperation.BUY, FundFlowOperation.SELL):
3658      meta["reason"] = "not_entry"
3659      return decision, meta
```

而它的调用点也只在 `decision.operation in (BUY, SELL) and position is None` 后面：

```text
9872  if decision.operation in (FundFlowOperation.BUY, FundFlowOperation.SELL) and position is None:
9896      if decision.target_portion_of_balance < min_open_portion:
9897          decision, probe_meta = self._apply_probe_floor_rescue(...)
```

因此当前高分信号先被 `missing_15m_entry_pattern -> HOLD` 后，probe rescue 没机会介入。

## 排除项

### 不是交易所下单失败

证据：

- `execution.status` 全部是 `noop`。
- `order_nonnull=0`。
- `trade_fills_utc.csv` 最近成交停在 `2026-05-25 13:15:15 UTC`，窗口内没有新成交。

### 不是 signal_pool 阻断

配置里的 legacy `signal_pool.enabled=false`：

```text
1622  "signal_pool": {
1623    "enabled": false,
```

窗口内没有看到 `signal_pool_filter` 作为阻断主因。

### 不是 min_open_portion 阻断

`min_open_portion` 检查发生在 BUY/SELL 新开仓路径之后。当前所有决策已经是 `HOLD`，所以没有进入该分支。

### 不是 runtime 异常中断

`runtime.err.*.log` 仅看到 deprecated config warning：

```text
[MACD_V2] deprecated soft_15m / RSI refinement config ignored in RSI rhythm mode ...
```

未见 traceback、交易所拒单或执行异常。

## 疑似 BUG/评审问题

### P1: 高分信号被 15m 硬门槛提前降级，导致 probe 机制失效

证据：

- `score >= threshold` 但 `reason=missing_15m_entry_pattern` 的 pre_execution 记录有 `212` 条。
- `score >= 0.8` 且 `missing_15m_entry_pattern` 的 attribution decision 有 `238` 条。
- 所有这些记录最终 `operation=hold`、`target=0`、`execution=noop`。

评审问题：

1. `require_15m_entry_pattern=true` 是否本意就是“一票否决”？
2. 如果本意是高分允许 probe，那么应该在 `missing_15m_entry_pattern` 时保留 BUY/SELL + 小仓位，还是新增一个 `probe_missing_15m_entry_pattern` 分支？
3. `probe_floor_rescue.shadow_mode=true` 是否仍是预期？当前即使进入，也不会真正提高 target。

### P2: 审计字段不足，不能看出 15m 形态到底失败在哪个子条件

当前 audit 只有：

```text
reason=missing_15m_entry_pattern
entry_15m=""
factor_scores 不在主 runtime 摘要中完整展示
```

建议评审是否需要把 `_entry_pattern_ok()` 的子条件写入 metadata，例如：

- `near_ema`
- `hist_cross`
- `bullish`
- `bearish`
- `pin_bar`
- `close`
- `ema20`
- `atr`

这不会改变交易逻辑，但会显著降低下次排查成本。

## 复核命令

```powershell
$start=[datetimeoffset]'2026-05-27T12:00:00Z'
$files=@(
  'D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow_attribution.jsonl',
  'D:\AIDCA\AI2\logs\2026-05\2026-05-28\fund_flow_attribution.jsonl'
)
$rows=foreach($f in $files){
  if(Test-Path $f){
    Get-Content -LiteralPath $f | ForEach-Object {
      $o=$_|ConvertFrom-Json
      if([datetimeoffset]$o.ts -ge $start){ $o }
    }
  }
}
$rows | Where-Object event -eq 'decision' |
  Group-Object {$_.decision.reason} |
  Sort-Object Count -Descending |
  Select-Object Count,Name

$rows | Where-Object {
  $_.event -eq 'decision' -and
  [double]$_.decision.target_portion_of_balance -gt 0
} | Select-Object ts,decision
```

```powershell
$start=[datetimeoffset]'2026-05-27T12:00:00Z'
$file='D:\AIDCA\AI2\logs\2026-05\2026-05-27\fund_flow\fund_flow_entry_exit_audit.jsonl'
$rows=Get-Content -LiteralPath $file | ForEach-Object {
  $o=$_ | ConvertFrom-Json
  if ([datetimeoffset]$o.ts -ge $start) { $o }
}
$rows | Group-Object reason | Sort-Object Count -Descending | Select-Object Count,Name
$rows | Where-Object {
  $_.stage -eq 'pre_execution' -and
  [double]$_.signal.score -ge [double]$_.signal.threshold -and
  [double]$_.signal.threshold -gt 0
} | Group-Object reason | Sort-Object Count -Descending | Select-Object Count,Name
```

## 建议给 Claude 的评审问题

请重点评审：

1. 当前 `quadrant_resonance` 的 `require_15m_entry_pattern` 是否过于硬，是否与 `probe_floor_rescue` 的设计目标冲突？
2. 对 `score >= threshold` 但缺 `entry_15m` 的场景，应该继续 HOLD，还是允许极小 probe？
3. 如果允许 probe，应该修改 `QuadrantResonanceEngine` 输出，还是在 `DecisionEngine` 层把特定 `allowed=False` 转成 probe decision？
4. 在不引入未来函数、同 bar 成交假设、过拟合参数的前提下，怎样回测比较：
   - 当前硬门槛
   - 只放宽高分 `missing_15m_entry_pattern`
   - 保持硬门槛但增加 15m 失败细分诊断

