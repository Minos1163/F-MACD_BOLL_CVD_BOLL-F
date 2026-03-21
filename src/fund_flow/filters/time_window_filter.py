"""
Phase 3C: 时间窗口过滤

核心逻辑：
- 排除低流动性时段，减少滑点和假信号
- 基于 UTC 小时白名单过滤
- 支持动态调整允许交易的时段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone
import logging


@dataclass
class TimeWindowFilterConfig:
    """时间窗口过滤器配置"""
    enabled: bool = False
    timezone: str = "UTC"
    
    # UTC 小时白名单（空列表 = 不过滤）
    # 默认建议值（来自 backtest profile 分析）
    # 排除：01, 02（亚洲深夜低流动）
    # 排除：11（欧洲午休前）
    # 排除：13（欧洲午休）
    # 排除：17, 18（美欧交接）
    allowed_hours_utc: List[int] = field(default_factory=lambda: [
        0, 3, 4, 5, 6, 7, 8, 9, 10,
        12, 14, 15, 16,
        19, 20, 21, 22, 23
    ])
    
    # 日志级别
    log_level: int = logging.DEBUG
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeWindowFilterConfig":
        """从字典创建配置"""
        allowed_hours = data.get("allowed_hours_utc", data.get("allowed_entry_hours", []))
        if not isinstance(allowed_hours, list):
            allowed_hours = []
            
        return cls(
            enabled=data.get("enabled", False),
            timezone=str(data.get("timezone", "UTC")),
            allowed_hours_utc=[int(h) for h in allowed_hours if isinstance(h, (int, float))],
        )


class TimeWindowFilter:
    """
    时间窗口过滤器
    
    功能：
    1. 检查当前时间是否在允许交易的时段内
    2. 支持按交易对设置不同的时间窗口
    3. 支持特殊时段警告
    """
    
    # 特殊时段定义（UTC）
    SPECIAL_WINDOWS = {
        "asia_low_liquidity": [1, 2],  # 亚洲深夜低流动
        "europe_lunch": [11, 13],  # 欧洲午休
        "us_eu_handover": [17, 18],  # 美欧交接
        "asia_open": [0, 1, 2, 3],  # 亚洲开盘
        "europe_open": [7, 8, 9, 10],  # 欧洲开盘
        "us_open": [13, 14, 15, 16],  # 美国开盘
        "us_close": [20, 21, 22, 23],  # 美国收盘
    }
    
    def __init__(self, config: TimeWindowFilterConfig = None):
        self.config = config or TimeWindowFilterConfig()
        self.logger = logging.getLogger("TimeWindowFilter")
        self.logger.setLevel(self.config.log_level)
        
        # 统计信息
        self._stats = {
            "total_checks": 0,
            "allowed": 0,
            "rejected": 0,
            "skipped_disabled": 0,
            "skipped_empty_whitelist": 0,
        }
        
        # 按小时统计拒绝
        self._hourly_rejections: Dict[int, int] = {}
    
    def should_allow_entry(
        self,
        timestamp: Optional[datetime] = None,
        symbol: str = "",
    ) -> Tuple[bool, str]:
        """
        检查是否允许入场
        
        Args:
            timestamp: 时间戳（None = 当前时间）
            symbol: 交易对（用于日志）
            
        Returns:
            (是否允许, 原因)
        """
        self._stats["total_checks"] += 1
        
        # 检查是否启用
        if not self.config.enabled:
            self._stats["skipped_disabled"] += 1
            return True, ""
        
        # 空白名单 = 不过滤
        if not self.config.allowed_hours_utc:
            self._stats["skipped_empty_whitelist"] += 1
            return True, ""
        
        # 获取 UTC 时间
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        utc_hour = timestamp.astimezone(timezone.utc).hour
        
        # 检查是否在白名单中
        if utc_hour not in self.config.allowed_hours_utc:
            self._stats["rejected"] += 1
            self._hourly_rejections[utc_hour] = self._hourly_rejections.get(utc_hour, 0) + 1
            
            reason = self._get_rejection_reason(utc_hour, symbol)
            self.logger.debug(reason)
            return False, reason
        
        self._stats["allowed"] += 1
        return True, ""
    
    def _get_rejection_reason(self, utc_hour: int, symbol: str) -> str:
        """获取拒绝原因"""
        # 检查是否属于特殊时段
        for window_name, hours in self.SPECIAL_WINDOWS.items():
            if utc_hour in hours:
                return (
                    f"[{symbol}] 当前 UTC {utc_hour}:00 "
                    f"属于 {window_name} 时段，跳过入场"
                )
        
        return (
            f"[{symbol}] 当前 UTC {utc_hour}:00 "
            f"不在允许交易窗口内，跳过入场"
        )
    
    def get_current_window_info(self, timestamp: Optional[datetime] = None) -> Dict[str, Any]:
        """
        获取当前时间窗口信息
        
        Returns:
            {
                "utc_hour": int,
                "is_allowed": bool,
                "special_windows": List[str],
            }
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        utc_hour = timestamp.astimezone(timezone.utc).hour
        
        # 检查所属的特殊时段
        special_windows = []
        for window_name, hours in self.SPECIAL_WINDOWS.items():
            if utc_hour in hours:
                special_windows.append(window_name)
        
        return {
            "utc_hour": utc_hour,
            "is_allowed": utc_hour in self.config.allowed_hours_utc,
            "special_windows": special_windows,
        }
    
    def get_next_allowed_hour(self, timestamp: Optional[datetime] = None) -> Optional[int]:
        """
        获取下一个允许交易的小时
        
        Returns:
            下一个允许的小时（UTC），如果当天没有则返回 None
        """
        if not self.config.allowed_hours_utc:
            return None
        
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        utc_hour = timestamp.astimezone(timezone.utc).hour
        
        # 找下一个允许的小时
        for h in sorted(self.config.allowed_hours_utc):
            if h > utc_hour:
                return h
        
        # 当天没有，返回明天的第一个
        return min(self.config.allowed_hours_utc) if self.config.allowed_hours_utc else None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "hourly_rejections": self._hourly_rejections.copy(),
        }
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        for key in self._stats:
            self._stats[key] = 0
        self._hourly_rejections.clear()


def check_time_window(
    timestamp: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
    symbol: str = "",
) -> Tuple[bool, str]:
    """
    便捷函数：检查时间窗口
    
    Args:
        timestamp: 时间戳
        config: 配置字典
        symbol: 交易对
        
    Returns:
        (是否允许, 原因)
    """
    cfg = TimeWindowFilterConfig.from_dict(config or {})
    filter_ = TimeWindowFilter(cfg)
    return filter_.should_allow_entry(timestamp=timestamp, symbol=symbol)
