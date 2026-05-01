from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.config.config_loader import ConfigLoader
from scripts.generate_backtest_config import build_backtest_copy
from scripts.backtest_macd_v2 import (
    BacktestConfig,
    BacktestEngine,
    apply_backtest_profile,
    build_backtest_summary,
    build_strategy_config,
)
from src.fund_flow.macd_strategy_v2 import MACDSignalV2, MACDStrategyV2Config


def _load_live_runtime_config() -> dict:
    config_path = Path("D:/AIDCA/AI2/config/trading_config_fund_flow.json")
    return json.loads(config_path.read_text(encoding="utf-8"))


def test_apply_backtest_profile_disables_short_filter_only_for_backtest() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT", "ETHUSDT"]},
        "fund_flow": {
            "allowed_entry_hours_utc": [],
            "macd_mtf_strategy_v2": {
                "short_quality_filter": {
                    "enabled": True,
                    "min_funding_rate": 0.0005,
                }
            },
            "backtest": {
                "default_profile": "",
                "profiles": {
                    "macd_v2_disable_short_filter": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "short_quality_filter": {"enabled": False}
                                }
                            }
                        }
                    }
                },
            },
        },
    }

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_disable_short_filter",
    )

    assert active_profile == "macd_v2_disable_short_filter"
    assert runtime_cfg["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["enabled"] is True
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["enabled"] is False
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["min_funding_rate"] == 0.0005


def test_apply_backtest_profile_maps_symbols_and_allowed_hours() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "allowed_entry_hours_utc": [],
            "backtest": {
                "default_profile": "",
                "profiles": {
                    "focus": {
                        "symbols": ["solusdt", "atomusdt"],
                        "allowed_entry_hours": [0, 6, 12],
                    }
                },
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg, profile_name="focus")

    assert active_profile == "focus"
    assert merged["trading"]["symbols"] == ["SOLUSDT", "ATOMUSDT"]
    assert merged["fund_flow"]["allowed_entry_hours_utc"] == [0, 6, 12]


def test_apply_backtest_profile_uses_default_profile_when_requested() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "short_quality_filter": {"enabled": True}
            },
            "backtest": {
                "default_profile": "macd_v2_disable_short_filter",
                "profiles": {
                    "macd_v2_disable_short_filter": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "short_quality_filter": {"enabled": False}
                                }
                            }
                        }
                    }
                },
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg)

    assert active_profile == "macd_v2_disable_short_filter"
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["enabled"] is False


def test_live_runtime_config_contains_soft_long_threshold_ablation_profiles() -> None:
    runtime_cfg = _load_live_runtime_config()
    profiles = runtime_cfg["fund_flow"]["backtest"]["profiles"]

    profile_080 = profiles["macd_v2_ablation_soft_long_threshold_080"]["config_overrides"]["fund_flow"][
        "macd_mtf_strategy_v2"
    ]
    profile_079 = profiles["macd_v2_ablation_soft_long_threshold_079"]["config_overrides"]["fund_flow"][
        "macd_mtf_strategy_v2"
    ]

    assert profile_080["entry_thresholds"]["soft_long_min_signal_score"] == 0.80
    assert profile_080["short_quality_filter"]["enabled"] is False
    assert profile_079["entry_thresholds"]["soft_long_min_signal_score"] == 0.79
    assert profile_079["short_quality_filter"]["enabled"] is False


def test_live_runtime_config_uses_rsi_rhythm_defaults() -> None:
    runtime_cfg = _load_live_runtime_config()
    v2_cfg = runtime_cfg["fund_flow"]["macd_mtf_strategy_v2"]

    assert v2_cfg["scoring_weights"]["weight_4h_direction"] == 0.40
    assert v2_cfg["scoring_weights"]["weight_1h_direction"] == 0.15
    assert v2_cfg["scoring_weights"]["weight_rsi_rhythm"] == 0.30
    assert v2_cfg["scoring_weights"]["weight_vwap"] == 0.05
    assert v2_cfg["scoring_weights"]["weight_15m_entry"] == 0.0
    assert v2_cfg["entry_thresholds"]["min_signal_score"] == 0.68
    assert v2_cfg["entry_thresholds"]["red_bar_growing"] == 0.68
    assert v2_cfg["entry_thresholds"]["green_bar_growing"] == 0.69
    assert v2_cfg["entry_thresholds"]["flip_bearish"] == 0.66
    assert v2_cfg["entry_thresholds"]["flip_bullish"] == 0.64
    assert v2_cfg["entry_filters"]["min_vwap_score_for_entry"] == 0.0
    assert v2_cfg["entry_filters"]["enable_flip_bullish_strict_filter"] is False
    assert v2_cfg["entry_filters"]["enable_flip_bullish_cvd_context_filter"] is False
    assert v2_cfg["entry_filters"]["disable_flip_bullish_entries"] is True
    assert v2_cfg["entry_filters"]["priority_exec_expire_seconds"] == 25
    assert v2_cfg["entry_filters"]["priority_exec_vip_expire_seconds"] == 45
    assert v2_cfg["position_management"]["enable_red_bar_growing_probe_overlay"] is False
    assert v2_cfg["position_management"]["enable_green_bar_growing_probe_overlay"] is True
    assert v2_cfg["position_management"]["green_bar_growing_probe_position_penalty"] == 0.10
    assert v2_cfg["position_management"]["green_bar_growing_probe_max_leverage"] == 2
    assert runtime_cfg["fund_flow"]["execution_degradation"]["open_market_fallback_enabled"] is True
    assert runtime_cfg["fund_flow"]["execution_degradation"]["open_ioc_retry_times"] == 4
    assert runtime_cfg["fund_flow"]["execution_degradation"]["open_ioc_dynamic_step_enabled"] is True
    assert runtime_cfg["fund_flow"]["execution_degradation"]["open_ioc_max_total_slippage_bps"] == 60
    assert runtime_cfg["fund_flow"]["execution_degradation"]["open_market_fallback_max_slippage_bps"] == 8
    assert runtime_cfg["fund_flow"]["execution_degradation"]["force_market_fallback_on_ioc_remainder"] is False
    assert runtime_cfg["fund_flow"]["max_active_symbols"] == 3
    assert runtime_cfg["fund_flow"]["competition_ranking"]["enabled"] is False
    assert runtime_cfg["fund_flow"]["pretrade_risk_gate"]["enabled"] is False
    assert runtime_cfg["fund_flow"]["pretrade_risk_gate"]["force_exit_on_gate"] is False
    assert runtime_cfg["fund_flow"]["pretrade_risk_gate"]["phase1_entry_only"] is True


def test_disable_short_filter_profile_includes_flip_bullish_relief_and_green_overlay() -> None:
    runtime_cfg = _load_live_runtime_config()

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_disable_short_filter",
    )

    assert active_profile == "macd_v2_disable_short_filter"
    v2_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]
    assert v2_cfg["entry_filters"]["enable_flip_bullish_strict_filter"] is False
    assert v2_cfg["entry_filters"]["enable_flip_bullish_cvd_context_filter"] is False
    assert v2_cfg["position_management"]["enable_green_bar_growing_probe_overlay"] is True
    assert v2_cfg["position_management"]["green_bar_growing_probe_position_penalty"] == 0.10
    assert v2_cfg["position_management"]["green_bar_growing_probe_max_leverage"] == 2


def test_build_strategy_config_keeps_rsi_rhythm_enabled_when_legacy_15m_flags_exist() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "scoring_weights": {
                    "weight_1h_direction": 0.15,
                    "weight_4h_direction": 0.40,
                    "weight_4h_enhancement": 0.10,
                    "weight_vwap": 0.10,
                    "weight_15m_entry": 0.0,
                    "weight_volume": 0.10,
                    "weight_rsi_rhythm": 0.25,
                },
                "entry_thresholds": {
                    "default": 0.85,
                    "min_signal_score": 0.85,
                },
                "entry_filters": {
                    "enable_soft_15m_confirmation_when_4h_primary": False,
                    "min_vwap_score_for_entry": 0.10,
                },
                "rsi_config": {
                    "enable_entry_refinement": False,
                    "rhythm": {
                        "enabled": True,
                        "conflict_penalty_mult": 0.85,
                    },
                },
            }
        }
    }

    strategy_config = build_strategy_config(runtime_cfg)

    assert strategy_config.weight_rsi_rhythm == 0.25
    assert strategy_config.weight_15m_entry == 0.0
    assert strategy_config.enable_rsi_rhythm_scoring is True
    assert strategy_config.rsi_conflict_penalty_mult == 0.85


def test_build_strategy_config_reads_precise_throughput_defaults() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "enable_priority_execution": True,
                    "priority_exec_min_score": 0.90,
                    "priority_exec_expire_seconds": 15,
                    "enable_vwap_flip_exemption": True,
                    "enable_neutral_upgrade": True,
                    "neutral_upgrade_min_rsi_score": 0.30,
                    "neutral_upgrade_penalty_mult": 0.90,
                    "enable_priority_allocation": True,
                    "priority_allocation_overdraft_pct": 0.08,
                },
                "rsi_config": {
                    "rhythm": {
                        "probe_exposure_mult": 0.20,
                        "probe_portion_scale": 0.25,
                        "probe_forced_leverage": 2,
                    }
                },
                "position_management": {
                    "enable_red_bar_growing_probe_overlay": True,
                    "red_bar_growing_probe_position_penalty": 0.50,
                    "red_bar_growing_probe_max_leverage": 2,
                    "enable_green_bar_growing_probe_overlay": True,
                    "green_bar_growing_probe_position_penalty": 0.40,
                    "green_bar_growing_probe_max_leverage": 2,
                },
            }
        }
    }

    strategy_config = build_strategy_config(runtime_cfg)

    assert strategy_config.enable_priority_execution is True
    assert strategy_config.priority_exec_min_score == pytest.approx(0.90, rel=1e-6)
    assert strategy_config.priority_exec_expire_seconds == 15
    assert strategy_config.enable_vwap_flip_exemption is True
    assert strategy_config.enable_neutral_upgrade is True
    assert strategy_config.neutral_upgrade_min_rsi_score == pytest.approx(0.30, rel=1e-6)
    assert strategy_config.neutral_upgrade_penalty_mult == pytest.approx(0.90, rel=1e-6)
    assert strategy_config.rsi_probe_exposure_mult == pytest.approx(0.20, rel=1e-6)
    assert strategy_config.rsi_probe_portion_scale == pytest.approx(0.25, rel=1e-6)
    assert strategy_config.rsi_probe_forced_leverage == 2
    assert strategy_config.enable_priority_allocation is True
    assert strategy_config.priority_allocation_overdraft_pct == pytest.approx(0.08, rel=1e-6)
    assert strategy_config.enable_red_bar_growing_probe_overlay is True
    assert strategy_config.red_bar_growing_probe_position_penalty == pytest.approx(0.50, rel=1e-6)
    assert strategy_config.red_bar_growing_probe_max_leverage == 2
    assert strategy_config.enable_green_bar_growing_probe_overlay is True
    assert strategy_config.green_bar_growing_probe_position_penalty == pytest.approx(0.40, rel=1e-6)
    assert strategy_config.green_bar_growing_probe_max_leverage == 2


def test_build_strategy_config_reads_vip_and_red_bar_overlay_defaults() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "priority_exec_vip_min_score": 0.92,
                    "priority_exec_vip_expire_seconds": 30,
                    "priority_exec_vip_allow_retry": True,
                },
                "position_management": {
                    "enable_red_bar_growing_probe_overlay": True,
                    "red_bar_growing_probe_position_penalty": 0.50,
                    "red_bar_growing_probe_max_leverage": 2,
                    "enable_green_bar_growing_probe_overlay": True,
                    "green_bar_growing_probe_position_penalty": 0.40,
                    "green_bar_growing_probe_max_leverage": 2,
                },
                "exit_management": {
                    "enable_priority_signal_shrink_exit": True,
                    "priority_signal_shrink_exit_required_bars": 3,
                    "priority_signal_shrink_exit_required_pct": 0.40,
                },
            }
        }
    }

    strategy_config = build_strategy_config(runtime_cfg)

    assert strategy_config.priority_exec_vip_min_score == pytest.approx(0.92, rel=1e-6)
    assert strategy_config.priority_exec_vip_expire_seconds == 30
    assert strategy_config.priority_exec_vip_allow_retry is True
    assert strategy_config.enable_red_bar_growing_probe_overlay is True
    assert strategy_config.red_bar_growing_probe_position_penalty == pytest.approx(0.50, rel=1e-6)
    assert strategy_config.red_bar_growing_probe_max_leverage == 2
    assert strategy_config.enable_green_bar_growing_probe_overlay is True
    assert strategy_config.green_bar_growing_probe_position_penalty == pytest.approx(0.40, rel=1e-6)
    assert strategy_config.green_bar_growing_probe_max_leverage == 2
    assert strategy_config.enable_priority_signal_shrink_exit is True
    assert strategy_config.priority_signal_shrink_exit_required_bars == 3
    assert strategy_config.priority_signal_shrink_exit_required_pct == pytest.approx(0.40, rel=1e-6)


def test_build_strategy_config_reads_flip_bullish_sniper_settings() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "flip_bullish_sniper": {
                        "enabled": True,
                        "require_momentum_reset": True,
                        "momentum_reset_max_bars_ago": 12,
                        "require_spring_confirmation": True,
                        "spring_min_rsi_low": 35,
                        "spring_require_price_break": True,
                        "require_trend_alignment": True,
                        "violation_penalty": "soft_penalty",
                        "perfect_score_bonus": 0.08,
                    },
                    "flip_bullish_cooling": {
                        "enabled": True,
                        "reject_if_1h_rsi_above": 75,
                        "reject_if_15m_no_spring_and_rsi_high": True,
                        "reject_if_15m_rsi_above": 65,
                    },
                }
            }
        }
    }

    strategy_config = build_strategy_config(runtime_cfg)

    assert strategy_config.enable_flip_bullish_sniper is True
    assert strategy_config.flip_bullish_momentum_reset_max_bars_ago == 12
    assert strategy_config.flip_bullish_spring_min_rsi_low == pytest.approx(35.0, rel=1e-6)
    assert strategy_config.flip_bullish_sniper_perfect_score_bonus == pytest.approx(0.08, rel=1e-6)
    assert strategy_config.enable_flip_bullish_cooling is True
    assert strategy_config.flip_bullish_cooling_reject_if_1h_rsi_above == pytest.approx(75.0, rel=1e-6)
    assert strategy_config.flip_bullish_cooling_reject_if_15m_no_spring_and_rsi_high is True
    assert strategy_config.flip_bullish_cooling_reject_if_15m_rsi_above == pytest.approx(65.0, rel=1e-6)


def test_build_strategy_config_reads_volume_vwap_combo_hotfix_settings() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "volume_vwap_both_low_min_score_vol": 0.0,
                    "volume_vwap_both_low_min_vwap_score": 0.0,
                    "disable_red_bar_shrinking_long_dual_support_entries": False,
                    "disable_green_bar_shrinking_short_dual_pressure_entries": False,
                    "flip_bullish_cooling": {
                        "enabled": True,
                        "reject_if_1h_rsi_above": 75.0,
                        "soft_rsi_above": 72.0,
                        "soft_discount": 0.90,
                        "hard_rsi_buffer": 4.0,
                        "reject_if_15m_no_spring_and_rsi_high": False,
                        "reject_if_15m_rsi_above": 65.0,
                    },
                }
            }
        }
    }

    strategy_config = build_strategy_config(runtime_cfg)

    assert strategy_config.volume_vwap_both_low_min_score_vol == pytest.approx(0.0, rel=1e-6)
    assert strategy_config.volume_vwap_both_low_min_vwap_score == pytest.approx(0.0, rel=1e-6)
    assert strategy_config.disable_red_bar_shrinking_long_dual_support_entries is False
    assert strategy_config.disable_green_bar_shrinking_short_dual_pressure_entries is False
    assert strategy_config.flip_bullish_cooling_hard_rsi_buffer == pytest.approx(4.0, rel=1e-6)
    assert strategy_config.flip_bullish_cooling_reject_if_15m_no_spring_and_rsi_high is False


def test_disable_short_filter_profile_relaxes_backtest_thresholds() -> None:
    runtime_cfg = _load_live_runtime_config()

    merged_cfg, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_disable_short_filter",
    )
    strategy_config = build_strategy_config(merged_cfg)

    assert active_profile == "macd_v2_disable_short_filter"
    assert merged_cfg["fund_flow"]["default_target_portion"] == pytest.approx(0.35, rel=1e-6)
    assert merged_cfg["fund_flow"]["max_symbol_position_portion"] == pytest.approx(0.35, rel=1e-6)
    assert strategy_config.min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert strategy_config.red_bar_growing_min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert strategy_config.green_bar_growing_min_signal_score == pytest.approx(0.69, rel=1e-6)
    assert strategy_config.flip_bearish_min_signal_score == pytest.approx(0.66, rel=1e-6)
    assert strategy_config.flip_bullish_min_signal_score == pytest.approx(0.64, rel=1e-6)
    assert strategy_config.preflip_trial_min_signal_score == pytest.approx(0.66, rel=1e-6)
    assert strategy_config.trial_short_below_structure_promotion_min_signal_score == pytest.approx(0.68, rel=1e-6)


def test_trading_symbols_respect_symbol_blacklist() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT", "QNTUSDT", "ethusdt", "BTCUSDT"]},
        "fund_flow": {"symbol_blacklist": ["qntusdt", "XMRUSDT"]},
    }

    assert ConfigLoader.get_symbol_blacklist(runtime_cfg) == ["QNTUSDT", "XMRUSDT"]
    assert ConfigLoader.get_trading_symbols(runtime_cfg) == ["BTCUSDT", "ETHUSDT"]


def test_apply_backtest_profile_filters_blacklisted_symbols() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["BTCUSDT"]},
        "fund_flow": {
            "symbol_blacklist": ["QNTUSDT"],
            "allowed_entry_hours_utc": [],
            "backtest": {
                "profiles": {
                    "focus": {
                        "symbols": ["QNTUSDT", "SOLUSDT"],
                    }
                }
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg, profile_name="focus")

    assert active_profile == "focus"
    assert merged["trading"]["symbols"] == ["SOLUSDT"]


def test_build_backtest_copy_persists_and_applies_symbol_blacklist() -> None:
    base_cfg = {
        "trading": {"symbols": ["BTCUSDT", "QNTUSDT", "ETHUSDT"]},
        "fund_flow": {
            "backtest": {
                "profiles": {
                    "top50": {"symbols": ["BTCUSDT", "QNTUSDT", "SOLUSDT"]},
                }
            }
        },
    }

    copied = build_backtest_copy(
        base_cfg,
        source_path="config/trading_config_fund_flow.json",
        default_profile="top50",
        symbol_blacklist=["QNTUSDT", "UNIUSDT"],
    )

    assert copied["fund_flow"]["symbol_blacklist"] == ["QNTUSDT", "UNIUSDT"]
    assert copied["trading"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert copied["fund_flow"]["backtest"]["profiles"]["top50"]["symbols"] == ["BTCUSDT", "SOLUSDT"]


def test_apply_backtest_profile_enables_preflip_trial_and_shrink_exit() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "primary_direction_timeframe": "1h",
                    "enable_4h_preflip_trial_entries": False,
                },
                "stop_loss_config": {
                    "enable_4h_shrink_exit": False,
                },
                "short_quality_filter": {"enabled": True},
            },
            "backtest": {
                "profiles": {
                    "macd_v2_4h_preflip_trial_exit": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "entry_filters": {
                                        "primary_direction_timeframe": "4h",
                                        "enable_4h_preflip_trial_entries": True,
                                        "preflip_trial_entry_scale": 0.35,
                                    },
                                    "stop_loss_config": {
                                        "enable_4h_shrink_exit": True,
                                        "exit_4h_shrink_bars": 2,
                                    },
                                    "short_quality_filter": {"enabled": False},
                                }
                            }
                        }
                    }
                }
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg, profile_name="macd_v2_4h_preflip_trial_exit")

    assert active_profile == "macd_v2_4h_preflip_trial_exit"
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["primary_direction_timeframe"] == "4h"
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["enable_4h_preflip_trial_entries"] is True
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["preflip_trial_entry_scale"] == 0.35
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["stop_loss_config"]["enable_4h_shrink_exit"] is True
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["stop_loss_config"]["exit_4h_shrink_bars"] == 2
    assert merged["fund_flow"]["macd_mtf_strategy_v2"]["short_quality_filter"]["enabled"] is False


def test_apply_backtest_profile_enables_targeted_loss_pocket_filters() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "enable_green_bar_growing_short_adx_1h_range_filter": False,
                    "green_bar_growing_short_min_adx_1h": 0.0,
                    "green_bar_growing_short_max_adx_1h": 0.0,
                    "enable_flip_bullish_cvd_context_filter": False,
                    "flip_bullish_max_cvd_upper_wick_ratio": 0.0,
                    "flip_bullish_min_cvd_1h_delta_ratio": 0.0,
                }
            },
            "backtest": {
                "profiles": {
                    "macd_v2_4h_preflip_trial_exit_filter_a": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "entry_filters": {
                                        "enable_green_bar_growing_short_adx_1h_range_filter": True,
                                        "green_bar_growing_short_min_adx_1h": 25.0,
                                        "green_bar_growing_short_max_adx_1h": 30.0,
                                        "enable_flip_bullish_cvd_context_filter": True,
                                        "flip_bullish_max_cvd_upper_wick_ratio": 0.20,
                                        "flip_bullish_min_cvd_1h_delta_ratio": 0.03,
                                    }
                                }
                            }
                        }
                    }
                }
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg, profile_name="macd_v2_4h_preflip_trial_exit_filter_a")

    filters = merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]
    assert active_profile == "macd_v2_4h_preflip_trial_exit_filter_a"
    assert filters["enable_green_bar_growing_short_adx_1h_range_filter"] is True
    assert filters["green_bar_growing_short_min_adx_1h"] == 25.0
    assert filters["green_bar_growing_short_max_adx_1h"] == 30.0
    assert filters["enable_flip_bullish_cvd_context_filter"] is True
    assert filters["flip_bullish_max_cvd_upper_wick_ratio"] == 0.20
    assert filters["flip_bullish_min_cvd_1h_delta_ratio"] == 0.03


def test_apply_backtest_profile_enables_v9_controls() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "risk": {
            "max_consecutive_losses": 2,
            "consecutive_loss_cooldown_seconds": 1800,
        },
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "stop_loss_config": {
                    "enable_4h_shrink_exit": True,
                    "exit_4h_require_profit": True,
                }
            },
            "backtest": {
                "profiles": {
                    "macd_v2_4h_preflip_trial_exit_filter_a_v9": {
                        "config_overrides": {
                            "risk": {
                                "max_consecutive_losses": 2,
                                "consecutive_loss_cooldown_seconds": 5400,
                            },
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "stop_loss_config": {
                                        "enable_4h_shrink_exit": True,
                                        "exit_4h_min_shrink_pct": 0.30,
                                        "exit_4h_require_profit": False,
                                        "exit_4h_weak_loss_threshold": -0.001,
                                    },
                                    "session_risk_control": {
                                        "enabled": True,
                                        "high_risk_sessions": [
                                            {"utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65}
                                        ],
                                        "apply_to_states": ["short_dual_pressure", "flip_bullish"],
                                    },
                                }
                            },
                        }
                    }
                }
            },
        },
    }

    merged, active_profile = apply_backtest_profile(runtime_cfg, profile_name="macd_v2_4h_preflip_trial_exit_filter_a_v9")

    assert active_profile == "macd_v2_4h_preflip_trial_exit_filter_a_v9"
    assert merged["risk"]["consecutive_loss_cooldown_seconds"] == 5400
    stop_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["stop_loss_config"]
    assert stop_cfg["exit_4h_min_shrink_pct"] == 0.30
    assert stop_cfg["exit_4h_require_profit"] is False
    assert stop_cfg["exit_4h_weak_loss_threshold"] == -0.001
    session_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["session_risk_control"]
    assert session_cfg["enabled"] is True
    assert session_cfg["high_risk_sessions"][0]["position_scale"] == 0.65
    assert session_cfg["apply_to_states"] == ["short_dual_pressure", "flip_bullish"]


def test_apply_backtest_profile_enables_v9_1_session_only_controls() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "risk": {
            "max_consecutive_losses": 2,
            "consecutive_loss_cooldown_seconds": 1800,
        },
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "stop_loss_config": {
                    "enable_4h_shrink_exit": True,
                    "exit_4h_min_shrink_pct": 0.20,
                    "exit_4h_require_profit": True,
                }
            },
            "backtest": {
                "profiles": {
                    "macd_v2_4h_preflip_trial_exit_filter_a_v9_1_session_only": {
                        "config_overrides": {
                            "risk": {
                                "max_consecutive_losses": 2,
                                "consecutive_loss_cooldown_seconds": 1800,
                            },
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "stop_loss_config": {
                                        "enable_4h_shrink_exit": True,
                                        "exit_4h_min_shrink_pct": 0.20,
                                        "exit_4h_require_profit": True,
                                    },
                                    "session_risk_control": {
                                        "enabled": True,
                                        "high_risk_sessions": [
                                            {"utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65}
                                        ],
                                        "apply_to_states": ["short_dual_pressure", "flip_bullish"],
                                    },
                                }
                            },
                        }
                    }
                }
            },
        },
    }

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_4h_preflip_trial_exit_filter_a_v9_1_session_only",
    )

    assert active_profile == "macd_v2_4h_preflip_trial_exit_filter_a_v9_1_session_only"
    assert merged["risk"]["consecutive_loss_cooldown_seconds"] == 1800
    stop_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["stop_loss_config"]
    assert stop_cfg["exit_4h_min_shrink_pct"] == 0.20
    assert stop_cfg["exit_4h_require_profit"] is True
    assert "exit_4h_weak_loss_threshold" not in stop_cfg
    session_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["session_risk_control"]
    assert session_cfg["enabled"] is True
    assert session_cfg["high_risk_sessions"][0]["position_scale"] == 0.65


def test_apply_backtest_profile_enables_v9_2_short_pressure_focus() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "fund_flow": {
            "backtest": {
                "profiles": {
                    "macd_v2_4h_preflip_trial_exit_filter_a_v9_2_short_pressure_focus": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "session_risk_control": {
                                        "enabled": True,
                                        "high_risk_sessions": [
                                            {"utc_start": "03:00", "utc_end": "05:30", "position_scale": 0.70},
                                            {"utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65},
                                        ],
                                        "apply_to_states": ["short_dual_pressure"],
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_4h_preflip_trial_exit_filter_a_v9_2_short_pressure_focus",
    )

    assert active_profile == "macd_v2_4h_preflip_trial_exit_filter_a_v9_2_short_pressure_focus"
    session_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["session_risk_control"]
    assert session_cfg["enabled"] is True
    assert len(session_cfg["high_risk_sessions"]) == 2
    assert session_cfg["high_risk_sessions"][0]["position_scale"] == 0.70
    assert session_cfg["apply_to_states"] == ["short_dual_pressure"]


def test_apply_backtest_profile_enables_v11_watchlist_throttle_and_preflip_symmetry() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT", "LINKUSDT"]},
        "fund_flow": {
            "backtest": {
                "profiles": {
                    "macd_v2_v11_watchlist_throttle_preflip_symmetric": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "entry_filters": {
                                        "preflip_trial_min_shrink_pct_long": 0.60,
                                        "preflip_trial_min_shrink_pct_short": 0.40,
                                    },
                                    "symbol_risk_tiers": {
                                        "watchlist_symbols": [
                                            "LINKUSDT",
                                            "ONDOUSDT",
                                            "LTCUSDT",
                                            "MORPHOUSDT",
                                            "TRUMPUSDT",
                                        ],
                                        "watchlist_max_position_portion": 0.40,
                                        "watchlist_max_leverage": 2,
                                        "watchlist_apply_session_scale_double": True,
                                        "watchlist_session_scale_multiplier": 0.80,
                                    },
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_v11_watchlist_throttle_preflip_symmetric",
    )

    assert active_profile == "macd_v2_v11_watchlist_throttle_preflip_symmetric"
    filter_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]
    assert filter_cfg["preflip_trial_min_shrink_pct_long"] == 0.60
    assert filter_cfg["preflip_trial_min_shrink_pct_short"] == 0.40
    symbol_risk_cfg = merged["fund_flow"]["macd_mtf_strategy_v2"]["symbol_risk_tiers"]
    assert symbol_risk_cfg["watchlist_symbols"][0] == "LINKUSDT"
    assert symbol_risk_cfg["watchlist_max_position_portion"] == 0.40
    assert symbol_risk_cfg["watchlist_max_leverage"] == 2
    assert symbol_risk_cfg["watchlist_apply_session_scale_double"] is True


def test_apply_backtest_profile_enables_v11_vwap_tiers_and_standalone_b1() -> None:
    runtime_cfg = {
        "trading": {"symbols": ["SOLUSDT"]},
        "fund_flow": {
            "backtest": {
                "profiles": {
                    "macd_v2_v11_vwap_score_tiers": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "vwap_score_position_tiers": {
                                        "apply_to_states": ["short_dual_pressure", "flip_bullish"],
                                        "tiers": [
                                            {"min": 0.12, "max": 0.20, "position_mult": 0.80},
                                            {"min": 0.20, "max": 0.30, "position_mult": 1.00},
                                            {"min": 0.30, "max": 1.00, "position_mult": 1.15},
                                        ],
                                    }
                                }
                            }
                        }
                    },
                    "macd_v2_v11_preflip_symmetric_only": {
                        "config_overrides": {
                            "fund_flow": {
                                "macd_mtf_strategy_v2": {
                                    "entry_filters": {
                                        "preflip_trial_min_shrink_pct_long": 0.60,
                                        "preflip_trial_min_shrink_pct_short": 0.40,
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
    }

    merged_c1, active_c1 = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_v11_vwap_score_tiers",
    )
    assert active_c1 == "macd_v2_v11_vwap_score_tiers"
    tier_cfg = merged_c1["fund_flow"]["macd_mtf_strategy_v2"]["vwap_score_position_tiers"]
    assert tier_cfg["apply_to_states"] == ["short_dual_pressure", "flip_bullish"]
    assert tier_cfg["tiers"][0]["position_mult"] == 0.80

    merged_b1, active_b1 = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_v11_preflip_symmetric_only",
    )
    assert active_b1 == "macd_v2_v11_preflip_symmetric_only"
    filter_cfg = merged_b1["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]
    assert filter_cfg["preflip_trial_min_shrink_pct_long"] == 0.60
    assert filter_cfg["preflip_trial_min_shrink_pct_short"] == 0.40


def test_backtest_shrink_exit_allows_weak_loss_threshold() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0)
    strategy_config = MACDStrategyV2Config(
        enable_4h_shrink_exit=True,
        exit_4h_require_profit=False,
        exit_4h_weak_loss_threshold=-0.001,
    )
    engine = BacktestEngine(config, strategy_config, runtime_config={})
    entry_time = pd.Timestamp("2026-03-21 14:45:00")
    engine.positions["SOLUSDT"] = {
        "side": "long",
        "entry_price": 100.0,
        "entry_notional": 2000.0,
        "position_value": 1000.0,
        "margin": 1000.0,
        "initial_margin": 1000.0,
        "remaining_fraction": 1.0,
        "leverage": 2,
        "stop_price": 95.0,
        "take_profit": None,
        "take_profit_levels": [],
        "entry_time": entry_time,
        "signal_score": 0.92,
        "signal_type_1h": "flip_bullish",
        "is_trial_entry": False,
        "entry_scale": 1.0,
        "session_position_scale": 0.65,
        "vwap_score": 0.20,
        "vwap_state": "short_dual_pressure",
        "vwap_location_score": 0.0,
        "ema_multiplier": 1.0,
        "ema_status": "normal",
        "realized_pnl_accum": 0.0,
    }
    analysis = {
        "signal": MACDSignalV2(
            direction="neutral",
            signal_score=0.0,
            details={"shrink_exit_ready": True, "shrink_exit_direction": "long"},
        ),
        "row_15m": pd.Series({"high": 100.0, "low": 99.9}),
        "price": 99.95,
        "time": pd.Timestamp("2026-03-21 15:00:00"),
    }

    closed = engine.check_stops("SOLUSDT", analysis)

    assert closed is True
    assert engine.trades[-1]["reason"] == "4h_shrink_exit"


def test_backtest_entry_cooldown_triggers_after_two_losses() -> None:
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        max_consecutive_losses=2,
        consecutive_loss_cooldown_seconds=5400,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config={})
    first_close = pd.Timestamp("2026-03-21 15:00:00")
    second_close = pd.Timestamp("2026-03-21 15:30:00")

    engine._update_loss_streak_after_trade_close(first_close, -10.0)
    assert engine._is_entry_cooldown_active(first_close) is False

    engine._update_loss_streak_after_trade_close(second_close, -5.0)
    assert engine._is_entry_cooldown_active(pd.Timestamp("2026-03-21 16:00:00")) is True
    assert engine._is_entry_cooldown_active(pd.Timestamp("2026-03-21 17:01:00")) is False


def test_backtest_candidate_audit_tracks_filter_reasons() -> None:
    config = BacktestConfig(symbols=["SOLUSDT", "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT"])
    strategy_config = MACDStrategyV2Config(
        min_signal_score=0.75,
        red_bar_growing_min_signal_score=0.75,
    )
    engine = BacktestEngine(config, strategy_config, runtime_config={})
    engine.positions["SOLUSDT"] = {"side": "long"}
    engine.pending_orders["BTCUSDT"] = {"margin": 100.0}

    analyses = {
        "SOLUSDT": {"signal": MACDSignalV2(direction="long", signal_score=0.90, signal_type_1h="red_bar_growing")},
        "BTCUSDT": {"signal": MACDSignalV2(direction="long", signal_score=0.88, signal_type_1h="red_bar_growing")},
        "ETHUSDT": {"signal": MACDSignalV2(direction="neutral", signal_score=0.0, signal_type_1h="red_bar_growing")},
        "XRPUSDT": {"signal": MACDSignalV2(direction="long", signal_score=0.70, signal_type_1h="red_bar_growing")},
        "BNBUSDT": {"signal": MACDSignalV2(direction="long", signal_score=0.80, signal_type_1h="red_bar_growing")},
    }

    candidates = engine._build_entry_candidates(analyses, closed_symbols_this_bar=set())

    assert [symbol for symbol, _analysis in candidates] == ["BNBUSDT"]
    assert engine.execution_audit["blocked_existing_position"] == 1
    assert engine.execution_audit["blocked_pending_order"] == 1
    assert engine.execution_audit["blocked_neutral_signal"] == 1
    assert engine.execution_audit["blocked_threshold"] == 1
    assert engine.execution_audit["candidate_entries"] == 1


def test_backtest_candidate_sort_key_prefers_sovereign_competition_score() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT", "BTCUSDT"]),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    regular = {
        "signal": MACDSignalV2(
            direction="long",
            signal_score=0.90,
            signal_type_1h="red_bar_growing",
            vwap_score=0.03,
            ema_multiplier=1.0,
            details={"competition_score": 0.90},
        )
    }
    sovereign = {
        "signal": MACDSignalV2(
            direction="long",
            signal_score=0.88,
            signal_type_1h="flip_bullish",
            vwap_score=0.01,
            ema_multiplier=1.0,
            details={
                "competition_score": 1.012,
                "rsi_launch_sovereign_active": True,
            },
        )
    }

    candidates = [("SOLUSDT", regular), ("BTCUSDT", sovereign)]
    candidates.sort(key=engine._candidate_sort_key, reverse=True)

    assert [symbol for symbol, _analysis in candidates] == ["BTCUSDT", "SOLUSDT"]


def test_backtest_capacity_examples_capture_sovereign_competition_metadata() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"]),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    sovereign_signal = MACDSignalV2(
        direction="long",
        signal_score=0.88,
        signal_type_1h="flip_bullish",
        entry_type_15m="flip_bullish",
        vwap_score=0.02,
        details={
            "competition_score": 1.012,
            "rsi_launch_sovereign_active": True,
        },
    )

    engine._record_capacity_block(
        current_ts=pd.Timestamp("2026-03-21 15:00:00"),
        blocked=[("SOLUSDT", {"signal": sovereign_signal})],
        positions_count=2,
        pending_count=1,
        precheck=False,
    )

    example = engine.execution_audit["competition_drop_examples"][0]
    assert example["competition_score"] == pytest.approx(1.012, rel=1e-6)
    assert example["rsi_launch_sovereign_active"] is True


def test_backtest_pending_cancel_audit_tracks_reason_breakdown() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0)
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config={})
    engine.capital = 9900.0
    engine.pending_orders["SOLUSDT"] = {"margin": 100.0}

    engine._cancel_pending_order("SOLUSDT", reason="ioc_unfilled")

    assert engine.capital == pytest.approx(10000.0, rel=1e-6)
    assert engine.execution_audit["orders_canceled"] == 1
    assert engine.execution_audit["pending_cancel_reasons"]["ioc_unfilled"] == 1


def test_backtest_execute_trade_uses_signal_level_priority_execution_metadata() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0, entry_time_in_force="IOC")
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config={})
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.92,
        signal_type_1h="flip_bullish",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "GTC",
            "entry_expire_seconds": 15,
            "entry_price_mode": "elastic_limit",
            "priority_execution_applied": True,
        },
    )
    analysis = {
        "signal": signal,
        "price": 100.0,
        "time": pd.Timestamp("2026-04-25 14:00:00"),
        "row_1h": pd.Series({"atr": 1.0}),
        "cvd_veto_context": {},
        "cvd_context": {},
    }

    accepted = engine.execute_trade("SOLUSDT", analysis, data={})

    assert accepted is True
    order = engine.pending_orders["SOLUSDT"]
    assert order["time_in_force"] == "GTC"
    assert order["entry_expire_seconds"] == 15
    assert order["entry_price_mode"] == "elastic_limit"
    assert order["priority_execution_applied"] is True


def test_backtest_execute_trade_persists_standard_ioc_market_fallback_metadata() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0, entry_time_in_force="IOC", entry_slippage=0.0)
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config={})
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.70,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "IOC",
            "entry_price_mode": "ioc_limit",
            "entry_market_fallback_enabled": True,
            "entry_market_fallback_timeout_ms": 2000,
            "entry_market_fallback_max_slippage_bps": 5,
            "entry_execution_policy": "ioc_market_fallback",
        },
    )
    analysis = {
        "signal": signal,
        "price": 100.0,
        "time": pd.Timestamp("2026-04-25 14:00:00"),
        "row_1h": pd.Series({"atr": 1.0}),
        "cvd_veto_context": {},
        "cvd_context": {},
    }

    accepted = engine.execute_trade("SOLUSDT", analysis, data={})

    assert accepted is True
    order = engine.pending_orders["SOLUSDT"]
    assert order["time_in_force"] == "IOC"
    assert order["entry_market_fallback_enabled"] is True
    assert order["entry_market_fallback_timeout_ms"] == 2000
    assert order["entry_market_fallback_max_slippage_bps"] == 5
    assert order["entry_execution_policy"] == "ioc_market_fallback"


def test_backtest_standard_ioc_market_fallback_fills_within_slippage_band() -> None:
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        entry_time_in_force="IOC",
        entry_slippage=0.0,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config={})
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.90,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "IOC",
            "entry_price_mode": "ioc_limit",
            "entry_market_fallback_enabled": True,
            "entry_market_fallback_timeout_ms": 2000,
            "entry_market_fallback_max_slippage_bps": 5,
            "entry_execution_policy": "ioc_market_fallback",
        },
    )
    entry_analysis = {
        "signal": signal,
        "price": 100.0,
        "time": pd.Timestamp("2026-04-25 14:00:00"),
        "row_1h": pd.Series({"atr": 1.0}),
        "cvd_veto_context": {},
        "cvd_context": {},
    }

    assert engine.execute_trade("SOLUSDT", entry_analysis, data={}) is True

    filled = engine.process_pending_orders(
        {
            "SOLUSDT": {
                "signal": signal,
                "price": 100.0,
                "time": pd.Timestamp("2026-04-25 14:15:00"),
                "row_15m": pd.Series({"open": 100.20, "high": 100.30, "low": 100.18, "close": 100.00}),
            }
        }
    )

    assert filled == {"SOLUSDT"}
    assert "SOLUSDT" not in engine.pending_orders
    assert engine.positions["SOLUSDT"]["entry_price"] == pytest.approx(100.05, rel=1e-6)
    assert engine.execution_audit["market_fallback_attempted"] == 1
    assert engine.execution_audit["market_fallback_filled"] == 1


def test_backtest_force_market_fallback_defaults_from_execution_degradation() -> None:
    runtime_config = {
        "fund_flow": {
            "execution_degradation": {
                "open_market_fallback_enabled": True,
                "open_market_fallback_max_slippage_bps": 8,
                "force_market_fallback_on_ioc_remainder": True,
            }
        }
    }
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        entry_time_in_force="IOC",
        entry_slippage=0.0,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config=runtime_config)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.86,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "IOC",
            "entry_price_mode": "ioc_limit",
            "entry_execution_policy": "ioc",
        },
    )
    entry_analysis = {
        "signal": signal,
        "price": 100.0,
        "time": pd.Timestamp("2026-04-25 14:00:00"),
        "row_1h": pd.Series({"atr": 1.0}),
        "cvd_veto_context": {},
        "cvd_context": {},
    }

    assert engine.execute_trade("SOLUSDT", entry_analysis, data={}) is True
    order = engine.pending_orders["SOLUSDT"]
    assert order["entry_execution_policy"] == "ioc"
    assert order["entry_market_fallback_enabled"] is True
    assert order["entry_market_fallback_max_slippage_bps"] == 8
    assert order["force_market_fallback_on_ioc_remainder"] is True

    filled = engine.process_pending_orders(
        {
            "SOLUSDT": {
                "signal": signal,
                "price": 100.0,
                "time": pd.Timestamp("2026-04-25 14:15:00"),
                "row_15m": pd.Series({"open": 100.02, "high": 100.08, "low": 100.01, "close": 100.02}),
            }
        }
    )

    assert filled == {"SOLUSDT"}
    assert engine.execution_audit["market_fallback_attempted"] == 1
    assert engine.execution_audit["market_fallback_filled"] == 1


def test_backtest_default_ioc_does_not_enable_forced_market_fallback_when_disabled() -> None:
    runtime_config = {
        "fund_flow": {
            "execution_degradation": {
                "open_market_fallback_enabled": True,
                "open_market_fallback_max_slippage_bps": 8,
                "force_market_fallback_on_ioc_remainder": False,
            }
        }
    }
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        entry_time_in_force="IOC",
        entry_slippage=0.0,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config=runtime_config)
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.86,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "IOC",
            "entry_price_mode": "ioc_limit",
            "entry_execution_policy": "ioc",
        },
    )

    assert engine.execute_trade(
        "SOLUSDT",
        {
            "signal": signal,
            "price": 100.0,
            "time": pd.Timestamp("2026-04-25 14:00:00"),
            "row_1h": pd.Series({"atr": 1.0}),
            "cvd_veto_context": {},
            "cvd_context": {},
        },
        data={},
    ) is True

    order = engine.pending_orders["SOLUSDT"]
    assert order["entry_market_fallback_enabled"] is False
    assert order["entry_market_fallback_max_slippage_bps"] == 0
    assert order["force_market_fallback_on_ioc_remainder"] is False

    filled = engine.process_pending_orders(
        {
            "SOLUSDT": {
                "signal": signal,
                "price": 100.0,
                "time": pd.Timestamp("2026-04-25 14:15:00"),
                "row_15m": pd.Series({"open": 100.02, "high": 100.08, "low": 100.01, "close": 100.02}),
            }
        }
    )

    assert filled == set()
    assert engine.execution_audit["market_fallback_attempted"] == 0
    assert engine.execution_audit["pending_cancel_reasons"] == {"ioc_unfilled": 1}


def test_backtest_force_market_fallback_survives_followup_signal_below_threshold() -> None:
    runtime_config = {
        "fund_flow": {
            "execution_degradation": {
                "open_market_fallback_enabled": True,
                "open_market_fallback_max_slippage_bps": 8,
                "force_market_fallback_on_ioc_remainder": True,
            }
        }
    }
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        entry_time_in_force="IOC",
        entry_slippage=0.0,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config=runtime_config)
    entry_signal = MACDSignalV2(
        direction="long",
        signal_score=0.86,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={"entry_time_in_force": "IOC", "entry_price_mode": "ioc_limit", "entry_execution_policy": "ioc"},
    )

    assert engine.execute_trade(
        "SOLUSDT",
        {
            "signal": entry_signal,
            "price": 100.0,
            "time": pd.Timestamp("2026-04-25 14:00:00"),
            "row_1h": pd.Series({"atr": 1.0}),
            "cvd_veto_context": {},
            "cvd_context": {},
        },
        data={},
    ) is True

    followup_signal = MACDSignalV2(
        direction="long",
        signal_score=0.60,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
    )
    filled = engine.process_pending_orders(
        {
            "SOLUSDT": {
                "signal": followup_signal,
                "price": 100.0,
                "time": pd.Timestamp("2026-04-25 14:15:00"),
                "row_15m": pd.Series({"open": 99.98, "high": 100.08, "low": 99.97, "close": 100.02}),
            }
        }
    )

    assert filled == {"SOLUSDT"}
    assert engine.execution_audit["pending_cancel_reasons"] == {}
    assert engine.execution_audit["market_fallback_attempted"] == 1
    assert engine.positions["SOLUSDT"]["entry_price"] == pytest.approx(100.07001, rel=1e-6)


def test_backtest_force_market_fallback_survives_followup_signal_reversal() -> None:
    runtime_config = {
        "fund_flow": {
            "execution_degradation": {
                "open_market_fallback_enabled": True,
                "open_market_fallback_max_slippage_bps": 8,
                "force_market_fallback_on_ioc_remainder": True,
            }
        }
    }
    config = BacktestConfig(
        symbols=["SOLUSDT"],
        initial_capital=10000.0,
        entry_time_in_force="IOC",
        entry_slippage=0.0,
    )
    engine = BacktestEngine(config, MACDStrategyV2Config(), runtime_config=runtime_config)
    entry_signal = MACDSignalV2(
        direction="long",
        signal_score=0.86,
        signal_type_1h="red_bar_growing",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={"entry_time_in_force": "IOC", "entry_price_mode": "ioc_limit", "entry_execution_policy": "ioc"},
    )

    assert engine.execute_trade(
        "SOLUSDT",
        {
            "signal": entry_signal,
            "price": 100.0,
            "time": pd.Timestamp("2026-04-25 14:00:00"),
            "row_1h": pd.Series({"atr": 1.0}),
            "cvd_veto_context": {},
            "cvd_context": {},
        },
        data={},
    ) is True

    reversed_signal = MACDSignalV2(
        direction="short",
        signal_score=0.86,
        signal_type_1h="flip_bearish",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="short_dual_pressure",
        ema_multiplier=1.0,
        ema_structure_status="normal",
    )
    filled = engine.process_pending_orders(
        {
            "SOLUSDT": {
                "signal": reversed_signal,
                "price": 100.0,
                "time": pd.Timestamp("2026-04-25 14:15:00"),
                "row_15m": pd.Series({"open": 100.02, "high": 100.08, "low": 100.01, "close": 100.02}),
            }
        }
    )

    assert filled == {"SOLUSDT"}
    assert engine.execution_audit["pending_cancel_reasons"] == {}
    assert engine.execution_audit["market_fallback_attempted"] == 1
    assert engine.positions["SOLUSDT"]["entry_price"] == pytest.approx(100.07001, rel=1e-6)


def test_backtest_competition_score_boosts_only_flip_bullish() -> None:
    engine = BacktestEngine(
        BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0),
        MACDStrategyV2Config(),
        runtime_config={},
    )
    bullish = MACDSignalV2(
        direction="long",
        signal_score=0.80,
        signal_type_1h="flip_bullish",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
    )
    bearish = MACDSignalV2(
        direction="short",
        signal_score=0.80,
        signal_type_1h="flip_bearish",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="short_dual_pressure",
        ema_multiplier=1.0,
        ema_structure_status="normal",
    )

    assert engine._resolve_competition_score(bullish) == pytest.approx(0.92, rel=1e-6)
    assert engine._resolve_competition_score(bearish) == pytest.approx(0.80, rel=1e-6)


def test_backtest_competition_score_respects_configured_cluster_bonus_overrides() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0)
    strategy_config = MACDStrategyV2Config()
    runtime_config = {
        "fund_flow": {
            "competition_ranking": {
                "enabled": True,
                "cluster_bonus_map": {
                    "flip_bearish": 0.05,
                    "red_bar_growing": 0.02,
                    "flip_bullish": -0.10,
                }
            }
        }
    }
    engine = BacktestEngine(config, strategy_config, runtime_config=runtime_config)

    bullish = MACDSignalV2(direction="long", signal_score=0.80, signal_type_1h="flip_bullish", details={})
    bearish = MACDSignalV2(direction="short", signal_score=0.80, signal_type_1h="flip_bearish", details={})
    growing = MACDSignalV2(direction="short", signal_score=0.80, signal_type_1h="red_bar_growing", details={})

    assert engine._resolve_competition_score(bullish) == pytest.approx(0.70, rel=1e-6)
    assert engine._resolve_competition_score(bearish) == pytest.approx(0.85, rel=1e-6)
    assert engine._resolve_competition_score(growing) == pytest.approx(0.82, rel=1e-6)


def test_backtest_vip_priority_order_retries_once_with_price_improvement_before_fill() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0, entry_time_in_force="IOC")
    strategy_config = MACDStrategyV2Config(
        enable_priority_execution=True,
        priority_exec_min_score=0.90,
        priority_exec_expire_seconds=15,
        priority_exec_vip_min_score=0.92,
        priority_exec_vip_expire_seconds=25,
        priority_exec_vip_allow_retry=True,
    )
    engine = BacktestEngine(config, strategy_config, runtime_config={})
    signal = MACDSignalV2(
        direction="long",
        signal_score=0.93,
        signal_type_1h="flip_bullish",
        entry_type_15m="rsi_spring",
        vwap_score=0.20,
        vwap_state="long_dual_support",
        ema_multiplier=1.0,
        ema_structure_status="normal",
        details={
            "entry_time_in_force": "GTC",
            "entry_expire_seconds": 25,
            "entry_price_mode": "elastic_limit",
            "priority_execution_applied": True,
            "priority_execution_tier": "vip",
            "entry_retry_enabled": True,
            "entry_retry_max_attempts": 1,
        },
    )
    entry_analysis = {
        "signal": signal,
        "price": 100.0,
        "time": pd.Timestamp("2026-04-25 14:00:00"),
        "row_1h": pd.Series({"atr": 1.0}),
        "cvd_veto_context": {},
        "cvd_context": {},
    }

    accepted = engine.execute_trade("SOLUSDT", entry_analysis, data={})

    assert accepted is True

    first_pass = {
        "SOLUSDT": {
            "signal": signal,
            "price": 101.0,
            "time": pd.Timestamp("2026-04-25 14:15:00"),
            "row_15m": pd.Series({"open": 101.0, "high": 101.4, "low": 100.6, "close": 101.2}),
        }
    }
    filled_first = engine.process_pending_orders(first_pass)

    assert filled_first == set()
    assert "SOLUSDT" in engine.pending_orders
    retried_order = engine.pending_orders["SOLUSDT"]
    assert retried_order["entry_retry_attempts"] == 1
    assert retried_order["limit_price"] > 100.0 * (1.0 + config.entry_slippage)

    second_pass = {
        "SOLUSDT": {
            "signal": signal,
            "price": 100.0,
            "time": pd.Timestamp("2026-04-25 14:30:00"),
            "row_15m": pd.Series({"open": 100.0, "high": 100.4, "low": 99.8, "close": 100.1}),
        }
    }
    filled_second = engine.process_pending_orders(second_pass)

    assert filled_second == {"SOLUSDT"}
    assert "SOLUSDT" not in engine.pending_orders


def test_build_backtest_summary_includes_execution_funnel_audit() -> None:
    config = BacktestConfig(symbols=["SOLUSDT"], initial_capital=10000.0)
    strategy_config = MACDStrategyV2Config()
    engine = BacktestEngine(config, strategy_config, runtime_config={})
    engine.execution_audit["candidate_entries"] = 12
    engine.execution_audit["orders_submitted"] = 5
    engine.execution_audit["orders_filled"] = 4
    engine.execution_audit["capacity_full_precheck_candidates"] = 3
    engine.execution_audit["capacity_competition_dropped"] = 2
    engine.execution_audit["pending_cancel_reasons"]["ioc_unfilled"] = 1

    summary = build_backtest_summary(
        config,
        strategy_config,
        engine,
        available_symbols=["SOLUSDT"],
        missing_symbols=[],
        stats={"signals": 20, "timeline_points": 10},
    )

    audit = summary["execution_funnel"]
    assert audit["candidate_entries"] == 12
    assert audit["orders_submitted"] == 5
    assert audit["orders_filled"] == 4
    assert audit["capacity_full_precheck_candidates"] == 3
    assert audit["capacity_competition_dropped"] == 2
    assert audit["pending_cancel_reasons"]["ioc_unfilled"] == 1
    assert audit["wsr"] == pytest.approx(0.08333333333333333, rel=1e-6)


def test_live_config_contains_vwap_deweight_ablation_profile() -> None:
    runtime_cfg = _load_live_runtime_config()

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_ablation_vwap_deweight",
    )

    assert active_profile == "macd_v2_ablation_vwap_deweight"
    scoring = merged["fund_flow"]["macd_mtf_strategy_v2"]["scoring_weights"]
    filters = merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]
    assert scoring["weight_vwap"] == 0.05
    assert filters["min_vwap_score_for_entry"] == 0.0
    assert filters["stable_bear_continuation_min_vwap_score"] == 0.0
    assert filters["stable_bull_continuation_min_vwap_score"] == 0.0


def test_live_config_contains_restore_1h_weight_ablation_profile() -> None:
    runtime_cfg = _load_live_runtime_config()

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_ablation_restore_1h_weight",
    )

    assert active_profile == "macd_v2_ablation_restore_1h_weight"
    scoring = merged["fund_flow"]["macd_mtf_strategy_v2"]["scoring_weights"]
    assert scoring["weight_1h_direction"] == 0.15
    assert scoring["weight_4h_direction"] == 0.40
    assert scoring["weight_vwap"] == runtime_cfg["fund_flow"]["macd_mtf_strategy_v2"]["scoring_weights"]["weight_vwap"]


def test_live_config_contains_remove_trial_promotion_ablation_profile() -> None:
    runtime_cfg = _load_live_runtime_config()

    merged, active_profile = apply_backtest_profile(
        runtime_cfg,
        profile_name="macd_v2_ablation_remove_trial_promotion",
    )

    assert active_profile == "macd_v2_ablation_remove_trial_promotion"
    filters = merged["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]
    assert filters["enable_4h_preflip_trial_entries"] is False
    assert filters["enable_trial_short_below_structure_continuation_promotion"] is False
    assert filters["enable_stable_bear_continuation"] == runtime_cfg["fund_flow"]["macd_mtf_strategy_v2"]["entry_filters"]["enable_stable_bear_continuation"]


def test_build_strategy_config_ignores_legacy_momentum_exhaustion_keys() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "rsi_config": {
                    "enable_entry_refinement": False,
                    "enable_momentum_exhaustion_veto": False,
                    "momentum_exhaustion_bars_1h": 7,
                    "momentum_exhaustion_rsi_overbought": 80.0,
                    "momentum_exhaustion_rsi_oversold": 20.0,
                }
            }
        }
    }

    cfg = build_strategy_config(runtime_cfg)

    assert cfg.enable_rsi_entry_refinement is False
    assert not hasattr(cfg, "enable_momentum_exhaustion_veto")
    assert not hasattr(cfg, "momentum_exhaustion_bars_1h")
    assert not hasattr(cfg, "momentum_exhaustion_rsi_overbought")
    assert not hasattr(cfg, "momentum_exhaustion_rsi_oversold")


def test_build_strategy_config_maps_rsi_launch_sovereign_fields() -> None:
    runtime_cfg = {
        "fund_flow": {
            "macd_mtf_strategy_v2": {
                "entry_filters": {
                    "enable_rsi_launch_sovereign_mode": True,
                    "rsi_launch_sovereign_score_bonus": 0.16,
                    "rsi_launch_sovereign_min_signal_score": 0.81,
                    "rsi_launch_sovereign_competition_multiplier": 1.18,
                    "rsi_launch_sovereign_priority_expire_seconds": 25,
                    "rsi_launch_sovereign_allow_retry": False,
                },
                "rsi_config": {
                    "rsi_launch_sovereign_reset_lookback": 10,
                    "rsi_launch_sovereign_long_reset_ceiling": 43.0,
                    "rsi_launch_sovereign_short_reset_floor": 57.0,
                    "rsi_launch_sovereign_long_4h_rsi_min": 52.0,
                    "rsi_launch_sovereign_short_4h_rsi_max": 48.0,
                    "rsi_launch_sovereign_long_1h_rsi_max": 76.0,
                    "rsi_launch_sovereign_short_1h_rsi_min": 24.0,
                },
            }
        }
    }

    cfg = build_strategy_config(runtime_cfg)

    assert cfg.enable_rsi_launch_sovereign_mode is True
    assert cfg.rsi_launch_sovereign_score_bonus == pytest.approx(0.16, rel=1e-6)
    assert cfg.rsi_launch_sovereign_min_signal_score == pytest.approx(0.81, rel=1e-6)
    assert cfg.rsi_launch_sovereign_competition_multiplier == pytest.approx(1.18, rel=1e-6)
    assert cfg.rsi_launch_sovereign_priority_expire_seconds == 25
    assert cfg.rsi_launch_sovereign_allow_retry is False
    assert cfg.rsi_launch_sovereign_reset_lookback == 10
    assert cfg.rsi_launch_sovereign_long_reset_ceiling == pytest.approx(43.0, rel=1e-6)
    assert cfg.rsi_launch_sovereign_short_reset_floor == pytest.approx(57.0, rel=1e-6)
    assert cfg.rsi_launch_sovereign_long_4h_rsi_min == pytest.approx(52.0, rel=1e-6)
    assert cfg.rsi_launch_sovereign_short_4h_rsi_max == pytest.approx(48.0, rel=1e-6)
    assert cfg.rsi_launch_sovereign_long_1h_rsi_max == pytest.approx(76.0, rel=1e-6)
    assert cfg.rsi_launch_sovereign_short_1h_rsi_min == pytest.approx(24.0, rel=1e-6)


def test_live_config_disables_weak_combo_veto_for_deployment() -> None:
    runtime_cfg = _load_live_runtime_config()

    cfg = build_strategy_config(runtime_cfg)

    assert cfg.enable_weak_combo_veto is False


def test_live_config_uses_rsi_resonance_threshold_defaults() -> None:
    runtime_cfg = _load_live_runtime_config()

    cfg = build_strategy_config(runtime_cfg)

    assert cfg.min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert cfg.red_bar_growing_min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert cfg.green_bar_growing_min_signal_score == pytest.approx(0.69, rel=1e-6)
    assert cfg.flip_bearish_min_signal_score == pytest.approx(0.66, rel=1e-6)
    assert cfg.flip_bullish_min_signal_score == pytest.approx(0.64, rel=1e-6)
    assert cfg.soft_long_min_signal_score == pytest.approx(0.66, rel=1e-6)
    assert cfg.stable_bear_continuation_min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert cfg.stable_bull_continuation_min_signal_score == pytest.approx(0.68, rel=1e-6)
    assert cfg.min_vwap_score_for_entry == pytest.approx(0.0, rel=1e-6)
    assert cfg.preflip_trial_min_signal_score == pytest.approx(0.66, rel=1e-6)
    assert cfg.trial_short_below_structure_promotion_min_signal_score == pytest.approx(0.68, rel=1e-6)
