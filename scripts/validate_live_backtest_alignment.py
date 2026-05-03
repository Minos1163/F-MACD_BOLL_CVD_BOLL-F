from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.config_loader import ConfigLoader
from scripts.backtest_macd_v2 import apply_backtest_profile


@dataclass(frozen=True)
class AlignmentRule:
    path: str
    max_delta: float


@dataclass(frozen=True)
class ApprovedDifference:
    path: str
    live: Any
    backtest: Any
    note: str = ""


DEFAULT_RULES: List[AlignmentRule] = [
    AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.default", 0.05),
    AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.red_bar_growing", 0.05),
    AlignmentRule("fund_flow.macd_mtf_strategy_v2.entry_thresholds.flip_bearish", 0.05),
    AlignmentRule("fund_flow.default_target_portion", 0.10),
    AlignmentRule("fund_flow.max_symbol_position_portion", 0.10),
    AlignmentRule("fund_flow.max_active_symbols", 0.0),
]

DEFAULT_APPROVED_DIFFERENCES: List[ApprovedDifference] = []


def _get_nested(data: dict, path: str) -> Any:
    current: Any = data
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def _matches_approved_difference(
    path: str,
    live_value: Any,
    backtest_value: Any,
    approved_differences: Iterable[ApprovedDifference],
) -> ApprovedDifference | None:
    for item in approved_differences:
        if str(item.path) != str(path):
            continue
        if item.live == live_value and item.backtest == backtest_value:
            return item
    return None


def compare_live_backtest_alignment(
    runtime_cfg: dict,
    rules: Iterable[AlignmentRule],
    approved_differences: Iterable[ApprovedDifference] | None = None,
) -> list[dict]:
    if not isinstance(runtime_cfg, dict):
        raise TypeError("runtime_cfg must be a dict")
    merged_cfg, active_profile = apply_backtest_profile(copy.deepcopy(runtime_cfg))
    approved_list = list(approved_differences or DEFAULT_APPROVED_DIFFERENCES)
    rows: list[dict] = []
    for rule in rules:
        live_value = _get_nested(runtime_cfg, rule.path)
        backtest_value = _get_nested(merged_cfg, rule.path)
        try:
            live_num = float(live_value)
            backtest_num = float(backtest_value)
            delta = abs(live_num - backtest_num)
        except Exception:
            live_num = live_value
            backtest_num = backtest_value
            delta = 0.0 if live_value == backtest_value else float("inf")
        approved = _matches_approved_difference(rule.path, live_value, backtest_value, approved_list)
        if delta <= float(rule.max_delta):
            status = "PASS"
        elif approved is not None:
            status = "APPROVED_DIFF"
        else:
            status = "FAIL"
        rows.append(
            {
                "path": rule.path,
                "live": live_num,
                "backtest": backtest_num,
                "delta": delta,
                "threshold": float(rule.max_delta),
                "status": status,
                "applied_backtest_profile": active_profile,
                "approved_note": approved.note if approved is not None else "",
            }
        )
    return rows


def _render_rows(rows: list[dict]) -> str:
    headers = ["path", "live", "backtest", "delta", "threshold", "status", "approved_note"]
    body: list[list[str]] = []
    for row in rows:
        body.append(
            [
                str(row["path"]),
                f"{row['live']}",
                f"{row['backtest']}",
                f"{row['delta']}",
                f"{row['threshold']}",
                str(row["status"]),
                str(row.get("approved_note", "")),
            ]
        )
    widths = [len(h) for h in headers]
    for values in body:
        for idx, value in enumerate(values):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    lines = [fmt(headers), "-+-".join("-" * width for width in widths)]
    lines.extend(fmt(values) for values in body)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare live config against its default backtest profile overlay.")
    parser.add_argument("--config", default="config/trading_config_fund_flow.json", help="runtime config path")
    args = parser.parse_args(argv)

    runtime_cfg = ConfigLoader.load_trading_config(args.config)
    rows = compare_live_backtest_alignment(runtime_cfg, DEFAULT_RULES)
    print(_render_rows(rows))
    if any(row["status"] == "FAIL" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
