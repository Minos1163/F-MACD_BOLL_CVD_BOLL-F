from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd


def _load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _build_reason_table(pending_cancels_df: pd.DataFrame) -> Dict[str, int]:
    if pending_cancels_df.empty or "reason" not in pending_cancels_df.columns:
        return {}
    counts = pending_cancels_df["reason"].fillna("").astype(str).value_counts().to_dict()
    return {str(key): int(val) for key, val in counts.items()}


def diagnose_ioc_fallback(summary: dict, pending_cancels_df: pd.DataFrame | None = None) -> dict:
    execution_funnel = (summary or {}).get("execution_funnel", {}) or {}
    cancel_df = pending_cancels_df if pending_cancels_df is not None else pd.DataFrame()
    cancel_reason_counts = _build_reason_table(cancel_df)

    ioc_cancels = _safe_int(cancel_reason_counts.get("ioc_no_fill", execution_funnel.get("orders_canceled", 0)))
    market_attempted = _safe_int(execution_funnel.get("market_fallback_attempted", 0))
    market_filled = _safe_int(execution_funnel.get("market_fallback_filled", 0))
    market_slippage_blocked = _safe_int(execution_funnel.get("market_fallback_slippage_blocked", 0))
    market_disabled = _safe_int(execution_funnel.get("market_fallback_disabled_by_policy", 0))

    fallback_not_reached = max(0, ioc_cancels - market_attempted - market_disabled - market_slippage_blocked)
    root_cause_breakdown = {
        "ioc_no_fill_total": ioc_cancels,
        "market_fallback_attempted": market_attempted,
        "market_fallback_filled": market_filled,
        "market_fallback_slippage_blocked": market_slippage_blocked,
        "market_fallback_disabled_by_policy": market_disabled,
        "fallback_not_reached_after_ioc_cancel": fallback_not_reached,
    }

    by_signal_type: Dict[str, int] = {}
    if not cancel_df.empty and "signal_type_1h" in cancel_df.columns:
        by_signal_type = {
            str(key): int(val)
            for key, val in cancel_df["signal_type_1h"].fillna("").astype(str).value_counts().to_dict().items()
        }

    avg_signal_score = 0.0
    p75_signal_score = 0.0
    if not cancel_df.empty and "signal_score" in cancel_df.columns:
        scores = pd.to_numeric(cancel_df["signal_score"], errors="coerce").dropna()
        if not scores.empty:
            avg_signal_score = float(scores.mean())
            p75_signal_score = float(scores.quantile(0.75))

    return {
        "summary_file": str((summary or {}).get("_summary_file", "")),
        "pending_cancel_rows": int(len(cancel_df)),
        "cancel_reason_counts": cancel_reason_counts,
        "root_cause_breakdown": root_cause_breakdown,
        "by_signal_type": by_signal_type,
        "signal_score_stats": {
            "avg": avg_signal_score,
            "p75": p75_signal_score,
        },
        "diagnosis": [
            "IOC 取消总量来自流动性未成交；若 market_fallback_attempted 为 0，则优先检查 entry_execution_policy 与 entry_market_fallback_enabled 双门。",
            "当 market_fallback_disabled_by_policy > 0 时，说明 metadata 或风控位主动禁用了市价兜底。",
            "若 fallback_not_reached_after_ioc_cancel 很高，说明大部分取消没有进入 market fallback 链，而不是进入后被滑点拦截。",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Diagnose why IOC cancels did not progress to fallback paths.")
    parser.add_argument("--summary", required=True, help="backtest summary json path")
    parser.add_argument("--pending-cancels", default=None, help="pending cancels csv path")
    parser.add_argument("--output", default=None, help="optional output json path")
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    summary = _load_summary(summary_path)
    summary["_summary_file"] = str(summary_path)

    pending_cancels_df = pd.DataFrame()
    if args.pending_cancels:
        pending_cancels_df = pd.read_csv(args.pending_cancels, encoding="utf-8-sig")

    result = diagnose_ioc_fallback(summary, pending_cancels_df)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
