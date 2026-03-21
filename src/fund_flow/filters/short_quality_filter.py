"""
Phase 3A: 空头质量过滤器

flip_bearish 独立前置过滤器，只在 1H 信号类型为 flip_bearish 时调用。
核心逻辑：
- Funding Rate 必须为正且超过阈值（多头付费持仓，做空更安全）
- OI Delta 必须为负（多头在减仓，资金在撤离）
- 价格在 VWAP 上方（有均值回归空间）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any
import logging


@dataclass
class ShortQualityFilterConfig:
    """空头质量过滤器配置"""
    enabled: bool = False
    
    # Funding Rate 阈值
    require_positive_funding: bool = True
    min_funding_rate: float = 0.0005  # 0.05%（年化约 54%）
    
    # OI Delta 阈值
    require_oi_delta_negative: bool = True
    max_oi_delta_ratio: float = 0.0  # 必须为负（多头减仓）
    
    # VWAP 位置
    require_price_above_vwap: bool = True
    min_price_vwap_ratio: float = 1.005  # 价格 > VWAP × 1.005
    min_vwap_deviation: float = 0.005  # 0.5% 偏离
    
    # 日志级别
    log_level: int = logging.DEBUG
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShortQualityFilterConfig":
        """从字典创建配置"""
        return cls(
            enabled=data.get("enabled", False),
            require_positive_funding=data.get("require_positive_funding", True),
            min_funding_rate=float(data.get("min_funding_rate", 0.0005)),
            require_oi_delta_negative=data.get("require_oi_delta_negative", True),
            max_oi_delta_ratio=float(data.get("max_oi_delta_ratio", 0.0)),
            require_price_above_vwap=data.get("require_price_above_vwap", True),
            min_price_vwap_ratio=float(data.get("min_price_vwap_ratio", 1.005)),
            min_vwap_deviation=float(data.get("min_vwap_deviation", 0.005)),
        )


class ShortQualityFilter:
    """
    flip_bearish 独立前置过滤器
    只在 1H 信号类型为 flip_bearish 时调用
    
    过滤逻辑：
    1. Funding Rate > 阈值：确认多头付费持仓
    2. OI Delta < 0：确认多头减仓
    3. 价格 > VWAP：确认有回归空间
    """
    
    def __init__(self, config: ShortQualityFilterConfig = None):
        self.config = config or ShortQualityFilterConfig()
        self.logger = logging.getLogger("ShortQualityFilter")
        self.logger.setLevel(self.config.log_level)
        
        # 统计信息
        self._stats = {
            "total_checks": 0,
            "passed": 0,
            "rejected_funding": 0,
            "rejected_oi": 0,
            "rejected_vwap": 0,
            "skipped_not_flip_bearish": 0,
            "skipped_disabled": 0,
            "skipped_missing_data": 0,
        }
    
    def should_allow(
        self,
        signal_type: str,
        funding_rate: Optional[float],
        oi_delta_ratio: Optional[float],
        price: float,
        vwap: float,
        symbol: str = "",
    ) -> Tuple[bool, str]:
        """
        判断是否允许空头入场
        
        Args:
            signal_type: 信号类型（只对 flip_bearish 生效）
            funding_rate: 当前 funding rate
            oi_delta_ratio: OI 变化率
            price: 当前价格
            vwap: 当前 VWAP
            symbol: 交易对（用于日志）
            
        Returns:
            (是否允许入场, 拒绝原因)
        """
        self._stats["total_checks"] += 1
        
        # 只对 flip_bearish 生效
        if signal_type != "flip_bearish":
            self._stats["skipped_not_flip_bearish"] += 1
            return True, ""
        
        # 检查是否启用
        if not self.config.enabled:
            self._stats["skipped_disabled"] += 1
            return True, ""
        
        # 条件1：Funding Rate 必须为正且超过阈值
        if self.config.require_positive_funding:
            if funding_rate is None:
                self._stats["skipped_missing_data"] += 1
                return False, f"[{symbol}] funding_rate 数据缺失，拒绝空头入场"
            
            if funding_rate <= self.config.min_funding_rate:
                self._stats["rejected_funding"] += 1
                reason = (
                    f"[{symbol}] funding_rate={funding_rate:.6f} "
                    f"未达到阈值 {self.config.min_funding_rate:.6f}"
                )
                self.logger.debug(reason)
                return False, reason
        
        # 条件2：OI Delta 必须为负（多头在减仓）
        if self.config.require_oi_delta_negative:
            if oi_delta_ratio is None:
                self._stats["skipped_missing_data"] += 1
                return False, f"[{symbol}] oi_delta_ratio 数据缺失，拒绝空头入场"
            
            if oi_delta_ratio >= self.config.max_oi_delta_ratio:
                self._stats["rejected_oi"] += 1
                reason = (
                    f"[{symbol}] oi_delta_ratio={oi_delta_ratio:.4f} >= 0，"
                    f"OI 未下降，空头质量不足"
                )
                self.logger.debug(reason)
                return False, reason
        
        # 条件3：价格在 VWAP 上方（有均值回归空间）
        if self.config.require_price_above_vwap:
            if vwap is None or vwap <= 0:
                self._stats["skipped_missing_data"] += 1
                return False, f"[{symbol}] VWAP 数据缺失，拒绝空头入场"
            
            price_vwap_ratio = price / vwap if vwap > 0 else 1.0
            vwap_deviation = (price - vwap) / vwap if vwap > 0 else 0.0
            
            if price_vwap_ratio < self.config.min_price_vwap_ratio:
                self._stats["rejected_vwap"] += 1
                reason = (
                    f"[{symbol}] price/vwap={price_vwap_ratio:.4f} "
                    f"< {self.config.min_price_vwap_ratio}，"
                    f"价格不够高，空头入场质量差"
                )
                self.logger.debug(reason)
                return False, reason
            
            if vwap_deviation < self.config.min_vwap_deviation:
                self._stats["rejected_vwap"] += 1
                reason = (
                    f"[{symbol}] vwap_deviation={vwap_deviation:.4f} "
                    f"< {self.config.min_vwap_deviation}，"
                    f"VWAP偏离不足，空头入场质量差"
                )
                self.logger.debug(reason)
                return False, reason
        
        # 所有条件满足
        self._stats["passed"] += 1
        self.logger.debug(f"[{symbol}] 空头质量过滤器通过")
        return True, ""
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        for key in self._stats:
            self._stats[key] = 0


def check_short_quality(
    signal_type: str,
    funding_rate: Optional[float],
    oi_delta_ratio: Optional[float],
    price: float,
    vwap: float,
    config: Optional[Dict[str, Any]] = None,
    symbol: str = "",
) -> Tuple[bool, str]:
    """
    便捷函数：检查空头质量
    
    Args:
        signal_type: 信号类型
        funding_rate: funding rate
        oi_delta_ratio: OI 变化率
        price: 当前价格
        vwap: VWAP
        config: 配置字典
        symbol: 交易对
        
    Returns:
        (是否允许, 原因)
    """
    cfg = ShortQualityFilterConfig.from_dict(config or {})
    filter_ = ShortQualityFilter(cfg)
    return filter_.should_allow(
        signal_type=signal_type,
        funding_rate=funding_rate,
        oi_delta_ratio=oi_delta_ratio,
        price=price,
        vwap=vwap,
        symbol=symbol,
    )
