# `volume_vwap_both_low` 完全移除建议（2026-05-02）

> **核心结论**：完全移除 `volume_vwap_both_low` 联合 veto，改为分层处理。
> 当前此门控位于 `threshold_check` 之前，阻断了 32 个分数已达 0.68+ 的候选，
> 包括最高分 0.824（ZROUSDT）。这是一个位置错误的粗暴过滤，不是风控措施。

---

## 0. 问题精确定位

### 0.1 实盘 12 小时窗口事实

```
窗口：2026-05-01 14:00 UTC → 2026-05-02 02:09 UTC
覆盖：26 个标的 × 48 个 15m 周期 = ~1247 次 decision
开仓：0 笔

HOLD 原因分布：
  volume_vwap_both_low              589  (47.2%)  ← 最大单项
  4H无明确方向                      391  (31.4%)
  vwap_hard_block                   169  (13.6%)
  rsi_15m_extreme_veto               50   (4.0%)
  green_bar_short_adx_range_filter   21   (1.7%)
  信号评分低于阈值                   16   (1.3%)
  flip_bullish_disabled              10   (0.8%)

已达阈值但仍被 veto 的高分候选：
  score >= 0.68 的候选 = 32 笔，全部被 volume_vwap_both_low 挡住
  最高分 ZROUSDT cycle4：score=0.824，veto=volume_vwap_both_low
```

### 0.2 代码执行顺序（问题所在）

```python
# src/fund_flow/macd_strategy_v2.py  当前执行顺序还原

def generate_signal(self, symbol, bars_15m, bars_1h, bars_4h, config):
    
    # ① 计算评分（score 已经算出来了）
    score, components = self._compute_signal_score(symbol, bars_1h, bars_4h, config)
    
    # ② volume_vwap_both_low veto ← 在 threshold_check 之前！（问题根源）
    # 行号：macd_strategy_v2.py:4566-4583
    score_vol  = components["volume_score"]
    vwap_score = components["vwap_score"]
    
    vol_low  = score_vol  < config.volume_vwap_both_low_min_score_vol   # 默认 0.05
    vwap_low = vwap_score <= config.volume_vwap_both_low_min_vwap_score  # 默认 0.10
    
    if vol_low and vwap_low:
        return _neutral_signal(symbol, score, veto="volume_vwap_both_low")
        # ↑ 直接返回，score=0.824 的候选就在这里死掉
    
    # ③ 其他 veto（vwap_hard_block, rsi_extreme, 等）
    # ...
    
    # ④ threshold_check ← score=0.824 根本没走到这里
    # 行号：macd_strategy_v2.py:4639-4679
    if score < config.threshold:
        return _neutral_signal(symbol, score, veto="score_below_threshold")
    
    # ⑤ 生成真实 EntrySignal
    return EntrySignal(...)
```

**根本问题：`volume_vwap_both_low` 不区分信号质量。
score=0.824 和 score=0.30 的候选被同等对待，都在 threshold_check 之前消灭。
这不是风控，是评分系统的自我否定。**

### 0.3 权重构成分析

```
当前权重配置：
  weight_4h_direction  = 0.40   ← 最重要维度
  weight_rsi_rhythm    = 0.30
  weight_1h_direction  = 0.15
  weight_volume        = 0.10   ← volume 权重只有 10%
  weight_vwap          = 0.05   ← vwap  权重只有 5%
  weight_15m_entry     = 0.00   ← 完全不加分

volume + vwap 合计权重 = 15%
但 volume_vwap_both_low veto 可以否决 score=0.824 的候选。

逻辑矛盾：
  - 评分系统认为 volume 和 vwap 合计只值 15%
  - 但 veto 逻辑认为这两个维度同时低就足以否决全局
  - 一个 score=0.824 的候选说明 4H+RSI+1H 三个主维度都极强
  - 让 15% 权重的维度否决 85% 权重的强信号，逻辑不自洽
```

---

## 1. 完全移除 `volume_vwap_both_low` 的实现

### 1.1 核心 DIFF — `macd_strategy_v2.py`

```diff
  # src/fund_flow/macd_strategy_v2.py
  # 行号参考：4560-4590（移除整个 volume_vwap_both_low veto 块）

  def generate_signal(self, symbol, bars_15m, bars_1h, bars_4h, config):
      
      score, components = self._compute_signal_score(symbol, bars_1h, bars_4h, config)
      direction          = self._get_primary_direction(bars_4h, bars_1h, config)
      
-     # ── volume_vwap_both_low 组合 veto（完全移除）─────────────────────────
-     score_vol  = components.get("volume_score", 0.0)
-     vwap_score = components.get("vwap_score", 0.0)
-     
-     vol_low  = score_vol  < config.volume_vwap_both_low_min_score_vol
-     vwap_low = vwap_score <= config.volume_vwap_both_low_min_vwap_score
-     
-     if vol_low and vwap_low:
-         self._record_hold(symbol, score, reason="volume_vwap_both_low")
-         return _neutral_signal(symbol, score, veto="volume_vwap_both_low")
-     # ── veto end ───────────────────────────────────────────────────────────
-     
+     # ── 替换：volume/vwap 信息写入信号元数据，不再 veto ────────────────────
+     # 原因：volume 和 vwap 合计权重仅 15%，不应在 threshold_check 前否决
+     # 高分候选（4H+RSI+1H 主维度强）不应被低权重维度拦截。
+     # volume/vwap 状态通过 signal.metadata 传递给执行层做仓位缩减判断。
+     volume_score = components.get("volume_score", 0.0)
+     vwap_score   = components.get("vwap_score", 0.0)
+     vol_vwap_warn = (
+         volume_score < config.volume_vwap_both_low_min_score_vol
+         and vwap_score <= config.volume_vwap_both_low_min_vwap_score
+     )
+     # 状态记录：只做日志，不做 veto
+     if vol_vwap_warn:
+         self._record_vol_vwap_warn(symbol, score, volume_score, vwap_score)
+     # ── 替换 end ────────────────────────────────────────────────────────────
      
      # 其他 veto（vwap_hard_block, rsi_extreme, 等）继续保留
      # ...
      
      # threshold_check（现在所有候选都能走到这里）
      if score < self._get_entry_threshold(direction, config):
          self._record_hold(symbol, score, reason="score_below_threshold")
          return _neutral_signal(symbol, score, veto="score_below_threshold")
      
      # 生成真实 EntrySignal，携带 vol_vwap_warn 元数据
      return EntrySignal(
          symbol=symbol,
          direction=direction,
          score=score,
          signal_type=self._classify_signal_type(components, direction),
          metadata={
              "volume_score":   volume_score,
              "vwap_score":     vwap_score,
              "vol_vwap_warn":  vol_vwap_warn,   # ← 执行层据此缩仓
              # ... 其他字段
          },
      )
```

### 1.2 `_record_vol_vwap_warn` 新增（伪代码）

```python
# src/fund_flow/macd_strategy_v2.py

def _record_vol_vwap_warn(
    self,
    symbol: str,
    score: float,
    volume_score: float,
    vwap_score: float,
) -> None:
    """
    原 volume_vwap_both_low veto 被移除后，
    改为写入警告日志，供事后统计被放行的 warn 候选的表现。
    不阻止信号进入执行层。
    """
    record = {
        "ts":            _utcnow_iso(),
        "symbol":        symbol,
        "score":         round(score, 4),
        "volume_score":  round(volume_score, 4),
        "vwap_score":    round(vwap_score, 4),
        "event":         "vol_vwap_warn_passed_to_threshold",
    }
    self._diag_sink.write("vol_vwap_warn", record)
    # 注意：这里只写 diag，不返回任何阻断结果
```

### 1.3 配置 DIFF

```diff
  # config/trading_config_fund_flow.json

  "signal_quality_gates": {
-   "volume_vwap_both_low_enabled": true,
-   "volume_vwap_both_low_min_score_vol": 0.05,
-   "volume_vwap_both_low_min_vwap_score": 0.10,
+   "volume_vwap_both_low_enabled": false,
+   "_removed_reason": "gate 位于 threshold_check 之前，阻断 score>=0.68 的高分候选。volume/vwap 权重仅 15%，不应否决 85% 强信号维度。改为执行层仓位缩减。",
+   
+   "vol_vwap_warn_log_enabled": true,
+   "_vol_vwap_warn_comment": "保留原阈值作为 warn 记录阈值，不再 veto",
+   "vol_vwap_warn_min_score_vol": 0.05,
+   "vol_vwap_warn_min_vwap_score": 0.10
  },
  
  "execution_degradation": {
    "open_ioc_retry_times": 4,
    "open_ioc_dynamic_step_enabled": true,
    "open_ioc_max_total_slippage_bps": 60,
    "force_market_fallback_on_ioc_remainder": false,
    "open_market_fallback_max_slippage_bps": 8,
+   
+   "vol_vwap_warn_position_scale": 0.50,
+   "_vol_vwap_warn_position_scale_comment": "vol_vwap_warn=true 时仓位缩减到 50%，保留机会但控制风险"
  }
```

---

## 2. 执行层仓位缩减 — 替代 veto 的正确处理

移除 veto 后，`vol_vwap_warn` 必须在执行层做仓位降级，而不是完全放行。

### 2.1 `decision_engine.py` DIFF

```diff
  # src/fund_flow/decision_engine.py
  # 行号参考：4387-4420（decision 处理段）

  def _make_entry_decision(self, signal: EntrySignal, config: DecisionConfig) -> Decision:
      
      # 基础仓位计算
      base_size = self._compute_position_size(signal.score, config)
      
+     # ── 新增：vol_vwap_warn 仓位降级 ────────────────────────────────────────
+     # 原 volume_vwap_both_low veto 已移除。
+     # 当 vol_vwap_warn=True 时（低成交量 + 低 VWAP 评分），
+     # 不阻止入场，但把仓位缩减到配置比例（默认 50%）。
+     # 这样：1）保留了高分信号的机会  2）通过小仓限制了低流动性风险
+     final_size = base_size
+     vol_vwap_warn = signal.metadata.get("vol_vwap_warn", False)
+     
+     if vol_vwap_warn and config.vol_vwap_warn_position_scale_enabled:
+         scale_factor = config.vol_vwap_warn_position_scale  # 默认 0.50
+         final_size   = base_size * scale_factor
+         self._record_decision_adjustment(
+             symbol=signal.symbol,
+             reason="vol_vwap_warn_position_scaled",
+             original_size=base_size,
+             adjusted_size=final_size,
+             scale_factor=scale_factor,
+             signal_score=signal.score,
+         )
+     # ── 仓位降级 end ──────────────────────────────────────────────────────────
      
      return Decision(
          operation=Operation.BUY if signal.direction == "long" else Operation.SELL,
          symbol=signal.symbol,
          size=final_size,
          signal_score=signal.score,
          signal_type=signal.signal_type,
          metadata=signal.metadata,
      )
```

### 2.2 完整执行层配置 DIFF

```diff
  # config/trading_config_fund_flow.json

  "decision_engine": {
    "max_active_symbols": 3,
    "reserve_pct": 0.20,
+   
+   "vol_vwap_warn_position_scale_enabled": true,
+   "vol_vwap_warn_position_scale": 0.50,
+   "_comment": "vol_vwap_warn 信号仓位缩 50%，不再完全 veto"
  }
```

---

## 3. `decision_engine.py` — 移除 neutral 路由中的 `volume_vwap_both_low`

```diff
  # src/fund_flow/decision_engine.py
  # 行号参考：4387-4391（hold 返回段）

  def process_signal(self, raw_signal, config):
      
      if raw_signal.is_neutral:
          veto_type = raw_signal.veto_reason
          
-         # 原始 veto_type 可能为 "volume_vwap_both_low"，映射到 HOLD
-         # 移除后这个分支不会再出现 volume_vwap_both_low 字符串
+         # 移除后 veto_type 只会是：
+         #   4H无明确方向 / vwap_hard_block / rsi_15m_extreme_veto
+         #   green_bar_short_adx_range_filter / score_below_threshold
+         #   flip_bullish_disabled / flip_bullish_sniper_no_trend_alignment
          
          return Decision(
              operation=Operation.HOLD,
              symbol=raw_signal.symbol,
              reason=f"macd_v2_hold_{veto_type}_score_{raw_signal.score:.4f}",
          )
      
      # 非 neutral → 进入 _make_entry_decision
      return self._make_entry_decision(raw_signal, config)
```

---

## 4. 诊断产物更新 — `fund_flow_attribution.jsonl`

移除 veto 后，诊断产物中的 `volume_vwap_both_low` 字段应重新定义：

```diff
  # src/fund_flow/attribution_writer.py

  def write_decision_record(self, symbol, cycle, signal, decision, config):
      record = {
          "cycle":         cycle,
          "symbol":        symbol,
          "score":         signal.score,
          "dir":           signal.direction,
          "decision":      decision.operation.value,
          "veto_reason":   decision.reason if decision.is_hold else None,
          
+         # 新增：vol_vwap_warn 状态（原 veto，现为元数据）
+         "vol_vwap_warn":          signal.metadata.get("vol_vwap_warn", False),
+         "volume_score":           signal.metadata.get("volume_score", None),
+         "vwap_score":             signal.metadata.get("vwap_score", None),
+         "vol_vwap_warn_scaled":   (
+             decision.metadata.get("vol_vwap_warn_position_scaled", False)
+             if not decision.is_hold else False
+         ),
+         "original_size":          decision.metadata.get("original_size", None),
+         "adjusted_size":          decision.metadata.get("adjusted_size", None),
          
-         # 移除：不再需要记录 volume_vwap_both_low 作为独立 HOLD 原因
-         # （因为它已经不再产生 HOLD）
      }
      self._sink.write(record)
```

---

## 5. 单测套件（完整）

```python
# tests/test_volume_vwap_veto_removal.py
"""
验证 volume_vwap_both_low veto 完全移除后的行为。
核心目标：
  1. 高分信号（score >= 0.68）不再被 vol_vwap 状态阻断
  2. vol_vwap_warn 状态正确传递到执行层
  3. 执行层仓位缩减正确生效
  4. 原有其他 veto（vwap_hard_block, rsi_extreme 等）不受影响
  5. 诊断日志正确写入 warn 状态
"""

import pytest
from unittest.mock import MagicMock, patch


class TestVolumeVwapVetoRemoval:
    """核心：veto 移除后高分信号必须通过"""

    def test_high_score_signal_passes_despite_low_vol_vwap(self):
        """
        score=0.824（ZROUSDT 历史案例），volume_score=0.02，vwap_score=0.05
        移除前：被 volume_vwap_both_low veto → neutral
        移除后：必须通过 threshold_check，生成 EntrySignal
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,   # 已移除
            red_bar_growing_threshold=0.68,
        ))
        bars_4h = make_bars_4h(adx=32.0, macd_hist_positive=True, direction="long")
        bars_1h = make_bars_1h(adx=22.0, macd_hist_growing=True)
        
        # 模拟低 volume 和低 vwap 的市场状态（原先会触发 veto）
        bars_1h.volume_score = 0.02   # 低于原 0.05 阈值
        bars_1h.vwap_score   = 0.05   # 低于原 0.10 阈值
        
        signal = strategy.generate_signal(
            symbol="ZROUSDT",
            bars_15m=make_bars_15m(),
            bars_1h=bars_1h,
            bars_4h=bars_4h,
            config=strategy.config,
        )
        
        # 移除后不应是 neutral
        assert not signal.is_neutral, (
            f"score=0.824 的候选不应被 vol_vwap 状态阻断，"
            f"实际 veto_reason={signal.veto_reason}"
        )
        assert signal.direction in ("long", "short")
        assert signal.score >= 0.68

    def test_low_score_signal_still_rejected_by_threshold(self):
        """
        score=0.55（低于阈值），即使 vol_vwap 状态良好
        移除 veto 后，threshold_check 仍然生效
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            red_bar_growing_threshold=0.68,
        ))
        bars_4h = make_bars_4h(score_contribution=0.55)
        bars_1h = make_bars_1h(volume_score=0.80, vwap_score=0.90)  # 好的 vol/vwap
        
        signal = strategy.generate_signal("BTCUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        assert signal.is_neutral
        assert signal.veto_reason == "score_below_threshold"

    def test_vol_vwap_warn_metadata_set_when_both_low(self):
        """
        vol_vwap 同时低时，signal.metadata["vol_vwap_warn"] 必须为 True
        （替代 veto，用于执行层仓位缩减判断）
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            vol_vwap_warn_min_score_vol=0.05,
            vol_vwap_warn_min_vwap_score=0.10,
            red_bar_growing_threshold=0.68,
        ))
        bars_4h = make_bars_4h(direction="long", strength="strong")  # 高分 4H
        bars_1h = make_bars_1h(volume_score=0.03, vwap_score=0.08)   # 低 vol/vwap
        
        signal = strategy.generate_signal("RENDERUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        # 信号应该通过（不是 neutral）
        assert not signal.is_neutral
        # 但 metadata 中必须携带 warn 标记
        assert signal.metadata["vol_vwap_warn"] is True
        assert signal.metadata["volume_score"] == pytest.approx(0.03, abs=0.01)
        assert signal.metadata["vwap_score"]   == pytest.approx(0.08, abs=0.01)

    def test_vol_vwap_warn_not_set_when_either_ok(self):
        """
        只有 volume 低（vwap 正常）或只有 vwap 低（volume 正常），
        vol_vwap_warn 应为 False（必须两个同时低才触发 warn）
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            vol_vwap_warn_min_score_vol=0.05,
            vol_vwap_warn_min_vwap_score=0.10,
            red_bar_growing_threshold=0.68,
        ))
        bars_4h = make_bars_4h(direction="long", strength="strong")
        
        # Case A：volume 低，vwap 正常
        bars_1h_a = make_bars_1h(volume_score=0.03, vwap_score=0.50)
        signal_a  = strategy.generate_signal("ETHUSDT", make_bars_15m(), bars_1h_a, bars_4h,
                                             strategy.config)
        assert signal_a.metadata.get("vol_vwap_warn", False) is False, \
            "只有 volume 低，不触发 both_low warn"
        
        # Case B：vwap 低，volume 正常
        bars_1h_b = make_bars_1h(volume_score=0.60, vwap_score=0.05)
        signal_b  = strategy.generate_signal("SOLUSDT", make_bars_15m(), bars_1h_b, bars_4h,
                                             strategy.config)
        assert signal_b.metadata.get("vol_vwap_warn", False) is False, \
            "只有 vwap 低，不触发 both_low warn"

    def test_volume_vwap_both_low_enabled_true_still_works(self):
        """
        向后兼容：若 volume_vwap_both_low_enabled=True（旧配置），
        veto 逻辑应仍然生效（不破坏现有 feature flag 机制）
        此测试在移除后标记为 skip，用于验证 feature flag 路径
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=True,   # 旧配置，保留向后兼容
            volume_vwap_both_low_min_score_vol=0.05,
            volume_vwap_both_low_min_vwap_score=0.10,
        ))
        bars_4h = make_bars_4h(direction="long", strength="strong")
        bars_1h = make_bars_1h(volume_score=0.02, vwap_score=0.05)
        
        signal = strategy.generate_signal("DOGEUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        # 旧配置开启时，仍然 veto（向后兼容）
        assert signal.is_neutral
        assert signal.veto_reason == "volume_vwap_both_low"


class TestPositionScalingOnVolVwapWarn:
    """执行层仓位缩减逻辑"""

    def test_position_scaled_down_on_vol_vwap_warn(self):
        """
        vol_vwap_warn=True 时，仓位应按 scale_factor 缩减
        默认 scale_factor=0.50 → 仓位减半
        """
        engine = make_decision_engine(config=make_config(
            vol_vwap_warn_position_scale_enabled=True,
            vol_vwap_warn_position_scale=0.50,
        ))
        signal = make_entry_signal(
            score=0.824,
            direction="long",
            signal_type="red_bar_growing",
            metadata={
                "vol_vwap_warn":  True,
                "volume_score":   0.03,
                "vwap_score":     0.08,
            },
        )
        base_size = engine._compute_position_size(signal.score, engine.config)
        
        decision = engine._make_entry_decision(signal, engine.config)
        
        assert decision.operation.value == "BUY"
        assert decision.size == pytest.approx(base_size * 0.50, rel=0.01), \
            f"期望仓位 {base_size * 0.50:.2f}，实际 {decision.size:.2f}"
        assert decision.metadata.get("vol_vwap_warn_position_scaled") is True
        assert decision.metadata.get("scale_factor") == pytest.approx(0.50, abs=0.01)

    def test_position_not_scaled_when_warn_false(self):
        """
        vol_vwap_warn=False 时，仓位按正常计算，不缩减
        """
        engine = make_decision_engine(config=make_config(
            vol_vwap_warn_position_scale_enabled=True,
            vol_vwap_warn_position_scale=0.50,
        ))
        signal = make_entry_signal(
            score=0.780,
            direction="long",
            metadata={
                "vol_vwap_warn": False,
                "volume_score":  0.60,
                "vwap_score":    0.45,
            },
        )
        base_size = engine._compute_position_size(signal.score, engine.config)
        
        decision = engine._make_entry_decision(signal, engine.config)
        
        assert decision.size == pytest.approx(base_size, rel=0.01), \
            "vol_vwap 状态正常时，仓位不应缩减"
        assert decision.metadata.get("vol_vwap_warn_position_scaled", False) is False

    def test_position_scaling_disabled_by_config(self):
        """
        vol_vwap_warn_position_scale_enabled=False 时，
        即使 vol_vwap_warn=True，仓位也不缩减
        """
        engine = make_decision_engine(config=make_config(
            vol_vwap_warn_position_scale_enabled=False,
        ))
        signal = make_entry_signal(
            score=0.720,
            direction="long",
            metadata={"vol_vwap_warn": True},
        )
        base_size = engine._compute_position_size(signal.score, engine.config)
        
        decision = engine._make_entry_decision(signal, engine.config)
        
        assert decision.size == pytest.approx(base_size, rel=0.01), \
            "仓位缩减功能关闭时不应缩减"

    def test_custom_scale_factor_applied_correctly(self):
        """
        自定义 scale_factor=0.30 时，仓位缩到 30%
        （极端低流动性场景）
        """
        engine = make_decision_engine(config=make_config(
            vol_vwap_warn_position_scale_enabled=True,
            vol_vwap_warn_position_scale=0.30,
        ))
        signal = make_entry_signal(
            score=0.700,
            direction="short",
            metadata={"vol_vwap_warn": True},
        )
        base_size = engine._compute_position_size(signal.score, engine.config)
        
        decision = engine._make_entry_decision(signal, engine.config)
        
        assert decision.operation.value == "SELL"
        assert decision.size == pytest.approx(base_size * 0.30, rel=0.01)

    def test_decision_adjustment_record_written(self):
        """
        仓位缩减时，_record_decision_adjustment 必须被调用，
        确保 attribution log 里有缩减记录
        """
        engine = make_decision_engine(config=make_config(
            vol_vwap_warn_position_scale_enabled=True,
            vol_vwap_warn_position_scale=0.50,
        ))
        signal = make_entry_signal(
            score=0.749,
            direction="long",
            symbol="RENDERUSDT",
            metadata={"vol_vwap_warn": True, "volume_score": 0.02, "vwap_score": 0.07},
        )
        
        with patch.object(engine, "_record_decision_adjustment") as mock_record:
            engine._make_entry_decision(signal, engine.config)
            
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["reason"] == "vol_vwap_warn_position_scaled"
            assert call_kwargs["symbol"] == "RENDERUSDT"
            assert call_kwargs["scale_factor"] == 0.50


class TestOtherVetoesUnaffected:
    """确认其他 veto 逻辑不受 volume_vwap_both_low 移除影响"""

    def test_vwap_hard_block_still_active(self):
        """
        vwap_hard_block 是独立 veto，必须在移除 volume_vwap_both_low 后仍然生效
        （两者是不同的阻断机制：hard_block 处理 VWAP 价格偏离，both_low 处理评分低）
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            vwap_hard_block_enabled=True,
            vwap_hard_block_deviation_pct=0.03,
        ))
        bars_1h = make_bars_1h(
            volume_score=0.03,     # 低 volume（原先会触发 both_low veto）
            vwap_score=0.05,       # 低 vwap 评分
            vwap_deviation_pct=0.05,  # VWAP 价格偏离 5%（超过 hard_block 阈值）
        )
        bars_4h = make_bars_4h(direction="long", strength="strong")
        
        signal = strategy.generate_signal("ICPUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        # vwap_hard_block 独立触发，与 both_low 无关
        assert signal.is_neutral
        assert signal.veto_reason == "vwap_hard_block", \
            f"期望 vwap_hard_block，实际 {signal.veto_reason}"

    def test_rsi_15m_extreme_veto_still_active(self):
        """
        rsi_15m_extreme_veto 在 volume_vwap_both_low 移除后仍然独立生效
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            rsi_15m_extreme_veto_enabled=True,
            rsi_15m_extreme_upper=80.0,
        ))
        bars_15m = make_bars_15m(rsi=85.0)   # RSI 极端
        bars_1h  = make_bars_1h(volume_score=0.02, vwap_score=0.05)  # 低 vol/vwap
        bars_4h  = make_bars_4h(direction="long", strength="strong")
        
        signal = strategy.generate_signal("DOGEUSDT", bars_15m, bars_1h, bars_4h,
                                          strategy.config)
        
        assert signal.is_neutral
        assert signal.veto_reason == "rsi_15m_extreme_veto"

    def test_4h_no_direction_still_active(self):
        """
        4H 无明确方向的 neutral 在移除 both_low 后仍然触发
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
        ))
        bars_4h = make_bars_4h(direction=None, adx=8.0)  # 无方向，ADX 极弱
        bars_1h = make_bars_1h(volume_score=0.02, vwap_score=0.05)
        
        signal = strategy.generate_signal("XRPUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        assert signal.is_neutral
        assert "4H" in signal.veto_reason or signal.veto_reason == "no_4h_direction"

    def test_flip_bullish_disabled_still_active(self):
        """
        flip_bullish 禁用逻辑不受影响
        """
        strategy = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            disable_flip_bullish_entries=True,
        ))
        bars_4h = make_bars_4h(signal_type="flip_bullish")
        bars_1h = make_bars_1h(volume_score=0.02, vwap_score=0.05)
        
        signal = strategy.generate_signal("BTCUSDT", make_bars_15m(), bars_1h, bars_4h,
                                          strategy.config)
        
        assert signal.is_neutral
        assert "flip_bullish_disabled" in signal.veto_reason


class TestDiagnosticLogging:
    """诊断日志正确性"""

    def test_vol_vwap_warn_written_to_diag_sink(self):
        """
        vol_vwap_warn 状态应写入 diag_sink，而不是变成 HOLD decision
        """
        diag_sink = MockDiagSink()
        strategy  = make_strategy(config=make_config(
            volume_vwap_both_low_enabled=False,
            vol_vwap_warn_log_enabled=True,
            vol_vwap_warn_min_score_vol=0.05,
            vol_vwap_warn_min_vwap_score=0.10,
        ), diag_sink=diag_sink)
        
        bars_4h = make_bars_4h(direction="long", strength="strong")
        bars_1h = make_bars_1h(volume_score=0.02, vwap_score=0.07)
        
        strategy.generate_signal("ALGOUSDT", make_bars_15m(), bars_1h, bars_4h,
                                 strategy.config)
        
        warn_records = diag_sink.get_records("vol_vwap_warn")
        assert len(warn_records) == 1
        assert warn_records[0]["symbol"] == "ALGOUSDT"
        assert warn_records[0]["event"]  == "vol_vwap_warn_passed_to_threshold"

    def test_attribution_record_includes_vol_vwap_fields(self):
        """
        attribution.jsonl 中每条 decision record 必须包含 vol_vwap 相关字段
        """
        writer  = AttributionWriter(sink=MockSink())
        signal  = make_entry_signal(
            score=0.749,
            symbol="RENDERUSDT",
            metadata={
                "vol_vwap_warn": True,
                "volume_score":  0.02,
                "vwap_score":    0.07,
            },
        )
        decision = make_decision(
            operation="BUY",
            metadata={
                "vol_vwap_warn_position_scaled": True,
                "original_size":  100.0,
                "adjusted_size":  50.0,
            },
        )
        
        writer.write_decision_record("RENDERUSDT", cycle=25, signal=signal,
                                     decision=decision, config=make_config())
        
        record = writer.sink.last_record
        assert record["vol_vwap_warn"]        is True
        assert record["volume_score"]          == pytest.approx(0.02, abs=0.005)
        assert record["vwap_score"]            == pytest.approx(0.07, abs=0.005)
        assert record["vol_vwap_warn_scaled"]  is True
        assert record["original_size"]         == pytest.approx(100.0, abs=0.1)
        assert record["adjusted_size"]         == pytest.approx(50.0, abs=0.1)

    def test_hold_decision_does_not_contain_volume_vwap_both_low_reason(self):
        """
        移除后，fund_flow_attribution.jsonl 中不应再出现
        veto_reason = "volume_vwap_both_low" 的 HOLD 记录
        """
        engine = make_decision_engine(config=make_config(
            volume_vwap_both_low_enabled=False,
        ))
        # 模拟一个低 vol/vwap 但高分的 signal（现在会通过 threshold）
        signal = make_entry_signal(
            score=0.72,
            direction="long",
            metadata={"vol_vwap_warn": True, "volume_score": 0.02, "vwap_score": 0.07},
        )
        
        decision = engine._make_entry_decision(signal, engine.config)
        
        # 高分信号不应是 HOLD，更不应有 volume_vwap_both_low 原因
        assert decision.operation.value != "HOLD", \
            "score >= threshold 的候选不应产生 HOLD decision"
        assert "volume_vwap_both_low" not in str(decision.reason or "")
```

---

## 6. 三组 A/B 消融计划（移除后验证）

### 6.1 消融脚本（伪代码）

```python
# scripts/run_vol_vwap_ablation_20260502.py
"""
验证移除 volume_vwap_both_low 后，回测与实盘的效果变化。
使用归核化基线（core_reset_20260501）作为对照组。
运行顺序：先 A，A 结果出来后再 B，B 通过后再 C。
不要同时运行多组，避免变量干扰。
"""

from backtest import run_strict_live_backtest, load_config, merge_config


BASE_CONFIG = load_config("config/trading_config_fund_flow.json")
WINDOW      = dict(start="2026-02-23", end="2026-03-24T23:59:59")

ABLATION_CONFIGS = [
    # ── 对照组：归核化基线（不改任何东西）──────────────────────────────────
    (
        "A_baseline_core_reset",
        {
            "signal_quality_gates": {
                "volume_vwap_both_low_enabled": True,   # 当前 live 状态
            },
        },
    ),
    
    # ── 实验组 1：完全移除 veto，不加仓位缩减 ─────────────────────────────
    # 目的：单独量化"放行高分信号"的效果，不混入仓位缩减的影响
    (
        "B_veto_removed_no_scale",
        {
            "signal_quality_gates": {
                "volume_vwap_both_low_enabled": False,
            },
            "decision_engine": {
                "vol_vwap_warn_position_scale_enabled": False,  # 不缩仓
            },
        },
    ),
    
    # ── 实验组 2：完全移除 veto，加 50% 仓位缩减（推荐配置）─────────────
    (
        "C_veto_removed_with_50pct_scale",
        {
            "signal_quality_gates": {
                "volume_vwap_both_low_enabled": False,
            },
            "decision_engine": {
                "vol_vwap_warn_position_scale_enabled": True,
                "vol_vwap_warn_position_scale": 0.50,
            },
        },
    ),
    
    # ── 实验组 3：完全移除 veto，加 30% 仓位缩减（保守配置）─────────────
    (
        "D_veto_removed_with_30pct_scale",
        {
            "signal_quality_gates": {
                "volume_vwap_both_low_enabled": False,
            },
            "decision_engine": {
                "vol_vwap_warn_position_scale_enabled": True,
                "vol_vwap_warn_position_scale": 0.30,
            },
        },
    ),
]


def run_ablation():
    results = []
    
    for name, overrides in ABLATION_CONFIGS:
        cfg = merge_config(BASE_CONFIG, overrides)
        r   = run_strict_live_backtest(cfg, **WINDOW, label=name)
        
        results.append({
            "name":            name,
            "return":          r.total_return,
            "wr":              r.win_rate,
            "trades":          r.total_trades,
            "pf":              r.profit_factor,
            "mdd":             r.max_drawdown,
            "submitted":       r.orders_submitted,
            "filled":          r.orders_filled,
            "canceled":        r.orders_canceled,
            "cancel_rate":     r.orders_canceled / r.orders_submitted if r.orders_submitted else 0,
            "vol_warn_trades": r.vol_vwap_warn_trade_count,      # 新增：vol_warn 信号的成交数
            "vol_warn_wr":     r.vol_vwap_warn_trade_win_rate,   # 新增：vol_warn 信号的 WR
            "vol_warn_pnl":    r.vol_vwap_warn_trade_pnl_sum,    # 新增：vol_warn 信号的 PnL
        })
    
    print_comparison_table(results, baseline_name="A_baseline_core_reset")
    return results
```

### 6.2 决策规则（读取消融结果后）

```python
def decide_vol_vwap_removal_action(results: list[dict]) -> str:
    A = find_result(results, "A_baseline_core_reset")
    B = find_result(results, "B_veto_removed_no_scale")
    C = find_result(results, "C_veto_removed_with_50pct_scale")
    D = find_result(results, "D_veto_removed_with_30pct_scale")
    
    print("=" * 70)
    print("vol_vwap_both_low 移除 消融决策分析")
    print("=" * 70)
    
    # ── 判断 1：B 组（移除 + 无缩仓）是否导致质量下降 ─────────────────────
    b_wr_ok      = B["wr"]  >= A["wr"]  - 0.03   # WR 下降不超 3pp
    b_mdd_ok     = B["mdd"] <= A["mdd"] + 0.02   # MDD 上升不超 2pp
    b_pf_ok      = B["pf"]  >= A["pf"]  - 0.50   # PF 下降不超 0.50
    b_return_ok  = B["return"] >= A["return"] - 0.03  # return 下降不超 3pp
    
    print(f"B（无缩仓）：WR={B['wr']:.2%} {'✓' if b_wr_ok else '✗'}  "
          f"MDD={B['mdd']:.2%} {'✓' if b_mdd_ok else '✗'}  "
          f"PF={B['pf']:.2f} {'✓' if b_pf_ok else '✗'}  "
          f"Return={B['return']:+.2%} {'✓' if b_return_ok else '✗'}")
    
    # ── 判断 2：vol_warn 信号的实际质量 ────────────────────────────────────
    warn_acceptable_wr  = B["vol_warn_wr"] >= 0.80     # warn 信号 WR >= 80%
    warn_positive_pnl   = B["vol_warn_pnl"] > 0        # warn 信号贡献正 PnL
    
    print(f"vol_warn 信号质量：WR={B['vol_warn_wr']:.2%} {'✓' if warn_acceptable_wr else '✗'}  "
          f"PnL={'正' if warn_positive_pnl else '负'} ({B['vol_warn_pnl']:+.2f})")
    
    # ── 判断 3：C 组（50% 缩仓）是否在 B 基础上进一步改善 MDD ──────────────
    c_better_mdd = C["mdd"] <= B["mdd"]
    c_return_ok  = C["return"] >= A["return"] * 0.97   # 不因缩仓损失超 3% return
    
    print(f"C（50% 缩仓）：MDD={C['mdd']:.2%} {'改善' if c_better_mdd else '未改善'}  "
          f"Return={C['return']:+.2%} {'✓' if c_return_ok else '✗'}")
    
    # ── 最终决策 ────────────────────────────────────────────────────────────
    if not (b_wr_ok and b_mdd_ok and b_pf_ok):
        return (
            "❌ B 组核心指标未通过：vol_warn 信号质量不足以支持完全放行。\n"
            "建议：维持 veto，但把触发位置移到 threshold_check 之后（改为后置过滤）。"
        )
    
    if not warn_acceptable_wr:
        return (
            "⚠️ B 组整体通过，但 vol_warn 信号 WR 低于 80%。\n"
            "建议：推进 C 组（50% 缩仓），WR 可容忍在 77%+ 时进入 live 测试。"
        )
    
    if c_better_mdd and c_return_ok:
        return (
            "✅ 推荐 C 组配置（完全移除 veto + 50% 仓位缩减）进入 live 测试。\n"
            "C 组在保留收益的同时降低了 MDD，是移除 veto 的最优配置。"
        )
    
    return (
        "✅ 推进 B 组配置（完全移除 veto，无缩仓）进入 live 测试。\n"
        "50% 缩仓未带来 MDD 改善，说明 vol_warn 信号质量本身已足够。"
    )
```

### 6.3 验收矩阵

```
消融组  配置                              Return    WR       MDD      PF     trades  结论
────────────────────────────────────────────────────────────────────────────────────────────
A       基线（veto 保留）                 41.58%  87.78%   8.23%    6.15    90     对照组
B       移除 veto，无缩仓                 目标≥41% ≥84.78%  ≤10.23%  ≥5.65  90-115  实验组
C       移除 veto，50% 缩仓（推荐）       目标≥41% ≥85.78%  ≤9.50%   ≥5.85  90-110  推荐组
D       移除 veto，30% 缩仓（保守）       目标≥40% ≥86.00%  ≤8.80%   ≥6.00  90-100  保守组
────────────────────────────────────────────────────────────────────────────────────────────
注：WR/MDD/PF 目标均相对 A 组留出容忍 delta（WR±3pp，MDD+2pp，PF-0.5）
    B 组 MDD 容忍 +2pp 是因为移除缩仓后仓位变大

vol_warn 专项验收（B 组和 C 组均需通过）：
  vol_warn 信号成交数      >= 5 笔（至少有统计意义）
  vol_warn 信号 WR         >= 77%（允许低于总体 WR 约 10pp）
  vol_warn 信号 PnL 总和   > 0  （整体贡献正收益）
```

---

## 7. 实盘 12 小时窗口的模拟回放

移除 veto 后，对 12 小时无开仓窗口的 32 个高分候选做回测验证：

```python
# scripts/replay_vol_vwap_blocked_signals_20260502.py
"""
对 2026-05-01 14:00 ~ 2026-05-02 02:09 窗口内
32 个被 volume_vwap_both_low 阻断的 score >= 0.68 候选，
做离线回放，验证它们如果被放行的真实表现。
"""

import json
from pathlib import Path
from datetime import datetime, timezone


BLOCKED_SIGNALS = [
    # 从 attribution.jsonl 解析出的被 veto 高分候选
    {"cycle": 4,  "ts": "2026-05-01T14:45:03Z", "symbol": "ZROUSDT",    "score": 0.824},
    {"cycle": 25, "ts": "2026-05-01T20:00:03Z", "symbol": "RENDERUSDT", "score": 0.749},
    {"cycle": 47, "ts": "2026-05-02T01:30:03Z", "symbol": "DOGEUSDT",   "score": 0.742},
    {"cycle": 2,  "ts": "2026-05-01T14:15:03Z", "symbol": "ICPUSDT",    "score": 0.719},
    # ... 其余 28 个候选从 attribution.jsonl 补全
]


def replay_blocked_signals(
    blocked_signals: list[dict],
    kline_cache_path: str,
    config: dict,
    forward_bars: int = 16,    # 回放 16 根 15m bar（= 4 小时）
) -> list[dict]:
    """
    对每个被阻断的候选信号，模拟：
    1. 入场价 = 信号时间后第 1 根 15m bar 开盘价
    2. 出场 = 持有 forward_bars 根 bar 后强制平仓
       （或触发 stop_loss_pct / take_profit_pct 先出场）
    3. 记录 PnL 和是否盈利
    """
    cache  = KlineCache(kline_cache_path)
    results = []
    
    for sig in blocked_signals:
        symbol     = sig["symbol"]
        entry_time = datetime.fromisoformat(sig["ts"].replace("Z", "+00:00"))
        
        # 拉取入场后的 K 线数据
        bars = cache.get_bars(
            symbol=symbol,
            start_time=entry_time,
            n_bars=forward_bars + 1,
            interval="15m",
        )
        
        if len(bars) < 2:
            print(f"[SKIP] {symbol} {entry_time} 数据不足")
            continue
        
        entry_price = bars[1].open_price   # 信号后第 1 根 bar 开盘入场
        direction   = sig.get("direction", "long")
        
        # 模拟持仓，检查 TP/SL
        exit_price    = None
        exit_reason   = None
        stop_loss     = config.get("stop_loss_pct",    0.02)
        take_profit   = config.get("take_profit_pct",  0.04)
        
        for bar in bars[1:forward_bars + 1]:
            if direction == "long":
                if bar.low_price <= entry_price * (1 - stop_loss):
                    exit_price  = entry_price * (1 - stop_loss)
                    exit_reason = "stop_loss"
                    break
                if bar.high_price >= entry_price * (1 + take_profit):
                    exit_price  = entry_price * (1 + take_profit)
                    exit_reason = "take_profit"
                    break
            else:  # short
                if bar.high_price >= entry_price * (1 + stop_loss):
                    exit_price  = entry_price * (1 + stop_loss)
                    exit_reason = "stop_loss"
                    break
                if bar.low_price <= entry_price * (1 - take_profit):
                    exit_price  = entry_price * (1 - take_profit)
                    exit_reason = "take_profit"
                    break
        
        if exit_price is None:
            # 没有触发 TP/SL，强制在最后一根 bar 收盘价出场
            exit_price  = bars[min(forward_bars, len(bars) - 1)].close_price
            exit_reason = "time_exit"
        
        if direction == "long":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        results.append({
            "symbol":       symbol,
            "score":        sig["score"],
            "entry_time":   sig["ts"],
            "entry_price":  entry_price,
            "exit_price":   exit_price,
            "exit_reason":  exit_reason,
            "direction":    direction,
            "pnl_pct":      round(pnl_pct, 4),
            "is_win":       pnl_pct > 0,
        })
    
    return results


def summarize_replay(results: list[dict]) -> None:
    wins   = [r for r in results if r["is_win"]]
    losses = [r for r in results if not r["is_win"]]
    
    total_pnl = sum(r["pnl_pct"] for r in results)
    wr        = len(wins) / len(results) if results else 0
    
    print(f"\n=== 32 个被 volume_vwap_both_low veto 阻断的候选回放结果 ===")
    print(f"总候选数：{len(results)}")
    print(f"胜率：   {wr:.2%}")
    print(f"总 PnL： {total_pnl:+.4f} ({total_pnl*100:+.2f}%)")
    print(f"平均盈利：{sum(r['pnl_pct'] for r in wins)/len(wins):.4f}" if wins else "无盈利单")
    print(f"平均亏损：{sum(r['pnl_pct'] for r in losses)/len(losses):.4f}" if losses else "无亏损单")
    
    print("\n高分候选（score >= 0.72）明细：")
    for r in sorted(results, key=lambda x: -x["score"]):
        if r["score"] >= 0.72:
            status = "✓ 盈" if r["is_win"] else "✗ 亏"
            print(f"  {status} {r['symbol']:12s} score={r['score']:.3f}  "
                  f"pnl={r['pnl_pct']:+.4f}  exit={r['exit_reason']}")
    
    print("\n决策建议：")
    if wr >= 0.80:
        print("  ✅ WR >= 80%：这 32 个候选整体质量足够，支持完全移除 veto。")
    elif wr >= 0.70:
        print("  ⚠️ WR 70-80%：支持移除 veto + 50% 仓位缩减（C 组配置）。")
    else:
        print("  ❌ WR < 70%：不支持完全移除 veto，改为后置过滤（threshold_check 之后）。")


if __name__ == "__main__":
    config = {
        "stop_loss_pct":   0.02,
        "take_profit_pct": 0.04,
    }
    results = replay_blocked_signals(
        blocked_signals=BLOCKED_SIGNALS,
        kline_cache_path="data/klines/",
        config=config,
        forward_bars=16,
    )
    summarize_replay(results)
    
    # 保存原始结果供后续分析
    out_path = Path("output/analysis/vol_vwap_blocked_replay_20260502.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n原始结果已保存至：{out_path}")
```

---

## 8. 其他三个关联问题的建议

### 8.1 `weight_15m_entry = 0.00` 问题

```
当前状态：
  weight_15m_entry = 0.00
  15m 在评分上完全不贡献正值，只负责否决（rsi_extreme_veto）
  
问题：
  一个评分系统中有一个维度权重=0，
  意味着 15m 信号的"质量"在选股排名中毫无作用。
  只有当 15m RSI 极端时才有否决权，这是不对称的设计。
  
建议（独立消融，不和 vol_vwap_both_low 同批跑）：
  第二批消融：weight_15m_entry 从 0.00 调到 0.05
  对应下调：weight_vwap 从 0.05 到 0.00，或 weight_volume 从 0.10 到 0.05
  
  调整后总权重验证：
    weight_4h_direction  = 0.40
    weight_rsi_rhythm    = 0.30
    weight_1h_direction  = 0.15
    weight_volume        = 0.10  （或 0.05）
    weight_vwap          = 0.05  （或 0.00）
    weight_15m_entry     = 0.05  （从 0.00 提升）
    合计                 = 1.05  ← 需要重新归一化
    
  归一化后：
    weight_4h_direction  = 0.381
    weight_rsi_rhythm    = 0.286
    weight_1h_direction  = 0.143
    weight_volume        = 0.095
    weight_vwap          = 0.048
    weight_15m_entry     = 0.048
    合计                 = 1.001（舍入）
```

### 8.2 `vwap_hard_block` 拆分建议

```
当前 VWAP 的双重职责：
  职责 1：vwap_hard_block — VWAP 价格偏离过大时硬阻断（位置风险）
  职责 2：volume_vwap_both_low — 低 vwap 评分 + 低 volume 评分时 veto（流动性风险）

移除 both_low 后，职责 2 转入执行层（仓位缩减）。
职责 1（vwap_hard_block）继续保留，不变。

建议：在配置中明确注释区分两者语义，避免后续运维混淆：
```

```diff
  # config/trading_config_fund_flow.json
  "vwap_gates": {
    "_comment": "VWAP 相关门控分两类，语义不同，不可混淆",
    
    "vwap_hard_block_enabled": true,
    "vwap_hard_block_deviation_pct": 0.03,
    "_vwap_hard_block_purpose": "价格偏离 VWAP 超过阈值时硬阻断（位置风险控制）",
    
-   "volume_vwap_both_low_enabled": true,
-   "volume_vwap_both_low_min_score_vol": 0.05,
-   "volume_vwap_both_low_min_vwap_score": 0.10,
+   "volume_vwap_both_low_enabled": false,
+   "_volume_vwap_both_low_purpose": "已移除 veto，改为执行层仓位缩减。见 decision_engine.vol_vwap_warn_position_scale",
+   
+   "vol_vwap_warn_log_enabled": true,
+   "vol_vwap_warn_min_score_vol": 0.05,
+   "vol_vwap_warn_min_vwap_score": 0.10,
+   "_vol_vwap_warn_purpose": "低流动性状态记录（原 both_low 阈值复用），不再阻断，执行层缩仓"
  }
```

### 8.3 `primary_direction_timeframe = 4H` 在低波动窗口的补充

```
4H无明确方向占 31.4% 的 HOLD，在低波动 / 盘整窗口会进一步放大。

当前不建议修改 primary_direction_timeframe，理由：
  1. 归核化基线中 flip_bearish（100% WR）依赖 4H 方向确认
  2. 修改此参数影响面大，需要独立消融
  
短期缓解方案（不改主逻辑的情况下）：
  在 4H 无明确方向时，允许 1H 方向明确 + 4H 非反向进入"trial"模式
  trial 模式：仓位 = 正常仓位 × 0.25，信号类型标记为 trial
  
这是下一轮（vol_vwap 消融结果稳定后）的独立议题，本文不展开 DIFF。
```

---

## 9. 监控指标（移除后 live 观察清单）

```python
# 移除 volume_vwap_both_low 后，live 监控必须新增以下指标

LIVE_MONITORING_CHECKLIST = {
    
    # ── 核心：移除效果是否达到预期 ──────────────────────────────────────────
    "vol_vwap_warn_trade_count_per_cycle": {
        "description": "每个 15m 周期中 vol_vwap_warn 信号成交数",
        "alert_if":    "过去 48 个周期 > 10 笔，说明低流动性市场下过度开仓",
        "alert_level": "WARNING",
    },
    "vol_vwap_warn_trade_wr_rolling_30": {
        "description": "过去 30 笔 vol_vwap_warn 成交的滚动 WR",
        "alert_if":    "< 0.70（低于 70%）",
        "alert_level": "CRITICAL — 考虑恢复 veto 或降低 scale_factor 到 0.25",
    },
    "vol_vwap_warn_trade_mdd_contribution": {
        "description": "vol_vwap_warn 成交单对总 MDD 的贡献（需权益曲线分析）",
        "alert_if":    "超过总 MDD 的 40%",
        "alert_level": "WARNING",
    },
    
    # ── 执行质量：仓位缩减是否正确触发 ────────────────────────────────────
    "vol_vwap_warn_position_scale_applied_pct": {
        "description": "vol_vwap_warn 信号中被缩仓的比例（应 = 100%）",
        "alert_if":    "< 95%（说明缩仓逻辑有 bug）",
        "alert_level": "CRITICAL",
    },
    
    # ── 原 veto 清零确认 ──────────────────────────────────────────────────
    "volume_vwap_both_low_hold_count_per_cycle": {
        "description": "每周期因 volume_vwap_both_low 产生的 HOLD 数（应 = 0）",
        "alert_if":    "> 0（说明旧代码路径仍被触发）",
        "alert_level": "CRITICAL — 配置未生效，检查 volume_vwap_both_low_enabled",
    },
    
    # ── 总体开仓频率 ──────────────────────────────────────────────────────
    "decision_buy_sell_rate_per_cycle": {
        "description": "每周期产生 BUY/SELL decision 的比例",
        "alert_if":    "< 0.02 （连续 24 个周期都低于 2%，说明仍有未知阻断）",
        "alert_level": "WARNING",
    },
    "hold_reason_distribution_shift": {
        "description": "HOLD 原因分布变化监控",
        "expected_after_removal": {
            "volume_vwap_both_low": "消失",
            "4H无明确方向":         "仍存在，预计占比上升到 45-55%（因 both_low 移除）",
            "vwap_hard_block":      "仍存在，预计占比上升到 18-25%",
            "score_below_threshold":"应上升（原先被 both_low 提前拦截的低分单，现在走到 threshold_check）",
        },
    },
}
```

---

## 10. 执行顺序速查

```
立即（2026-05-02）：
  □ 运行 replay_vol_vwap_blocked_signals_20260502.py
    → 对 32 个历史被阻断候选做离线回放
    → 如果 WR >= 70%，确认移除方向正确
  
  □ 实现代码修改（6 个文件）：
    1. src/fund_flow/macd_strategy_v2.py  — 移除 veto 块，加 _record_vol_vwap_warn
    2. src/fund_flow/decision_engine.py   — 加 vol_vwap_warn 仓位缩减
    3. src/fund_flow/attribution_writer.py — 更新诊断字段
    4. config/trading_config_fund_flow.json — 配置 DIFF
    5. tests/test_volume_vwap_veto_removal.py — 新增单测（本文 Section 5）
    6. scripts/run_vol_vwap_ablation_20260502.py — 消融脚本
  
  □ 运行单测：
    pytest tests/test_volume_vwap_veto_removal.py -v
    → 预期 18 个用例全部通过
  
下一步（单测通过后）：
  □ 运行消融 A 组（基线 rerun，确认环境）
  □ 运行消融 B 组（移除 veto，无缩仓）
  □ 用决策规则判断是否推进 C 组
  □ C 组通过后：更新 live 配置，开启 12 小时 live 观察

Live 观察通过后：
  □ 与 Round 1 退出修复合并（两个修改方向互不干扰）
  □ 一起跑 30d strict-live rerun
```

---

## 11. 风险告知（必须在改之前确认）

```
风险 1：低流动性市场的追单损耗
  场景：vol_vwap_warn 信号在实际流动性不足时，IOC 大概率被取消
  缓解：仓位缩减到 50%，IOC 取消后 fallback 门槛 0.88（P1-B 已配置）
  监控：vol_vwap_warn 信号的 IOC cancel_rate（单独统计）

风险 2：VWAP 低评分暗示价格在 VWAP 不利侧
  场景：vwap_score 低可能意味着价格远离 VWAP，存在均值回归风险
  缓解：vwap_hard_block 处理的是价格偏离（保留），
         vwap_score 低只是评分贡献少，不代表价格位置危险
  确认：确认 vwap_score 的定义——是"价格与 VWAP 的距离评分"还是"VWAP 斜率评分"
         如果是前者，需要和 vwap_hard_block 做阈值校对，避免双重宽松

风险 3：回测样本有限
  当前 30d 样本（2026-02-23 ~ 2026-03-24）中 vol_vwap_both_low 触发频次未知
  需要从历史 attribution.jsonl 统计这段窗口内 both_low 的命中次数和信号质量
  如果历史样本中 both_low 命中的信号 WR < 70%，需要降低缩仓比例到 0.30

风险 4：移除后开仓频率可能大幅增加
  实盘窗口 589 次 both_low HOLD = 47.2% 的 HOLD 总量
  移除后这些候选会进入 threshold_check
  但大多数 score 低于 0.68（只有 32 个 score >= 0.68）
  实际新增成交预计 5-15 笔/月，不是 589 笔全部放行
  验证：消融 B/C 组的 trades 数与基线对比
```

---

*文档生成：2026-05-02*
*基于日志产物：fund_flow_attribution.jsonl 2026-05-01~02*
*基于代码位置：macd_strategy_v2.py:4566-4583 / decision_engine.py:4387-4391*
*下次更新节点：离线回放脚本结果 + 消融 A/B 组产物产出后*
