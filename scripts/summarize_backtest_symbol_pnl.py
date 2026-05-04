from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable


FIELDNAMES = [
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


def summarize_files(
    paths: Iterable[Path],
    symbols: set[str] | None = None,
) -> list[dict[str, float | int | str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    symbol_filter = {symbol.upper() for symbol in symbols} if symbols else None

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
        trades = len(rows)
        wins = sum(1 for pnl in pnls if pnl > 0)
        losses = sum(1 for pnl in pnls if pnl <= 0)

        summaries.append(
            {
                "symbol": symbol,
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": round((wins / trades * 100.0) if trades else 0.0, 6),
                "net_pnl": round(sum(pnls), 6),
                "avg_pnl": round((sum(pnls) / trades) if trades else 0.0, 6),
                "worst_pnl": round(min(pnls), 6) if pnls else 0.0,
                "worst_price_pnl_pct": round(min(price_pnls), 6) if price_pnls else 0.0,
            }
        )

    return sorted(summaries, key=lambda row: float(row["net_pnl"]))


def write_csv(rows: list[dict[str, float | int | str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
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

        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
