from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


BJ_TZ = "Asia/Shanghai"
UTC = "UTC"
RSI_PERIOD = 4
FLAT_THRESHOLD = 0.3
TF_WEIGHTS = {"15m": 0.20, "1h": 0.50, "4h": 0.30}


def parse_bj_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(BJ_TZ)
    return ts.tz_convert(BJ_TZ)


def parse_utc_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None or value == "":
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(UTC)
    return ts.tz_convert(UTC)


def rsi_direction(rsi_prev: float, rsi_curr: float, flat_threshold: float = FLAT_THRESHOLD) -> str:
    if rsi_prev is None or rsi_curr is None:
        return "unknown"
    if pd.isna(rsi_prev) or pd.isna(rsi_curr):
        return "unknown"
    diff = float(rsi_curr) - float(rsi_prev)
    if diff > flat_threshold:
        return "up"
    if diff < -flat_threshold:
        return "down"
    return "flat"


def direction_score(direction: str) -> float:
    if direction == "up":
        return 1.0
    if direction == "down":
        return -1.0
    return 0.0


def rsi_side_alignment(side: str, rsi_dir: str) -> str:
    side_up = str(side or "").upper()
    direction = str(rsi_dir or "")
    if direction == "flat":
        return "flat"
    if direction not in {"up", "down"}:
        return "unknown"
    if (side_up == "LONG" and direction == "up") or (side_up == "SHORT" and direction == "down"):
        return "aligned"
    if (side_up == "LONG" and direction == "down") or (side_up == "SHORT" and direction == "up"):
        return "opposed"
    return "unknown"


def side_from_operation(operation: str) -> str:
    op = str(operation or "").lower()
    if op == "buy":
        return "LONG"
    if op == "sell":
        return "SHORT"
    return ""


def fill_closes_side(fill_side: str) -> str:
    side = str(fill_side or "")
    if side in {"卖出", "SELL", "sell"}:
        return "LONG"
    if side in {"买入", "BUY", "buy"}:
        return "SHORT"
    return ""


def iter_attribution_files(logs_root: Path) -> Iterable[Path]:
    yield from sorted(logs_root.glob("*/fund_flow_attribution.jsonl"))


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def filter_records_by_window(logs_root: Path, start_bj: pd.Timestamp) -> Iterable[Dict[str, Any]]:
    start_utc = start_bj.tz_convert(UTC)
    for path in iter_attribution_files(logs_root):
        for rec in iter_jsonl(path):
            ts = parse_utc_timestamp(rec.get("ts"))
            if ts is None or ts < start_utc:
                continue
            rec["_source_file"] = str(path)
            yield rec


def load_all_decision_records(logs_root: Path) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for path in iter_attribution_files(logs_root):
        for rec in iter_jsonl(path):
            if rec.get("event") != "decision":
                continue
            ts = parse_utc_timestamp(rec.get("ts"))
            if ts is None:
                continue
            context = rec.get("context") if isinstance(rec.get("context"), dict) else {}
            decision = rec.get("decision") if isinstance(rec.get("decision"), dict) else {}
            md = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
            symbol = str(context.get("symbol") or decision.get("symbol") or "").upper()
            price = _to_float(context.get("price"), math.nan)
            if not symbol or not math.isfinite(price) or price <= 0:
                continue
            rows.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "price": price,
                    "event": rec.get("event"),
                    "operation": str(decision.get("operation") or "").lower(),
                    "target_portion": _to_float(decision.get("target_portion_of_balance"), 0.0),
                    "reason": str(decision.get("reason") or ""),
                    "vwap_score": _to_float(md.get("vwap_score"), math.nan),
                    "vol_vwap_warn": md.get("vol_vwap_warn"),
                    "regime": md.get("regime"),
                    "metadata_omitted_keys": int(_to_float(md.get("_omitted_keys"), 0)),
                    "source_file": str(path),
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)
    return df


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_wilder_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi.astype(float)


def build_price_bars(decisions: pd.DataFrame, freq: str) -> Dict[str, pd.DataFrame]:
    bars: Dict[str, pd.DataFrame] = {}
    if decisions.empty:
        return bars
    for symbol, group in decisions.groupby("symbol"):
        g = group[["ts", "price"]].copy()
        g["bucket"] = g["ts"].dt.floor(freq)
        close = g.sort_values("ts").groupby("bucket")["price"].last().sort_index()
        if close.empty:
            continue
        frame = pd.DataFrame({"close": close})
        frame["rsi"] = calculate_wilder_rsi(frame["close"], RSI_PERIOD)
        frame["rsi_prev"] = frame["rsi"].shift(1)
        frame["rsi_dir"] = [rsi_direction(prev, cur) for prev, cur in zip(frame["rsi_prev"], frame["rsi"])]
        bars[symbol] = frame
    return bars


def lookup_bar_value(bars: Dict[str, pd.DataFrame], symbol: str, ts: pd.Timestamp, field: str) -> Any:
    frame = bars.get(symbol)
    if frame is None or frame.empty:
        return None
    pos = frame.index.searchsorted(ts, side="right") - 1
    if pos < 0:
        return None
    value = frame.iloc[pos].get(field)
    if pd.isna(value):
        return None
    return value


def add_rsi_features(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return decisions.copy()
    enriched = decisions.copy()
    bars_by_tf = {
        "15m": build_price_bars(decisions, "15min"),
        "1h": build_price_bars(decisions, "1h"),
        "4h": build_price_bars(decisions, "4h"),
    }
    for tf in ("15m", "1h", "4h"):
        rsi_values = []
        rsi_prev_values = []
        rsi_dirs = []
        for row in enriched.itertuples(index=False):
            symbol = getattr(row, "symbol")
            ts = getattr(row, "ts")
            rsi_values.append(lookup_bar_value(bars_by_tf[tf], symbol, ts, "rsi"))
            rsi_prev_values.append(lookup_bar_value(bars_by_tf[tf], symbol, ts, "rsi_prev"))
            rsi_dirs.append(lookup_bar_value(bars_by_tf[tf], symbol, ts, "rsi_dir") or "unknown")
        enriched[f"rsi_{tf}"] = rsi_values
        enriched[f"rsi_{tf}_prev"] = rsi_prev_values
        enriched[f"rsi_{tf}_dir"] = rsi_dirs
    enriched["rsi_weighted_direction_score"] = (
        enriched["rsi_15m_dir"].map(direction_score).fillna(0.0) * TF_WEIGHTS["15m"]
        + enriched["rsi_1h_dir"].map(direction_score).fillna(0.0) * TF_WEIGHTS["1h"]
        + enriched["rsi_4h_dir"].map(direction_score).fillna(0.0) * TF_WEIGHTS["4h"]
    )
    enriched["rsi_consensus_direction"] = enriched["rsi_weighted_direction_score"].map(
        lambda score: "LONG" if score > 0 else ("SHORT" if score < 0 else "FLAT")
    )
    return enriched


def load_fills(logs_root: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(logs_root.glob("*/trade_fills_utc.csv")):
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty:
            continue
        df["source_file"] = str(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    fills = pd.concat(frames, ignore_index=True)
    return dedupe_fills(fills)


def dedupe_fills(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return fills.copy()
    subset = [col for col in ["成交ID", "订单ID", "合约", "时间(UTC)", "方向", "价格", "数量"] if col in fills.columns]
    if not subset:
        return fills.drop_duplicates().copy()
    return fills.drop_duplicates(subset=subset).copy()


def normalize_fills(fills: pd.DataFrame, start_utc: pd.Timestamp) -> pd.DataFrame:
    if fills.empty:
        return fills
    out = fills.copy()
    out["ts"] = pd.to_datetime(out["时间(UTC)"], utc=True, errors="coerce")
    out["symbol"] = out["合约"].astype(str).str.upper()
    out["fill_side"] = out["方向"].astype(str)
    out["price"] = pd.to_numeric(out["价格"], errors="coerce")
    out["quantity"] = pd.to_numeric(out["数量"], errors="coerce")
    out["realized_pnl"] = pd.to_numeric(out["已实现盈亏"], errors="coerce").fillna(0.0)
    out = out[out["ts"].notna() & (out["ts"] >= start_utc)].copy()
    out["closes_side"] = out["fill_side"].map(fill_closes_side)
    return out.sort_values("ts").reset_index(drop=True)


def build_entries(decisions: pd.DataFrame, start_utc: pd.Timestamp) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame()
    entries = decisions[
        (decisions["ts"] >= start_utc)
        & decisions["operation"].isin(["buy", "sell"])
        & (decisions["target_portion"] > 0)
    ].copy()
    if entries.empty:
        return entries
    entries["entry_id"] = range(len(entries))
    entries["side"] = entries["operation"].map(side_from_operation)
    entries["is_dca"] = entries["reason"].str.contains("DCA|马丁", case=False, regex=True, na=False)
    entries["rsi_1h_4h_combo"] = entries["rsi_1h_dir"].astype(str) + "/" + entries["rsi_4h_dir"].astype(str)
    entries["rsi_1h_15m_combo"] = entries["rsi_1h_dir"].astype(str) + "/" + entries["rsi_15m_dir"].astype(str)
    entries["rsi_3tf_combo"] = (
        entries["rsi_15m_dir"].astype(str)
        + "/"
        + entries["rsi_1h_dir"].astype(str)
        + "/"
        + entries["rsi_4h_dir"].astype(str)
    )
    return entries.reset_index(drop=True)


def match_entry_pnl(entries: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    if entries.empty:
        return entries.copy()
    out = entries.copy()
    out["matched_realized_pnl"] = 0.0
    out["matched_close_fills"] = 0
    out["matched_closed"] = False
    if fills.empty:
        return out
    normal_entries = out[~out["is_dca"]].copy()
    for fill in fills.itertuples(index=False):
        pnl = _to_float(getattr(fill, "realized_pnl", 0.0), 0.0)
        if abs(pnl) <= 1e-12:
            continue
        symbol = getattr(fill, "symbol")
        closes_side = getattr(fill, "closes_side")
        ts = getattr(fill, "ts")
        candidates = normal_entries[
            (normal_entries["symbol"] == symbol)
            & (normal_entries["side"] == closes_side)
            & (normal_entries["ts"] <= ts)
        ]
        if candidates.empty:
            continue
        entry_idx = candidates.sort_values("ts").iloc[-1].name
        out.loc[entry_idx, "matched_realized_pnl"] += pnl
        out.loc[entry_idx, "matched_close_fills"] += 1
        out.loc[entry_idx, "matched_closed"] = True
    out["matched_win"] = out["matched_realized_pnl"] > 0
    return out


def future_price(decisions: pd.DataFrame, symbol: str, ts: pd.Timestamp, horizon: pd.Timedelta) -> Optional[float]:
    group = decisions[decisions["symbol"] == symbol]
    target = ts + horizon
    future = group[group["ts"] >= target]
    if future.empty:
        return None
    return _to_float(future.iloc[0]["price"], math.nan)


def build_forward_stats(decisions: pd.DataFrame, start_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    sample = decisions[(decisions["ts"] >= start_utc) & decisions["rsi_consensus_direction"].isin(["LONG", "SHORT"])].copy()
    for row in sample.itertuples(index=False):
        for label, horizon in [("1h", pd.Timedelta(hours=1)), ("4h", pd.Timedelta(hours=4)), ("8h", pd.Timedelta(hours=8))]:
            fp = future_price(decisions, getattr(row, "symbol"), getattr(row, "ts"), horizon)
            if fp is None or not math.isfinite(fp):
                continue
            ret = (fp - getattr(row, "price")) / getattr(row, "price")
            direction = getattr(row, "rsi_consensus_direction")
            correct = ret > 0 if direction == "LONG" else ret < 0
            rows.append(
                {
                    "horizon": label,
                    "symbol": getattr(row, "symbol"),
                    "ts": getattr(row, "ts"),
                    "rsi_consensus_direction": direction,
                    "forward_return": ret,
                    "direction_correct": bool(correct),
                    "rsi_15m_dir": getattr(row, "rsi_15m_dir"),
                    "rsi_1h_dir": getattr(row, "rsi_1h_dir"),
                    "rsi_4h_dir": getattr(row, "rsi_4h_dir"),
                }
            )
    return pd.DataFrame(rows)


def summarize_entries(entries: pd.DataFrame, group_cols: List[str]) -> List[Dict[str, Any]]:
    if entries.empty:
        return []
    matched = entries[entries["matched_closed"]].copy()
    if matched.empty:
        return []
    rows = []
    for keys, group in matched.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(group_cols, keys)}
        wins = int(group["matched_win"].sum())
        count = int(len(group))
        row.update(
            entries=count,
            wins=wins,
            losses=count - wins,
            win_rate=round(wins / count, 4) if count else 0.0,
            pnl=round(float(group["matched_realized_pnl"].sum()), 6),
            avg_pnl=round(float(group["matched_realized_pnl"].mean()), 6) if count else 0.0,
        )
        rows.append(row)
    return sorted(rows, key=lambda item: (-item["entries"], str(item)))


def summarize_forward(forward: pd.DataFrame, group_cols: List[str]) -> List[Dict[str, Any]]:
    if forward.empty:
        return []
    rows = []
    for keys, group in forward.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(group_cols, keys)}
        count = int(len(group))
        correct = int(group["direction_correct"].sum())
        row.update(
            samples=count,
            correct=correct,
            success_rate=round(correct / count, 4) if count else 0.0,
            avg_forward_return=round(float(group["forward_return"].mean()), 6) if count else 0.0,
        )
        rows.append(row)
    return sorted(rows, key=lambda item: (str(item.get("horizon", "")), -item["samples"], str(item)))


def summarize_alignment(entries: pd.DataFrame) -> List[Dict[str, Any]]:
    if entries.empty:
        return []
    matched = entries[(~entries["is_dca"]) & entries["matched_closed"]].copy()
    if matched.empty:
        return []
    rows: List[Dict[str, Any]] = []
    for tf in ("1h", "4h", "15m"):
        align_col = f"rsi_{tf}_alignment"
        matched[align_col] = [
            rsi_side_alignment(side, direction)
            for side, direction in zip(matched["side"], matched[f"rsi_{tf}_dir"])
        ]
        for alignment, group in matched.groupby(align_col, dropna=False):
            count = int(len(group))
            wins = int(group["matched_win"].sum())
            rows.append(
                {
                    "timeframe": tf,
                    "alignment": alignment,
                    "entries": count,
                    "wins": wins,
                    "losses": count - wins,
                    "win_rate": round(wins / count, 4) if count else 0.0,
                    "pnl": round(float(group["matched_realized_pnl"].sum()), 6),
                    "avg_pnl": round(float(group["matched_realized_pnl"].mean()), 6) if count else 0.0,
                }
            )
    return sorted(rows, key=lambda item: (item["timeframe"], item["alignment"]))


def markdown_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    if not rows:
        return "_No data._\n"
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for col in columns:
            val = row.get(col, "")
            if isinstance(val, float):
                if col.endswith("rate"):
                    values.append(f"{val * 100:.2f}%")
                else:
                    values.append(f"{val:.6f}")
            else:
                values.append(str(val))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def top_loss_cases(entries: pd.DataFrame, limit: int = 10) -> List[Dict[str, Any]]:
    if entries.empty:
        return []
    losses = entries[entries["matched_closed"] & (entries["matched_realized_pnl"] < 0)].copy()
    losses = losses.sort_values("matched_realized_pnl").head(limit)
    columns = [
        "symbol",
        "side",
        "ts",
        "matched_realized_pnl",
        "rsi_15m_dir",
        "rsi_1h_dir",
        "rsi_4h_dir",
        "rsi_weighted_direction_score",
        "reason",
    ]
    rows = []
    for _, row in losses.iterrows():
        item = {col: row.get(col) for col in columns}
        item["ts"] = str(item["ts"])
        item["matched_realized_pnl"] = round(float(item["matched_realized_pnl"]), 6)
        item["rsi_weighted_direction_score"] = round(float(item["rsi_weighted_direction_score"]), 4)
        rows.append(item)
    return rows


def build_report(summary: Dict[str, Any], tables: Dict[str, List[Dict[str, Any]]]) -> str:
    strongest = summary.get("strongest_tf_by_abs_pnl")
    flat_note = summary.get("flat_note", "")
    lines = [
        "# RSI(4) Direction Success Live Review",
        "",
        f"Generated: `{pd.Timestamp.now(tz=BJ_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}`",
        "",
        "## Window",
        "",
        f"- Beijing: `{summary['window_start_bj']}` to `{summary['window_end_bj']}`",
        f"- UTC: `{summary['window_start_utc']}` to `{summary['window_end_utc']}`",
        "",
        "## Data Quality",
        "",
        "- RSI fields were not available directly in compacted `fund_flow_attribution.jsonl` metadata.",
        "- RSI(4) was recomputed from per-symbol attribution `context.price` snapshots.",
        "- This is a close-like reconstruction, not exchange OHLC RSI. Buckets with small sample counts should not be overfit.",
        "",
        "## Executive Summary",
        "",
        f"- Decision events analyzed: `{summary['decision_events']}`",
        f"- Entry decisions: `{summary['entry_decisions']}`",
        f"- Non-DCA entry decisions: `{summary['non_dca_entries']}`",
        f"- Deduped fills in window: `{summary['deduped_fills']}`",
        f"- Matched closed non-DCA entries: `{summary['matched_closed_entries']}`",
        f"- Matched closed PnL: `{summary['matched_closed_pnl']:.6f} USDT`",
        f"- Matched win rate: `{summary['matched_win_rate'] * 100:.2f}%`",
        f"- Strongest timeframe by absolute matched PnL split: `{strongest or 'n/a'}`",
        f"- Flat-threshold read: {flat_note}",
        "",
        "## RSI Side Alignment Summary",
        "",
        "Aligned means RSI direction supports the trade side: `up` for LONG, `down` for SHORT. Opposed means RSI points against the trade side.",
        "",
        markdown_table(tables["alignment"], ["timeframe", "alignment", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "Read: 1H alignment is the main check for whether the proposed 1H anchor has empirical support in this slice; 15m should be treated as trigger confirmation only when it does not fight 1H/4H.",
        "",
        "## Matched Entry Outcomes By RSI Direction",
        "",
        "### 1H RSI Direction",
        markdown_table(tables["by_1h"], ["rsi_1h_dir", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "### 4H RSI Direction",
        markdown_table(tables["by_4h"], ["rsi_4h_dir", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "### 15m RSI Direction",
        markdown_table(tables["by_15m"], ["rsi_15m_dir", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "### 1H + 4H Combo",
        markdown_table(tables["by_1h_4h"], ["rsi_1h_4h_combo", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "### 1H + 15m Combo",
        markdown_table(tables["by_1h_15m"], ["rsi_1h_15m_combo", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "### 15m + 1H + 4H Combo",
        markdown_table(tables["by_3tf"], ["rsi_3tf_combo", "side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "## Forward Return Direction Check",
        "",
        "This auxiliary view uses all decision snapshots with non-flat weighted RSI consensus and checks whether price moved in the RSI consensus direction.",
        "",
        markdown_table(
            tables["forward_by_horizon"],
            ["horizon", "rsi_consensus_direction", "samples", "correct", "success_rate", "avg_forward_return"],
        ),
        "## Top Matched Loss Cases",
        "",
        markdown_table(
            tables["top_losses"],
            [
                "symbol",
                "side",
                "ts",
                "matched_realized_pnl",
                "rsi_15m_dir",
                "rsi_1h_dir",
                "rsi_4h_dir",
                "rsi_weighted_direction_score",
                "reason",
            ],
        ),
        "## Bottom Line",
        "",
        summary.get("bottom_line", ""),
        "",
    ]
    return "\n".join(lines)


def compute_analysis(logs_root: Path, start_bj: pd.Timestamp) -> tuple[Dict[str, Any], pd.DataFrame, Dict[str, List[Dict[str, Any]]]]:
    start_utc = start_bj.tz_convert(UTC)
    all_decisions = load_all_decision_records(logs_root)
    if all_decisions.empty:
        raise RuntimeError(f"No attribution decision records found under {logs_root}")
    enriched = add_rsi_features(all_decisions)
    window_decisions = enriched[enriched["ts"] >= start_utc].copy()
    if window_decisions.empty:
        raise RuntimeError(f"No decision records found after {start_utc}")
    window_end_utc = window_decisions["ts"].max()

    fills = normalize_fills(load_fills(logs_root), start_utc)
    entries = build_entries(window_decisions, start_utc)
    entries = match_entry_pnl(entries, fills)
    matched_non_dca = entries[(~entries.get("is_dca", False)) & entries.get("matched_closed", False)] if not entries.empty else pd.DataFrame()
    forward = build_forward_stats(enriched, start_utc)

    tables = {
        "by_1h": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_1h_dir", "side"]),
        "by_4h": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_4h_dir", "side"]),
        "by_15m": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_15m_dir", "side"]),
        "alignment": summarize_alignment(entries),
        "by_1h_4h": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_1h_4h_combo", "side"]),
        "by_1h_15m": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_1h_15m_combo", "side"]),
        "by_3tf": summarize_entries(entries[~entries["is_dca"]] if not entries.empty else entries, ["rsi_3tf_combo", "side"]),
        "forward_by_horizon": summarize_forward(forward, ["horizon", "rsi_consensus_direction"]),
        "top_losses": top_loss_cases(entries[~entries["is_dca"]] if not entries.empty else entries),
    }

    matched_count = int(len(matched_non_dca)) if not matched_non_dca.empty else 0
    matched_pnl = float(matched_non_dca["matched_realized_pnl"].sum()) if matched_count else 0.0
    matched_wins = int(matched_non_dca["matched_win"].sum()) if matched_count else 0
    matched_win_rate = matched_wins / matched_count if matched_count else 0.0

    strongest_tf = strongest_timeframe(tables)
    flat_note = evaluate_flat_note(entries)
    bottom_line = make_bottom_line(tables, matched_count)
    summary = {
        "window_start_bj": str(start_bj),
        "window_start_utc": str(start_utc),
        "window_end_utc": str(window_end_utc),
        "window_end_bj": str(window_end_utc.tz_convert(BJ_TZ)),
        "decision_events": int(len(window_decisions)),
        "entry_decisions": int(len(entries)),
        "non_dca_entries": int((~entries["is_dca"]).sum()) if not entries.empty else 0,
        "dca_entries": int(entries["is_dca"].sum()) if not entries.empty else 0,
        "deduped_fills": int(len(fills)),
        "matched_closed_entries": matched_count,
        "matched_closed_pnl": matched_pnl,
        "matched_wins": matched_wins,
        "matched_win_rate": matched_win_rate,
        "strongest_tf_by_abs_pnl": strongest_tf,
        "flat_note": flat_note,
        "bottom_line": bottom_line,
        "rsi_period": RSI_PERIOD,
        "flat_threshold": FLAT_THRESHOLD,
        "tf_weights": TF_WEIGHTS,
    }
    return summary, entries, tables


def strongest_timeframe(tables: Dict[str, List[Dict[str, Any]]]) -> str:
    alignment = tables.get("alignment", [])
    candidates = [
        row
        for row in alignment
        if row.get("alignment") == "aligned" and int(row.get("entries", 0)) >= 5
    ]
    if not candidates:
        return ""
    best = max(
        candidates,
        key=lambda row: (float(row.get("win_rate", 0.0)), float(row.get("pnl", 0.0)), int(row.get("entries", 0))),
    )
    return str(best.get("timeframe") or "")


def evaluate_flat_note(entries: pd.DataFrame) -> str:
    if entries.empty or "matched_closed" not in entries:
        return "样本不足，无法评价 flat bucket。"
    matched = entries[(~entries["is_dca"]) & entries["matched_closed"]]
    if matched.empty:
        return "样本不足，无法评价 flat bucket。"
    notes = []
    for tf in ("1h", "4h", "15m"):
        col = f"rsi_{tf}_dir"
        flat = matched[matched[col] == "flat"]
        non_flat = matched[matched[col].isin(["up", "down"])]
        if len(flat) < 3 or len(non_flat) < 3:
            notes.append(f"{tf}: flat/non-flat 样本偏少")
            continue
        flat_wr = float((flat["matched_realized_pnl"] > 0).mean())
        non_wr = float((non_flat["matched_realized_pnl"] > 0).mean())
        notes.append(f"{tf}: flat {flat_wr * 100:.1f}% vs non-flat {non_wr * 100:.1f}%")
    return "; ".join(notes)


def make_bottom_line(tables: Dict[str, List[Dict[str, Any]]], matched_count: int) -> str:
    if matched_count < 10:
        return (
            "Matched closed entry sample is small, so use this as a diagnostic slice rather than a parameter verdict. "
            "The safer next step is to keep logging full RSI metadata and rerun this on a larger live window."
        )
    forward = tables.get("forward_by_horizon", [])
    if forward:
        best = max(forward, key=lambda row: float(row.get("success_rate", 0.0)))
        alignment = tables.get("alignment", [])
        aligned = [row for row in alignment if row.get("alignment") == "aligned" and int(row.get("entries", 0)) >= 5]
        best_tf = strongest_timeframe(tables)
        best_tf_line = ""
        if aligned and best_tf:
            row = next((item for item in aligned if item.get("timeframe") == best_tf), None)
            if row:
                best_tf_line = (
                    f" In matched entries, {best_tf} RSI side-alignment was strongest "
                    f"({float(row.get('win_rate', 0.0)) * 100:.2f}% win rate, "
                    f"{float(row.get('pnl', 0.0)):.4f} USDT PnL)."
                )
        return (
            f"Forward-return diagnostics are strongest for {best.get('horizon')} "
            f"{best.get('rsi_consensus_direction')} consensus at {float(best.get('success_rate', 0.0)) * 100:.2f}% success. "
            "Matched entry buckets should be interpreted with their sample counts."
            + best_tf_line
        )
    return "No forward-return diagnostics were available; rely only on matched closed entry buckets."


def write_outputs(summary: Dict[str, Any], entries: pd.DataFrame, tables: Dict[str, List[Dict[str, Any]]], out: Path, report: Path, entries_csv: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    entries_csv.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "tables": tables}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    entries_out = entries.copy()
    for col in entries_out.columns:
        if pd.api.types.is_datetime64_any_dtype(entries_out[col]):
            entries_out[col] = entries_out[col].astype(str)
    entries_out.to_csv(entries_csv, index=False, encoding="utf-8-sig")
    report.write_text(build_report(summary, tables), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze RSI(4) direction vs live entry success from compact fund-flow logs.")
    parser.add_argument("--start-bj", required=True, help='Beijing start time, e.g. "2026-05-08 19:00:00"')
    parser.add_argument("--logs-root", default="logs/2026-05", help="Monthly log root")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--report", required=True, help="Output Markdown report path")
    parser.add_argument("--entries-csv", default="output/analysis/rsi4_direction_success_entries.csv", help="Output entries CSV path")
    args = parser.parse_args(argv)

    start_bj = parse_bj_timestamp(args.start_bj)
    summary, entries, tables = compute_analysis(Path(args.logs_root), start_bj)
    write_outputs(summary, entries, tables, Path(args.out), Path(args.report), Path(args.entries_csv))
    print(f"summary: {args.out}")
    print(f"entries: {args.entries_csv}")
    print(f"report: {args.report}")
    print(f"matched_closed_entries: {summary['matched_closed_entries']}")
    print(f"matched_win_rate: {summary['matched_win_rate'] * 100:.2f}%")


if __name__ == "__main__":
    main()
