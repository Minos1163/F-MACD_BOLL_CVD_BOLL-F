# Tighten Short Entry Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten MACD V2 short-entry gating so low-quality `SHORT` and `flip_bearish` setups fail earlier, remain probe-only when `RSI_1h < 40`, and require meaningful 15m confirmation before a 4H bearish flip can dominate scoring.

**Architecture:** Keep the change surgical inside the existing MACD V2 engine. Add short-side-specific config fields and resolver helpers in `MACDStrategyV2Config` and `MACDStrategyV2Engine`, then thread them through runtime config loading without changing unrelated long-side behavior. Implement the new guards in the existing score assembly path so the same rejection metadata, probe sizing, and backtest/live config plumbing continue to work.

**Tech Stack:** Python, pytest, existing MACD V2 strategy engine, JSON runtime config.

---

## File Map

**Modify:**
- `src/fund_flow/macd_strategy_v2.py`
  Responsibility: strategy config defaults, VWAP floor resolution, RSI rhythm probe behavior, 4H/15m score assembly, short-entry gating details.
- `src/fund_flow/decision_engine.py`
  Responsibility: load the new short-entry guard config fields from runtime config into `MACDStrategyV2Config`.
- `config/trading_config_fund_flow.json`
  Responsibility: live/default runtime values for the new short-entry guard fields and updated `weight_15m_entry`.
- `tests/test_macd_strategy_v2_4h_scoring.py`
  Responsibility: focused engine-level tests for VWAP floor resolution, RSI probe-only behavior, 4H bearish flip gating, and 15m scoring participation.
- `tests/test_fund_flow_decision_engine.py`
  Responsibility: config propagation assertions for the new fields and updated defaults.
- `tests/test_backtest_profiles.py`
  Responsibility: live config/profile expectation updates so runtime defaults match the new short-entry guard policy.

**No new production modules are required.** Keep this change inside existing files.

## Design Decisions Locked For Implementation

- Short-side VWAP tightening is side-specific. Preserve the current long-side `flip_bullish` exemption unless a later spec explicitly changes it.
- Replace the blanket flip exemption behavior with a helper that can distinguish:
  - long `flip_bullish`
  - short `flip_bearish`
  - non-flip signals
  - trial entries
- For this feature, use:
  - normal short minimum VWAP score: `0.06`
  - `flip_bearish` short minimum VWAP score: `0.08`
- `RSI_1h < 40` on short setups means probe-only sizing, not full rejection.
- `4H flip_bearish` no longer receives automatic full `weight_4h_direction` unless at least one of these is true:
  - `is_4h_enhanced` or `enhancement_score > 0`
  - 15m confirmation is meaningful
- “Meaningful 15m confirmation” for this change means existing bearish-friendly 15m entry/refine signals already present in the engine:
  - `entry_type_15m in {"flip_bearish", "green_bar_growing", "rsi_spring", "rsi_neutral_resume"}`
  - or `entry_score_15m > 0`
- `weight_15m_entry` should become a real additive score term and should also be visible in `details["score_15m"]`.
- Do not introduce a new subsystem or broad refactor. Reuse existing `probe_mode`, `rsi_exposure_mult`, `entry_type_15m`, and rejection-detail plumbing.

## Verification Strategy

- Run narrow pytest targets after each small behavior change.
- End with the three touched suites:
  - `pytest tests/test_macd_strategy_v2_4h_scoring.py -q`
  - `pytest tests/test_fund_flow_decision_engine.py -q`
  - `pytest tests/test_backtest_profiles.py -q`
- If any pre-existing unrelated failure appears, document it before proceeding further.

### Task 1: Add Failing Tests For Short-Side VWAP Floors

**Files:**
- Modify: `tests/test_macd_strategy_v2_4h_scoring.py`
- Modify: `src/fund_flow/macd_strategy_v2.py:972-980`

- [ ] **Step 1: Write the failing tests for short-side VWAP floor resolution**

```python
def test_flip_bearish_short_uses_stricter_vwap_floor_even_when_flip_exemption_enabled() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.10,
            preflip_trial_min_vwap_score=0.06,
            enable_vwap_flip_exemption=True,
        )
    )

    assert engine._resolve_min_vwap_score_for_entry(
        trade_direction="short",
        signal_type_1h="flip_bearish",
        is_trial_entry=False,
    ) == pytest.approx(0.08, rel=1e-6)


def test_non_flip_short_uses_short_floor_before_global_floor() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.10,
            preflip_trial_min_vwap_score=0.06,
            enable_vwap_flip_exemption=True,
        )
    )

    assert engine._resolve_min_vwap_score_for_entry(
        trade_direction="short",
        signal_type_1h="green_bar_growing",
        is_trial_entry=False,
    ) == pytest.approx(0.06, rel=1e-6)


def test_flip_bullish_long_keeps_existing_flip_exemption_behavior() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            min_vwap_score_for_entry=0.10,
            preflip_trial_min_vwap_score=0.06,
            enable_vwap_flip_exemption=True,
        )
    )

    assert engine._resolve_min_vwap_score_for_entry(
        trade_direction="long",
        signal_type_1h="flip_bullish",
        is_trial_entry=False,
    ) == pytest.approx(0.0, rel=1e-6)
```

- [ ] **Step 2: Run the targeted tests and confirm they fail on the current resolver signature/behavior**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "vwap_floor or flip_signals_skip_vwap_score_floor" -q`

Expected: FAIL because `_resolve_min_vwap_score_for_entry()` does not yet accept `trade_direction`, and current `flip_bearish` behavior returns `0.0`.

- [ ] **Step 3: Implement the minimal resolver change in `src/fund_flow/macd_strategy_v2.py`**

```python
def _resolve_min_vwap_score_for_entry(
    self,
    *,
    trade_direction: Optional[str],
    signal_type_1h: Optional[str],
    is_trial_entry: bool,
) -> float:
    direction = str(trade_direction or "").strip().lower()
    signal_type = str(signal_type_1h or "").strip().lower()

    if is_trial_entry:
        return float(self.config.preflip_trial_min_vwap_score)

    if direction == "long":
        if self.config.enable_vwap_flip_exemption and signal_type == "flip_bullish":
            return 0.0
        return float(self.config.min_vwap_score_for_entry)

    if direction == "short":
        if signal_type == "flip_bearish":
            return 0.08
        return 0.06

    if self.config.enable_vwap_flip_exemption and signal_type in {"flip_bullish", "flip_bearish"}:
        return 0.0
    return float(self.config.min_vwap_score_for_entry)
```

- [ ] **Step 4: Update the call site that applies the VWAP score filter**

```python
min_vwap_score_for_entry = max(
    0.0,
    self._resolve_min_vwap_score_for_entry(
        trade_direction=trade_direction,
        signal_type_1h=signal_type_1h,
        is_trial_entry=is_trial_entry,
    ),
)
```

- [ ] **Step 5: Re-run the targeted tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "vwap_floor or flip_signals_skip_vwap_score_floor" -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_macd_strategy_v2_4h_scoring.py src/fund_flow/macd_strategy_v2.py
git commit -m "test: lock short-side vwap entry floors"
```

### Task 2: Replace Hardcoded Short Floors With Config Fields And Propagation Tests

**Files:**
- Modify: `src/fund_flow/macd_strategy_v2.py`
- Modify: `src/fund_flow/decision_engine.py`
- Modify: `config/trading_config_fund_flow.json`
- Modify: `tests/test_fund_flow_decision_engine.py`
- Modify: `tests/test_backtest_profiles.py`

- [ ] **Step 1: Write failing config propagation tests**

```python
def test_macd_v2_live_defaults_include_short_vwap_floor_and_15m_weight() -> None:
    cfg = _cfg()
    cfg["fund_flow"]["strategy_mode"] = "macd_mtf_strategy_v2"
    cfg["fund_flow"]["macd_mtf_strategy_v2"] = {}

    engine = FundFlowDecisionEngine(cfg)

    assert engine.macd_v2_config.weight_15m_entry == pytest.approx(0.05, rel=1e-6)
    assert engine.macd_v2_config.short_min_vwap_score_for_entry == pytest.approx(0.06, rel=1e-6)
    assert engine.macd_v2_config.flip_bearish_short_min_vwap_score_for_entry == pytest.approx(0.08, rel=1e-6)
```

```python
def test_live_runtime_config_uses_short_entry_guard_defaults() -> None:
    runtime_cfg = _load_live_runtime_config()
    v2_cfg = runtime_cfg["fund_flow"]["macd_mtf_strategy_v2"]

    assert v2_cfg["scoring_weights"]["weight_15m_entry"] == 0.05
    assert v2_cfg["entry_filters"]["short_min_vwap_score_for_entry"] == 0.06
    assert v2_cfg["entry_filters"]["flip_bearish_short_min_vwap_score_for_entry"] == 0.08
```

- [ ] **Step 2: Run the propagation/profile tests to verify they fail**

Run: `pytest tests/test_fund_flow_decision_engine.py -k "short_vwap_floor or live_defaults" -q`

Run: `pytest tests/test_backtest_profiles.py -k "short_entry_guard_defaults or live_runtime_config_uses_rsi_rhythm_defaults" -q`

Expected: FAIL because the config dataclass, loader, and runtime JSON do not yet define these fields and still expect `weight_15m_entry == 0.0`.

- [ ] **Step 3: Add the minimal config fields to `MACDStrategyV2Config`**

```python
weight_15m_entry: float = 0.05
short_min_vwap_score_for_entry: float = 0.06
flip_bearish_short_min_vwap_score_for_entry: float = 0.08
short_rsi_probe_only_below: float = 40.0
flip_bearish_require_enhancement_or_15m_confirmation: bool = True
```

- [ ] **Step 4: Replace the hardcoded numbers from Task 1 with config-backed values**

```python
if direction == "short":
    if signal_type == "flip_bearish":
        return float(self.config.flip_bearish_short_min_vwap_score_for_entry)
    return float(self.config.short_min_vwap_score_for_entry)
```

- [ ] **Step 5: Load the new config fields in `src/fund_flow/decision_engine.py`**

```python
weight_15m_entry=self._to_float(weights_cfg.get("weight_15m_entry"), 0.05),
short_min_vwap_score_for_entry=self._to_float(
    filter_cfg.get("short_min_vwap_score_for_entry"),
    0.06,
),
flip_bearish_short_min_vwap_score_for_entry=self._to_float(
    filter_cfg.get("flip_bearish_short_min_vwap_score_for_entry"),
    0.08,
),
short_rsi_probe_only_below=self._to_float(
    rsi_cfg.get("short_rsi_probe_only_below"),
    40.0,
),
flip_bearish_require_enhancement_or_15m_confirmation=bool(
    filter_cfg.get("flip_bearish_require_enhancement_or_15m_confirmation", True)
),
```

- [ ] **Step 6: Update the live/default runtime config values in `config/trading_config_fund_flow.json`**

```json
"scoring_weights": {
  "weight_15m_entry": 0.05
},
"entry_filters": {
  "min_vwap_score_for_entry": 0.0,
  "short_min_vwap_score_for_entry": 0.06,
  "flip_bearish_short_min_vwap_score_for_entry": 0.08,
  "flip_bearish_require_enhancement_or_15m_confirmation": true
},
"rsi_config": {
  "short_rsi_probe_only_below": 40.0
}
```

- [ ] **Step 7: Re-run the propagation/profile tests**

Run: `pytest tests/test_fund_flow_decision_engine.py -k "short_vwap_floor or live_defaults" -q`

Run: `pytest tests/test_backtest_profiles.py -k "short_entry_guard_defaults or live_runtime_config_uses_rsi_rhythm_defaults" -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/fund_flow/macd_strategy_v2.py src/fund_flow/decision_engine.py config/trading_config_fund_flow.json tests/test_fund_flow_decision_engine.py tests/test_backtest_profiles.py
git commit -m "feat: add config-backed short entry guard defaults"
```

### Task 3: Make `RSI_1h < 40` Force Probe-Only Short Sizing

**Files:**
- Modify: `tests/test_macd_strategy_v2_4h_scoring.py`
- Modify: `src/fund_flow/macd_strategy_v2.py:1445-1653`

- [ ] **Step 1: Write the failing engine-level RSI rhythm test**

```python
def test_evaluate_rsi_rhythm_short_below_40_forces_probe_mode_without_hard_veto() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            enable_rsi_rhythm_scoring=True,
            rsi_rhythm_block_score=-0.30,
            short_rsi_probe_only_below=40.0,
        )
    )

    result = engine.evaluate_rsi_rhythm(
        direction="short",
        rsi_15m_series=np.array([58.0, 61.0, 63.0, 60.0]),
        rsi_1h_series=np.array([46.0, 43.0, 39.5, 38.5]),
        rsi_4h_series=np.array([52.0, 49.0, 46.0, 43.0]),
        close_15m_series=np.array([101.0, 100.8, 100.6, 100.4]),
        close_1h_series=np.array([102.0, 101.5, 101.0, 100.5]),
        close_4h_series=np.array([104.0, 103.0, 102.0, 101.0]),
        macd_hist_1h_current=-0.08,
    )

    assert result["hard_veto"] is False
    assert result["probe_mode"] is True
    assert result["exposure_mult"] == pytest.approx(engine.config.rsi_probe_exposure_mult, rel=1e-6)
```

- [ ] **Step 2: Write the failing analyze-path sizing test**

```python
def test_analyze_short_below_40_marks_probe_mode_in_final_details() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.15,
            weight_4h_direction=0.40,
            weight_vwap=0.05,
            weight_15m_entry=0.05,
            weight_volume=0.10,
            flip_bearish_min_signal_score=0.66,
            min_signal_score=0.66,
            min_vwap_score_for_entry=0.0,
            short_min_vwap_score_for_entry=0.06,
            flip_bearish_short_min_vwap_score_for_entry=0.08,
            disable_green_bar_growing_entries=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.08, 0.03, -0.02, -0.05]),
        macd_hist_1h=np.array([0.10, 0.04, -0.01, -0.06]),
        macd_hist_4h=np.array([0.12, 0.08, 0.02, -0.03]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=1.8,
        vwap=100.0,
        structural_vwap=100.4,
        close_price=99.7,
        bb_middle_1h=100.2,
        bb_upper_1h=102.0,
        bb_lower_1h=98.0,
        bb_middle_4h=100.8,
        bb_upper_4h=103.0,
        bb_lower_4h=98.5,
        bb_middle_15m=100.0,
        bb_upper_15m=100.8,
        bb_lower_15m=99.2,
        close_15m=99.7,
        adx_1h=28.0,
        adx_4h=26.0,
        atr_1h=0.9,
        rsi_15m=np.array([58.0, 61.0, 63.0, 60.0]),
        rsi_1h=np.array([46.0, 43.0, 39.5, 38.5]),
        rsi_4h=np.array([52.0, 49.0, 46.0, 43.0]),
    )

    assert signal.direction == "short"
    assert signal.details["rsi_probe_mode"] is True
```

- [ ] **Step 3: Run the new RSI tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "probe_mode and below_40" -q`

Expected: FAIL because short-side `RSI_1h < 40` currently has no dedicated probe-only forcing logic.

- [ ] **Step 4: Implement the minimal short-side probe-only logic in `evaluate_rsi_rhythm()`**

```python
if (
    direction == "short"
    and np.isfinite(current_rsi_1h)
    and current_rsi_1h < float(self.config.short_rsi_probe_only_below)
):
    result["probe_mode"] = True
    result["exposure_mult"] = min(
        float(result.get("exposure_mult", 1.0)),
        float(self.config.rsi_probe_exposure_mult),
    )
```

- [ ] **Step 5: Preserve existing veto behavior while making the probe flag flow through final details**

```python
rsi_probe_mode = self._resolve_effective_probe_mode(
    signal_type_1h,
    bool(rsi_rhythm.get("probe_mode", False)),
)
```

Expected: no new code is needed if the existing final-detail plumbing already reads `rsi_probe_mode`; only verify that the new branch sets `probe_mode` early enough.

- [ ] **Step 6: Re-run the RSI tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "probe_mode and below_40" -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_macd_strategy_v2_4h_scoring.py src/fund_flow/macd_strategy_v2.py
git commit -m "feat: force probe-only short entries below 1h rsi 40"
```

### Task 4: Gate 4H `flip_bearish` So It Needs Enhancement Or 15m Confirmation

**Files:**
- Modify: `tests/test_macd_strategy_v2_4h_scoring.py`
- Modify: `src/fund_flow/macd_strategy_v2.py:4342-4399`

- [ ] **Step 1: Write the failing 4H bearish flip gating tests**

```python
def test_flip_bearish_4h_no_longer_gets_full_weight_without_enhancement_or_15m_confirmation() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.15,
            weight_4h_direction=0.40,
            weight_4h_enhancement=0.10,
            weight_vwap=0.05,
            weight_15m_entry=0.05,
            weight_volume=0.10,
            min_signal_score=0.66,
            flip_bearish_min_signal_score=0.66,
            min_vwap_score_for_entry=0.0,
            short_min_vwap_score_for_entry=0.06,
            flip_bearish_short_min_vwap_score_for_entry=0.08,
            disable_green_bar_growing_entries=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.06, 0.02, -0.01, -0.02]),
        macd_hist_1h=np.array([0.08, 0.03, -0.01, -0.04]),
        macd_hist_4h=np.array([0.12, 0.05, 0.01, -0.02]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=1.4,
        vwap=100.0,
        structural_vwap=100.2,
        close_price=99.8,
        bb_middle_1h=100.1,
        bb_upper_1h=101.5,
        bb_lower_1h=98.8,
        bb_middle_4h=100.6,
        bb_upper_4h=102.5,
        bb_lower_4h=98.9,
        bb_middle_15m=100.0,
        bb_upper_15m=100.6,
        bb_lower_15m=99.4,
        close_15m=99.8,
        adx_1h=24.0,
        adx_4h=22.0,
        atr_1h=0.7,
    )

    assert signal.details["signal_type_4h"] == "flip_bearish"
    assert signal.details["score_4h_base"] < pytest.approx(0.40, rel=1e-6)
```

```python
def test_flip_bearish_4h_keeps_full_weight_when_15m_confirmation_exists() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.15,
            weight_4h_direction=0.40,
            weight_4h_enhancement=0.10,
            weight_vwap=0.05,
            weight_15m_entry=0.05,
            weight_volume=0.10,
            min_signal_score=0.66,
            flip_bearish_min_signal_score=0.66,
            min_vwap_score_for_entry=0.0,
            short_min_vwap_score_for_entry=0.06,
            flip_bearish_short_min_vwap_score_for_entry=0.08,
            disable_green_bar_growing_entries=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.12, 0.08, 0.02, -0.04]),
        macd_hist_1h=np.array([0.10, 0.05, 0.01, -0.05]),
        macd_hist_4h=np.array([0.14, 0.07, 0.02, -0.03]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=1.8,
        vwap=100.0,
        structural_vwap=100.4,
        close_price=99.6,
        bb_middle_1h=100.0,
        bb_upper_1h=101.8,
        bb_lower_1h=98.6,
        bb_middle_4h=100.7,
        bb_upper_4h=102.8,
        bb_lower_4h=98.7,
        bb_middle_15m=100.0,
        bb_upper_15m=100.8,
        bb_lower_15m=99.2,
        close_15m=99.6,
        adx_1h=28.0,
        adx_4h=24.0,
        atr_1h=0.8,
    )

    assert signal.details["entry_type_15m"] in {"green_bar_growing", "rsi_spring", "rsi_neutral_resume", "flip_bearish"}
    assert signal.details["score_4h_base"] == pytest.approx(0.40, rel=1e-6)
```

- [ ] **Step 2: Run the gating tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "flip_bearish_4h and confirmation" -q`

Expected: FAIL because current code always assigns full `weight_4h_direction` to `4H flip_bearish`.

- [ ] **Step 3: Add a focused helper for bearish 15m confirmation**

```python
def _has_meaningful_short_15m_confirmation(
    self,
    *,
    trade_direction: str,
    entry_type_15m: Optional[str],
    entry_score_15m: float,
) -> bool:
    if str(trade_direction or "").strip().lower() != "short":
        return False

    entry_type = str(entry_type_15m or "").strip().lower()
    if entry_type in {"flip_bearish", "green_bar_growing", "rsi_spring", "rsi_neutral_resume"}:
        return True
    return float(entry_score_15m or 0.0) > 0
```

- [ ] **Step 4: Apply the helper to the 4H base score assembly**

```python
meaningful_short_15m_confirmation = self._has_meaningful_short_15m_confirmation(
    trade_direction=trade_direction,
    entry_type_15m=entry_type_15m,
    entry_score_15m=entry_score_15m,
)

elif direction_4h == trade_direction and signal_type_4h in ["flip_bullish", "flip_bearish"]:
    score_4h_base = self.config.weight_4h_direction
    if (
        trade_direction == "short"
        and signal_type_4h == "flip_bearish"
        and self.config.flip_bearish_require_enhancement_or_15m_confirmation
        and not is_4h_enhanced
        and enhancement_score <= 0
        and not meaningful_short_15m_confirmation
    ):
        score_4h_base = self.config.weight_4h_direction * 0.5
```

- [ ] **Step 5: Surface the gating state in `details` for later auditability**

```python
'meaningful_short_15m_confirmation': meaningful_short_15m_confirmation,
'flip_bearish_4h_guard_applied': bool(
    trade_direction == "short"
    and signal_type_4h == "flip_bearish"
    and self.config.flip_bearish_require_enhancement_or_15m_confirmation
    and not is_4h_enhanced
    and enhancement_score <= 0
    and not meaningful_short_15m_confirmation
),
```

- [ ] **Step 6: Re-run the gating tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "flip_bearish_4h and confirmation" -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_macd_strategy_v2_4h_scoring.py src/fund_flow/macd_strategy_v2.py
git commit -m "feat: gate 4h flip bearish on enhancement or 15m confirmation"
```

### Task 5: Make `weight_15m_entry` Participate In Entry Filtering

**Files:**
- Modify: `tests/test_macd_strategy_v2_4h_scoring.py`
- Modify: `src/fund_flow/macd_strategy_v2.py:4399-4405`

- [ ] **Step 1: Write the failing 15m score contribution tests**

```python
def test_weight_15m_entry_adds_real_score_component() -> None:
    engine = MACDStrategyV2Engine(
        MACDStrategyV2Config(
            weight_1h_direction=0.15,
            weight_4h_direction=0.40,
            weight_vwap=0.05,
            weight_15m_entry=0.05,
            weight_volume=0.10,
            min_signal_score=0.66,
            flip_bearish_min_signal_score=0.66,
            min_vwap_score_for_entry=0.0,
            short_min_vwap_score_for_entry=0.06,
            flip_bearish_short_min_vwap_score_for_entry=0.08,
            disable_green_bar_growing_entries=False,
        )
    )

    signal = engine.analyze(
        macd_hist_15m=np.array([0.10, 0.05, 0.01, -0.06]),
        macd_hist_1h=np.array([0.12, 0.06, 0.01, -0.05]),
        macd_hist_4h=np.array([0.15, 0.08, 0.02, -0.04]),
        idx_15m=3,
        idx_1h=3,
        idx_4h=3,
        volume_ratio=1.8,
        vwap=100.0,
        structural_vwap=100.5,
        close_price=99.5,
        bb_middle_1h=100.1,
        bb_upper_1h=101.7,
        bb_lower_1h=98.4,
        bb_middle_4h=100.8,
        bb_upper_4h=102.9,
        bb_lower_4h=98.6,
        bb_middle_15m=100.0,
        bb_upper_15m=100.8,
        bb_lower_15m=99.1,
        close_15m=99.5,
        adx_1h=29.0,
        adx_4h=25.0,
        atr_1h=0.8,
    )

    assert signal.details["score_15m"] > 0.0
```

```python
def test_weight_15m_entry_can_be_the_difference_between_pass_and_reject() -> None:
    base_config = MACDStrategyV2Config(
        weight_1h_direction=0.15,
        weight_4h_direction=0.40,
        weight_vwap=0.05,
        weight_volume=0.10,
        min_signal_score=0.70,
        flip_bearish_min_signal_score=0.70,
        min_vwap_score_for_entry=0.0,
        short_min_vwap_score_for_entry=0.06,
        flip_bearish_short_min_vwap_score_for_entry=0.08,
        disable_green_bar_growing_entries=False,
    )

    no_15m = MACDStrategyV2Engine(dataclasses.replace(base_config, weight_15m_entry=0.0))
    with_15m = MACDStrategyV2Engine(dataclasses.replace(base_config, weight_15m_entry=0.05))

    no_15m_signal = no_15m.analyze(...)
    with_15m_signal = with_15m.analyze(...)

    assert no_15m_signal.direction == "neutral"
    assert with_15m_signal.direction == "short"
```

- [ ] **Step 2: Run the targeted 15m tests**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "weight_15m_entry" -q`

Expected: FAIL because `score_15m` is currently hardcoded to `0.0`.

- [ ] **Step 3: Implement the minimal 15m scoring contribution**

```python
score_15m = 0.0
if self.config.weight_15m_entry > 0:
    score_15m = min(
        self.config.weight_15m_entry,
        max(0.0, float(entry_score_15m or 0.0)) * self.config.weight_15m_entry,
    )
    if score_15m == 0.0 and self._has_meaningful_short_15m_confirmation(
        trade_direction=trade_direction,
        entry_type_15m=entry_type_15m,
        entry_score_15m=entry_score_15m,
    ):
        score_15m = self.config.weight_15m_entry
score += score_15m
```

- [ ] **Step 4: Verify `details["score_15m"]` now reflects the added term**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "weight_15m_entry" -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_macd_strategy_v2_4h_scoring.py src/fund_flow/macd_strategy_v2.py
git commit -m "feat: restore 15m entry weighting in short entry score"
```

### Task 6: Update Runtime/Profile Expectations And Run Full Relevant Suites

**Files:**
- Modify: `tests/test_backtest_profiles.py`
- Modify: `tests/test_fund_flow_decision_engine.py`
- Modify: `config/trading_config_fund_flow.json`

- [ ] **Step 1: Update stale assertions that still lock the old defaults**

```python
assert v2_cfg["scoring_weights"]["weight_15m_entry"] == 0.05
assert v2_cfg["entry_filters"]["short_min_vwap_score_for_entry"] == 0.06
assert v2_cfg["entry_filters"]["flip_bearish_short_min_vwap_score_for_entry"] == 0.08
assert strategy_config.weight_15m_entry == pytest.approx(0.05, rel=1e-6)
```

- [ ] **Step 2: Run the full strategy scoring suite**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -q`

Expected: PASS.

- [ ] **Step 3: Run the config propagation suite**

Run: `pytest tests/test_fund_flow_decision_engine.py -q`

Expected: PASS.

- [ ] **Step 4: Run the profile/defaults suite**

Run: `pytest tests/test_backtest_profiles.py -q`

Expected: PASS.

- [ ] **Step 5: If all three suites pass, commit the expectation updates**

```bash
git add tests/test_backtest_profiles.py tests/test_fund_flow_decision_engine.py config/trading_config_fund_flow.json
git commit -m "test: align runtime defaults with tightened short entry guards"
```

### Task 7: Final Verification And Push Readiness

**Files:**
- Modify: none

- [ ] **Step 1: Run the exact final verification commands**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -q`

Run: `pytest tests/test_fund_flow_decision_engine.py -q`

Run: `pytest tests/test_backtest_profiles.py -q`

Expected: all PASS.

- [ ] **Step 2: Inspect the final diff**

Run: `git diff --stat HEAD~4..HEAD`

Expected: only the intended strategy, config, and test files changed.

- [ ] **Step 3: Inspect the branch state**

Run: `git status --short`

Expected: clean working tree.

- [ ] **Step 4: Optional targeted regression sanity check against the original ICP failure mode**

Run: `pytest tests/test_macd_strategy_v2_4h_scoring.py -k "flip_bearish or weight_15m_entry or probe_mode" -q`

Expected: PASS.

- [ ] **Step 5: Commit only if a final meta-commit is still needed**

```bash
git status --short
```

Expected: no output. If empty, do not create another commit.

## Self-Review

- Spec coverage:
  - `SHORT` VWAP floor `>= 0.06/0.08`: covered in Tasks 1-2.
  - `RSI_1h < 40` probe-only short: covered in Task 3.
  - `4H flip_bearish` no longer gets free `0.40`: covered in Task 4.
  - `weight_15m_entry` materially participates: covered in Task 5.
  - runtime/default config expectation updates: covered in Tasks 2 and 6.
- Placeholder scan:
  - No `TODO`, `TBD`, or “similar to Task N” placeholders remain.
  - One test snippet intentionally uses `analyze(...)` shorthand in Task 5 Step 1 for duplication control; replace it during implementation by copying the concrete analyze payload from the first test in that step and only changing the engine config between the two assertions.
- Type consistency:
  - New proposed config names are consistent across plan sections:
    - `short_min_vwap_score_for_entry`
    - `flip_bearish_short_min_vwap_score_for_entry`
    - `short_rsi_probe_only_below`
    - `flip_bearish_require_enhancement_or_15m_confirmation`

