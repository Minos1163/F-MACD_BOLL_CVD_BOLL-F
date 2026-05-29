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
    if vwap_gate.get("enabled") is not False:
        errors.append("vwap_deviation_gate.enabled must be false")
    if str(vwap_gate.get("mode") or "").strip().lower() not in {"observation_only", "disabled"}:
        errors.append(f"vwap_deviation_gate.mode={vwap_gate.get('mode')}, must be observation_only/disabled")
    if "vwap_deviation_hard_block" in vwap_cfg:
        errors.append("vwap_deviation_hard_block still present, must be deleted")
    weights = v2.get("scoring_weights", {}) if isinstance(v2.get("scoring_weights"), dict) else {}
    if abs(_as_float(weights.get("weight_vwap"), 1.0)) > 1e-12:
        errors.append("scoring_weights.weight_vwap must be 0.0")
    filters = v2.get("entry_filters", {}) if isinstance(v2.get("entry_filters"), dict) else {}
    for key in (
        "min_vwap_score_for_entry",
        "short_min_vwap_score_for_entry",
        "flip_bearish_short_min_vwap_score_for_entry",
        "stable_bear_continuation_min_vwap_score",
        "stable_bull_continuation_min_vwap_score",
    ):
        if _as_float(filters.get(key), 0.0) > 0.0:
            errors.append(f"entry_filters.{key} must be 0.0")
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


def assert_entry_quality_gates(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    gates = v2.get("entry_quality_gates", {}) if isinstance(v2.get("entry_quality_gates"), dict) else {}
    gate_15m = gates.get("15m_hard_gate", {}) if isinstance(gates.get("15m_hard_gate"), dict) else {}
    if gate_15m.get("enabled") is not True:
        errors.append("entry_quality_gates.15m_hard_gate.enabled must be true")
    if _as_float(gate_15m.get("medium_15m_raw"), 0.0) < 0.30:
        errors.append("entry_quality_gates.15m_hard_gate.medium_15m_raw must be >= 0.30")
    if _as_float(gate_15m.get("below_vwap_risk_pct"), 1.0) > 0.005:
        errors.append("entry_quality_gates.15m_hard_gate.below_vwap_risk_pct must be <= 0.005")
    if _as_float(gate_15m.get("risk_count_dual_probe_max"), 1.0) > 0.08:
        errors.append("entry_quality_gates.15m_hard_gate.risk_count_dual_probe_max must be <= 0.08")

    flip = gates.get("flip_bullish_size_guard", {}) if isinstance(gates.get("flip_bullish_size_guard"), dict) else {}
    if flip.get("enabled") is not True:
        errors.append("entry_quality_gates.flip_bullish_size_guard.enabled must be true")
    if str(flip.get("below_vwap_no_15m_action") or "").strip().upper() != "BLOCK":
        errors.append("entry_quality_gates.flip_bullish_size_guard.below_vwap_no_15m_action must be BLOCK")
    if _as_float(flip.get("above_vwap_15m_ok_max"), 1.0) > 0.10:
        errors.append("entry_quality_gates.flip_bullish_size_guard.above_vwap_15m_ok_max must be <= 0.10")

    adx = gates.get("adx_regime_size_cap", {}) if isinstance(gates.get("adx_regime_size_cap"), dict) else {}
    if adx.get("enabled") is not True:
        errors.append("entry_quality_gates.adx_regime_size_cap.enabled must be true")
    if _as_float(adx.get("weak_adx_threshold"), 0.0) < 20.0:
        errors.append("entry_quality_gates.adx_regime_size_cap.weak_adx_threshold must be >= 20")

    ema = gates.get("ema_conditional_multiplier", {}) if isinstance(gates.get("ema_conditional_multiplier"), dict) else {}
    if ema.get("enabled") is not True:
        errors.append("entry_quality_gates.ema_conditional_multiplier.enabled must be true")
    if ema.get("require_price_vwap_aligned") is not False:
        errors.append("entry_quality_gates.ema_conditional_multiplier.require_price_vwap_aligned must be false")
    if _as_float(ema.get("require_15m_raw_min"), 0.0) < 0.25:
        errors.append("entry_quality_gates.ema_conditional_multiplier.require_15m_raw_min must be >= 0.25")
    if _as_float(ema.get("require_adx_min"), 0.0) < 20.0:
        errors.append("entry_quality_gates.ema_conditional_multiplier.require_adx_min must be >= 20")
    vwap_score = gates.get("vwap_score_hard_block", {}) if isinstance(gates.get("vwap_score_hard_block"), dict) else {}
    if vwap_score.get("enabled") is not False:
        errors.append("entry_quality_gates.vwap_score_hard_block.enabled must be false")
    no_trade = gates.get("no_trade_gate", {}) if isinstance(gates.get("no_trade_gate"), dict) else {}
    if no_trade.get("enabled") is not True:
        errors.append("entry_quality_gates.no_trade_gate.enabled must be true")
    if _as_float(no_trade.get("block_below_score"), 0.0) < 0.85:
        errors.append("entry_quality_gates.no_trade_gate.block_below_score must be >= 0.85")
    range_gate = gates.get("range_gate", {}) if isinstance(gates.get("range_gate"), dict) else {}
    if range_gate.get("enabled") is not True:
        errors.append("entry_quality_gates.range_gate.enabled must be true")
    if _as_float(range_gate.get("block_below_score"), 0.0) < 0.80:
        errors.append("entry_quality_gates.range_gate.block_below_score must be >= 0.80")
    return errors


def assert_market_breadth_and_continuation(ff: Dict[str, Any], v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    breadth = ff.get("market_breadth", {}) if isinstance(ff.get("market_breadth"), dict) else {}
    if breadth.get("enabled") is not True:
        errors.append("market_breadth.enabled must be true")
    if _as_float(breadth.get("slow_bull_breadth_ratio"), 0.0) < 0.60:
        errors.append("market_breadth.slow_bull_breadth_ratio must be >= 0.60")
    if _as_float(breadth.get("mode_a_breadth_min"), 0.0) < 0.80:
        errors.append("market_breadth.mode_a_breadth_min must be >= 0.80")
    if _as_float(breadth.get("mode_a_alt_median_min"), 0.0) < 0.0025:
        errors.append("market_breadth.mode_a_alt_median_min must be >= 0.0025")
    if _as_float(breadth.get("mode_a_btc_min"), 0.0) > -0.001 + 1e-12:
        errors.append("market_breadth.mode_a_btc_min must be <= -0.001")
    if _as_float(breadth.get("mode_b_btc_30m_min"), 0.0) > 0.002 + 1e-12:
        errors.append("market_breadth.mode_b_btc_30m_min must be <= 0.002")
    if _as_float(breadth.get("mode_c_breadth_min"), 0.0) < 0.90:
        errors.append("market_breadth.mode_c_breadth_min must be >= 0.90")
    if _as_float(breadth.get("mode_c_alt_median_min"), 0.0) < 0.001:
        errors.append("market_breadth.mode_c_alt_median_min must be >= 0.001")
    if int(_as_float(breadth.get("confirm_cycles"), 0.0)) < 2:
        errors.append("market_breadth.confirm_cycles must be >= 2")

    cont = v2.get("continuation_long", {}) if isinstance(v2.get("continuation_long"), dict) else {}
    if cont.get("enabled") is not True:
        errors.append("continuation_long.enabled must be true")
    if int(_as_float(cont.get("min_conditions_met"), 0.0)) < 4:
        errors.append("continuation_long.min_conditions_met must be >= 4")
    if _as_float(cont.get("max_portion_6of6"), 1.0) > 0.042:
        errors.append("continuation_long.max_portion_6of6 must be <= 0.042")
    if _as_float(cont.get("max_portion_5of6"), 1.0) > 0.030:
        errors.append("continuation_long.max_portion_5of6 must be <= 0.030")
    if _as_float(cont.get("max_portion_4of6"), 1.0) > 0.020:
        errors.append("continuation_long.max_portion_4of6 must be <= 0.020")
    if cont.get("low_corr_strict_mode") is not True:
        errors.append("continuation_long.low_corr_strict_mode must be true")

    short_guard = v2.get("slow_bull_short_guard", {}) if isinstance(v2.get("slow_bull_short_guard"), dict) else {}
    if short_guard.get("enabled") is not True:
        errors.append("slow_bull_short_guard.enabled must be true")
    return errors


def assert_micro_notional_gate(ff: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if _as_float(ff.get("min_entry_notional_usdt"), 0.0) < 0.10:
        errors.append("min_entry_notional_usdt must be >= 0.10")
    if _as_float(ff.get("min_entry_margin_usdt"), 0.0) < 1.0:
        errors.append("min_entry_margin_usdt must be >= 1.0")
    return errors


def assert_slow_bull_live_test(ff: Dict[str, Any]) -> List[str]:
    cfg = ff.get("slow_bull_live_test", {})
    if not isinstance(cfg, dict):
        return ["slow_bull_live_test must be configured for 100U live test"]
    errors: List[str] = []
    if cfg.get("enabled") is not True:
        errors.append("slow_bull_live_test.enabled must be true for live slow-bull test")
    if str(cfg.get("rsi_extreme_mode") or "").strip().lower() != "cap_not_block":
        errors.append("slow_bull_live_test.rsi_extreme_mode must be cap_not_block")
    if _as_float(cfg.get("rsi_extreme_threshold"), 0.0) > 72.0:
        errors.append("slow_bull_live_test.rsi_extreme_threshold must be <= 72.0")
    max_portion = _as_float(cfg.get("rsi_extreme_max_portion"), 0.0)
    if max_portion <= 0.0 or max_portion > 0.02 + 1e-12:
        errors.append("slow_bull_live_test.rsi_extreme_max_portion must be >0 and <= 0.02")

    one_h = cfg.get("slow_bull_1h_gate_downgrade", {})
    if not isinstance(one_h, dict):
        errors.append("slow_bull_live_test.slow_bull_1h_gate_downgrade must be configured")
    else:
        if one_h.get("enabled") is not True:
            errors.append("slow_bull_1h_gate_downgrade.enabled must be true")
        if str(one_h.get("mode") or "").strip().lower() != "ignore_if_momentum_ok":
            errors.append("slow_bull_1h_gate_downgrade.mode must be ignore_if_momentum_ok")
        if _as_float(one_h.get("momentum_threshold_30m"), 0.0) > 0.003 + 1e-12:
            errors.append("slow_bull_1h_gate_downgrade.momentum_threshold_30m must be <= 0.003")
        if _as_float(one_h.get("momentum_threshold_60m"), 0.0) > 0.005 + 1e-12:
            errors.append("slow_bull_1h_gate_downgrade.momentum_threshold_60m must be <= 0.005")

    fee = cfg.get("fee_fragmentation_control", {})
    if not isinstance(fee, dict):
        errors.append("slow_bull_live_test.fee_fragmentation_control must be configured")
    else:
        if fee.get("enabled") is not True:
            errors.append("fee_fragmentation_control.enabled must be true")
        if _as_float(fee.get("min_probe_notional"), 0.0) < 1.0:
            errors.append("fee_fragmentation_control.min_probe_notional must be >= 1.0")

    replacement = cfg.get("capacity_replacement_shadow", {})
    if isinstance(replacement, dict) and replacement.get("replacement_enabled") is not False:
        errors.append("capacity_replacement_shadow.replacement_enabled must remain false in live")
    return errors


def assert_short_micro_floor(v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    pm = v2.get("position_management", {}) if isinstance(v2.get("position_management"), dict) else {}
    if _as_float(pm.get("green_bar_growing_probe_position_penalty"), 0.0) < 0.20:
        errors.append("green_bar_growing_probe_position_penalty must be >= 0.20")
    if _as_float(pm.get("probe_penalty_floor_notional_usdt"), 0.0) < 2.0:
        errors.append("probe_penalty_floor_notional_usdt must be >= 2.0")
    if "short_floor_max_lift_ratio" in pm:
        errors.append("short_floor_max_lift_ratio must be removed; final passed signals lift without ratio cap")
    guard = pm.get("vol_vwap_warn_scale_min_notional_guard", {})
    if not isinstance(guard, dict) or guard.get("enabled") is not True:
        errors.append("vol_vwap_warn_scale_min_notional_guard.enabled must be true")
    return errors


def assert_final_signal_notional_floor(ff: Dict[str, Any]) -> List[str]:
    floor = ff.get("final_signal_notional_floor", {})
    if not isinstance(floor, dict):
        return ["final_signal_notional_floor must be configured"]
    errors: List[str] = []
    if floor.get("enabled") is not True:
        errors.append("final_signal_notional_floor.enabled must be true")
    if floor.get("apply_to_final_only") is not True:
        errors.append("final_signal_notional_floor.apply_to_final_only must be true")
    return errors


def assert_position_count_limit_by_margin(ff: Dict[str, Any]) -> List[str]:
    limit = ff.get("position_count_limit_by_margin", {})
    if not isinstance(limit, dict):
        return ["position_count_limit_by_margin must be configured"]
    errors: List[str] = []
    is_quadrant = str(ff.get("strategy_mode") or "").strip().lower() == "quadrant_resonance"
    if limit.get("enabled") is not True:
        errors.append("position_count_limit_by_margin.enabled must be true")
    if _as_float(limit.get("small_margin_threshold_usdt"), 0.0) != 5.0:
        errors.append("position_count_limit_by_margin.small_margin_threshold_usdt must be 5.0")
    if int(_as_float(limit.get("max_small_margin_positions"), 0.0)) != 5:
        errors.append("position_count_limit_by_margin.max_small_margin_positions must be 5")
    expected_large = 0 if is_quadrant else 4
    expected_small_leverage = 9
    if int(_as_float(limit.get("max_large_margin_positions"), 0.0)) != expected_large:
        errors.append(f"position_count_limit_by_margin.max_large_margin_positions must be {expected_large}")
    if int(_as_float(limit.get("small_margin_leverage"), 0.0)) != expected_small_leverage:
        errors.append(f"position_count_limit_by_margin.small_margin_leverage must be {expected_small_leverage}")
    if int(_as_float(ff.get("max_leverage"), 0.0)) < 9:
        errors.append("fund_flow.max_leverage must be >= 9 for small margin leverage override")
    required_total = int(_as_float(limit.get("max_small_margin_positions"), 0.0)) + int(
        _as_float(limit.get("max_large_margin_positions"), 0.0)
    )
    if required_total > 0 and int(_as_float(ff.get("max_active_symbols"), 0.0)) < required_total:
        errors.append(f"max_active_symbols must be >= {required_total} for margin buckets")
    dyn = ff.get("dynamic_max_active_symbols", {})
    if isinstance(dyn, dict) and required_total > 0 and int(_as_float(dyn.get("max_active_symbols"), 0.0)) < required_total:
        errors.append(f"dynamic_max_active_symbols.max_active_symbols must be >= {required_total}")
    return errors


def assert_dynamic_leverage_caps(ff: Dict[str, Any], v2: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    pfr = ff.get("probe_floor_rescue", {}) if isinstance(ff.get("probe_floor_rescue"), dict) else {}
    rsi = v2.get("rsi_config", {}) if isinstance(v2.get("rsi_config"), dict) else {}
    rhythm = rsi.get("rhythm", {}) if isinstance(rsi.get("rhythm"), dict) else {}
    filters = v2.get("entry_filters", {}) if isinstance(v2.get("entry_filters"), dict) else {}
    pm = v2.get("position_management", {}) if isinstance(v2.get("position_management"), dict) else {}
    caps = {
        "probe_floor_rescue.probe_leverage_cap": pfr.get("probe_leverage_cap"),
        "rsi_config.rhythm.probe_forced_leverage": rhythm.get("probe_forced_leverage"),
        "entry_filters.preflip_trial_max_leverage": filters.get("preflip_trial_max_leverage"),
        "entry_filters.flip_bearish_normal_boll_max_leverage": filters.get("flip_bearish_normal_boll_max_leverage"),
        "position_management.red_bar_growing_probe_max_leverage": pm.get("red_bar_growing_probe_max_leverage"),
        "position_management.green_bar_growing_probe_max_leverage": pm.get("green_bar_growing_probe_max_leverage"),
    }
    for key, raw in caps.items():
        if _as_float(raw, 3.0) < 3.0:
            errors.append(f"{key} must be >= 3 for 3/4/5 leverage ladder")
    return errors


def assert_btc_beta_risk(ff: Dict[str, Any]) -> List[str]:
    beta = ff.get("btc_beta_risk", {})
    if not isinstance(beta, dict):
        return ["btc_beta_risk must be configured"]
    errors: List[str] = []
    if beta.get("enabled") is not True:
        errors.append("btc_beta_risk.enabled must be true")
    if beta.get("warmup_on_start") is not True:
        errors.append("btc_beta_risk.warmup_on_start must be true")
    if int(_as_float(beta.get("warmup_kline_limit"), 0.0)) < 50:
        errors.append("btc_beta_risk.warmup_kline_limit must be >= 50")
    if _as_float(beta.get("default_corr_major_symbols"), 0.0) < 0.35:
        errors.append("btc_beta_risk.default_corr_major_symbols must be >= 0.35")
    if _as_float(beta.get("min_corr_for_btc_weight"), 0.0) < 0.20:
        errors.append("btc_beta_risk.min_corr_for_btc_weight must be >= 0.20")
    if int(_as_float(beta.get("corr_window_bars"), 0.0)) < 48:
        errors.append("btc_beta_risk.corr_window_bars must be >= 48")
    if int(_as_float(beta.get("fast_fail_min_age_bars"), 0.0)) < 4:
        errors.append("btc_beta_risk.fast_fail_min_age_bars must be >= 4")
    if int(_as_float(beta.get("fast_fail_window_bars"), 0.0)) < 4:
        errors.append("btc_beta_risk.fast_fail_window_bars must be >= 4")
    if _as_float(beta.get("fast_fail_mae_threshold"), 0.0) > -0.0035 + 1e-12:
        errors.append("btc_beta_risk.fast_fail_mae_threshold must be <= -0.0035")
    if _as_float(beta.get("fast_fail_mfe_threshold"), 0.0) > 0.002 + 1e-12:
        errors.append("btc_beta_risk.fast_fail_mfe_threshold must be <= 0.002")
    if int(_as_float(beta.get("risk_score_reduce_threshold"), 0.0)) != 2:
        errors.append("btc_beta_risk.risk_score_reduce_threshold must be 2")
    if int(_as_float(beta.get("risk_score_close_threshold"), 0.0)) != 4:
        errors.append("btc_beta_risk.risk_score_close_threshold must be 4")
    if _as_float(beta.get("small_notional_close_threshold"), 0.0) > 5.0:
        errors.append("btc_beta_risk.small_notional_close_threshold must be <= 5")
    if _as_float(beta.get("small_notional_close_equity_pct"), 0.0) < 0.02:
        errors.append("btc_beta_risk.small_notional_close_equity_pct must be >= 0.02")
    if _as_float(beta.get("tiny_notional_skip_threshold"), 0.0) < 1.0:
        errors.append("btc_beta_risk.tiny_notional_skip_threshold must be >= 1")
    return errors


def assert_btc_entry_regime_gate(ff: Dict[str, Any]) -> List[str]:
    gate = ff.get("btc_entry_regime_gate", {})
    if not isinstance(gate, dict):
        return ["btc_entry_regime_gate must be configured"]
    errors: List[str] = []
    if gate.get("enabled") is not True:
        errors.append("btc_entry_regime_gate.enabled must be true")
    if _as_float(gate.get("falling_avg_ret"), 0.0) > -0.001 + 1e-12:
        errors.append("btc_entry_regime_gate.falling_avg_ret must be <= -0.001")
    if _as_float(gate.get("rising_avg_ret"), 0.0) < 0.001 - 1e-12:
        errors.append("btc_entry_regime_gate.rising_avg_ret must be >= 0.001")
    if int(_as_float(gate.get("chase_short_block_bars"), 0.0)) < 4:
        errors.append("btc_entry_regime_gate.chase_short_block_bars must be >= 4")
    if _as_float(gate.get("chase_short_ret_threshold"), 0.0) > -0.015 + 1e-12:
        errors.append("btc_entry_regime_gate.chase_short_ret_threshold must be <= -0.015")
    if "btc_falling_low_vwap_block" in gate:
        errors.append("btc_entry_regime_gate.btc_falling_low_vwap_block must be removed")
    if "chase_short_block_vwap" in gate:
        errors.append("btc_entry_regime_gate.chase_short_block_vwap must be removed")
    return errors


def assert_dca_disabled(ff: Dict[str, Any]) -> List[str]:
    if ff.get("dca_martingale_enabled") is not False:
        return ["dca_martingale_enabled must be false"]
    return []


def assert_quadrant_resonance(ff: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if str(ff.get("strategy_mode") or "").strip().lower() != "quadrant_resonance":
        return errors
    cfg = ff.get("quadrant_resonance", {}) if isinstance(ff.get("quadrant_resonance"), dict) else {}
    if not cfg:
        return ["quadrant_resonance config must be present when strategy_mode=quadrant_resonance"]
    risk = cfg.get("risk", {}) if isinstance(cfg.get("risk"), dict) else {}
    entry = cfg.get("entry", {}) if isinstance(cfg.get("entry"), dict) else {}
    capacity = cfg.get("capacity", {}) if isinstance(cfg.get("capacity"), dict) else {}
    audit = cfg.get("audit", {}) if isinstance(cfg.get("audit"), dict) else {}
    if _as_float(risk.get("min_entry_notional_usdt"), 0.0) < 8.0:
        errors.append("quadrant_resonance.risk.min_entry_notional_usdt must be >= 8.0")
    if _as_float(risk.get("min_entry_margin_usdt"), 0.0) < 1.0:
        errors.append("quadrant_resonance.risk.min_entry_margin_usdt must be >= 1.0")
    if int(_as_float(risk.get("max_leverage"), 99.0)) > 3:
        errors.append("quadrant_resonance.risk.max_leverage must be <= 3")
    if _as_float(risk.get("max_total_exposure_pct"), 99.0) > 0.75 + 1e-12:
        errors.append("quadrant_resonance.risk.max_total_exposure_pct must be <= 0.75")
    if _as_float(entry.get("standard_threshold"), 0.0) < 0.80:
        errors.append("quadrant_resonance.entry.standard_threshold must be >= 0.80")
    if _as_float(entry.get("transition_threshold"), 0.0) < 0.85:
        errors.append("quadrant_resonance.entry.transition_threshold must be >= 0.85")
    if _as_float(entry.get("ema20_distance_atr_mult"), 99.0) > 2.5 + 1e-12:
        errors.append("quadrant_resonance.entry.ema20_distance_atr_mult must be <= 2.5")
    if int(_as_float(capacity.get("max_active_symbols"), 99.0)) > 8:
        errors.append("quadrant_resonance.capacity.max_active_symbols must be <= 8")
    for key in ("entry_decision_path", "exit_audit_path", "capacity_replacement_path"):
        if not str(audit.get(key) or "").strip():
            errors.append(f"quadrant_resonance.audit.{key} must be configured")
    return errors


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
    errors.extend(assert_entry_quality_gates(v2))
    errors.extend(assert_short_micro_floor(v2))
    errors.extend(assert_final_signal_notional_floor(ff))
    errors.extend(assert_micro_notional_gate(ff))
    errors.extend(assert_slow_bull_live_test(ff))
    errors.extend(assert_position_count_limit_by_margin(ff))
    errors.extend(assert_dynamic_leverage_caps(ff, v2))
    errors.extend(assert_btc_beta_risk(ff))
    errors.extend(assert_btc_entry_regime_gate(ff))
    errors.extend(assert_market_breadth_and_continuation(ff, v2))
    errors.extend(assert_dca_disabled(ff))
    errors.extend(assert_quadrant_resonance(ff))

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
