#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.klines_downloader import load_or_download


BACKTEST_SCRIPT = ROOT / "tools" / "backtest" / "backtest_fund_flow_rule.py"
DEFAULT_CONFIG = ROOT / "config" / "trading_config_fund_flow.json"


@dataclass(frozen=True)
class Candidate:
    name: str
    profile: str


@dataclass(frozen=True)
class CandidateMode:
    candidate: Candidate
    mode: str


def _parse_float_values(raw: str) -> List[float]:
    values: List[float] = []
    for part in str(raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        values.append(float(text))
    return values


def _parse_int_values(raw: str) -> List[int]:
    values: List[int] = []
    for part in str(raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        values.append(int(text))
    return values


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config root must be an object: {path}")
    return data


def _score_summary(summary: Dict[str, Any]) -> float:
    ret = float(summary.get("total_return_pct") or 0.0)
    drawdown = float(summary.get("max_drawdown_pct") or 0.0)
    profit_factor = float(summary.get("profit_factor") or 0.0)
    return ret + drawdown * 0.35 + profit_factor * 10.0


def _resolve_candidates(config: Dict[str, Any], symbols: Sequence[str], explicit_profiles: Sequence[str]) -> List[Candidate]:
    candidates: List[Candidate] = [Candidate(name="baseline", profile="")]
    if explicit_profiles:
        for profile in explicit_profiles:
            candidates.append(Candidate(name=profile, profile=profile))
        return candidates

    wanted = {str(symbol).upper() for symbol in symbols}
    backtest_cfg = (((config.get("fund_flow") or {}).get("backtest")) or {})
    profiles = backtest_cfg.get("profiles") if isinstance(backtest_cfg.get("profiles"), dict) else {}
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        profile_symbols = {str(symbol).upper() for symbol in profile.get("symbols") or []}
        if profile_symbols == wanted:
            candidates.append(Candidate(name=profile_name, profile=profile_name))
    return candidates


def _build_hour_variants(base_hours: Sequence[int]) -> List[tuple[str, List[int]]]:
    normalized = sorted({int(hour) for hour in base_hours if 0 <= int(hour) <= 23})
    if not normalized:
        raise RuntimeError("grid base profile must define allowed_entry_hours")

    variants: List[tuple[str, List[int]]] = [("hours_base", normalized)]
    seen = {tuple(normalized)}

    candidates = [
        ("hours_no_midday", [hour for hour in normalized if hour not in {11, 12}]),
        ("hours_eu_us_focus", [hour for hour in normalized if hour in {11, 12, 17, 18, 19, 20, 23}]),
        ("hours_asia_us_focus", [hour for hour in normalized if hour in {0, 6, 7, 8, 9, 17, 18, 19, 20, 23}]),
    ]
    for label, hours in candidates:
        cleaned = sorted({int(hour) for hour in hours if 0 <= int(hour) <= 23})
        key = tuple(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        variants.append((label, cleaned))
    return variants


def _threshold_variant_map(base_mode_overrides: Dict[str, Any], factors: Sequence[float]) -> List[tuple[str, Dict[str, float]]]:
    slope_base = float(base_mode_overrides.get("min_1h_slope_pct") or 0.0006)
    macd_base = float(base_mode_overrides.get("min_macd_hist_pct") or 0.00016)
    bb_base = float(base_mode_overrides.get("min_bb_width_delta") or 0.0012)

    variants: List[tuple[str, Dict[str, float]]] = []
    for factor in factors:
        if factor <= 0:
            continue
        if abs(factor - 1.0) < 1e-9:
            label = "thr_base"
        elif factor < 1.0:
            label = f"thr_soft_{int(round(factor * 100))}"
        else:
            label = f"thr_tight_{int(round(factor * 100))}"
        variants.append(
            (
                label,
                {
                    "min_1h_slope_pct": round(slope_base * factor, 8),
                    "min_macd_hist_pct": round(macd_base * factor, 8),
                    "min_bb_width_delta": round(bb_base * factor, 8),
                },
            )
        )
    if not variants:
        raise RuntimeError("grid threshold factors produced no variants")
    return variants


def _dedupe_candidates(candidates: Sequence[Candidate]) -> List[Candidate]:
    seen: set[str] = set()
    result: List[Candidate] = []
    for candidate in candidates:
        key = f"{candidate.name}|{candidate.profile}"
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _build_grid_config(
    config: Dict[str, Any],
    *,
    base_profile_name: str,
    symbols: Sequence[str],
    threshold_factors: Sequence[float],
    margin_values: Sequence[float],
    cooldown_values: Sequence[int],
) -> tuple[Dict[str, Any], List[Candidate], Dict[str, Any]]:
    cloned = copy.deepcopy(config)
    fund_flow_cfg = cloned.setdefault("fund_flow", {})
    if not isinstance(fund_flow_cfg, dict):
        raise RuntimeError("config.fund_flow must be an object")
    backtest_cfg = fund_flow_cfg.setdefault("backtest", {})
    if not isinstance(backtest_cfg, dict):
        raise RuntimeError("config.fund_flow.backtest must be an object")
    profiles = backtest_cfg.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise RuntimeError("config.fund_flow.backtest.profiles must be an object")

    base_profile = profiles.get(base_profile_name)
    if not isinstance(base_profile, dict):
        raise RuntimeError(f"grid base profile not found: {base_profile_name}")

    base_hours = base_profile.get("allowed_entry_hours") if isinstance(base_profile.get("allowed_entry_hours"), list) else []
    base_mode_overrides = base_profile.get("mode_overrides") if isinstance(base_profile.get("mode_overrides"), dict) else {}
    hour_variants = _build_hour_variants(base_hours)
    threshold_variants = _threshold_variant_map(base_mode_overrides, threshold_factors)

    generated: List[Candidate] = []
    for hour_label, hours in hour_variants:
        for threshold_label, threshold_overrides in threshold_variants:
            for margin in margin_values:
                for cooldown in cooldown_values:
                    profile_name = f"wf_{hour_label}_{threshold_label}_m{int(round(margin * 1000)):03d}_cd{int(cooldown)}"
                    profile = copy.deepcopy(base_profile)
                    profile["symbols"] = [str(symbol).upper() for symbol in symbols]
                    profile["allowed_entry_hours"] = hours
                    mode_overrides = copy.deepcopy(base_mode_overrides)
                    mode_overrides.update(threshold_overrides)
                    mode_overrides["margin_pct_per_trade"] = round(float(margin), 6)
                    mode_overrides["cooldown_bars"] = int(cooldown)
                    profile["mode_overrides"] = mode_overrides
                    profile["notes"] = (
                        f"Auto-generated walk-forward grid from {base_profile_name}: "
                        f"{hour_label}, {threshold_label}, margin={margin}, cooldown={cooldown}"
                    )
                    profiles[profile_name] = profile
                    generated.append(Candidate(name=profile_name, profile=profile_name))

    grid_meta = {
        "base_profile": base_profile_name,
        "hour_variants": [{"name": label, "hours": hours} for label, hours in hour_variants],
        "threshold_variants": [
            {"name": label, **overrides}
            for label, overrides in threshold_variants
        ],
        "margin_values": [round(float(value), 6) for value in margin_values],
        "cooldown_values": [int(value) for value in cooldown_values],
        "generated_candidates": len(generated),
    }
    return cloned, generated, grid_meta


def _download_master_data(
    symbols: Sequence[str],
    interval: str,
    total_days: int,
    master_dir: Path,
    refresh: bool,
) -> Dict[str, pd.DataFrame]:
    master_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        file_path = master_dir / f"{symbol}_{interval}_{total_days}d.csv"
        if refresh and file_path.exists():
            file_path.unlink()
        df, _ = load_or_download(symbol, interval, total_days, str(master_dir))
        if df is None or df.empty:
            raise RuntimeError(f"failed to load master data for {symbol}")
        df = df.sort_index()
        df.index = pd.to_datetime(df.index)
        out[symbol] = df
    return out


def _common_latest_timestamp(master_data: Dict[str, pd.DataFrame]) -> pd.Timestamp:
    latest = [df.index.max() for df in master_data.values() if not df.empty]
    if not latest:
        raise RuntimeError("master data is empty")
    return min(pd.Timestamp(ts) for ts in latest)


def _slice_window_to_dir(
    master_data: Dict[str, pd.DataFrame],
    data_dir: Path,
    end_time: pd.Timestamp,
    eval_days: int,
    warmup_days: int,
) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    start_time = end_time - pd.Timedelta(days=eval_days + warmup_days)
    for symbol, df in master_data.items():
        window = df[(df.index > start_time) & (df.index <= end_time)].copy()
        if window.empty:
            raise RuntimeError(f"window slice empty for {symbol} ending at {end_time}")
        out_path = data_dir / f"{symbol}_15m_{eval_days + warmup_days}d.csv"
        to_write = window.reset_index().rename(columns={"index": "timestamp"})
        to_write["timestamp"] = pd.to_datetime(to_write["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        to_write.to_csv(out_path, index=False, encoding="utf-8")


def _run_backtest(
    *,
    config_path: Path,
    data_dir: Path,
    report_dir: Path,
    days: int,
    profile: str,
    mode: str,
    symbols: Sequence[str],
) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(BACKTEST_SCRIPT),
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--report-dir",
        str(report_dir),
        "--days",
        str(days),
        "--mode",
        mode,
    ]
    if profile:
        cmd.extend(["--profile", profile])
    else:
        cmd.extend(["--symbols", ",".join(symbols)])

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse backtest output: {exc}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}") from exc


def _train_candidate_modes(
    candidates: Sequence[Candidate],
    config_path: Path,
    data_dir: Path,
    report_dir: Path,
    days: int,
    symbols: Sequence[str],
) -> Dict[CandidateMode, Dict[str, Any]]:
    results: Dict[CandidateMode, Dict[str, Any]] = {}
    for candidate in candidates:
        payload = _run_backtest(
            config_path=config_path,
            data_dir=data_dir,
            report_dir=report_dir / candidate.name / "train",
            days=days,
            profile=candidate.profile,
            mode="compare",
            symbols=symbols,
        )
        if payload.get("mode") != "compare":
            raise RuntimeError(f"unexpected train payload mode for {candidate.name}")
        for mode_name in ("loose", "strict"):
            summary = payload.get(mode_name)
            if isinstance(summary, dict):
                results[CandidateMode(candidate=candidate, mode=mode_name)] = summary
    return results


def _pick_best(results: Dict[CandidateMode, Dict[str, Any]], predicate) -> CandidateMode:
    eligible = [(key, value) for key, value in results.items() if predicate(key)]
    if not eligible:
        raise RuntimeError("no eligible candidates for selection")
    return max(eligible, key=lambda item: _score_summary(item[1]))[0]


def _fold_schedule(
    latest_ts: pd.Timestamp,
    evaluation_days: int,
    train_days: int,
    test_days: int,
) -> List[Dict[str, pd.Timestamp]]:
    eval_start = latest_ts - pd.Timedelta(days=evaluation_days)
    folds: List[Dict[str, pd.Timestamp]] = []
    cursor = eval_start
    while cursor + pd.Timedelta(days=train_days + test_days) <= latest_ts:
        train_start = cursor
        train_end = cursor + pd.Timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + pd.Timedelta(days=test_days)
        folds.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        cursor += pd.Timedelta(days=test_days)
    if not folds:
        raise RuntimeError("no folds generated; expand evaluation_days or reduce window sizes")
    return folds


def _aggregate_test_metrics(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
    if not rows:
        return {}
    returns = [float(row[key]["total_return_pct"]) / 100.0 for row in rows]
    drawdowns = [float(row[key]["max_drawdown_pct"]) for row in rows]
    win_rates = [float(row[key]["win_rate_pct"]) for row in rows]
    profit_factors = [float(row[key]["profit_factor"]) for row in rows]
    trade_counts = [int(row[key]["trade_count"]) for row in rows]
    compounded = math.prod(1.0 + value for value in returns) - 1.0
    positive_folds = sum(1 for value in returns if value > 0)
    return {
        "folds": len(rows),
        "positive_folds": positive_folds,
        "positive_fold_ratio": round(positive_folds / len(rows), 4),
        "avg_return_pct": round(sum(returns) / len(rows) * 100.0, 4),
        "median_return_pct": round(float(pd.Series(returns).median()) * 100.0, 4),
        "min_return_pct": round(min(returns) * 100.0, 4),
        "max_return_pct": round(max(returns) * 100.0, 4),
        "compounded_return_pct": round(compounded * 100.0, 4),
        "avg_max_drawdown_pct": round(sum(drawdowns) / len(rows), 4),
        "worst_max_drawdown_pct": round(min(drawdowns), 4),
        "avg_win_rate_pct": round(sum(win_rates) / len(rows), 4),
        "avg_profit_factor": round(sum(profit_factors) / len(rows), 6),
        "total_trades": int(sum(trade_counts)),
    }


def _selection_counts(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        candidate = row["selected_candidate"]
        profile = str(candidate["profile"])
        mode = str(candidate["mode"])
        key = f"{profile}|{mode}"
        bucket = counts.setdefault(
            key,
            {
                "profile": profile,
                "mode": mode,
                "count": 0,
                "avg_train_score": 0.0,
                "avg_test_return_pct": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["avg_train_score"] += float(candidate["train_score"])
        bucket["avg_test_return_pct"] += float(row["selected_test"]["total_return_pct"])

    result: List[Dict[str, Any]] = []
    for bucket in counts.values():
        count = max(int(bucket["count"]), 1)
        result.append(
            {
                "profile": bucket["profile"],
                "mode": bucket["mode"],
                "count": count,
                "avg_train_score": round(bucket["avg_train_score"] / count, 6),
                "avg_test_return_pct": round(bucket["avg_test_return_pct"] / count, 4),
            }
        )
    result.sort(key=lambda item: (-int(item["count"]), -float(item["avg_train_score"]), item["profile"], item["mode"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Rolling walk-forward tuning for fund-flow rule backtest")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config JSON")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT", help="Comma-separated symbols")
    parser.add_argument("--profiles", default="", help="Comma-separated candidate profiles; empty means auto-discover symbol-matching profiles plus baseline")
    parser.add_argument("--grid-base-profile", default="", help="Generate a small candidate grid around this profile")
    parser.add_argument("--grid-threshold-factors", default="0.85,1.0,1.15", help="Comma-separated multipliers for slope/macd/bb thresholds")
    parser.add_argument("--grid-margin-values", default="0.10,0.12,0.14", help="Comma-separated margin_pct_per_trade values")
    parser.add_argument("--grid-cooldown-values", default="16,20,24", help="Comma-separated cooldown_bars values")
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--evaluation-days", type=int, default=180)
    parser.add_argument("--warmup-days", type=int, default=7)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--master-dir", default=str(ROOT / "data" / "walk_forward_master"))
    parser.add_argument("--work-dir", default=str(ROOT / "tmp" / "walk_forward"))
    parser.add_argument("--report-dir", default=str(ROOT / "output" / "walk_forward"))
    parser.add_argument("--refresh-master", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = _read_json(config_path)
    symbols = [item.strip().upper() for item in str(args.symbols).split(",") if item.strip()]
    explicit_profiles = [item.strip() for item in str(args.profiles).split(",") if item.strip()]
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    active_config = config
    active_config_path = config_path
    grid_meta: Dict[str, Any] = {}
    generated_candidates: List[Candidate] = []
    if str(args.grid_base_profile).strip():
        active_config, generated_candidates, grid_meta = _build_grid_config(
            config,
            base_profile_name=str(args.grid_base_profile).strip(),
            symbols=symbols,
            threshold_factors=_parse_float_values(args.grid_threshold_factors),
            margin_values=_parse_float_values(args.grid_margin_values),
            cooldown_values=_parse_int_values(args.grid_cooldown_values),
        )
        active_config_path = work_dir / "walk_forward_grid_config.json"
        active_config_path.write_text(json.dumps(active_config, ensure_ascii=False, indent=2), encoding="utf-8")

    candidates = _resolve_candidates(active_config, symbols, explicit_profiles)
    if generated_candidates:
        candidates = _dedupe_candidates([candidates[0], *generated_candidates, *candidates[1:]])
    if len(candidates) < 2:
        raise RuntimeError("need at least baseline plus one profile candidate for walk-forward tuning")

    master_days = args.evaluation_days + args.warmup_days
    master_data = _download_master_data(
        symbols=symbols,
        interval=args.interval,
        total_days=master_days,
        master_dir=Path(args.master_dir),
        refresh=args.refresh_master,
    )
    latest_ts = _common_latest_timestamp(master_data)
    folds = _fold_schedule(
        latest_ts=latest_ts,
        evaluation_days=args.evaluation_days,
        train_days=args.train_days,
        test_days=args.test_days,
    )

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for idx, fold in enumerate(folds, start=1):
        fold_name = f"fold_{idx:02d}"
        train_data_dir = work_dir / fold_name / "train_data"
        test_data_dir = work_dir / fold_name / "test_data"
        _slice_window_to_dir(master_data, train_data_dir, fold["train_end"], args.train_days, args.warmup_days)
        _slice_window_to_dir(master_data, test_data_dir, fold["test_end"], args.test_days, args.warmup_days)

        train_results = _train_candidate_modes(
            candidates=candidates,
            config_path=active_config_path,
            data_dir=train_data_dir,
            report_dir=report_dir / fold_name,
            days=args.train_days,
            symbols=symbols,
        )
        best_overall = _pick_best(train_results, predicate=lambda key: True)
        best_baseline = _pick_best(train_results, predicate=lambda key: key.candidate.name == "baseline")

        selected_test = _run_backtest(
            config_path=active_config_path,
            data_dir=test_data_dir,
            report_dir=report_dir / fold_name / "selected_test",
            days=args.test_days,
            profile=best_overall.candidate.profile,
            mode=best_overall.mode,
            symbols=symbols,
        )
        baseline_test = _run_backtest(
            config_path=active_config_path,
            data_dir=test_data_dir,
            report_dir=report_dir / fold_name / "baseline_test",
            days=args.test_days,
            profile=best_baseline.candidate.profile,
            mode=best_baseline.mode,
            symbols=symbols,
        )

        selected_summary = selected_test
        baseline_summary = baseline_test
        row = {
            "fold": fold_name,
            "train_start": fold["train_start"].isoformat(),
            "train_end": fold["train_end"].isoformat(),
            "test_start": fold["test_start"].isoformat(),
            "test_end": fold["test_end"].isoformat(),
            "selected_candidate": {
                "profile": best_overall.candidate.name,
                "mode": best_overall.mode,
                "train_score": round(_score_summary(train_results[best_overall]), 6),
                "train_return_pct": round(float(train_results[best_overall]["total_return_pct"]), 4),
                "train_drawdown_pct": round(float(train_results[best_overall]["max_drawdown_pct"]), 4),
                "train_profit_factor": round(float(train_results[best_overall]["profit_factor"]), 6),
            },
            "baseline_candidate": {
                "profile": best_baseline.candidate.name,
                "mode": best_baseline.mode,
                "train_score": round(_score_summary(train_results[best_baseline]), 6),
                "train_return_pct": round(float(train_results[best_baseline]["total_return_pct"]), 4),
                "train_drawdown_pct": round(float(train_results[best_baseline]["max_drawdown_pct"]), 4),
                "train_profit_factor": round(float(train_results[best_baseline]["profit_factor"]), 6),
            },
            "selected_test": selected_summary,
            "baseline_test": baseline_summary,
        }
        rows.append(row)

    aggregate = {
        "selected_test": _aggregate_test_metrics(rows, key="selected_test"),
        "baseline_test": _aggregate_test_metrics(rows, key="baseline_test"),
        "selection_counts": _selection_counts(rows),
    }
    result = {
        "symbols": symbols,
        "train_days": args.train_days,
        "test_days": args.test_days,
        "evaluation_days": args.evaluation_days,
        "warmup_days": args.warmup_days,
        "latest_timestamp": latest_ts.isoformat(),
        "candidate_count": len(candidates),
        "grid": grid_meta,
        "candidates": [{"name": candidate.name, "profile": candidate.profile} for candidate in candidates],
        "folds": rows,
        "aggregate": aggregate,
    }

    timestamp = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    summary_path = report_dir / f"walk_forward_summary_{timestamp}.json"
    folds_path = report_dir / f"walk_forward_folds_{timestamp}.csv"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_rows: List[Dict[str, Any]] = []
    for row in rows:
        csv_rows.append(
            {
                "fold": row["fold"],
                "train_start": row["train_start"],
                "train_end": row["train_end"],
                "test_start": row["test_start"],
                "test_end": row["test_end"],
                "selected_profile": row["selected_candidate"]["profile"],
                "selected_mode": row["selected_candidate"]["mode"],
                "selected_train_score": row["selected_candidate"]["train_score"],
                "selected_test_return_pct": row["selected_test"]["total_return_pct"],
                "selected_test_drawdown_pct": row["selected_test"]["max_drawdown_pct"],
                "selected_test_profit_factor": row["selected_test"]["profit_factor"],
                "baseline_mode": row["baseline_candidate"]["mode"],
                "baseline_test_return_pct": row["baseline_test"]["total_return_pct"],
                "baseline_test_drawdown_pct": row["baseline_test"]["max_drawdown_pct"],
                "baseline_test_profit_factor": row["baseline_test"]["profit_factor"],
            }
        )
    pd.DataFrame(csv_rows).to_csv(folds_path, index=False, encoding="utf-8-sig")

    print(json.dumps({**result, "summary_path": str(summary_path), "folds_path": str(folds_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
