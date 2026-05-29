from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fund_flow.btc_beta_risk import BtcBetaRiskConfig, BtcBetaRiskScorer, BtcPriceCache


def _seed_corr(scorer: BtcBetaRiskScorer, symbol: str, aligned: bool) -> None:
    for i in range(12):
        btc_ret = 0.001 if i % 2 == 0 else -0.001
        alt_ret = btc_ret if aligned else -btc_ret
        scorer.update_corr_history(symbol, btc_ret, alt_ret)


def test_low_corr_disables_btc_weight_when_only_btc_is_against() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig(min_corr_for_btc_weight=0.20))
    _seed_corr(scorer, "DOGEUSDT", aligned=False)

    result = scorer.score(
        symbol="DOGEUSDT",
        direction="long",
        btc_ret_15m=-0.004,
        btc_ret_30m=-0.006,
        alt_ret_15m=0.001,
        alt_ret_30m=0.002,
        position_age_bars=1,
        mfe_pct=0.0,
        mae_pct=-0.003,
    )

    assert result["use_btc"] is False
    assert result["risk_score"] == 0
    assert result["action"] == "HOLD"


def test_high_corr_fast_fail_reduces_when_alt_turns_against() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig())
    _seed_corr(scorer, "ADAUSDT", aligned=True)

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=4,
        mfe_pct=0.001,
        mae_pct=-0.004,
    )

    assert result["use_btc"] is True
    assert result["risk_score"] >= 2
    assert result["action"] == "REDUCE_50"
    assert "fast_fail" in result["reason"]


def test_fast_fail_does_not_fire_before_min_age_bars() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig())
    _seed_corr(scorer, "ADAUSDT", aligned=True)

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=1,
        mfe_pct=0.001,
        mae_pct=-0.004,
    )

    assert "fast_fail" not in result["reason"]
    assert result["fast_fail_min_age_bars"] == 4


def test_major_symbol_uses_default_corr_before_history_is_warmed() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig(default_corr_major_symbols=0.40))

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.002,
        btc_ret_30m=-0.003,
        alt_ret_15m=0.001,
        alt_ret_30m=0.002,
        position_age_bars=1,
        mfe_pct=0.0,
        mae_pct=-0.003,
    )

    assert result["corr"] == 0.40
    assert result["use_btc"] is True
    assert result["risk_score"] >= 1


def test_non_major_symbol_keeps_zero_default_corr_before_history() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig(default_corr_major_symbols=0.40))

    result = scorer.score(
        symbol="PUMPUSDT",
        direction="long",
        btc_ret_15m=-0.004,
        btc_ret_30m=-0.006,
        alt_ret_15m=0.001,
        alt_ret_30m=0.002,
        position_age_bars=1,
        mfe_pct=0.0,
        mae_pct=-0.003,
    )

    assert result["corr"] == 0.0
    assert result["use_btc"] is False
    assert result["risk_score"] == 0


def test_warmup_from_klines_replaces_default_corr_with_real_history() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig(default_corr_major_symbols=0.40))
    btc_closes = [100.0, 101.0, 100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0, 104.0, 106.0]
    alt_closes = [50.0, 50.5, 50.0, 51.0, 50.5, 51.5, 51.0, 52.0, 51.5, 52.5, 52.0, 53.0]

    scorer.warmup_from_klines("ADAUSDT", btc_closes, alt_closes)

    corr = scorer.get_btc_alt_corr("ADAUSDT")
    assert corr > 0.95


def test_small_position_reduce_upgrades_to_close_above_tiny_skip_floor() -> None:
    scorer = BtcBetaRiskScorer(
        BtcBetaRiskConfig(small_notional_close_threshold=5.0, tiny_notional_skip_threshold=1.0)
    )
    _seed_corr(scorer, "ADAUSDT", aligned=True)

    small = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=4,
        mfe_pct=0.001,
        mae_pct=-0.004,
        position_notional=3.0,
        account_equity=100.0,
    )
    large = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=4,
        mfe_pct=0.001,
        mae_pct=-0.004,
        position_notional=20.0,
        account_equity=100.0,
    )

    assert small["risk_score"] >= 2
    assert small["action"] == "CLOSE"
    assert small["small_notional_close"] is True
    assert small["tiny_notional_skip"] is False
    assert large["action"] == "REDUCE_50"


def test_dynamic_small_notional_close_threshold_uses_equity_floor() -> None:
    scorer = BtcBetaRiskScorer(
        BtcBetaRiskConfig(small_notional_close_threshold=1.0, small_notional_close_equity_pct=0.02)
    )
    _seed_corr(scorer, "ADAUSDT", aligned=True)

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=4,
        mfe_pct=0.001,
        mae_pct=-0.004,
        position_notional=1.5,
        account_equity=100.0,
    )

    assert result["small_notional_close_threshold"] == pytest.approx(2.0)
    assert result["action"] == "CLOSE"
    assert result["small_notional_close"] is True


def test_tiny_position_skips_real_close_instead_of_sending_dust_order() -> None:
    scorer = BtcBetaRiskScorer(
        BtcBetaRiskConfig(small_notional_close_threshold=5.0, tiny_notional_skip_threshold=1.0)
    )
    _seed_corr(scorer, "ADAUSDT", aligned=True)

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.0005,
        btc_ret_30m=-0.0010,
        alt_ret_15m=-0.0012,
        alt_ret_30m=-0.0010,
        position_age_bars=4,
        mfe_pct=0.001,
        mae_pct=-0.004,
        position_notional=0.5,
        account_equity=100.0,
    )

    assert result["risk_score"] >= 2
    assert result["action"] == "SKIP_TINY_CLOSE"
    assert result["small_notional_close"] is False
    assert result["tiny_notional_skip"] is True
    assert "tiny_notional_skip(0.50U)" in result["reason"]


def test_high_corr_btc_alt_sync_close_requires_stacked_risk() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig())
    _seed_corr(scorer, "XLMUSDT", aligned=True)

    result = scorer.score(
        symbol="XLMUSDT",
        direction="long",
        btc_ret_15m=-0.0020,
        btc_ret_30m=-0.0030,
        alt_ret_15m=-0.0014,
        alt_ret_30m=-0.0020,
        position_age_bars=4,
        mfe_pct=0.0,
        mae_pct=-0.004,
    )

    assert result["use_btc"] is True
    assert result["risk_score"] >= 4
    assert result["action"] == "CLOSE"
    assert "btc_alt_30m_sync" in result["reason"]


def test_short_position_uses_positive_returns_as_against_direction() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig())
    _seed_corr(scorer, "ICPUSDT", aligned=True)

    result = scorer.score(
        symbol="ICPUSDT",
        direction="short",
        btc_ret_15m=0.0020,
        btc_ret_30m=0.0030,
        alt_ret_15m=0.0012,
        alt_ret_30m=0.0018,
        position_age_bars=3,
        mfe_pct=0.003,
        mae_pct=-0.001,
    )

    assert result["risk_score"] >= 4
    assert result["action"] == "CLOSE"


def test_disabled_config_always_holds() -> None:
    scorer = BtcBetaRiskScorer(BtcBetaRiskConfig(enabled=False))

    result = scorer.score(
        symbol="ADAUSDT",
        direction="long",
        btc_ret_15m=-0.01,
        btc_ret_30m=-0.02,
        alt_ret_15m=-0.01,
        alt_ret_30m=-0.02,
        position_age_bars=1,
        mfe_pct=0.0,
        mae_pct=-0.01,
    )

    assert result["action"] == "HOLD"
    assert result["risk_score"] == 0


def test_price_cache_returns_15m_and_30m_closed_return() -> None:
    cache = BtcPriceCache(max_bars=4)
    cache.push(100.0)
    cache.push(101.0)
    cache.push(103.0)

    assert cache.ret_15m() == 2.0 / 101.0
    assert cache.ret_30m() == 3.0 / 100.0
