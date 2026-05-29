from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from src.fund_flow.attribution_engine import FundFlowAttributionEngine
from src.fund_flow.models import FundFlowDecision, Operation, TimeInForce
from src.fund_flow.risk_engine import FundFlowRiskEngine
from src.trading.intents import PositionSide as IntentPositionSide


class FundFlowExecutionRouter:
    """
    统一执行器：
    - 开仓: IOC -> GTC 回退 + TP/SL
    - 平仓: IOC 多次重试 + GTC reduce-only 兜底
    """

    def __init__(
        self,
        client: Any,
        risk_engine: FundFlowRiskEngine,
        attribution_engine: FundFlowAttributionEngine,
        close_retry_times: int = 4,
    ) -> None:
        self.client = client
        self.risk = risk_engine
        self.attribution = attribution_engine
        ff_cfg = ((self.risk.config or {}).get("fund_flow", {}) or {})
        degrade_cfg = ff_cfg.get("execution_degradation", {}) or {}
        if not isinstance(degrade_cfg, dict):
            degrade_cfg = {}

        self.open_ioc_retry_times = max(1, int(degrade_cfg.get("open_ioc_retry_times", 1) or 1))
        self.open_ioc_retry_step_bps = max(0.0, self._to_float(degrade_cfg.get("open_ioc_retry_step_bps", 10.0), 10.0))
        self.open_ioc_dynamic_step_enabled = self._to_bool(
            degrade_cfg.get("open_ioc_dynamic_step_enabled", False),
            False,
        )
        self.open_ioc_max_total_slippage_bps = max(
            0.0,
            self._to_float(degrade_cfg.get("open_ioc_max_total_slippage_bps", 0.0), 0.0),
        )
        self.open_gtc_fallback_enabled = self._to_bool(degrade_cfg.get("open_gtc_fallback_enabled", True), True)
        self.open_market_fallback_enabled = self._to_bool(degrade_cfg.get("open_market_fallback_enabled", False), False)
        self.open_market_fallback_max_slippage_bps = max(
            0.0,
            self._to_float(degrade_cfg.get("open_market_fallback_max_slippage_bps", 0.0), 0.0),
        )
        self.force_market_fallback_on_ioc_remainder = self._to_bool(
            degrade_cfg.get("force_market_fallback_on_ioc_remainder", False),
            False,
        )

        close_retry_default = max(1, int(close_retry_times))
        self.close_retry_times = max(
            1,
            int(degrade_cfg.get("close_ioc_retry_times", close_retry_default) or close_retry_default),
        )
        self.close_ioc_retry_step_bps = max(0.0, self._to_float(degrade_cfg.get("close_ioc_retry_step_bps", 10.0), 10.0))
        self.close_gtc_fallback_enabled = self._to_bool(degrade_cfg.get("close_gtc_fallback_enabled", True), True)
        self.close_market_fallback_enabled = self._to_bool(degrade_cfg.get("close_market_fallback_enabled", False), False)
        count_limit_cfg = ff_cfg.get("position_count_limit_by_margin", {}) or {}
        if not isinstance(count_limit_cfg, dict):
            count_limit_cfg = {}
        self.position_count_limit_by_margin_enabled = self._to_bool(count_limit_cfg.get("enabled", False), False)
        self.position_count_small_margin_threshold_usdt = max(
            0.0,
            self._to_float(count_limit_cfg.get("small_margin_threshold_usdt", 5.0), 5.0),
        )
        self.position_count_max_small_margin_positions = max(
            0,
            int(self._to_float(count_limit_cfg.get("max_small_margin_positions", 5), 5.0)),
        )
        self.position_count_max_large_margin_positions = max(
            0,
            int(self._to_float(count_limit_cfg.get("max_large_margin_positions", 4), 4.0)),
        )
        self.position_count_small_margin_leverage = max(
            0,
            int(self._to_float(count_limit_cfg.get("small_margin_leverage", 0), 0.0)),
        )
        self.min_entry_margin_usdt = max(0.0, self._to_float(ff_cfg.get("min_entry_margin_usdt", 0.0), 0.0))

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return default

    @staticmethod
    def _is_success(result: Dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("warning") == "order_failed_but_position_exists":
            return True
        if result.get("status") == "error":
            return False
        code = result.get("code")
        if isinstance(code, (int, float)) and code < 0:
            return False
        return True

    @staticmethod
    def _extract_message(result: Dict[str, Any]) -> str:
        return str(result.get("msg") or result.get("message") or result)

    def _ensure_open_quantity(
        self,
        *,
        symbol: str,
        raw_quantity: float,
        price: float,
        leverage: int,
        available_balance: float,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        兜底开仓数量，避免因精度/最小名义价值导致 quantity 被归零（尤其是 SELL）。
        """
        info: Dict[str, Any] = {
            "raw_quantity": raw_quantity,
            "formatted_quantity": 0.0,
            "used_min_qty_fallback": False,
        }
        qty = max(0.0, self._to_float(raw_quantity, 0.0))
        if qty > 0:
            try:
                qty = float(self.client.format_quantity(symbol, qty))
            except Exception:
                pass
        info["formatted_quantity"] = qty

        if qty <= 0 and price > 0:
            info["used_min_qty_fallback"] = True
            step_qty = 0.0
            min_qty = 0.0
            try:
                symbol_info = self.client.get_symbol_info(symbol) or {}
                step_size = self._to_float(symbol_info.get("step_size"), 0.0)
                if step_size > 0:
                    step_qty = float(self.client.format_quantity(symbol, step_size))
                min_qty = self._to_float(symbol_info.get("min_qty"), 0.0)
                if min_qty > 0:
                    min_qty = float(self.client.format_quantity(symbol, min_qty))
            except Exception:
                step_qty = 0.0
                min_qty = 0.0

            candidate = max(self._to_float(raw_quantity, 0.0), step_qty, min_qty)
            if candidate <= 0:
                candidate = max(step_qty, min_qty)

            if candidate > 0:
                try:
                    candidate = float(
                        self.client.ensure_min_notional_quantity(
                            symbol,
                            candidate,
                            price,
                        )
                    )
                except Exception:
                    pass
                if min_qty > 0 and candidate < min_qty:
                    candidate = min_qty
                try:
                    candidate = float(self.client.format_quantity(symbol, candidate))
                except Exception:
                    pass
            qty = max(0.0, candidate)
            info["fallback_quantity"] = qty

        if qty <= 0:
            info["reject_reason"] = "qty_zero_after_fallback"
            return 0.0, info

        safe_lev = max(1, int(leverage or 1))
        required_margin = (qty * price) / safe_lev if price > 0 else 0.0
        info["required_margin"] = required_margin
        info["available_balance"] = available_balance
        if required_margin > (available_balance + 1e-8):
            info["reject_reason"] = "insufficient_balance_for_min_qty"
            return 0.0, info

        return qty, info

    def _resolve_close_quantity(
        self,
        *,
        symbol: str,
        position_size: float,
        target_portion: float,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        计算平仓数量。
        当目标平仓量被交易所步长量化为 0 时，自动升级为可执行数量（优先全平当前微仓位），
        避免风控减仓持续 noop（"平仓数量为0"）而被动等待止损。
        """
        info: Dict[str, Any] = {
            "position_size": max(0.0, self._to_float(position_size, 0.0)),
            "target_portion": max(0.0, self._to_float(target_portion, 0.0)),
            "raw_close_quantity": 0.0,
            "formatted_close_quantity": 0.0,
            "promoted_to_full_close": False,
            "promotion_reason": "",
        }
        pos_size = info["position_size"]
        tgt = info["target_portion"]
        raw_close_qty = max(0.0, pos_size * tgt)
        info["raw_close_quantity"] = raw_close_qty
        close_qty = raw_close_qty
        try:
            close_qty = float(self.client.format_quantity(symbol, close_qty))
        except Exception:
            pass
        info["formatted_close_quantity"] = close_qty
        if close_qty > 0:
            return close_qty, info

        if raw_close_qty <= 0 or pos_size <= 0:
            info["reject_reason"] = "close_qty_zero_after_format"
            return 0.0, info

        # 微仓位兜底：若部分平仓量被格式化为 0，升级为全平当前可执行仓位。
        full_close_qty = pos_size
        try:
            full_close_qty = float(self.client.format_quantity(symbol, full_close_qty))
        except Exception:
            pass
        if full_close_qty > 0:
            info["promoted_to_full_close"] = True
            info["promotion_reason"] = "partial_qty_rounded_to_zero"
            info["formatted_close_quantity"] = full_close_qty
            return full_close_qty, info

        info["reject_reason"] = "full_close_qty_zero_after_format"
        return 0.0, info

    def _format_price(self, symbol: str, price: float) -> float:
        """Format price to exchange tick/precision to avoid -1111 precision errors."""
        if price <= 0:
            return price
        try:
            info = self.client.get_symbol_info(symbol)
        except Exception:
            info = None

        if isinstance(info, dict):
            try:
                tick = float(info.get("tick_size", 0) or 0)
            except Exception:
                tick = 0.0
            if tick > 0:
                try:
                    p_dec = Decimal(str(price))
                    t_dec = Decimal(str(tick))
                    q = (p_dec / t_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    out = float((q * t_dec).normalize())
                    if out > 0:
                        return out
                except Exception:
                    pass
            try:
                precision = int(info.get("price_precision", 4) or 4)
                if precision < 0:
                    precision = 4
                return round(float(price), precision)
            except Exception:
                pass
        return round(float(price), 4)

    def _is_no_liquidity(self, result: Dict[str, Any]) -> bool:
        msg = self._extract_message(result).lower()
        code = result.get("code")
        if code in (-2010, -5022):
            return True
        keys = (
            "immediately match and take",
            "insufficient liquidity",
            "no liquidity",
            "would immediately trigger",
        )
        return any(k in msg for k in keys)

    def _is_reduce_only_rejected(self, result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        code = result.get("code")
        try:
            if code is not None and int(float(code)) == -2022:
                return True
        except Exception:
            pass
        msg = self._extract_message(result).lower()
        keys = (
            "reduceonly order is rejected",
            "reduceonly rejected",
            "reduce only order is rejected",
            "reduceonly",
            "-2022",
        )
        return any(k in msg for k in keys)

    def _sync_symbol_leverage(self, symbol: str, target_leverage: int) -> Dict[str, Any]:
        """
        将交易所该交易对杠杆同步到目标值，避免“策略显示杠杆”和“实盘实际杠杆”不一致。
        """
        requested = int(target_leverage)
        try:
            if not hasattr(self.client, "position_gateway"):
                return {"status": "skipped", "requested": requested, "message": "position_gateway unavailable"}
            raw = self.client.position_gateway.change_leverage(symbol, requested)
            applied = requested
            if isinstance(raw, dict):
                try:
                    code_field = raw.get("code")
                    if code_field is not None:
                        code_value = int(str(code_field))
                        if code_value < 0:
                            return {
                                "status": "error",
                                "requested": requested,
                                "message": str(raw.get("msg") or raw),
                                "raw": raw,
                            }
                except Exception:
                    pass
                try:
                    lev_field = raw.get("leverage")
                    if lev_field is not None:
                        applied = int(float(lev_field))
                except Exception:
                    applied = requested
            return {"status": "success", "requested": requested, "applied": applied, "raw": raw}
        except Exception as e:
            return {"status": "error", "requested": requested, "message": f"change_leverage exception: {e}"}

    @staticmethod
    def _position_from_snapshot(position: Optional[Dict[str, Any]]) -> Tuple[str, float]:
        if not position:
            return "", 0.0
        side = str(position.get("side", "")).upper()
        size = float(position.get("amount", 0.0) or position.get("positionAmt", 0.0) or 0.0)
        return side, abs(size)

    @staticmethod
    def _infer_position_side(raw_position: Optional[Dict[str, Any]]) -> str:
        if not isinstance(raw_position, dict):
            return ""
        side = str(raw_position.get("positionSide", "")).upper()
        if side in ("LONG", "SHORT"):
            return side
        amt = FundFlowExecutionRouter._to_float(raw_position.get("positionAmt"), 0.0)
        if amt > 0:
            return "LONG"
        if amt < 0:
            return "SHORT"
        return ""

    def _fetch_live_position_state(self, symbol: str, preferred_side: str = "") -> Dict[str, Any]:
        """
        从交易所实时拉取仓位，避免使用快照导致 reduce-only 方向/数量失配。
        """
        symbol_up = str(symbol or "").upper()
        side_pref = str(preferred_side or "").upper()
        try:
            if side_pref in ("LONG", "SHORT"):
                pos_side = self.client.get_position(symbol_up, side=side_pref)
                amt_side = abs(self._to_float((pos_side or {}).get("positionAmt"), 0.0)) if isinstance(pos_side, dict) else 0.0
                if amt_side > 0:
                    return {
                        "ok": True,
                        "symbol": symbol_up,
                        "side": side_pref,
                        "size": amt_side,
                        "source": "get_position(side)",
                        "raw": pos_side,
                    }

            pos_any = self.client.get_position(symbol_up)
            amt_any = abs(self._to_float((pos_any or {}).get("positionAmt"), 0.0)) if isinstance(pos_any, dict) else 0.0
            if amt_any > 0:
                side_any = self._infer_position_side(pos_any) or side_pref
                return {
                    "ok": True,
                    "symbol": symbol_up,
                    "side": side_any,
                    "size": amt_any,
                    "source": "get_position(any)",
                    "raw": pos_any,
                }

            all_positions = self.client.get_all_positions() if hasattr(self.client, "get_all_positions") else []
            candidates: List[Dict[str, Any]] = []
            for p in all_positions or []:
                if not isinstance(p, dict):
                    continue
                if str(p.get("symbol") or "").upper() != symbol_up:
                    continue
                amt = abs(self._to_float(p.get("positionAmt"), 0.0))
                if amt <= 0:
                    continue
                candidates.append(p)
            if candidates:
                primary = max(candidates, key=lambda x: abs(self._to_float(x.get("positionAmt"), 0.0)))
                amt_primary = abs(self._to_float(primary.get("positionAmt"), 0.0))
                side_primary = self._infer_position_side(primary) or side_pref
                return {
                    "ok": True,
                    "symbol": symbol_up,
                    "side": side_primary,
                    "size": amt_primary,
                    "source": "get_all_positions",
                    "raw": primary,
                }

            return {
                "ok": True,
                "symbol": symbol_up,
                "side": "",
                "size": 0.0,
                "source": "flat",
                "raw": {},
            }
        except Exception as e:
            return {
                "ok": False,
                "symbol": symbol_up,
                "side": "",
                "size": 0.0,
                "source": "error",
                "error": str(e),
            }

    def _position_margin_usdt(self, position: Dict[str, Any]) -> float:
        margin = self._to_float(position.get("margin"), 0.0)
        if margin > 0:
            return abs(margin)
        margin = self._to_float(position.get("initialMargin"), 0.0)
        if margin > 0:
            return abs(margin)
        amount = abs(self._to_float(position.get("positionAmt"), 0.0))
        entry_price = self._to_float(position.get("entryPrice"), 0.0)
        leverage = self._to_float(position.get("leverage"), 0.0)
        if amount > 0 and entry_price > 0 and leverage > 0:
            return abs(amount * entry_price / leverage)
        notional = abs(self._to_float(position.get("notional"), 0.0))
        if notional <= 0:
            notional = abs(self._to_float(position.get("positionValue"), 0.0))
        if notional > 0 and leverage > 0:
            return abs(notional / leverage)
        return 0.0

    def _check_position_count_limit_by_margin(
        self,
        *,
        symbol: str,
        new_margin: float,
        position: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        threshold = float(self.position_count_small_margin_threshold_usdt)
        bucket = "small" if float(new_margin) < threshold else "large"
        max_count = (
            int(self.position_count_max_small_margin_positions)
            if bucket == "small"
            else int(self.position_count_max_large_margin_positions)
        )
        counts = {"small": 0, "large": 0}
        if position is not None or not self.position_count_limit_by_margin_enabled or max_count <= 0:
            return {
                "allowed": True,
                "bucket": bucket,
                "current_count": 0,
                "max_count": max_count,
                "threshold_usdt": threshold,
                "new_margin_usdt": float(new_margin),
                "counts": counts,
            }

        symbol_up = str(symbol or "").upper()
        try:
            positions = self.client.get_all_positions() if hasattr(self.client, "get_all_positions") else []
        except Exception as e:
            return {
                "allowed": True,
                "bucket": bucket,
                "current_count": 0,
                "max_count": max_count,
                "threshold_usdt": threshold,
                "new_margin_usdt": float(new_margin),
                "counts": counts,
                "position_fetch_error": str(e),
            }

        seen_symbols = set()
        for raw_position in positions or []:
            if not isinstance(raw_position, dict):
                continue
            pos_symbol = str(raw_position.get("symbol") or "").upper()
            if not pos_symbol or pos_symbol == symbol_up or pos_symbol in seen_symbols:
                continue
            amount = abs(self._to_float(raw_position.get("positionAmt"), 0.0))
            if amount <= 0:
                continue
            margin = self._position_margin_usdt(raw_position)
            if margin <= 0:
                continue
            seen_symbols.add(pos_symbol)
            if margin < threshold:
                counts["small"] += 1
            else:
                counts["large"] += 1

        current_count = counts[bucket]
        return {
            "allowed": current_count < max_count,
            "bucket": bucket,
            "current_count": current_count,
            "max_count": max_count,
            "threshold_usdt": threshold,
            "new_margin_usdt": float(new_margin),
            "counts": counts,
        }

    def _check_min_entry_margin(
        self,
        *,
        decision: FundFlowDecision,
        margin: float,
        available_balance: float,
    ) -> Dict[str, Any]:
        threshold = float(self.min_entry_margin_usdt)
        meta = {
            "enabled": threshold > 0.0,
            "reason": "disabled",
            "estimated_margin_usdt": max(0.0, float(margin or 0.0)),
            "min_entry_margin_usdt": threshold,
            "target_portion": self._to_float(getattr(decision, "target_portion_of_balance", 0.0), 0.0),
            "available_balance": max(0.0, float(available_balance or 0.0)),
            "leverage": max(1, int(self._to_float(getattr(decision, "leverage", 1), 1.0))),
        }
        if decision.operation not in (Operation.BUY, Operation.SELL):
            meta["reason"] = "not_entry"
            return {"allowed": True, **meta}
        if threshold <= 0.0:
            return {"allowed": True, **meta}
        if meta["estimated_margin_usdt"] + 1e-12 < threshold:
            meta["reason"] = "micro_margin_block"
            return {"allowed": False, **meta}
        meta["reason"] = "margin_check_passed"
        return {"allowed": True, **meta}

    def _place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: float,
        price: float,
        tif: TimeInForce,
        reduce_only: bool,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": tif.value.upper(),
        }
        try:
            if bool(self.client.broker.get_hedge_mode()):
                params["positionSide"] = position_side
        except Exception:
            params["positionSide"] = position_side

        try:
            return self.client._execute_order_v2(
                params=params,
                side=side,
                reduce_only=reduce_only,
            )
        except Exception as e:
            msg = str(e)
            if "[OPEN BLOCKED]" in msg:
                return {
                    "status": "noop",
                    "code": 0,
                    "message": msg,
                    "open_blocked": True,
                }
            return {
                "status": "error",
                "code": -1,
                "message": f"place_limit_order exception: {msg}",
            }

    def _place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: float,
        reduce_only: bool,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "type": "MARKET",
            "quantity": quantity,
        }
        try:
            if bool(self.client.broker.get_hedge_mode()):
                params["positionSide"] = position_side
        except Exception:
            params["positionSide"] = position_side

        try:
            return self.client._execute_order_v2(
                params=params,
                side=side,
                reduce_only=reduce_only,
            )
        except Exception as e:
            msg = str(e)
            if "[OPEN BLOCKED]" in msg:
                return {
                    "status": "noop",
                    "code": 0,
                    "message": msg,
                    "open_blocked": True,
                }
            return {
                "status": "error",
                "code": -1,
                "message": f"place_market_order exception: {msg}",
            }

    def _place_exit_guard_close_position_order(
        self,
        *,
        symbol: str,
        close_side: str,
        position_side: str,
        quantity: float,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "type": "MARKET",
            "quantity": quantity,
            "closePosition": True,
        }
        try:
            if bool(self.client.broker.get_hedge_mode()):
                params["positionSide"] = position_side
        except Exception:
            params["positionSide"] = position_side

        try:
            return self.client._execute_order_v2(
                params=params,
                side=close_side,
                reduce_only=False,
            )
        except Exception as e:
            return {
                "status": "error",
                "code": -1,
                "message": f"exit_guard_close_position exception: {e}",
            }

    def _retry_exit_guard_close_position_after_reduce_reject(
        self,
        *,
        decision: FundFlowDecision,
        position_side: str,
        close_side: str,
        close_qty: float,
        filled_close_qty: float,
    ) -> Optional[Dict[str, Any]]:
        if "EXIT_SIGNAL_GUARD" not in str(decision.reason or ""):
            return None
        live = self._fetch_live_position_state(decision.symbol, preferred_side=position_side)
        live_size = self._to_float(live.get("size"), 0.0)
        live_side = str(live.get("side") or position_side).upper()
        if live.get("ok") and live_size <= 0:
            return {
                "status": "success",
                "operation": "close",
                "message": "ExitGuard -2022 后实时仓位为0，按已平仓处理",
                "quantity": close_qty,
                "filled_quantity": filled_close_qty,
                "remaining_quantity": 0.0,
                "fallback": "exit_guard_reduce_only_recheck_flat",
                "position_sync": live,
            }
        if not live.get("ok") or live_side not in ("LONG", "SHORT") or live_size <= 0:
            return None

        retry_side = "SELL" if live_side == "LONG" else "BUY"
        retry_qty = live_size
        try:
            retry_qty = float(self.client.format_quantity(decision.symbol, retry_qty))
        except Exception:
            pass
        if retry_qty <= 0:
            return None

        retry = self._place_exit_guard_close_position_order(
            symbol=decision.symbol,
            close_side=retry_side,
            position_side=live_side,
            quantity=retry_qty,
        )
        executed = min(self._to_float(retry.get("executedQty"), 0.0), retry_qty)
        success = self._is_success(retry) or self._is_filled(retry)
        return {
            "status": "success" if success else "error",
            "operation": "close",
            "order": retry,
            "quantity": close_qty,
            "filled_quantity": filled_close_qty + executed,
            "remaining_quantity": 0.0 if success else retry_qty,
            "fallback": "exit_guard_close_position_retry",
            "position_sync": live,
            "message": "ExitGuard -2022 后使用 closePosition 重试" if success else self._extract_message(retry),
        }

    @staticmethod
    def _with_degradation_path(result: Dict[str, Any], path: List[Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(result, dict):
            result["degradation_path"] = path
            return result
        return {"status": "error", "message": str(result), "degradation_path": path}

    def _resolve_open_ioc_retry_plan(self, decision_score: float) -> Tuple[int, float]:
        retry_times = int(self.open_ioc_retry_times)
        step_bps = float(self.open_ioc_retry_step_bps)
        if self.open_ioc_dynamic_step_enabled:
            if decision_score >= 0.90:
                step_bps = max(step_bps, self.open_ioc_retry_step_bps * 2.0)
            elif decision_score >= 0.80:
                step_bps = max(step_bps, self.open_ioc_retry_step_bps * 1.5)
        if self.open_ioc_max_total_slippage_bps > 0 and step_bps > 0:
            allowed_retry_count = int(self.open_ioc_max_total_slippage_bps // step_bps)
            retry_times = min(retry_times, max(1, allowed_retry_count + 1))
        return retry_times, step_bps

    def _try_place_with_fallback(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: float,
        price: float,
        tif: TimeInForce,
        reduce_only: bool,
        execution_policy: str = "ioc",
        market_fallback_enabled: bool = False,
        market_fallback_timeout_ms: int = 0,
        market_fallback_max_slippage_bps: int = 0,
        market_fallback_reference_price: float = 0.0,
        current_price: float = 0.0,
        disable_market_fallback: bool = False,
        decision_score: float = 0.0,
    ) -> Dict[str, Any]:
        path: List[Dict[str, Any]] = []
        policy = str(execution_policy or "ioc").strip().lower()
        retry_times, retry_step_bps = self._resolve_open_ioc_retry_plan(decision_score)

        current = self._place_limit_order(
            symbol=symbol,
            side=side,
            position_side=position_side,
            quantity=quantity,
            price=price,
            tif=tif,
            reduce_only=reduce_only,
        )
        path.append(
            {
                "step": "limit_initial",
                "tif": tif.value,
                "price": price,
                "success": self._is_success(current),
                "execution_policy": policy,
            }
        )
        if self._is_success(current) or (isinstance(current, dict) and current.get("open_blocked")):
            return self._with_degradation_path(current, path)

        # 非 IOC 订单不做 IOC 退化链
        if tif != TimeInForce.IOC:
            return self._with_degradation_path(current, path)

        # IOC 多次重试（仅在流动性不足类错误时触发）
        if policy != "ioc_market_fallback":
            for i in range(1, retry_times):
                if not self._is_no_liquidity(current):
                    break
                total_slippage_bps = retry_step_bps * i
                step = (retry_step_bps / 10000.0) * i
                retry_price = price * (1.0 + step) if side == "BUY" else price * (1.0 - step)
                retry_price = self._format_price(symbol, retry_price)
                current = self._place_limit_order(
                    symbol=symbol,
                    side=side,
                    position_side=position_side,
                    quantity=quantity,
                    price=retry_price,
                    tif=TimeInForce.IOC,
                    reduce_only=reduce_only,
                )
                path.append(
                    {
                        "step": "limit_ioc_retry",
                        "retry_index": i,
                        "tif": TimeInForce.IOC.value,
                        "price": retry_price,
                        "step_bps": retry_step_bps,
                        "total_slippage_bps": total_slippage_bps,
                        "success": self._is_success(current),
                    }
                )
                if self._is_success(current) or (isinstance(current, dict) and current.get("open_blocked")):
                    return self._with_degradation_path(current, path)

        force_market_fallback = (
            self.force_market_fallback_on_ioc_remainder
            and policy != "ioc_market_fallback"
            and self.open_market_fallback_enabled
            and not disable_market_fallback
        )

        # IOC -> GTC 退化。强制市价安全网开启时，GTC 不再抢先返回 pending。
        if (
            policy != "ioc_market_fallback"
            and self.open_gtc_fallback_enabled
            and not force_market_fallback
            and self._is_no_liquidity(current)
        ):
            gtc_result = self._place_limit_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                quantity=quantity,
                price=self._format_price(symbol, price),
                tif=TimeInForce.GTC,
                reduce_only=reduce_only,
            )
            path.append(
                {
                    "step": "limit_gtc_fallback",
                    "tif": TimeInForce.GTC.value,
                    "price": self._format_price(symbol, price),
                    "success": self._is_success(gtc_result),
                }
            )
            current = gtc_result
            if self._is_success(current) or (isinstance(current, dict) and current.get("open_blocked")):
                return self._with_degradation_path(current, path)

        # 最后兜底：市价开仓（默认关闭）
        if self._is_no_liquidity(current):
            fallback_allowed = (
                self.open_market_fallback_enabled
                and (
                    (policy == "ioc_market_fallback" and market_fallback_enabled)
                    or force_market_fallback
                )
                and not disable_market_fallback
            )
            if fallback_allowed:
                ref_price = float(market_fallback_reference_price or price or current_price or 0.0)
                latest_price = float(current_price or price or ref_price or 0.0)
                if ref_price > 0 and latest_price > 0:
                    fallback_slippage_bps = float(
                        market_fallback_max_slippage_bps or self.open_market_fallback_max_slippage_bps or 0
                    )
                    max_slippage = max(0.0, fallback_slippage_bps) / 10000.0
                    if side == "BUY":
                        slippage_blocked = latest_price > ref_price * (1.0 + max_slippage)
                    else:
                        slippage_blocked = latest_price < ref_price * (1.0 - max_slippage)
                    path.append(
                        {
                            "step": "market_fallback_guard",
                            "timeout_ms": int(market_fallback_timeout_ms or 0),
                            "reference_price": ref_price,
                            "latest_price": latest_price,
                            "max_slippage_bps": int(fallback_slippage_bps),
                            "forced": bool(force_market_fallback),
                            "success": not slippage_blocked,
                        }
                    )
                    if not slippage_blocked:
                        market_result = self._place_market_order(
                            symbol=symbol,
                            side=side,
                            position_side=position_side,
                            quantity=quantity,
                            reduce_only=reduce_only,
                        )
                        path.append(
                            {
                                "step": "market_fallback",
                                "forced": bool(force_market_fallback),
                                "success": self._is_success(market_result),
                            }
                        )
                        current = market_result
            elif policy != "ioc_market_fallback" and self.open_market_fallback_enabled and not disable_market_fallback:
                market_result = self._place_market_order(
                    symbol=symbol,
                    side=side,
                    position_side=position_side,
                    quantity=quantity,
                    reduce_only=reduce_only,
                )
                path.append(
                    {
                        "step": "market_fallback",
                        "success": self._is_success(market_result),
                    }
                )
                current = market_result

        return self._with_degradation_path(current, path)

    def _place_tp_sl(self, decision: FundFlowDecision, position_side: str) -> Dict[str, Any]:
        tp = decision.take_profit_price
        sl = decision.stop_loss_price
        metadata = decision.metadata if isinstance(decision.metadata, dict) else {}
        tp_levels_raw = metadata.get("tp_levels") if isinstance(metadata, dict) else None
        tp_levels: List[Tuple[float, float]] = []
        if isinstance(tp_levels_raw, list):
            for item in tp_levels_raw:
                if not isinstance(item, dict):
                    continue
                level_price_raw = item.get("price")
                reduce_pct_raw = item.get("reduce_pct")
                if level_price_raw is None or reduce_pct_raw is None:
                    continue
                try:
                    level_price = float(level_price_raw)
                    reduce_pct = float(reduce_pct_raw)
                except Exception:
                    continue
                if level_price > 0 and reduce_pct > 0:
                    tp_levels.append((level_price, max(0.0, min(1.0, reduce_pct))))
        if tp is None and sl is None and not tp_levels:
            return {"status": "noop", "message": "no tp/sl"}
        side = IntentPositionSide.LONG if position_side == "LONG" else IntentPositionSide.SHORT
        qty: Optional[float] = None
        try:
            pos = self.client.get_position(decision.symbol, side=position_side)
            if pos and abs(float(pos.get("positionAmt", 0))) > 0:
                qty = abs(float(pos.get("positionAmt", 0)))
                qty = float(self.client.format_quantity(decision.symbol, qty))
        except Exception:
            qty = None
        try:
            try:
                result = self.client._execute_protection_v2(
                    symbol=decision.symbol,
                    side=side,
                    tp=tp,
                    sl=sl,
                    quantity=qty,
                    tp_levels=tp_levels or None,
                )
            except TypeError:
                result = self.client._execute_protection_v2(
                    symbol=decision.symbol,
                    side=side,
                    tp=tp,
                    sl=sl,
                )
            if isinstance(result, dict) and str(result.get("status", "")).lower() == "success" and not result.get("orders"):
                synthetic_orders: List[Dict[str, Any]] = []
                if tp is not None or tp_levels:
                    synthetic_orders.append({"orderId": "synthetic_tp", "type": "TAKE_PROFIT"})
                if sl is not None:
                    synthetic_orders.append({"orderId": "synthetic_sl", "type": "STOP"})
                if synthetic_orders:
                    result = dict(result)
                    result["orders"] = synthetic_orders
            return result
        except Exception as e:
            return {"status": "error", "code": -1, "message": f"place_tp_sl exception: {e}"}

    @staticmethod
    def _is_exchange_error_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return True
        code = item.get("code")
        return isinstance(code, (int, float)) and code < 0

    def _check_protection_completeness(
        self,
        decision: FundFlowDecision,
        protection: Dict[str, Any],
    ) -> Dict[str, Any]:
        orders = protection.get("orders") if isinstance(protection, dict) else []
        order_list = orders if isinstance(orders, list) else []
        success_orders: List[Dict[str, Any]] = []
        for item in order_list:
            if not isinstance(item, dict):
                continue
            if self._is_exchange_error_item(item):
                continue
            if item.get("orderId") is None:
                continue
            success_orders.append(item)

        has_tp = False
        has_sl = False
        for item in success_orders:
            order_type = str(item.get("type") or item.get("strategyType") or "").upper()
            if "TAKE_PROFIT" in order_type:
                has_tp = True
            if "STOP" in order_type:
                has_sl = True

        need_tp = decision.take_profit_price is not None
        need_sl = decision.stop_loss_price is not None
        status = str(protection.get("status", "")).lower()
        status_ok = status in ("success", "noop")

        if not status_ok:
            return {
                "ok": False,
                "reason": f"protection_status={status or 'unknown'}",
                "has_tp": has_tp,
                "has_sl": has_sl,
            }
        if need_tp and not has_tp:
            return {"ok": False, "reason": "missing_take_profit_order", "has_tp": has_tp, "has_sl": has_sl}
        if need_sl and not has_sl:
            return {"ok": False, "reason": "missing_stop_loss_order", "has_tp": has_tp, "has_sl": has_sl}
        return {"ok": True, "reason": "ok", "has_tp": has_tp, "has_sl": has_sl}

    def _force_flatten_position(self, symbol: str, position_side: str) -> Dict[str, Any]:
        side_up = str(position_side or "").upper()
        if side_up not in ("LONG", "SHORT"):
            return {"status": "error", "message": f"invalid position side: {position_side}"}
        try:
            pos = self.client.get_position(symbol, side=side_up)
            if not pos or abs(float(pos.get("positionAmt", 0))) <= 0:
                return {"status": "noop", "message": "no position to flatten"}
            qty = abs(float(pos.get("positionAmt", 0)))
            qty = float(self.client.format_quantity(symbol, qty))
            close_side = "SELL" if side_up == "LONG" else "BUY"
            params: Dict[str, Any] = {
                "symbol": symbol,
                "type": "MARKET",
                "quantity": qty,
                "closePosition": True,
            }
            try:
                if bool(self.client.broker.get_hedge_mode()):
                    params["positionSide"] = side_up
            except Exception:
                pass
            result = self.client._execute_order_v2(
                params=params,
                side=close_side,
                reduce_only=True,
            )
            if not self._is_success(result):
                return {
                    "status": "error",
                    "message": f"force_flatten order rejected: {self._extract_message(result)}",
                    "order": result,
                }
            if self._is_filled(result):
                return {"status": "success", "order": result}

            # 回滚路径必须尽量确认仓位是否已实际消失，避免“假成功”。
            latest = self.client.get_position(symbol, side=side_up)
            latest_amt = abs(self._to_float((latest or {}).get("positionAmt"), 0.0)) if isinstance(latest, dict) else 0.0
            if latest_amt <= 0:
                return {
                    "status": "success",
                    "order": result,
                    "message": "position closed after flatten request",
                }
            return {
                "status": "error",
                "message": "force_flatten not confirmed; position still open",
                "order": result,
                "remaining_qty": latest_amt,
            }
        except Exception as e:
            return {"status": "error", "message": f"force_flatten exception: {e}"}

    def _is_filled(self, result: Dict[str, Any]) -> bool:
        if not self._is_success(result):
            return False
        status = str(result.get("status", "")).upper()
        if status in ("FILLED", "PARTIALLY_FILLED"):
            return True
        executed_qty = self._to_float(result.get("executedQty"), 0.0)
        return executed_qty > 0

    def _cleanup_symbol_orders_after_flat(self, symbol: str) -> Dict[str, str]:
        """
        Best-effort cleanup for a symbol that is confirmed flat.

        PAPI conditional TP/SL orders are not reliably covered by allOpenOrders,
        so close/no-position paths must clear both conditional and regular open orders.
        """
        result: Dict[str, str] = {}
        try:
            if hasattr(self.client, "cancel_all_conditional_orders"):
                self.client.cancel_all_conditional_orders(symbol)
                result["cancel_conditional_orders"] = "ok"
            else:
                result["cancel_conditional_orders"] = "unavailable"
        except Exception as e:
            result["cancel_conditional_orders"] = f"error:{e}"

        try:
            self.client.cancel_all_open_orders(symbol)
            result["cancel_open_orders"] = "ok"
        except Exception as e:
            result["cancel_open_orders"] = f"error:{e}"

        return result

    def _is_fully_filled(self, result: Dict[str, Any]) -> bool:
        if not self._is_success(result):
            return False
        status = str(result.get("status", "")).upper()
        if status == "FILLED":
            return True
        executed_qty = self._to_float(result.get("executedQty"), 0.0)
        orig_qty = self._to_float(result.get("origQty"), 0.0)
        if orig_qty > 0:
            return executed_qty >= max(orig_qty - 1e-12, 0.0)
        return False

    def execute_decision(
        self,
        decision: FundFlowDecision,
        account_state: Dict[str, Any],
        current_price: float,
        position: Optional[Dict[str, Any]] = None,
        trigger_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trigger_context = trigger_context or {}
        if decision.operation in (Operation.BUY, Operation.SELL):
            metadata = dict(decision.metadata or {})
            if "account_equity" not in metadata:
                equity = self._to_float(account_state.get("equity"), 0.0)
                if equity <= 0:
                    equity = self._to_float(account_state.get("available_balance"), 0.0)
                if equity > 0:
                    metadata["account_equity"] = equity
                    decision.metadata = metadata
        try:
            decision = self.risk.validate_decision(decision, position=position)
        except Exception as e:
            result = {"status": "error", "message": f"decision 校验失败: {e}"}
            self.attribution.log_execution(decision, result)
            return result

        try:
            if decision.operation == Operation.HOLD:
                result = {"status": "noop", "message": "hold"}
                self.attribution.log_execution(decision, result)
                return result

            if decision.operation in (Operation.BUY, Operation.SELL):
                available_balance = self._to_float(account_state.get("available_balance"), 0.0)
                if available_balance <= 0:
                    result = {"status": "error", "message": "可用余额为0，禁止开仓"}
                    self.attribution.log_execution(decision, result)
                    return result

                margin = available_balance * decision.target_portion_of_balance
                margin_gate = self._check_min_entry_margin(
                    decision=decision,
                    margin=margin,
                    available_balance=available_balance,
                )
                if not bool(margin_gate.get("allowed", True)):
                    if isinstance(decision.metadata, dict):
                        decision.metadata["micro_margin_gate"] = margin_gate
                    result = {
                        "status": "noop",
                        "message": "开仓保证金低于最小阈值，跳过开仓",
                        "micro_margin_gate": margin_gate,
                        "trigger_context": trigger_context,
                    }
                    self.attribution.log_execution(decision, result)
                    return result
                if isinstance(decision.metadata, dict):
                    decision.metadata["micro_margin_gate"] = margin_gate
                count_limit = self._check_position_count_limit_by_margin(
                    symbol=decision.symbol,
                    new_margin=margin,
                    position=position,
                )
                if not bool(count_limit.get("allowed", True)):
                    result = {
                        "status": "noop",
                        "message": "持仓数量限制，跳过开仓",
                        "position_count_limit": count_limit,
                        "trigger_context": trigger_context,
                    }
                    self.attribution.log_execution(decision, result)
                    return result

                leverage = self.risk.clamp_leverage(decision.leverage)
                small_margin_leverage_override = None
                strategy_mode = ""
                if isinstance(decision.metadata, dict):
                    strategy_mode = str(decision.metadata.get("strategy_mode") or "").strip().lower()
                if (
                    self.position_count_limit_by_margin_enabled
                    and margin > 0
                    and margin < self.position_count_small_margin_threshold_usdt
                    and self.position_count_small_margin_leverage > leverage
                ):
                    original_leverage = leverage
                    leverage = self.position_count_small_margin_leverage
                    small_margin_leverage_override = {
                        "enabled": True,
                        "threshold_usdt": self.position_count_small_margin_threshold_usdt,
                        "margin_usdt": margin,
                        "original_leverage": original_leverage,
                        "leverage": leverage,
                    }
                leverage_sync = self._sync_symbol_leverage(decision.symbol, leverage)
                strict_sync = bool(
                    ((self.risk.config or {}).get("fund_flow", {}) or {}).get("strict_leverage_sync", True)
                )
                if leverage_sync.get("status") == "error" and strict_sync:
                    result = {
                        "status": "error",
                        "message": "杠杆同步失败，已阻止开仓",
                        "leverage_sync": leverage_sync,
                        "trigger_context": trigger_context,
                    }
                    self.attribution.log_execution(decision, result)
                    return result
                if leverage_sync.get("status") == "success":
                    try:
                        leverage = int(leverage_sync.get("applied", leverage))
                    except Exception:
                        pass

                position_value = margin * leverage
                qty_raw = round(position_value / current_price, 10) if current_price > 0 else 0.0
                qty, qty_info = self._ensure_open_quantity(
                    symbol=decision.symbol,
                    raw_quantity=qty_raw,
                    price=current_price,
                    leverage=leverage,
                    available_balance=available_balance,
                )
                if qty <= 0:
                    result = {
                        "status": "error",
                        "message": "开仓数量无效（最小下单量/余额约束）",
                        "quantity_info": qty_info,
                    }
                    self.attribution.log_execution(decision, result)
                    return result

                raw_price = self.risk.pick_entry_price(decision, current_price)
                order_price = self.risk.enforce_price_bounds(raw_price, current_price)
                order_price = self._format_price(decision.symbol, order_price)
                side = "BUY" if decision.operation == Operation.BUY else "SELL"
                position_side = "LONG" if decision.operation == Operation.BUY else "SHORT"
                md = decision.metadata if isinstance(decision.metadata, dict) else {}
                tif_override = str(md.get("entry_tif_override", "") or "").strip().upper()
                entry_tif = decision.time_in_force
                if tif_override == "GTC":
                    entry_tif = TimeInForce.GTC
                elif tif_override == "IOC":
                    entry_tif = TimeInForce.IOC
                entry_execution_policy = str(md.get("entry_execution_policy", "ioc") or "ioc")
                entry_market_fallback_enabled = bool(md.get("entry_market_fallback_enabled", False))
                entry_market_fallback_timeout_ms = int(md.get("entry_market_fallback_timeout_ms", 0) or 0)
                entry_market_fallback_max_slippage_bps = int(md.get("entry_market_fallback_max_slippage_bps", 0) or 0)
                entry_reference_price = self._to_float(md.get("entry_reference_price"), current_price)
                disable_market_fallback = bool(md.get("disable_market_fallback", False))
                decision_score = max(
                    self._to_float(md.get("competition_score"), 0.0),
                    self._to_float(md.get("signal_score"), 0.0),
                )

                order_result = self._try_place_with_fallback(
                    symbol=decision.symbol,
                    side=side,
                    position_side=position_side,
                    quantity=qty,
                    price=order_price,
                    tif=entry_tif,
                    reduce_only=False,
                    execution_policy=entry_execution_policy,
                    market_fallback_enabled=entry_market_fallback_enabled,
                    market_fallback_timeout_ms=entry_market_fallback_timeout_ms,
                    market_fallback_max_slippage_bps=entry_market_fallback_max_slippage_bps,
                    market_fallback_reference_price=entry_reference_price,
                    current_price=current_price,
                    disable_market_fallback=disable_market_fallback,
                    decision_score=decision_score,
                )
                if isinstance(order_result, dict) and order_result.get("open_blocked"):
                    result = {
                        "status": "noop",
                        "message": "已有持仓，跳过重复开仓",
                        "order": order_result,
                        "leverage_sync": leverage_sync,
                        "trigger_context": trigger_context,
                    }
                    self.attribution.log_execution(decision, result)
                    return result
                if not self._is_success(order_result):
                    order_error_msg = self._extract_message(order_result) if isinstance(order_result, dict) else str(order_result)
                    order_error_code = order_result.get("code") if isinstance(order_result, dict) else None
                    result = {
                        "status": "error",
                        "message": "开仓失败",
                        "error_detail": order_error_msg,
                        "error_code": order_error_code,
                        "order": order_result,
                        "leverage_sync": leverage_sync,
                        "quantity_info": qty_info,
                        "trigger_context": trigger_context,
                    }
                    self.attribution.log_execution(decision, result)
                    return result

                entry_filled = self._is_filled(order_result)
                if entry_filled:
                    protection = self._place_tp_sl(decision, position_side)
                    protection_guard = self._check_protection_completeness(decision, protection)
                    if not protection_guard.get("ok", False):
                        ff_cfg = (self.risk.config or {}).get("fund_flow", {}) or {}
                        rollback_on_fail = bool(ff_cfg.get("rollback_on_tp_sl_fail", True))
                        rollback_result = None
                        if rollback_on_fail:
                            rollback_result = self._force_flatten_position(decision.symbol, position_side)
                        result = {
                            "status": "error",
                            "message": "保护单下发失败，已阻止裸仓",
                            "order": order_result,
                            "protection": protection,
                            "protection_guard": protection_guard,
                            "rollback": rollback_result,
                            "quantity": qty,
                            "price": order_price,
                            "leverage": leverage,
                            "margin": margin,
                            "position_value": position_value,
                            "leverage_sync": leverage_sync,
                            "small_margin_leverage_override": small_margin_leverage_override,
                            "quantity_info": qty_info,
                            "trigger_context": trigger_context,
                        }
                        self.attribution.log_execution(decision, result)
                        return result
                else:
                    protection = {
                        "status": "pending",
                        "message": "entry not filled yet, tp/sl skipped for now",
                    }

                result = {
                    "status": "success" if entry_filled else "pending",
                    "message": "开仓成交，保护单已处理" if entry_filled else "开仓委托已提交，待成交（非失败）",
                    "operation": decision.operation.value,
                    "order": order_result,
                    "protection": protection,
                    "quantity": qty,
                    "price": order_price,
                    "leverage": leverage,
                    "margin": margin,
                    "position_value": position_value,
                    "quantity_info": qty_info,
                    "leverage_sync": leverage_sync,
                    "small_margin_leverage_override": small_margin_leverage_override,
                    "trigger_context": trigger_context,
                }
                self.attribution.log_execution(decision, result)
                return result

            if decision.operation == Operation.CLOSE:
                snapshot_side, snapshot_size = self._position_from_snapshot(position)
                live_position = self._fetch_live_position_state(decision.symbol, preferred_side=snapshot_side)
                position_side = snapshot_side
                position_size = snapshot_size
                if live_position.get("ok"):
                    live_side = str(live_position.get("side", "")).upper()
                    live_size = self._to_float(live_position.get("size"), 0.0)
                    if live_size <= 0:
                        result = {
                            "status": "noop",
                            "message": "无可平仓位（交易所实时仓位为0）",
                            "position_sync": {
                                "snapshot_side": snapshot_side,
                                "snapshot_size": snapshot_size,
                                "live_side": live_side,
                                "live_size": live_size,
                                "source": live_position.get("source"),
                            },
                        }
                        result.update(self._cleanup_symbol_orders_after_flat(decision.symbol))
                        self.attribution.log_execution(decision, result)
                        return result
                    position_size = live_size
                    if live_side in ("LONG", "SHORT"):
                        position_side = live_side
                if position_size <= 0 or position_side not in ("LONG", "SHORT"):
                    result = {
                        "status": "noop",
                        "message": "无可平仓位",
                        "position_sync": {
                            "snapshot_side": snapshot_side,
                            "snapshot_size": snapshot_size,
                            "live_ok": bool(live_position.get("ok")),
                            "live_error": live_position.get("error"),
                        },
                    }
                    result.update(self._cleanup_symbol_orders_after_flat(decision.symbol))
                    self.attribution.log_execution(decision, result)
                    return result

                close_qty, close_qty_info = self._resolve_close_quantity(
                    symbol=decision.symbol,
                    position_size=position_size,
                    target_portion=decision.target_portion_of_balance,
                )
                if close_qty <= 0:
                    result = {
                        "status": "noop",
                        "message": "平仓数量为0",
                        "quantity_info": close_qty_info,
                    }
                    self.attribution.log_execution(decision, result)
                    return result

                base_close_price = self.risk.pick_close_price(decision, current_price, position_side)
                base_close_price = self.risk.align_close_price(base_close_price, current_price, position_side)
                close_side = "SELL" if position_side == "LONG" else "BUY"
                is_full_close_target = bool(close_qty_info.get("promoted_to_full_close")) or (
                    decision.target_portion_of_balance >= 1.0
                )

                final_result: Dict[str, Any] = {}
                close_path: List[Dict[str, Any]] = []
                remaining_close_qty = close_qty
                filled_close_qty = 0.0
                for i in range(self.close_retry_times):
                    req_qty = remaining_close_qty
                    try:
                        req_qty = float(self.client.format_quantity(decision.symbol, req_qty))
                    except Exception:
                        pass
                    if req_qty <= 0:
                        break
                    step = (self.close_ioc_retry_step_bps / 10000.0) * i
                    if position_side == "LONG":
                        retry_price = base_close_price * (1.0 - step)
                    else:
                        retry_price = base_close_price * (1.0 + step)
                    retry_price = self.risk.align_close_price(retry_price, current_price, position_side)
                    retry_price = self._format_price(decision.symbol, retry_price)
                    retry_result = self._place_limit_order(
                        symbol=decision.symbol,
                        side=close_side,
                        position_side=position_side,
                        quantity=req_qty,
                        price=retry_price,
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                    )
                    executed_qty = min(self._to_float(retry_result.get("executedQty"), 0.0), max(req_qty, 0.0))
                    if executed_qty > 0:
                        filled_close_qty += executed_qty
                        remaining_close_qty = max(0.0, close_qty - filled_close_qty)
                        try:
                            remaining_close_qty = float(self.client.format_quantity(decision.symbol, remaining_close_qty))
                        except Exception:
                            pass
                    close_path.append(
                        {
                            "step": "close_ioc_retry",
                            "retry_index": i,
                            "request_quantity": req_qty,
                            "executed_quantity": executed_qty,
                            "remaining_quantity": remaining_close_qty,
                            "price": retry_price,
                            "success": self._is_success(retry_result),
                            "filled": self._is_filled(retry_result),
                            "fully_filled": self._is_fully_filled(retry_result),
                            "reduce_only_rejected": self._is_reduce_only_rejected(retry_result),
                        }
                    )

                    if self._is_reduce_only_rejected(retry_result):
                        # 立即重查实时仓位，避免在已平仓/错腿状态下继续重复提交，触发连续 -2022。
                        live_after_retry = self._fetch_live_position_state(decision.symbol, preferred_side=position_side)
                        live_retry_size = self._to_float(live_after_retry.get("size"), 0.0)
                        live_retry_side = str(live_after_retry.get("side", "")).upper()
                        close_path.append(
                            {
                                "step": "close_reduce_recheck",
                                "retry_index": i,
                                "live_ok": bool(live_after_retry.get("ok")),
                                "live_side": live_retry_side,
                                "live_size": live_retry_size,
                                "source": live_after_retry.get("source"),
                            }
                        )
                        if live_after_retry.get("ok") and live_retry_size <= 0:
                            remaining_close_qty = 0.0
                            final_result = {
                                "status": "success",
                                "operation": "close",
                                "message": "ReduceOnly rejected 后实时仓位为0，终止重试并按已平仓处理",
                                "quantity": close_qty,
                                "filled_quantity": filled_close_qty,
                                "remaining_quantity": 0.0,
                                "fallback": "reduce_only_recheck_flat",
                            }
                            break
                        if live_after_retry.get("ok") and live_retry_side in ("LONG", "SHORT") and live_retry_side != position_side:
                            position_side = live_retry_side
                            close_side = "SELL" if position_side == "LONG" else "BUY"
                        if live_after_retry.get("ok") and live_retry_size > 0 and remaining_close_qty > live_retry_size:
                            remaining_close_qty = live_retry_size
                            try:
                                remaining_close_qty = float(self.client.format_quantity(decision.symbol, remaining_close_qty))
                            except Exception:
                                pass

                    if remaining_close_qty <= 0:
                        final_result = {
                            "status": "success",
                            "operation": "close",
                            "order": retry_result,
                            "quantity": close_qty,
                            "filled_quantity": filled_close_qty,
                            "remaining_quantity": 0.0,
                            "retry_index": i,
                            "price": retry_price,
                        }
                        break

                if not final_result:
                    if self.close_gtc_fallback_enabled:
                        boundary_price = current_price * (0.99 if position_side == "LONG" else 1.01)
                        boundary_price = self._format_price(decision.symbol, boundary_price)
                        fallback_qty = remaining_close_qty
                        try:
                            fallback_qty = float(self.client.format_quantity(decision.symbol, fallback_qty))
                        except Exception:
                            pass
                        if fallback_qty <= 0:
                            final_result = {
                                "status": "success" if remaining_close_qty <= 0 else "error",
                                "operation": "close",
                                "quantity": close_qty,
                                "filled_quantity": filled_close_qty,
                                "remaining_quantity": remaining_close_qty,
                                "fallback": "gtc_reduce_only_skipped_zero_qty",
                                "price": boundary_price,
                            }
                        else:
                            fallback = self._place_limit_order(
                                symbol=decision.symbol,
                                side=close_side,
                                position_side=position_side,
                                quantity=fallback_qty,
                                price=boundary_price,
                                tif=TimeInForce.GTC,
                                reduce_only=True,
                            )
                            fallback_executed = min(self._to_float(fallback.get("executedQty"), 0.0), max(fallback_qty, 0.0))
                            if fallback_executed > 0:
                                filled_close_qty += fallback_executed
                                remaining_close_qty = max(0.0, close_qty - filled_close_qty)
                                try:
                                    remaining_close_qty = float(self.client.format_quantity(decision.symbol, remaining_close_qty))
                                except Exception:
                                    pass
                            close_path.append(
                                {
                                    "step": "close_gtc_fallback",
                                    "request_quantity": fallback_qty,
                                    "executed_quantity": fallback_executed,
                                    "remaining_quantity": remaining_close_qty,
                                    "price": boundary_price,
                                    "success": self._is_success(fallback),
                                    "filled": self._is_filled(fallback),
                                    "reduce_only_rejected": self._is_reduce_only_rejected(fallback),
                                }
                            )
                            fallback_status = (
                                "success"
                                if remaining_close_qty <= 0
                                else ("pending" if self._is_success(fallback) or self._is_filled(fallback) else "error")
                            )
                            final_result = {
                                "status": fallback_status,
                                "operation": "close",
                                "order": fallback,
                                "quantity": close_qty,
                                "filled_quantity": filled_close_qty,
                                "remaining_quantity": remaining_close_qty,
                                "fallback": "gtc_reduce_only",
                                "price": boundary_price,
                            }
                    else:
                        final_result = {
                            "status": "error",
                            "operation": "close",
                            "message": "IOC平仓重试耗尽，且GTC回退已禁用",
                            "quantity": close_qty,
                            "filled_quantity": filled_close_qty,
                            "remaining_quantity": remaining_close_qty,
                        }

                if final_result.get("status") == "error" and self.close_market_fallback_enabled:
                    market_qty = remaining_close_qty
                    try:
                        market_qty = float(self.client.format_quantity(decision.symbol, market_qty))
                    except Exception:
                        pass
                    if market_qty <= 0:
                        final_result = {
                            "status": "success" if remaining_close_qty <= 0 else "error",
                            "operation": "close",
                            "quantity": close_qty,
                            "filled_quantity": filled_close_qty,
                            "remaining_quantity": remaining_close_qty,
                            "fallback": "market_reduce_only_skipped_zero_qty",
                        }
                    else:
                        market_fallback = self._place_market_order(
                            symbol=decision.symbol,
                            side=close_side,
                            position_side=position_side,
                            quantity=market_qty,
                            reduce_only=True,
                        )
                        market_executed = min(self._to_float(market_fallback.get("executedQty"), 0.0), max(market_qty, 0.0))
                        if market_executed > 0:
                            filled_close_qty += market_executed
                            remaining_close_qty = max(0.0, close_qty - filled_close_qty)
                            try:
                                remaining_close_qty = float(self.client.format_quantity(decision.symbol, remaining_close_qty))
                            except Exception:
                                pass
                        close_path.append(
                            {
                                "step": "close_market_fallback",
                                "request_quantity": market_qty,
                                "executed_quantity": market_executed,
                                "remaining_quantity": remaining_close_qty,
                                "success": self._is_success(market_fallback),
                                "filled": self._is_filled(market_fallback),
                                "reduce_only_rejected": self._is_reduce_only_rejected(market_fallback),
                            }
                        )
                        market_status = (
                            "success"
                            if remaining_close_qty <= 0
                            else ("pending" if self._is_success(market_fallback) or self._is_filled(market_fallback) else "error")
                        )
                        final_result = {
                            "status": market_status,
                            "operation": "close",
                            "order": market_fallback,
                            "quantity": close_qty,
                            "filled_quantity": filled_close_qty,
                            "remaining_quantity": remaining_close_qty,
                            "fallback": "market_reduce_only",
                        }

                reduce_only_rejected = self._is_reduce_only_rejected(final_result.get("order")) or any(
                    bool(step.get("reduce_only_rejected")) for step in close_path
                )
                if final_result.get("status") == "error" and reduce_only_rejected:
                    exit_guard_retry = self._retry_exit_guard_close_position_after_reduce_reject(
                        decision=decision,
                        position_side=position_side,
                        close_side=close_side,
                        close_qty=close_qty,
                        filled_close_qty=filled_close_qty,
                    )
                    if exit_guard_retry is not None:
                        final_result = exit_guard_retry
                        if final_result.get("status") == "success":
                            remaining_close_qty = 0.0
                    else:
                        live_after_reject = self._fetch_live_position_state(decision.symbol, preferred_side=position_side)
                        live_after_size = self._to_float(live_after_reject.get("size"), 0.0)
                        if live_after_reject.get("ok") and live_after_size <= 0:
                            final_result = {
                                "status": "success",
                                "operation": "close",
                                "message": "ReduceOnly rejected，但交易所实时仓位已为0，按已平仓处理",
                                "quantity": close_qty,
                                "filled_quantity": filled_close_qty,
                                "remaining_quantity": 0.0,
                                "fallback": "reduce_only_reconciled_flat",
                                "position_sync": {
                                    "snapshot_side": snapshot_side,
                                    "snapshot_size": snapshot_size,
                                    "live_side": live_after_reject.get("side"),
                                    "live_size": live_after_size,
                                    "source": live_after_reject.get("source"),
                                },
                            }
                            remaining_close_qty = 0.0
                        else:
                            final_result["position_sync"] = {
                                "snapshot_side": snapshot_side,
                                "snapshot_size": snapshot_size,
                                "live_side": live_after_reject.get("side"),
                                "live_size": live_after_size,
                                "live_ok": bool(live_after_reject.get("ok")),
                                "source": live_after_reject.get("source"),
                                "error": live_after_reject.get("error"),
                            }

                if final_result.get("status") == "error" and not final_result.get("message"):
                    order_detail = final_result.get("order")
                    detail_msg = self._extract_message(order_detail) if isinstance(order_detail, dict) else ""
                    final_result["message"] = detail_msg or "平仓失败"

                close_order = final_result.get("order", {})
                close_filled = filled_close_qty > 0 or self._is_filled(close_order)
                target_close_completed = remaining_close_qty <= 0
                final_result["target_close_completed"] = target_close_completed
                if is_full_close_target:
                    final_result["full_close_completed"] = target_close_completed
                if target_close_completed:
                    if is_full_close_target:
                        final_result.update(self._cleanup_symbol_orders_after_flat(decision.symbol))
                elif close_filled:
                    if final_result.get("status") == "success":
                        final_result["status"] = "pending"
                    final_result["message"] = (
                        "全平仅部分成交，保留保护单，等待剩余仓位处理"
                        if is_full_close_target
                        else "部分平仓仅部分成交，目标剩余仓位待继续处理"
                    )
                    final_result["remaining_quantity"] = remaining_close_qty
                final_result["degradation_path"] = close_path
                final_result["quantity_info"] = close_qty_info

                self.attribution.log_execution(decision, final_result)
                return final_result

            result = {"status": "error", "message": f"不支持的 operation: {decision.operation.value}"}
            self.attribution.log_execution(decision, result)
            return result
        except Exception as e:
            result = {
                "status": "error",
                "message": f"execute_decision exception: {e}",
                "trigger_context": trigger_context,
            }
            self.attribution.log_execution(decision, result)
            return result

    @staticmethod
    def decision_to_json(decision: FundFlowDecision) -> str:
        return json.dumps(decision.to_dict(), ensure_ascii=False)
