from __future__ import annotations

from typing import Any

from chia.consensus.default_constants import update_testnet_overrides


def test_testnet11() -> None:
    overrides: dict[str, Any] = {}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {"MIN_PLOT_SIZE_V2": 18}


def test_min_plot_size() -> None:
    overrides: dict[str, Any] = {"MIN_PLOT_SIZE": 18}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {"MIN_PLOT_SIZE_V1": 18, "MIN_PLOT_SIZE_V2": 18}


def test_max_plot_size() -> None:
    overrides: dict[str, Any] = {"MAX_PLOT_SIZE": 32}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {"MAX_PLOT_SIZE_V1": 32, "MIN_PLOT_SIZE_V2": 18}


def test_mainnet() -> None:
    overrides: dict[str, Any] = {}
    update_testnet_overrides("mainnet", overrides)
    assert overrides == {}
