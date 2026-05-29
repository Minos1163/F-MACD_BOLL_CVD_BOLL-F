from __future__ import annotations

from pathlib import Path

from _common import REPO_ROOT, session_context, write_state


def main() -> int:
    expected = [
        REPO_ROOT / "config" / "trading_config_fund_flow.json",
        REPO_ROOT / "scripts" / "backtest_macd_v2.py",
        REPO_ROOT / "data" / "backtest_cache",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in expected if not path.exists()]
    write_state("session_start.json", {"missing": missing})

    context = (
        "Crypto quant guardrails are active for this repository. Before strategy edits, state the "
        "hypothesis, expected regime, failure mode, and verification command. Never use lookahead "
        "data, repaint signals, or same-bar fill assumptions. Run the hook scripts manually if "
        "Codex lifecycle hooks are unavailable on this platform."
    )
    if missing:
        context += " Missing expected research assets: " + ", ".join(missing) + "."
    session_context(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
