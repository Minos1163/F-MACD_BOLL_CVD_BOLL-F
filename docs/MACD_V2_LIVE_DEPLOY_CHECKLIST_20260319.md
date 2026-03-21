# MACD V2 Live Deploy Checklist

Date: 2026-03-19

## Recommended Runtime Parameters

- `fund_flow.max_active_symbols = 3`
- `fund_flow.default_target_portion = 0.6`
- `fund_flow.max_symbol_position_portion = 0.6`
- `fund_flow.min_open_portion = 0.06`
- `fund_flow.min_leverage = 2`
- `fund_flow.default_leverage = 3`
- `fund_flow.max_leverage = 4`
- `fund_flow.entry_slippage = 0.0015`
- `fund_flow.stop_loss_pct = 0.004`
- `fund_flow.take_profit_pct = 0.0`
- `fund_flow.breakeven_enabled = true`
- `fund_flow.breakeven_trigger_pnl_ratio = 0.003`
- `fund_flow.breakeven_lock_ratio = 0.001`
- `fund_flow.strategy_mode = macd_mtf_strategy_v2`

## MACD V2 Entry Filters

- `entry_filters.enable_flip_bullish_strict_filter = true`
- `entry_filters.disable_flip_bullish_entries = true`
- `entry_filters.flip_bullish_min_vwap_score = 0.12`
- `entry_filters.flip_bullish_require_pullback_bounce = true`
- `entry_filters.flip_bullish_require_15m_growing = true`
- `entry_filters.disable_green_bar_growing_entries = true`

## MACD V2 Penalty Controls

- `penalty_config.overheat_growing_penalty = 0.12`
- `penalty_config.overheat_ema_multiplier_threshold = 1.2`
- `penalty_config.overheat_vwap_score_threshold = 0.10`

## Backtest Baseline

- Source summary: `output/backtest/v2_summary_20260319_125906.json`
- Source trades: `output/backtest/v2_trades_20260319_125906.csv`
- Data coverage: `32/35` symbols
- Missing data: `SHIBUSDT`, `RNDRUSDT`, `PEPEUSDT`
- Initial capital: `$10,000`
- Final equity: `$14,467.33`
- Return: `+44.67%`
- Total trades: `156`
- Win rate: `69.9%`
- Profit factor: `3.01`

## Stress Test Snapshot

- Portfolio max drawdown: `-8.20%`
- Worst single trade: `-$712.05`
- Max consecutive losing trades: `7`
- Worst 3-trade loss block: `-$712.73`
- Worst 5-trade loss block: `-$707.03`
- Worst 10-trade loss block: `-$714.79`
- Worst day realized PnL: `-$700.54` on `2026-02-11`

## Symbol Risk Watchlist

- `UNIUSDT`: total PnL `-$724.94`, symbol max drawdown `-7.41%`
- `HBARUSDT`: total PnL `-$478.79`, symbol max drawdown `-4.88%`, max loss streak `5`
- `FILUSDT`: total PnL `-$272.69`, symbol max drawdown `-2.77%`
- `DOGEUSDT`: total PnL `-$206.77`, symbol max drawdown `-2.28%`

## Operational Interpretation

- Current account circuit config is still meaningful:
  - `risk.max_daily_loss_percent = 5`
  - `risk.max_consecutive_losses = 2`
- Worst historical day was about `-7.01%` of a `$10,000` account, so the daily loss circuit can trigger in real trading.
- Long loss streaks are still possible at trade level, especially when multiple symbols stop out near the same time.
- The current configuration is materially more stable than earlier versions, but it is not low-volatility.

## Deployment Guardrails

- Use current config only after confirming protection orders are successfully attached on live entries.
- Watch `UNIUSDT` and `HBARUSDT` first; they are the clearest candidates for symbol-level throttling or removal if live behavior matches backtest weakness.
- If the first live batch shows clustered stop-outs, reduce `max_active_symbols` from `3` to `2` before changing leverage.
