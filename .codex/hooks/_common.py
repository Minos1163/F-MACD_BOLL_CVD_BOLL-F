from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / ".codex" / "hook_state"


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw_stdin": raw}
    return data if isinstance(data, dict) else {"_stdin": data}


def emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False))


def allow() -> None:
    return


def deny_pre_tool(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
            "systemMessage": reason,
        }
    )


def block(reason: str) -> None:
    emit({"decision": "block", "reason": reason, "systemMessage": reason})


def post_feedback(reason: str, additional_context: str = "") -> None:
    out: dict[str, Any] = {
        "decision": "block",
        "reason": reason,
        "systemMessage": reason,
    }
    if additional_context:
        out["hookSpecificOutput"] = {
            "hookEventName": "PostToolUse",
            "additionalContext": additional_context,
        }
    emit(out)


def session_context(additional_context: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": additional_context,
            }
        }
    )


def run_git(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def changed_files(staged: bool = False) -> list[Path]:
    args = ["diff", "--name-only"]
    if staged:
        args.insert(1, "--cached")
    proc = run_git(args)
    if proc.returncode != 0:
        return []
    return [
        REPO_ROOT / line.strip()
        for line in proc.stdout.splitlines()
        if line.strip()
    ]


def staged_files() -> list[Path]:
    return changed_files(staged=True)


def relevant_strategy_file(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix() if path.is_absolute() else path.as_posix()
    return (
        rel.startswith("src/fund_flow/")
        or rel.startswith("src/trading/")
        or rel.startswith("src/risk/")
        or rel.startswith("scripts/backtest")
        or rel.startswith("scripts/analyze")
        or rel.startswith("scripts/compare")
        or rel.startswith("scripts/rolling")
        or rel.startswith("config/")
    ) and path.suffix.lower() in {".py", ".json", ".toml", ".yaml", ".yml"}


def text_from_payload(payload: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload.get("tool_input", payload))
    return "\n".join(parts)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def newest_file(patterns: Iterable[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(REPO_ROOT.glob(pattern))
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def latest_backtest_summary() -> Path | None:
    return newest_file(
        [
            "output/backtest/hook_latest_summary.json",
            "output/backtest/*_summary.json",
            "reports/**/*summary*.json",
        ]
    )


def write_state(name: str, data: dict[str, Any]) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / name
    payload = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def extract_metrics(summary: dict[str, Any]) -> dict[str, float]:
    risk = summary.get("risk_metrics") if isinstance(summary.get("risk_metrics"), dict) else {}
    return {
        "profit_factor": float(summary.get("profit_factor", 0.0) or 0.0),
        "trade_count": float(summary.get("total_trades", summary.get("trade_count", 0)) or 0),
        "win_rate_pct": float(summary.get("win_rate_pct", 0.0) or 0.0),
        "return_pct": float(summary.get("return_pct", 0.0) or 0.0),
        "max_drawdown_pct": abs(float(risk.get("max_drawdown_pct", summary.get("max_drawdown_pct", 0.0)) or 0.0)),
        "final_capital": float(summary.get("final_capital", 0.0) or 0.0),
        "initial_capital": float(summary.get("initial_capital", 0.0) or 0.0),
    }


def normalized_drawdown_fraction(value: float) -> float:
    return value / 100.0 if value > 1.0 else value


def contains_any(text: str, patterns: Iterable[re.Pattern[str]]) -> list[str]:
    return [pattern.pattern for pattern in patterns if pattern.search(text)]


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
