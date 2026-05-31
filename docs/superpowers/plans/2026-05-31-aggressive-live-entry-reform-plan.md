# Aggressive Live Entry Reform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move quadrant resonance from audit-only/dry-run behavior into a bounded live-entry test path for the 100U account while preserving max notional, max concurrent positions, and BNB fee controls.

**Architecture:** Keep the existing signal flow: `QuadrantResonanceEngine` produces `QuadrantSignal`, `FundFlowDecisionEngine` converts it to `FundFlowDecision`, and existing execution/risk gates remain downstream. The change activates existing quality/watchlist/recovering diagnostics as reduced-size live paths and downgrades selected probe vetoes to reduced-size entries rather than bypassing global risk caps.

**Tech Stack:** Python, pytest, JSON config, existing fund_flow strategy modules.

---

## Assumptions And Risk Frame

- User explicitly requested live behavior changes, so editing `config/trading_config_fund_flow.json` is in scope.
- No lookahead is introduced: all decisions use the current `timeframes` snapshot already supplied to live evaluation.
- Failure mode: reduced entries may increase churn or correlated losses; red-line caps and existing execution guards remain in force.
- Verification commands: `PYTHONPATH=. pytest tests/test_quadrant_resonance.py -q`, `PYTHONPATH=. pytest tests/test_fund_flow_bot_dual_leg_guard.py tests/test_fund_flow_risk_engine.py -q`, `python -m json.tool config/trading_config_fund_flow.json`, `.codex/hooks/anti_future_leak.py --all-changed`, `.codex/hooks/risk_guard.py`.

## Files

- Modify: `src/fund_flow/quadrant_resonance.py` for quality live entry, recovering reduced entries, and graded probe veto.
- Modify: `src/fund_flow/decision_engine.py` for watchlist direct promotion.
- Modify: `config/trading_config_fund_flow.json` for aggressive test-account parameters.
- Modify: `tests/test_quadrant_resonance.py` for signal-engine behavior tests.
- Modify: `tests/test_fund_flow_bot_dual_leg_guard.py` or existing decision tests only if direct watchlist promotion needs integration coverage.

### Task 1: Quality Live Entry

- [ ] Add failing tests showing `entry_15m_quality_mode=live` allows quality >= 0.70 even when legacy `entry_15m` is absent, creates watchlist intent for quality >= 0.50, and holds below 0.50.
- [ ] Implement minimal logic in `QuadrantResonanceEngine` so live quality mode treats `entry_15m_quality_score >= open_min` as satisfying the 15m entry gate.
- [ ] Preserve metadata fields: `entry_15m_quality_score`, `entry_15m_quality_bucket`, and legacy `entry_15m_detail`.
- [ ] Verify with targeted pytest.

### Task 2: Recovering Reduced Entry

- [ ] Add failing tests showing `quadrant_state=recovering` plus `score >= 0.80` returns allowed signal with `target_portion` multiplied by 0.50.
- [ ] Add failing tests showing recovering below threshold creates/keeps watchlist intent and defense remains hold.
- [ ] Implement config fields and branch without changing EMA-disorder defense.
- [ ] Verify with targeted pytest.

### Task 3: Graded Probe Veto

- [ ] Add failing tests for breadth weak half-size, direction-against under 0.8% quarter-size, direction-against at/over 0.8% reject, no 15m/1H momentum reject, and flow score > -0.30 quarter-size.
- [ ] Implement `_grade_probe_veto()` and route vetoed probe candidates through it when `probe_veto_graded_enabled=true`.
- [ ] Preserve hard rejects for both-timeframe no momentum and severe breadth/flow conflicts.
- [ ] Verify with targeted pytest.

### Task 4: Watchlist Direct Promotion

- [ ] Add integration test showing a stored quadrant watchlist candidate promotes directly when missing conditions are satisfied, even if the current standard signal is not already allowed.
- [ ] Implement direct promotion in `FundFlowDecisionEngine` when `watchlist_direct_open_enabled=true`.
- [ ] Ensure the generated decision still uses existing decision/execution path metadata and reduced `watchlist_promoted_portion_mult=0.75`.
- [ ] Verify with targeted pytest.

### Task 5: Live Config

- [ ] Update `fund_flow.quadrant_resonance.entry_filters` values requested by the user.
- [ ] Update `fund_flow.btc_beta_risk` values requested by the user.
- [ ] Confirm red lines are present and not loosened: max single notional <= 40U, max concurrent positions <= 4, BNB fee usage remains true where configured.
- [ ] Validate JSON.

### Task 6: Full Verification

- [ ] Run all quadrant tests.
- [ ] Run bot/risk regression tests.
- [ ] Run JSON validation.
- [ ] Run anti-future-leak and risk guard hooks, or report exact hook failure.
- [ ] Run `git diff --check` on changed files.
