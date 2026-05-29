# Quadrant Live EMA Field Contract Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复实盘 `quadrant_resonance` 因 4H `ema20`/`ema50` 缺失而永久进入 DEFENSE 的字段契约 BUG。

**Architecture:** 在实盘 flow context 合成层统一把旧 EMA 字段别名标准化成 `ema20`/`ema50`/`ema200`，让新四象限引擎收到与回测一致的字段。四象限引擎只增强缺失审计粒度，不放宽任何入场、仓位、风控或执行逻辑。

**Tech Stack:** Python、`src/app/fund_flow_bot.py`、`src/fund_flow/quadrant_resonance.py`、pytest。

---

### Task 1: Add Regression Tests

**Files:**
- Modify: `tests/test_fund_flow_bot_dual_leg_guard.py`
- Modify: `tests/test_quadrant_resonance.py`

- [ ] **Step 1: Add timeframe alias mapping test**

Add a test that feeds `_apply_timeframe_context()` live-like `trend_filters_by_timeframe` data containing `ema_fast`/`ema_slow` and `ema21`/`ema55`, then asserts `timeframes[*].ema20/ema50/ema200` are positive.

- [ ] **Step 2: Add no-overwrite test**

Add a test that confirms exact positive `ema20`/`ema50` fields are not overwritten by alias fields.

- [ ] **Step 3: Add missing indicator detail test**

Update the missing 4H indicator test to expect `missing_indicators_multiple` plus `missing_indicator_fields`.

### Task 2: Implement Minimal Fix

**Files:**
- Modify: `src/app/fund_flow_bot.py`
- Modify: `src/fund_flow/quadrant_resonance.py`

- [ ] **Step 1: Normalize EMA aliases in live flow context**

In `_apply_timeframe_context()`, after merging timeframe dictionaries, normalize:

```python
ema20 <- ema20, ema_20, ema_fast, ema21
ema50 <- ema50, ema_50, ema_slow, ema55
ema200 <- ema200, ema_200
```

Keep existing positive exact fields. Only copy positive numeric aliases.

- [ ] **Step 2: Refine missing audit detail**

In `_quadrant_debug()`, emit `missing_indicators_ema20`, `missing_indicators_ema50`, `missing_indicators_ema200`, `missing_indicators_macd_hist`, or `missing_indicators_multiple`, and include `missing_indicator_fields`.

### Task 3: Verify Live Safety

**Files:**
- No code edits.

- [ ] **Step 1: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_quadrant_resonance.py tests/test_fund_flow_bot_dual_leg_guard.py -q --basetemp D:\AIDCA\AI2\.pytest_tmp_quadrant_fix
```

- [ ] **Step 2: Compile touched modules**

Run:

```powershell
python -m py_compile src/fund_flow/quadrant_resonance.py src/app/fund_flow_bot.py src/fund_flow/decision_engine.py
```

- [ ] **Step 3: Run live guard scripts**

Run:

```powershell
python scripts/pre_live_assertions.py --config config/trading_config_fund_flow.json
python scripts/verify_deployment.py --config config/trading_config_fund_flow.json
```
