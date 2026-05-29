from __future__ import annotations

import argparse
import re
from pathlib import Path

from _common import REPO_ROOT, allow, deny_pre_tool, env_flag, read_payload, staged_files, text_from_payload


PROTECTED_PATHS = [
    "src/app/fund_flow_bot.py",
    "src/fund_flow/execution_router.py",
    "src/fund_flow/risk_engine.py",
    "src/trading/risk_manager.py",
    "config/trading_config_fund_flow_live_production.json",
    ".env",
]

LIVE_CONFIG_RE = re.compile(r"config/trading_config_fund_flow_live.*\.json", re.IGNORECASE)
WRITE_INTENT_RE = re.compile(
    r"\b(apply_patch|set-content|out-file|new-item|remove-item|move-item|copy-item|del |erase |rm |mv |cp |python .*open\s*\()",
    re.IGNORECASE,
)


def is_protected(path: Path | str) -> bool:
    rel = path.as_posix() if isinstance(path, Path) else str(path).replace("\\", "/")
    if rel.startswith(str(REPO_ROOT).replace("\\", "/")):
        rel = Path(rel).relative_to(REPO_ROOT).as_posix()
    return rel in PROTECTED_PATHS or bool(LIVE_CONFIG_RE.fullmatch(rel))


def protected_mentions(text: str) -> list[str]:
    normalized = text.replace("\\", "/").lower()
    hits = [path for path in PROTECTED_PATHS if path.lower() in normalized]
    hits.extend(match.group(0) for match in LIVE_CONFIG_RE.finditer(normalized))
    return sorted(set(hits))


def main() -> int:
    parser = argparse.ArgumentParser(description="Protect live execution and risk surfaces.")
    parser.add_argument("--staged", action="store_true", help="Scan staged paths for pre-commit.")
    args = parser.parse_args()

    if args.staged:
        blocked = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in staged_files()
            if is_protected(path)
        ]
        if blocked and not env_flag("ALLOW_LIVE_ENGINE_COMMIT"):
            print(
                "Live risk guard blocked staged protected files. Set ALLOW_LIVE_ENGINE_COMMIT=1 "
                "only after explicitly documenting the live-change hypothesis, rollback plan, "
                "and verification evidence.\n"
                + "\n".join(f"- {path}" for path in blocked)
            )
            return 2
        return 0

    payload = read_payload()
    text = text_from_payload(payload)
    hits = protected_mentions(text)
    if hits and WRITE_INTENT_RE.search(text) and not env_flag("ALLOW_LIVE_ENGINE_EDIT"):
        deny_pre_tool(
            "Live execution/risk surface edit blocked without explicit override: "
            + ", ".join(hits[:8])
            + ". Set ALLOW_LIVE_ENGINE_EDIT=1 only for an intentional live change."
        )
        return 0

    allow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
