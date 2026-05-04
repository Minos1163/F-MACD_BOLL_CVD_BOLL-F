"""
Audit realized stop-loss behavior in MACD V2 backtest trades.

This script is intentionally read-only. It classifies losing trades against the
configured fund_flow stop and MACD V2 max dynamic stop, then writes a CSV/JSON
packet that explains whether large losses came from wide stop placement or from
fill-price slippage through the stop.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trades(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _default_output_prefix(trades_path: Path) -> Path:
    return trades_path.with_suffix("")


def _pct(value: float) -> float:
    return value * 100.0


def classify_loss(
    *,
    loss_abs_ratio: float,
    fill_slip_abs_ratio: float,
    configured_stop_pct: float,
    max_stop_loss_pct: float,
    hard_limit_pct: float,
) -> str:
    tolerance = 0.001
    if loss_abs_ratio <= configured_stop_pct + tolerance:
        return "ok_configured_stop"
    if hard_limit_pct > 0 and loss_abs_ratio > hard_limit_pct + tolerance:
        return "critical_beyond_hard_limit"
    if max_stop_loss_pct > 0 and loss_abs_ratio > max_stop_loss_pct + tolerance:
        return "critical_beyond_strategy_max_stop"
    if fill_slip_abs_ratio > tolerance:
        return "warn_stop_fill_slipped"
    return "warn_wide_stop_distance"


def build_rows(
    trades: List[Dict[str, str]],
    *,
    configured_stop_pct: float,
    max_stop_loss_pct: float,
    hard_limit_pct: float,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for trade in trades:
        pnl = _safe_float(trade.get("pnl"))
        if pnl >= 0:
            continue

        side = str(trade.get("side", "")).lower()
        entry_price = _safe_float(trade.get("entry_price"))
        exit_price = _safe_float(trade.get("exit_price"))
        if entry_price <= 0 or exit_price <= 0:
            continue

        pnl_ratio = (exit_price - entry_price) / entry_price if side == "long" else (entry_price - exit_price) / entry_price
        loss_abs_ratio = abs(min(0.0, pnl_ratio))
        configured_stop_price = (
            entry_price * (1.0 - configured_stop_pct)
            if side == "long"
            else entry_price * (1.0 + configured_stop_pct)
        )
        max_stop_price = (
            entry_price * (1.0 - max_stop_loss_pct)
            if side == "long"
            else entry_price * (1.0 + max_stop_loss_pct)
        )

        if side == "long":
            fill_slip_ratio = min(0.0, (exit_price - max_stop_price) / entry_price)
        else:
            fill_slip_ratio = min(0.0, (max_stop_price - exit_price) / entry_price)

        rows.append(
            {
                "symbol": trade.get("symbol", ""),
                "side": side,
                "entry_time": trade.get("entry_time", ""),
                "exit_time": trade.get("exit_time", ""),
                "reason": trade.get("reason", ""),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "price_pnl_pct": _pct(pnl_ratio),
                "loss_abs_pct": _pct(loss_abs_ratio),
                "configured_stop_pct": _pct(configured_stop_pct),
                "configured_stop_price": configured_stop_price,
                "max_stop_loss_pct": _pct(max_stop_loss_pct),
                "max_stop_price": max_stop_price,
                "fill_slip_vs_max_stop_pct": _pct(abs(fill_slip_ratio)),
                "signal_score": _safe_float(trade.get("signal_score")),
                "signal_type_1h": trade.get("signal_type_1h", ""),
                "vwap_score": _safe_float(trade.get("vwap_score")),
                "vwap_state": trade.get("vwap_state", ""),
                "adx_1h": _safe_float(trade.get("adx_1h")),
                "leverage": int(_safe_float(trade.get("leverage"), 0.0)),
                "category": classify_loss(
                    loss_abs_ratio=loss_abs_ratio,
                    fill_slip_abs_ratio=abs(fill_slip_ratio),
                    configured_stop_pct=configured_stop_pct,
                    max_stop_loss_pct=max_stop_loss_pct,
                    hard_limit_pct=hard_limit_pct,
                ),
            }
        )
    rows.sort(key=lambda item: float(item["pnl"]))
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_category: Dict[str, Dict[str, Any]] = {}
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        for key, bucket_key in (("by_category", str(row["category"])), ("by_symbol", str(row["symbol"]))):
            target = by_category if key == "by_category" else by_symbol
            bucket = target.setdefault(bucket_key, {"count": 0, "pnl": 0.0, "max_loss_abs_pct": 0.0})
            bucket["count"] += 1
            bucket["pnl"] += float(row["pnl"])
            bucket["max_loss_abs_pct"] = max(float(bucket["max_loss_abs_pct"]), float(row["loss_abs_pct"]))

    return {
        "loss_count": len(rows),
        "gross_loss": sum(float(row["pnl"]) for row in rows),
        "max_loss_abs_pct": max((float(row["loss_abs_pct"]) for row in rows), default=0.0),
        "by_category": by_category,
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda item: float(item[1]["pnl"]))),
        "worst_losses": rows[:10],
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MACD V2 backtest stop-loss behavior.")
    parser.add_argument("--trades", required=True, help="backtest trades CSV")
    parser.add_argument("--summary", required=True, help="backtest summary JSON")
    parser.add_argument("--hard-limit-pct", type=float, default=0.015, help="hard loss limit ratio for classification")
    parser.add_argument("--output-prefix", default=None, help="output prefix, defaults next to trades file")
    args = parser.parse_args()

    trades_path = Path(args.trades)
    summary_path = Path(args.summary)
    prefix = Path(args.output_prefix) if args.output_prefix else _default_output_prefix(trades_path)

    summary = _load_json(summary_path)
    runtime_limits = summary.get("runtime_limits", {}) if isinstance(summary.get("runtime_limits"), dict) else {}
    strategy_config = summary.get("strategy_config", {}) if isinstance(summary.get("strategy_config"), dict) else {}
    configured_stop_pct = _safe_float(runtime_limits.get("stop_loss_pct"), 0.0)
    max_stop_loss_pct = _safe_float(strategy_config.get("max_stop_loss_pct"), 0.0)

    rows = build_rows(
        _load_trades(trades_path),
        configured_stop_pct=configured_stop_pct,
        max_stop_loss_pct=max_stop_loss_pct,
        hard_limit_pct=float(args.hard_limit_pct),
    )
    audit_summary = {
        "trades_file": str(trades_path),
        "summary_file": str(summary_path),
        "configured_stop_pct": configured_stop_pct,
        "max_stop_loss_pct": max_stop_loss_pct,
        "hard_limit_pct": float(args.hard_limit_pct),
        **summarize(rows),
    }

    csv_path = prefix.parent / f"{prefix.name}_stop_loss_audit.csv"
    json_path = prefix.parent / f"{prefix.name}_stop_loss_audit.json"
    write_csv(csv_path, rows)
    json_path.write_text(json.dumps(audit_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"stop_loss_audit_csv: {csv_path}")
    print(f"stop_loss_audit_json: {json_path}")


if __name__ == "__main__":
    main()
