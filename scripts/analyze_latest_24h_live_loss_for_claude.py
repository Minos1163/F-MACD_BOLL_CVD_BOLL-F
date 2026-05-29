from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


BJ_TZ = "Asia/Shanghai"
UTC = "UTC"


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


def _find_log_max_ts(logs_root: Path) -> pd.Timestamp:
    latest: Optional[pd.Timestamp] = None
    for path in sorted(logs_root.glob("*/fund_flow_attribution.jsonl")):
        for rec in _iter_jsonl(path):
            ts = _parse_utc(rec.get("ts"))
            if ts is not None and (latest is None or ts > latest):
                latest = ts
    if latest is not None:
        return latest
    mtimes = [pd.Timestamp(p.stat().st_mtime, unit="s", tz=UTC) for p in logs_root.rglob("*") if p.is_file()]
    if not mtimes:
        raise FileNotFoundError(f"no log files under {logs_root}")
    return max(mtimes)


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


def load_decisions(logs_root: Path, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for path in sorted(logs_root.glob("*/fund_flow_attribution.jsonl")):
        for rec in _iter_jsonl(path):
            ts = _parse_utc(rec.get("ts"))
            if ts is None or ts < start_utc or ts > end_utc or rec.get("event") != "decision":
                continue
            decision = rec.get("decision") if isinstance(rec.get("decision"), dict) else {}
            context = rec.get("context") if isinstance(rec.get("context"), dict) else {}
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
                    "cash": _to_float((context.get("portfolio") or {}).get("cash"), math.nan) if isinstance(context.get("portfolio"), dict) else math.nan,
                    "total_assets": _to_float((context.get("portfolio") or {}).get("total_assets"), math.nan) if isinstance(context.get("portfolio"), dict) else math.nan,
                    "position_count": _to_float((context.get("portfolio") or {}).get("position_count"), math.nan) if isinstance(context.get("portfolio"), dict) else math.nan,
                    "regime": md.get("regime"),
                    "regime_adx": _to_float(md.get("regime_adx"), math.nan),
                    "regime_atr_pct": _to_float(md.get("regime_atr_pct"), math.nan),
                    "vwap_score": _to_float(md.get("vwap_score"), math.nan),
                    "score_volume": _to_float(md.get("score_volume"), math.nan),
                    "direction_lock": md.get("direction_lock"),
                    "signal_score": _to_float(md.get("signal_score"), math.nan),
                    "flow_cvd_ratio": _to_float(flow.get("cvd_ratio"), math.nan),
                    "flow_oi_delta_ratio": _to_float(flow.get("oi_delta_ratio"), math.nan),
                    "flow_trap_score": _to_float(flow.get("trap_score"), math.nan),
                    "source_file": str(path),
                }
            )
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True) if rows else pd.DataFrame()


def load_fills(logs_root: Path, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
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
    if decisions.empty or "total_assets" not in decisions.columns:
        return {}
    df = decisions[["ts", "bj", "cash", "total_assets", "position_count"]].copy()
    for col in ["cash", "total_assets", "position_count"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["total_assets"].notna()]
    if df.empty:
        return {}
    start = df.iloc[0]
    end = df.iloc[-1]
    high = df.loc[df["total_assets"].idxmax()]
    low = df.loc[df["total_assets"].idxmin()]
    shock_ts = pd.Timestamp("2026-05-11 08:00:00", tz=BJ_TZ).tz_convert(UTC)
    before_shock = df[df["ts"] < shock_ts].tail(1)
    after_shock = df[df["ts"] >= shock_ts].head(1)
    def pack(row: pd.Series) -> Dict[str, Any]:
        return {
            "bj": str(row["bj"]),
            "cash": round(float(row["cash"]), 6) if pd.notna(row["cash"]) else None,
            "total_assets": round(float(row["total_assets"]), 6),
            "position_count": int(row["position_count"]) if pd.notna(row["position_count"]) else None,
        }
    out = {
        "start": pack(start),
        "end": pack(end),
        "high": pack(high),
        "low": pack(low),
        "start_to_end_delta": round(float(end["total_assets"] - start["total_assets"]), 6),
        "high_to_end_delta": round(float(end["total_assets"] - high["total_assets"]), 6),
        "high_to_end_pct": round(float((end["total_assets"] - high["total_assets"]) / high["total_assets"]), 6) if float(high["total_assets"]) else 0.0,
    }
    if not before_shock.empty:
        out["before_0800_bj"] = pack(before_shock.iloc[0])
    if not after_shock.empty:
        out["after_0800_bj"] = pack(after_shock.iloc[0])
    return out


def summarize(df: pd.DataFrame, cols: List[str]) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    rows: List[Dict[str, Any]] = []
    for keys, group in df.groupby(cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        count = len(group)
        wins = int((group["matched_realized_pnl"] > 0).sum()) if "matched_realized_pnl" in group else 0
        row = {col: key for col, key in zip(cols, keys)}
        row.update(
            entries=int(count),
            wins=wins,
            losses=int(count - wins),
            win_rate=round(wins / count, 4) if count else 0.0,
            pnl=round(float(group["matched_realized_pnl"].sum()), 6) if "matched_realized_pnl" in group else 0.0,
            avg_pnl=round(float(group["matched_realized_pnl"].mean()), 6) if "matched_realized_pnl" in group and count else 0.0,
        )
        rows.append(row)
    return sorted(rows, key=lambda r: (float(r.get("pnl", 0.0)), -int(r.get("entries", 0))))


def table(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    if not rows:
        return "_No data._\n"
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        vals = []
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, float):
                vals.append(f"{val:.6f}" if not col.endswith("rate") else f"{val*100:.2f}%")
            else:
                vals.append(str(val))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out) + "\n"


def load_runtime_markers(logs_root: Path, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> Dict[str, Any]:
    counts: Counter[str] = Counter()
    examples: List[str] = []
    current_mtime = None
    patterns = {
        "reverse_position_suppression": "reverse_position_suppression",
        "vwap_hard_block": "vwap_hard_block",
        "account_cooldown": "account_cooldown",
        "protection_gap": "protection_gap",
        "dual_leg": "双腿",
        "extreme_vol": "极端波动",
        "close": "决策=CLOSE",
    }
    for path in sorted(logs_root.glob("*/runtime.out*.log")):
        mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)
        if mtime < start_utc - pd.Timedelta(hours=8) or mtime > end_utc + pd.Timedelta(hours=8):
            continue
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                for key, pattern in patterns.items():
                    if pattern in line:
                        counts[key] += 1
                        if len(examples) < 20:
                            examples.append(line.strip()[:240])
    return {"counts": dict(counts), "examples": examples}


def build_report(
    *,
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
    decisions: pd.DataFrame,
    fills: pd.DataFrame,
    entries: pd.DataFrame,
    runtime: Dict[str, Any],
    config: Dict[str, Any],
) -> str:
    matched = entries[entries["matched_closed"]].copy() if not entries.empty else pd.DataFrame()
    pf_summary = portfolio_summary(decisions)
    total_fill_pnl = float(fills["realized_pnl"].sum()) if not fills.empty else 0.0
    shock_start = pd.Timestamp("2026-05-11 08:00:00", tz=BJ_TZ).tz_convert(UTC)
    shock_end = shock_start + pd.Timedelta(hours=4)
    shock_fills = fills[(fills["ts"] >= shock_start) & (fills["ts"] <= shock_end)] if not fills.empty else pd.DataFrame()
    before_shock = fills[fills["ts"] < shock_start] if not fills.empty else pd.DataFrame()
    after_shock = fills[fills["ts"] >= shock_start] if not fills.empty else pd.DataFrame()

    top_fill_losses = []
    if not fills.empty:
        for _, row in fills[fills["realized_pnl"] < 0].sort_values("realized_pnl").head(20).iterrows():
            top_fill_losses.append(
                {
                    "bj": str(row["bj"]),
                    "symbol": row["symbol"],
                    "fill_side": row["fill_side"],
                    "closes_side": row["closes_side"],
                    "price": round(float(row["price"]), 8),
                    "quantity": round(float(row["quantity"]), 8),
                    "realized_pnl": round(float(row["realized_pnl"]), 6),
                }
            )

    top_entry_losses = []
    if not matched.empty:
        for _, row in matched[matched["matched_realized_pnl"] < 0].sort_values("matched_realized_pnl").head(20).iterrows():
            top_entry_losses.append(
                {
                    "bj": str(row["bj"]),
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "pnl": round(float(row["matched_realized_pnl"]), 6),
                    "target_portion": round(float(row["target_portion"]), 6),
                    "leverage": int(row["leverage"]),
                    "regime": row["regime"],
                    "atr_pct": round(float(row["regime_atr_pct"]), 6) if math.isfinite(float(row["regime_atr_pct"])) else "",
                    "vwap": round(float(row["vwap_score"]), 4) if math.isfinite(float(row["vwap_score"])) else "",
                    "reason": row["reason"],
                }
            )

    requested = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "HYPEUSDT", "XRPUSDT"]
    trading = config.get("trading", {}) if isinstance(config.get("trading"), dict) else {}
    ff = config.get("fund_flow", {}) if isinstance(config.get("fund_flow"), dict) else {}
    symbols = [str(x).upper() for x in trading.get("symbols", []) if str(x).strip()]
    blacklist = {str(x).upper() for x in ff.get("symbol_blacklist", []) if str(x).strip()}

    lines = [
        "# 2026-05-11 Latest 24H Live Loss Attribution For Claude",
        "",
        f"- Window BJ: `{start_utc.tz_convert(BJ_TZ)}` -> `{end_utc.tz_convert(BJ_TZ)}`",
        f"- Window UTC: `{start_utc}` -> `{end_utc}`",
        "- Note: window is based on latest available log timestamp, not wall-clock now.",
        "",
        "## Executive Summary",
        "",
        f"- Deduped fills: `{len(fills)}`; realized PnL: `{total_fill_pnl:.6f} USDT`.",
        f"- Portfolio start->end total assets delta: `{pf_summary.get('start_to_end_delta', 0.0):.6f} USDT`.",
        f"- Portfolio high->end drawdown: `{pf_summary.get('high_to_end_delta', 0.0):.6f} USDT` (`{pf_summary.get('high_to_end_pct', 0.0):.2%}`).",
        f"- Before 2026-05-11 08:00 BJ fill PnL: `{float(before_shock['realized_pnl'].sum()) if not before_shock.empty else 0.0:.6f} USDT`.",
        f"- From 2026-05-11 08:00 BJ onward fill PnL: `{float(after_shock['realized_pnl'].sum()) if not after_shock.empty else 0.0:.6f} USDT`.",
        f"- 08:00-12:00 BJ shock-window fill PnL: `{float(shock_fills['realized_pnl'].sum()) if not shock_fills.empty else 0.0:.6f} USDT`.",
        f"- Decision events: `{len(decisions)}`; entry decisions: `{len(entries)}`; matched closed entries: `{len(matched)}`.",
        "- Important: realized fill PnL and portfolio equity tell different stories here. Fills are positive, but total assets fell from the pre-08:00 high into the evening.",
        "- Entry-to-PnL matching is approximate: each realized close fill is matched to latest prior same-symbol same-side non-DCA entry in this 24H window.",
        "",
        "## Portfolio Equity Curve Check",
        "",
        "```json",
        json.dumps(pf_summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Requested Symbol Config Check",
        "",
        table(
            [
                {
                    "symbol": sym,
                    "in_trading_symbols": sym in symbols,
                    "blacklisted": sym in blacklist,
                    "effective": sym in symbols and sym not in blacklist,
                }
                for sym in requested
            ],
            ["symbol", "in_trading_symbols", "blacklisted", "effective"],
        ),
        "",
        "## Fill PnL By Symbol",
        "",
        table(
            [
                {"symbol": k, "fills": int(len(g)), "pnl": round(float(g["realized_pnl"].sum()), 6)}
                for k, g in fills.groupby("symbol")
            ] if not fills.empty else [],
            ["symbol", "fills", "pnl"],
        ),
        "",
        "## Matched Entry Outcome By Side",
        "",
        table(summarize(matched, ["side"]) if not matched.empty else [], ["side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "## Matched Entry Outcome By Regime",
        "",
        table(summarize(matched, ["regime"]) if not matched.empty else [], ["regime", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "## Top Realized Fill Losses",
        "",
        table(top_fill_losses, ["bj", "symbol", "fill_side", "closes_side", "price", "quantity", "realized_pnl"]),
        "",
        "## Top Matched Entry Losses",
        "",
        table(top_entry_losses, ["bj", "symbol", "side", "pnl", "target_portion", "leverage", "regime", "atr_pct", "vwap", "reason"]),
        "",
        "## Runtime Markers",
        "",
        "```json",
        json.dumps(runtime.get("counts", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "Examples:",
        "",
        "\n".join(f"- `{x}`" for x in runtime.get("examples", [])[:12]) or "_No runtime marker examples._",
        "",
        "## Diagnosis For Claude Review",
        "",
        "1. The 08:00 BJ BTC-led selloff created a correlated downside shock. Existing single-direction alt positions could only react through stop/close logic; there was no gated opposite-leg hedge path.",
        "2. Current live code had `entry_side_mode=BOTH`, but bot-level `reverse_position_suppression` blocked opposite entries whenever a symbol already had a position. Therefore BOTH did not mean emergency hedge was available.",
        "3. Adding BTC/ETH/BNB to the universe gives the strategy direct large-cap market context/trading candidates, but it also changes opportunity selection and should be reviewed via 30D backtest.",
        "4. Enabling dual-leg hedge must be gated. Without loss/shock/signal gates, hedge mode can become churn and double fees. Proposed implementation only allows the opposite leg when current leg is losing, new opposite signal is strong, and ATR shock is elevated.",
        "",
        "## Questions For Claude",
        "",
        "1. Are the proposed dual-leg gates strict enough: unrealized loss >= 1.2%, signal_score >= 0.72, regime_atr_pct >= 1.2%, max hedge leg 8%, leverage cap 2x?",
        "2. Should BTC/ETH/BNB be tradable symbols, context-only symbols, or both?",
        "3. Should shock detection use BTC return/beta explicitly instead of per-symbol ATR only?",
        "4. Should dual-leg hedge auto-unwind when original leg recovers, or require independent TP/SL only?",
        "5. Should account-level profit lock trigger before allowing any new hedge leg after a profitable night?",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs-root", default="logs/2026-05")
    parser.add_argument("--config", default="config/trading_config_fund_flow.json")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--report", default="docs/2026-05-11_latest_24h_btc_selloff_loss_attribution_for_claude.md")
    parser.add_argument("--out", default="output/analysis/latest_24h_btc_selloff_loss_attribution.json")
    args = parser.parse_args(argv)

    logs_root = Path(args.logs_root)
    end_utc = _find_log_max_ts(logs_root)
    start_utc = end_utc - pd.Timedelta(hours=float(args.hours))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    decisions = load_decisions(logs_root, start_utc, end_utc)
    fills = load_fills(logs_root, start_utc, end_utc)
    entries = match_entries(build_entries(decisions), fills)
    runtime = load_runtime_markers(logs_root, start_utc, end_utc)
    report = build_report(
        start_utc=start_utc,
        end_utc=end_utc,
        decisions=decisions,
        fills=fills,
        entries=entries,
        runtime=runtime,
        config=config,
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    payload = {
        "window": {"start_utc": str(start_utc), "end_utc": str(end_utc)},
        "fills": int(len(fills)),
        "fill_pnl": float(fills["realized_pnl"].sum()) if not fills.empty else 0.0,
        "portfolio": portfolio_summary(decisions),
        "decisions": int(len(decisions)),
        "entries": int(len(entries)),
        "matched_entries": int(entries["matched_closed"].sum()) if not entries.empty else 0,
        "runtime": runtime,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "out": str(out_path), **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
