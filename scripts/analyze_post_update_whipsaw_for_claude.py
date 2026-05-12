from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


UTC = "UTC"
BJ_TZ = "Asia/Shanghai"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _parse_utc(value: Any) -> Optional[pd.Timestamp]:
    if value is None or value == "":
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(UTC)
    return ts.tz_convert(UTC)


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
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


def _side_from_operation(operation: str) -> str:
    op = str(operation or "").lower()
    if op == "buy":
        return "LONG"
    if op == "sell":
        return "SHORT"
    return ""


def _fill_closes_side(fill_side: str) -> str:
    side = str(fill_side or "")
    if side in {"卖出", "SELL", "sell"}:
        return "LONG"
    if side in {"买入", "BUY", "buy"}:
        return "SHORT"
    return ""


def _find_latest_ts(log_dirs: List[Path]) -> pd.Timestamp:
    latest: Optional[pd.Timestamp] = None
    for root in log_dirs:
        path = root / "fund_flow_attribution.jsonl"
        if not path.exists():
            continue
        for rec in _iter_jsonl(path):
            ts = _parse_utc(rec.get("ts"))
            if ts is not None and (latest is None or ts > latest):
                latest = ts
    if latest is not None:
        return latest
    mtimes = [pd.Timestamp(p.stat().st_mtime, unit="s", tz=UTC) for root in log_dirs for p in root.rglob("*") if p.is_file()]
    if not mtimes:
        raise FileNotFoundError("no log files found")
    return max(mtimes)


def load_decisions(log_dirs: List[Path], start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for root in log_dirs:
        path = root / "fund_flow_attribution.jsonl"
        if not path.exists():
            continue
        for rec in _iter_jsonl(path):
            ts = _parse_utc(rec.get("ts"))
            if ts is None or ts < start_utc or ts > end_utc or rec.get("event") != "decision":
                continue
            decision = rec.get("decision") if isinstance(rec.get("decision"), dict) else {}
            context = rec.get("context") if isinstance(rec.get("context"), dict) else {}
            portfolio = context.get("portfolio") if isinstance(context.get("portfolio"), dict) else {}
            flow = context.get("flow_context") if isinstance(context.get("flow_context"), dict) else {}
            md = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
            op = str(decision.get("operation") or "").lower()
            rows.append(
                {
                    "ts": ts,
                    "bj": ts.tz_convert(BJ_TZ),
                    "symbol": str(context.get("symbol") or decision.get("symbol") or "").upper(),
                    "operation": op,
                    "side": _side_from_operation(op),
                    "target_portion": _to_float(decision.get("target_portion_of_balance"), 0.0),
                    "leverage": int(_to_float(decision.get("leverage"), 0.0)),
                    "reason": str(decision.get("reason") or ""),
                    "price": _to_float(context.get("price"), math.nan),
                    "cash": _to_float(portfolio.get("cash"), math.nan),
                    "total_assets": _to_float(portfolio.get("total_assets"), math.nan),
                    "position_count": _to_float(portfolio.get("position_count"), math.nan),
                    "active_symbols": ",".join(str(x) for x in (portfolio.get("active_symbols") or [])),
                    "regime": md.get("regime"),
                    "regime_adx": _to_float(md.get("regime_adx"), math.nan),
                    "regime_atr_pct": _to_float(md.get("regime_atr_pct"), math.nan),
                    "vwap_score": _to_float(md.get("vwap_score"), math.nan),
                    "score_volume": _to_float(md.get("score_volume"), math.nan),
                    "signal_score": _to_float(md.get("signal_score"), math.nan),
                    "flow_cvd_ratio": _to_float(flow.get("cvd_ratio"), math.nan),
                    "flow_oi_delta_ratio": _to_float(flow.get("oi_delta_ratio"), math.nan),
                    "source_file": str(path),
                }
            )
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True) if rows else pd.DataFrame()


def load_fills(log_dirs: List[Path], start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for root in log_dirs:
        path = root / "trade_fills_utc.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if not df.empty:
            df["source_file"] = str(path)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    fills = pd.concat(frames, ignore_index=True)
    subset = [col for col in ["成交ID", "订单ID", "合约", "时间(UTC)", "方向", "价格", "数量"] if col in fills.columns]
    fills = fills.drop_duplicates(subset=subset).copy()
    fills["ts"] = pd.to_datetime(fills["时间(UTC)"], utc=True, errors="coerce")
    fills["bj"] = fills["ts"].dt.tz_convert(BJ_TZ)
    fills["symbol"] = fills["合约"].astype(str).str.upper()
    fills["fill_side"] = fills["方向"].astype(str)
    fills["price"] = pd.to_numeric(fills["价格"], errors="coerce")
    fills["quantity"] = pd.to_numeric(fills["数量"], errors="coerce")
    fills["notional"] = pd.to_numeric(fills["成交额"], errors="coerce")
    fills["fee"] = pd.to_numeric(fills["手续费"], errors="coerce").fillna(0.0)
    fills["realized_pnl"] = pd.to_numeric(fills["已实现盈亏"], errors="coerce").fillna(0.0)
    fills["closes_side"] = fills["fill_side"].map(_fill_closes_side)
    return fills[fills["ts"].notna() & (fills["ts"] >= start_utc) & (fills["ts"] <= end_utc)].sort_values("ts").reset_index(drop=True)


def build_entries(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame()
    entries = decisions[(decisions["operation"].isin(["buy", "sell"])) & (decisions["target_portion"] > 0)].copy()
    entries["is_dca"] = entries["reason"].str.contains("DCA|马丁", case=False, regex=True, na=False)
    entries["matched_realized_pnl"] = 0.0
    entries["matched_close_fills"] = 0
    entries["matched_closed"] = False
    entries["accounting"] = (pd.to_numeric(entries["target_portion"], errors="coerce").fillna(0.0) >= 0.01).map(
        {True: "meaningful", False: "micro"}
    )
    return entries.reset_index(drop=True)


def match_entries(entries: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    if entries.empty or fills.empty:
        return entries
    out = entries.copy()
    normal = out[~out["is_dca"]].copy()
    for fill in fills.itertuples(index=False):
        pnl = _to_float(getattr(fill, "realized_pnl", 0.0), 0.0)
        if abs(pnl) <= 1e-12:
            continue
        candidates = normal[
            (normal["symbol"] == getattr(fill, "symbol"))
            & (normal["side"] == getattr(fill, "closes_side"))
            & (normal["ts"] <= getattr(fill, "ts"))
        ]
        if candidates.empty:
            continue
        idx = candidates.sort_values("ts").iloc[-1].name
        out.loc[idx, "matched_realized_pnl"] += pnl
        out.loc[idx, "matched_close_fills"] += 1
        out.loc[idx, "matched_closed"] = True
    out["matched_win"] = out["matched_realized_pnl"] > 0
    return out


def portfolio_summary(decisions: pd.DataFrame) -> Dict[str, Any]:
    if decisions.empty:
        return {}
    df = decisions[["ts", "bj", "cash", "total_assets", "position_count", "active_symbols"]].copy()
    for col in ["cash", "total_assets", "position_count"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["total_assets"].notna()]
    if df.empty:
        return {}
    start = df.iloc[0]
    end = df.iloc[-1]
    high = df.loc[df["total_assets"].idxmax()]
    low = df.loc[df["total_assets"].idxmin()]

    def pack(row: pd.Series) -> Dict[str, Any]:
        return {
            "bj": str(row["bj"]),
            "cash": round(float(row["cash"]), 6) if pd.notna(row["cash"]) else None,
            "total_assets": round(float(row["total_assets"]), 6),
            "position_count": int(row["position_count"]) if pd.notna(row["position_count"]) else None,
            "active_symbols": row.get("active_symbols", ""),
        }

    return {
        "start": pack(start),
        "end": pack(end),
        "high": pack(high),
        "low": pack(low),
        "start_to_end_delta": round(float(end["total_assets"] - start["total_assets"]), 6),
        "start_to_end_pct": round(float((end["total_assets"] - start["total_assets"]) / start["total_assets"]), 6),
        "high_to_low_delta": round(float(low["total_assets"] - high["total_assets"]), 6),
        "high_to_low_pct": round(float((low["total_assets"] - high["total_assets"]) / high["total_assets"]), 6),
        "low_to_end_delta": round(float(end["total_assets"] - low["total_assets"]), 6),
        "low_to_end_pct": round(float((end["total_assets"] - low["total_assets"]) / low["total_assets"]), 6),
    }


def table(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    if not rows:
        return "_No data._\n"
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        vals: List[str] = []
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, float):
                if "rate" in col or col.endswith("_pct"):
                    vals.append(f"{val*100:.2f}%")
                else:
                    vals.append(f"{val:.6f}")
            else:
                vals.append(str(val))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out) + "\n"


def summarize_entries(entries: pd.DataFrame, by: List[str]) -> List[Dict[str, Any]]:
    if entries.empty:
        return []
    rows: List[Dict[str, Any]] = []
    for keys, group in entries.groupby(by, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(by, keys)}
        row.update(
            entries=int(len(group)),
            avg_portion=round(float(group["target_portion"].mean()), 6),
            pnl=round(float(group["matched_realized_pnl"].sum()), 6) if "matched_realized_pnl" in group else 0.0,
            closed=int(group["matched_closed"].sum()) if "matched_closed" in group else 0,
        )
        rows.append(row)
    return sorted(rows, key=lambda r: (str(r.get(by[0], "")), float(r.get("pnl", 0.0))))


def price_path(decisions: pd.DataFrame, symbols: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if decisions.empty:
        return rows
    for symbol in symbols:
        group = decisions[(decisions["symbol"] == symbol) & decisions["price"].notna()].copy()
        if group.empty:
            continue
        start = group.iloc[0]
        end = group.iloc[-1]
        high = group.loc[group["price"].idxmax()]
        low = group.loc[group["price"].idxmin()]
        rows.append(
            {
                "symbol": symbol,
                "start_bj": str(start["bj"])[:19],
                "start_price": round(float(start["price"]), 8),
                "high_bj": str(high["bj"])[:19],
                "high_price": round(float(high["price"]), 8),
                "low_bj": str(low["bj"])[:19],
                "low_price": round(float(low["price"]), 8),
                "end_price": round(float(end["price"]), 8),
                "start_to_high_pct": round(float(high["price"] / start["price"] - 1.0), 6) if float(start["price"]) else 0.0,
                "high_to_end_pct": round(float(end["price"] / high["price"] - 1.0), 6) if float(high["price"]) else 0.0,
            }
        )
    return rows


def parse_runtime(log_dirs: List[Path], start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> Dict[str, Any]:
    gate_rows: List[Dict[str, Any]] = []
    score_rows: List[Dict[str, Any]] = []
    marker_counts: Counter[str] = Counter()
    examples: Dict[str, List[str]] = defaultdict(list)
    current_ts: Optional[pd.Timestamp] = None
    cycle_re = re.compile(r"=== FUND_FLOW cycle .*? @ ([0-9-]+ [0-9:]+) UTC ===")
    score_re = re.compile(
        r"MACD_V2评分: stage=([^,]+), dir=([^,]+), primary=4H:([0-9.]+)\(([^)]+)\), "
        r"1H=([0-9.]+)\(([^)]+)\).*?VWAPq=([0-9.]+), VWAPa=([0-9.]+).*?"
        r"total=([0-9.]+)/([0-9.]+).*?veto=([^,\s]+)"
    )
    patterns = {
        "vwap_hard_block": "vwap_hard_block",
        "rsi_1h_direction_block": "rsi_1h_direction_block",
        "rsi_1h_direction_against_veto": "rsi_1h_direction_against_veto",
        "rsi_1h_direction_flat_veto": "rsi_1h_direction_flat_veto",
        "rsi_15m_extreme_veto": "rsi_15m_extreme_veto",
        "threshold_low": "信号评分低于阈值",
        "target_below_min_open": "目标开仓比例低于最小下单阈值",
        "active_symbol_capacity": "active_symbol_capacity",
        "dca_hold": "DCA未触发",
        "short_regime_guard": "short_regime_guard",
        "dual_leg_allowed": "极端行情允许双腿对冲",
    }
    for root in log_dirs:
        for path in sorted(root.glob("runtime.out*.log")):
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    cycle_match = cycle_re.search(line)
                    if cycle_match:
                        current_ts = pd.Timestamp(cycle_match.group(1), tz=UTC)
                    in_window = current_ts is not None and start_utc <= current_ts <= end_utc
                    if not in_window:
                        continue
                    for key, pattern in patterns.items():
                        if pattern in line:
                            marker_counts[key] += 1
                            if len(examples[key]) < 5:
                                examples[key].append(line.strip()[:260])
                    if "ENTRY_GATE_BLOCK" in line:
                        raw = line.split("ENTRY_GATE_BLOCK", 1)[1].strip()
                        try:
                            payload = json.loads(raw)
                        except Exception:
                            continue
                        payload["cycle_ts"] = current_ts
                        payload["cycle_bj"] = current_ts.tz_convert(BJ_TZ) if current_ts is not None else None
                        gate_rows.append(payload)
                    if "MACD_V2评分:" in line:
                        m = score_re.search(line)
                        if m:
                            score_rows.append(
                                {
                                    "cycle_ts": current_ts,
                                    "cycle_bj": current_ts.tz_convert(BJ_TZ) if current_ts is not None else None,
                                    "stage": m.group(1),
                                    "direction": m.group(2),
                                    "score_4h": _to_float(m.group(3), 0.0),
                                    "signal_4h": m.group(4),
                                    "score_1h": _to_float(m.group(5), 0.0),
                                    "signal_1h": m.group(6),
                                    "vwap_quality": _to_float(m.group(7), 0.0),
                                    "vwap_alpha": _to_float(m.group(8), 0.0),
                                    "total_score": _to_float(m.group(9), 0.0),
                                    "threshold": _to_float(m.group(10), 0.0),
                                    "veto": m.group(11),
                                    "raw": line.strip()[:300],
                                }
                            )
    gates = pd.DataFrame(gate_rows)
    scores = pd.DataFrame(score_rows)
    return {"counts": marker_counts, "examples": examples, "gates": gates, "scores": scores}


def day_baseline(root: Path) -> Dict[str, Any]:
    if not root.exists():
        return {}
    decisions = load_decisions([root], pd.Timestamp.min.tz_localize(UTC), pd.Timestamp.max.tz_localize(UTC))
    fills = load_fills([root], pd.Timestamp.min.tz_localize(UTC), pd.Timestamp.max.tz_localize(UTC))
    entries = build_entries(decisions)
    pf = portfolio_summary(decisions)
    return {
        "day": root.name,
        "decision_events": int(len(decisions)),
        "entry_decisions": int(len(entries)),
        "buy_entries": int((entries["operation"] == "buy").sum()) if not entries.empty else 0,
        "sell_entries": int((entries["operation"] == "sell").sum()) if not entries.empty else 0,
        "fill_pnl": round(float(fills["realized_pnl"].sum()), 6) if not fills.empty else 0.0,
        "assets_start": pf.get("start", {}).get("total_assets"),
        "assets_end": pf.get("end", {}).get("total_assets"),
        "asset_delta_pct": pf.get("start_to_end_pct"),
        "asset_high_to_low_pct": pf.get("high_to_low_pct"),
    }


def build_report(
    *,
    log_dirs: List[Path],
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
    decisions: pd.DataFrame,
    fills: pd.DataFrame,
    entries: pd.DataFrame,
    runtime: Dict[str, Any],
    baseline_0508: Dict[str, Any],
    prev_doc: Path,
) -> str:
    matched = entries[entries["matched_closed"]].copy() if not entries.empty else pd.DataFrame()
    pf = portfolio_summary(decisions)
    gates: pd.DataFrame = runtime["gates"]
    scores: pd.DataFrame = runtime["scores"]
    counts: Counter[str] = runtime["counts"]
    examples: Dict[str, List[str]] = runtime["examples"]

    fill_by_symbol = (
        [
            {"symbol": symbol, "fills": int(len(group)), "pnl": round(float(group["realized_pnl"].sum()), 6), "notional": round(float(group["notional"].sum()), 6)}
            for symbol, group in fills.groupby("symbol")
        ]
        if not fills.empty
        else []
    )
    fill_by_symbol = sorted(fill_by_symbol, key=lambda row: row["pnl"])

    top_losses = []
    if not fills.empty:
        for _, row in fills[fills["realized_pnl"] < 0].sort_values("realized_pnl").head(12).iterrows():
            top_losses.append(
                {
                    "bj": str(row["bj"])[:19],
                    "symbol": row["symbol"],
                    "fill_side": row["fill_side"],
                    "price": round(float(row["price"]), 8),
                    "notional": round(float(row["notional"]), 6),
                    "pnl": round(float(row["realized_pnl"]), 6),
                }
            )

    entry_rows = []
    if not entries.empty:
        for _, row in entries.iterrows():
            entry_rows.append(
                {
                    "bj": str(row["bj"])[:19],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "portion": round(float(row["target_portion"]), 6),
                    "pnl": round(float(row.get("matched_realized_pnl", 0.0)), 6),
                    "regime": row["regime"],
                    "adx": round(float(row["regime_adx"]), 2) if math.isfinite(float(row["regime_adx"])) else "",
                    "atr_pct": round(float(row["regime_atr_pct"]), 6) if math.isfinite(float(row["regime_atr_pct"])) else "",
                    "vwap": round(float(row["vwap_score"]), 4) if math.isfinite(float(row["vwap_score"])) else "",
                    "reason": row["reason"],
                }
            )

    gate_summary = []
    if not gates.empty:
        for gate, group in gates.groupby("gate", dropna=False):
            gate_summary.append(
                {
                    "gate": gate,
                    "count": int(len(group)),
                    "avg_score": round(float(pd.to_numeric(group.get("signal_score"), errors="coerce").mean()), 6),
                    "top_symbols": ", ".join(group["symbol"].astype(str).value_counts().head(5).index.tolist()),
                }
            )
        gate_summary = sorted(gate_summary, key=lambda row: row["count"], reverse=True)

    score_stage_summary = []
    if not scores.empty:
        for stage, group in scores.groupby("stage", dropna=False):
            score_stage_summary.append(
                {
                    "stage": stage,
                    "count": int(len(group)),
                    "avg_total": round(float(group["total_score"].mean()), 6),
                    "top_signal_1h": ", ".join(group["signal_1h"].value_counts().head(4).index.tolist()),
                }
            )
        score_stage_summary = sorted(score_stage_summary, key=lambda row: row["count"], reverse=True)

    top_blocked_scores = []
    if not gates.empty and "signal_score" in gates:
        gate_copy = gates.copy()
        gate_copy["signal_score_num"] = pd.to_numeric(gate_copy["signal_score"], errors="coerce")
        for _, row in gate_copy.sort_values("signal_score_num", ascending=False).head(12).iterrows():
            top_blocked_scores.append(
                {
                    "bj": str(row.get("cycle_bj"))[:19],
                    "symbol": row.get("symbol"),
                    "side": row.get("side"),
                    "gate": row.get("gate"),
                    "score": round(float(row.get("signal_score_num")), 6) if pd.notna(row.get("signal_score_num")) else "",
                    "threshold": row.get("signal_threshold"),
                    "value": row.get("value"),
                    "vwap": row.get("vwap_score"),
                    "signal_1h": row.get("signal_1h"),
                    "signal_4h": row.get("signal_4h"),
                }
            )

    btc_path = price_path(decisions, ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT"])
    op_counts = decisions["operation"].value_counts().to_dict() if not decisions.empty else {}
    entries_by_side = summarize_entries(entries, ["side"]) if not entries.empty else []
    entries_by_reason_family = []
    if not entries.empty:
        tmp = entries.copy()
        tmp["family"] = tmp["reason"].str.replace(r"_vwap_[0-9.]+", "", regex=True)
        entries_by_reason_family = summarize_entries(tmp, ["family"])

    lines = [
        "# 2026-05-12 Post-Update Whipsaw Attribution For Claude",
        "",
        f"**审阅窗口**: `{start_utc.tz_convert(BJ_TZ)}` -> `{end_utc.tz_convert(BJ_TZ)}`",
        f"**日志来源**: `{'; '.join(str(p) for p in log_dirs)}`",
        f"**对照文档**: `{prev_doc}`",
        "",
        "## Executive Summary",
        "",
        f"- 最新 24H 决策事件 `{len(decisions)}`，其中 `BUY={op_counts.get('buy', 0)}`、`SELL={op_counts.get('sell', 0)}`、`HOLD={op_counts.get('hold', 0)}`。",
        f"- 去重成交 `{len(fills)}`，realized PnL `{float(fills['realized_pnl'].sum()) if not fills.empty else 0.0:.6f} USDT`。",
        f"- 权益从 `{pf.get('start', {}).get('total_assets')}` 到 `{pf.get('end', {}).get('total_assets')}`，净变化 `{pf.get('start_to_end_delta')} USDT` (`{pf.get('start_to_end_pct', 0.0):.2%}`)。",
        f"- 低点 `{pf.get('low', {}).get('bj')}` total_assets=`{pf.get('low', {}).get('total_assets')}`，随后到窗口末端修复 `{pf.get('low_to_end_delta')} USDT` (`{pf.get('low_to_end_pct', 0.0):.2%}`)。",
        "- 结论：策略不是完全停摆，而是上升段只开了 2 笔 LONG，且都在上升后半段/回落前入场；下跌段直到 14:00 BJ 后才集中开 SHORT，错过 08:00-09:30 的主要下跌。",
        "- 双腿对冲目标没有真正实现：本窗口没有出现 `dual_leg_allowed` 日志，反向保护只存在于配置和极端 ATR 条件里，未形成 BTC 主导冲击时的实时对冲。",
        "- 昨天的 P0 配置修复有副作用：`min_vwap_score_for_entry=0.12` 和 dynamic sizing 降低了低 VWAP 追涨风险，但也把大量信号压成 `target < min_open_portion`，尤其是高分 SHORT 只剩微仓位、被最小下单阈值过滤。",
        "",
        "## Portfolio Timeline",
        "",
        "```json",
        json.dumps(pf, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Market Path Proxy",
        "",
        table(btc_path, ["symbol", "start_bj", "start_price", "high_bj", "high_price", "low_bj", "low_price", "end_price", "start_to_high_pct", "high_to_end_pct"]),
        "",
        "## Actual Entries After Update",
        "",
        table(entry_rows, ["bj", "symbol", "side", "portion", "pnl", "regime", "adx", "atr_pct", "vwap", "reason"]),
        "",
        "### Entry Summary By Side",
        "",
        table(entries_by_side, ["side", "entries", "avg_portion", "closed", "pnl"]),
        "",
        "### Entry Summary By Family",
        "",
        table(entries_by_reason_family, ["family", "entries", "avg_portion", "closed", "pnl"]),
        "",
        "## Fill PnL By Symbol",
        "",
        table(fill_by_symbol, ["symbol", "fills", "pnl", "notional"]),
        "",
        "## Top Realized Losses",
        "",
        table(top_losses, ["bj", "symbol", "fill_side", "price", "notional", "pnl"]),
        "",
        "## Runtime Blockers",
        "",
        "### Marker Counts",
        "",
        "```json",
        json.dumps(dict(counts.most_common()), ensure_ascii=False, indent=2),
        "```",
        "",
        "### Entry Gate Blocks",
        "",
        table(gate_summary, ["gate", "count", "avg_score", "top_symbols"]),
        "",
        "### Highest-Score Blocked Entry Candidates",
        "",
        table(top_blocked_scores, ["bj", "symbol", "side", "gate", "score", "threshold", "value", "vwap", "signal_1h", "signal_4h"]),
        "",
        "### MACD_V2 Score Stages",
        "",
        table(score_stage_summary, ["stage", "count", "avg_total", "top_signal_1h"]),
        "",
        "## 05-08 Comparison",
        "",
        table([baseline_0508], ["day", "decision_events", "entry_decisions", "buy_entries", "sell_entries", "fill_pnl", "assets_start", "assets_end", "asset_delta_pct", "asset_high_to_low_pct"]),
        "",
        "05-08 的核心差异：当时主导交易族是 `LONG + red_bar_growing`，且允许 `vwap_score=0.25` 的大仓进入；这在微涨/顺风市场里捕捉了大部分上涨。05-12 更新后，低 VWAP floor 和 dynamic sizing 把这类早期追涨能力显著压低，但系统又没有引入可替代的 BTC shock / trend-following breakout 入口。",
        "",
        "## Root Cause Findings",
        "",
        "### [CRITICAL-1] 上升段失效：VWAP floor + RSI 方向门控使趋势早期 LONG 变稀疏",
        "",
        "- BTC 22:30 BJ -> 02:30 BJ 从约 `80710.9` 涨到 `81992.0`，约 `+1.59%`；SOL 同期从 `94.97` 附近涨到 `98.15`，约 `+3.35%`。",
        "- 策略在这个上涨段只开了 `BTC LONG 00:15` 和 `DOGE LONG 00:45` 两笔，且都是 `red_bar_growing`、低 VWAP 分 `0.1692/0.1844`，属于被 dynamic sizing 压仓后的晚入场。",
        "- 大量候选停在 `rsi_1h_direction_block / rsi_1h_direction_against_veto / 4H无明确方向`，说明 4H-primary + RSI 方向门控在反转初期太慢。",
        "",
        "### [CRITICAL-2] 下跌段失效：没有 BTC shock 触发器，SHORT 在 14:00 后才集中出现",
        "",
        "- BTC 从 02:30 BJ 高点 `81992` 回落到 09:00 BJ `81030`，再到 19:00 BJ `80631`。",
        "- 08:00-09:30 的下跌主段中，系统已有 BTC/DOGE LONG，未触发双腿对冲；BTC 到 09:36 才止损/平仓，亏 `-0.868 USDT`。",
        "- 14:00 BJ 才出现 `SOL/VET/XLM/AAVE/POL` 等 SHORT 群，说明 4H/MACD 反应滞后，下午才捕捉到跌势尾段。",
        "",
        "### [CRITICAL-3] 双腿对冲没有真实上线到 BTC 主导冲击场景",
        "",
        "- 本窗口 runtime marker 中 `dual_leg_allowed=0`。",
        "- 当前极端双腿 gate 依赖 `current leg loss + signal_score + regime_atr_pct`；而 BTC 跌势初期 ATR 不一定达到阈值，且反向 SHORT 信号常被 RSI/4H/容量/最小仓位挡掉。",
        "- 这解释了为什么“黑天鹅对冲”目标没有兑现：我们只放开了很窄的同品种反向例外，没有实现 BTC return/beta 级别的系统冲击检测。",
        "",
        "### [HIGH-1] shrink cap 覆盖错层：实际成交多为 1H shrinking，不是 4H shrinking",
        "",
        "- 昨天配置 `signal_type_caps.red_bar_shrinking/green_bar_shrinking` 只由 `signal_type_4h` 解析。",
        "- 本窗口主要成交族是 `macd_v2_short_1h_green_bar_shrinking_15m__vwap_*`，但对应 4H 多数是 `green_bar_growing` 或 `flip_bearish`，所以 shrink cap 没有覆盖这些 1H shrink 成交。",
        "- 结果仍出现 `0.2142/0.2856` 的 SHORT 仓位，而不是预期的 `<=0.10`。",
        "",
        "### [HIGH-2] dynamic sizing 与 min_open_portion 相互打架，产生大量高分但不可下单的微仓信号",
        "",
        "- `ENTRY_GATE_BLOCK.min_open_portion` 大量出现，且最高分 blocked 信号包括 `score>0.85` 的 SHORT。",
        "- 典型：`BTCUSDT SHORT score=0.8781` 被压到 `target=0.000175 < min_open=0.06`；`ETHUSDT SHORT score≈0.86` 多次进入 short quality/filter/微仓路径但没有形成有效开仓。",
        "- 这不是单纯门槛过高，而是仓位缩放链把信号质量和可执行性断开了：分数足够，但 target 被压到交易所/系统最小仓位以下。",
        "",
        "### [MEDIUM-1] 05-08 的高收益来自顺风高 beta LONG 暴露，昨天更新削弱了这类暴露但没有补上趋势跟随替代路径",
        "",
        "- 05-08 同口径：`entry_decisions=24`，`BUY=19`，`SELL=5`，fill PnL `+12.1830 USDT`，权益约 `+4.90%`。",
        "- 最新 24H：`entry_decisions=14`，`BUY=2`，`SELL=12`，fill PnL `+0.6609 USDT`，权益约 `+1.61%`，并经历低点回撤。",
        "- 换句话说，昨天更新减少了坏 LONG，但也砍掉了 05-08 那套赚钱的主要来源；下午 SHORT 修复了一部分，但没有替代早盘趋势捕捉能力。",
        "",
        "## Questions For Claude",
        "",
        "1. `signal_type_position_caps` 是否应该同时支持 `signal_type_1h` 和 `signal_type_4h`？当前只 cap 4H，导致 `1h_green_bar_shrinking` 仍能大仓开。",
        "2. `min_open_portion=0.06` 与 dynamic sizing 是否应该联动？对于 score>0.85 但 target 被压到 0.001 的信号，是应放大到 probe 仓、还是彻底不生成 entry？",
        "3. 是否应把 BTC/ETH/BNB 从 tradable 改为 context-only，直到大币独立参数回测通过？本窗口 BTC LONG 是最大亏损之一。",
        "4. 双腿对冲是否应由 BTC 5m/15m return + volume shock 触发，而不是等待单品种 `regime_atr_pct`？",
        "5. 4H-primary + RSI direction hard veto 是否应在 shock/reversal regime 下临时降级为 soft penalty？当前它在上升初期和下跌初期都明显滞后。",
        "6. 是否需要恢复一个 05-08 风格的 trend-following LONG lane，但只在 BTC/ETH context 同向、且 account profit lock 未触发时允许？",
        "",
        "## Suggested Next Experiment",
        "",
        "```text",
        "A. baseline_current_patched",
        "B. current + signal_type_caps_apply_to_1h",
        "C. current + min_open_probe_floor(score>=0.80 -> target=max(target,0.06))",
        "D. current + BTC shock detector (context-only) + hedge shadow orders",
        "E. current + disable BTC/ETH/BNB tradable, keep context-only",
        "F. 05-08-style long lane restored with profit-lock and BTC context guard",
        "```",
        "",
        "验收标准：30D WR >= 72%，成交数 >= 55，总 PnL >= current 95%，最大回撤不高于 current；另需单独检查 05-11/05-12 两个冲击窗口的 high-to-low DD。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log-dir",
        action="append",
        default=[],
        help="Log directory. Can be passed multiple times.",
    )
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--report", default="docs/2026-05-12_post_update_whipsaw_attribution_for_claude.md")
    parser.add_argument("--previous-doc", default="docs/2026-05-11_latest_24h_btc_selloff_loss_attribution_for_claude.md")
    parser.add_argument("--baseline-day-dir", default="logs/2026-05/2026-05-08")
    args = parser.parse_args(argv)

    log_dirs = [Path(p) for p in args.log_dir] or [
        Path("logs/2026-05/2026-05-11"),
        Path("logs/2026-05/2026-05-12-1"),
        Path("logs/2026-05/2026-05-12-2"),
    ]
    end_utc = _find_latest_ts(log_dirs)
    start_utc = end_utc - pd.Timedelta(hours=float(args.hours))
    decisions = load_decisions(log_dirs, start_utc, end_utc)
    fills = load_fills(log_dirs, start_utc, end_utc)
    entries = match_entries(build_entries(decisions), fills)
    runtime = parse_runtime(log_dirs, start_utc, end_utc)
    baseline = day_baseline(Path(args.baseline_day_dir))
    report = build_report(
        log_dirs=log_dirs,
        start_utc=start_utc,
        end_utc=end_utc,
        decisions=decisions,
        fills=fills,
        entries=entries,
        runtime=runtime,
        baseline_0508=baseline,
        prev_doc=Path(args.previous_doc),
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(report_path),
                "window_bj": [str(start_utc.tz_convert(BJ_TZ)), str(end_utc.tz_convert(BJ_TZ))],
                "decisions": int(len(decisions)),
                "fills": int(len(fills)),
                "entries": int(len(entries)),
                "fill_pnl": float(fills["realized_pnl"].sum()) if not fills.empty else 0.0,
                "runtime_counts": dict(runtime["counts"].most_common()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
