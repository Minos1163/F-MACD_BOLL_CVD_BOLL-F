from __future__ import annotations

import json
from datetime import datetime

from _common import REPO_ROOT, extract_metrics, latest_backtest_summary, write_state


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    journal_dir = REPO_ROOT / "research" / today
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / "hook_journal.md"

    summary_path = latest_backtest_summary()
    if summary_path and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        metrics = extract_metrics(summary)
        line = (
            f"- {datetime.now().isoformat(timespec='seconds')} summary={summary_path.relative_to(REPO_ROOT).as_posix()} "
            f"return={metrics['return_pct']:.2f}% pf={metrics['profit_factor']:.2f} "
            f"dd={metrics['max_drawdown_pct']:.2f} trades={metrics['trade_count']:.0f}\n"
        )
    else:
        line = f"- {datetime.now().isoformat(timespec='seconds')} no backtest summary available\n"

    if not journal_path.exists():
        journal_path.write_text(f"# Hook Journal {today}\n\n", encoding="utf-8")
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    write_state("last_journal.json", {"journal": str(journal_path), "summary": str(summary_path or "")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
