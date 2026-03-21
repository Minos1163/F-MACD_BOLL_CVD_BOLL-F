import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from src.config.config_loader import ConfigLoader


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"config root must be an object: {path}")
    return data


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _normalize_symbol_list(raw_symbols) -> list[str]:
    return ConfigLoader._normalize_symbol_list(raw_symbols)


def _apply_symbol_blacklist(cfg: dict) -> None:
    fund_flow_cfg = cfg.get("fund_flow", {}) if isinstance(cfg.get("fund_flow"), dict) else {}
    blacklist = _normalize_symbol_list(fund_flow_cfg.get("symbol_blacklist", []))
    if not blacklist:
        return

    fund_flow_cfg["symbol_blacklist"] = blacklist
    blacklist_set = set(blacklist)

    trading_cfg = cfg.get("trading", {}) if isinstance(cfg.get("trading"), dict) else {}
    trading_symbols = _normalize_symbol_list(trading_cfg.get("symbols", []))
    if trading_symbols:
        trading_cfg["symbols"] = [symbol for symbol in trading_symbols if symbol not in blacklist_set]

    backtest_cfg = fund_flow_cfg.get("backtest", {}) if isinstance(fund_flow_cfg.get("backtest"), dict) else {}
    profiles = backtest_cfg.get("profiles", {}) if isinstance(backtest_cfg.get("profiles"), dict) else {}
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        profile_symbols = _normalize_symbol_list(profile.get("symbols", []))
        if profile_symbols:
            profile["symbols"] = [symbol for symbol in profile_symbols if symbol not in blacklist_set]


def build_backtest_copy(
    base_cfg: dict,
    source_path: str,
    default_profile: str | None,
    symbol_blacklist: list[str] | None = None,
) -> dict:
    cfg = deepcopy(base_cfg)
    meta = cfg.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
    meta.update(
        {
            "generated_for": "backtest",
            "generated_from": source_path,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    cfg["_meta"] = meta

    fund_flow_cfg = cfg.setdefault("fund_flow", {})
    if not isinstance(fund_flow_cfg, dict):
        raise ValueError("fund_flow config must be an object")
    backtest_cfg = fund_flow_cfg.setdefault("backtest", {})
    if not isinstance(backtest_cfg, dict):
        raise ValueError("fund_flow.backtest config must be an object")

    if symbol_blacklist is not None:
        fund_flow_cfg["symbol_blacklist"] = _normalize_symbol_list(symbol_blacklist)

    _apply_symbol_blacklist(cfg)

    if default_profile:
        backtest_cfg["default_profile"] = default_profile

    return cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a dedicated JSON config for backtests from a live config.")
    parser.add_argument("--base", required=True, help="source live config path")
    parser.add_argument("--output", required=True, help="output backtest config path")
    parser.add_argument("--default-profile", default=None, help="optional default backtest profile name")
    parser.add_argument("--set-symbol-blacklist", nargs="*", default=None, help="optional symbol blacklist to persist into fund_flow.symbol_blacklist")
    args = parser.parse_args()

    base_path = Path(args.base)
    output_path = Path(args.output)
    base_cfg = load_json(base_path)
    backtest_cfg = build_backtest_copy(
        base_cfg,
        str(base_path),
        args.default_profile,
        symbol_blacklist=args.set_symbol_blacklist,
    )
    save_json(output_path, backtest_cfg)

    print(f"generated backtest config: {output_path}")
    print(f"source config: {base_path}")
    if args.default_profile:
        print(f"default_profile: {args.default_profile}")
    blacklist = ConfigLoader.get_symbol_blacklist(backtest_cfg)
    if blacklist:
        print(f"symbol_blacklist: {', '.join(blacklist)}")


if __name__ == "__main__":
    main()
