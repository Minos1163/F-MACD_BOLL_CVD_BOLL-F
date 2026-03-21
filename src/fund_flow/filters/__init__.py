"""
V3策略过滤器模块

包含：
- ShortQualityFilter: 空头质量过滤器
- WinnerPyramidingManager: 赢家加仓管理器
- TimeWindowFilter: 时间窗口过滤器
- SymbolSignalOverrideRegistry: Symbol级信号Override注册表
"""

from .short_quality_filter import (
    ShortQualityFilter,
    ShortQualityFilterConfig,
)
from .winner_pyramiding import (
    WinnerPyramidingManager,
    WinnerPyramidingConfig,
)
from .time_window_filter import (
    TimeWindowFilter,
    TimeWindowFilterConfig,
)
from .symbol_signal_override import (
    SymbolSignalOverrideRegistry,
    SymbolSignalOverride,
)

__all__ = [
    # 空头质量过滤器
    "ShortQualityFilter",
    "ShortQualityFilterConfig",
    # 赢家加仓
    "WinnerPyramidingManager",
    "WinnerPyramidingConfig",
    # 时间窗口过滤
    "TimeWindowFilter",
    "TimeWindowFilterConfig",
    # Symbol级信号Override
    "SymbolSignalOverrideRegistry",
    "SymbolSignalOverride",
]
