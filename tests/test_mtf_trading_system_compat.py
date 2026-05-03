from src.fund_flow import mtf_trading_system


def test_mtf_trading_system_keeps_legacy_layer_exports() -> None:
    assert mtf_trading_system.MacroLayer is mtf_trading_system.MacroLayer4H
    assert mtf_trading_system.CoreLayer is mtf_trading_system.CoreLayer1H
    assert mtf_trading_system.MicroLayer is mtf_trading_system.MicroLayer15m


def test_create_mtf_system_uses_legacy_layer_exports() -> None:
    system = mtf_trading_system.create_mtf_system()

    assert isinstance(system.macro_layer, mtf_trading_system.MacroLayer4H)
    assert isinstance(system.core_layer, mtf_trading_system.CoreLayer1H)
    assert isinstance(system.micro_layer, mtf_trading_system.MicroLayer15m)
