"""
V3策略过滤器集成模块

将所有过滤器集成到统一的调用接口：
- ShortQualityFilter: 空头质量过滤器
- WinnerPyramidingManager: 赢家加仓管理器
- TimeWindowFilter: 时间窗口过滤器
- SymbolSignalOverrideRegistry: Symbol级信号Override注册表

使用示例：
    from src.fund_flow.v3_filter_integration import V3FilterManager
    
    # 初始化
    manager = V3FilterManager(config)
    
    # 检查入场
    result = manager.check_entry(...)
    
    # 检查加仓
    result = manager.check_addition(...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import logging

from src.fund_flow.filters.short_quality_filter import (
    ShortQualityFilter,
    ShortQualityFilterConfig,
)
from src.fund_flow.filters.winner_pyramiding import (
    WinnerPyramidingManager,
    WinnerPyramidingConfig,
)
from src.fund_flow.filters.time_window_filter import (
    TimeWindowFilter,
    TimeWindowFilterConfig,
)
from src.fund_flow.filters.symbol_signal_override import (
    SymbolSignalOverrideRegistry,
    SymbolSignalOverride,
)


@dataclass
class V3FilterResult:
    """过滤器检查结果"""
    # 是否允许操作
    allowed: bool
    
    # 过滤器名称
    filter_name: str
    
    # 拒绝原因（如果 allowed=False）
    reason: str
    
    # 额外信息
    details: Dict[str, Any] = field(default_factory=dict)


class V3FilterManager:
    """
    V3策略过滤器管理器
    
    统一管理所有过滤器的初始化和调用
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化过滤器管理器
        
        Args:
            config: 完整配置字典
        """
        self.config = config
        self.logger = logging.getLogger("V3FilterManager")
        
        # 提取 fund_flow 配置
        ff_config = config.get("fund_flow", {})
        macd_v2_config = ff_config.get("macd_mtf_strategy_v2", {})
        
        # 初始化时间窗口过滤器
        time_window_cfg = TimeWindowFilterConfig.from_dict({
            "enabled": bool(ff_config.get("allowed_entry_hours_utc", [])),
            "allowed_hours_utc": ff_config.get("allowed_entry_hours_utc", []),
        })
        self.time_window_filter = TimeWindowFilter(time_window_cfg)
        
        # 初始化空头质量过滤器
        short_quality_cfg = macd_v2_config.get("short_quality_filter", {})
        self.short_quality_filter = ShortQualityFilter(
            ShortQualityFilterConfig.from_dict(short_quality_cfg)
        )
        
        # 初始化赢家加仓管理器
        winner_pyramiding_cfg = ff_config.get("winner_pyramiding", {})
        self.winner_pyramiding = WinnerPyramidingManager(
            WinnerPyramidingConfig.from_dict(winner_pyramiding_cfg)
        )
        
        # 初始化 Symbol 级信号 Override 注册表
        entry_filters = macd_v2_config.get("entry_filters", {})
        symbol_overrides = entry_filters.get("symbol_signal_overrides", {})
        if isinstance(symbol_overrides, dict):
            # 字典格式转列表
            symbol_overrides = [{"symbol": k, **v} for k, v in symbol_overrides.items()]
        self.signal_override_registry = SymbolSignalOverrideRegistry(
            overrides=symbol_overrides if isinstance(symbol_overrides, list) else [],
            global_config=entry_filters,
        )
        
        self.logger.info(
            f"V3FilterManager 初始化完成: "
            f"time_window={'enabled' if time_window_cfg.enabled else 'disabled'}, "
            f"short_quality={'enabled' if short_quality_cfg.get('enabled') else 'disabled'}, "
            f"winner_pyramiding={'enabled' if winner_pyramiding_cfg.get('enabled') else 'disabled'}"
        )
    
    def check_entry(
        self,
        symbol: str,
        signal_type: str,
        direction: str,
        timestamp: Optional[datetime] = None,
        funding_rate: Optional[float] = None,
        oi_delta_ratio: Optional[float] = None,
        price: float = 0.0,
        vwap: float = 0.0,
        signal_score: float = 0.0,
    ) -> V3FilterResult:
        """
        检查是否允许入场
        
        Args:
            symbol: 交易对
            signal_type: 信号类型
            direction: 方向 (long/short)
            timestamp: 时间戳
            funding_rate: funding rate
            oi_delta_ratio: OI 变化率
            price: 当前价格
            vwap: VWAP
            signal_score: 信号评分
            
        Returns:
            V3FilterResult
        """
        # 1. 时间窗口过滤
        allowed, reason = self.time_window_filter.should_allow_entry(
            timestamp=timestamp,
            symbol=symbol,
        )
        if not allowed:
            return V3FilterResult(
                allowed=False,
                filter_name="time_window_filter",
                reason=reason,
            )
        
        # 2. Symbol 级信号禁用检查
        if self.signal_override_registry.is_signal_disabled(symbol, signal_type):
            return V3FilterResult(
                allowed=False,
                filter_name="signal_override",
                reason=f"[{symbol}] 信号类型 {signal_type} 已被禁用",
            )
        
        # 3. Symbol 级评分门槛检查
        min_signal_score = self.signal_override_registry.get_min_signal_score(symbol)
        if signal_score < min_signal_score:
            return V3FilterResult(
                allowed=False,
                filter_name="signal_score",
                reason=f"[{symbol}] 信号评分 {signal_score:.3f} < 门槛 {min_signal_score:.3f}",
            )
        
        # 4. 空头质量过滤（仅对空头信号）
        if direction == "short" and signal_type == "flip_bearish":
            allowed, reason = self.short_quality_filter.should_allow(
                signal_type=signal_type,
                funding_rate=funding_rate,
                oi_delta_ratio=oi_delta_ratio,
                price=price,
                vwap=vwap,
                symbol=symbol,
            )
            if not allowed:
                return V3FilterResult(
                    allowed=False,
                    filter_name="short_quality_filter",
                    reason=reason,
                )
        
        # 所有检查通过
        return V3FilterResult(
            allowed=True,
            filter_name="all_passed",
            reason="",
            details={
                "min_signal_score": min_signal_score,
                "signal_score": signal_score,
            },
        )
    
    def check_addition(
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
    ) -> V3FilterResult:
        """
        检查是否允许赢家加仓
        
        Args:
            symbol: 交易对
            unrealized_pnl_pct: 未实现盈亏比例
            signal_type_1h: 1H 信号类型
            ema_structure: EMA 结构状态
            vwap_score: VWAP 评分
            signal_score: 综合信号评分
            position_side: 持仓方向
            current_position_size: 当前持仓大小
            max_allowed_size: 最大允许持仓大小
            initial_size: 初始仓位大小
            
        Returns:
            V3FilterResult
        """
        allowed, reason, addition_size = self.winner_pyramiding.should_add(
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
        
        return V3FilterResult(
            allowed=allowed,
            filter_name="winner_pyramiding",
            reason=reason,
            details={
                "addition_size": addition_size,
                "current_count": self.winner_pyramiding.get_addition_count(symbol),
            },
        )
    
    def record_addition(
        self,
        symbol: str,
        size: float,
        price: float,
        signal_score: float,
        vwap_score: float,
        unrealized_pnl_pct: float,
    ) -> None:
        """记录加仓成功"""
        self.winner_pyramiding.record_addition(
            symbol=symbol,
            size=size,
            price=price,
            signal_score=signal_score,
            vwap_score=vwap_score,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
    
    def reset_symbol_state(self, symbol: str) -> None:
        """重置 symbol 状态（持仓关闭后调用）"""
        self.winner_pyramiding.reset_symbol(symbol)
    
    def is_signal_disabled(self, symbol: str, signal_type: str) -> bool:
        """检查信号是否被禁用"""
        return self.signal_override_registry.is_signal_disabled(symbol, signal_type)
    
    def get_min_signal_score(self, symbol: str) -> float:
        """获取 symbol 的评分门槛"""
        return self.signal_override_registry.get_min_signal_score(symbol)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有过滤器的统计信息"""
        return {
            "time_window_filter": self.time_window_filter.get_stats(),
            "short_quality_filter": self.short_quality_filter.get_stats(),
            "winner_pyramiding": self.winner_pyramiding.get_stats(),
            "signal_override": self.signal_override_registry.get_stats(),
        }
    
    def reset_all_stats(self) -> None:
        """重置所有过滤器的统计信息"""
        self.time_window_filter.reset_stats()
        self.short_quality_filter.reset_stats()
        self.winner_pyramiding.reset_stats()
        self.signal_override_registry.reset_stats()


# 便捷函数
def create_v3_filter_manager(config: Dict[str, Any]) -> V3FilterManager:
    """创建 V3 过滤器管理器"""
    return V3FilterManager(config)
