from __future__ import annotations

import logging
from typing import List

import pytest
from blspy import G1Element

from chia.plot_sync.delta import Delta, DeltaType, PathListDelta, PlotListDelta
from chia.protocols.harvester_protocol import Plot
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint64

log = logging.getLogger(__name__)


def dummy_plot(path: str) -> Plot:
    return Plot(path, uint8(32), bytes32(b"\00" * 32), G1Element(), None, G1Element(), uint64(0), uint64(0))


@pytest.mark.parametrize(
    ["delta"],
    [
        pytest.param(PathListDelta(), id="path list"),
        pytest.param(PlotListDelta(), id="plot list"),
    ],
)
def test_list_delta(delta: DeltaType) -> None:
    assert delta.empty()
    if type(delta) == PathListDelta:
        assert delta.additions == []
    elif type(delta) == PlotListDelta:
        assert delta.additions == {}
    else:
        assert False
    assert delta.removals == []
    assert delta.empty()
    if type(delta) == PathListDelta:
        delta.additions.append("0")
    elif type(delta) == PlotListDelta:
        delta.additions["0"] = dummy_plot("0")
    else:
        assert False, "Invalid delta type"
    assert not delta.empty()
    delta.removals.append("0")
    assert not delta.empty()
    delta.additions.clear()
    assert not delta.empty()
    delta.clear()
    assert delta.empty()


@pytest.mark.parametrize(
    ["old", "new", "result"],
    [
        [[], [], PathListDelta()],
        [["1"], ["0"], PathListDelta(["0"], ["1"])],
        [["1", "2", "3"], ["1", "2", "3"], PathListDelta([], [])],
        [["2", "1", "3"], ["2", "3", "1"], PathListDelta([], [])],
        [["2"], ["2", "3", "1"], PathListDelta(["3", "1"], [])],
        [["2"], ["1", "3"], PathListDelta(["1", "3"], ["2"])],
        [["1"], ["1", "2", "3"], PathListDelta(["2", "3"], [])],
        [[], ["1", "2", "3"], PathListDelta(["1", "2", "3"], [])],
        [["-1"], ["1", "2", "3"], PathListDelta(["1", "2", "3"], ["-1"])],
        [["-1", "1"], ["2", "3"], PathListDelta(["2", "3"], ["-1", "1"])],
        [["-1", "1", "2"], ["2", "3"], PathListDelta(["3"], ["-1", "1"])],
        [["-1", "2", "3"], ["2", "3"], PathListDelta([], ["-1"])],
        [["-1", "2", "3", "-2"], ["2", "3"], PathListDelta([], ["-1", "-2"])],
        [["-2", "2", "3", "-1"], ["2", "3"], PathListDelta([], ["-2", "-1"])],
    ],
)
def test_path_list_delta_from_lists(old: List[str], new: List[str], result: PathListDelta) -> None:
    assert PathListDelta.from_lists(old, new) == result


def test_delta_empty() -> None:
    delta: Delta = Delta()
    all_deltas: List[DeltaType] = [delta.valid, delta.invalid, delta.keys_missing, delta.duplicates]
    assert delta.empty()
    for d1 in all_deltas:
        delta.valid.additions["0"] = dummy_plot("0")
        delta.invalid.additions.append("0")
        delta.keys_missing.additions.append("0")
        delta.duplicates.additions.append("0")
        assert not delta.empty()
        for d2 in all_deltas:
            if d2 is not d1:
                d2.clear()
            assert not delta.empty()
        assert not delta.empty()
        d1.clear()
        assert delta.empty()
