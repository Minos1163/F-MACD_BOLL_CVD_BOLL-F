from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _fund_flow(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg.get("fund_flow", {}) if isinstance(cfg.get("fund_flow"), dict) else {}


def _rule(rules: List[Dict[str, Any]], direction: str, signal_1h: str) -> Dict[str, Any] | None:
    for item in rules:
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("direction") or "").strip().lower() == direction
            and str(item.get("signal_1h") or "").strip().lower() == signal_1h
        ):
            return item
    return None


def _as_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def assert_vwap_ablation(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    vwap_cfg = v2.get("vwap_config", {}) if isinstance(v2.get("vwap_config"), dict) else {}
    vwap_gate = vwap_cfg.get("vwap_deviation_gate", {}) if isinstance(vwap_cfg.get("vwap_deviation_gate"), dict) else {}
    if str(vwap_gate.get("mode") or "").strip().lower() != "directional_ablation":
        errors.append(
            f"vwap_deviation_gate.mode={vwap_gate.get('mode')}, must be directional_ablation"
        )
    if "vwap_deviation_hard_block" in vwap_cfg:
        errors.append("vwap_deviation_hard_block still present, must be deleted")
    same_dir = vwap_gate.get("same_dir_trend_aligned", {}) if isinstance(vwap_gate.get("same_dir_trend_aligned"), dict) else {}
    if _as_float(same_dir.get("pass_dev_pct"), 0.0) < 0.04:
        errors.append(
            f"same_dir_trend_aligned.pass_dev_pct={same_dir.get('pass_dev_pct')} < 0.04, ablation ineffective"
        )
    return errors


def assert_rsi_adaptive_gate(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    rsi_cfg = v2.get("rsi_config", {}) if isinstance(v2.get("rsi_config"), dict) else {}
    rhythm = rsi_cfg.get("rhythm", {}) if isinstance(rsi_cfg.get("rhythm"), dict) else {}
    gate = rhythm.get("adaptive_direction_gate", {}) if isinstance(rhythm.get("adaptive_direction_gate"), dict) else {}
    if gate.get("enabled") is not True:
        errors.append("rsi_config.rhythm.adaptive_direction_gate.enabled must be true")
    if _as_float(gate.get("soft_rsi_against_mult"), 0.0) <= 0.0:
        errors.append("soft_rsi_against_mult must be > 0")
    if _as_float(gate.get("soft_rsi_against_max_portion"), 1.0) > 0.10:
        errors.append(
            f"soft_rsi_against_max_portion={gate.get('soft_rsi_against_max_portion')} > 0.10"
        )
    if _as_float(gate.get("soft_rsi_flat_mult"), 0.0) <= 0.0:
        errors.append("soft_rsi_flat_mult must be > 0")
    return errors


def assert_probe_notional_coherence(ff: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    notional = ff.get("min_open_notional", {}) if isinstance(ff.get("min_open_notional"), dict) else {}
    if _as_float(notional.get("default_usdt"), 0.0) <= 0.0:
        errors.append("min_open_notional.default_usdt must be configured")
    if _as_float(notional.get("default_usdt"), 99.0) > 2.0:
        errors.append("min_open_notional.default_usdt must be <= 2.0 for small accounts")
    if _as_float(notional.get("btc_usdt"), 0.0) < 5.0:
        errors.append("min_open_notional.btc_usdt must be >= 5.0")
    if _as_float(notional.get("major_usdt"), 99.0) > 2.0:
        errors.append("min_open_notional.major_usdt must be <= 2.0; only BTC should require 5U")
    if "min_open_notional_usdt" in ff:
        errors.append("min_open_notional_usdt still present; use min_open_notional instead")
    return errors


def assert_counter_trend_long_guard(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    guard = v2.get("counter_trend_long_guard", {}) if isinstance(v2.get("counter_trend_long_guard"), dict) else {}
    if guard.get("enabled") is not True:
        errors.append("counter_trend_long_guard.enabled must be true")
    if _as_float(guard.get("vwap_dev_extreme_pct"), 1.0) > 0.03:
        errors.append("counter_trend_long_guard.vwap_dev_extreme_pct must be <= 0.03")
    if _as_float(guard.get("min_15m_raw_for_confirm"), 0.0) < 0.30:
        errors.append("counter_trend_long_guard.min_15m_raw_for_confirm must be >= 0.30")
    if str(guard.get("extreme_range_action") or "").strip().upper() != "BLOCK":
        errors.append("counter_trend_long_guard.extreme_range_action must be BLOCK")
    return errors


def assert_short_micro_floor(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    pm = v2.get("position_management", {}) if isinstance(v2.get("position_management"), dict) else {}
    if _as_float(pm.get("green_bar_growing_probe_position_penalty"), 0.0) < 0.20:
        errors.append("green_bar_growing_probe_position_penalty must be >= 0.20")
    if _as_float(pm.get("probe_penalty_floor_notional_usdt"), 0.0) < 2.0:
        errors.append("probe_penalty_floor_notional_usdt must be >= 2.0")
    ratio = _as_float(pm.get("short_floor_max_lift_ratio"), 0.0)
    if ratio <= 0.0 or ratio > 5.0:
        errors.append("short_floor_max_lift_ratio must be configured in (0, 5]")
    return errors


def assert_dca_disabled(ff: Dict[str, Any]) -> List[str]:
    if ff.get("dca_martingale_enabled") is not False:
        return ["dca_martingale_enabled must be false"]
    return []


def run_assertions(config_path: Path) -> int:
    errors: List[str] = []
    cfg = _load_config(config_path)
    ff = _fund_flow(cfg)
    v2 = ff.get("macd_mtf_strategy_v2", {}) if isinstance(ff.get("macd_mtf_strategy_v2"), dict) else {}
    dyn = v2.get("dynamic_position_sizing", {}) if isinstance(v2.get("dynamic_position_sizing"), dict) else {}

    combo = ff.get("signal_combo_hard_block", {}) if isinstance(ff.get("signal_combo_hard_block"), dict) else {}
    rules = combo.get("rules", []) if isinstance(combo.get("rules"), list) else []
    if combo.get("enabled") is not True:
        errors.append("signal_combo_hard_block.enabled must be true")

    checks = [
        ("long", "flip_bearish", "BLOCK"),
        ("long", "green_bar_growing", "BLOCK"),
        ("short", "flip_bullish", "BLOCK"),
        ("short", "red_bar_growing", "BLOCK"),
    ]
    for direction, signal_1h, action in checks:
        found = _rule(rules, direction, signal_1h)
        if found is None or str(found.get("action") or "").strip().upper() != action:
            errors.append(f"{direction}+{signal_1h} must be {action}")

    shrink = _rule(rules, "long", "red_bar_shrinking")
    if shrink is None or str(shrink.get("action") or "").strip().upper() != "PROBE":
        errors.append("long+red_bar_shrinking must be PROBE")
    elif float(shrink.get("max_portion", 1.0) or 1.0) > 0.06:
        errors.append(f"long+red_bar_shrinking max_portion={shrink.get('max_portion')} > 0.06")

    floor = dyn.get("total_compression_floor", {}) if isinstance(dyn.get("total_compression_floor"), dict) else {}
    if floor.get("enabled") is True:
        errors.append("total_compression_floor.enabled must be false for emergency baseline")

    pfr = ff.get("probe_floor_rescue", {}) if isinstance(ff.get("probe_floor_rescue"), dict) else {}
    if pfr.get("shadow_mode") is not True:
        errors.append("probe_floor_rescue.shadow_mode must be true")

    ec = ff.get("exit_cooldown", {}) if isinstance(ff.get("exit_cooldown"), dict) else {}
    if ec.get("enabled") is not True:
        errors.append("exit_cooldown.enabled must be true")

    pc = v2.get("partial_confirm", {}) if isinstance(v2.get("partial_confirm"), dict) else {}
    if pc.get("shadow_mode") is not True:
        errors.append("partial_confirm.shadow_mode must remain true")

    errors.extend(assert_vwap_ablation(v2))
    errors.extend(assert_rsi_adaptive_gate(v2))
    errors.extend(assert_probe_notional_coherence(ff))
    errors.extend(assert_counter_trend_long_guard(v2))
    errors.extend(assert_short_micro_floor(v2))
    errors.extend(assert_dca_disabled(ff))

    if errors:
        print("PRE-LIVE ASSERTIONS FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("All pre-live assertions passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/trading_config_fund_flow.json")
    args = parser.parse_args()
    return run_assertions(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
