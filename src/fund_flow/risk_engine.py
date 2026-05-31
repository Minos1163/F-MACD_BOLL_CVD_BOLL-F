from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from src.config.config_loader import ConfigLoader
from src.fund_flow.models import FundFlowDecision, Operation


class FundFlowRiskEngine:
    """
    资金流执行前统一风控校验：
    - operation/symbol 合法性
    - 仓位比例、杠杆边界
    - Hyper 风格价格边界钳制（默认 ±1%）
    """

    def __init__(
        self,
        config: Dict[str, Any],
        symbol_whitelist: Optional[Iterable[str]] = None,
    ) -> None:
        self.config = config or {}
        fund_flow_cfg = self.config.get("fund_flow", self.config) or {}
        leverage_cfg = ConfigLoader.get_leverage_settings(self.config, scope="fund_flow")

        self.min_leverage = int(leverage_cfg["min_leverage"])
        self.max_leverage = int(leverage_cfg["max_leverage"])
        self.default_leverage = int(leverage_cfg["default_leverage"])
        self.legacy_min_open_portion = float(fund_flow_cfg.get("min_open_portion", 0.0) or 0.0)
        self.min_open_portion = 0.0
        notional_cfg = fund_flow_cfg.get("min_open_notional", {})
        if not isinstance(notional_cfg, dict):
            notional_cfg = {}
        self.min_open_notional_default = float(notional_cfg.get("default_usdt", 2.0) or 2.0)
        self.min_open_notional_major = float(notional_cfg.get("major_usdt", 5.0) or 5.0)
        self.min_open_notional_btc = float(notional_cfg.get("btc_usdt", self.min_open_notional_major) or self.min_open_notional_major)
        self.major_symbols = {
            str(s).upper()
            for s in notional_cfg.get("major_symbols", ["BTCUSDT"])
            if str(s).strip()
        }
        rescue_cfg = fund_flow_cfg.get("probe_floor_rescue", {})
        if not isinstance(rescue_cfg, dict):
            rescue_cfg = {}
        self.probe_min_open_portion = float(
            rescue_cfg.get(
                "probe_min_open_portion",
                fund_flow_cfg.get("probe_min_open_portion", self.legacy_min_open_portion or 0.0),
            )
        )
        v2_cfg = fund_flow_cfg.get("macd_mtf_strategy_v2", {})
        if not isinstance(v2_cfg, dict):
            v2_cfg = {}
        position_cfg = v2_cfg.get("position_management", {})
        if not isinstance(position_cfg, dict):
            position_cfg = {}
        floor_cfg = fund_flow_cfg.get("final_signal_notional_floor", {})
        if not isinstance(floor_cfg, dict):
            floor_cfg = {}
        self.final_signal_notional_floor_enabled = bool(floor_cfg.get("enabled", True))
        self.final_signal_notional_floor_final_only = bool(floor_cfg.get("apply_to_final_only", True))
        quadrant_cfg = fund_flow_cfg.get("quadrant_resonance", {})
        if not isinstance(quadrant_cfg, dict):
            quadrant_cfg = {}
        quadrant_risk_cfg = quadrant_cfg.get("risk", {})
        if not isinstance(quadrant_risk_cfg, dict):
            quadrant_risk_cfg = {}
        self.quadrant_min_entry_notional = float(
            quadrant_risk_cfg.get("min_entry_notional_usdt", 12.0) or 12.0
        )
        self.quadrant_min_entry_margin = float(
            quadrant_risk_cfg.get("min_entry_margin_usdt", 1.0) or 1.0
        )
        self.max_open_portion = float(fund_flow_cfg.get("max_open_portion", 1.0))
        self.max_single_position_notional = max(
            0.0,
            float(fund_flow_cfg.get("max_single_position_notional", 0.0) or 0.0),
        )
        self.price_deviation_limit_percent = float(
            fund_flow_cfg.get("price_deviation_limit_percent", 1.0)
        )
        account_risk_cfg = fund_flow_cfg.get("account_risk", {})
        self.account_risk_cfg = account_risk_cfg if isinstance(account_risk_cfg, dict) else {}
        self.symbol_whitelist = {s.upper() for s in symbol_whitelist or []}
        self._last_min_notional_meta: Dict[str, Any] = {}

    def validate_symbol(
        self,
        symbol: str,
        operation: Optional[Operation] = None,
        position: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol 为空或非法")
        if self.symbol_whitelist and symbol.upper() not in self.symbol_whitelist:
            if operation == Operation.CLOSE and isinstance(position, dict):
                amount = 0.0
                try:
                    amount = abs(float(position.get("amount", 0.0) or 0.0))
                except Exception:
                    amount = 0.0
                if amount > 0 or bool(position.get("hedge_conflict")):
                    return
            raise ValueError(f"symbol 不在白名单: {symbol}")

    def validate_operation(self, operation: Operation) -> None:
        if operation not in (
            Operation.BUY,
            Operation.SELL,
            Operation.HOLD,
            Operation.CLOSE,
        ):
            raise ValueError(f"operation 非法: {operation}")

    def clamp_leverage(self, leverage: Any) -> int:
        try:
            lev = int(leverage)
        except Exception:
            lev = self.default_leverage
        if lev < self.min_leverage:
            return self.min_leverage
        if lev > self.max_leverage:
            return self.max_leverage
        return int(lev)

    def _get_min_notional(self, symbol: str) -> float:
        symbol_u = str(symbol or "").upper()
        if symbol_u == "BTCUSDT":
            return self.min_open_notional_btc
        if symbol_u in self.major_symbols:
            return self.min_open_notional_major
        return self.min_open_notional_default

    def _get_effective_min_notional(self, symbol: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        base = self._get_min_notional(symbol)
        if isinstance(metadata, dict) and str(metadata.get("strategy_mode") or "").strip().lower() == "quadrant_resonance":
            return max(base, self.quadrant_min_entry_notional)
        return base

    def _get_effective_min_margin(self, metadata: Optional[Dict[str, Any]] = None) -> float:
        if isinstance(metadata, dict) and str(metadata.get("strategy_mode") or "").strip().lower() == "quadrant_resonance":
            return max(0.0, self.quadrant_min_entry_margin)
        return 0.0

    @staticmethod
    def _metadata_float(metadata: Optional[Dict[str, Any]], *keys: str) -> float:
        if not isinstance(metadata, dict):
            return 0.0
        for key in keys:
            try:
                value = float(metadata.get(key, 0.0) or 0.0)
            except Exception:
                value = 0.0
            if value > 0:
                return value
        return 0.0

    @staticmethod
    def _metadata_bool(metadata: Optional[Dict[str, Any]], key: str) -> bool:
        if not isinstance(metadata, dict):
            return False
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "final"}
        return False

    @classmethod
    def _is_final_passed_signal(cls, metadata: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(metadata, dict):
            return False
        stage = str(metadata.get("stage") or metadata.get("reject_stage") or "").strip().lower()
        is_final = stage == "final" or cls._metadata_bool(metadata, "is_final_signal")
        if not is_final:
            return False
        score = cls._metadata_float(metadata, "signal_score", "total_score")
        threshold = cls._metadata_float(metadata, "signal_score_threshold", "threshold")
        return threshold > 0 and score + 1e-12 >= threshold

    def validate_target_portion(
        self,
        portion: Any,
        operation: Operation,
        symbol: str = "",
        account_equity: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[float]:
        self._last_min_notional_meta = {}
        if operation == Operation.HOLD:
            return 0.0
        try:
            val = float(portion)
        except Exception:
            val = 0.0
        if operation == Operation.CLOSE:
            if val <= 0:
                return 1.0
            if val > 1.0:
                return 1.0
            return val
        if val <= 0 or val > self.max_open_portion:
            raise ValueError(
                f"target_portion_of_balance out of range: {val:.4f}, required (0, {self.max_open_portion}]"
            )
        equity = float(account_equity or 0.0)
        if equity > 0:
            leverage = max(1.0, self._metadata_float(metadata, "leverage", "leverage_cap"))
            is_quadrant = isinstance(metadata, dict) and str(metadata.get("strategy_mode") or "").strip().lower() == "quadrant_resonance"
            notional = val * equity * leverage if is_quadrant else val * equity
            margin = val * equity
            min_notional = self._get_effective_min_notional(symbol, metadata)
            min_margin = self._get_effective_min_margin(metadata)
            if notional < min_notional or margin < min_margin:
                min_notional_portion = (
                    min_notional / (equity * leverage)
                    if is_quadrant and equity > 0 and leverage > 0
                    else min_notional / equity if equity > 0 else 0.0
                )
                min_margin_portion = min_margin / equity if equity > 0 else 0.0
                min_portion = max(min_notional_portion, min_margin_portion)
                lift_ratio = (min_portion / val) if val > 0 else float("inf")
                self._last_min_notional_meta = {
                    "target_portion": val,
                    "account_equity": equity,
                    "notional_usdt": notional,
                    "margin_usdt": margin,
                    "min_notional_usdt": min_notional,
                    "min_entry_margin_usdt": min_margin,
                    "min_executable_portion": min_portion,
                    "min_notional_lift_ratio": lift_ratio,
                }
                final_passed = self._is_final_passed_signal(metadata)
                if (
                    self.final_signal_notional_floor_enabled
                    and final_passed
                    and operation in (Operation.BUY, Operation.SELL)
                ):
                    gate_cap = 0.0
                    if isinstance(metadata, dict) and bool(metadata.get("gate_cap_applied", False)):
                        try:
                            gate_cap = float(metadata.get("gate_cap_portion") or 0.0)
                        except Exception:
                            gate_cap = 0.0
                    lifted_portion = min(min_portion, self.max_open_portion)
                    if gate_cap > 0:
                        lifted_portion = min(lifted_portion, gate_cap)
                        self._last_min_notional_meta["gate_cap_applied"] = True
                        self._last_min_notional_meta["gate_cap_portion"] = gate_cap
                    self._last_min_notional_meta["final_signal_notional_floor_applied"] = True
                    self._last_min_notional_meta["short_executable_floor_applied"] = operation == Operation.SELL
                    return lifted_portion
                if operation == Operation.SELL and not self.final_signal_notional_floor_final_only:
                    self._last_min_notional_meta["short_executable_floor_applied"] = True
                    return min_portion
                self._last_min_notional_meta["final_signal_notional_floor_applied"] = False
                self._last_min_notional_meta["short_executable_floor_applied"] = False
                return None
        return val

    def _apply_max_single_position_notional_cap(
        self,
        portion: float,
        operation: Operation,
        account_equity: float,
        leverage: float,
        metadata: Optional[Dict[str, Any]],
    ) -> float:
        cap = float(self.max_single_position_notional)
        equity = float(account_equity or 0.0)
        lev = max(1.0, float(leverage or 1.0))
        if operation not in (Operation.BUY, Operation.SELL) or cap <= 0.0 or equity <= 0.0:
            return float(portion)
        current_notional = float(portion) * equity * lev
        if current_notional <= cap + 1e-12:
            return float(portion)
        capped = max(0.0, min(float(portion), cap / (equity * lev)))
        if isinstance(metadata, dict):
            metadata["max_single_position_notional_cap_applied"] = True
            metadata["max_single_position_notional"] = cap
            metadata["max_single_position_notional_before"] = current_notional
            metadata["max_single_position_notional_after"] = capped * equity * lev
        return capped

    def resolve_min_open_portion(self, decision: Optional[FundFlowDecision] = None) -> float:
        base_min = float(self.min_open_portion)
        if isinstance(getattr(decision, "metadata", None), dict) and bool(decision.metadata.get("rsi_probe_mode", False)):
            return max(0.0001, min(base_min, float(self.probe_min_open_portion)))
        return base_min

    @staticmethod
    def _cfg_bool(cfg: Dict[str, Any], key: str, default: bool = False) -> bool:
        value = cfg.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _cfg_float(cfg: Dict[str, Any], key: str, default: float) -> float:
        try:
            return float(cfg.get(key, default))
        except Exception:
            return float(default)

    @staticmethod
    def _cfg_int(cfg: Dict[str, Any], key: str, default: int) -> int:
        try:
            return int(float(cfg.get(key, default)))
        except Exception:
            return int(default)

    @staticmethod
    def _scale_leverage(leverage: int, scaler: float, rounding: str) -> int:
        raw = float(leverage) * float(scaler)
        mode = str(rounding or "floor").strip().lower()
        if mode == "ceil":
            return int(math.ceil(raw))
        if mode in {"round", "nearest"}:
            return int(round(raw))
        return int(math.floor(raw))

    def _apply_account_risk_scaler(self, decision: FundFlowDecision) -> FundFlowDecision:
        cfg = self.account_risk_cfg
        if not cfg or not self._cfg_bool(cfg, "enabled", False):
            return decision
        if decision.operation not in (Operation.BUY, Operation.SELL):
            return decision
        if isinstance(decision.metadata, dict) and decision.metadata.get("account_risk_scaler_applied") is True:
            return decision

        original_portion = float(decision.target_portion_of_balance)
        original_leverage = int(decision.leverage)

        exposure_scaler = (
            self._cfg_float(cfg, "exposure_scaler_value", 1.0)
            if self._cfg_bool(cfg, "exposure_scaler_enabled", False)
            else 1.0
        )
        leverage_scaler = (
            self._cfg_float(cfg, "leverage_scaler_value", 1.0)
            if self._cfg_bool(cfg, "leverage_scaler_enabled", False)
            else 1.0
        )
        rounding = str(cfg.get("leverage_rounding", "floor") or "floor")

        scaled_portion = original_portion * exposure_scaler
        if scaled_portion > self.max_open_portion:
            raise ValueError(
                "account_risk scaled target_portion_of_balance 越界: "
                f"{scaled_portion:.4f}, 要求 (0, {self.max_open_portion}]"
            )

        min_scaled_leverage = max(1, self._cfg_int(cfg, "min_scaled_leverage", self.min_leverage))
        scaled_leverage = self._scale_leverage(original_leverage, leverage_scaler, rounding)
        scaled_leverage = max(min_scaled_leverage, scaled_leverage)
        decision.leverage = self.clamp_leverage(scaled_leverage)
        decision.target_portion_of_balance = scaled_portion

        metadata = dict(decision.metadata or {})
        metadata["account_risk_scaler_applied"] = True
        if self._cfg_bool(cfg, "metadata_enabled", False):
            metadata.update(
                {
                    "original_target_portion_of_balance": original_portion,
                    "scaled_target_portion_of_balance": scaled_portion,
                    "original_leverage": original_leverage,
                    "scaled_leverage": decision.leverage,
                    "exposure_scaler_value": exposure_scaler,
                    "leverage_scaler_value": leverage_scaler,
                    "leverage_rounding": rounding,
                }
            )
        decision.metadata = metadata

        return decision

    def enforce_price_bounds(self, price: float, oracle_price: float) -> float:
        if price <= 0 or oracle_price <= 0:
            raise ValueError("price/oracle_price 必须大于 0")
        deviation = self.price_deviation_limit_percent / 100.0
        lower = oracle_price * (1.0 - deviation)
        upper = oracle_price * (1.0 + deviation)
        return min(max(price, lower), upper)

    def pick_entry_price(self, decision: FundFlowDecision, current_price: float) -> float:
        if decision.operation == Operation.BUY:
            return float(decision.max_price or current_price)
        if decision.operation == Operation.SELL:
            return float(decision.min_price or current_price)
        return float(current_price)

    def pick_close_price(self, decision: FundFlowDecision, current_price: float, position_side: str) -> float:
        side = str(position_side or "").upper()
        if side == "LONG":
            return float(decision.min_price or (current_price * 0.995))
        if side == "SHORT":
            return float(decision.max_price or (current_price * 1.005))
        return float(current_price)

    def align_close_price(self, close_price: float, current_price: float, position_side: str) -> float:
        side = str(position_side or "").upper()
        if side == "LONG" and close_price > current_price:
            return current_price * 0.9995
        if side == "SHORT" and close_price < current_price:
            return current_price * 1.0005
        return close_price

    def validate_decision(
        self,
        decision: FundFlowDecision,
        position: Optional[Dict[str, Any]] = None,
    ) -> FundFlowDecision:
        self.validate_operation(decision.operation)
        self.validate_symbol(decision.symbol, decision.operation, position)
        decision.leverage = self.clamp_leverage(decision.leverage)
        if decision.operation in (Operation.BUY, Operation.SELL):
            metadata = dict(decision.metadata or {})
            metadata.setdefault("leverage", decision.leverage)
            decision.metadata = metadata
            account_equity = self._metadata_float(
                decision.metadata,
                "account_equity",
                "equity",
                "available_balance",
            )
            validated_portion = self.validate_target_portion(
                decision.target_portion_of_balance,
                decision.operation,
                symbol=decision.symbol,
                account_equity=account_equity,
                metadata=decision.metadata,
            )
            if validated_portion is None:
                metadata = dict(decision.metadata or {})
                metadata.update(self._last_min_notional_meta)
                metadata["min_notional_soft_hold"] = True
                return FundFlowDecision(
                    operation=Operation.HOLD,
                    symbol=decision.symbol,
                    target_portion_of_balance=0.0,
                    leverage=max(1, int(decision.leverage or self.default_leverage)),
                    reason=(
                        "min_notional_below_floor"
                        if not decision.reason
                        else f"min_notional_below_floor | {decision.reason}"
                    ),
                    metadata=metadata,
                )
            validated_portion = self._apply_max_single_position_notional_cap(
                validated_portion,
                decision.operation,
                account_equity,
                decision.leverage,
                decision.metadata,
            )
            decision.target_portion_of_balance = validated_portion
            if self._last_min_notional_meta:
                metadata = dict(decision.metadata or {})
                metadata.update(self._last_min_notional_meta)
                decision.metadata = metadata
        else:
            decision.target_portion_of_balance = self.validate_target_portion(
                decision.target_portion_of_balance,
                decision.operation,
            )
        decision = self._apply_account_risk_scaler(decision)
        if decision.operation in (Operation.BUY, Operation.SELL):
            account_equity = self._metadata_float(
                decision.metadata,
                "account_equity",
                "equity",
                "available_balance",
            )
            revalidated_portion = self.validate_target_portion(
                decision.target_portion_of_balance,
                decision.operation,
                symbol=decision.symbol,
                account_equity=account_equity,
                metadata=decision.metadata,
            )
            if revalidated_portion is None:
                metadata = dict(decision.metadata or {})
                metadata.update(self._last_min_notional_meta)
                metadata["min_notional_soft_hold"] = True
                metadata["min_notional_post_account_risk_revalidated"] = True
                return FundFlowDecision(
                    operation=Operation.HOLD,
                    symbol=decision.symbol,
                    target_portion_of_balance=0.0,
                    leverage=max(1, int(decision.leverage or self.default_leverage)),
                    reason=(
                        "min_notional_below_floor"
                        if not decision.reason
                        else f"min_notional_below_floor | {decision.reason}"
                    ),
                    metadata=metadata,
                )
            if abs(float(revalidated_portion) - float(decision.target_portion_of_balance)) > 1e-12:
                decision.target_portion_of_balance = float(revalidated_portion)
                metadata = dict(decision.metadata or {})
                metadata.update(self._last_min_notional_meta)
                metadata["min_notional_post_account_risk_revalidated"] = True
                decision.metadata = metadata
            capped_portion = self._apply_max_single_position_notional_cap(
                decision.target_portion_of_balance,
                decision.operation,
                account_equity,
                decision.leverage,
                decision.metadata,
            )
            if abs(float(capped_portion) - float(decision.target_portion_of_balance)) > 1e-12:
                decision.target_portion_of_balance = float(capped_portion)
        return decision
