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
        fund_flow_cfg = self.config.get("fund_flow", {}) or {}
        leverage_cfg = ConfigLoader.get_leverage_settings(self.config, scope="fund_flow")

        self.min_leverage = int(leverage_cfg["min_leverage"])
        self.max_leverage = int(leverage_cfg["max_leverage"])
        self.default_leverage = int(leverage_cfg["default_leverage"])
        self.min_open_portion = float(fund_flow_cfg.get("min_open_portion", 0.08))
        self.probe_min_open_portion = float(
            fund_flow_cfg.get("probe_min_open_portion", fund_flow_cfg.get("min_open_portion", 0.08))
        )
        self.max_open_portion = float(fund_flow_cfg.get("max_open_portion", 1.0))
        self.price_deviation_limit_percent = float(
            fund_flow_cfg.get("price_deviation_limit_percent", 1.0)
        )
        account_risk_cfg = fund_flow_cfg.get("account_risk", {})
        self.account_risk_cfg = account_risk_cfg if isinstance(account_risk_cfg, dict) else {}
        self.symbol_whitelist = {s.upper() for s in symbol_whitelist or []}

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

    def validate_target_portion(self, portion: Any, operation: Operation) -> float:
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
        if not (self.min_open_portion <= val <= self.max_open_portion):
            raise ValueError(
                f"target_portion_of_balance 越界: {val:.4f}, 要求 [{self.min_open_portion}, {self.max_open_portion}]"
            )
        return val

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
                f"{scaled_portion:.4f}, 要求 [{self.min_open_portion}, {self.max_open_portion}]"
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
            min_open_backup = self.min_open_portion
            try:
                self.min_open_portion = self.resolve_min_open_portion(decision)
                decision.target_portion_of_balance = self.validate_target_portion(
                    decision.target_portion_of_balance,
                    decision.operation,
                )
            finally:
                self.min_open_portion = min_open_backup
        else:
            decision.target_portion_of_balance = self.validate_target_portion(
                decision.target_portion_of_balance,
                decision.operation,
            )
        decision = self._apply_account_risk_scaler(decision)
        return decision
