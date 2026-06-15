from __future__ import annotations

from typing import Any

from chia.consensus.default_constants import update_testnet_overrides


def test_testnet11() -> None:
    overrides: dict[str, Any] = {}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {
        "TESTNET": True,
        "PLOT_SIZE_V2": 28,
        "SOFT_FORK8_HEIGHT": 3755000,
        "SOFT_FORK9_HEIGHT": 3924000,
    }


def test_min_plot_size() -> None:
    overrides: dict[str, Any] = {"MIN_PLOT_SIZE": 18}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {
        "TESTNET": True,
        "MIN_PLOT_SIZE": 18,
        "PLOT_SIZE_V2": 28,
        "SOFT_FORK8_HEIGHT": 3755000,
        "SOFT_FORK9_HEIGHT": 3924000,
    }


def test_max_plot_size() -> None:
    overrides: dict[str, Any] = {"MAX_PLOT_SIZE": 32}
    update_testnet_overrides("testnet11", overrides)
    assert overrides == {
        "TESTNET": True,
        "MAX_PLOT_SIZE": 32,
        "PLOT_SIZE_V2": 28,
        "SOFT_FORK8_HEIGHT": 3755000,
        "SOFT_FORK9_HEIGHT": 3924000,
    }


def test_testneta() -> None:
    overrides: dict[str, Any] = {}
    update_testnet_overrides("testneta", overrides)
    assert overrides == {
        "TESTNET": True,
        "MIN_PLOT_SIZE_V1": 18,
        "PLOT_SIZE_V2": 28,
        "SOFT_FORK8_HEIGHT": 3755000,
        "SOFT_FORK9_HEIGHT": 3924000,
        "HARD_FORK_HEIGHT": 3693395,
    }


def test_mainnet() -> None:
    overrides: dict[str, Any] = {}
    update_testnet_overrides("mainnet", overrides)
    assert overrides == {}
