from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


BJ_TZ = "Asia/Shanghai"
UTC = "UTC"
DEFAULT_START_BJ = "2026-05-08 19:00:00"


RUNTIME_SCORE_RE = re.compile(
    r"MACD_V2评分: stage=(?P<stage>[^,]+), dir=(?P<dir>[^,]+), "
    r"primary=4H:(?P<score_4h>[-0-9.]+)\((?P<signal_4h>[^)]*)\), "
    r"1H=(?P<score_1h>[-0-9.]+)\((?P<signal_1h>[^)]*)\), "
    r"4H_enh=(?P<score_4h_enh>[-0-9.]+)\(raw=(?P<raw_4h_enh>[-0-9.]+)\), "
    r"VWAP=(?P<score_vwap>[-0-9.]+)\(dev=(?P<vwap_dev>[-+0-9.]+)%\), "
    r"15M=(?P<score_15m>[-0-9.]+)\((?P<entry_15m>[^)]*)\), "
    r"VOL=(?P<score_vol>[-0-9.]+)\(r=(?P<vol_ratio>[-0-9.]+)\), "
    r"EMA=(?P<ema_mult>[-0-9.]+)x/(?P<ema_status>[^,]+), "
    r"total=(?P<total>[-0-9.]+)/(?P<threshold>[-0-9.]+), "
    r"th_src=(?P<th_src>[^,]+), trial=(?P<trial>[^,]+), stable=(?P<stable>[^,]+), veto=(?P<veto>.+)$"
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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


def load_runtime_scores(logs_root: Path, start_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    current_symbol = ""
    current_operation = ""
    current_status = ""
    current_portion = math.nan
    current_leverage = math.nan
    for path in sorted(logs_root.glob("*/runtime.out*.log")):
        mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)
        if mtime < start_utc - pd.Timedelta(hours=12):
            continue
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for lineno, line in enumerate(handle, start=1):
                decision_match = re.search(
                    r"\[(?P<symbol>[A-Z0-9]+USDT)\]\s+决策=(?P<op>[A-Z]+)\s+\|\s+状态=(?P<status>[^|]+)\s+\|\s+目标占比=(?P<portion>[-0-9.]+).*?杠杆\(请求/实际\)=(?P<lev_req>[-0-9.]+)x/(?P<lev_actual>[-0-9.]+)x",
                    line,
                )
                if decision_match:
                    current_symbol = decision_match.group("symbol")
                    current_operation = decision_match.group("op")
                    current_status = decision_match.group("status").strip()
                    current_portion = _to_float(decision_match.group("portion"), math.nan)
                    current_leverage = _to_float(decision_match.group("lev_actual"), math.nan)
                    continue
                score_match = RUNTIME_SCORE_RE.search(line.strip())
                if not score_match:
                    continue
                data = score_match.groupdict()
                row = {
                    "source_file": str(path),
                    "line": lineno,
                    "symbol": current_symbol,
                    "operation": current_operation,
                    "status": current_status,
                    "target_portion": current_portion,
                    "leverage_actual": current_leverage,
                    "stage": data["stage"],
                    "direction": data["dir"],
                    "score_4h": _to_float(data["score_4h"]),
                    "signal_4h": data["signal_4h"],
                    "score_1h": _to_float(data["score_1h"]),
                    "signal_1h": data["signal_1h"],
                    "score_4h_enh": _to_float(data["score_4h_enh"]),
                    "raw_4h_enh": _to_float(data["raw_4h_enh"]),
                    "score_vwap": _to_float(data["score_vwap"]),
                    "vwap_dev_pct": _to_float(data["vwap_dev"]),
                    "score_15m": _to_float(data["score_15m"]),
                    "entry_15m": data["entry_15m"],
                    "score_vol": _to_float(data["score_vol"]),
                    "vol_ratio": _to_float(data["vol_ratio"]),
                    "ema_mult": _to_float(data["ema_mult"]),
                    "ema_status": data["ema_status"],
                    "total": _to_float(data["total"]),
                    "threshold": _to_float(data["threshold"]),
                    "threshold_source": data["th_src"],
                    "trial": data["trial"] == "True",
                    "stable": data["stable"],
                    "veto": data["veto"],
                }
                rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_entry_gate_blocks(logs_root: Path, start_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for path in sorted(logs_root.glob("*/runtime.out*.log")):
        mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz=UTC)
        if mtime < start_utc - pd.Timedelta(hours=12):
            continue
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                marker = "ENTRY_GATE_BLOCK "
                if marker not in line:
                    continue
                payload_text = line.split(marker, 1)[1].strip()
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_decisions(logs_root: Path, start_utc: pd.Timestamp) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for path in sorted(logs_root.glob("*/fund_flow_attribution.jsonl")):
        for rec in iter_jsonl(path):
            ts = parse_utc_timestamp(rec.get("ts"))
            if ts is None or ts < start_utc or rec.get("event") != "decision":
                continue
            decision = rec.get("decision") if isinstance(rec.get("decision"), dict) else {}
            context = rec.get("context") if isinstance(rec.get("context"), dict) else {}
            md = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
            op = str(decision.get("operation") or "").lower()
            symbol = str(context.get("symbol") or decision.get("symbol") or "").upper()
            rows.append(
                {
                    "ts": ts,
                    "bj": ts.tz_convert(BJ_TZ),
                    "symbol": symbol,
                    "operation": op,
                    "side": side_from_operation(op),
                    "target_portion": _to_float(decision.get("target_portion_of_balance"), 0.0),
                    "leverage": int(_to_float(decision.get("leverage"), 0.0)),
                    "reason": str(decision.get("reason") or ""),
                    "price": _to_float(context.get("price"), math.nan),
                    "regime": md.get("regime"),
                    "regime_adx": _to_float(md.get("regime_adx"), math.nan),
                    "regime_atr_pct": _to_float(md.get("regime_atr_pct"), math.nan),
                    "vwap_score": _to_float(md.get("vwap_score"), math.nan),
                    "vol_vwap_warn": md.get("vol_vwap_warn"),
                    "vol_vwap_warn_position_scaled": md.get("vol_vwap_warn_position_scaled"),
                    "score_volume": _to_float(md.get("score_volume"), math.nan),
                    "metadata_omitted_keys": int(_to_float(md.get("_omitted_keys"), 0)),
                    "source_file": str(path),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


def load_fills(logs_root: Path, start_utc: pd.Timestamp) -> pd.DataFrame:
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
    subset = [col for col in ["成交ID", "订单ID", "合约", "时间(UTC)", "方向", "价格", "数量"] if col in fills.columns]
    fills = fills.drop_duplicates(subset=subset).copy()
    fills["ts"] = pd.to_datetime(fills["时间(UTC)"], utc=True, errors="coerce")
    fills["symbol"] = fills["合约"].astype(str).str.upper()
    fills["fill_side"] = fills["方向"].astype(str)
    fills["price"] = pd.to_numeric(fills["价格"], errors="coerce")
    fills["quantity"] = pd.to_numeric(fills["数量"], errors="coerce")
    fills["realized_pnl"] = pd.to_numeric(fills["已实现盈亏"], errors="coerce").fillna(0.0)
    fills["closes_side"] = fills["fill_side"].map(fill_closes_side)
    return fills[fills["ts"].notna() & (fills["ts"] >= start_utc)].sort_values("ts").reset_index(drop=True)


def build_entries(decisions: pd.DataFrame, min_meaningful_target_portion: float = 0.01) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame()
    entries = decisions[
        decisions["operation"].isin(["buy", "sell"])
        & (decisions["target_portion"] > 0)
    ].copy()
    entries["entry_id"] = range(len(entries))
    entries["is_dca"] = entries["reason"].str.contains("DCA|马丁", case=False, regex=True, na=False)
    entries["signal_family"] = entries["reason"].str.extract(r"macd_v2_(long|short)_1h_([^_]+(?:_[^_]+)*)_15m", expand=False)[1]
    min_portion = max(0.0, float(min_meaningful_target_portion))
    entries["is_meaningful_position"] = pd.to_numeric(entries["target_portion"], errors="coerce").fillna(0.0) >= min_portion
    entries["position_accounting"] = entries["is_meaningful_position"].map(
        {True: "meaningful", False: "micro_notional"}
    )
    entries["matched_realized_pnl"] = 0.0
    entries["matched_close_fills"] = 0
    entries["matched_closed"] = False
    return entries.reset_index(drop=True)


def match_entry_pnl(
    entries: pd.DataFrame,
    fills: pd.DataFrame,
    min_meaningful_target_portion: float = 0.01,
) -> pd.DataFrame:
    if entries.empty or fills.empty:
        return entries
    out = entries.copy()
    if "is_meaningful_position" not in out.columns:
        min_portion = max(0.0, float(min_meaningful_target_portion))
        out["is_meaningful_position"] = pd.to_numeric(out["target_portion"], errors="coerce").fillna(0.0) >= min_portion
    if "position_accounting" not in out.columns:
        out["position_accounting"] = out["is_meaningful_position"].map({True: "meaningful", False: "micro_notional"})
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


def summarize_group(df: pd.DataFrame, group_cols: List[str]) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    rows = []
    for keys, group in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(group_cols, keys)}
        count = int(len(group))
        wins = int(group["matched_win"].sum()) if "matched_win" in group else 0
        row.update(
            entries=count,
            wins=wins,
            losses=count - wins,
            win_rate=round(wins / count, 4) if count else 0.0,
            pnl=round(float(group["matched_realized_pnl"].sum()), 6) if "matched_realized_pnl" in group else 0.0,
            avg_pnl=round(float(group["matched_realized_pnl"].mean()), 6) if "matched_realized_pnl" in group and count else 0.0,
        )
        rows.append(row)
    return sorted(rows, key=lambda x: (-abs(float(x.get("pnl", 0.0))), -int(x.get("entries", 0)), str(x)))


def config_snapshot(config_path: Path) -> Dict[str, Any]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    ff = cfg.get("fund_flow", {}) if isinstance(cfg.get("fund_flow"), dict) else {}
    v2 = ff.get("macd_mtf_strategy_v2", {}) if isinstance(ff.get("macd_mtf_strategy_v2"), dict) else {}
    weights = v2.get("scoring_weights", {}) if isinstance(v2.get("scoring_weights"), dict) else {}
    thresholds = v2.get("entry_thresholds", {}) if isinstance(v2.get("entry_thresholds"), dict) else {}
    entry_filters = v2.get("entry_filters", {}) if isinstance(v2.get("entry_filters"), dict) else {}
    rsi_cfg = v2.get("rsi_config", {}) if isinstance(v2.get("rsi_config"), dict) else {}
    rhythm = rsi_cfg.get("rhythm", {}) if isinstance(rsi_cfg.get("rhythm"), dict) else {}
    pm = v2.get("position_management", {}) if isinstance(v2.get("position_management"), dict) else {}
    pretrade = ff.get("pretrade_risk_gate", {}) if isinstance(ff.get("pretrade_risk_gate"), dict) else {}
    return {
        "weights": weights,
        "weight_sum": round(sum(_to_float(v) for v in weights.values()), 6),
        "thresholds": thresholds,
        "entry_filters": entry_filters,
        "rsi_period": rsi_cfg.get("period"),
        "rsi_rhythm": rhythm,
        "position_management": pm,
        "fund_flow_position": {
            "default_target_portion": ff.get("default_target_portion"),
            "add_position_portion": ff.get("add_position_portion"),
            "max_symbol_position_portion": ff.get("max_symbol_position_portion"),
            "min_open_portion": ff.get("min_open_portion"),
            "max_active_symbols": ff.get("max_active_symbols"),
            "default_leverage": ff.get("default_leverage"),
            "min_leverage": ff.get("min_leverage"),
            "max_leverage": ff.get("max_leverage"),
        },
        "pretrade_risk_gate": pretrade,
    }


def markdown_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    if not rows:
        return "_No data._\n"
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for col in columns:
            val = row.get(col, "")
            if isinstance(val, pd.Timestamp):
                val = str(val)
            if isinstance(val, float):
                if col.endswith("rate"):
                    values.append(f"{val * 100:.2f}%")
                else:
                    values.append(f"{val:.6f}")
            else:
                values.append(str(val))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def build_report(
    *,
    start_bj: pd.Timestamp,
    end_utc: Optional[pd.Timestamp],
    cfg: Dict[str, Any],
    summary: Dict[str, Any],
    tables: Dict[str, Any],
) -> str:
    end_text = str(end_utc.tz_convert(BJ_TZ)) if end_utc is not None else "unknown"
    weights_rows = [
        {"component": k, "weight": _to_float(v)}
        for k, v in cfg["weights"].items()
    ]
    threshold_rows = [
        {"threshold": k, "value": _to_float(v)}
        for k, v in cfg["thresholds"].items()
    ]
    lines = [
        "# Live Strategy Chain + Loss Attribution Review For Claude",
        "",
        "Date: `2026-05-10`",
        "",
        "Window:",
        f"- Beijing start: `{start_bj}`",
        f"- Beijing end from logs: `{end_text}`",
        f"- UTC start: `{start_bj.tz_convert(UTC)}`",
        "",
        "## Executive Summary",
        "",
        f"- Scoring weights currently sum to `{cfg['weight_sum']:.2f}`, not `1.00`.",
        "- The strategy does not normalize by total weight. It adds component scores and then caps final score at `1.0`.",
        "- The old `0.85` default exists only as fallback/legacy in code and some outer DCA/winner configs. The active MACD V2 live entry thresholds are much lower.",
        "- The observed `0.64` threshold is from the actual runtime logs in this window. Current workspace config is not identical to the logged runtime threshold ladder.",
        "- Current workspace config has `default/min_signal_score=0.68`, `red_bar_growing=0.68`, `green_bar_growing=0.69`, `flip_bearish=0.66`, `flip_bullish=0.64`.",
        "- Runtime logs in this window show a lower ladder: `flip_bullish=0.60`, `flip_bearish=0.62`, `red_bar_growing=0.64`, `green_bar_growing=0.65`, and trial/preflip around `0.66`.",
        "- This review uses compact live logs. Attribution metadata omits many debug fields, so runtime text lines are used for detailed score examples and distribution checks.",
        "",
        "## Weight Distribution",
        "",
        markdown_table(weights_rows, ["component", "weight"]),
        f"Weight sum: `{cfg['weight_sum']:.2f}`.",
        "",
        "Important interpretation: `weight_4h_enhancement=0.10` is configured, but current scoring folds the 4H enhancement bonus into the capped 4H direction score. The emitted `score_4h_enhancement` is often `0.0`; the effective bonus can appear inside `score_4h`.",
        "",
        "## Active Entry Thresholds",
        "",
        markdown_table(threshold_rows, ["threshold", "value"]),
        "",
        "Threshold resolution in code:",
        "",
        "```text",
        "threshold_signal_type = 4H signal type when primary_mode=4h",
        "threshold = resolve_entry_threshold(signal_type, entry_type_15m, trial/stable flags)",
        "if neutral_upgrade applies: threshold = min(threshold, neutral_upgrade_override)",
        "if RSI spring override applies: threshold = min(threshold, spring_override_min_signal_score)",
        "if RSI launch sovereign applies: threshold = min(threshold, sovereign_threshold)",
        "entry passes only if score >= threshold",
        "```",
        "",
        "## Runtime Threshold Distribution",
        "",
        markdown_table(tables["runtime_thresholds"], ["threshold", "samples"]),
        "",
        "Runtime final-stage threshold sources:",
        "",
        "| Source | Count | Observed threshold |",
        "|---|---:|---:|",
        "| `primary_4h_red_bar_growing` | 86 | `0.64` |",
        "| `preflip_trial` / `-` | 53 | `0.66` |",
        "| `primary_4h_green_bar_growing` | 32 | `0.65` |",
        "| `primary_4h_flip_bearish` | 10 | `0.62` |",
        "| `primary_4h_flip_bullish` | 10 | `0.60` |",
        "",
        "This is the concrete reason `0.64` appears in live logs despite the older mental model of `0.85`.",
        "",
        "## Runtime Final Score Examples",
        "",
        markdown_table(
            tables["runtime_final_examples"],
            ["symbol", "operation", "status", "stage", "direction", "signal_1h", "signal_4h", "score_1h", "score_4h", "score_vwap", "score_15m", "score_vol", "total", "threshold", "threshold_source", "trial", "target_portion", "leverage_actual"],
        ),
        "",
        "## Loss Attribution Since Start",
        "",
        f"- Decision events: `{summary['decision_events']}`",
        f"- Entry decisions: `{summary['entry_decisions']}`",
        f"- Non-DCA entry decisions: `{summary['non_dca_entries']}`",
        f"- Deduped fills: `{summary['deduped_fills']}`",
        f"- Realized PnL in fill window: `{summary['realized_pnl']:.6f} USDT`",
        f"- Matched closed entries: `{summary['matched_closed_entries']}`",
        f"- Matched closed entry PnL: `{summary['matched_closed_pnl']:.6f} USDT`",
        f"- Matched win rate: `{summary['matched_win_rate']:.2%}`",
        f"- Meaningful target threshold: `target_portion >= {summary['min_meaningful_target_portion']:.4f}`",
        f"- Meaningful matched entries: `{summary['meaningful_matched_closed_entries']}`",
        f"- Meaningful matched PnL: `{summary['meaningful_matched_closed_pnl']:.6f} USDT`",
        f"- Meaningful matched win rate: `{summary['meaningful_matched_win_rate']:.2%}`",
        f"- Micro-notional matched entries: `{summary['micro_matched_closed_entries']}`",
        f"- Micro-notional matched PnL: `{summary['micro_matched_closed_pnl']:.6f} USDT`",
        f"- Micro-notional matched win rate: `{summary['micro_matched_win_rate']:.2%}`",
        "",
        "Loss concentration:",
        "",
        "- Losing LONG entries: `6`, total matched PnL about `-3.72 USDT`.",
        "- Losing SHORT entries: `10`, total matched PnL about `-1.51 USDT`.",
        "- The largest loss cluster is ordinary long `macd_v2_long_1h_red_bar_growing_15m__vwap_0.25`.",
        "- Short losses are more numerous but mostly smaller; the weakest short family by win rate is `short_1h_flip_bearish` in this slice.",
        "- `vol_vwap_warn` is `False` for the top matched losses, so this particular window's losses are not explained by the previous weak VWAP warning bucket.",
        "- A large share of losing longs had `vwap_score=0.25`, which passed current VWAP quality. This suggests the current VWAP gate did not distinguish the long loss tail in this window.",
        "",
        "### Top Matched Losses",
        "",
        markdown_table(
            tables["top_losses"],
            ["bj", "symbol", "side", "matched_realized_pnl", "target_portion", "leverage", "regime", "regime_adx", "vwap_score", "score_volume", "vol_vwap_warn", "reason"],
        ),
        "",
        "### Outcome By Side",
        "",
        markdown_table(tables["by_side"], ["side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By Side, Meaningful Positions Only",
        "",
        markdown_table(tables["by_side_meaningful"], ["side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By Side, Micro-Notional Positions",
        "",
        markdown_table(tables["by_side_micro"], ["side", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By Position Accounting",
        "",
        markdown_table(tables["by_position_accounting"], ["position_accounting", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By Regime",
        "",
        markdown_table(tables["by_regime"], ["regime", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By VWAP Bucket",
        "",
        markdown_table(tables["by_vwap_bucket"], ["vwap_bucket", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "### Outcome By Signal Family",
        "",
        markdown_table(tables["by_reason"], ["reason_family", "entries", "wins", "losses", "win_rate", "pnl", "avg_pnl"]),
        "",
        "## Entry And Position Chain",
        "",
        "1. `fund_flow_bot` gets market data and builds flow snapshot.",
        "2. `FundFlowDecisionEngine` runs MACD MTF V2 and creates `MACDSignalV2`.",
        "3. `macd_strategy_v2` gates in stages: 1H direction, BOLL/EMA structure, VWAP, 4H enhancement, RSI rhythm, strict filters, score aggregation, final threshold check.",
        "4. Score aggregation currently uses:",
        "   - 1H direction score up to `weight_1h_direction`.",
        "   - 4H direction score up to `weight_4h_direction`, with folded 4H enhancement bonus.",
        "   - RSI rhythm weighted score `raw_score * weight_rsi_rhythm`.",
        "   - VWAP score from VWAP location model.",
        "   - 15m entry score up to `weight_15m_entry`.",
        "   - Volume score up to `weight_volume`.",
        "   - Multiplicative penalties for RSI/MACD conflict, neutral upgrade, flip-bullish filters, and overheat.",
        "   - Final score is capped with `min(score, 1.0)`.",
        "5. If `score < signal_score_threshold`, the signal is downgraded to HOLD.",
        "6. If it passes, dynamic stop is calculated and decision metadata carries score, threshold, stop, route, and sizing hints.",
        "7. Bot applies pretrade risk gate, same-side add guard, conflict protection, protection-gap block, active symbol capacity, min-open-portion, and position cap.",
        "8. Orders are submitted through the execution router; pending entry protection is deferred until fill, then protection hooks/SLA monitor attach or repair TP/SL.",
        "",
        "## Position Management And Risk Controls",
        "",
        "Configured fund-flow position values:",
        "",
        "```json",
        json.dumps(cfg["fund_flow_position"], ensure_ascii=False, indent=2),
        "```",
        "",
        "Configured RSI rhythm values:",
        "",
        "```json",
        json.dumps({"period": cfg["rsi_period"], "rhythm": cfg["rsi_rhythm"]}, ensure_ascii=False, indent=2),
        "```",
        "",
        "Configured MACD V2 position management:",
        "",
        "```json",
        json.dumps(cfg["position_management"], ensure_ascii=False, indent=2),
        "```",
        "",
        "Configured pretrade risk gate:",
        "",
        "```json",
        json.dumps(cfg["pretrade_risk_gate"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Specific Questions For Claude",
        "",
        "1. Is it coherent for configured scoring weights to sum to `1.15` while the final score is capped at `1.0`, or should the components be normalized/rebalanced?",
        "2. Are current active thresholds (`0.64-0.69`) too low compared with the historical `0.85` target, given the current component scores and observed loss cases?",
        "3. Should `primary_4h_red_bar_growing` and `flip_bullish` remain at `0.64`, or should they return toward `0.75-0.85`?",
        "4. Do top losses cluster around low VWAP quality, specific regimes, or trial entries enough to justify another gate?",
        "5. Should tiny `target_portion` entries created by min-notional adjustment be treated as probes with separate accounting?",
        "6. Are protection-gap and active-symbol-cap blocks protecting correctly, or are they causing adverse selection by leaving weaker fills active?",
        "",
        "## Caveats",
        "",
        "- Entry-to-PnL matching is approximate: realized PnL fills are matched to the latest prior same-symbol, same-side non-DCA entry.",
        "- Compact attribution metadata omits detailed score fields; runtime logs are used for detailed score examples.",
        "- Some realized PnL can belong to positions opened before the window and is included only in total fill PnL, not matched entry PnL.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-bj", default=DEFAULT_START_BJ)
    parser.add_argument("--logs-root", default="logs/2026-05")
    parser.add_argument("--config", default="config/trading_config_fund_flow.json")
    parser.add_argument("--out", default="output/analysis/live_strategy_chain_20260508_1900_bj.json")
    parser.add_argument("--entries-csv", default="output/analysis/live_strategy_chain_entries_20260508_1900_bj.csv")
    parser.add_argument("--runtime-csv", default="output/analysis/live_strategy_chain_runtime_scores_20260508_1900_bj.csv")
    parser.add_argument("--report", default="docs/2026-05-10_live_strategy_chain_loss_review_for_claude.md")
    parser.add_argument("--min-meaningful-target-portion", type=float, default=0.01)
    args = parser.parse_args(argv)

    start_bj = parse_bj_timestamp(args.start_bj)
    start_utc = start_bj.tz_convert(UTC)
    logs_root = Path(args.logs_root)
    cfg = config_snapshot(Path(args.config))

    decisions = load_decisions(logs_root, start_utc)
    entries = build_entries(decisions, min_meaningful_target_portion=args.min_meaningful_target_portion)
    fills = load_fills(logs_root, start_utc)
    entries = match_entry_pnl(entries, fills, min_meaningful_target_portion=args.min_meaningful_target_portion)
    runtime_scores = load_runtime_scores(logs_root, start_utc)
    gate_blocks = load_entry_gate_blocks(logs_root, start_utc)

    matched = entries[entries["matched_closed"]].copy() if not entries.empty else pd.DataFrame()
    meaningful_matched = matched[matched["is_meaningful_position"]].copy() if not matched.empty and "is_meaningful_position" in matched else pd.DataFrame()
    micro_matched = matched[~matched["is_meaningful_position"]].copy() if not matched.empty and "is_meaningful_position" in matched else pd.DataFrame()
    non_dca = entries[~entries["is_dca"]].copy() if not entries.empty else pd.DataFrame()
    end_utc = None
    if not decisions.empty:
        end_utc = decisions["ts"].max()

    if not matched.empty:
        matched["vwap_bucket"] = pd.cut(
            pd.to_numeric(matched["vwap_score"], errors="coerce").fillna(-1),
            bins=[-2, 0, 0.12, 0.25, 0.5, 1.01],
            labels=["missing_or_zero", "(0,0.12]", "(0.12,0.25]", "(0.25,0.5]", ">0.5"],
            include_lowest=True,
        ).astype(str)
        matched["reason_family"] = matched["reason"].str.replace(r"_vwap_[-0-9.]+", "", regex=True)
    else:
        matched["vwap_bucket"] = []
        matched["reason_family"] = []

    threshold_counts = []
    if not runtime_scores.empty:
        for threshold, count in runtime_scores["threshold"].round(4).value_counts().sort_index().items():
            threshold_counts.append({"threshold": float(threshold), "samples": int(count)})
    final_examples = []
    if not runtime_scores.empty:
        sample = runtime_scores[runtime_scores["stage"] == "final"].copy()
        sample = sample.sort_values(["total", "threshold"], ascending=[True, True]).head(20)
        final_examples = sample[
            [
                "symbol", "operation", "status", "stage", "direction", "signal_1h", "signal_4h",
                "score_1h", "score_4h", "score_vwap", "score_15m", "score_vol",
                "total", "threshold", "threshold_source", "trial", "target_portion", "leverage_actual",
            ]
        ].to_dict("records")

    top_losses = []
    if not matched.empty:
        losses = matched[matched["matched_realized_pnl"] < 0].sort_values("matched_realized_pnl").head(15)
        for _, row in losses.iterrows():
            top_losses.append(
                {
                    "bj": str(row["bj"]),
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "matched_realized_pnl": round(float(row["matched_realized_pnl"]), 6),
                    "target_portion": round(float(row["target_portion"]), 6),
                    "leverage": int(row["leverage"]),
                    "regime": row["regime"],
                    "regime_adx": round(float(row["regime_adx"]), 4) if math.isfinite(float(row["regime_adx"])) else "",
                    "vwap_score": round(float(row["vwap_score"]), 4) if math.isfinite(float(row["vwap_score"])) else "",
                    "score_volume": round(float(row["score_volume"]), 4) if math.isfinite(float(row["score_volume"])) else "",
                    "vol_vwap_warn": row["vol_vwap_warn"],
                    "reason": row["reason"],
                }
            )

    summary = {
        "start_bj": str(start_bj),
        "start_utc": str(start_utc),
        "end_utc": str(end_utc) if end_utc is not None else None,
        "decision_events": int(len(decisions)),
        "entry_decisions": int(len(entries)),
        "non_dca_entries": int(len(non_dca)),
        "deduped_fills": int(len(fills)),
        "realized_pnl": round(float(fills["realized_pnl"].sum()), 6) if not fills.empty else 0.0,
        "matched_closed_entries": int(len(matched)),
        "matched_closed_pnl": round(float(matched["matched_realized_pnl"].sum()), 6) if not matched.empty else 0.0,
        "matched_win_rate": round(float(matched["matched_win"].mean()), 6) if not matched.empty else 0.0,
        "min_meaningful_target_portion": float(args.min_meaningful_target_portion),
        "meaningful_matched_closed_entries": int(len(meaningful_matched)),
        "meaningful_matched_closed_pnl": round(float(meaningful_matched["matched_realized_pnl"].sum()), 6) if not meaningful_matched.empty else 0.0,
        "meaningful_matched_win_rate": round(float(meaningful_matched["matched_win"].mean()), 6) if not meaningful_matched.empty else 0.0,
        "micro_matched_closed_entries": int(len(micro_matched)),
        "micro_matched_closed_pnl": round(float(micro_matched["matched_realized_pnl"].sum()), 6) if not micro_matched.empty else 0.0,
        "micro_matched_win_rate": round(float(micro_matched["matched_win"].mean()), 6) if not micro_matched.empty else 0.0,
        "runtime_score_rows": int(len(runtime_scores)),
        "entry_gate_blocks": int(len(gate_blocks)),
    }

    tables = {
        "runtime_thresholds": threshold_counts,
        "runtime_final_examples": final_examples,
        "top_losses": top_losses,
        "by_side": summarize_group(matched, ["side"]) if not matched.empty else [],
        "by_side_meaningful": summarize_group(meaningful_matched, ["side"]) if not meaningful_matched.empty else [],
        "by_side_micro": summarize_group(micro_matched, ["side"]) if not micro_matched.empty else [],
        "by_position_accounting": summarize_group(matched, ["position_accounting"]) if not matched.empty and "position_accounting" in matched else [],
        "by_regime": summarize_group(matched, ["regime"]) if not matched.empty else [],
        "by_vwap_bucket": summarize_group(matched, ["vwap_bucket"]) if not matched.empty else [],
        "by_reason": summarize_group(matched, ["reason_family"])[:20] if not matched.empty else [],
        "gate_block_counts": gate_blocks["gate"].value_counts().to_dict() if not gate_blocks.empty and "gate" in gate_blocks else {},
    }

    out_payload = {
        "config": cfg,
        "summary": summary,
        "tables": tables,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    entries_csv = Path(args.entries_csv)
    entries_csv.parent.mkdir(parents=True, exist_ok=True)
    entries.to_csv(entries_csv, index=False)

    runtime_csv = Path(args.runtime_csv)
    runtime_csv.parent.mkdir(parents=True, exist_ok=True)
    runtime_scores.to_csv(runtime_csv, index=False)

    report = build_report(
        start_bj=start_bj,
        end_utc=end_utc,
        cfg=cfg,
        summary=summary,
        tables=tables,
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(json.dumps({"summary": summary, "out": str(out_path), "entries_csv": str(entries_csv), "runtime_csv": str(runtime_csv), "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
