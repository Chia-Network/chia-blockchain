from __future__ import annotations

from chia.util.service_groups import services_for_groups


def test_services_for_groups() -> None:
    i = 0
    for service in services_for_groups(["harvester"]):
        assert service == "chia_harvester"
        i += 1
    assert i == 1

    for _ in services_for_groups(["daemon"]):
        # The loop should never be run
        assert False  # pragma: no cover
