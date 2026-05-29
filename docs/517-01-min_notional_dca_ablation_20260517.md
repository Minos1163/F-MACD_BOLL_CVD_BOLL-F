# 最小仓位修复 + DCA 移除 + 门控消融
**日期**: 2026-05-17  
**执行顺序**: min_notional fix → DCA 禁用 → vwap_score_filter 放宽 → probe 独立阈值  
**核心**: 0.042 BUY 被执行层拒绝是今天唯一的纯 bug，其余是参数优化

---

## [命令-1] 最小开仓改为绝对金额（今天，P0）

### 根因确认

```python
# 当前错误：min_open_portion = 0.06 = 6% 账户权益
# 账户 111U × 6% = 6.67 USDT 最小开仓
# probe target = 0.042 × 111U = 4.67 USDT < 6.67 → 被执行层拒绝

# 错误读取路径（risk_engine.py）：
fund_flow_cfg.get("probe_min_open_portion",     # 这个字段不存在于顶层
    fund_flow_cfg.get("min_open_portion", 0.08)) # 退化到 0.08！

# 正确读取路径应该是：
fund_flow_cfg["probe_floor_rescue"]["probe_min_open_portion"]  # 0.042
# 但 risk_engine 没有读这一层
```

### 修复：绝对金额替换百分比

```python
# src/fund_flow/risk_engine.py
# FundFlowRiskEngine.__init__() 修改

class FundFlowRiskEngine:
    def __init__(self, config: dict):
        fund_flow = config.get("fund_flow", config)

        # ── 删除旧的 portion 百分比最小值 ────────────────────
        # self.min_open_portion = fund_flow.get("min_open_portion", 0.06)

        # ── 新增：绝对金额最小值（按品种分类）───────────────
        notional_cfg = fund_flow.get("min_open_notional", {})
        self.min_open_notional_default = notional_cfg.get("default_usdt",    2.0)
        self.min_open_notional_btc     = notional_cfg.get("btc_usdt",        5.0)
        self.min_open_notional_major   = notional_cfg.get("major_usdt",      3.0)

        # 大市值品种列表
        self.major_symbols = set(
            notional_cfg.get("major_symbols",
                             ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"])
        )

        # 保留 portion 上限（不变）
        self.max_open_portion = fund_flow.get("max_symbol_position_portion", 0.35)

        # probe 识别：从正确路径读取
        rescue_cfg = fund_flow.get("probe_floor_rescue", {})
        self.probe_min_open_portion = rescue_cfg.get("probe_min_open_portion", 0.042)
        self.probe_min_score        = rescue_cfg.get("min_score_threshold",     0.80)


    def _get_min_notional(self, symbol: str) -> float:
        """按品种返回最小名义价值（USDT）"""
        if symbol == "BTCUSDT":
            return self.min_open_notional_btc
        if symbol in self.major_symbols:
            return self.min_open_notional_major
        return self.min_open_notional_default


    def validate_target_portion(
        self,
        symbol:         str,
        target_portion: float,
        signal_score:   float,
        account_equity: float,
        is_probe:       bool = False,
    ) -> float:
        """
        替换原有 [0.06, 1.0] 区间校验
        返回最终生效的 target_portion（可能调整，不再直接 raise）
        """
        notional = target_portion * account_equity
        min_notional = self._get_min_notional(symbol)

        # ── 上限检查（不变）────────────────────────────────
        if target_portion > self.max_open_portion:
            self._log_warning(
                f"{symbol} target={target_portion:.4f} > max={self.max_open_portion}, "
                f"capped"
            )
            target_portion = self.max_open_portion

        # ── 最小金额检查（新逻辑）──────────────────────────
        if notional >= min_notional:
            return target_portion   # 通过，金额足够

        # ── probe rescue（金额不足时）──────────────────────
        if is_probe or signal_score >= self.probe_min_score:
            probe_notional = self.probe_min_open_portion * account_equity
            if probe_notional >= min_notional:
                self._log_info(
                    f"[RISK_PROBE] {symbol} notional={notional:.2f} < {min_notional}, "
                    f"rescued to probe={self.probe_min_open_portion:.3f} "
                    f"({probe_notional:.2f}U)"
                )
                return self.probe_min_open_portion
            # probe 仍不够（账户过小）：压到能通过的最小比例
            min_portion = min_notional / account_equity
            self._log_info(
                f"[RISK_MIN] {symbol} forced to min_portion={min_portion:.4f} "
                f"({min_notional}U)"
            )
            return min_portion

        # 低分信号且金额不足：拒绝（但不再 raise，改为返回 0）
        self._log_info(
            f"[RISK_BLOCK] {symbol} notional={notional:.2f} < {min_notional}, "
            f"score={signal_score:.4f} < probe_threshold, blocked"
        )
        return 0.0   # 调用方检查 0 则跳过开仓
```

### 配置修改

```diff
# config/trading_config_fund_flow.json

- "min_open_portion": 0.060,           # 删除：不再用百分比最小值

+ "min_open_notional": {
+   "default_usdt":  2.0,              # 普通山寨：最小 2 USDT
+   "major_usdt":    3.0,              # 主流（SOL/XRP 等）：最小 3 USDT
+   "btc_usdt":      5.0,              # BTC：最小 5 USDT
+   "major_symbols": ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]
+ },

  "probe_floor_rescue": {
    "enabled":              true,
    "shadow_mode":          true,       # 维持，probe rescue 仍是 shadow
    "min_score_threshold":  0.800,
    "probe_min_open_portion": 0.042,    # risk engine 现在能正确读到这里
  }
```

### 验收

```bash
# 重启后检查 BUY 决策不再被 min_open_portion 拒绝
grep "decision 校验失败.*越界" logs/... | wc -l
# 预期：0

# 检查 ATOM/HYPE 的 0.042 probe 订单能提交
grep "RISK_PROBE\|RISK_MIN" logs/... | head -10
```

---

## [命令-2] DCA 从策略中移除（今天，P0）

### 为什么移除 DCA

```
DCA 的问题（来自历史日志）：

1. TRUMP 事件：15:15 开多，方向错误，16:00~18:30 已有 RSI against veto
   → 19:00 DCA 触发（drawdown=1.05%）→ 加仓亏损方向 → 扩大损失

2. 语义冲突：当前策略同时有：
   - ExitGuard（发现反向信号 → 平仓）
   - DCA（亏损 → 加仓）
   两者在方向判断上是相反操作，在同一根 K 线上竞争

3. 信号质量：DCA 的触发条件是"亏损超过 drawdown 阈值"
   与"新信号是否仍然有效"完全解耦
   → 在方向错误时强制加仓，放大损失
```

### 禁用方法（配置层，不删代码）

```diff
# config/trading_config_fund_flow.json

  "dca": {
-   "enabled": true,
+   "enabled": false,    # 禁用 DCA，ExitGuard 主导持仓管理
+   "comment": "DCA 与 ExitGuard 语义冲突，统一由 ExitGuard 处理方向反转"
  }
```

```python
# src/app/fund_flow_bot.py — _maybe_trigger_dca() 最开始

def _maybe_trigger_dca(self, symbol: str, position: dict) -> bool:
+   if not self.config.dca.enabled:
+       return False    # DCA 已禁用，直接返回

    # 原有 DCA 逻辑（保留代码，只是不执行）...
```

### 验收

```bash
grep "DCA.*触发\|DCA未触发" logs/... | wc -l
# 预期：0（DCA 禁用后不再出现此日志）
```

---

## [命令-3] vwap_score_filter 放宽（明天，P1）

### 当前问题

```python
# 典型被拒绝案例：
# VWAPq=0.0525 → vwap_score_filter(0.0525 < 0.0600) → HOLD
# VWAPq=0.0599 → vwap_score_filter(0.0599 < 0.0600) → HOLD

# 这个 0.0600 门槛的含义是：
# VWAP 位置评分低于 6% 时不允许开仓
# 但对于 RSI soft probe 路径（已经是趋势回调），
# VWAP 低分正好对应"价格在 VWAP 附近但动能弱"
# 这不是排除信号的理由，而是应该压缩仓位的理由
```

### 修复：vwap_score_filter 改为仓位调节器

```python
# src/fund_flow/macd_strategy_v2.py
# 替换 vwap_score_filter 的 hard block 逻辑

def _apply_vwap_score_filter(
    self,
    vwap_score:    float,
    signal_type:   str,    # "probe" | "normal"
    current_score: float,
) -> dict:
    """
    不再是 hard block，而是仓位调节器
    """
    cfg = self.config.vwap_score_filter

    # probe 路径豁免：score 低但方向已通过 RSI soft
    if signal_type == "probe":
        if vwap_score >= cfg.probe_min:          # 0.03（新参数）
            return {"action": "PASS", "portion_mult": 0.80}
        if vwap_score >= 0.01:
            return {"action": "PASS", "portion_mult": 0.60}
        return {"action": "BLOCK", "reason": "vwap_score_too_low_for_probe"}

    # 正常路径
    if vwap_score >= cfg.normal_min:             # 0.04（从 0.06 降低）
        return {"action": "PASS", "portion_mult": 1.0}
    if vwap_score >= 0.02:
        return {"action": "PASS", "portion_mult": 0.70}

    return {"action": "BLOCK", "reason": "vwap_score_insufficient"}
```

```diff
# config/trading_config_fund_flow.json

  "vwap_score_filter": {
-   "min_vwap_score": 0.0600,

+   "normal_min":     0.0400,    # 从 0.06 降到 0.04
+   "probe_min":      0.0300,    # probe 路径更低门槛
+   "below_probe_min_mult": 0.60 # 极低 VWAP 分时压缩仓位而非阻断
  }
```

---

## [命令-4] probe 独立阈值（明天，P1）

### 问题

```
RSI soft after → 总分 0.42~0.47
主阈值 0.69（green_bar_growing）
gap = 0.22~0.27，差距太大

原因：RSI soft probe 路径下：
  4H score = 0.4（正常）
  1H score = 0.0（RSI soft penalty 清零了 1H 方向分）
  15M score ≈ 0
  VOL     = 0.033
  VWAP    = 低
  总分 ≈ 0.40 + 0.033 + VWAP ≈ 0.43~0.47

要让这类信号开仓，要么恢复 1H 分，要么给独立更低阈值
```

### 修复：probe 路径独立阈值

```python
# src/fund_flow/macd_strategy_v2.py
# threshold_check 阶段

def _resolve_entry_threshold(
    self,
    signal_type:   str,
    entry_type_15m: str,
    is_probe:      bool,
    is_rsi_soft:   bool,
) -> float:
    """
    按信号路径返回不同阈值
    """
    base = self.config.entry_thresholds.get(signal_type, 0.68)

    # RSI soft probe 路径：独立更低阈值
    if is_rsi_soft and is_probe:
        probe_th = self.config.entry_thresholds.get(
            "rsi_soft_probe", 0.55
        )
        return min(base, probe_th)   # 取更低值

    # 正常 probe（非 RSI soft）
    if is_probe:
        probe_th = self.config.entry_thresholds.get("probe", 0.60)
        return min(base, probe_th)

    return base
```

```diff
# config/trading_config_fund_flow.json

  "entry_thresholds": {
    "default":          0.680,
    "red_bar_growing":  0.680,
    "green_bar_growing":0.690,
    "flip_bearish":     0.660,
    "flip_bullish":     0.640,

+   "probe":            0.600,    # 一般 probe 路径
+   "rsi_soft_probe":   0.550,    # RSI soft + probe 组合路径
+   "comment": "probe 阈值只在 is_probe=True 时生效，不影响正常路径"
  }
```

### 同时修复 1H 评分在 soft probe 中的零值问题

```python
# RSI soft penalty 当前把 1H 分清零了
# 但 4H green_bar_growing 已经给了 0.4 的方向分
# 1H green_bar_shrinking 作为"趋势中的回调"，应给小额正分，不是 0

def _score_1h_direction_with_soft_probe(
    self,
    signal_1h:   str,
    signal_4h:   str,
    direction:   str,
    rsi_soft:    bool,
) -> float:
    """
    soft probe 路径下，1H score 不为 0
    """
    if not rsi_soft:
        return self._score_1h_direction_normal(signal_1h, direction)

    # soft probe：1H 给部分分（不是满分，但不是 0）
    SOFT_PROBE_1H_SCORES = {
        ("green_bar_shrinking", "short"): 0.08,  # 空头回调，给小额正分
        ("red_bar_shrinking",   "long"):  0.08,  # 多头回调
        ("green_bar_growing",   "short"): 0.15,  # 同向确认
        ("red_bar_growing",     "long"):  0.15,
    }
    key = (signal_1h, direction)
    return SOFT_PROBE_1H_SCORES.get(key, 0.05)
```

---

## [命令-5] 更新 pre_live_assertions

```python
# scripts/pre_live_assertions.py

def assert_min_notional(cfg: dict) -> list[str]:
    errors = []
    notional = cfg.get("min_open_notional", {})

    if "default_usdt" not in notional:
        errors.append("min_open_notional.default_usdt missing")
    if notional.get("default_usdt", 0) > 3.0:
        errors.append(
            f"min_open_notional.default_usdt={notional['default_usdt']} > 3.0, "
            "too restrictive for small accounts"
        )
    if "min_open_portion" in cfg:
        errors.append(
            "min_open_portion still present, must be deleted "
            "(replaced by min_open_notional)"
        )
    return errors


def assert_dca_disabled(cfg: dict) -> list[str]:
    dca = cfg.get("dca", {})
    if dca.get("enabled", True):
        return ["dca.enabled must be false (conflicts with ExitGuard)"]
    return []


def assert_probe_threshold_lower(cfg: dict) -> list[str]:
    errors = []
    th = cfg.get("entry_thresholds", {})
    if th.get("rsi_soft_probe", 1.0) > 0.60:
        errors.append(
            f"entry_thresholds.rsi_soft_probe={th.get('rsi_soft_probe')} > 0.60"
        )
    if th.get("probe", 1.0) > 0.65:
        errors.append(
            f"entry_thresholds.probe={th.get('probe')} > 0.65"
        )
    return errors
```

---

## 执行清单

```
今天（P0，必须）：
□ risk_engine.py: validate_target_portion() 改为绝对金额校验
□ risk_engine.py: probe 读取路径修复（从 probe_floor_rescue 读 0.042）
□ config: min_open_notional 添加，min_open_portion 删除
□ config: dca.enabled = false
□ pre_live_assertions: 加 assert_min_notional + assert_dca_disabled
□ 重启，verify_deployment.py ✅，pre_live_assertions.py ✅
□ 检查 ATOM/HYPE 0.042 probe BUY 不再被 error 拒绝

明天（P1，验收后）：
□ vwap_score_filter: 改为仓位调节器，normal_min 降到 0.04
□ entry_thresholds: 加 probe=0.60 / rsi_soft_probe=0.55
□ 1H soft probe 评分：不归零，给 0.05~0.15 小额分
□ 重启验收

不动（等明天验收后评估）：
❌ probe_floor_rescue shadow_mode（等 combo_block + RSI 修复双验收）
❌ partial_confirm live
❌ neutral upgrade shrink 路径放宽
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-17*  
*今天只改两件事：min_notional 修 bug + DCA 禁用。其余明天。*
