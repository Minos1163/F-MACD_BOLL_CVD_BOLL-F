from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_rsi4_direction_success_live import (
    dedupe_fills,
    rsi_direction,
    filter_records_by_window,
)


def test_rsi_direction_uses_flat_threshold() -> None:
    assert rsi_direction(50.0, 50.29) == "flat"
    assert rsi_direction(50.0, 50.30) == "flat"
    assert rsi_direction(50.0, 50.31) == "up"
    assert rsi_direction(50.0, 49.69) == "down"


def test_filter_records_by_beijing_window(tmp_path: Path) -> None:
    log_dir = tmp_path / "2026-05-08"
    log_dir.mkdir(parents=True)
    path = log_dir / "fund_flow_attribution.jsonl"
    rows = [
        {"ts": "2026-05-08T10:59:59+00:00", "event": "decision", "decision": {}, "context": {"symbol": "BTCUSDT", "price": 1}},
        {"ts": "2026-05-08T11:00:00+00:00", "event": "decision", "decision": {}, "context": {"symbol": "BTCUSDT", "price": 2}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    filtered = list(filter_records_by_window(tmp_path, pd.Timestamp("2026-05-08 19:00:00", tz="Asia/Shanghai")))

    assert len(filtered) == 1
    assert filtered[0]["context"]["price"] == 2


def test_dedupe_fills_uses_exchange_identity_columns() -> None:
    fills = pd.DataFrame(
        [
            {
                "时间(UTC)": "2026-05-09 00:00:00",
                "合约": "BTCUSDT",
                "方向": "买入",
                "价格": 100.0,
                "数量": 1.0,
                "已实现盈亏": 0.0,
                "订单ID": "o1",
                "成交ID": "f1",
            },
            {
                "时间(UTC)": "2026-05-09 00:00:00",
                "合约": "BTCUSDT",
                "方向": "买入",
                "价格": 100.0,
                "数量": 1.0,
                "已实现盈亏": 0.0,
                "订单ID": "o1",
                "成交ID": "f1",
            },
        ]
    )

    deduped = dedupe_fills(fills)

    assert len(deduped) == 1
