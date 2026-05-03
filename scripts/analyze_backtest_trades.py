import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import pandas as pd


def load_trades(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build_symbol_breakdown(trades: List[dict]) -> List[dict]:
    acc: Dict[str, dict] = defaultdict(
        lambda: {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "long_trades": 0,
            "short_trades": 0,
        }
    )

    for trade in trades:
        symbol = str(trade["symbol"])
        pnl = float(trade["pnl"])
        side = str(trade["side"]).lower()
        bucket = acc[symbol]
        bucket["trades"] += 1
        bucket["total_pnl"] += pnl
        if side == "long":
            bucket["long_trades"] += 1
        elif side == "short":
            bucket["short_trades"] += 1
        if pnl > 0:
            bucket["wins"] += 1
            bucket["gross_win"] += pnl
        else:
            bucket["losses"] += 1
            bucket["gross_loss"] += abs(pnl)

    rows: List[dict] = []
    for symbol, bucket in acc.items():
        trades_count = int(bucket["trades"])
        rows.append(
            {
                "symbol": symbol,
                "trades": trades_count,
                "wins": int(bucket["wins"]),
                "losses": int(bucket["losses"]),
                "win_rate_pct": (bucket["wins"] / trades_count * 100.0) if trades_count else 0.0,
                "total_pnl": float(bucket["total_pnl"]),
                "avg_pnl": float(bucket["total_pnl"]) / trades_count if trades_count else 0.0,
                "profit_factor": (
                    float(bucket["gross_win"]) / float(bucket["gross_loss"])
                    if bucket["gross_loss"] > 0
                    else (float("inf") if bucket["gross_win"] > 0 else 0.0)
                ),
                "long_trades": int(bucket["long_trades"]),
                "short_trades": int(bucket["short_trades"]),
            }
        )

    rows.sort(key=lambda item: float(item["total_pnl"]), reverse=True)
    return rows


def build_drawdown_breakdown(trades: List[dict], initial_capital: float) -> List[dict]:
    if not trades:
        return []

    ordered = sorted(
        trades,
        key=lambda item: (
            pd.Timestamp(item["exit_time"]),
            pd.Timestamp(item["entry_time"]),
            str(item["symbol"]),
        ),
    )

    equity = float(initial_capital)
    running_peak = float(initial_capital)
    current_episode = None
    episodes: List[dict] = []

    for index, trade in enumerate(ordered, start=1):
        pnl = float(trade["pnl"])
        exit_time = pd.Timestamp(trade["exit_time"])
        equity += pnl

        if equity >= running_peak:
            if current_episode is not None:
                current_episode["recovery_time"] = exit_time.strftime("%Y-%m-%d %H:%M:%S")
                current_episode["duration_trades"] = index - current_episode["start_trade_index"] + 1
                episodes.append(current_episode)
                current_episode = None
            running_peak = equity
            continue

        drawdown = running_peak - equity
        drawdown_pct = (drawdown / running_peak * 100.0) if running_peak > 0 else 0.0
        if current_episode is None:
            current_episode = {
                "start_trade_index": index,
                "start_time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "peak_equity": running_peak,
                "trough_equity": equity,
                "max_drawdown": drawdown,
                "max_drawdown_pct": drawdown_pct,
                "trough_time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "recovery_time": "",
                "duration_trades": 0,
            }
        elif drawdown > float(current_episode["max_drawdown"]):
            current_episode["trough_equity"] = equity
            current_episode["max_drawdown"] = drawdown
            current_episode["max_drawdown_pct"] = drawdown_pct
            current_episode["trough_time"] = exit_time.strftime("%Y-%m-%d %H:%M:%S")

    if current_episode is not None:
        current_episode["duration_trades"] = len(ordered) - current_episode["start_trade_index"] + 1
        episodes.append(current_episode)

    episodes.sort(key=lambda item: float(item["max_drawdown"]), reverse=True)
    return episodes


def build_true_drawdown_breakdown(equity_curve_path: Path) -> List[dict]:
    if not equity_curve_path.exists():
        return []

    rows = list(csv.DictReader(equity_curve_path.open("r", encoding="utf-8-sig", newline="")))
    if not rows:
        return []

    episodes: List[dict] = []
    peak_equity = None
    peak_time = ""
    current_episode = None

    for index, row in enumerate(rows, start=1):
        equity = float(row["equity"])
        ts = str(row["timestamp"])
        if peak_equity is None or equity >= peak_equity:
            if current_episode is not None:
                current_episode["recovery_time"] = ts
                current_episode["duration_points"] = index - current_episode["start_point_index"] + 1
                episodes.append(current_episode)
                current_episode = None
            peak_equity = equity
            peak_time = ts
            continue

        drawdown = peak_equity - equity
        drawdown_pct = (drawdown / peak_equity * 100.0) if peak_equity > 0 else 0.0
        if current_episode is None:
            current_episode = {
                "start_point_index": index,
                "start_time": peak_time,
                "peak_equity": peak_equity,
                "trough_equity": equity,
                "max_drawdown": drawdown,
                "max_drawdown_pct": drawdown_pct,
                "trough_time": ts,
                "recovery_time": "",
                "duration_points": 0,
            }
        elif drawdown > float(current_episode["max_drawdown"]):
            current_episode["trough_equity"] = equity
            current_episode["max_drawdown"] = drawdown
            current_episode["max_drawdown_pct"] = drawdown_pct
            current_episode["trough_time"] = ts

    if current_episode is not None:
        current_episode["duration_points"] = len(rows) - current_episode["start_point_index"] + 1
        episodes.append(current_episode)

    episodes.sort(key=lambda item: float(item["max_drawdown"]), reverse=True)
    return episodes


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            fh.write("")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_cancel_quality_summary(trades_df: pd.DataFrame, pending_cancels_df: pd.DataFrame) -> dict:
    filled_scores = pd.to_numeric(trades_df.get("signal_score", pd.Series(dtype=float)), errors="coerce").dropna()
    canceled_scores = pd.to_numeric(pending_cancels_df.get("signal_score", pd.Series(dtype=float)), errors="coerce").dropna()

    def _percentiles(series: pd.Series) -> dict:
        if series.empty:
            return {"p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
        return {
            "p10": float(series.quantile(0.10)),
            "p25": float(series.quantile(0.25)),
            "p50": float(series.quantile(0.50)),
            "p75": float(series.quantile(0.75)),
            "p90": float(series.quantile(0.90)),
        }

    by_signal_type: Dict[str, dict] = {}
    trade_type_counts = (
        trades_df.groupby("signal_type_1h").size().to_dict()
        if "signal_type_1h" in trades_df.columns and not trades_df.empty
        else {}
    )
    cancel_type_counts = (
        pending_cancels_df.groupby("signal_type_1h").size().to_dict()
        if "signal_type_1h" in pending_cancels_df.columns and not pending_cancels_df.empty
        else {}
    )
    for signal_type in sorted(set(trade_type_counts) | set(cancel_type_counts)):
        by_signal_type[str(signal_type)] = {
            "filled": int(trade_type_counts.get(signal_type, 0) or 0),
            "canceled": int(cancel_type_counts.get(signal_type, 0) or 0),
        }

    return {
        "filled_count": int(len(filled_scores)),
        "canceled_count": int(len(canceled_scores)),
        "filled_avg_score": float(filled_scores.mean()) if not filled_scores.empty else 0.0,
        "canceled_avg_score": float(canceled_scores.mean()) if not canceled_scores.empty else 0.0,
        "canceled_score_percentiles": _percentiles(canceled_scores),
        "by_signal_type": by_signal_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a backtest trades CSV into symbol and drawdown breakdowns.")
    parser.add_argument("--trades", required=True, help="path to backtest trades csv")
    parser.add_argument("--initial-capital", type=float, default=10000.0, help="initial capital used in the backtest")
    parser.add_argument("--equity-curve", default=None, help="optional per-bar equity curve csv for true drawdown analysis")
    parser.add_argument("--pending-cancels", default=None, help="optional pending cancel audit csv")
    parser.add_argument("--output-prefix", default=None, help="output prefix; defaults next to the trades file")
    args = parser.parse_args()

    trades_path = Path(args.trades)
    trades = load_trades(trades_path)
    symbol_rows = build_symbol_breakdown(trades)
    realized_drawdown_rows = build_drawdown_breakdown(trades, initial_capital=float(args.initial_capital))
    true_drawdown_rows = build_true_drawdown_breakdown(Path(args.equity_curve)) if args.equity_curve else []

    if args.output_prefix:
        prefix = Path(args.output_prefix)
    else:
        prefix = trades_path.with_suffix("")

    symbol_csv = prefix.parent / f"{prefix.name}_symbol_breakdown.csv"
    drawdown_csv = prefix.parent / f"{prefix.name}_drawdown_breakdown.csv"
    true_drawdown_csv = prefix.parent / f"{prefix.name}_true_drawdown_breakdown.csv"
    summary_json = prefix.parent / f"{prefix.name}_analysis_summary.json"
    cancel_quality_json = prefix.parent / f"{prefix.name}_cancel_quality_summary.json"

    write_csv(symbol_csv, symbol_rows)
    write_csv(drawdown_csv, realized_drawdown_rows)
    write_csv(true_drawdown_csv, true_drawdown_rows)
    cancel_quality_summary = None
    if args.pending_cancels:
        pending_cancels_df = pd.read_csv(args.pending_cancels, encoding="utf-8-sig")
        trades_df = pd.DataFrame(trades)
        cancel_quality_summary = build_cancel_quality_summary(trades_df, pending_cancels_df)
        cancel_quality_json.write_text(json.dumps(cancel_quality_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "trades_file": str(trades_path),
        "initial_capital": float(args.initial_capital),
        "equity_curve_file": str(args.equity_curve) if args.equity_curve else "",
        "pending_cancels_file": str(args.pending_cancels) if args.pending_cancels else "",
        "symbol_breakdown_file": str(symbol_csv),
        "drawdown_breakdown_file": str(drawdown_csv),
        "true_drawdown_breakdown_file": str(true_drawdown_csv),
        "cancel_quality_summary_file": str(cancel_quality_json) if cancel_quality_summary is not None else "",
        "symbols_traded": len(symbol_rows),
        "drawdown_episodes": len(realized_drawdown_rows),
        "true_drawdown_episodes": len(true_drawdown_rows),
        "top_symbol": symbol_rows[0] if symbol_rows else None,
        "worst_symbol": symbol_rows[-1] if symbol_rows else None,
        "max_drawdown_episode": realized_drawdown_rows[0] if realized_drawdown_rows else None,
        "max_true_drawdown_episode": true_drawdown_rows[0] if true_drawdown_rows else None,
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"symbol_breakdown: {symbol_csv}")
    print(f"drawdown_breakdown: {drawdown_csv}")
    print(f"true_drawdown_breakdown: {true_drawdown_csv}")
    if cancel_quality_summary is not None:
        print(f"cancel_quality_summary: {cancel_quality_json}")
    print(f"summary: {summary_json}")


if __name__ == "__main__":
    main()
