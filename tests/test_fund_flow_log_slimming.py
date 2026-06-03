from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app import fund_flow_bot as bot_module
from src.app.fund_flow_bot import TradingBot
from src.fund_flow.attribution_engine import FundFlowAttributionEngine
from src.fund_flow.models import FundFlowDecision, Operation


def test_minimal_attribution_keeps_decision_summary_and_omits_bulky_context(tmp_path: Path) -> None:
    engine = FundFlowAttributionEngine(tmp_path, mode="minimal")
    decision = FundFlowDecision(
        operation=Operation.BUY,
        symbol="BTCUSDT",
        target_portion_of_balance=0.123456789,
        leverage=4,
        reason="macd_v2_long_1h_red_bar_shrinking_15m__vwap_0.85",
        metadata={
            "signal_score": 0.812345,
            "signal_type_1h": "red_bar_shrinking",
            "signal_type_15m": "red_bar_growing",
            "vwap_score": 0.85,
            "large_debug_blob": {"nested": list(range(50))},
        },
    )

    engine.log_decision(
        decision,
        {
            "symbol": "BTCUSDT",
            "price": 100.123456789,
            "portfolio": {"cash": 10, "positions": {"BTCUSDT": {"amount": 1}}},
            "flow_context": {
                "cvd_ratio": 0.1,
                "timeframes": {
                    "1m": {"cvd_ratio": 0.1},
                    "5m": {"cvd_ratio": 0.2},
                    "15m": {"cvd_ratio": 0.3},
                    "1h": {"cvd_ratio": 0.4},
                },
            },
            "trigger_context": {"full": "not needed in minimal attribution"},
        },
    )

    rec = json.loads((tmp_path / "fund_flow_attribution.jsonl").read_text(encoding="utf-8"))

    assert rec["event"] == "decision"
    assert rec["context"] == {"symbol": "BTCUSDT", "price": pytest.approx(100.123457)}
    assert rec["decision"]["metadata"]["signal_score"] == pytest.approx(0.812345)
    assert rec["decision"]["metadata"]["signal_type_1h"] == "red_bar_shrinking"
    assert "portfolio" not in rec["context"]
    assert "flow_context" not in rec["context"]
    assert "trigger_context" not in rec["context"]
    assert "large_debug_blob" not in rec["decision"]["metadata"]


def test_risk_state_save_writes_compact_json_without_empty_default_sections(tmp_path: Path) -> None:
    bot = TradingBot.__new__(TradingBot)
    bot._risk_state_path = str(tmp_path / "fund_flow_risk_state.json")
    bot._consecutive_losses = 0
    bot._cooldown_reason = None
    bot._cooldown_expires = None
    bot._daily_open_equity = None
    bot._daily_open_date = None
    bot._peak_equity = None
    bot._dca_stage_by_pos = {}
    bot._winner_pyramid_stage_by_pos = {}
    bot._protection_plan_by_pos = {}
    bot._conflict_exit_streak_by_symbol = {}
    bot._conflict_cooldown_until_by_symbol = {}
    bot._conflict_cooldown_reason_by_symbol = {}

    bot._save_risk_state()

    text = Path(bot._risk_state_path).read_text(encoding="utf-8")
    data = json.loads(text)

    assert "\n" not in text.strip()
    assert "updated_at" in data
    assert "dca_stage_by_pos" not in data
    assert "winner_pyramid_stage_by_pos" not in data
    assert "protection_plan_by_pos" not in data
    assert "conflict_exit_streak_by_symbol" not in data


def test_market_storage_db_can_be_disabled_without_creating_strategy_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: List[Dict[str, Any]] = []

    class _Storage:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(bot_module, "MarketStorage", _Storage)

    bot = TradingBot.__new__(TradingBot)
    bot.config = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "log_compaction": {"market_storage_enabled": False},
            "signal_pool": {"enabled": True, "pool_id": "default_pool", "rules": []},
        },
    }
    bot.logs_dir = str(tmp_path)
    bot.log_root_dir = str(tmp_path)
    bot.client = object()
    bot._dynamic_stop_loss_enabled = False
    bot._build_signal_pool_configs_from_config = lambda ff_cfg: {}

    bot._init_fund_flow_modules()

    assert calls == []
    assert bot.fund_flow_storage is None
    assert not (tmp_path / "fund_flow_strategy.db").exists()


def test_api_cycle_stats_log_can_be_disabled(tmp_path: Path) -> None:
    bot = TradingBot.__new__(TradingBot)
    bot.config = {"logging": {"api_cycle_stats_enabled": False}}
    bot.log_root_dir = str(tmp_path)
    bot._api_cycle_stats_log_name = "api_cycle_stats_utc.jsonl"

    bot._append_api_cycle_stats_log({"processed": 1})

    assert not list(tmp_path.rglob("api_cycle_stats_utc.jsonl"))


def test_runtime_log_sink_can_be_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    created: List[Dict[str, Any]] = []

    class _Writer:
        def __init__(self, root_dir: str, file_name: str) -> None:
            created.append({"root_dir": root_dir, "file_name": file_name})

    monkeypatch.setattr(bot_module, "_SixHourBucketFile", _Writer)

    bot = TradingBot.__new__(TradingBot)
    bot.config = {"logging": {"runtime_file_enabled": False}}
    bot.log_root_dir = str(tmp_path)
    bot._runtime_out_fp = None
    bot._runtime_err_fp = None

    bot._configure_runtime_log_sink()

    assert created == []
    assert bot._runtime_out_fp is None
    assert bot._runtime_err_fp is None


def test_startup_manifest_static_includes_version_and_quadrant_keys() -> None:
    config = {
        "fund_flow": {
            "quadrant_resonance": {
                "entry": {
                    "entry_15m_quality_model": "structural_v2",
                    "entry_15m_quality_open_min": 0.60,
                    "entry_15m_quality_watch_min": 0.40,
                    "watchlist_direct_open_enabled": True,
                    "watchlist_fallback_min_portion": 0.033,
                    "ema_conflict_entry_penalty": 0.05,
                }
            }
        }
    }

    manifest = TradingBot._build_startup_manifest_static(
        config=config,
        config_path="config/trading_config_fund_flow.json",
    )

    assert manifest["event"] == "STARTUP_MANIFEST"
    assert manifest["config_path"] == "config/trading_config_fund_flow.json"
    assert manifest["config_hash"]
    assert "git_commit" in manifest
    assert "git_dirty" in manifest
    assert manifest["quadrant_resonance"]["entry_15m_quality_model"] == "structural_v2"
    assert manifest["quadrant_resonance"]["entry_15m_quality_open_min"] == pytest.approx(0.60)
    assert manifest["quadrant_resonance"]["entry_15m_quality_watch_min"] == pytest.approx(0.40)
    assert manifest["quadrant_resonance"]["watchlist_direct_open_enabled"] is True
    assert manifest["quadrant_resonance"]["watchlist_fallback_min_portion"] == pytest.approx(0.033)
    assert manifest["quadrant_resonance"]["ema_conflict_entry_penalty"] == pytest.approx(0.05)
