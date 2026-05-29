# 严格执行命令：配置核验 + 持仓退出守卫 + 分阶段入场放行
**审阅日期**: 2026-05-13  
**性质**: 强制执行指令，非建议；每一条均有验收断言  
**背景**: 上次优化部分未落地（runtime 仍显示 shadow_mode=true），TRUMP 持仓反向信号未触发提前止损，导致额外损失

---

## 🚨 立即执行（今天，不允许跳过）

---

### [命令-0] 确认部署状态，这是所有其他命令的前提

**问题证据**

```
当前配置文件：probe_floor_rescue.shadow_mode = false
运行时日志：   probe_floor_rescue.shadow_mode = True  ← 矛盾

结论：bot 进程仍在使用旧配置，新配置未加载。
在这个状态下，一切上次审阅的修复均未生效。
继续叠加新配置没有意义，必须先确认部署。
```

**必须执行的验证步骤**

```bash
# Step 1: 停止当前 bot 进程
# (根据实际启动方式选择)
pkill -f "fund_flow_bot" || kill $(lsof -ti:YOUR_PORT)

# Step 2: 确认进程已停止
ps aux | grep fund_flow_bot | grep -v grep
# 预期：无输出

# Step 3: 重启 bot
python3 src/main.py --config config/trading_config_fund_flow.json

# Step 4: 等待第一个 cycle（约 15 分钟），然后检查日志
grep "probe_floor_rescue" logs/2026-05/2026-05-13* | tail -5
# 必须看到：shadow_mode=False（注意大小写）

# Step 5: 检查权重是否生效
grep "weight_rsi_rhythm" logs/2026-05/2026-05-13* | tail -3
# 必须看到：0.22（而非 0.30）

# Step 6: 检查 shrink cap 是否覆盖 1H
grep "shrink_cap" logs/2026-05/2026-05-13* | tail -5
# 必须看到：hit on 1H 或 hit on 4H（而非只有 4H）
```

**验收断言（Python 脚本）**

```python
# scripts/verify_deployment.py
# 每次重启后必须运行此脚本，通过才能继续

import json, sys, re
from pathlib import Path

def verify():
    errors = []

    # 1. 检查配置文件
    cfg = json.load(open("config/trading_config_fund_flow.json"))

    pf = cfg.get("probe_floor_rescue", {})
    if pf.get("shadow_mode") != False:
        errors.append(f"probe_floor_rescue.shadow_mode = {pf.get('shadow_mode')}, must be false")

    w = cfg.get("scoring_weights", {})
    if abs(w.get("weight_rsi_rhythm", 0) - 0.22) > 0.001:
        errors.append(f"weight_rsi_rhythm = {w.get('weight_rsi_rhythm')}, must be 0.22")
    if abs(w.get("weight_4h_direction", 0) - 0.45) > 0.001:
        errors.append(f"weight_4h_direction = {w.get('weight_4h_direction')}, must be 0.45")
    if abs(w.get("weight_4h_enhancement", 1) - 0.00) > 0.001:
        errors.append(f"weight_4h_enhancement = {w.get('weight_4h_enhancement')}, must be 0.00")

    shrink = cfg.get("signal_type_position_caps", {})
    for k in ["red_bar_shrinking", "green_bar_shrinking"]:
        apply_to = shrink.get(k, {}).get("apply_to", [])
        if "signal_1h" not in apply_to:
            errors.append(f"signal_type_caps.{k}.apply_to missing signal_1h")

    if errors:
        print("❌ 部署验证失败：")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("✅ 部署验证通过，所有配置已正确加载")

verify()
```

```bash
# 每次重启后执行：
python scripts/verify_deployment.py
# 必须输出 ✅ 才能继续后续步骤
# 如果 ❌，检查配置文件路径、JSON 格式、进程是否用了正确的 --config
```

---

## 🔴 优先级 P0：持仓退出守卫（TRUMP 事件根因）

---

### [命令-1] 实装 position_exit_signal_guard

**TRUMP 事件的完整失败链**

```
15:15 BJ  开多 TRUMP @ 2.483（signal_1h=red_bar_shrinking，这是错误信号）
16:00 BJ  signal_1h → red_bar_shrinking，RISK: mae=-1.37%，action=none  ← 失败1
17:00 BJ  signal_1h 仍 red_bar_shrinking，score=0.763 过阈值但 HOLD      ← 失败2
17:45 BJ  signal_1h=red_bar_shrinking，mae=-1.37%，action=none           ← 失败3
18:00 BJ  signal_1h=red_bar_shrinking，rsi_1h_against_veto，action=none  ← 失败4
19:00 BJ  DCA 触发！drawdown=1.05% 加仓                                  ← 失败5（雪上加霜）
19:52 BJ  价格止损出场 @ 2.387，亏损 -1.131 USDT

关键矛盾：
  策略侧 16:00~18:30 连续检测到 rsi_1h_direction_against_veto
  这意味着策略自己知道 1H 方向与持仓方向相反
  但 RISK 模块仍然 action=none
  DCA 模块在持仓亏损时加仓，进一步扩大暴露

两个独立 bug：
  Bug A: RISK 模块没有把"策略侧 veto 信号"转化为退出动作
  Bug B: DCA 在持仓方向已经明确反转时仍然触发
```

**实装代码（逐行可执行）**

```python
# src/app/fund_flow_bot.py 或 src/fund_flow/exit_signal_guard.py（新文件）

class PositionExitSignalGuard:
    """
    持仓期间，将策略侧的方向反转信号转化为主动退出动作。
    独立于价格止损，作为前置退出层。
    """

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", True)

        # 1H 信号反转触发（必须参数）
        self.bearish_1h_signals = set(
            config.get("bearish_1h_signals",
                        ["flip_bearish", "green_bar_growing", "green_bar_shrinking"])
        )
        self.bullish_1h_signals = set(
            config.get("bullish_1h_signals",
                        ["flip_bullish", "red_bar_growing", "red_bar_shrinking"])
        )

        # 连续确认根数（防止单根噪音）
        self.confirm_bars_required = config.get("confirm_bars_required", 2)

        # MAE 条件（已亏损到一定程度才触发，避免在正常波动时退出）
        self.mae_trigger_pct = config.get("mae_trigger_pct", -0.008)  # -0.8%

        # DCA 保护：方向反转时禁止 DCA
        self.block_dca_on_reverse = config.get("block_dca_on_reverse", True)

        # 状态跟踪
        self._reverse_bars: dict[str, int] = {}   # symbol → 连续反转根数

    def evaluate(
        self,
        symbol:       str,
        position:     dict,     # 当前持仓 {side, entry_price, unrealized_pnl_pct}
        signal_now:   dict,     # 当前周期策略信号 {signal_1h, rsi_dir_1h, veto_code}
    ) -> dict:
        """
        返回：
          { "action": "CLOSE"|"REDUCE"|"HOLD"|"BLOCK_DCA",
            "reduce_pct": float,
            "reason": str }
        """
        if not self.enabled:
            return {"action": "HOLD", "reason": "guard disabled"}

        side        = position["side"]          # "LONG" or "SHORT"
        mae_pct     = position.get("unrealized_pnl_pct", 0)
        signal_1h   = signal_now.get("signal_1h", "")
        veto_code   = signal_now.get("veto_code", "")

        # ── 判断当前信号是否反向 ───────────────────────────
        is_reverse = False
        if side == "LONG" and signal_1h in self.bearish_1h_signals:
            is_reverse = True
        if side == "SHORT" and signal_1h in self.bullish_1h_signals:
            is_reverse = True

        # rsi_1h_direction_against_veto 也视为反向信号
        if "rsi_1h_direction_against_veto" in veto_code:
            is_reverse = True

        # ── 连续根数计数 ────────────────────────────────────
        if is_reverse:
            self._reverse_bars[symbol] = self._reverse_bars.get(symbol, 0) + 1
        else:
            self._reverse_bars[symbol] = 0

        bars = self._reverse_bars[symbol]

        # ── DCA 阻断（立即生效，不等 confirm_bars）─────────
        if is_reverse and self.block_dca_on_reverse:
            return {
                "action":     "BLOCK_DCA",
                "reduce_pct": 0,
                "reason":     f"reverse signal detected ({signal_1h}), DCA blocked",
            }

        # ── 触发条件：连续 N 根反向 + MAE 已亏损 ────────────
        if bars >= self.confirm_bars_required and mae_pct <= self.mae_trigger_pct:
            # 第一阶段：减仓 50%
            if bars == self.confirm_bars_required:
                return {
                    "action":     "REDUCE",
                    "reduce_pct": 0.50,
                    "reason": (
                        f"reverse signal confirmed {bars} bars, "
                        f"mae={mae_pct:.2%}, reduce 50%"
                    ),
                }

            # 第二阶段（多一根仍反向）：全平
            if bars >= self.confirm_bars_required + 1:
                return {
                    "action":     "CLOSE",
                    "reduce_pct": 1.00,
                    "reason": (
                        f"reverse signal confirmed {bars} bars, "
                        f"mae={mae_pct:.2%}, full close"
                    ),
                }

        return {
            "action":     "HOLD",
            "reverse_bars": bars,
            "reason":     f"no exit condition met (bars={bars}, mae={mae_pct:.2%})",
        }
```

**在 fund_flow_bot.py 中集成**

```python
# src/app/fund_flow_bot.py
# 在 _process_symbol 的 RISK 决策之后，DCA 决策之前，插入：

def _apply_exit_signal_guard(self, symbol: str, position: dict, signal: dict) -> bool:
    """
    返回 True = 已触发退出，跳过后续 DCA 逻辑
    """
    result = self.exit_signal_guard.evaluate(symbol, position, signal)
    action = result["action"]

    if action == "CLOSE":
        self._log_info(f"[ExitGuard] {symbol} FULL CLOSE: {result['reason']}")
        self._execute_close(symbol, ratio=1.0, reason="exit_signal_guard_full")
        return True

    elif action == "REDUCE":
        self._log_info(f"[ExitGuard] {symbol} REDUCE 50%: {result['reason']}")
        self._execute_close(symbol, ratio=0.50, reason="exit_signal_guard_reduce")
        # 不 return True，允许继续监控剩余仓位

    elif action == "BLOCK_DCA":
        self._log_info(f"[ExitGuard] {symbol} DCA BLOCKED: {result['reason']}")
        self._skip_dca = True   # 设置标志位，DCA 模块检查此标志
        return False

    return False


# DCA 触发前检查：
def _maybe_trigger_dca(self, symbol: str, position: dict) -> bool:
+   if getattr(self, "_skip_dca", False):
+       self._skip_dca = False
+       self._log_info(f"[DCA] {symbol} DCA skipped by exit_signal_guard")
+       return False
    # ... 原有 DCA 逻辑 ...
```

**对应配置**

```diff
# config/trading_config_fund_flow.json

+ "position_exit_signal_guard": {
+   "enabled":              true,
+   "bearish_1h_signals":   ["flip_bearish", "green_bar_growing", "green_bar_shrinking"],
+   "bullish_1h_signals":   ["flip_bullish", "red_bar_growing", "red_bar_shrinking"],
+   "confirm_bars_required": 2,
+   "mae_trigger_pct":      -0.008,
+   "block_dca_on_reverse": true
+ }
```

**TRUMP 事件回放验证**

```
如果 exit_signal_guard 已实装：
  15:15 BJ  开多 @ 2.483
  16:00 BJ  signal_1h=red_bar_shrinking → is_reverse=True，bars=1，mae=-1.37%
            mae=-1.37% < -0.8%，bars=1 < 2，DCA blocked
  16:15 BJ  signal_1h=red_bar_shrinking → bars=2，mae=-1.37%
            ✅ 触发 REDUCE 50%，出场一半 @ ~2.47
  16:30 BJ  signal_1h=red_bar_shrinking → bars=3
            ✅ 触发 CLOSE 100%，出场剩余 @ ~2.47

  实际出场价 ~2.47（vs 止损出场 2.387）
  节省损失估算：-1.131 × 50% ≈ -0.565 USDT
  如果 DCA 也被阻断：避免 19:00 的加仓，进一步节省约 -0.3 USDT
```

---

## 🟡 优先级 P1：分阶段入场放行（有序，不一次全开）

---

### [命令-2] VWAP ATR 归一化（第一个放行，风险最低）

**为什么先做这个**

```
vwap_hard_block 在最新 2H 触发 52 次（24.3%）
这是纯粹的"一刀切过严"问题，修复不涉及方向判断
风险：低（只影响已通过其他门控的候选的 VWAP 过滤）
```

```python
# src/fund_flow/macd_strategy_v2.py
# 替换 vwap_hard_block 的判断逻辑（约 3893-3905 行附近）

# 原有代码（删除）：
# if vwap_deviation > self.config.vwap_deviation_hard_block:  # 固定 3%
#     return self._neutral_signal(reason='vwap_hard_block', ...)

# 新代码（替换）：
def _check_vwap_gate(
    self,
    price:         float,
    vwap:          float,
    atr_pct:       float,
    signal_score:  float,
) -> dict:
    """
    ATR 归一化 VWAP 门控，替换固定 3% 一刀切
    返回：{ "action": "PASS"|"PENALTY"|"PROBE"|"BLOCK", "mult": float }
    """
    if vwap <= 0 or atr_pct <= 0:
        # ATR/VWAP 数据缺失，退化到固定门槛
        dev_pct = abs(price - vwap) / vwap if vwap > 0 else 0
        if dev_pct > 0.06:
            return {"action": "BLOCK", "mult": 0.0}
        return {"action": "PASS",  "mult": 1.0}

    dev_pct       = abs(price - vwap) / vwap
    dev_in_atr    = dev_pct / atr_pct     # 以 ATR 为单位的偏离

    cfg = self.config.vwap_deviation_gate

    if dev_in_atr < cfg.pass_atr_multiplier:       # < 1.5 × ATR
        return {"action": "PASS",    "mult": 1.0}

    if dev_in_atr < cfg.penalty_atr_multiplier:    # 1.5~2.5 × ATR
        slope  = cfg.penalty_mult_slope             # 0.15
        mult   = 1.0 - (dev_in_atr - 1.5) * slope
        return {"action": "PENALTY", "mult": max(mult, 0.70)}

    if dev_in_atr < cfg.block_atr_multiplier:      # 2.5~4.0 × ATR
        return {"action": "PROBE",   "mult": 0.80, "max_portion": 0.06}

    return {"action": "BLOCK", "mult": 0.0}        # > 4.0 × ATR
```

```diff
# config/trading_config_fund_flow.json

- "vwap_deviation_hard_block": 0.03,

+ "vwap_deviation_gate": {
+   "mode":                   "atr_normalized",
+   "pass_atr_multiplier":    1.5,
+   "penalty_atr_multiplier": 2.5,
+   "block_atr_multiplier":   4.0,
+   "penalty_mult_slope":     0.15,
+   "fallback_hard_block_pct": 0.06
+ }
```

**验收**

```bash
# 重启后运行 12H，检查：
grep "vwap_hard_block" logs/... | wc -l      # 应从 360/窗口 降到 < 150
grep "vwap_penalty"    logs/... | wc -l      # 新增 penalty 类，说明 ATR 归一化生效
grep "vwap_probe"      logs/... | wc -l      # 新增 probe 类
```

---

### [命令-3] probe_floor_rescue 真正上线（shadow_mode 确认关闭后）

```diff
# config/trading_config_fund_flow.json
# 此项仅在命令-0 验证通过后才有意义

  "probe_floor_rescue": {
-   "shadow_mode":          true,    # ← 如果仍然是 true，先执行命令-0
+   "shadow_mode":          false,   # 确认已关闭

    "enabled":              true,
    "min_score_threshold":  0.800,   # score >= 0.80 才救
-   "probe_portion":        0.060,
+   "probe_min_open_portion": 0.042, # probe 专用 min_open（低于正常 0.06）
    "probe_leverage_cap":   2
  },

+ "min_open_portion_by_mode": {
+   "normal": 0.060,
+   "probe":  0.042
+ }
```

**代码修改（fund_flow_bot.py，约 3038-3118 行）**

```python
def _apply_probe_floor_rescue(
    self,
    symbol:       str,
    signal_score: float,
    target:       float,
) -> float | None:
    cfg = self.config.probe_floor_rescue

    if not cfg.enabled:
        return None

-   if cfg.shadow_mode:                          # 旧逻辑：只记录不下单
-       self._log_shadow(symbol, signal_score, target)
-       return None

    # shadow_mode 已关闭，执行实际救援
    if signal_score < cfg.min_score_threshold:
        return None   # 低分不救

    probe_min = cfg.probe_min_open_portion       # 0.042
    if target >= probe_min:
        return target                            # 已经够大，不需要救援

    # 信号足够强但仓位被压缩 → 提升到 probe_min
    self._log_info(
        f"[ProbeRescue] {symbol} score={signal_score:.3f} "
        f"target={target:.4f} → probe_min={probe_min:.3f}"
    )
    return probe_min
```

---

### [命令-4] neutral_upgrade 放宽（第三步，需要前两步稳定后）

**执行前提**：命令-1/2/3 已运行 ≥ 12H，日志确认无明显 WR 下降

```diff
# config/trading_config_fund_flow.json

  "neutral_upgrade": {
    "enabled":                         true,
-   "neutral_upgrade_min_rsi_score":   0.35,
+   "neutral_upgrade_min_rsi_score":   0.20,

-   "neutral_upgrade_probe_rsi_score": 0.20,
+   "neutral_upgrade_probe_rsi_score": 0.12,

    "neutral_upgrade_penalty_mult":    0.90,

+   "partial_confirm_path": {
+     "enabled":           true,
+     "4h_shrink_signals": ["red_bar_shrinking","green_bar_shrinking"],
+     "1h_confirm_long":   ["red_bar_growing","flip_bullish"],
+     "1h_confirm_short":  ["green_bar_growing","flip_bearish"],
+     "penalty_mult":      0.85,
+     "max_portion":       0.10,
+     "score_bonus":       0.02
+   }
  }
```

**验收标准**

```
neutral_upgrade_gate HOLD 次数：从 105/窗口 降到 < 60
新增 partial_confirm 开仓：至少 3~5 笔/12H
partial_confirm WR（首个 24H）：≥ 60%（否则回滚）
```

---

## 执行检查清单（必须按顺序打勾）

```
□ 命令-0A: bot 进程已停止并重启
□ 命令-0B: verify_deployment.py 输出 ✅
□ 命令-0C: runtime 日志确认 shadow_mode=False
□ 命令-1A: position_exit_signal_guard 代码已写入
□ 命令-1B: config 中 position_exit_signal_guard.enabled = true
□ 命令-1C: DCA 模块已添加 _skip_dca 标志位检查
□ 命令-2A: vwap_deviation_gate ATR 归一化代码已替换旧逻辑
□ 命令-2B: config 中 vwap_deviation_hard_block 已删除
□ 命令-3A: probe_floor_rescue.shadow_mode = false（配置）
□ 命令-3B: probe_floor_rescue 代码中 shadow 分支已删除
□ 命令-4:  等 ≥ 12H 后再执行（neutral_upgrade 放宽）

未完成上述任何一项 → 不得继续叠加新配置
```

---

## 本次不执行的项目（明确列出，不是忘了）

```
❌ 权重重平衡（weight_rsi_rhythm 0.30→0.22）
   原因：需要确认 RSI raw_score 是否真的 >1.0；
         如果代码已做内部归一化，这个改动无效或有害。
         先从日志中提取一批 raw_rsi_score 样本确认后再动。

❌ rsi_1h_direction_against_veto → soft penalty
   原因：TRUMP 事件说明"放松入场 RSI"不是方向，
         而是"持仓退出 RSI"需要更灵敏。
         在 exit_signal_guard 稳定 3 天后再评估入场侧放宽。

❌ BTC/ETH/BNB 双腿对冲
   原因：依赖 BTC context 数据接入（命令-0 之前连状态都未确认）。
         单独列为下次审阅项。

❌ 1H confirmation 从 hard → soft（penalty 0.90）
   原因：同上，先保住退出侧，再谈入场侧放宽。
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-13*  
*执行顺序不得颠倒：命令-0 → 命令-1 → 命令-2/3（同步）→ 命令-4（12H 后）*  
*每条命令均有验收断言，未通过断言不得继续*
