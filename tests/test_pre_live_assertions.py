from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_pre_live_assertions_accept_current_config() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", "config/trading_config_fund_flow.json"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All pre-live assertions passed" in result.stdout


def test_pre_live_assertions_reject_missing_combo_block(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["signal_combo_hard_block"]["enabled"] = False
    bad_cfg = tmp_path / "bad_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "signal_combo_hard_block.enabled" in result.stdout


def test_pre_live_assertions_reject_dca_enabled(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["dca_martingale_enabled"] = True
    bad_cfg = tmp_path / "bad_dca_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "dca_martingale_enabled" in result.stdout


def test_pre_live_assertions_reject_disabled_15m_quality_gate(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_quality_gates"]["15m_hard_gate"]["enabled"] = False
    bad_cfg = tmp_path / "bad_entry_quality_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "entry_quality_gates.15m_hard_gate.enabled" in result.stdout


def test_pre_live_assertions_reject_disabled_btc_entry_regime_gate(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["btc_entry_regime_gate"]["enabled"] = False
    cfg["fund_flow"]["btc_beta_risk"]["warmup_on_start"] = False
    cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_quality_gates"]["vwap_score_hard_block"]["enabled"] = True
    bad_cfg = tmp_path / "bad_btc_gate_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "btc_entry_regime_gate.enabled" in result.stdout
    assert "btc_beta_risk.warmup_on_start" in result.stdout
    assert "entry_quality_gates.vwap_score_hard_block.enabled" in result.stdout


def test_pre_live_assertions_reject_disabled_slow_bull_live_test(tmp_path: Path) -> None:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    cfg["fund_flow"]["slow_bull_live_test"]["enabled"] = False
    cfg["fund_flow"]["slow_bull_live_test"]["rsi_extreme_mode"] = "hard_block"
    cfg["fund_flow"]["slow_bull_live_test"]["capacity_replacement_shadow"]["replacement_enabled"] = True
    bad_cfg = tmp_path / "bad_slow_bull_live_config.json"
    bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/pre_live_assertions.py", "--config", str(bad_cfg)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "slow_bull_live_test.enabled" in result.stdout
    assert "slow_bull_live_test.rsi_extreme_mode" in result.stdout
    assert "capacity_replacement_shadow.replacement_enabled" in result.stdout
