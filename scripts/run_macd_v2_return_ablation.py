"""
Run one-variable MACD V2 return ablations against strict-live backtest settings.

The script writes temporary config files under output/backtest/ablation_configs
and calls scripts/backtest_macd_v2.py with --strict-live-mode. It uses only
configuration keys that the current backtest engine already understands.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_blacklist(cfg: Dict[str, Any], symbols: List[str]) -> Dict[str, Any]:
    out = copy.deepcopy(cfg)
    fund_flow = out.setdefault("fund_flow", {})
    existing = fund_flow.get("symbol_blacklist", [])
    existing = existing if isinstance(existing, list) else []
    merged = sorted({str(item).upper() for item in existing + symbols if str(item).strip()})
    fund_flow["symbol_blacklist"] = merged
    return out


def build_suite(base: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    def patch(overrides: Dict[str, Any]) -> Dict[str, Any]:
        return deep_merge(base, overrides)

    return {
        "00_baseline": copy.deepcopy(base),
        "S1_max_stop_2pct": patch(
            {"fund_flow": {"macd_mtf_strategy_v2": {"stop_loss_config": {"max_stop_loss_pct": 0.020}}}}
        ),
        "S2_max_stop_1_5pct": patch(
            {"fund_flow": {"macd_mtf_strategy_v2": {"stop_loss_config": {"max_stop_loss_pct": 0.015}}}}
        ),
        "S3_max_stop_1pct": patch(
            {"fund_flow": {"macd_mtf_strategy_v2": {"stop_loss_config": {"max_stop_loss_pct": 0.010}}}}
        ),
        "S4_hard_stop_2pct": patch({"fund_flow": {"hard_stop_loss_pct": 0.020}}),
        "S5_hard_stop_1_5pct": patch({"fund_flow": {"hard_stop_loss_pct": 0.015}}),
        "S6_hard_stop_1pct": patch({"fund_flow": {"hard_stop_loss_pct": 0.010}}),
        "B1_disable_light_tp": patch(
            {"risk": {"conflict_protection": {"light_take_profit_enabled": False}}}
        ),
        "B2_light_tp_only_range": patch(
            {"risk": {"conflict_protection": {"light_take_profit_only_range": True}}}
        ),
        "B3_light_tp_only_low_adx": patch(
            {"risk": {"conflict_protection": {"light_take_profit_max_adx_1h": 20}}}
        ),
        "B4_light_tp_only_low_score": patch(
            {"risk": {"conflict_protection": {"light_take_profit_max_signal_score": 0.70}}}
        ),
        "B5_light_tp_half_reduce": patch(
            {"risk": {"conflict_protection": {"light_take_profit_pct": 0.50}}}
        ),
        "C1_tiered_tp_conservative": patch(
            {
                "fund_flow": {
                    "take_profit_pct_levels": [0.006, 0.015, 0.025],
                    "take_profit_reduce_pct_levels": [0.50, 0.30, 0.20],
                }
            }
        ),
        "C2_tiered_tp_aggressive": patch(
            {
                "fund_flow": {
                    "take_profit_pct_levels": [0.008, 0.020, 0.035],
                    "take_profit_reduce_pct_levels": [0.40, 0.35, 0.25],
                }
            }
        ),
        "D1_max_symbols_4": patch({"fund_flow": {"max_active_symbols": 4}}),
        "D2_max_symbols_5": patch({"fund_flow": {"max_active_symbols": 5}}),
        "D3_max_symbols_6": patch({"fund_flow": {"max_active_symbols": 6}}),
        "E1_gtc_wait_2bars": patch(
            {"fund_flow": {"backtest_entry_time_in_force": "GTC", "backtest_gtc_expire_bars": 2}}
        ),
        "E2_gtc_wait_3bars": patch(
            {"fund_flow": {"backtest_entry_time_in_force": "GTC", "backtest_gtc_expire_bars": 3}}
        ),
        "F1_blacklist_adausdt": apply_blacklist(base, ["ADAUSDT"]),
        "F2_blacklist_ada_fet": apply_blacklist(base, ["ADAUSDT", "FETUSDT"]),
        "F3_blacklist_ada_fet_xlm": apply_blacklist(base, ["ADAUSDT", "FETUSDT", "XLMUSDT"]),
        "SS1_xlm_stop_1pct": patch(
            {
                "fund_flow": {
                    "macd_mtf_strategy_v2": {
                        "symbol_risk_tiers": {
                            "max_stop_loss_pct_by_symbol": {"XLMUSDT": 0.010}
                        }
                    }
                }
            }
        ),
        "SS2_sol_stop_1_5pct": patch(
            {
                "fund_flow": {
                    "macd_mtf_strategy_v2": {
                        "symbol_risk_tiers": {
                            "max_stop_loss_pct_by_symbol": {"SOLUSDT": 0.015}
                        }
                    }
                }
            }
        ),
        "SS3_algo_jst_stop_1_5pct": patch(
            {
                "fund_flow": {
                    "macd_mtf_strategy_v2": {
                        "symbol_risk_tiers": {
                            "max_stop_loss_pct_by_symbol": {
                                "ALGOUSDT": 0.015,
                                "JSTUSDT": 0.015,
                            }
                        }
                    }
                }
            }
        ),
        "SS4_tail_risk_stop_caps": patch(
            {
                "fund_flow": {
                    "macd_mtf_strategy_v2": {
                        "symbol_risk_tiers": {
                            "max_stop_loss_pct_by_symbol": {
                                "XLMUSDT": 0.010,
                                "SOLUSDT": 0.015,
                                "ALGOUSDT": 0.015,
                                "JSTUSDT": 0.015,
                            }
                        }
                    }
                }
            }
        ),
        "SS5_blacklist_xlm": apply_blacklist(base, ["XLMUSDT"]),
    }


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def find_summary_from_stdout(stdout: str) -> Path:
    for line in reversed(stdout.splitlines()):
        if "摘要已保存:" in line:
            return PROJECT_ROOT / line.split("摘要已保存:", 1)[1].strip()
    raise RuntimeError("could not find summary path in backtest output")


def parse_summary(path: Path) -> Dict[str, Any]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    trades = int(summary.get("total_trades", 0) or 0)
    wins = int(summary.get("winning_trades", 0) or 0)
    losses = int(summary.get("losing_trades", 0) or 0)
    final_capital = safe_number(summary.get("final_capital"))
    initial_capital = safe_number(summary.get("initial_capital"), 10000.0)
    risk_metrics = summary.get("risk_metrics", {}) if isinstance(summary.get("risk_metrics"), dict) else {}
    funnel = summary.get("execution_funnel", {}) if isinstance(summary.get("execution_funnel"), dict) else {}
    return {
        "return_pct": safe_number(summary.get("return_pct")),
        "final_capital": final_capital,
        "net_pnl": final_capital - initial_capital,
        "total_trades": trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate_pct": safe_number(summary.get("win_rate_pct")),
        "profit_factor": safe_number(summary.get("profit_factor")),
        "max_drawdown_pct": safe_number(risk_metrics.get("max_drawdown_pct")),
        "candidate_entries": int(funnel.get("candidate_entries", 0) or 0),
        "orders_submitted": int(funnel.get("orders_submitted", 0) or 0),
        "orders_filled": int(funnel.get("orders_filled", 0) or 0),
        "orders_canceled": int(funnel.get("orders_canceled", 0) or 0),
        "summary_file": str(path),
    }


def run_backtest(config_path: Path, output_prefix: Path, *, timeout_seconds: int) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "backtest_macd_v2.py"),
        "--config",
        str(config_path),
        "--strict-live-mode",
        "--simulate-live-close-layers",
        "--output-prefix",
        str(output_prefix),
        "--initial-capital",
        "10000",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"backtest failed for {config_path.name} rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return parse_summary(find_summary_from_stdout(proc.stdout))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strict-live MACD V2 return ablations.")
    parser.add_argument("--config", default="config/trading_config_fund_flow.json", help="base runtime config")
    parser.add_argument("--cases", nargs="*", default=None, help="case names to run; defaults to baseline plus common first-pass cases")
    parser.add_argument("--all", action="store_true", help="run every configured ablation case")
    parser.add_argument("--output-dir", default="output/backtest/ablation_20260503", help="output directory")
    parser.add_argument("--timeout-seconds", type=int, default=1200, help="timeout per backtest")
    args = parser.parse_args()

    base_config_path = PROJECT_ROOT / args.config
    base = load_config(base_config_path)
    suite = build_suite(base)
    if args.all:
        case_names = list(suite.keys())
    elif args.cases:
        case_names = args.cases
    else:
        case_names = [
            "00_baseline",
            "S1_max_stop_2pct",
            "S2_max_stop_1_5pct",
            "S3_max_stop_1pct",
            "S4_hard_stop_2pct",
            "S5_hard_stop_1_5pct",
            "S6_hard_stop_1pct",
        ]

    unknown = [name for name in case_names if name not in suite]
    if unknown:
        raise SystemExit(f"unknown ablation cases: {', '.join(unknown)}")

    output_dir = PROJECT_ROOT / args.output_dir
    config_dir = output_dir / "configs"
    result_dir = output_dir / "runs"
    config_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    for index, name in enumerate(case_names, start=1):
        cfg_path = config_dir / f"{name}.json"
        cfg_path.write_text(json.dumps(suite[name], ensure_ascii=False, indent=2), encoding="utf-8")
        prefix = result_dir / f"{run_id}_{index:02d}_{name}"
        print(f"[{index}/{len(case_names)}] running {name}")
        metrics = run_backtest(cfg_path, prefix, timeout_seconds=int(args.timeout_seconds))
        metrics["case"] = name
        metrics["config_file"] = str(cfg_path)
        rows.append(metrics)
        print(
            f"  return={metrics['return_pct']:+.2f}% win={metrics['win_rate_pct']:.2f}% "
            f"pf={metrics['profit_factor']:.2f} mdd={metrics['max_drawdown_pct']:.2f}% "
            f"trades={metrics['total_trades']}"
        )

    csv_path = output_dir / f"ablation_results_{run_id}.csv"
    json_path = output_dir / f"ablation_results_{run_id}.json"
    write_csv(csv_path, rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results_csv: {csv_path}")
    print(f"results_json: {json_path}")


if __name__ == "__main__":
    main()
