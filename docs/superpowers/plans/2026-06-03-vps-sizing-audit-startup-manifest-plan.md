# VPS Sizing Audit Startup Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop watchlist/direct-open candidates from reaching execution with `target_portion=0.0`, make effective entry thresholds auditable, and print enough startup version/config data to verify VPS deployment.

**Architecture:** Keep the existing quadrant direction and entry models unchanged. Add a final non-zero fallback at the watchlist sizing boundary, expose the real `effective_open_min` bucket in audit metadata, and print a startup manifest from `TradingBot` after config/runtime log setup. Parameter relaxation is intentionally last.

**Tech Stack:** Python, pytest, existing `FundFlowDecisionEngine`, `QuadrantResonanceConfig`, `TradingBot` runtime logging.

---

### Task 1: Verify Local Version State

**Files:**
- Read only: git state and `config/trading_config_fund_flow.json`

- [ ] **Step 1: Run local version checks**

Run:

```powershell
git log --oneline -3
rg -n "entry_15m_quality_model|watchlist_direct_open_enabled|ema_conflict_entry_penalty" config\trading_config_fund_flow.json src\fund_flow src\app tests -S
git status --short --branch
```

Expected:

- Latest committed code may still be `3bbb0fc`.
- `entry_15m_quality_model="structural_v2"` is present in the local working tree.
- There are uncommitted strategy/config changes, so VPS git-pull deployment would not receive them until committed/pushed.

### Task 2: Watchlist Sizing Fallback

**Files:**
- Modify: `src/fund_flow/quadrant_resonance.py`
- Modify: `src/fund_flow/decision_engine.py`
- Test: `tests/test_quadrant_resonance.py`

- [ ] **Step 1: Add failing tests**

Add tests that assert:

```python
def test_watchlist_base_portion_falls_back_when_equity_missing():
    engine = _decision_engine_with_quadrant_config({
        "watchlist_fallback_min_portion": 0.033,
        "high_score_probe_portion": 0.042,
    })

    portion = engine._quadrant_watchlist_base_portion(metadata={}, leverage=3)

    assert portion == pytest.approx(0.033)
```

and:

```python
def test_watchlist_promoted_signal_never_returns_zero_target_portion():
    engine = _decision_engine_with_quadrant_config({
        "watchlist_fallback_min_portion": 0.033,
        "watchlist_promoted_portion_mult": 0.75,
    })
    signal = SimpleNamespace(
        direction="long",
        target_portion=0.0,
        leverage=3,
        atr_stop_distance=0.0,
        quadrant=Quadrant.Q1,
        resonance_score=0.0,
        threshold=0.0,
        factor_scores={},
        take_profit_levels=[],
    )

    promoted = engine._quadrant_watchlist_promoted_signal(
        symbol="HYPEUSDT",
        price=10.0,
        signal=signal,
        review={"result": "promoted_direct", "side": "long", "base_portion": 0.0, "portion_multiplier": 0.75},
        metadata={},
    )

    assert promoted is not None
    assert promoted.target_portion > 0.0
    assert promoted.metadata["watchlist_sizing_fallback_applied"] is True
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
pytest tests/test_quadrant_resonance.py -k "watchlist_base_portion_falls_back_when_equity_missing or watchlist_promoted_signal_never_returns_zero_target_portion" -q
```

Expected: FAIL because missing equity currently returns `0.0`.

- [ ] **Step 3: Implement minimal sizing fallback**

Add config field:

```python
watchlist_fallback_min_portion: float = 0.033
```

Parse it from `entry`.

Change `_quadrant_watchlist_base_portion()`:

```python
if equity <= 0.0:
    return max(0.0, self._to_float(getattr(cfg, "watchlist_fallback_min_portion", 0.033), 0.033))
```

In `_quadrant_watchlist_promoted_signal()`, if target remains `<= 0`, force the same fallback and add audit metadata:

```python
metadata["watchlist_sizing_fallback_applied"] = True
metadata["watchlist_sizing_fallback_reason"] = "target_portion_non_positive"
```

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command. Expected: PASS.

### Task 3: Entry Effective Threshold Audit

**Files:**
- Modify: `src/fund_flow/quadrant_resonance.py`
- Test: `tests/test_quadrant_resonance.py`

- [ ] **Step 1: Add failing test**

Add a test that builds an analysis path where `entry_15m_quality_score >= open_min` but `< open_min + ema_conflict_entry_penalty`, and asserts metadata includes:

```python
assert metadata["ema_conflict"] is True
assert metadata["entry_15m_effective_open_min"] == pytest.approx(0.70)
assert metadata["entry_15m_quality_bucket_effective"] == "watch"
assert metadata["entry_15m_quality_bucket"] == "open"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
pytest tests/test_quadrant_resonance.py -k "effective_open_min" -q
```

Expected: FAIL because effective bucket/ema conflict audit is missing or incomplete.

- [ ] **Step 3: Implement audit fields**

In `QuadrantResonanceEngine.analyze()`, after computing `effective_open_min`, write:

```python
metadata["ema_conflict"] = bool(ema_conflict)
metadata["entry_15m_base_open_min"] = base_open_min
metadata["entry_15m_effective_open_min"] = effective_open_min
metadata["entry_15m_quality_bucket_effective"] = self._entry_quality_bucket_for_threshold(entry_score, effective_open_min)
```

Use the existing watch threshold for effective watch/hold split.

- [ ] **Step 4: Run test to verify GREEN**

Run the same pytest command. Expected: PASS.

### Task 4: Startup Manifest

**Files:**
- Modify: `src/app/fund_flow_bot.py`
- Test: `tests/test_quadrant_resonance.py` or focused runtime test if existing helper is available

- [ ] **Step 1: Add helper test**

Add a test for a pure helper that builds a manifest dict from config and config path:

```python
manifest = TradingBot._build_startup_manifest_static(config=config, config_path="config/trading_config_fund_flow.json")
assert manifest["event"] == "STARTUP_MANIFEST"
assert "config_hash" in manifest
assert manifest["quadrant_resonance"]["entry_15m_quality_model"] == "structural_v2"
```

- [ ] **Step 2: Run test to verify RED**

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Implement startup manifest**

Add static helper in `TradingBot`:

- `event`
- `git_commit`
- `git_dirty`
- `config_path`
- `config_hash`
- key quadrant settings: `entry_15m_quality_model`, `entry_15m_quality_open_min`, `entry_15m_quality_watch_min`, `watchlist_direct_open_enabled`, `watchlist_fallback_min_portion`, `ema_conflict_entry_penalty`

Call it once in `__init__` after runtime log sink is configured and before/around `_print_startup_summary()`:

```python
print("STARTUP_MANIFEST " + json.dumps(manifest, ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 4: Run test and py_compile**

Run:

```powershell
pytest tests/test_quadrant_resonance.py -k "startup_manifest" -q
python -m py_compile src\app\fund_flow_bot.py src\fund_flow\decision_engine.py src\fund_flow\quadrant_resonance.py
```

Expected: PASS.

### Task 5: Parameter Change Last

**Files:**
- Modify: `config/trading_config_fund_flow.json`
- Test: config grep

- [ ] **Step 1: Only after Tasks 1-4 pass, lower EMA conflict penalty**

Change:

```json
"ema_conflict_entry_penalty": 0.05
```

- [ ] **Step 2: Verify config**

Run:

```powershell
rg -n "ema_conflict_entry_penalty" config\trading_config_fund_flow.json tests src -S
```

Expected: live config shows `0.05`; tests that intentionally assert default parsing can keep `0.10`.

### Task 6: Final Verification

Run:

```powershell
pytest tests/test_quadrant_resonance.py -q
python -m py_compile src\app\fund_flow_bot.py src\fund_flow\decision_engine.py src\fund_flow\quadrant_resonance.py
git diff --stat
```

Expected:

- Targeted tests pass.
- No syntax errors.
- Diff is limited to plan, sizing/audit/manifest/config/tests.

