from __future__ import annotations

from typing import List

import pytest

benchmark_runner_fixture_name = "benchmark_runner"
benchmark_marker_name = "benchmark"
enable_benchmark_assertions_flag_name = "--enable-benchmark-assertions"


def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    group = parser.getgroup("Chia tests")
    group.addoption(
        enable_benchmark_assertions_flag_name,
        action="store_true",
        help="enable benchmarking assertions (does not select benchmark tests)",
    )


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: List[pytest.Item]) -> None:
    for item in items:
        if benchmark_runner_fixture_name in getattr(item, "fixturenames", ()):
            item.add_marker(benchmark_marker_name)
