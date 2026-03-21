"""
Phase 3B: 赢家加仓机制

核心逻辑：
- 只在浮盈 + 信号持续确认时才允许加仓
- 与现有 drawdown DCA 语义完全不同，不复用同一配置
- 赢家加仓 = 顺势而为，DCA = 逆势摊平
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime
import logging


@dataclass
class WinnerPyramidingConfig:
    """赢家加仓配置（与现有 DCA 完全独立）"""
    enabled: bool = False
    
    # 触发条件
    min_unrealized_pnl_pct: float = 0.003  # 浮盈 ≥ 0.3%
    require_signal_type: str = "red_bar_growing"  # 要求的1H信号类型
    allowed_ema_structures: List[str] = field(default_factory=lambda: ["strong", "normal"])
    min_vwap_score: float = 0.10
    min_signal_score: float = 0.85
    
    # 加仓参数
    max_additions: int = 1  # 最多加仓次数
    addition_ratio: float = 0.50  # 加仓量 = 初始仓位 × 0.5
    
    # 加仓冷却
    min_addition_interval_seconds: int = 900  # 加仓间隔 ≥ 15分钟
    
    # 日志级别
    log_level: int = logging.INFO
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WinnerPyramidingConfig":
        """从字典创建配置"""
        allowed_ema = data.get("ema_structure_status", ["strong", "normal"])
        if isinstance(allowed_ema, list):
            allowed_ema_structures = allowed_ema
        else:
            allowed_ema_structures = ["strong", "normal"]
            
        signal_types = data.get("signal_types", ["red_bar_growing"])
        require_signal_type = signal_types[0] if signal_types else "red_bar_growing"
        
        return cls(
            enabled=data.get("enabled", False),
            min_unrealized_pnl_pct=float(data.get("min_unrealized_pnl_ratio", 0.003)),
            require_signal_type=require_signal_type,
            allowed_ema_structures=allowed_ema_structures,
            min_vwap_score=float(data.get("min_vwap_score", 0.10)),
            min_signal_score=float(data.get("min_signal_score", 0.85)),
            max_additions=int(data.get("max_additions", 1)),
            addition_ratio=float(data.get("base_add_portion", 0.50)),
            min_addition_interval_seconds=int(data.get("min_addition_interval_seconds", 900)),
        )


@dataclass
class PositionAdditionRecord:
    """加仓记录"""
    timestamp: datetime
    size: float
    price: float
    signal_score: float
    vwap_score: float
    unrealized_pnl_pct: float


class WinnerPyramidingManager:
    """
    赢家加仓管理器
    只在浮盈 + 信号持续确认时才允许加仓
    
    与现有 drawdown DCA 的本质区别：
    - DCA: 亏损时加仓（逆势摊平成本）
    - 赢家加仓: 浮盈时加仓（顺势放大收益）
    """
    
    def __init__(self, config: WinnerPyramidingConfig = None):
        self.config = config or WinnerPyramidingConfig()
        self.logger = logging.getLogger("WinnerPyramiding")
        self.logger.setLevel(self.config.log_level)
        
        # {symbol: (addition_count, last_addition_time, records)}
        self._addition_state: Dict[str, Tuple[int, Optional[datetime], List[PositionAdditionRecord]]] = {}
        
        # 统计信息
        self._stats = {
            "total_checks": 0,
            "allowed": 0,
            "rejected_disabled": 0,
            "rejected_not_long": 0,
            "rejected_max_additions": 0,
            "rejected_insufficient_profit": 0,
            "rejected_wrong_signal": 0,
            "rejected_ema_structure": 0,
            "rejected_vwap_score": 0,
            "rejected_signal_score": 0,
            "rejected_cooldown": 0,
            "rejected_position_limit": 0,
        }
    
    def should_add(
        self,
        symbol: str,
        unrealized_pnl_pct: float,
        signal_type_1h: str,
        ema_structure: str,
        vwap_score: float,
        signal_score: float,
        position_side: str,
        current_position_size: float,
        max_allowed_size: float,
        initial_size: float,
    ) -> Tuple[bool, str, float]:
        """
        判断是否允许加仓
        
        Args:
            symbol: 交易对
            unrealized_pnl_pct: 未实现盈亏比例
            signal_type_1h: 1H 信号类型
            ema_structure: EMA 结构状态
            vwap_score: VWAP 评分
            signal_score: 综合信号评分
            position_side: 持仓方向 ("long" or "short")
            current_position_size: 当前持仓大小
            max_allowed_size: 最大允许持仓大小
            initial_size: 初始仓位大小
            
        Returns:
            (是否加仓, 原因, 加仓大小)
        """
        self._stats["total_checks"] += 1
        
        # 检查是否启用
        if not self.config.enabled:
            self._stats["rejected_disabled"] += 1
            return False, "winner_pyramiding 未启用", 0.0
        
        # 只加多头（空头侧不做赢家加仓）
        if position_side != "long":
            self._stats["rejected_not_long"] += 1
            return False, "当前版本只对多头做赢家加仓", 0.0
        
        # 获取当前加仓状态
        state = self._addition_state.get(symbol, (0, None, []))
        current_count, last_addition_time, records = state
        
        # 检查次数限制
        if current_count >= self.config.max_additions:
            self._stats["rejected_max_additions"] += 1
            return False, f"已达最大加仓次数 {self.config.max_additions}", 0.0
        
        # 检查冷却时间
        if last_addition_time is not None:
            elapsed = (datetime.now() - last_addition_time).total_seconds()
            if elapsed < self.config.min_addition_interval_seconds:
                self._stats["rejected_cooldown"] += 1
                remaining = self.config.min_addition_interval_seconds - elapsed
                return False, f"加仓冷却中，剩余 {remaining:.0f} 秒", 0.0
        
        # 条件1：必须处于浮盈
        if unrealized_pnl_pct < self.config.min_unrealized_pnl_pct:
            self._stats["rejected_insufficient_profit"] += 1
            return False, (
                f"浮盈 {unrealized_pnl_pct:.4f} "
                f"< 阈值 {self.config.min_unrealized_pnl_pct}"
            ), 0.0
        
        # 条件2：1H 信号仍为指定类型（趋势延续）
        if signal_type_1h != self.config.require_signal_type:
            self._stats["rejected_wrong_signal"] += 1
            return False, (
                f"当前 1H 信号 {signal_type_1h} "
                f"!= 要求 {self.config.require_signal_type}"
            ), 0.0
        
        # 条件3：EMA 结构仍支持
        if ema_structure not in self.config.allowed_ema_structures:
            self._stats["rejected_ema_structure"] += 1
            return False, (
                f"EMA 结构 {ema_structure} "
                f"不在允许列表 {self.config.allowed_ema_structures}"
            ), 0.0
        
        # 条件4：VWAP 位置未过热
        if vwap_score < self.config.min_vwap_score:
            self._stats["rejected_vwap_score"] += 1
            return False, (
                f"VWAP 分 {vwap_score:.3f} "
                f"< 阈值 {self.config.min_vwap_score}"
            ), 0.0
        
        # 条件5：综合评分仍达门槛
        if signal_score < self.config.min_signal_score:
            self._stats["rejected_signal_score"] += 1
            return False, (
                f"综合评分 {signal_score:.3f} "
                f"< 阈值 {self.config.min_signal_score}"
            ), 0.0
        
        # 计算加仓大小
        addition_size = initial_size * self.config.addition_ratio
        
        # 检查不超过最大仓位
        projected_total = current_position_size + addition_size
        if projected_total > max_allowed_size:
            # 调整加仓大小
            addition_size = max_allowed_size - current_position_size
            if addition_size <= 0:
                self._stats["rejected_position_limit"] += 1
                return False, (
                    f"加仓后将超出最大仓位 {max_allowed_size:.4f}"
                ), 0.0
        
        # 所有条件满足
        self._stats["allowed"] += 1
        self.logger.info(
            f"[{symbol}] 赢家加仓条件满足: "
            f"加仓 {addition_size:.4f}, "
            f"浮盈 {unrealized_pnl_pct:.3%}, "
            f"评分 {signal_score:.3f}"
        )
        return True, "所有赢家加仓条件满足", addition_size
    
    def record_addition(
        self,
        symbol: str,
        size: float,
        price: float,
        signal_score: float,
        vwap_score: float,
        unrealized_pnl_pct: float,
    ) -> None:
        """记录加仓成功，更新计数器"""
        state = self._addition_state.get(symbol, (0, None, []))
        current_count, _, records = state
        
        record = PositionAdditionRecord(
            timestamp=datetime.now(),
            size=size,
            price=price,
            signal_score=signal_score,
            vwap_score=vwap_score,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
        
        self._addition_state[symbol] = (
            current_count + 1,
            datetime.now(),
            records + [record],
        )
        
        self.logger.info(
            f"[{symbol}] 记录加仓: +{size:.4f} @ {price:.2f}, "
            f"累计加仓 {current_count + 1} 次"
        )
    
    def reset_symbol(self, symbol: str) -> None:
        """持仓关闭后重置计数器"""
        if symbol in self._addition_state:
            del self._addition_state[symbol]
            self.logger.debug(f"[{symbol}] 重置赢家加仓状态")
    
    def get_addition_count(self, symbol: str) -> int:
        """获取当前加仓次数"""
        state = self._addition_state.get(symbol, (0, None, []))
        return state[0]
    
    def get_addition_records(self, symbol: str) -> List[PositionAdditionRecord]:
        """获取加仓记录"""
        state = self._addition_state.get(symbol, (0, None, []))
        return state[2]
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        for key in self._stats:
            self._stats[key] = 0


def check_winner_pyramiding(
    symbol: str,
    unrealized_pnl_pct: float,
    signal_type_1h: str,
    ema_structure: str,
    vwap_score: float,
    signal_score: float,
    position_side: str,
    current_position_size: float,
    max_allowed_size: float,
    initial_size: float,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, float]:
    """
    便捷函数：检查是否允许赢家加仓
    
    Returns:
        (是否加仓, 原因, 加仓大小)
    """
    cfg = WinnerPyramidingConfig.from_dict(config or {})
    manager = WinnerPyramidingManager(cfg)
    return manager.should_add(
        symbol=symbol,
        unrealized_pnl_pct=unrealized_pnl_pct,
        signal_type_1h=signal_type_1h,
        ema_structure=ema_structure,
        vwap_score=vwap_score,
        signal_score=signal_score,
        position_side=position_side,
        current_position_size=current_position_size,
        max_allowed_size=max_allowed_size,
        initial_size=initial_size,
    )
