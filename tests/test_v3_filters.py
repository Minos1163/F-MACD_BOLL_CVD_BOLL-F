"""
V3策略过滤器测试

测试内容：
- 空头质量过滤器
- 赢家加仓机制
- 时间窗口过滤
- Symbol级信号Override
- 集成测试
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

# 导入被测试模块
from src.fund_flow.filters.short_quality_filter import (
    ShortQualityFilter,
    ShortQualityFilterConfig,
    check_short_quality,
)
from src.fund_flow.filters.winner_pyramiding import (
    WinnerPyramidingManager,
    WinnerPyramidingConfig,
    check_winner_pyramiding,
)
from src.fund_flow.filters.time_window_filter import (
    TimeWindowFilter,
    TimeWindowFilterConfig,
    check_time_window,
)
from src.fund_flow.filters.symbol_signal_override import (
    SymbolSignalOverrideRegistry,
    SymbolSignalOverride,
    create_override_registry,
)
from src.fund_flow.v3_filter_integration import (
    V3FilterManager,
    V3FilterResult,
)


class TestShortQualityFilter:
    """空头质量过滤器测试"""
    
    def test_disabled_filter(self):
        """测试：禁用时允许所有"""
        config = ShortQualityFilterConfig(enabled=False)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=None,
            oi_delta_ratio=None,
            price=100.0,
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is True
        assert reason == ""
    
    def test_not_flip_bearish(self):
        """测试：非 flip_bearish 信号直接通过"""
        config = ShortQualityFilterConfig(enabled=True)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="red_bar_growing",
            funding_rate=None,
            oi_delta_ratio=None,
            price=100.0,
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is True
    
    def test_missing_funding_rate(self):
        """测试：缺失 funding_rate 数据"""
        config = ShortQualityFilterConfig(enabled=True)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=None,
            oi_delta_ratio=-0.01,
            price=100.0,
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is False
        assert "funding_rate" in reason
    
    def test_low_funding_rate(self):
        """测试：funding_rate 低于阈值"""
        config = ShortQualityFilterConfig(enabled=True, min_funding_rate=0.0005)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=0.0001,  # 低于阈值
            oi_delta_ratio=-0.01,
            price=100.0,
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is False
        assert "funding_rate" in reason
    
    def test_positive_oi_delta(self):
        """测试：OI 增加（多头增仓）"""
        config = ShortQualityFilterConfig(enabled=True)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=0.001,
            oi_delta_ratio=0.01,  # OI 增加
            price=100.0,
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is False
        assert "oi_delta" in reason
    
    def test_price_below_vwap(self):
        """测试：价格低于 VWAP"""
        config = ShortQualityFilterConfig(enabled=True)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=0.001,
            oi_delta_ratio=-0.01,
            price=97.0,  # 低于 VWAP
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is False
        assert "vwap" in reason.lower()
    
    def test_all_conditions_pass(self):
        """测试：所有条件满足"""
        config = ShortQualityFilterConfig(enabled=True)
        filter_ = ShortQualityFilter(config)
        
        allowed, reason = filter_.should_allow(
            signal_type="flip_bearish",
            funding_rate=0.001,  # > 阈值
            oi_delta_ratio=-0.01,  # 负数
            price=100.0,  # > VWAP
            vwap=98.0,
            symbol="BTCUSDT",
        )
        
        assert allowed is True
        assert reason == ""


class TestWinnerPyramiding:
    """赢家加仓机制测试"""
    
    def test_disabled(self):
        """测试：禁用时不加仓"""
        config = WinnerPyramidingConfig(enabled=False)
        manager = WinnerPyramidingManager(config)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.01,
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is False
        assert "未启用" in reason
    
    def test_short_position(self):
        """测试：空头不加仓"""
        config = WinnerPyramidingConfig(enabled=True)
        manager = WinnerPyramidingManager(config)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.01,
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="short",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is False
        assert "多头" in reason
    
    def test_insufficient_profit(self):
        """测试：浮盈不足"""
        config = WinnerPyramidingConfig(enabled=True, min_unrealized_pnl_pct=0.003)
        manager = WinnerPyramidingManager(config)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.001,  # 低于阈值
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is False
        assert "浮盈" in reason
    
    def test_wrong_signal_type(self):
        """测试：信号类型不匹配"""
        config = WinnerPyramidingConfig(enabled=True, require_signal_type="red_bar_growing")
        manager = WinnerPyramidingManager(config)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.01,
            signal_type_1h="flip_bullish",  # 不匹配
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is False
        assert "信号" in reason
    
    def test_max_additions_reached(self):
        """测试：达到最大加仓次数"""
        config = WinnerPyramidingConfig(enabled=True, max_additions=1)
        manager = WinnerPyramidingManager(config)
        
        # 记录一次加仓
        manager.record_addition("BTCUSDT", 0.005, 100.0, 0.90, 0.15, 0.01)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.01,
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is False
        assert "最大加仓次数" in reason
    
    def test_all_conditions_pass(self):
        """测试：所有条件满足"""
        config = WinnerPyramidingConfig(
            enabled=True,
            min_unrealized_pnl_pct=0.003,
            require_signal_type="red_bar_growing",
            allowed_ema_structures=["strong", "normal"],
            min_vwap_score=0.10,
            min_signal_score=0.85,
            max_additions=1,
            addition_ratio=0.50,
        )
        manager = WinnerPyramidingManager(config)
        
        allowed, reason, size = manager.should_add(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.005,  # > 0.003
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,  # > 0.10
            signal_score=0.90,  # > 0.85
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert allowed is True
        assert size == 0.005  # 0.01 * 0.5


class TestTimeWindowFilter:
    """时间窗口过滤器测试"""
    
    def test_disabled(self):
        """测试：禁用时允许所有"""
        config = TimeWindowFilterConfig(enabled=False)
        filter_ = TimeWindowFilter(config)
        
        # 任意时间都允许
        for hour in range(24):
            ts = datetime(2026, 3, 19, hour, 0, tzinfo=timezone.utc)
            allowed, reason = filter_.should_allow_entry(ts, "BTCUSDT")
            assert allowed is True
    
    def test_empty_whitelist(self):
        """测试：空白名单允许所有"""
        config = TimeWindowFilterConfig(enabled=True, allowed_hours_utc=[])
        filter_ = TimeWindowFilter(config)
        
        ts = datetime(2026, 3, 19, 1, 0, tzinfo=timezone.utc)
        allowed, reason = filter_.should_allow_entry(ts, "BTCUSDT")
        
        assert allowed is True
    
    def test_allowed_hour(self):
        """测试：允许的小时"""
        config = TimeWindowFilterConfig(enabled=True, allowed_hours_utc=[8, 9, 10])
        filter_ = TimeWindowFilter(config)
        
        ts = datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc)
        allowed, reason = filter_.should_allow_entry(ts, "BTCUSDT")
        
        assert allowed is True
    
    def test_blocked_hour(self):
        """测试：禁止的小时"""
        config = TimeWindowFilterConfig(enabled=True, allowed_hours_utc=[8, 9, 10])
        filter_ = TimeWindowFilter(config)
        
        ts = datetime(2026, 3, 19, 1, 0, tzinfo=timezone.utc)  # 亚洲深夜
        allowed, reason = filter_.should_allow_entry(ts, "BTCUSDT")
        
        assert allowed is False
        assert "UTC" in reason
    
    def test_special_window_detection(self):
        """测试：特殊时段检测"""
        config = TimeWindowFilterConfig(enabled=True, allowed_hours_utc=list(range(24)))
        filter_ = TimeWindowFilter(config)
        
        # 亚洲深夜
        ts = datetime(2026, 3, 19, 1, 0, tzinfo=timezone.utc)
        info = filter_.get_current_window_info(ts)
        assert "asia_low_liquidity" in info["special_windows"]
        
        # 欧洲开盘
        ts = datetime(2026, 3, 19, 8, 0, tzinfo=timezone.utc)
        info = filter_.get_current_window_info(ts)
        assert "europe_open" in info["special_windows"]


class TestSymbolSignalOverride:
    """Symbol 级信号 Override 测试"""
    
    def test_global_config_fallback(self):
        """测试：无覆盖时使用全局配置"""
        registry = SymbolSignalOverrideRegistry(
            overrides=[],
            global_config={"disable_flip_bullish_entries": True},
        )
        
        assert registry.is_signal_disabled("BTCUSDT", "flip_bullish") is True
    
    def test_symbol_override(self):
        """测试：symbol 级覆盖"""
        registry = SymbolSignalOverrideRegistry(
            overrides=[
                {"symbol": "ATOMUSDT", "disable_flip_bullish": False}
            ],
            global_config={"disable_flip_bullish_entries": True},
        )
        
        # 全局禁用
        assert registry.is_signal_disabled("BTCUSDT", "flip_bullish") is True
        
        # ATOM 覆盖为允许
        assert registry.is_signal_disabled("ATOMUSDT", "flip_bullish") is False
    
    def test_min_signal_score_override(self):
        """测试：评分门槛覆盖"""
        registry = SymbolSignalOverrideRegistry(
            overrides=[
                {"symbol": "SOLUSDT", "min_signal_score_override": 0.90}
            ],
            global_config={"min_signal_score": 0.85},
        )
        
        assert registry.get_min_signal_score("BTCUSDT") == 0.85
        assert registry.get_min_signal_score("SOLUSDT") == 0.90
    
    def test_register_and_unregister(self):
        """测试：注册和移除覆盖"""
        registry = SymbolSignalOverrideRegistry()
        
        # 注册
        override = SymbolSignalOverride(symbol="XRPUSDT", disable_flip_bullish=False)
        registry.register_override(override)
        
        assert registry.is_signal_disabled("XRPUSDT", "flip_bullish") is False
        
        # 移除
        registry.unregister_override("XRPUSDT")
        assert registry.get_override("XRPUSDT") is None

    def test_registry_normalizes_symbol_and_ignores_invalid_items(self):
        """测试：registry 规范化 symbol 并忽略无效 list 项"""
        registry = SymbolSignalOverrideRegistry(
            overrides=[
                {"symbol": "solusdt", "disable_flip_bullish": False},
                {"_comment": "invalid example item without symbol"},
                "bad-item",
            ],
            global_config={"disable_flip_bullish_entries": True},
        )

        assert registry.is_signal_disabled("SOLUSDT", "flip_bullish") is False
        assert registry.is_signal_disabled("BTCUSDT", "flip_bullish") is True

    def test_create_override_registry_reads_entry_threshold_fallback(self):
        """测试：create_override_registry 可回退到 entry_thresholds.min_signal_score"""
        registry = create_override_registry(
            {
                "fund_flow": {
                    "macd_mtf_strategy_v2": {
                        "entry_thresholds": {"min_signal_score": 0.86},
                        "entry_filters": {
                            "symbol_signal_overrides": [
                                {
                                    "symbol": "ATOMUSDT",
                                    "disable_flip_bullish": False,
                                }
                            ]
                        },
                    }
                }
            }
        )

        assert registry.get_min_signal_score("BTCUSDT") == 0.86
        assert registry.is_signal_disabled("ATOMUSDT", "flip_bullish") is False


class TestV3FilterManager:
    """V3 过滤器管理器集成测试"""
    
    @pytest.fixture
    def config(self):
        """测试配置"""
        return {
            "fund_flow": {
                "allowed_entry_hours_utc": [8, 9, 10, 14, 15, 16, 20, 21, 22],
                "winner_pyramiding": {
                    "enabled": True,
                    "min_unrealized_pnl_ratio": 0.003,
                    "min_signal_score": 0.85,
                    "min_vwap_score": 0.10,
                    "max_additions": 1,
                    "base_add_portion": 0.5,
                    "signal_types": ["red_bar_growing"],
                    "ema_structure_status": ["strong", "normal"],
                },
                "macd_mtf_strategy_v2": {
                    "entry_filters": {
                        "disable_flip_bullish_entries": True,
                        "disable_green_bar_growing_entries": True,
                        "min_signal_score": 0.85,
                        "symbol_signal_overrides": [
                            {
                                "symbol": "ATOMUSDT",
                                "disable_flip_bullish": False,
                                "min_signal_score_override": 0.88,
                            }
                        ],
                    },
                    "short_quality_filter": {
                        "enabled": True,
                        "min_funding_rate": 0.0005,
                        "max_oi_delta_ratio": 0.0,
                        "min_vwap_deviation": 0.005,
                    },
                },
            }
        }
    
    def test_time_window_blocking(self, config):
        """测试：时间窗口阻止入场"""
        manager = V3FilterManager(config)
        
        # 禁止的小时
        ts = datetime(2026, 3, 19, 1, 0, tzinfo=timezone.utc)
        result = manager.check_entry(
            symbol="BTCUSDT",
            signal_type="red_bar_growing",
            direction="long",
            timestamp=ts,
            signal_score=0.90,
        )
        
        assert result.allowed is False
        assert result.filter_name == "time_window_filter"
    
    def test_signal_disabled(self, config):
        """测试：信号禁用"""
        manager = V3FilterManager(config)
        
        ts = datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc)
        result = manager.check_entry(
            symbol="BTCUSDT",
            signal_type="flip_bullish",  # 全局禁用
            direction="long",
            timestamp=ts,
            signal_score=0.90,
        )
        
        assert result.allowed is False
        assert result.filter_name == "signal_override"
    
    def test_symbol_override_enabled(self, config):
        """测试：symbol 级覆盖启用信号"""
        manager = V3FilterManager(config)
        
        ts = datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc)
        result = manager.check_entry(
            symbol="ATOMUSDT",  # 覆盖为允许
            signal_type="flip_bullish",
            direction="long",
            timestamp=ts,
            signal_score=0.90,  # > 0.88
        )
        
        assert result.allowed is True
    
    def test_short_quality_filter(self, config):
        """测试：空头质量过滤"""
        manager = V3FilterManager(config)
        
        ts = datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc)
        result = manager.check_entry(
            symbol="BTCUSDT",
            signal_type="flip_bearish",
            direction="short",
            timestamp=ts,
            funding_rate=0.0001,  # 低于阈值
            oi_delta_ratio=-0.01,
            price=100.0,
            vwap=98.0,
            signal_score=0.90,
        )
        
        assert result.allowed is False
        assert result.filter_name == "short_quality_filter"
    
    def test_winner_pyramiding(self, config):
        """测试：赢家加仓"""
        manager = V3FilterManager(config)
        
        result = manager.check_addition(
            symbol="BTCUSDT",
            unrealized_pnl_pct=0.005,
            signal_type_1h="red_bar_growing",
            ema_structure="strong",
            vwap_score=0.15,
            signal_score=0.90,
            position_side="long",
            current_position_size=0.01,
            max_allowed_size=0.05,
            initial_size=0.01,
        )
        
        assert result.allowed is True
        assert result.details["addition_size"] == 0.005


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
