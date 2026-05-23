from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _as_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def verify(config_path: Path) -> int:
    errors: list[str] = []
    cfg = _load_config(config_path)
    logging_cfg = cfg.get("logging", {}) if isinstance(cfg.get("logging"), dict) else {}
    ff = cfg.get("fund_flow", {}) if isinstance(cfg.get("fund_flow"), dict) else {}
    log_compaction = ff.get("log_compaction", {}) if isinstance(ff.get("log_compaction"), dict) else {}
    v2 = ff.get("macd_mtf_strategy_v2", {}) if isinstance(ff.get("macd_mtf_strategy_v2"), dict) else {}
    dyn = v2.get("dynamic_position_sizing", {}) if isinstance(v2.get("dynamic_position_sizing"), dict) else {}
    vwap_cfg = v2.get("vwap_config", {}) if isinstance(v2.get("vwap_config"), dict) else {}
    entry_filters = v2.get("entry_filters", {}) if isinstance(v2.get("entry_filters"), dict) else {}
    partial_confirm = v2.get("partial_confirm", {}) if isinstance(v2.get("partial_confirm"), dict) else {}
    execution_degradation = (
        ff.get("execution_degradation", {}) if isinstance(ff.get("execution_degradation"), dict) else {}
    )

    pf = ff.get("probe_floor_rescue", {}) if isinstance(ff.get("probe_floor_rescue"), dict) else {}
    if pf.get("shadow_mode") is not True:
        errors.append(f"fund_flow.probe_floor_rescue.shadow_mode = {pf.get('shadow_mode')}, must be true")
    if _as_float(pf.get("min_score_threshold"), 0.0) < 0.8:
        errors.append("fund_flow.probe_floor_rescue.min_score_threshold must be >= 0.80")
    if abs(_as_float(pf.get("probe_min_open_portion"), 0.0) - 0.042) > 0.001:
        errors.append(
            f"fund_flow.probe_floor_rescue.probe_min_open_portion = {pf.get('probe_min_open_portion')}, must be 0.042"
        )

    shrink = dyn.get("signal_type_caps", {}) if isinstance(dyn.get("signal_type_caps"), dict) else {}
    for key in ("red_bar_shrinking", "green_bar_shrinking"):
        apply_to = shrink.get(key, {}).get("apply_to", []) if isinstance(shrink.get(key), dict) else []
        if "signal_1h" not in apply_to:
            errors.append(f"fund_flow.macd_mtf_strategy_v2.dynamic_position_sizing.signal_type_caps.{key}.apply_to missing signal_1h")

    floor = dyn.get("total_compression_floor", {}) if isinstance(dyn.get("total_compression_floor"), dict) else {}
    if floor.get("enabled") is not False:
        errors.append("fund_flow.macd_mtf_strategy_v2.dynamic_position_sizing.total_compression_floor.enabled must be false")

    vwap_gate = vwap_cfg.get("vwap_deviation_gate", {}) if isinstance(vwap_cfg.get("vwap_deviation_gate"), dict) else {}
    if str(vwap_gate.get("mode", "")).strip().lower() != "directional_ablation":
        errors.append("fund_flow.macd_mtf_strategy_v2.vwap_config.vwap_deviation_gate.mode must be directional_ablation")
    if "vwap_deviation_hard_block" in vwap_cfg:
        errors.append("fund_flow.macd_mtf_strategy_v2.vwap_config.vwap_deviation_hard_block must be removed")
    same_dir = vwap_gate.get("same_dir_trend_aligned", {}) if isinstance(vwap_gate.get("same_dir_trend_aligned"), dict) else {}
    if _as_float(same_dir.get("pass_dev_pct"), 0.0) < 0.04:
        errors.append("fund_flow.macd_mtf_strategy_v2.vwap_config.vwap_deviation_gate.same_dir_trend_aligned.pass_dev_pct must be >= 0.04")
    if _as_float(same_dir.get("probe_dev_pct"), 0.0) > 0.15 + 1e-12:
        errors.append("fund_flow.macd_mtf_strategy_v2.vwap_config.vwap_deviation_gate.same_dir_trend_aligned.probe_dev_pct must be <= 0.15")
    ambiguous = vwap_gate.get("ambiguous", {}) if isinstance(vwap_gate.get("ambiguous"), dict) else {}
    if abs(_as_float(ambiguous.get("block_atr_mult"), 0.0) - 4.0) > 0.001:
        errors.append("fund_flow.macd_mtf_strategy_v2.vwap_config.vwap_deviation_gate.ambiguous.block_atr_mult must be 4.0")

    if partial_confirm.get("enabled") is not True:
        errors.append("fund_flow.macd_mtf_strategy_v2.partial_confirm.enabled must be true")
    if partial_confirm.get("shadow_mode") is not True:
        errors.append("fund_flow.macd_mtf_strategy_v2.partial_confirm.shadow_mode must be true before 12H shadow validation")
    pc_thresholds = partial_confirm.get("thresholds", {}) if isinstance(partial_confirm.get("thresholds"), dict) else {}
    if abs(_as_float(pc_thresholds.get("MEDIUM"), 0.0) - 0.58) > 0.001:
        errors.append("fund_flow.macd_mtf_strategy_v2.partial_confirm.thresholds.MEDIUM must be 0.58")
    pc_vwap = partial_confirm.get("vwap_safety", {}) if isinstance(partial_confirm.get("vwap_safety"), dict) else {}
    if abs(_as_float(pc_vwap.get("max_dev_atr_ratio"), 0.0) - 3.0) > 0.001:
        errors.append("fund_flow.macd_mtf_strategy_v2.partial_confirm.vwap_safety.max_dev_atr_ratio must be 3.0")

    if abs(_as_float(execution_degradation.get("open_ioc_retry_step_bps"), 0.0) - 20.0) > 0.001:
        errors.append("fund_flow.execution_degradation.open_ioc_retry_step_bps must be 20")
    if int(_as_float(execution_degradation.get("open_ioc_retry_times"), 0.0)) != 4:
        errors.append("fund_flow.execution_degradation.open_ioc_retry_times must be 4")
    if abs(_as_float(entry_filters.get("entry_market_fallback_min_score"), 0.0) - 0.72) > 0.001:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_filters.entry_market_fallback_min_score must be 0.72")

    exit_guard = ff.get("position_exit_signal_guard", {}) if isinstance(ff.get("position_exit_signal_guard"), dict) else {}
    if exit_guard.get("enabled") is not True:
        errors.append("fund_flow.position_exit_signal_guard.enabled must be true")
    if _as_float(exit_guard.get("mae_trigger_pct"), 0.0) > -0.008 + 1e-12:
        errors.append("fund_flow.position_exit_signal_guard.mae_trigger_pct must be <= -0.008")
    if int(_as_float(exit_guard.get("confirm_bars_required"), 0.0)) < 2:
        errors.append("fund_flow.position_exit_signal_guard.confirm_bars_required must be >= 2")
    if exit_guard.get("block_dca_on_reverse") is not True:
        errors.append("fund_flow.position_exit_signal_guard.block_dca_on_reverse must be true")

    beta = ff.get("btc_beta_risk", {}) if isinstance(ff.get("btc_beta_risk"), dict) else {}
    if beta.get("enabled") is not True:
        errors.append("fund_flow.btc_beta_risk.enabled must be true")
    if beta.get("warmup_on_start") is not True:
        errors.append("fund_flow.btc_beta_risk.warmup_on_start must be true")
    if int(_as_float(beta.get("warmup_kline_limit"), 0.0)) < 50:
        errors.append("fund_flow.btc_beta_risk.warmup_kline_limit must be >= 50")
    if _as_float(beta.get("default_corr_major_symbols"), 0.0) < 0.35:
        errors.append("fund_flow.btc_beta_risk.default_corr_major_symbols must be >= 0.35")
    if _as_float(beta.get("min_corr_for_btc_weight"), 0.0) < 0.20:
        errors.append("fund_flow.btc_beta_risk.min_corr_for_btc_weight must be >= 0.20")
    if int(_as_float(beta.get("corr_window_bars"), 0.0)) < 48:
        errors.append("fund_flow.btc_beta_risk.corr_window_bars must be >= 48")
    if int(_as_float(beta.get("fast_fail_window_bars"), 0.0)) != 2:
        errors.append("fund_flow.btc_beta_risk.fast_fail_window_bars must be 2")
    if _as_float(beta.get("fast_fail_mae_threshold"), 0.0) > -0.002 + 1e-12:
        errors.append("fund_flow.btc_beta_risk.fast_fail_mae_threshold must be <= -0.002")
    if _as_float(beta.get("fast_fail_mfe_threshold"), 0.0) > 0.002 + 1e-12:
        errors.append("fund_flow.btc_beta_risk.fast_fail_mfe_threshold must be <= 0.002")
    if int(_as_float(beta.get("risk_score_reduce_threshold"), 0.0)) != 2:
        errors.append("fund_flow.btc_beta_risk.risk_score_reduce_threshold must be 2")
    if int(_as_float(beta.get("risk_score_close_threshold"), 0.0)) != 4:
        errors.append("fund_flow.btc_beta_risk.risk_score_close_threshold must be 4")
    if _as_float(beta.get("small_notional_close_threshold"), 0.0) > 10.0:
        errors.append("fund_flow.btc_beta_risk.small_notional_close_threshold must be <= 10")

    btc_entry = ff.get("btc_entry_regime_gate", {}) if isinstance(ff.get("btc_entry_regime_gate"), dict) else {}
    if btc_entry.get("enabled") is not True:
        errors.append("fund_flow.btc_entry_regime_gate.enabled must be true")
    if _as_float(btc_entry.get("falling_avg_ret"), 0.0) > -0.001 + 1e-12:
        errors.append("fund_flow.btc_entry_regime_gate.falling_avg_ret must be <= -0.001")
    if _as_float(btc_entry.get("rising_avg_ret"), 0.0) < 0.001 - 1e-12:
        errors.append("fund_flow.btc_entry_regime_gate.rising_avg_ret must be >= 0.001")
    if _as_float(btc_entry.get("chase_short_ret_threshold"), 0.0) > -0.015 + 1e-12:
        errors.append("fund_flow.btc_entry_regime_gate.chase_short_ret_threshold must be <= -0.015")
    if _as_float(btc_entry.get("btc_falling_low_vwap_block"), 1.0) > 0.30:
        errors.append("fund_flow.btc_entry_regime_gate.btc_falling_low_vwap_block must be <= 0.30")

    entry_quality = v2.get("entry_quality_gates", {}) if isinstance(v2.get("entry_quality_gates"), dict) else {}
    vwap_score_gate = entry_quality.get("vwap_score_hard_block", {}) if isinstance(entry_quality.get("vwap_score_hard_block"), dict) else {}
    if vwap_score_gate.get("enabled") is not True:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.vwap_score_hard_block.enabled must be true")
    if _as_float(vwap_score_gate.get("below_block"), 1.0) > 0.12:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.vwap_score_hard_block.below_block must be <= 0.12")
    if _as_float(vwap_score_gate.get("below_probe"), 1.0) > 0.30:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.vwap_score_hard_block.below_probe must be <= 0.30")
    if _as_float(vwap_score_gate.get("probe_max"), 1.0) > 0.042:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.vwap_score_hard_block.probe_max must be <= 0.042")
    no_trade_gate = entry_quality.get("no_trade_gate", {}) if isinstance(entry_quality.get("no_trade_gate"), dict) else {}
    if no_trade_gate.get("enabled") is not True:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.no_trade_gate.enabled must be true")
    range_gate = entry_quality.get("range_gate", {}) if isinstance(entry_quality.get("range_gate"), dict) else {}
    if range_gate.get("enabled") is not True:
        errors.append("fund_flow.macd_mtf_strategy_v2.entry_quality_gates.range_gate.enabled must be true")

    position_limit = ff.get("position_count_limit_by_margin", {}) if isinstance(ff.get("position_count_limit_by_margin"), dict) else {}
    required_total_cap = int(_as_float(position_limit.get("max_small_margin_positions"), 0.0)) + int(
        _as_float(position_limit.get("max_large_margin_positions"), 0.0)
    )
    if position_limit.get("enabled") is True and required_total_cap > 0:
        if int(_as_float(ff.get("max_active_symbols"), 0.0)) < required_total_cap:
            errors.append("fund_flow.max_active_symbols must be >= small+large bucket total")
        dyn_cap = ff.get("dynamic_max_active_symbols", {}) if isinstance(ff.get("dynamic_max_active_symbols"), dict) else {}
        if int(_as_float(dyn_cap.get("max_active_symbols"), 0.0)) < required_total_cap:
            errors.append("fund_flow.dynamic_max_active_symbols.max_active_symbols must be >= small+large bucket total")
        if int(_as_float(position_limit.get("small_margin_leverage"), 0.0)) != 9:
            errors.append("fund_flow.position_count_limit_by_margin.small_margin_leverage must be 9")
        if int(_as_float(ff.get("max_leverage"), 0.0)) < 9:
            errors.append("fund_flow.max_leverage must be >= 9 for small margin leverage override")

    rsi_rhythm = v2.get("rsi_config", {}).get("rhythm", {}) if isinstance(v2.get("rsi_config"), dict) else {}
    position_management = v2.get("position_management", {}) if isinstance(v2.get("position_management"), dict) else {}
    leverage_caps = {
        "fund_flow.probe_floor_rescue.probe_leverage_cap": pf.get("probe_leverage_cap"),
        "rsi_config.rhythm.probe_forced_leverage": rsi_rhythm.get("probe_forced_leverage"),
        "entry_filters.preflip_trial_max_leverage": entry_filters.get("preflip_trial_max_leverage"),
        "entry_filters.flip_bearish_normal_boll_max_leverage": entry_filters.get("flip_bearish_normal_boll_max_leverage"),
        "position_management.red_bar_growing_probe_max_leverage": position_management.get("red_bar_growing_probe_max_leverage"),
        "position_management.green_bar_growing_probe_max_leverage": position_management.get("green_bar_growing_probe_max_leverage"),
    }
    for key, raw in leverage_caps.items():
        if _as_float(raw, 3.0) < 3.0:
            errors.append(f"fund_flow.macd_mtf_strategy_v2.{key} must be >= 3 for 3/4/5 leverage ladder")

    if logging_cfg.get("runtime_file_enabled") is not True:
        errors.append("logging.runtime_file_enabled must be true to retain runtime.out.*.log")
    if logging_cfg.get("api_cycle_stats_enabled") is not False:
        errors.append("logging.api_cycle_stats_enabled must be false for VPS log slimming")
    if log_compaction.get("market_storage_enabled") is not False:
        errors.append("fund_flow.log_compaction.market_storage_enabled must be false for VPS log slimming")
    if str(log_compaction.get("attribution_mode") or "").strip().lower() != "minimal":
        errors.append("fund_flow.log_compaction.attribution_mode must be minimal")

    if errors:
        print("部署验证失败:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("部署验证通过，配置路径与关键 live 参数正确")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/trading_config_fund_flow.json")
    args = parser.parse_args()
    return verify(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
