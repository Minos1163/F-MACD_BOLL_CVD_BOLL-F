from __future__ import annotations

import argparse
import re
from pathlib import Path

from _common import (
    REPO_ROOT,
    allow,
    changed_files,
    contains_any,
    deny_pre_tool,
    read_payload,
    read_text,
    relevant_strategy_file,
    staged_files,
    text_from_payload,
)


DANGER_PATTERNS = [
    re.compile(r"\.shift\s*\(\s*-\s*\d+"),
    re.compile(r"\.shift\s*\(\s*periods\s*=\s*-\s*\d+"),
    re.compile(r"\blead\s*\("),
    re.compile(r"\bfuture_(?:return|close|high|low|price|candle)\b", re.IGNORECASE),
    re.compile(r"\bnext_(?:candle|bar|close|high|low|price)\b", re.IGNORECASE),
    re.compile(r"\blookahead\b", re.IGNORECASE),
    re.compile(r"\brepaint(?:ing)?\b", re.IGNORECASE),
    re.compile(r"rolling\s*\([^)]*center\s*=\s*True"),
    re.compile(r"\bentry_time\s*==\s*exit_time\b"),
]


def scan_text(label: str, text: str) -> list[str]:
    matches = contains_any(text, DANGER_PATTERNS)
    return [f"{label}: {match}" for match in matches]


def scan_files(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        if not path.exists() or not relevant_strategy_file(path):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        findings.extend(scan_text(rel, read_text(path)))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Block high-confidence future leak patterns.")
    parser.add_argument("--staged", action="store_true", help="Scan staged files for pre-commit.")
    parser.add_argument("--all-changed", action="store_true", help="Scan changed files in the worktree.")
    args = parser.parse_args()

    if args.staged:
        findings = scan_files(staged_files())
        if findings:
            print("Future leak guard blocked staged changes:\n" + "\n".join(f"- {item}" for item in findings))
            return 2
        return 0

    if args.all_changed:
        findings = scan_files(changed_files())
        if findings:
            print("Future leak guard found changed-file risks:\n" + "\n".join(f"- {item}" for item in findings))
            return 2
        return 0

    payload = read_payload()
    findings = scan_text("tool_input", text_from_payload(payload))
    if findings:
        deny_pre_tool("Future-leak pattern detected. " + "; ".join(findings[:5]))
        return 0

    allow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
