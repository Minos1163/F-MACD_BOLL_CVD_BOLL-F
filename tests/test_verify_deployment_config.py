from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_verify_deployment_accepts_current_live_config() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", "config/trading_config_fund_flow.json"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "部署验证通过" in result.stdout


def test_verify_deployment_rejects_live_probe_config(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["probe_floor_rescue"]["shadow_mode"] = False
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "probe_floor_rescue.shadow_mode" in result.stdout


def test_verify_deployment_rejects_non_directional_vwap_gate(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["vwap_config"]["vwap_deviation_gate"]["mode"] = "atr_normalized"
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "vwap_deviation_gate.mode" in result.stdout


def test_verify_deployment_rejects_legacy_vwap_hard_block_field(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["vwap_config"]["vwap_deviation_hard_block"] = 0.03
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "vwap_deviation_hard_block" in result.stdout


def test_verify_deployment_rejects_ineffective_directional_vwap_ablation(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["scoring_weights"]["weight_vwap"] = 0.05
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "weight_vwap" in result.stdout


def test_verify_deployment_rejects_disabled_partial_confirm_shadow(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["partial_confirm"] = {
        "enabled": False,
        "shadow_mode": False,
        "thresholds": {"MEDIUM": 0.58},
    }
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "partial_confirm" in result.stdout


def test_verify_deployment_rejects_disabled_runtime_log_or_enabled_heavy_outputs(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["logging"]["runtime_file_enabled"] = False
    cfg["logging"]["api_cycle_stats_enabled"] = True
    cfg["fund_flow"]["log_compaction"]["market_storage_enabled"] = True
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "runtime_file_enabled" in result.stdout
    assert "api_cycle_stats_enabled" in result.stdout
    assert "market_storage_enabled" in result.stdout


def test_verify_deployment_rejects_unsafe_ioc_execution_settings(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["execution_degradation"]["open_ioc_retry_step_bps"] = 15
    cfg["fund_flow"]["execution_degradation"]["open_ioc_retry_times"] = 3
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["entry_market_fallback_min_score"] = 0.68
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "open_ioc_retry_step_bps" in result.stdout
    assert "open_ioc_retry_times" in result.stdout
    assert "entry_market_fallback_min_score" in result.stdout


def test_verify_deployment_rejects_quadrant_bucket_total_cap_below_four(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["max_active_symbols"] = 3
    cfg["fund_flow"]["dynamic_max_active_symbols"]["max_active_symbols"] = 3
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "max_active_symbols" in result.stdout


def test_verify_deployment_rejects_missing_quadrant_small_margin_nine_x_leverage(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["position_count_limit_by_margin"]["small_margin_leverage"] = 5
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "small_margin_leverage" in result.stdout


def test_verify_deployment_rejects_two_x_leverage_caps(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    v2 = cfg["fund_flow"]["macd_mtf_strategy_v2"]
    v2["rsi_config"]["rhythm"]["probe_forced_leverage"] = 2
    v2["entry_filters"]["preflip_trial_max_leverage"] = 2
    v2["position_management"]["red_bar_growing_probe_max_leverage"] = 2
    v2["position_management"]["green_bar_growing_probe_max_leverage"] = 2
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "leverage" in result.stdout


def test_verify_deployment_rejects_disabled_btc_beta_risk(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["btc_beta_risk"] = {
        "enabled": False,
        "min_corr_for_btc_weight": 0.20,
        "risk_score_reduce_threshold": 3,
        "risk_score_close_threshold": 5,
    }
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "btc_beta_risk.enabled" in result.stdout


def test_verify_deployment_rejects_unsafe_btc_beta_thresholds(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["btc_beta_risk"] = {
        "enabled": True,
        "min_corr_for_btc_weight": 0.10,
        "fast_fail_window_bars": 3,
        "fast_fail_mae_threshold": -0.001,
        "fast_fail_mfe_threshold": 0.003,
        "risk_score_reduce_threshold": 2,
        "risk_score_close_threshold": 4,
    }
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "btc_beta_risk.min_corr_for_btc_weight" in result.stdout
    assert "btc_beta_risk.risk_score_reduce_threshold" in result.stdout
    assert "btc_beta_risk.risk_score_close_threshold" in result.stdout


def test_verify_deployment_rejects_missing_btc_warmup_and_entry_gate(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["btc_beta_risk"]["warmup_on_start"] = False
    cfg["fund_flow"]["btc_beta_risk"]["warmup_kline_limit"] = 20
    cfg["fund_flow"]["btc_entry_regime_gate"]["enabled"] = False
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_quality_gates"]["vwap_score_hard_block"]["enabled"] = True
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_quality_gates"]["no_trade_gate"]["enabled"] = False
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_quality_gates"]["range_gate"]["enabled"] = False
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "btc_beta_risk.warmup_on_start" in result.stdout
    assert "btc_entry_regime_gate.enabled" in result.stdout
    assert "vwap_score_hard_block.enabled" in result.stdout
    assert "no_trade_gate.enabled" in result.stdout
    assert "range_gate.enabled" in result.stdout


def test_verify_deployment_rejects_unsafe_slow_bull_live_switches(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["slow_bull_live_test"]["enabled"] = False
    cfg["fund_flow"]["slow_bull_live_test"]["rsi_extreme_max_portion"] = 0.05
    cfg["fund_flow"]["slow_bull_live_test"]["slow_bull_1h_gate_downgrade"]["mode"] = "keep"
    cfg["fund_flow"]["slow_bull_live_test"]["fee_fragmentation_control"]["min_probe_notional"] = 0.5
    cfg["fund_flow"]["slow_bull_live_test"]["capacity_replacement_shadow"]["replacement_enabled"] = True
    bad_cfg = tmp_path / "bad_slow_bull_live_switches.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_deployment.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "slow_bull_live_test.enabled" in result.stdout
    assert "rsi_extreme_max_portion" in result.stdout
    assert "slow_bull_1h_gate_downgrade.mode" in result.stdout
    assert "fee_fragmentation_control.min_probe_notional" in result.stdout
    assert "capacity_replacement_shadow.replacement_enabled" in result.stdout
