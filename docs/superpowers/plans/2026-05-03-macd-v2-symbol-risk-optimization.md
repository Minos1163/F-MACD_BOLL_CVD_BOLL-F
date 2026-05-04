# MACD V2 Symbol Risk Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the next strategy optimization cycle by validating and, if justified, promoting ADA/FET symbol risk control, then preparing the next symbol-scoped risk experiments from the validated candidate baseline.

**Architecture:** Treat `F2_blacklist_ada_fet` as a candidate, not production, until longer-window and cross-period checks pass. Keep changes surgical: first add reproducible validation tooling, then run gated backtests, then update only `fund_flow.symbol_blacklist` if the evidence passes. Do not bundle global stop changes, light TP changes, capacity changes, or IOC/GTC changes.

**Tech Stack:** Python scripts, JSON config, CSV backtest artifacts, `scripts/backtest_macd_v2.py`, `scripts/run_macd_v2_return_ablation.py`, `pytest`.

---

## File Map

- Modify: `docs/2026-05-03_macd_v2_high_winrate_low_return_review_packet.md`
  - Append final validation results, deployment decision, and next experiment status after commands run.
- Create: `scripts/summarize_backtest_symbol_pnl.py`
  - Small CSV utility to summarize net PnL, trade count, win rate, worst loss, and average PnL by symbol from one or more backtest trade CSVs.
- Create: `tests/test_summarize_backtest_symbol_pnl.py`
  - Unit tests for the summary utility using temporary CSV fixtures.
- Modify only if validation passes: `config/trading_config_fund_flow.json`
  - Append `ADAUSDT` and `FETUSDT` to `fund_flow.symbol_blacklist`.
- Create only if validation passes: `config/candidates/trading_config_fund_flow_post_ada_fet_20260503.json`
  - Snapshot of the validated production candidate for future SS/LT experiments.
- Do not modify in this plan: `src/fund_flow/macd_strategy_v2.py`
  - Symbol-scoped stop overrides are future work unless SS experiments prove they are needed and the code path is explicitly implemented.
- Do not modify in this plan: `src/app/fund_flow_bot.py`
  - Current live stack reads config through `decision_engine.py`; first verify behavior before changing runtime code.

## Success Gates

- Gate 1: 60d candidate validation passes.
  - `win_rate >= 90%`
  - `profit_factor >= 4.0`
  - `max_drawdown <= 7%`
  - `total_trades` materially exceeds the 30d candidate sample of `153`
  - Return is directionally strong for 60d; target `>= +60%`, but review if slightly below with clearly improved PF/MDD versus baseline.
- Gate 2: ADA/FET cross-period validation passes.
  - ADA+FET combined net PnL is negative in at least `2/3` tested windows, or one symbol is consistently negative enough to justify blacklisting that symbol alone.
- Gate 3: Candidate config diff is clean.
  - Only `fund_flow.symbol_blacklist` changes for deployment.
- Gate 4: Verification passes.
  - `python -m py_compile scripts\backtest_macd_v2.py scripts\run_macd_v2_return_ablation.py scripts\audit_backtest_stop_losses.py scripts\summarize_backtest_symbol_pnl.py`
  - `pytest tests\test_summarize_backtest_symbol_pnl.py -q`

## Task 1: Add Symbol PnL Summary Utility

**Files:**
- Create: `scripts/summarize_backtest_symbol_pnl.py`
- Create: `tests/test_summarize_backtest_symbol_pnl.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_summarize_backtest_symbol_pnl.py`:

```python
import csv
from pathlib import Path

from scripts.summarize_backtest_symbol_pnl import summarize_files


def _write_trades(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "symbol",
        "pnl",
        "entry_price",
        "exit_price",
        "side",
        "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_summarize_files_groups_symbol_metrics(tmp_path: Path) -> None:
    trades = tmp_path / "trades.csv"
    _write_trades(
        trades,
        [
            {"symbol": "ADAUSDT", "pnl": "-10", "entry_price": "1.00", "exit_price": "0.95", "side": "long", "reason": "stop"},
            {"symbol": "ADAUSDT", "pnl": "4", "entry_price": "1.00", "exit_price": "1.02", "side": "long", "reason": "tp"},
            {"symbol": "FETUSDT", "pnl": "-2", "entry_price": "2.00", "exit_price": "1.98", "side": "long", "reason": "stop"},
        ],
    )

    rows = summarize_files([trades])

    ada = next(row for row in rows if row["symbol"] == "ADAUSDT")
    fet = next(row for row in rows if row["symbol"] == "FETUSDT")

    assert ada["trades"] == 2
    assert ada["wins"] == 1
    assert ada["losses"] == 1
    assert ada["net_pnl"] == -6.0
    assert ada["win_rate_pct"] == 50.0
    assert ada["worst_pnl"] == -10.0
    assert ada["worst_price_pnl_pct"] == -5.0

    assert fet["trades"] == 1
    assert fet["net_pnl"] == -2.0
    assert fet["worst_price_pnl_pct"] == -1.0


def test_summarize_files_can_filter_symbols(tmp_path: Path) -> None:
    trades = tmp_path / "trades.csv"
    _write_trades(
        trades,
        [
            {"symbol": "ADAUSDT", "pnl": "-10", "entry_price": "1.00", "exit_price": "0.95", "side": "long", "reason": "stop"},
            {"symbol": "SOLUSDT", "pnl": "30", "entry_price": "10.00", "exit_price": "10.50", "side": "long", "reason": "tp"},
        ],
    )

    rows = summarize_files([trades], symbols={"ADAUSDT"})

    assert [row["symbol"] for row in rows] == ["ADAUSDT"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests\test_summarize_backtest_symbol_pnl.py -q
```

Expected: FAIL because `scripts.summarize_backtest_symbol_pnl` does not exist.

- [ ] **Step 3: Implement the summary utility**

Create `scripts/summarize_backtest_symbol_pnl.py`:

```python
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _price_pnl_pct(row: dict[str, str]) -> float:
    entry = _to_float(row.get("entry_price"))
    exit_price = _to_float(row.get("exit_price"))
    if entry <= 0:
        return 0.0
    side = str(row.get("side") or "long").lower()
    if side == "short":
        return ((entry - exit_price) / entry) * 100.0
    return ((exit_price - entry) / entry) * 100.0


def summarize_files(paths: Iterable[Path], symbols: set[str] | None = None) -> list[dict[str, float | int | str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    symbol_filter = {s.upper() for s in symbols} if symbols else None

    for path in paths:
        with Path(path).open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                symbol = str(row.get("symbol") or "").upper()
                if not symbol:
                    continue
                if symbol_filter is not None and symbol not in symbol_filter:
                    continue
                grouped[symbol].append(row)

    summaries: list[dict[str, float | int | str]] = []
    for symbol, rows in grouped.items():
        pnls = [_to_float(row.get("pnl")) for row in rows]
        price_pnls = [_price_pnl_pct(row) for row in rows]
        wins = sum(1 for pnl in pnls if pnl > 0)
        losses = sum(1 for pnl in pnls if pnl <= 0)
        trades = len(rows)
        summaries.append(
            {
                "symbol": symbol,
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": (wins / trades * 100.0) if trades else 0.0,
                "net_pnl": round(sum(pnls), 6),
                "avg_pnl": round((sum(pnls) / trades), 6) if trades else 0.0,
                "worst_pnl": round(min(pnls), 6) if pnls else 0.0,
                "worst_price_pnl_pct": round(min(price_pnls), 6) if price_pnls else 0.0,
            }
        )

    return sorted(summaries, key=lambda row: float(row["net_pnl"]))


def write_csv(rows: list[dict[str, float | int | str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "trades",
        "wins",
        "losses",
        "win_rate_pct",
        "net_pnl",
        "avg_pnl",
        "worst_pnl",
        "worst_price_pnl_pct",
    ]
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize MACD V2 backtest trade PnL by symbol.")
    parser.add_argument("trades_csv", nargs="+", type=Path)
    parser.add_argument("--symbols", nargs="*", default=None, help="optional symbol filter, e.g. ADAUSDT FETUSDT")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    rows = summarize_files(args.trades_csv, symbols=set(args.symbols or []) or None)
    if args.output:
        write_csv(rows, args.output)
    else:
        import sys

        fieldnames = [
            "symbol",
            "trades",
            "wins",
            "losses",
            "win_rate_pct",
            "net_pnl",
            "avg_pnl",
            "worst_pnl",
            "worst_price_pnl_pct",
        ]
        stdout_writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        stdout_writer.writeheader()
        stdout_writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and compile**

Run:

```bash
pytest tests\test_summarize_backtest_symbol_pnl.py -q
python -m py_compile scripts\summarize_backtest_symbol_pnl.py
```

Expected: tests pass and py_compile exits 0.

## Task 2: Run 60d Baseline and Candidate Validation

**Files:**
- Read: `config/trading_config_fund_flow.json`
- Read: `config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json`
- Output: `output/backtest/validation_60d_20260503/*`

- [ ] **Step 1: Run 60d production baseline**

Run:

```bash
python scripts\backtest_macd_v2.py --config config\trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2026-03-04 --end 2026-05-03 --output-prefix output\backtest\validation_60d_20260503\baseline_60d --initial-capital 10000
```

Expected: creates `output\backtest\validation_60d_20260503\baseline_60d_summary.json` and `baseline_60d_trades.csv`.

- [ ] **Step 2: Run 60d ADA/FET blacklist candidate**

Run:

```bash
python scripts\backtest_macd_v2.py --config config\candidates\trading_config_fund_flow_blacklist_ada_fet_20260503.json --strict-live-mode --simulate-live-close-layers --start 2026-03-04 --end 2026-05-03 --output-prefix output\backtest\validation_60d_20260503\candidate_blacklist_ada_fet_60d --initial-capital 10000
```

Expected: creates `output\backtest\validation_60d_20260503\candidate_blacklist_ada_fet_60d_summary.json` and `candidate_blacklist_ada_fet_60d_trades.csv`.

- [ ] **Step 3: Summarize 60d ADA/FET contribution in baseline**

Run:

```bash
python scripts\summarize_backtest_symbol_pnl.py output\backtest\validation_60d_20260503\baseline_60d_trades.csv --symbols ADAUSDT FETUSDT --output output\backtest\validation_60d_20260503\baseline_60d_ada_fet_symbol_pnl.csv
```

Expected: output CSV shows ADA/FET 60d trade count and net PnL.

- [ ] **Step 4: Compare 60d metrics**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

base = json.loads(Path("output/backtest/validation_60d_20260503/baseline_60d_summary.json").read_text(encoding="utf-8"))
cand = json.loads(Path("output/backtest/validation_60d_20260503/candidate_blacklist_ada_fet_60d_summary.json").read_text(encoding="utf-8"))
keys = ["return_pct", "win_rate_pct", "profit_factor", "total_trades"]
print("metric,baseline,candidate,delta")
for key in keys:
    b = float(base.get(key, 0))
    c = float(cand.get(key, 0))
    print(f"{key},{b:.6f},{c:.6f},{c-b:.6f}")
b_mdd = float(base.get("risk_metrics", {}).get("max_drawdown_pct", base.get("max_drawdown_pct", 0)))
c_mdd = float(cand.get("risk_metrics", {}).get("max_drawdown_pct", cand.get("max_drawdown_pct", 0)))
print(f"max_drawdown_pct,{b_mdd:.6f},{c_mdd:.6f},{c_mdd-b_mdd:.6f}")
PY
```

Expected: candidate should improve or preserve risk-adjusted performance versus 60d baseline.

- [ ] **Step 5: Gate decision**

Accept the 60d candidate only if:

```text
candidate win_rate_pct >= 90
candidate profit_factor >= 4
candidate max_drawdown_pct <= 7
candidate total_trades > 153
candidate return_pct is materially better than 60d baseline, or has clearly lower MDD and higher PF with acceptable return
```

If this fails, stop before production config changes and document the failure in the review packet.

## Task 3: Run Cross-Period ADA/FET Attribution

**Files:**
- Output: `output/backtest/validation_periods_20260503/*`
- Output: `output/backtest/validation_periods_20260503/*_ada_fet_symbol_pnl.csv`

- [ ] **Step 1: Run Q4 2025 baseline window**

Run:

```bash
python scripts\backtest_macd_v2.py --config config\trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2025-10-01 --end 2025-12-31 --output-prefix output\backtest\validation_periods_20260503\baseline_q4_2025 --initial-capital 10000
```

Expected: if data exists, creates `baseline_q4_2025_trades.csv`. If the command reports missing coverage, record that and use the available cached period instead of fabricating results.

- [ ] **Step 2: Summarize Q4 2025 ADA/FET**

Run:

```bash
python scripts\summarize_backtest_symbol_pnl.py output\backtest\validation_periods_20260503\baseline_q4_2025_trades.csv --symbols ADAUSDT FETUSDT --output output\backtest\validation_periods_20260503\baseline_q4_2025_ada_fet_symbol_pnl.csv
```

Expected: CSV exists if the Q4 backtest produced trades.

- [ ] **Step 3: Run Q1 2026 baseline window**

Run:

```bash
python scripts\backtest_macd_v2.py --config config\trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --start 2026-01-01 --end 2026-03-31 --output-prefix output\backtest\validation_periods_20260503\baseline_q1_2026 --initial-capital 10000
```

Expected: creates `baseline_q1_2026_trades.csv` if data coverage supports the period.

- [ ] **Step 4: Summarize Q1 2026 ADA/FET**

Run:

```bash
python scripts\summarize_backtest_symbol_pnl.py output\backtest\validation_periods_20260503\baseline_q1_2026_trades.csv --symbols ADAUSDT FETUSDT --output output\backtest\validation_periods_20260503\baseline_q1_2026_ada_fet_symbol_pnl.csv
```

Expected: CSV exists if the Q1 backtest produced trades.

- [ ] **Step 5: Summarize current 30d baseline ADA/FET**

Run:

```bash
python scripts\summarize_backtest_symbol_pnl.py output\backtest\live_strict_30d_20260503_trades.csv --symbols ADAUSDT FETUSDT --output output\backtest\validation_periods_20260503\baseline_30d_ada_fet_symbol_pnl.csv
```

Expected: CSV confirms current-window ADA/FET contribution.

- [ ] **Step 6: Gate decision**

Accept hard blacklist only if ADA/FET combined net PnL is negative in at least `2/3` available periods. If only one symbol is consistently bad, deploy only that symbol. If neither is consistently bad outside current 30d, stop and plan dynamic risk-tier logic instead.

## Task 4: Verify Config Diff and Live Gating Path

**Files:**
- Read: `config/trading_config_fund_flow.json`
- Read: `config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json`
- Read: `src/fund_flow/decision_engine.py`

- [ ] **Step 1: Verify candidate config only changes expected symbol blacklist**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

prod = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
cand = json.loads(Path("config/candidates/trading_config_fund_flow_blacklist_ada_fet_20260503.json").read_text(encoding="utf-8"))

prod_list = prod["fund_flow"]["symbol_blacklist"]
cand_list = cand["fund_flow"]["symbol_blacklist"]
extra = sorted(set(cand_list) - set(prod_list))
missing = sorted(set(prod_list) - set(cand_list))

print("extra_symbols", extra)
print("missing_symbols", missing)
if extra != ["ADAUSDT", "FETUSDT"] or missing:
    raise SystemExit("candidate blacklist diff is not clean")
PY
```

Expected:

```text
extra_symbols ['ADAUSDT', 'FETUSDT']
missing_symbols []
```

- [ ] **Step 2: Verify live decision engine maps `fund_flow.symbol_blacklist` to `NO_TRADE`**

Run:

```bash
Select-String -Path src\fund_flow\decision_engine.py -Pattern 'raw_blacklist = ff_cfg.get\("symbol_blacklist"|overrides\[symbol_up\] = "NO_TRADE"' -Context 0,2
```

Expected: shows `raw_blacklist = ff_cfg.get("symbol_blacklist", [])` and `overrides[symbol_up] = "NO_TRADE"`.

## Task 5: Promote ADA/FET Symbol Control If Gates Pass

**Files:**
- Modify: `config/trading_config_fund_flow.json`
- Create: `config/candidates/trading_config_fund_flow_post_ada_fet_20260503.json`

- [ ] **Step 1: Edit production config only after Task 2, Task 3, and Task 4 pass**

Modify `config/trading_config_fund_flow.json` under `fund_flow.symbol_blacklist` by appending:

```json
      "ADAUSDT",
      "FETUSDT"
```

Keep the existing blacklist entries unchanged. Do not change `risk`, stop settings, light TP settings, capacity, execution, or thresholds.

- [ ] **Step 2: Create validated candidate snapshot**

Copy the resulting production config to:

```text
config/candidates/trading_config_fund_flow_post_ada_fet_20260503.json
```

The file should match production config after the blacklist edit.

- [ ] **Step 3: Run production-config backtest verification**

Run:

```bash
python scripts\backtest_macd_v2.py --config config\trading_config_fund_flow.json --strict-live-mode --simulate-live-close-layers --output-prefix output\backtest\production_blacklist_ada_fet_20260503 --initial-capital 10000
```

Expected: metrics match the verified candidate within normal determinism:

```text
return_pct ~= 35.2316
win_rate_pct ~= 94.1176
profit_factor ~= 13.5797
max_drawdown_pct ~= 3.2189
```

- [ ] **Step 4: Run compile and focused tests**

Run:

```bash
python -m py_compile scripts\backtest_macd_v2.py scripts\run_macd_v2_return_ablation.py scripts\audit_backtest_stop_losses.py scripts\summarize_backtest_symbol_pnl.py
pytest tests\test_summarize_backtest_symbol_pnl.py -q
```

Expected: all commands pass.

## Task 6: Document Final Decision and Evidence

**Files:**
- Modify: `docs/2026-05-03_macd_v2_high_winrate_low_return_review_packet.md`

- [ ] **Step 1: Add validation results**

Append a section named:

```markdown
## 10. Final Validation And Deployment Decision
```

Include:

```markdown
| Check | Result | Decision |
|---|---|---|
| 60d candidate validation | `<fill actual metrics>` | pass/fail |
| ADA/FET cross-period PnL | `<fill actual period results>` | pass/fail |
| candidate config diff | only `fund_flow.symbol_blacklist += ADA/FET` | pass/fail |
| production backtest after promotion | `<fill actual metrics>` | pass/fail |
```

- [ ] **Step 2: Record the exact decision**

Write one of these exact conclusions:

```markdown
Decision: Promote `ADAUSDT` and `FETUSDT` to production `fund_flow.symbol_blacklist`.
```

or:

```markdown
Decision: Do not hard-blacklist both symbols. Use the validation findings to design symbol risk-tier throttles instead.
```

- [ ] **Step 3: Verify no stale recommendations remain**

Run:

```bash
Select-String -Path docs\2026-05-03_macd_v2_high_winrate_low_return_review_packet.md -Pattern 'global hard stop|disable light|max_active_symbols|IOC|GTC|symbol_blacklist'
```

Expected: closed directions remain closed; only ADA/FET symbol risk control is presented as the production-sized change.

## Task 7: Prepare Next SS/LT Experiments Without Deploying Them

**Files:**
- Modify: `scripts/run_macd_v2_return_ablation.py` only if needed
- Do not modify production config

- [ ] **Step 1: Check whether existing ablation script can run from candidate baseline**

Run:

```bash
python scripts\run_macd_v2_return_ablation.py --help
```

Expected: understand whether it supports a custom base config. If it does not, plan a small follow-up patch adding `--base-config` before SS/LT experiments.

- [ ] **Step 2: Do not implement symbol-scoped stop config until code support exists**

Before any SS case using `symbol_risk_overrides`, verify with:

```bash
Select-String -Path scripts\backtest_macd_v2.py,src\fund_flow\macd_strategy_v2.py -Pattern 'symbol_risk_overrides|max_stop_loss_pct'
```

Expected: if `symbol_risk_overrides` is absent, do not create config-only SS cases. Add a separate implementation plan for symbol-scoped stop support.

- [ ] **Step 3: If F2 is promoted, run only already-supported LT variants later**

Supported current knobs include:

```text
risk.conflict_protection.light_take_profit_max_adx_1h
risk.conflict_protection.light_take_profit_max_signal_score
risk.conflict_protection.light_take_profit_pct
```

Run LT only after F2 is the accepted baseline. Reject any LT result that drops below:

```text
win_rate < 90%
profit_factor < 5.0
max_drawdown > 5.5%
```

## Self-Review

- Spec coverage: The plan covers the requested continuation path: 60d validation, cross-period ADA/FET attribution, gated deployment, and deferred SS/LT experiments.
- Placeholder scan: No task uses TBD/TODO. Every command and expected result is explicit. Actual metrics are intentionally filled only after the command runs.
- Type consistency: The plan uses the real config field `fund_flow.symbol_blacklist`, not `risk.symbol_blacklist`. The live gating path is verified in `src/fund_flow/decision_engine.py`.
