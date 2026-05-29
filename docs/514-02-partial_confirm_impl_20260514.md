# 4H Shrink + 1H Confirm 方向识别 — 权威实现命令
**日期**: 2026-05-14  
**问题根因**: `trade_direction is None` 分支里没有处理 shrink+confirm 组合，187 个有效候选被归零  
**修复范围**: `macd_strategy_v2.py` 约 3735-3850 行，单一函数插入，不改动其他路径

---

## 为什么这个方向识别是有理有据的

```
4H green_bar_shrinking 的含义：
  4H MACD 绿柱在缩短（空头动能在减弱）
  不代表"没有方向"，代表"当前下跌趋势正在失去动力"
  是 4H 级别潜在底部的早期信号

1H red_bar_growing 的含义：
  1H MACD 红柱在增长（多头动能在增强）
  1H 级别多头已经启动

两者叠加 = 空头动能正在 4H 级别衰减，同时多头在 1H 级别确认启动
这是趋势反转早期的标准形态，不应被当成"无方向"归零

类比：
  4H green_bar_shrinking = 卖方力量减弱（熊转牛的先决条件）
  1H red_bar_growing     = 买方力量增强（确认信号）
  组合                   = 做多的早期信号，需要小仓、独立阈值、快速止损

盈利逻辑：
  这类信号的优势不是"方向非常确定"，而是"在转折点附近提前进场"
  因此：仓位必须小（probe），止损必须严格，让胜率×盈亏比而非单次大仓决定收益
```

---

## [命令-1] 立即执行：加 shadow 日志（今天，不下单）

**目的**：先收集数据，验证信号质量，再决定是否 live

```python
# src/fund_flow/macd_strategy_v2.py
# 插入位置：_evaluate_direction() 或等效函数内，
# 在 "if trade_direction is None" 分支的最开始

# ── 步骤 1：定义 partial_confirm 组合表 ─────────────────────────

PARTIAL_CONFIRM_TABLE = {
    # 做多候选：4H 空头动能收缩 + 1H 多头确认
    ("green_bar_shrinking", "red_bar_growing"):  {
        "direction":      "long",
        "confidence":     "MEDIUM",    # 中等置信度
        "reason":         "4H熊力衰减+1H多头启动",
    },
    ("green_bar_shrinking", "flip_bullish"):  {
        "direction":      "long",
        "confidence":     "HIGH",      # 更强：1H 已 flip
        "reason":         "4H熊力衰减+1H金叉确认",
    },
    ("green_bar_shrinking", "red_bar_shrinking"):  {
        "direction":      "long",
        "confidence":     "LOW",       # 弱：1H 也在收缩
        "reason":         "4H/1H双收缩，多头萌芽",
        "shadow_only":    True,        # 只记录，不开仓
    },

    # 做空候选：4H 多头动能收缩 + 1H 空头确认
    ("red_bar_shrinking", "green_bar_growing"):  {
        "direction":      "short",
        "confidence":     "MEDIUM",
        "reason":         "4H牛力衰减+1H空头启动",
    },
    ("red_bar_shrinking", "flip_bearish"):  {
        "direction":      "short",
        "confidence":     "HIGH",
        "reason":         "4H牛力衰减+1H死叉确认",
    },
    ("red_bar_shrinking", "green_bar_shrinking"):  {
        "direction":      "short",
        "confidence":     "LOW",
        "reason":         "4H/1H双收缩，空头萌芽",
        "shadow_only":    True,
    },
}


# ── 步骤 2：partial_confirm 检查函数 ─────────────────────────────

def _check_partial_confirm(
    self,
    signal_4h: str,
    signal_1h: str,
) -> dict | None:
    """
    检查是否命中 partial_confirm 组合
    返回命中结果 dict，或 None（未命中）
    """
    key = (signal_4h, signal_1h)
    result = PARTIAL_CONFIRM_TABLE.get(key)
    if result is None:
        return None

    # 复制一份，避免修改全局表
    return dict(result)


# ── 步骤 3：shadow 评分计算 ──────────────────────────────────────

def _compute_partial_confirm_shadow_score(
    self,
    pc_result:    dict,      # _check_partial_confirm 的返回值
    score_1h:     float,     # 当前 1H 方向分
    score_vwap:   float,     # VWAP 分（即使是 0 也记录）
    score_vol:    float,     # 成交量分
    score_15m:    float,     # 15m 分
    rsi_score:    float,     # RSI rhythm raw score
    vwap_dev_pct: float,     # VWAP 偏离百分比
    atr_pct:      float,     # ATR/价格
) -> dict:
    """
    计算 partial_confirm 路径下的评分和仓位
    shadow 模式：只记录，不实际开仓
    """
    confidence = pc_result["confidence"]
    direction  = pc_result["direction"]

    # ── 4H shrink 方向分（固定给小额，因为方向有但不确定）──────
    SHRINK_4H_SCORES = {
        "HIGH":   0.15,    # 相当于 flip 状态的分数
        "MEDIUM": 0.10,
        "LOW":    0.05,
    }
    score_4h_partial = SHRINK_4H_SCORES[confidence]

    # ── 组合评分（按当前权重体系计算）──────────────────────────
    # 注意：这里用实际配置权重，不是假设值
    w = self.config.scoring_weights
    raw_score = (
        score_1h            * w.weight_1h_direction   +
        score_4h_partial    * w.weight_4h_direction   +   # 小额 4H 分
        min(rsi_score, 1.0) * w.weight_rsi_rhythm     +   # RSI 归一化
        score_vwap          * w.weight_vwap            +
        score_15m           * w.weight_15m_entry       +
        score_vol           * w.weight_volume
    )

    # penalty_mult 来自 neutral_upgrade_penalty（0.85）
    penalty_mult = self.config.entry_filters.neutral_upgrade_penalty_mult
    scored = raw_score * penalty_mult

    # ── 目标仓位（强制 probe 小仓）────────────────────────────
    CONFIDENCE_MAX_PORTION = {
        "HIGH":   0.10,
        "MEDIUM": 0.06,
        "LOW":    0.042,    # probe 专用 min_open
    }
    max_portion = CONFIDENCE_MAX_PORTION[confidence]

    # ── 独立阈值（比默认 0.68 低，因为这是早期信号）──────────
    CONFIDENCE_THRESHOLD = {
        "HIGH":   0.60,    # 需要回测验证
        "MEDIUM": 0.58,
        "LOW":    0.55,    # shadow only，不实际用
    }
    threshold = CONFIDENCE_THRESHOLD[confidence]

    # ── VWAP 偏离安全检查（追高/追空风险）────────────────────
    vwap_dev_atr_ratio = abs(vwap_dev_pct) / atr_pct if atr_pct > 0 else 999
    vwap_safe = (vwap_dev_atr_ratio < 3.0)    # VWAP 偏离 < 3×ATR 才安全

    # ── 方向一致性检查：VWAP 位置应与方向一致 ────────────────
    vwap_aligned = (
        (direction == "long"  and vwap_dev_pct > -0.02) or  # 做多时不能深度低于 VWAP
        (direction == "short" and vwap_dev_pct <  0.02)     # 做空时不能深度高于 VWAP
    )

    would_pass = (
        scored >= threshold
        and vwap_safe
        and vwap_aligned
        and not pc_result.get("shadow_only", False)
    )

    return {
        "pc_direction":      direction,
        "pc_confidence":     confidence,
        "pc_score_4h":       score_4h_partial,
        "pc_scored":         round(scored, 4),
        "pc_threshold":      threshold,
        "pc_max_portion":    max_portion,
        "pc_would_pass":     would_pass,
        "pc_vwap_safe":      vwap_safe,
        "pc_vwap_aligned":   vwap_aligned,
        "pc_shadow_only":    pc_result.get("shadow_only", False),
        "pc_reason":         pc_result["reason"],
    }
```

---

## [命令-2] 插入位置（精确行号）

```python
# src/fund_flow/macd_strategy_v2.py
# 约 3735 行：if trade_direction is None: 分支的最开始

def _resolve_trade_direction(
    self,
    signal_4h:  str,
    signal_1h:  str,
    # ... 其他参数 ...
) -> tuple[str | None, str]:
    """
    返回 (trade_direction, reason)
    """

    # ── 原有主方向逻辑（不动）───────────────────────────────
    direction = self._resolve_primary_direction(signal_4h, signal_1h)
    if direction is not None:
        return direction, ""

    # ── [新增] partial_confirm 检查 ─────────────────────────
    # 必须在 neutral_upgrade 之前执行
    pc = self._check_partial_confirm(signal_4h, signal_1h)

    if pc is not None:
        # 有 partial_confirm 命中 → 记录 shadow 日志
        shadow = self._compute_partial_confirm_shadow_score(pc, ...)

        self._log_info(
            f"[PC_SHADOW] {signal_4h}+{signal_1h} "
            f"dir={shadow['pc_direction']} "
            f"conf={shadow['pc_confidence']} "
            f"score={shadow['pc_scored']:.4f}/th={shadow['pc_threshold']} "
            f"would_pass={shadow['pc_would_pass']} "
            f"max_portion={shadow['pc_max_portion']} "
            f"reason={shadow['pc_reason']}"
        )

        # shadow 模式：只记录，不开仓（直到验收通过）
        if self.config.partial_confirm.shadow_mode:
            return None, "4H无明确方向"    # 维持原有 HOLD 行为

        # live 模式：would_pass 才开仓
        if shadow["pc_would_pass"]:
            return shadow["pc_direction"], f"partial_confirm_{shadow['pc_confidence']}"

        return None, "partial_confirm_score_insufficient"

    # ── 原有 neutral_upgrade（不动）────────────────────────
    return self._evaluate_neutral_upgrade(...)
```

---

## [命令-3] 配置（精确字段）

```diff
# config/trading_config_fund_flow.json

+ "partial_confirm": {
+   "shadow_mode":    true,       # P0: 先 shadow，12H 后再开 live
+   "enabled":        true,
+
+   "thresholds": {
+     "HIGH":         0.60,
+     "MEDIUM":       0.58
+   },
+   "max_portions": {
+     "HIGH":         0.10,
+     "MEDIUM":       0.06
+   },
+   "score_4h_partial": {
+     "HIGH":         0.15,
+     "MEDIUM":       0.10
+   },
+   "penalty_mult":   0.85,
+
+   "vwap_safety": {
+     "max_dev_atr_ratio":  3.0,
+     "long_min_dev_pct":  -0.02,
+     "short_max_dev_pct":  0.02
+   },
+
+   "live_signal_map": {
+     "long":  [
+       ["green_bar_shrinking", "red_bar_growing",  "MEDIUM"],
+       ["green_bar_shrinking", "flip_bullish",      "HIGH"]
+     ],
+     "short": [
+       ["red_bar_shrinking",   "green_bar_growing", "MEDIUM"],
+       ["red_bar_shrinking",   "flip_bearish",      "HIGH"]
+     ],
+     "shadow_only": [
+       ["green_bar_shrinking", "red_bar_shrinking", "LOW"],
+       ["red_bar_shrinking",   "green_bar_shrinking","LOW"]
+     ]
+   }
+ }

# 同时修复 fingerprint 读取路径
# src/app/fund_flow_bot.py 约 367-390 行

- neutral = v2_cfg.get("neutral_upgrade", {})
- "neutral_upg_rsi": self._to_float(neutral.get("neutral_upgrade_min_rsi_score"), 0.0)

+ entry_filters = v2_cfg.get("entry_filters", {})
+ "neutral_upg_rsi": self._to_float(
+     entry_filters.get("neutral_upgrade_min_rsi_score"), 0.0
+ ),
+ "pc_shadow": v2_cfg.get("partial_confirm", {}).get("shadow_mode", "MISSING"),
+ "pc_enabled": v2_cfg.get("partial_confirm", {}).get("enabled", False),
```

---

## [命令-4] 验收标准（shadow 阶段，12H 后检查）

```bash
# 检查 shadow 日志是否出现
grep "PC_SHADOW" logs/2026-05/2026-05-14* | wc -l
# 预期：> 100（本窗口 187 个候选应大部分命中）

# 检查 would_pass 比例
grep "PC_SHADOW" logs/... | grep "would_pass=True" | wc -l
# 预期：30~80（并非所有候选都通过 VWAP/score 检查）

# 检查 confidence 分布
grep "PC_SHADOW" logs/... | grep "conf=HIGH" | wc -l
grep "PC_SHADOW" logs/... | grep "conf=MEDIUM" | wc -l

# 检查 score 分布（应在 0.55~0.65 区间）
grep "PC_SHADOW" logs/... | grep -oP "score=\d+\.\d+" | sort | uniq -c

# 12H 后决定是否 live：
# 条件 A: would_pass 数量 >= 15/12H（说明信号足够多）
# 条件 B: score 中位数 >= 0.57（说明信号质量可接受）
# 条件 C: VWAP 安全通过率 >= 70%（说明没有追高追空问题）
# 三个条件都满足 → 把 shadow_mode 改 false
```

---

## [命令-5] live 后的持续监控（不可省略）

```python
# 每 24H 计算一次 partial_confirm 路径的实际胜率

def audit_partial_confirm_daily(trades: list[dict]) -> dict:
    pc_trades = [t for t in trades if "partial_confirm" in t.get("reason_family", "")]

    if len(pc_trades) < 5:
        return {"status": "INSUFFICIENT_SAMPLE", "count": len(pc_trades)}

    wins   = [t for t in pc_trades if t["pnl"] > 0]
    losses = [t for t in pc_trades if t["pnl"] <= 0]
    wr     = len(wins) / len(pc_trades)
    avg_w  = sum(t["pnl"] for t in wins)   / max(len(wins), 1)
    avg_l  = sum(t["pnl"] for t in losses) / max(len(losses), 1)
    ev     = wr * avg_w + (1 - wr) * avg_l   # 期望值

    status = "OK"
    if wr < 0.55:
        status = "ROLLBACK_REQUIRED"    # 胜率低于 55% 立即回滚
    elif ev < 0:
        status = "ROLLBACK_REQUIRED"    # 负期望值立即回滚
    elif wr < 0.62:
        status = "WATCH"                # 观察，不扩仓

    return {
        "status":    status,
        "count":     len(pc_trades),
        "win_rate":  round(wr, 4),
        "avg_win":   round(avg_w, 4),
        "avg_loss":  round(avg_l, 4),
        "ev":        round(ev, 4),
    }

# 验收标准（live 第一个 24H）：
# WR >= 60%，EV > 0 → 维持，可考虑放大 max_portion 到 0.15
# WR 55%~60%，EV > 0 → 维持 WATCH，不扩仓
# WR < 55% 或 EV < 0 → 立即回滚（shadow_mode = true）
```

---

## 本次禁止执行的项（白名单外一律不动）

```
❌ 降低 entry_threshold（threshold_check 只占 18.5%，最低分候选 gap=0.12+，降阈值无效）
❌ 调整 VWAP ATR 倍数（本窗口 vwap_hard_block 只有 8 次，不是瓶颈）
❌ 调整 weight_rsi（shadow log 收集中，本轮不动权重）
❌ 加任何其他参数（先把 partial_confirm shadow 跑起来再说）
```

## 执行清单（今天）

```
□ 命令-1: PARTIAL_CONFIRM_TABLE 和三个函数已写入 macd_strategy_v2.py
□ 命令-2: 插入位置正确（trade_direction is None 分支最开始，neutral_upgrade 之前）
□ 命令-3A: partial_confirm 配置块已加入 config，shadow_mode=true
□ 命令-3B: fingerprint neutral_upg_rsi 读取路径已修正
□ 命令-3C: fingerprint 新增 pc_shadow / pc_enabled 字段
□ 重启 bot，等第一个 cycle 打印 CONFIG_FINGERPRINT
□ grep "PC_SHADOW" 确认 shadow 日志出现
□ 12H 后执行命令-4 验收
□ 验收通过 → shadow_mode=false → 重启
□ 24H 后执行命令-5 监控
```

---

*审阅人: Claude Sonnet 4.6 | 2026-05-14*  
*核心修复：一个函数插入，不改动其他路径，shadow 先行，验收再 live*
