import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
            {
                "symbol": "ADAUSDT",
                "pnl": "-10",
                "entry_price": "1.00",
                "exit_price": "0.95",
                "side": "long",
                "reason": "stop",
            },
            {
                "symbol": "ADAUSDT",
                "pnl": "4",
                "entry_price": "1.00",
                "exit_price": "1.02",
                "side": "long",
                "reason": "tp",
            },
            {
                "symbol": "FETUSDT",
                "pnl": "-2",
                "entry_price": "2.00",
                "exit_price": "1.98",
                "side": "long",
                "reason": "stop",
            },
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
            {
                "symbol": "ADAUSDT",
                "pnl": "-10",
                "entry_price": "1.00",
                "exit_price": "0.95",
                "side": "long",
                "reason": "stop",
            },
            {
                "symbol": "SOLUSDT",
                "pnl": "30",
                "entry_price": "10.00",
                "exit_price": "10.50",
                "side": "long",
                "reason": "tp",
            },
        ],
    )

    rows = summarize_files([trades], symbols={"ADAUSDT"})

    assert [row["symbol"] for row in rows] == ["ADAUSDT"]
