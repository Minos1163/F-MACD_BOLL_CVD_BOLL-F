import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a concise risk report from backtest summary and analysis outputs.")
    parser.add_argument("--summary", required=True, help="backtest summary json")
    parser.add_argument("--analysis", required=True, help="analysis summary json")
    parser.add_argument("--output-prefix", required=True, help="output file prefix")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    risk_metrics = summary.get("risk_metrics", {}) or {}
    report = {
        "backtest_profile": summary.get("backtest_profile"),
        "config_path": summary.get("config_path"),
        "window_start_iso": summary.get("window_start_iso"),
        "window_end_iso": summary.get("window_end_iso"),
        "available_symbols": len(summary.get("available_symbols", []) or []),
        "return_pct": summary.get("return_pct"),
        "total_trades": summary.get("total_trades"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "profit_factor": summary.get("profit_factor"),
        "signals_generated": summary.get("signals_generated"),
        "true_max_drawdown_value": risk_metrics.get("max_drawdown_value"),
        "true_max_drawdown_pct": risk_metrics.get("max_drawdown_pct"),
        "true_max_drawdown_start_time": risk_metrics.get("max_drawdown_start_time"),
        "true_max_drawdown_trough_time": risk_metrics.get("max_drawdown_trough_time"),
        "true_max_drawdown_recovery_time": risk_metrics.get("max_drawdown_recovery_time"),
        "equity_curve_points": risk_metrics.get("equity_curve_points"),
        "symbols_traded": analysis.get("symbols_traded"),
        "top_symbol": analysis.get("top_symbol"),
        "worst_symbol": analysis.get("worst_symbol"),
        "max_true_drawdown_episode": analysis.get("max_true_drawdown_episode"),
        "analysis_files": {
            "symbol_breakdown_file": analysis.get("symbol_breakdown_file"),
            "drawdown_breakdown_file": analysis.get("drawdown_breakdown_file"),
            "true_drawdown_breakdown_file": analysis.get("true_drawdown_breakdown_file"),
        },
    }

    json_path = output_prefix.parent / f"{output_prefix.name}.json"
    md_path = output_prefix.parent / f"{output_prefix.name}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    top_symbol = report.get("top_symbol") or {}
    worst_symbol = report.get("worst_symbol") or {}
    max_dd = report.get("max_true_drawdown_episode") or {}
    md = "\n".join(
        [
            f"# Risk Report: {report.get('backtest_profile')}",
            "",
            f"- Config: `{report.get('config_path')}`",
            f"- Return: `{report.get('return_pct'):.2f}%`",
            f"- Trades: `{report.get('total_trades')}`",
            f"- Win rate: `{report.get('win_rate_pct'):.2f}%`",
            f"- Profit factor: `{report.get('profit_factor'):.2f}`",
            f"- True max drawdown: `${report.get('true_max_drawdown_value'):.2f}` / `{report.get('true_max_drawdown_pct'):.2f}%`",
            f"- Drawdown window: `{report.get('true_max_drawdown_start_time')}` -> `{report.get('true_max_drawdown_trough_time')}`",
            f"- Recovery: `{report.get('true_max_drawdown_recovery_time') or 'unrecovered in sample'}`",
            "",
            "## Contribution",
            f"- Top symbol: `{top_symbol.get('symbol', '')}` pnl `${float(top_symbol.get('total_pnl', 0.0)):.2f}`",
            f"- Worst symbol: `{worst_symbol.get('symbol', '')}` pnl `${float(worst_symbol.get('total_pnl', 0.0)):.2f}`",
            "",
            "## Files",
            f"- Symbol breakdown: `{analysis.get('symbol_breakdown_file')}`",
            f"- Realized drawdown breakdown: `{analysis.get('drawdown_breakdown_file')}`",
            f"- True drawdown breakdown: `{analysis.get('true_drawdown_breakdown_file')}`",
        ]
    )
    md_path.write_text(md + "\n", encoding="utf-8")

    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
