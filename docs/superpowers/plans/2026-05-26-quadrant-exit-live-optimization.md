# Quadrant Exit Live Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize the `quadrant_resonance` strategy by tightening low-quality entries, replacing overly early intrabar exits with live-executable staged exits, validating by backtest, then applying the proven settings to live config.

**Architecture:** Keep `quadrant_resonance` as the single shared signal/exit engine for live and backtest. Backtest may add execution simulation switches, but production behavior must come from config-driven engine fields, not separate hard-coded backtest rules. Post-exit future bars remain audit-only.

**Tech Stack:** Python, `src/fund_flow/quadrant_resonance.py`, `scripts/backtest_macd_v2.py`, `src/fund_flow/decision_engine.py`, `config/trading_config_fund_flow.json`, pytest.

---

### Task 1: Entry Quality Filters

**Files:**
- Modify: `src/fund_flow/quadrant_resonance.py`
- Test: `tests/test_quadrant_resonance.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
def test_standard_quadrant_requires_entry_pattern_when_enabled() -> None:
    engine = _engine({"entry": {"standard_threshold": 0.85, "require_15m_entry_pattern": True}})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )
    assert result.allowed is False
    assert result.reason == "missing_15m_entry_pattern"

def test_mid_score_requires_three_1h_macd_bars_when_enabled() -> None:
    engine = _engine({"entry": {"standard_threshold": 0.85, "mid_score_requires_3bar_macd": True}})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(
            tf1h=_tf(macd_hist_series=[0.01, 0.02], rsi=55),
            tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02], rsi=55),
        ),
        portfolio={"equity": 100.0},
    )
    assert result.allowed is False
    assert result.reason == "mid_score_needs_3bar_macd"

def test_4h_rsi_extreme_penalty_applies_before_threshold() -> None:
    engine = _engine({"entry": {"standard_threshold": 0.95, "extreme_4h_rsi_penalty": 0.05}})
    result = engine.analyze(
        symbol="ICPUSDT",
        price=100.0,
        timeframes=_timeframes(q4h=_tf(rsi=75), tf15m=_tf(close=100, ema20=99.5, macd_hist_series=[-0.01, 0.02], rsi=55)),
        portfolio={"equity": 100.0},
    )
    assert result.allowed is True
    assert result.resonance_score == pytest.approx(0.95)
    assert result.metadata["extreme_4h_rsi_penalty"] == pytest.approx(0.05)
```

- [ ] **Step 2: Run red tests**

Run: `python -m pytest tests/test_quadrant_resonance.py::test_standard_quadrant_requires_entry_pattern_when_enabled tests/test_quadrant_resonance.py::test_mid_score_requires_three_1h_macd_bars_when_enabled tests/test_quadrant_resonance.py::test_4h_rsi_extreme_penalty_applies_before_threshold -q`

Expected: tests fail because fields and filters do not exist.

- [ ] **Step 3: Implement minimal fields and filters**

Add config fields:

```python
require_15m_entry_pattern: bool = False
mid_score_requires_3bar_macd: bool = False
mid_score_upper_bound: float = 0.90
extreme_4h_rsi_penalty: float = 0.0
long_4h_rsi_penalty_above: float = 70.0
short_4h_rsi_penalty_below: float = 30.0
```

Apply them inside `analyze()` after factor scoring and before threshold pass.

- [ ] **Step 4: Run green tests**

Run same command. Expected: PASS.

### Task 2: Exit Policy Engine

**Files:**
- Modify: `src/fund_flow/quadrant_resonance.py`
- Modify: `scripts/backtest_macd_v2.py`
- Test: `tests/test_quadrant_resonance.py`
- Test: `tests/test_backtest_review_followup.py`

- [ ] **Step 1: Write failing tests**

Tests must cover:

```python
def test_close_confirm_stop_does_not_exit_on_wick_only() -> None:
    engine = _engine({"exit": {"stop_trigger": "close_confirm", "hard_stop_atr_mult": 1.5}})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=99.2,
        timeframes={"15m": _tf(close=99.2, low=97.0, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"stage": "validation"},
    )
    assert result["action"] == "hold"

def test_close_confirm_stop_exits_on_close_breach() -> None:
    engine = _engine({"exit": {"stop_trigger": "close_confirm", "hard_stop_atr_mult": 1.5}})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=96.9,
        timeframes={"15m": _tf(close=96.9, low=96.8, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"stage": "validation"},
    )
    assert result["action"] == "close"
    assert result["reason"] == "HARD_STOP_LOSS_CLOSE_CONFIRMED"

def test_tp1_reduces_30_percent_and_moves_to_trend_stage() -> None:
    engine = _engine({"exit": {"tp1_atr_mult": 1.2, "tp1_reduce_pct": 0.30, "ema20_trailing_enabled": True}})
    result = engine.evaluate_exit(
        direction="long",
        entry_price=100.0,
        current_price=102.5,
        timeframes={"15m": _tf(close=102.5, high=102.5, atr=2.0), "1h": _tf(), "4h": _tf()},
        position={"tp1_done": False},
    )
    assert result == {"action": "reduce", "ratio": 0.30, "reason": "TP1_REDUCE_TO_EMA_TRAIL", "updates": {"tp1_done": True, "stage": "trend"}}
```

- [ ] **Step 2: Run red tests**

Run: `python -m pytest tests/test_quadrant_resonance.py tests/test_backtest_review_followup.py::test_quadrant_backtest_momentum_exit_reduces_position_once -q`

- [ ] **Step 3: Implement exit config**

Add config fields:

```python
stop_trigger: str = "intrabar"
tp1_atr_mult: float = 1.5
tp1_reduce_pct: float = 0.30
fast_validation_bars: int = 2
fast_validation_min_mfe: float = 0.005
fast_validation_mae_stop_fraction: float = 0.80
trend_trail_atr_mult: float = 2.0
momentum_reduce_pct_first: float = 0.25
momentum_reduce_pct_second: float = 0.50
trend_reduce_pct: float = 0.50
```

`evaluate_exit()` returns updates for position state. `scripts/backtest_macd_v2.py` applies those updates after reduce/close.

- [ ] **Step 4: Run green tests**

Run focused tests. Expected: PASS.

### Task 3: Backtest Comparison and 100U Validation

**Files:**
- Modify: `scripts/backtest_macd_v2.py` only if needed for reporting
- Output: `output/backtest/quadrant_resonance_exit_opt_*`

- [ ] **Step 1: Run current-window 10000U optimized backtest**

Run:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strategy quadrant_resonance --strict-live-mode --simulate-live-close-layers --start 2026-05-01T00:00:00 --end 2026-05-24T14:00:00 --output-prefix output/backtest/quadrant_resonance_exit_opt_10000u
```

- [ ] **Step 2: Run current-window 100U optimized backtest**

Run:

```bash
python scripts/backtest_macd_v2.py --config config/trading_config_fund_flow.json --strategy quadrant_resonance --strict-live-mode --simulate-live-close-layers --initial-capital 100 --max-positions 5 --start 2026-05-01T00:00:00 --end 2026-05-24T14:00:00 --output-prefix output/backtest/quadrant_resonance_exit_opt_100u
```

- [ ] **Step 3: Compare against baseline**

Acceptance for applying live config:

- 10000U return not worse than baseline by more than 20% relative.
- `stop_loss_intrabar` net loss reduced by at least 30%, or replaced by close-confirm reasons with lower total loss.
- `stopped_before_followthrough` ratio below baseline 87.8%.
- 100U run has at least 50 trade rows and no sub-1U opening margin.

### Task 4: Live Config Rollout

**Files:**
- Modify: `config/trading_config_fund_flow.json`
- Verify: `scripts/pre_live_assertions.py`
- Verify: `scripts/verify_deployment.py`

- [ ] **Step 1: Apply only validated config values**

If Task 3 passes, set:

```json
"standard_threshold": 0.85,
"require_15m_entry_pattern": true,
"mid_score_requires_3bar_macd": true,
"extreme_4h_rsi_penalty": 0.05,
"hard_stop_atr_mult": 1.5,
"stop_trigger": "close_confirm",
"tp1_atr_mult": 1.2,
"tp1_reduce_pct": 0.30,
"ema20_trailing_enabled": true,
"fast_validation_bars": 2,
"fast_validation_min_mfe": 0.005,
"trend_trail_atr_mult": 2.0,
"momentum_reduce_pct_first": 0.25
```

For 100U live:

```json
"min_entry_notional_usdt": 8.0,
"max_active_symbols": 5,
"drawdown_halve_at_pct": 0.10,
"drawdown_restore_at_pct": 0.05
```

- [ ] **Step 2: Run live checks**

Run:

```bash
python scripts/pre_live_assertions.py --config config/trading_config_fund_flow.json
python scripts/verify_deployment.py --config config/trading_config_fund_flow.json
python -m py_compile src/fund_flow/quadrant_resonance.py scripts/backtest_macd_v2.py src/fund_flow/decision_engine.py src/app/fund_flow_bot.py
```

Expected: all exit 0.

### Task 5: Review Document

**Files:**
- Create: `docs/2026-05-26_quadrant_resonance_exit_optimization_result_for_deepseek.md`

- [ ] **Step 1: Write result report**

Include:

- Baseline vs optimized 10000U metrics.
- Optimized 100U metrics.
- Exit reason breakdown.
- stopped_before_followthrough comparison.
- Whether live config was applied.
- Remaining risks.

---

## Self-Review

Spec coverage:

- Entry threshold/shape/RSI recommendations: Task 1.
- Close-confirm stop, ATR 1.5, TP1 partial, EMA trail, fast validation: Task 2.
- 10000U and 100U backtests: Task 3.
- Live config after validation: Task 4.
- DeepSeek report: Task 5.

Known deliberate deferrals:

- Downloading one year of data is not included in this code task because the user asked to modify, backtest, and deploy now; the report must still state cached data limitations.
- External news/blacklist APIs remain out of scope.
