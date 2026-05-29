from __future__ import annotations

import argparse
import json

from _common import REPO_ROOT, extract_metrics, latest_backtest_summary, normalized_drawdown_fraction, post_feedback, write_state


MAX_DRAWDOWN = 0.25
MIN_PROFIT_FACTOR = 1.30
MIN_TRADE_COUNT = 80


def evaluate() -> tuple[bool, str, dict[str, float], str]:
    backtest_state_path = REPO_ROOT / ".codex" / "hook_state" / "last_backtest.json"
    if backtest_state_path.exists():
        backtest_state = json.loads(backtest_state_path.read_text(encoding="utf-8"))
        status = str(backtest_state.get("status", ""))
        if status in {"required", "failed"}:
            return False, str(backtest_state.get("reason", f"backtest status is {status}")), {}, ""

    summary_path = latest_backtest_summary()
    if summary_path is None:
        return False, "No backtest summary JSON found.", {}, ""

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics = extract_metrics(summary)
    failures: list[str] = []

    if normalized_drawdown_fraction(metrics["max_drawdown_pct"]) > MAX_DRAWDOWN:
        failures.append(f"max drawdown too high: {metrics['max_drawdown_pct']:.4g}")
    if metrics["profit_factor"] < MIN_PROFIT_FACTOR:
        failures.append(f"profit factor too low: {metrics['profit_factor']:.4g}")
    if metrics["trade_count"] < MIN_TRADE_COUNT:
        failures.append(f"trade count too low: {metrics['trade_count']:.0f}")

    passed = not failures
    reason = "metrics passed" if passed else "; ".join(failures)
    return passed, reason, metrics, str(summary_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check latest backtest metrics against minimum quality gates.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when metrics are missing or fail.")
    args = parser.parse_args()

    passed, reason, metrics, summary_path = evaluate()
    write_state("last_metrics_check.json", {"passed": passed, "reason": reason, "metrics": metrics, "summary": summary_path})

    if not passed:
        if args.strict:
            print(reason)
            return 2
        post_feedback(
            "Backtest metrics gate failed or is missing: " + reason,
            "Do not treat this strategy change as verified until a strict-live backtest produces acceptable metrics.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
