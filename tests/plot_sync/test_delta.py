import logging

import pytest
from blspy import G1Element

from chia.plot_sync.delta import Delta, PathListDelta, PlotListDelta
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
def test_list_delta(delta) -> None:
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
    else:
        delta.additions["0"] = dummy_plot("0")
    assert not delta.empty()
    delta.removals.append("0")
    assert not delta.empty()
    delta.additions.clear()
    assert not delta.empty()
    delta.clear()
    assert delta.empty()


def test_path_list_delta_from_lists() -> None:
    delta: PathListDelta
    assert PathListDelta.from_lists([], []).empty()
    delta = PathListDelta.from_lists(["1"], ["0"])
    assert delta.additions == ["0"]
    assert delta.removals == ["1"]
    delta = PathListDelta.from_lists(["1", "2", "3"], ["1", "2", "3"])
    assert delta.additions == []
    assert delta.removals == []
    delta = PathListDelta.from_lists(["1", "2"], ["1", "2", "3"])
    assert delta.additions == ["3"]
    assert delta.removals == []
    delta = PathListDelta.from_lists(["1"], ["1", "2", "3"])
    assert delta.additions == ["2", "3"]
    assert delta.removals == []
    delta = PathListDelta.from_lists([], ["1", "2", "3"])
    assert delta.additions == ["1", "2", "3"]
    assert delta.removals == []
    delta = PathListDelta.from_lists(["-1"], ["1", "2", "3"])
    assert delta.additions == ["1", "2", "3"]
    assert delta.removals == ["-1"]
    delta = PathListDelta.from_lists(["-1", "1"], ["2", "3"])
    assert delta.additions == ["2", "3"]
    assert delta.removals == ["-1", "1"]
    delta = PathListDelta.from_lists(["-1", "1", "2"], ["2", "3"])
    assert delta.additions == ["3"]
    assert delta.removals == ["-1", "1"]


def test_delta() -> None:
    delta: Delta = Delta()
    assert delta.empty()
    for d in [delta.valid, delta.invalid, delta.keys_missing]:
        if type(d) == PlotListDelta:
            d.additions["0"] = dummy_plot("0")
        else:
            d.additions.append("0")
        assert not delta.empty()
        d.clear()
        assert delta.empty()
    delta.valid.additions["0"] = dummy_plot("0")
    delta.invalid.additions.append("0")
    delta.keys_missing.additions.append("0")
    assert not delta.empty()
    delta.valid.clear()
    assert not delta.empty()
    delta.invalid.clear()
    assert not delta.empty()
    delta.keys_missing.clear()
    assert delta.empty()
