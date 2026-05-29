from __future__ import annotations

import hashlib
import argparse
import os
import subprocess
from pathlib import Path

from _common import REPO_ROOT, changed_files, relevant_strategy_file, write_state


BACKTEST_CMD = [
    "python",
    "scripts/backtest_macd_v2.py",
    "--config",
    "config/trading_config_fund_flow.json",
    "--strict-live-mode",
    "--simulate-live-close-layers",
    "--output-prefix",
    "output/backtest/hook_latest",
]


def fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        rel = path.relative_to(REPO_ROOT).as_posix()
        digest.update(rel.encode("utf-8"))
        if path.exists() and path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or require the strategy backtest gate.")
    parser.add_argument("--force", action="store_true", help="Run the full backtest instead of only marking it required.")
    args = parser.parse_args()

    relevant = [path for path in changed_files() if path.exists() and relevant_strategy_file(path)]
    if not relevant:
        write_state("last_backtest.json", {"status": "skipped", "reason": "no relevant strategy/config changes"})
        return 0

    if not args.force and os.environ.get("CODEX_RUN_BACKTEST_HOOK", "").strip().lower() not in {"1", "true", "yes", "on"}:
        write_state(
            "last_backtest.json",
            {
                "status": "required",
                "reason": "relevant strategy/config changes detected; run python .codex/hooks/pre_backtest.py --force",
                "changed_files": [path.relative_to(REPO_ROOT).as_posix() for path in relevant],
            },
        )
        return 0

    if not (REPO_ROOT / "data" / "backtest_cache").exists():
        write_state("last_backtest.json", {"status": "skipped", "reason": "missing data/backtest_cache"})
        return 0

    fp = fingerprint(relevant)
    fp_path = REPO_ROOT / ".codex" / "hook_state" / "backtest_fingerprint.txt"
    if fp_path.exists() and fp_path.read_text(encoding="utf-8").strip() == fp:
        write_state("last_backtest.json", {"status": "skipped", "reason": "fingerprint already tested", "fingerprint": fp})
        return 0

    proc = subprocess.run(BACKTEST_CMD, cwd=REPO_ROOT, text=True, capture_output=True, timeout=1200)
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    if proc.returncode == 0:
        fp_path.write_text(fp, encoding="utf-8")

    write_state(
        "last_backtest.json",
        {
            "status": "passed" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "fingerprint": fp,
            "changed_files": [path.relative_to(REPO_ROOT).as_posix() for path in relevant],
            "command": BACKTEST_CMD,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        },
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
