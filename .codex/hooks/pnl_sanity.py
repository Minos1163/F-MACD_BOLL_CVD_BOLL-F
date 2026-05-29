from __future__ import annotations

import argparse
import json
import math

from _common import extract_metrics, latest_backtest_summary, write_state


def main() -> int:
    parser = argparse.ArgumentParser(description="Run basic PnL sanity checks on the latest backtest summary.")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    summary_path = latest_backtest_summary()
    if summary_path is None:
        write_state("last_pnl_sanity.json", {"passed": False, "reason": "no summary"})
        if args.strict:
            print("No backtest summary JSON found for PnL sanity check.")
            return 2
        return 0

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics = extract_metrics(summary)
    failures: list[str] = []
    if metrics["initial_capital"] <= 0:
        failures.append("initial_capital must be positive")
    if metrics["final_capital"] <= 0:
        failures.append("final_capital must be positive")
    if not math.isfinite(metrics["profit_factor"]):
        failures.append("profit_factor must be finite for production comparison")
    if abs(metrics["return_pct"]) > 200 and metrics["trade_count"] < 30:
        failures.append("extreme return with low trade count is likely unstable")

    passed = not failures
    write_state(
        "last_pnl_sanity.json",
        {
            "passed": passed,
            "reason": "passed" if passed else "; ".join(failures),
            "metrics": metrics,
            "summary": str(summary_path),
        },
    )
    if failures and args.strict:
        print("; ".join(failures))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
