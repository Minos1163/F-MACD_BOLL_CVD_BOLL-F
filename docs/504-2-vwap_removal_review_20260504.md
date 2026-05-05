# VWAP 移除 / MACD+EMA+RSI 替换门控 · 审查报告

- 日期: `2026-05-04`
- 版本: `candidate_c_macd_ema_rsi_gate`
- 状态: **审查建议 — 未经ablation不得部署**

---

## 目录

1. [诊断结论](#1-诊断结论)
2. [13个问题的答案](#2-13个问题的答案)
3. [替换门控伪代码](#3-替换门控伪代码)
4. [配置DIFF](#4-配置diff)
5. [ablation执行计划](#5-ablation执行计划)
6. [部署检查清单](#6-部署检查清单)

---

## 1. 诊断结论

### 1.1 当前失效模式

```
vwap_score_filter  = 35,454  ← 主杀手
vwap_hard_block    =  3,591  ← 次杀手
total_trades       =      0  ← 策略完全饥饿

结论: VWAP 不是"方向质量过滤器"
     它是"价格位置过滤器", 被错误地用作趋势入场门
     MACD趋势延续信号本质上就会"偏离VWAP"
     所以 VWAP 在趋势策略里天然地是反向选择器
```

### 1.2 权重与门控不一致

```
weight_vwap = 0.05   ← 分数贡献只有5%
但门控 min_vwap_score_for_entry = 0.12/0.25 是硬否决
实际上VWAP作为入场否决权远强于它的分数权重
这是架构设计缺陷, 不是参数调优问题
```

### 1.3 建议方向

```
不要: 仅降低 min_vwap_score_for_entry 到 0.10 或 0.08
      (所有floor联合否决, 不解决根本问题)

要:   完整执行三阶段ablation
      candidate_a → candidate_b → candidate_c
      以 candidate_c (MACD+EMA+RSI谐振门) 为目标部署候选
      VWAP降级为纯遥测字段, 不再参与入场决策
```

---

## 2. 13个问题的答案

### Q1: VWAP与MACD趋势策略是否根本不兼容?

**结论: 不是根本不兼容, 但当前用法是架构错误**

```
可保留的用途:
  - VWAP距离作为仓位规模警告 (非否决)
  - VWAP偏离度作为遥测字段供事后分析
  - structural_vwap 偏离超过 5% 时降低仓位到 0.6x

不应继续的用途:
  - 硬入场门 (min_vwap_score_for_entry)
  - 硬偏离否决 (vwap_deviation_hard_block = 0.03)
  - flip_bearish 特殊门控 (0.25的floor)
```

### Q2: VWAP是否应只移除入场门同时保留遥测?

**是的, 这是正确做法**

```
保留:
  calculate_vwap_score() 函数 → 输出到 trade_log 的 vwap_score 字段
  vwap_alert_deviation = 0.005 → 仅触发日志告警, 不阻断入场
  structural_vwap 偏离 > 0.05 → 触发仓位缩减警告标志

移除/归零:
  所有 min_vwap_score_for_entry 类参数 → 设为 0.0
  vwap_deviation_hard_block → 设为 999.0 (等效禁用)
  weight_vwap → 设为 0.0 (见Q3)
```

### Q3: weight_vwap=0后, 0.05的权重如何分配?

**建议: 选项C — 移至 weight_rsi_rhythm**

```
分析:
  选项A (不分配):
    - 总分上限从1.0降为0.95, 入场阈值0.680不变
    - 边际信号可能因分数不足而被拒绝
    - 不推荐: 造成隐式阈值提高

  选项B (移至 weight_4h_direction = 0.45):
    - 4H已是最大权重0.40, 再提高会使1H/RSI边际化
    - 风险: 弱1H信号搭便车进入

  选项C (移至 weight_rsi_rhythm = 0.35):  ← 推荐
    - RSI rhythm是方向质量的独立验证者
    - 与MACD的时序相关性较低, 提高它是真正的多样化
    - RSI rhythm score已经是精细计算值, 值得更高权重

  选项D (移至 weight_volume = 0.15):
    - volume是条件性质量信号, 不是方向信号
    - 高volume本身不证明方向正确
    - 不推荐作为主要重分配目标

结论: weight_rsi_rhythm 从 0.30 → 0.35
      同时将 weight_volume 从 0.10 → 0.10 (保持不变)
      总权重保持 1.0
```

### Q4: MACD+EMA+RSI谐振能否单独维持胜率和利润因子?

**条件成立, 但需要加固以下三点:**

```
当前策略已有的保护:
  ✓ primary_direction_timeframe = "4h"
  ✓ require_1h_confirmation_when_4h_primary = true
  ✓ flip_bearish_min_adx_1h = 30.0
  ✓ flip_bearish_require_enhancement_or_15m_confirmation = true

当前策略缺少的保护 (移除VWAP后需补充):
  ✗ 4H MACD方向与1H信号的显式谐振硬门
  ✗ EMA结构对 flip_bearish 的否决 (against时应拒绝)
  ✗ RSI rhythm在rebound冲突时对空单的否决
  ✗ 独立的低质量入场集群拦截器
```

### Q5: 如果不足, 哪个应该先加强?

**优先级: RSI rhythm > EMA structure > MACD 15m 时序**

```
理由:
  1. RSI rhythm 已有精细的分数体系但没有硬门
     在VWAP移除后, RSI rhythm score < 0.40 的空单应被拒绝
     RSI rebound冲突下的 flip_bearish 是已知损失集群

  2. EMA structure = "against" 当前已有系数惩罚
     但没有硬否决 flip_bearish 的逻辑
     当EMA结构对做空不利时, flip_bearish 损失率极高

  3. 15m 入场时序是现有的最后一道门, 已有增强路径
     不需要大改, 只需确认 flip_bearish 必须有15m确认
```

### Q6: 没有VWAP如何保护flip_bearish?

**7层非VWAP保护栈:**

```
层1 (已有): ADX 1H >= 30
层2 (已有): 4H MACD是 short 或 stable_bear_continuation
层3 (已有): 15m bearish确认 或 4H enhancement
层4 (新增): EMA结构不为 "against" (硬否决)
层5 (新增): RSI rhythm score >= 0.35 for short (硬门)
层6 (新增): RSI不在 rebound_conflict 状态 (硬否决)
层7 (保留): funding_rate > 0.0005 AND OI delta < 0
            (flip_bearish_independent_enabled = true的检查)
```

### Q7: vol_vwap_warn_position_scale 如何处理?

**重命名为 vol_warn_position_scale, 移除VWAP依赖**

```
当前行为:
  vol_vwap_warn_position_scale = 0.0
  → 当低volume + 低VWAP score时, 仓位归零

建议:
  将逻辑改为: 低volume时仓位缩减到 0.5x
  而不是归零 (归零等于不入场, 属于过度控制)

  新参数: vol_warn_position_scale = 0.5
  触发条件: volume_ratio < 0.8 (低于日均80%)
  这样保留了volume质量信号, 但不依赖VWAP
```

### Q8: RANGE/NO_TRADE长门是否继续引用VWAP?

**完全切换到 MACD/EMA/RSI/ADX/score**

```
当前 RANGE 状态下的 VWAP 引用应替换为:
  - ADX < 20 → 确认 RANGE 状态 (非趋势)
  - 1H signal 为 green_bar_shrinking/red_bar_shrinking 且无4H方向 → RANGE
  - signal_score < 0.60 → NO_TRADE
  - EMA结构 = weak 且4H无方向性 → RANGE

不应继续使用:
  - VWAP proximity判断RANGE
  - VWAP score < threshold作为RANGE的判断依据
```

### Q9: 部署前最小ablation集合是什么?

**强制3次ablation + 1次shadow:**

```
ablation_a: 移除所有VWAP门, weight_vwap保持0.05
ablation_b: ablation_a + weight_vwap=0, 权重移到RSI rhythm
ablation_c: ablation_b + 新增MACD/EMA/RSI谐振硬门
shadow_48h: ablation_c配置, 不执行真实订单, 记录would-be trades

判断规则:
  若ablation_b胜率/PF崩溃 → VWAP在隐藏方向质量问题, 需加固C层再测
  若ablation_c恢复 → 以C配置为准部署
  若全部失败 → 保持VWAP为遥测, 先做MACD/EMA/RSI的独立质量工程
```

### Q10: 必须监控的指标?

**必须全部满足:**

```
30d回测指标:
  total_trades      >= 50
  win_rate          >= 75.0%
  profit_factor     >= 1.30
  max_drawdown      <= 15.0%
  avg_loss          <= 0.8 * avg_win (利润因子>1.3的隐含条件)

60d验证:
  MDD不超过30d结果的 1.5x
  无单一symbol损失超过总亏损的 40%

近期损失集群回放 (34h窗口):
  weak flip_bearish 仍被非VWAP过滤器拦截
  低volume red_bar_growing long 被volume缩减或拒绝

Shadow指标 (48h):
  would-be_trades   >= 10
  would-be_win_rate >= 70% (shadow期允许放宽5%)
```

---

## 3. 替换门控伪代码

> 以下伪代码对应 `candidate_c_macd_ema_rsi_gate` 配置
> 函数签名与现有代码风格对齐

```python
# ============================================================
# FILE: src/fund_flow/macd_strategy_v2.py
# SECTION: MACD+EMA+RSI Resonance Gate (replaces VWAP gate)
# VERSION: candidate_c
# ============================================================


# ------------------------------------------------------------
# CONSTANTS — 所有新增硬门阈值, 集中定义便于ablation调参
# ------------------------------------------------------------

class ResonanceGateConfig:
    """
    MACD+EMA+RSI谐振门控配置
    VWAP移除后替代所有 min_vwap_score_for_entry 类参数
    """

    # Long 方向谐振门
    LONG_4H_DIRECTION_REQUIRED      = ["long", "stable_bull_continuation"]
    LONG_1H_SIGNAL_ALLOWED          = [
        "red_bar_growing",
        "flip_bullish",
        "green_bar_shrinking",   # 需要额外确认
        "red_bar_shrinking",     # 需要额外确认 + RSI支持
    ]
    LONG_EMA_STATUS_BLOCKED         = ["against"]       # 硬否决
    LONG_RSI_RHYTHM_MIN             = 0.35              # RSI rhythm score 最低门
    LONG_RSI_HARD_VETO_STATES       = ["late_overheat"] # RSI状态硬否决
    LONG_VOLUME_WARN_RATIO          = 0.80              # 低于此值触发仓位缩减
    LONG_VOLUME_WARN_SCALE          = 0.50              # 低volume时仓位缩减倍数

    # Short 方向谐振门
    SHORT_4H_DIRECTION_REQUIRED     = ["short", "stable_bear_continuation"]
    SHORT_1H_SIGNAL_ALLOWED         = [
        "green_bar_growing",
        "flip_bearish",
        "red_bar_shrinking",     # 需要额外确认
        "green_bar_shrinking",   # 需要额外确认
    ]
    SHORT_EMA_STATUS_BLOCKED        = ["against"]       # 硬否决
    SHORT_RSI_RHYTHM_MIN            = 0.35              # RSI rhythm score for short
    SHORT_RSI_HARD_VETO_STATES      = ["rebound_conflict", "spring_conflict"]
    SHORT_VOLUME_WARN_RATIO         = 0.80
    SHORT_VOLUME_WARN_SCALE         = 0.50

    # flip_bearish 专用附加门 (7层保护栈)
    FLIP_BEARISH_ADX_MIN            = 30.0
    FLIP_BEARISH_RSI_RHYTHM_MIN     = 0.40              # 比普通空单更严
    FLIP_BEARISH_REQUIRE_EMA_OK     = True              # EMA不能是against
    FLIP_BEARISH_REQUIRE_4H_ALIGN   = True              # 4H必须是short或stable_bear
    FLIP_BEARISH_REQUIRE_15M_OR_ENH = True              # 15m确认 或 4H enhancement
    FLIP_BEARISH_FUNDING_MIN        = 0.0005
    FLIP_BEARISH_OI_DELTA_MAX       = 0.0               # OI delta必须为负

    # flip_bullish 专用附加门
    FLIP_BULLISH_RSI_RHYTHM_MIN     = 0.30
    FLIP_BULLISH_REQUIRE_4H_ALIGN   = True
    FLIP_BULLISH_EMA_STATUS_BLOCKED = ["against"]

    # Trial entry 门 (preflip)
    TRIAL_LONG_RSI_RHYTHM_MIN       = 0.30
    TRIAL_SHORT_RSI_RHYTHM_MIN      = 0.30
    TRIAL_EMA_STATUS_BLOCKED        = ["against"]

    # 遥测保留 (不阻断入场)
    VWAP_TELEMETRY_WARN_DEVIATION   = 0.005  # 仅记录告警
    VWAP_POSITION_SCALE_THRESHOLD   = 0.05   # structural偏离>5%时仓位 0.7x


# ------------------------------------------------------------
# MAIN GATE FUNCTION
# 替换原 _check_vwap_gate() 函数
# ------------------------------------------------------------

def check_resonance_gate(
    signal_type: str,
    trade_direction: str,
    is_trial: bool,
    macd_4h_direction: str,
    macd_1h_signal: str,
    macd_1h_confirmation: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    adx_1h: float,
    volume_ratio: float,
    has_15m_confirmation: bool,
    has_4h_enhancement: bool,
    funding_rate: float,
    oi_delta_ratio: float,
    vwap_score: float,              # 保留入参, 仅用于遥测
    structural_vwap_deviation: float,  # 保留入参, 仅用于遥测
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    MACD+EMA+RSI谐振门控
    返回: GateResult(passed=bool, reason=str, position_scale=float)

    注意:
      - 此函数不引用任何 VWAP 阈值作为入场条件
      - vwap_score 和 structural_vwap_deviation 仅记录到遥测日志
      - 所有否决返回明确的 reason 字符串便于attribution统计
    """

    # ---- 遥测记录 (非阻断) ----
    telemetry = {
        "vwap_score": vwap_score,
        "structural_vwap_deviation": structural_vwap_deviation,
        "vwap_warn": abs(structural_vwap_deviation) > cfg.VWAP_TELEMETRY_WARN_DEVIATION,
    }
    log_telemetry("vwap_telemetry", telemetry)

    # ---- 初始化仓位缩减系数 ----
    position_scale = 1.0

    # structural VWAP 过度偏离 → 仓位缩减 (非否决)
    if abs(structural_vwap_deviation) > cfg.VWAP_POSITION_SCALE_THRESHOLD:
        position_scale *= 0.70
        log_info(f"structural_vwap_deviation={structural_vwap_deviation:.3f} > "
                 f"{cfg.VWAP_POSITION_SCALE_THRESHOLD}, position_scale reduced to "
                 f"{position_scale:.2f}")

    # ---- 分支: Trial Entry ----
    if is_trial:
        return _check_trial_resonance_gate(
            trade_direction=trade_direction,
            macd_4h_direction=macd_4h_direction,
            ema_structure_status=ema_structure_status,
            rsi_rhythm_score=rsi_rhythm_score,
            rsi_state=rsi_state,
            volume_ratio=volume_ratio,
            position_scale=position_scale,
            cfg=cfg,
        )

    # ---- 分支: flip_bearish ----
    if signal_type == "flip_bearish" and trade_direction == "short":
        return _check_flip_bearish_gate(
            macd_4h_direction=macd_4h_direction,
            ema_structure_status=ema_structure_status,
            rsi_rhythm_score=rsi_rhythm_score,
            rsi_state=rsi_state,
            adx_1h=adx_1h,
            volume_ratio=volume_ratio,
            has_15m_confirmation=has_15m_confirmation,
            has_4h_enhancement=has_4h_enhancement,
            funding_rate=funding_rate,
            oi_delta_ratio=oi_delta_ratio,
            position_scale=position_scale,
            cfg=cfg,
        )

    # ---- 分支: flip_bullish ----
    if signal_type == "flip_bullish" and trade_direction == "long":
        return _check_flip_bullish_gate(
            macd_4h_direction=macd_4h_direction,
            ema_structure_status=ema_structure_status,
            rsi_rhythm_score=rsi_rhythm_score,
            rsi_state=rsi_state,
            volume_ratio=volume_ratio,
            position_scale=position_scale,
            cfg=cfg,
        )

    # ---- 标准 Long 入场门 ----
    if trade_direction == "long":
        return _check_standard_long_gate(
            macd_4h_direction=macd_4h_direction,
            macd_1h_signal=macd_1h_signal,
            ema_structure_status=ema_structure_status,
            rsi_rhythm_score=rsi_rhythm_score,
            rsi_state=rsi_state,
            volume_ratio=volume_ratio,
            position_scale=position_scale,
            cfg=cfg,
        )

    # ---- 标准 Short 入场门 ----
    if trade_direction == "short":
        return _check_standard_short_gate(
            macd_4h_direction=macd_4h_direction,
            macd_1h_signal=macd_1h_signal,
            ema_structure_status=ema_structure_status,
            rsi_rhythm_score=rsi_rhythm_score,
            rsi_state=rsi_state,
            volume_ratio=volume_ratio,
            position_scale=position_scale,
            cfg=cfg,
        )

    # 未知组合 → 保守拒绝
    return GateResult(
        passed=False,
        reason=f"resonance_gate_unknown_combination("
               f"signal={signal_type},dir={trade_direction})",
        position_scale=0.0,
    )


# ------------------------------------------------------------
# 标准 Long 入场门
# ------------------------------------------------------------

def _check_standard_long_gate(
    macd_4h_direction: str,
    macd_1h_signal: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    volume_ratio: float,
    position_scale: float,
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    标准做多入场门
    所有条件串联 (AND), 任一失败即拒绝
    """

    # 层1: 4H MACD方向必须支持做多
    if macd_4h_direction not in cfg.LONG_4H_DIRECTION_REQUIRED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_long_4h_direction_fail("
                   f"got={macd_4h_direction},"
                   f"required={cfg.LONG_4H_DIRECTION_REQUIRED})",
            position_scale=0.0,
        )

    # 层2: 1H信号类型必须在允许列表内
    if macd_1h_signal not in cfg.LONG_1H_SIGNAL_ALLOWED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_long_1h_signal_fail("
                   f"got={macd_1h_signal},"
                   f"allowed={cfg.LONG_1H_SIGNAL_ALLOWED})",
            position_scale=0.0,
        )

    # 层3: EMA结构不能为against
    if ema_structure_status in cfg.LONG_EMA_STATUS_BLOCKED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_long_ema_against("
                   f"ema_status={ema_structure_status})",
            position_scale=0.0,
        )

    # 层4: RSI rhythm score 必须达到最低门
    if rsi_rhythm_score < cfg.LONG_RSI_RHYTHM_MIN:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_long_rsi_rhythm_fail("
                   f"score={rsi_rhythm_score:.3f},"
                   f"min={cfg.LONG_RSI_RHYTHM_MIN})",
            position_scale=0.0,
        )

    # 层5: RSI状态硬否决
    if rsi_state in cfg.LONG_RSI_HARD_VETO_STATES:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_long_rsi_state_veto("
                   f"state={rsi_state})",
            position_scale=0.0,
        )

    # 层6: volume告警 → 仓位缩减 (非否决)
    if volume_ratio < cfg.LONG_VOLUME_WARN_RATIO:
        position_scale *= cfg.LONG_VOLUME_WARN_SCALE
        log_info(f"long_volume_warn: volume_ratio={volume_ratio:.2f} < "
                 f"{cfg.LONG_VOLUME_WARN_RATIO}, position_scale → {position_scale:.2f}")

    # 所有层通过
    return GateResult(
        passed=True,
        reason="resonance_gate_long_pass",
        position_scale=position_scale,
    )


# ------------------------------------------------------------
# 标准 Short 入场门
# ------------------------------------------------------------

def _check_standard_short_gate(
    macd_4h_direction: str,
    macd_1h_signal: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    volume_ratio: float,
    position_scale: float,
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    标准做空入场门
    """

    # 层1: 4H MACD方向必须支持做空
    if macd_4h_direction not in cfg.SHORT_4H_DIRECTION_REQUIRED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_short_4h_direction_fail("
                   f"got={macd_4h_direction},"
                   f"required={cfg.SHORT_4H_DIRECTION_REQUIRED})",
            position_scale=0.0,
        )

    # 层2: 1H信号类型必须在允许列表内
    if macd_1h_signal not in cfg.SHORT_1H_SIGNAL_ALLOWED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_short_1h_signal_fail("
                   f"got={macd_1h_signal},"
                   f"allowed={cfg.SHORT_1H_SIGNAL_ALLOWED})",
            position_scale=0.0,
        )

    # 层3: EMA结构不能为against (做空方向)
    if ema_structure_status in cfg.SHORT_EMA_STATUS_BLOCKED:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_short_ema_against("
                   f"ema_status={ema_structure_status})",
            position_scale=0.0,
        )

    # 层4: RSI rhythm score for short
    if rsi_rhythm_score < cfg.SHORT_RSI_RHYTHM_MIN:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_short_rsi_rhythm_fail("
                   f"score={rsi_rhythm_score:.3f},"
                   f"min={cfg.SHORT_RSI_RHYTHM_MIN})",
            position_scale=0.0,
        )

    # 层5: RSI rebound/spring 冲突 → 空单否决
    if rsi_state in cfg.SHORT_RSI_HARD_VETO_STATES:
        return GateResult(
            passed=False,
            reason=f"resonance_gate_short_rsi_state_veto("
                   f"state={rsi_state})",
            position_scale=0.0,
        )

    # 层6: volume告警 → 仓位缩减
    if volume_ratio < cfg.SHORT_VOLUME_WARN_RATIO:
        position_scale *= cfg.SHORT_VOLUME_WARN_SCALE
        log_info(f"short_volume_warn: volume_ratio={volume_ratio:.2f}, "
                 f"position_scale → {position_scale:.2f}")

    return GateResult(
        passed=True,
        reason="resonance_gate_short_pass",
        position_scale=position_scale,
    )


# ------------------------------------------------------------
# flip_bearish 专用7层保护门
# ------------------------------------------------------------

def _check_flip_bearish_gate(
    macd_4h_direction: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    adx_1h: float,
    volume_ratio: float,
    has_15m_confirmation: bool,
    has_4h_enhancement: bool,
    funding_rate: float,
    oi_delta_ratio: float,
    position_scale: float,
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    flip_bearish 7层保护栈
    每一层对应原文档第6节中一个非VWAP保护

    层1 (已有): ADX >= 30
    层2 (已有): 4H MACD方向兼容
    层3 (已有): 15m确认 或 4H enhancement
    层4 (新增): EMA不为against
    层5 (新增): RSI rhythm score >= 0.40
    层6 (新增): RSI不在rebound_conflict
    层7 (保留): funding rate + OI delta
    """

    # 层1: ADX >= 30 (已有逻辑, 此处显式化)
    if adx_1h < cfg.FLIP_BEARISH_ADX_MIN:
        return GateResult(
            passed=False,
            reason=f"flip_bearish_gate_adx_fail("
                   f"adx={adx_1h:.1f},"
                   f"min={cfg.FLIP_BEARISH_ADX_MIN})",
            position_scale=0.0,
        )

    # 层2: 4H必须兼容空方向
    if cfg.FLIP_BEARISH_REQUIRE_4H_ALIGN:
        if macd_4h_direction not in cfg.SHORT_4H_DIRECTION_REQUIRED:
            return GateResult(
                passed=False,
                reason=f"flip_bearish_gate_4h_direction_fail("
                       f"got={macd_4h_direction})",
                position_scale=0.0,
            )

    # 层3: 15m确认 或 4H enhancement (已有, 显式化)
    if cfg.FLIP_BEARISH_REQUIRE_15M_OR_ENH:
        if not has_15m_confirmation and not has_4h_enhancement:
            return GateResult(
                passed=False,
                reason="flip_bearish_gate_no_15m_or_enhancement",
                position_scale=0.0,
            )

    # 层4 (新增): EMA结构不能为against
    if cfg.FLIP_BEARISH_REQUIRE_EMA_OK:
        if ema_structure_status in cfg.SHORT_EMA_STATUS_BLOCKED:
            return GateResult(
                passed=False,
                reason=f"flip_bearish_gate_ema_against("
                       f"ema_status={ema_structure_status})",
                position_scale=0.0,
            )

    # 层5 (新增): RSI rhythm score — flip_bearish 门比普通空单更严
    if rsi_rhythm_score < cfg.FLIP_BEARISH_RSI_RHYTHM_MIN:
        return GateResult(
            passed=False,
            reason=f"flip_bearish_gate_rsi_rhythm_fail("
                   f"score={rsi_rhythm_score:.3f},"
                   f"min={cfg.FLIP_BEARISH_RSI_RHYTHM_MIN})",
            position_scale=0.0,
        )

    # 层6 (新增): RSI状态不能为rebound/spring冲突
    if rsi_state in cfg.SHORT_RSI_HARD_VETO_STATES:
        return GateResult(
            passed=False,
            reason=f"flip_bearish_gate_rsi_state_veto("
                   f"state={rsi_state})",
            position_scale=0.0,
        )

    # 层7 (保留): funding rate + OI delta
    if funding_rate < cfg.FLIP_BEARISH_FUNDING_MIN:
        return GateResult(
            passed=False,
            reason=f"flip_bearish_gate_funding_fail("
                   f"rate={funding_rate:.6f},"
                   f"min={cfg.FLIP_BEARISH_FUNDING_MIN})",
            position_scale=0.0,
        )

    if oi_delta_ratio > cfg.FLIP_BEARISH_OI_DELTA_MAX:
        return GateResult(
            passed=False,
            reason=f"flip_bearish_gate_oi_delta_fail("
                   f"oi_delta={oi_delta_ratio:.4f},"
                   f"max={cfg.FLIP_BEARISH_OI_DELTA_MAX})",
            position_scale=0.0,
        )

    # volume告警 → 缩减 (不否决)
    if volume_ratio < cfg.SHORT_VOLUME_WARN_RATIO:
        position_scale *= cfg.SHORT_VOLUME_WARN_SCALE

    return GateResult(
        passed=True,
        reason="flip_bearish_gate_pass",
        position_scale=position_scale,
    )


# ------------------------------------------------------------
# flip_bullish 专用门
# ------------------------------------------------------------

def _check_flip_bullish_gate(
    macd_4h_direction: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    volume_ratio: float,
    position_scale: float,
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    flip_bullish 入场门 (比flip_bearish宽松, 因为做多风险结构更有利)
    """

    # 4H方向兼容
    if cfg.FLIP_BULLISH_REQUIRE_4H_ALIGN:
        if macd_4h_direction not in cfg.LONG_4H_DIRECTION_REQUIRED:
            return GateResult(
                passed=False,
                reason=f"flip_bullish_gate_4h_direction_fail("
                       f"got={macd_4h_direction})",
                position_scale=0.0,
            )

    # EMA不为against
    if ema_structure_status in cfg.FLIP_BULLISH_EMA_STATUS_BLOCKED:
        return GateResult(
            passed=False,
            reason=f"flip_bullish_gate_ema_against("
                   f"ema_status={ema_structure_status})",
            position_scale=0.0,
        )

    # RSI rhythm (比做多标准稍宽)
    if rsi_rhythm_score < cfg.FLIP_BULLISH_RSI_RHYTHM_MIN:
        return GateResult(
            passed=False,
            reason=f"flip_bullish_gate_rsi_rhythm_fail("
                   f"score={rsi_rhythm_score:.3f},"
                   f"min={cfg.FLIP_BULLISH_RSI_RHYTHM_MIN})",
            position_scale=0.0,
        )

    # RSI late_overheat状态 → 否决flip_bullish
    if rsi_state in cfg.LONG_RSI_HARD_VETO_STATES:
        return GateResult(
            passed=False,
            reason=f"flip_bullish_gate_rsi_state_veto(state={rsi_state})",
            position_scale=0.0,
        )

    # volume告警
    if volume_ratio < cfg.LONG_VOLUME_WARN_RATIO:
        position_scale *= cfg.LONG_VOLUME_WARN_SCALE

    return GateResult(
        passed=True,
        reason="flip_bullish_gate_pass",
        position_scale=position_scale,
    )


# ------------------------------------------------------------
# Trial Entry 门 (preflip trial)
# ------------------------------------------------------------

def _check_trial_resonance_gate(
    trade_direction: str,
    macd_4h_direction: str,
    ema_structure_status: str,
    rsi_rhythm_score: float,
    rsi_state: str,
    volume_ratio: float,
    position_scale: float,
    cfg: ResonanceGateConfig,
) -> GateResult:
    """
    Trial entry 门 — 比标准入场略宽松, 但保留EMA和RSI硬门
    """

    rsi_min = (
        cfg.TRIAL_SHORT_RSI_RHYTHM_MIN
        if trade_direction == "short"
        else cfg.TRIAL_LONG_RSI_RHYTHM_MIN
    )

    # EMA结构硬门 (trial也不能进against方向)
    if ema_structure_status in cfg.TRIAL_EMA_STATUS_BLOCKED:
        return GateResult(
            passed=False,
            reason=f"trial_gate_ema_against(dir={trade_direction},"
                   f"ema_status={ema_structure_status})",
            position_scale=0.0,
        )

    # RSI rhythm 最低门 (trial可以低于标准门)
    if rsi_rhythm_score < rsi_min:
        return GateResult(
            passed=False,
            reason=f"trial_gate_rsi_rhythm_fail("
                   f"score={rsi_rhythm_score:.3f},"
                   f"min={rsi_min})",
            position_scale=0.0,
        )

    # RSI状态: short方向不允许rebound_conflict
    if trade_direction == "short" and rsi_state in cfg.SHORT_RSI_HARD_VETO_STATES:
        return GateResult(
            passed=False,
            reason=f"trial_gate_short_rsi_state_veto(state={rsi_state})",
            position_scale=0.0,
        )

    # volume缩减 (非否决)
    if volume_ratio < cfg.SHORT_VOLUME_WARN_RATIO:
        position_scale *= cfg.SHORT_VOLUME_WARN_SCALE

    return GateResult(
        passed=True,
        reason=f"trial_gate_pass(dir={trade_direction})",
        position_scale=position_scale,
    )


# ------------------------------------------------------------
# Attribution 统计 (对应原 vwap_attr 的替换)
# ------------------------------------------------------------

class ResonanceGateAttribution:
    """
    记录谐振门拒绝原因, 替换原来的 vwap_score_filter / vwap_hard_block 计数
    用于ablation对比和线上监控
    """

    def __init__(self):
        self.counters = defaultdict(int)
        self.by_signal  = defaultdict(lambda: defaultdict(int))
        self.by_side    = defaultdict(lambda: defaultdict(int))

    def record(
        self,
        passed: bool,
        reason: str,
        signal_type: str,
        trade_direction: str,
    ):
        if not passed:
            self.counters[reason] += 1
            self.by_signal[signal_type][reason] += 1
            self.by_side[trade_direction][reason] += 1
        else:
            self.counters["resonance_gate_pass"] += 1

    def summary(self) -> dict:
        return {
            "total_gate_blocks":   sum(v for k, v in self.counters.items()
                                       if k != "resonance_gate_pass"),
            "total_gate_pass":     self.counters["resonance_gate_pass"],
            "block_by_reason":     dict(self.counters),
            "block_by_signal":     {k: dict(v) for k, v in self.by_signal.items()},
            "block_by_side":       {k: dict(v) for k, v in self.by_side.items()},
        }
```

---

## 4. 配置DIFF

以下DIFF对应 `candidate_c_macd_ema_rsi_gate` 配置
基于 `config/trading_config_fund_flow.json`

### 4.1 VWAP 入场门全部归零

```diff
   // ===== VWAP Entry Gates =====
-  "min_vwap_score_for_entry": 0.12,
+  "min_vwap_score_for_entry": 0.0,

-  "short_min_vwap_score_for_entry": 0.12,
+  "short_min_vwap_score_for_entry": 0.0,

-  "flip_bearish_short_min_vwap_score_for_entry": 0.25,
+  "flip_bearish_short_min_vwap_score_for_entry": 0.0,

-  "preflip_trial_min_vwap_score": 0.12,
+  "preflip_trial_min_vwap_score": 0.0,

-  "trial_short_below_structure_promotion_min_vwap_score": 0.12,
+  "trial_short_below_structure_promotion_min_vwap_score": 0.0,

-  "stable_bear_continuation_min_vwap_score": 0.12,
+  "stable_bear_continuation_min_vwap_score": 0.0,

-  "stable_bull_continuation_min_vwap_score": 0.12,
+  "stable_bull_continuation_min_vwap_score": 0.0,

-  "flip_bullish_min_vwap_score": 0.12,
+  "flip_bullish_min_vwap_score": 0.0,

-  "vol_vwap_warn_min_vwap_score": 0.12,
+  "vol_vwap_warn_min_vwap_score": 0.0,
```

### 4.2 VWAP 硬偏离否决禁用

```diff
-  "vwap_deviation_hard_block": 0.03,
+  "vwap_deviation_hard_block": 999.0,
```

### 4.3 VWAP 分数权重归零 + 权重重分配

```diff
   // ===== Score Weights =====
   "weight_1h_direction": 0.15,
   "weight_4h_direction": 0.40,
   "weight_4h_enhancement": 0.10,
-  "weight_rsi_rhythm": 0.30,
+  "weight_rsi_rhythm": 0.35,
-  "weight_vwap": 0.05,
+  "weight_vwap": 0.0,
   "weight_15m_entry": 0.05,
   "weight_volume": 0.10,
```

### 4.4 vol_vwap_warn 改为纯volume警告

```diff
-  "vol_vwap_warn_position_scale": 0.0,
+  "vol_vwap_warn_position_scale": 0.0,
+  "vol_warn_position_scale": 0.50,
+  "vol_warn_volume_ratio_threshold": 0.80,
```

> 注: `vol_vwap_warn_position_scale` 保持0.0以防止旧逻辑误触发
> 新增 `vol_warn_position_scale` 由新代码读取

### 4.5 新增 MACD+EMA+RSI 谐振门参数块

```diff
+  // ===== Resonance Gate (替换 VWAP 入场门) =====
+  "resonance_gate_enabled": true,
+
+  // Long gates
+  "resonance_long_4h_required": ["long", "stable_bull_continuation"],
+  "resonance_long_ema_blocked": ["against"],
+  "resonance_long_rsi_rhythm_min": 0.35,
+  "resonance_long_rsi_veto_states": ["late_overheat"],
+
+  // Short gates
+  "resonance_short_4h_required": ["short", "stable_bear_continuation"],
+  "resonance_short_ema_blocked": ["against"],
+  "resonance_short_rsi_rhythm_min": 0.35,
+  "resonance_short_rsi_veto_states": ["rebound_conflict", "spring_conflict"],
+
+  // flip_bearish 7层保护
+  "flip_bearish_resonance_rsi_rhythm_min": 0.40,
+  "flip_bearish_resonance_require_ema_ok": true,
+  "flip_bearish_resonance_require_4h_align": true,
+
+  // flip_bullish 门
+  "flip_bullish_resonance_rsi_rhythm_min": 0.30,
+  "flip_bullish_resonance_require_4h_align": true,
+
+  // Trial entry 门
+  "trial_resonance_long_rsi_rhythm_min": 0.30,
+  "trial_resonance_short_rsi_rhythm_min": 0.30,
+  "trial_resonance_ema_blocked": ["against"],
+
+  // Structural VWAP 遥测仓位缩减 (非硬门)
+  "structural_vwap_telemetry_position_scale_threshold": 0.05,
+  "structural_vwap_telemetry_position_scale": 0.70,
+  "vwap_alert_deviation": 0.005,
```

### 4.6 flip_bearish 独立质量过滤器 — 移除VWAP依赖

```diff
   "short_quality_filter": {
     "enabled": false,
     "flip_bearish_independent_enabled": true,
     "min_funding_rate": 0.0005,
     "max_oi_delta_ratio": 0.0,
-    "min_vwap_deviation": 0.005,
+    "min_vwap_deviation": 0.0,
-    "flip_bearish_min_vwap_score": 0.25,
+    "flip_bearish_min_vwap_score": 0.0,
+    "flip_bearish_min_rsi_rhythm": 0.40,
+    "flip_bearish_require_ema_not_against": true,
+    "flip_bearish_require_4h_bear_alignment": true
   }
```

### 4.7 pretrade_risk_gate — 维持禁用

```diff
   "pretrade_risk_gate": {
-    "enabled": false,
+    "enabled": false,
     // 不变 — ablation期间不启用
   }
```

> **理由**: VWAP门移除后, 策略trade count会骤增
> pretrade_risk_gate 如同期开启, 将无法区分是它还是谐振门决定了结果
> 应在candidate_c ablation通过后单独做pretrade gate的开关实验

---

## 5. Ablation执行计划

### 5.1 配置矩阵

| 配置名 | VWAP门 | weight_vwap | 谐振门 | 预期trades |
|---|---|---|---|---|
| `baseline` | 全部激活 | 0.05 | 无 | 0 |
| `candidate_a` | 全部=0 + hard=999 | 0.05 | 无 | 未知(待测) |
| `candidate_b` | 全部=0 + hard=999 | 0.00→RSI | 无 | 未知(待测) |
| `candidate_c` | 全部=0 + hard=999 | 0.00→RSI | 启用 | 目标≥50/30d |

### 5.2 执行命令

```bash
# candidate_a
python scripts/backtest_macd_v2.py \
  --config config/candidate_a_no_vwap_gate.json \
  --strict-live-mode \
  --simulate-live-close-layers \
  --output-prefix output/backtest/ablation_a_20260504

# candidate_b
python scripts/backtest_macd_v2.py \
  --config config/candidate_b_no_vwap_score.json \
  --strict-live-mode \
  --simulate-live-close-layers \
  --output-prefix output/backtest/ablation_b_20260504

# candidate_c
python scripts/backtest_macd_v2.py \
  --config config/candidate_c_resonance_gate.json \
  --strict-live-mode \
  --simulate-live-close-layers \
  --output-prefix output/backtest/ablation_c_20260504

# 60d validation (candidate_c only)
python scripts/backtest_macd_v2.py \
  --config config/candidate_c_resonance_gate.json \
  --strict-live-mode \
  --simulate-live-close-layers \
  --start-date 2026-03-04 \
  --end-date 2026-05-04 \
  --output-prefix output/backtest/ablation_c_60d_20260504
```

### 5.3 判断规则

```
场景A: candidate_a trades > 50 且 win_rate >= 75%
  → MACD/EMA/RSI本身已足够, 不需要谐振门
  → 但仍建议启用谐振门作为长期保护
  → 部署: candidate_b (分数重分配) 作为最终配置

场景B: candidate_a trades > 50 但 win_rate < 70%
  → VWAP确实在隐藏方向质量问题
  → 必须部署 candidate_c (谐振门)
  → 若candidate_c win_rate >= 75%, 则部署c

场景C: candidate_a trades < 20
  → 非VWAP因素也在阻断 (score/其他门)
  → 先做score权重诊断, 再重跑ablation

场景D: candidate_c win_rate < 70% 且 trades > 50
  → MACD/EMA/RSI谐振门仍不能维持质量
  → 暂停VWAP移除计划
  → 优先做 RSI rhythm 和 EMA structure 的单独质量工程
  → 重新设计信号pool的准入标准
```

---

## 6. 部署检查清单

在将任何candidate配置推送到live之前, 必须逐项确认:

### 6.1 回测指标门 (30d strict-live)

```
[ ] total_trades >= 50
[ ] win_rate >= 75.0%
[ ] profit_factor >= 1.30
[ ] max_drawdown <= 15.0%
[ ] avg_loss <= 0.8 * avg_win
[ ] no single symbol > 40% of total losses
```

### 6.2 60d验证门

```
[ ] 60d MDD <= 1.5 * 30d MDD
[ ] 60d win_rate within 3% of 30d win_rate
[ ] 60d profit_factor >= 1.25
```

### 6.3 损失集群回放

```
[ ] flip_bearish / low-volume shorts 仍被以下非VWAP过滤器之一拦截:
    ADX < 30 或
    RSI rhythm < 0.40 或
    RSI state = rebound_conflict 或
    EMA = against 或
    no 15m + no 4H enhancement
[ ] low-volume red_bar_growing longs 被 vol_warn_position_scale 缩减
```

### 6.4 Attribution 验证

```
[ ] 新的 resonance_gate attribution 字段出现在回测输出中
[ ] vwap_score_filter 计数 = 0 (VWAP门已完全禁用)
[ ] vwap_hard_block 计数 = 0
[ ] resonance_gate_block_by_reason 显示合理的拒绝分布
    (不应全部集中在单一层, 说明有层被意外过度触发)
```

### 6.5 Shadow 验证 (48h)

```
[ ] shadow模式运行完整48h无异常
[ ] would-be trades >= 10
[ ] would-be win_rate >= 70%
[ ] 无 flip_bearish would-be trade 绕过了所有7层保护
[ ] protection_sla 无异常触发
```

### 6.6 代码验证

```
[ ] check_resonance_gate() 单元测试通过
    - flip_bearish 7层测试全部覆盖
    - volume告警缩减路径测试
    - EMA against硬否决测试
    - RSI rebound_conflict硬否决测试
[ ] ResonanceGateAttribution.summary() 输出字段与backtest attribution对齐
[ ] vwap_score 和 structural_vwap_deviation 仍出现在 trade_log (遥测保留)
[ ] short_quality_filter.flip_bearish_independent_enabled = true 仍激活
[ ] vol_vwap_warn_position_scale 旧逻辑路径不再被新代码触发
```

---

> **最终建议**: 先跑ablation_a观察trade count恢复情况, 再决定是否需要candidate_c的完整谐振门。
> 若ablation_b的win_rate就能达标, 则candidate_c的谐振门作为可选保护层而非强制层部署。
> **永远不要在ablation未通过的情况下部署任何VWAP移除配置。**
