# Codex.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Do not assume. Do not hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop, name what is confusing, and ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility or configurability that was not requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Do not improve adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If unrelated dead code is noticed, mention it rather than deleting it.

When your changes create orphans:
- Remove imports, variables, and functions that your changes made unused.
- Do not remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

## Crypto Quant Trading Research Rules

This repository is for systematic crypto strategy research and live-trading support. Treat all strategy changes as risk-bearing unless proven otherwise.

## Mandatory Risk Rules

- Never introduce lookahead bias.
- Never use future candle data in entry, exit, sizing, risk, or regime logic.
- Never use repaint indicators for executable signals.
- Never assume same-bar fills for take profit, stop loss, entry, or exit.
- Entry and exit must be executable in live trading with known order timing.
- Do not modify live execution, live risk, or production config paths unless the task explicitly asks for live behavior changes.

## Backtest Standards

- Include fee simulation.
- Include slippage simulation.
- State latency or candle-close assumptions.
- Prefer strict live-mode backtests when comparing candidates to production behavior.
- Backtests must report, or explicitly explain missing:
  - Sharpe
  - Max drawdown
  - Win rate
  - Profit factor
  - Exposure
  - Trade count
  - Expectancy
  - Tail risk
  - MFE/MAE when trade-level data is available

## Strategy Standards

- Prefer robust strategies over overfit strategies.
- Avoid parameter explosion.
- Avoid curve fitting to a single symbol, date range, or market regime.
- Penalize low trade count systems.
- Validate symbol robustness and time robustness before treating a result as real alpha.
- Treat high backtest PnL with low trade count or high same-bar dependence as suspicious.

## Code Standards

All strategy logic must include, or explicitly preserve existing:
- stop loss
- take profit or exit logic
- position sizing
- risk cap
- fee and slippage assumptions in backtest paths

## Research Workflow

Before modifying strategy logic:
1. Explain the hypothesis.
2. Explain the expected market regime.
3. Explain the failure mode.
4. State the verification command or backtest window.

After backtest:
1. Explain why the strategy appeared to work or fail.
2. Explain risk exposure.
3. Explain possible overfit risks.
4. Compare against live-executable assumptions.

## Hook-Aware Workflow

- Treat `.codex/hooks/anti_future_leak.py` and `.codex/hooks/risk_guard.py` as hard guardrails.
- Treat `.codex/hooks/pre_backtest.py`, `.codex/hooks/metrics_check.py`, `.codex/hooks/pnl_sanity.py`, and `.codex/hooks/auto_journal.py` as the minimum audit loop after strategy edits.
- If Codex lifecycle hooks are unavailable on the current platform, manually run the same scripts before claiming a strategy change is safe.
