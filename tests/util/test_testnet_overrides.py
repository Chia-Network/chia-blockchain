from __future__ import annotations

from typing import Any, Dict

from chia.server.start_full_node import update_testnet_overrides


def test_testnet10() -> None:
    overrides: Dict[str, Any] = {}
    update_testnet_overrides("testnet10", overrides)
    assert overrides == {
        "SOFT_FORK2_HEIGHT": 0,
        "SOFT_FORK3_HEIGHT": 2960728,
        "HARD_FORK_HEIGHT": 2997292,
        "PLOT_FILTER_128_HEIGHT": 3061804,
        "PLOT_FILTER_64_HEIGHT": 8010796,
        "PLOT_FILTER_32_HEIGHT": 13056556,
    }


def test_testnet10_existing() -> None:
    overrides: Dict[str, Any] = {
        "SOFT_FORK2_HEIGHT": 42,
        "SOFT_FORK3_HEIGHT": 42,
        "HARD_FORK_HEIGHT": 42,
        "PLOT_FILTER_128_HEIGHT": 42,
        "PLOT_FILTER_64_HEIGHT": 42,
        "PLOT_FILTER_32_HEIGHT": 42,
    }
    update_testnet_overrides("testnet10", overrides)
    assert overrides == {
        "SOFT_FORK2_HEIGHT": 42,
        "SOFT_FORK3_HEIGHT": 42,
        "HARD_FORK_HEIGHT": 42,
        "PLOT_FILTER_128_HEIGHT": 42,
        "PLOT_FILTER_64_HEIGHT": 42,
        "PLOT_FILTER_32_HEIGHT": 42,
    }


def test_mainnet() -> None:
    overrides: Dict[str, Any] = {}
    update_testnet_overrides("mainnet", overrides)
    assert overrides == {}
