from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _read_csv_required(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")
    return pd.read_csv(path)


def _require_non_empty(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        raise ValueError(f"{label} file is empty")


def _to_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    out = df.copy()
    if limit is not None:
        out = out.head(limit)
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    return json.loads(out.to_json(orient="records", force_ascii=False))


def _find_time_column(df: pd.DataFrame) -> str:
    for column in ("timestamp", "time", "datetime"):
        if column in df.columns:
            return column
    raise ValueError("equity curve must contain timestamp, time, or datetime column")


def _group_breakdown(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    available = [column for column in columns if column in df.columns]
    if not available or df.empty:
        return []
    grouped = (
        df.groupby(available, dropna=False)
        .agg(
            trades=("pnl", "size"),
            wins=("pnl", lambda s: int((s > 0).sum())),
            losses=("pnl", lambda s: int((s <= 0).sum())),
            total_pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            min_pnl=("pnl", "min"),
            median_hold_min=("hold_min", "median"),
            max_hold_min=("hold_min", "max"),
        )
        .reset_index()
        .sort_values(["total_pnl", "trades"], ascending=[True, False])
    )
    return _to_records(grouped)


def diagnose_mdd_round1(
    *,
    trades_file: Path | str,
    equity_curve_file: Path | str,
    drawdown_file: Path | str,
    window_start: str,
    window_end: str,
) -> dict[str, Any]:
    trades_path = Path(trades_file)
    equity_path = Path(equity_curve_file)
    drawdown_path = Path(drawdown_file)

    trades = _read_csv_required(trades_path, "trades")
    equity = _read_csv_required(equity_path, "equity curve")
    drawdowns = _read_csv_required(drawdown_path, "drawdown")
    _require_non_empty(trades, "trades")
    _require_non_empty(equity, "equity curve")
    _require_non_empty(drawdowns, "drawdown")

    for column in ("entry_time", "exit_time", "pnl"):
        if column not in trades.columns:
            raise ValueError(f"trades file missing required column: {column}")

    start = pd.Timestamp(window_start)
    end = pd.Timestamp(window_end)
    if end < start:
        raise ValueError("window_end must be greater than or equal to window_start")

    trades = trades.copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    trades["hold_min"] = (trades["exit_time"] - trades["entry_time"]).dt.total_seconds() / 60.0

    overlap = trades[(trades["entry_time"] <= end) & (trades["exit_time"] >= start)].copy()
    closed = trades[(trades["exit_time"] >= start) & (trades["exit_time"] <= end)].copy()
    losses = closed[closed["pnl"] <= 0].copy()

    time_column = _find_time_column(equity)
    equity = equity.copy()
    equity[time_column] = pd.to_datetime(equity[time_column])
    equity_window = equity[(equity[time_column] >= start) & (equity[time_column] <= end)].copy()

    drawdowns = drawdowns.copy()
    for column in ("start_time", "trough_time", "recovery_time"):
        if column in drawdowns.columns:
            drawdowns[column] = pd.to_datetime(drawdowns[column], errors="coerce")
    drawdown_window = drawdowns
    if "start_time" in drawdowns.columns and "trough_time" in drawdowns.columns:
        drawdown_window = drawdowns[(drawdowns["start_time"] <= end) & (drawdowns["trough_time"] >= start)].copy()

    low_quality_columns = [
        column
        for column in ("signal_score", "vwap_score", "adx_1h", "adx_4h", "bb_middle_slope_4h")
        if column in closed.columns
    ]
    low_quality = []
    if low_quality_columns and not losses.empty:
        low_quality = _to_records(
            losses.sort_values("pnl")[
                ["symbol", "side", "entry_time", "exit_time", "pnl", "reason", "signal_type_1h", "hold_min"]
                + low_quality_columns
            ],
            limit=25,
        )

    equity_stats: dict[str, Any] = {"points": int(len(equity_window))}
    if not equity_window.empty and "equity" in equity_window.columns:
        equity_stats.update(
            {
                "start_equity": float(equity_window.iloc[0]["equity"]),
                "end_equity": float(equity_window.iloc[-1]["equity"]),
                "min_equity": float(pd.to_numeric(equity_window["equity"], errors="coerce").min()),
                "max_equity": float(pd.to_numeric(equity_window["equity"], errors="coerce").max()),
            }
        )

    return {
        "source_files": {
            "trades": str(trades_path),
            "equity_curve": str(equity_path),
            "drawdown": str(drawdown_path),
        },
        "window": {
            "start": str(start),
            "end": str(end),
            "overlap_trades": int(len(overlap)),
            "closed_trades": int(len(closed)),
            "closed_losses": int(len(losses)),
            "closed_pnl": float(closed["pnl"].sum()) if not closed.empty else 0.0,
            "closed_loss_pnl": float(losses["pnl"].sum()) if not losses.empty else 0.0,
        },
        "equity_window": equity_stats,
        "drawdown_episodes": _to_records(drawdown_window.head(10)),
        "reason_breakdown": _group_breakdown(closed, ["reason"]),
        "signal_type_breakdown": _group_breakdown(closed, ["signal_type_1h"]),
        "symbol_breakdown": _group_breakdown(closed, ["symbol"]),
        "reason_signal_breakdown": _group_breakdown(closed, ["reason", "signal_type_1h"]),
        "loss_trades": _to_records(
            losses.sort_values("pnl")[
                [column for column in ("symbol", "side", "entry_time", "exit_time", "pnl", "reason", "signal_type_1h", "signal_score", "hold_min") if column in losses.columns]
            ],
            limit=50,
        )
        if not losses.empty
        else [],
        "low_quality_loss_candidates": low_quality,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose MACD V2 Round 1 MDD contribution inside a fixed drawdown window.")
    parser.add_argument("--trades-file", required=True)
    parser.add_argument("--equity-curve-file", required=True)
    parser.add_argument("--drawdown-file", required=True)
    parser.add_argument("--window-start", default="2026-02-28 17:30:00")
    parser.add_argument("--window-end", default="2026-03-04 00:30:00")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    result = diagnose_mdd_round1(
        trades_file=Path(args.trades_file),
        equity_curve_file=Path(args.equity_curve_file),
        drawdown_file=Path(args.drawdown_file),
        window_start=args.window_start,
        window_end=args.window_end,
    )

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
