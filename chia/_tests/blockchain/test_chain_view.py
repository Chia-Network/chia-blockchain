from __future__ import annotations

import pytest
from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32

from chia.consensus.chain_view import ChainView, StaleChainViewError


def block_hash(height: int, fork: int = 0) -> bytes32:
    return bytes32(height.to_bytes(16, "big") + fork.to_bytes(16, "big"))


def make_ses(height: int) -> SubEpochSummary:
    return SubEpochSummary(block_hash(height), block_hash(height), uint8(0), None, None, None)


class FakeChainIndex:
    """A mutable main chain: heights 0..peak, plus sub-epoch summaries."""

    def __init__(self, peak_height: int, ses_heights: list[int]) -> None:
        self.hashes: dict[uint32, bytes32] = {uint32(h): block_hash(h) for h in range(peak_height + 1)}
        self.summaries: dict[uint32, SubEpochSummary] = {uint32(h): make_ses(h) for h in ses_heights}

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        return self.hashes.get(height)

    def get_ses_heights(self) -> list[uint32]:
        return sorted(self.summaries.keys())

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self.summaries[height]

    def reorg(self, fork_height: int, new_peak_height: int) -> None:
        """Replace everything above fork_height with a different chain."""
        self.hashes = {h: hh for h, hh in self.hashes.items() if h <= fork_height}
        for h in range(fork_height + 1, new_peak_height + 1):
            self.hashes[uint32(h)] = block_hash(h, fork=1)
        self.summaries = {h: s for h, s in self.summaries.items() if h <= fork_height}


def test_pin_requires_main_chain_membership() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])

    assert ChainView.pin(chain, block_hash(80), uint32(80)) is not None
    # wrong hash at that height
    assert ChainView.pin(chain, block_hash(80, fork=1), uint32(80)) is None
    # height beyond the chain
    assert ChainView.pin(chain, block_hash(200), uint32(200)) is None


def test_reads_resolve_through_the_pin() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])
    view = ChainView.pin(chain, block_hash(80), uint32(80))
    assert view is not None

    assert view.height_to_hash(uint32(50)) == block_hash(50)
    # ses heights are scoped to the pinned height
    assert view.get_ses_heights() == [uint32(10), uint32(50)]
    assert view.get_ses(uint32(50)) == make_ses(50)
    with pytest.raises(KeyError):
        view.get_ses(uint32(90))
    # reads above the pin resolve through the live chain (descendants of the pin)
    assert view.height_to_hash(uint32(90)) == block_hash(90)
    assert view.height_to_hash(uint32(200)) is None


def test_chain_extension_does_not_invalidate() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])
    view = ChainView.pin(chain, block_hash(100), uint32(100))
    assert view is not None

    chain.hashes[uint32(101)] = block_hash(101)
    assert view.height_to_hash(uint32(100)) == block_hash(100)
    assert view.height_to_hash(uint32(101)) == block_hash(101)


def test_reorg_above_pin_does_not_invalidate() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])
    view = ChainView.pin(chain, block_hash(80), uint32(80))
    assert view is not None

    chain.reorg(fork_height=90, new_peak_height=105)
    assert view.height_to_hash(uint32(80)) == block_hash(80)
    assert view.height_to_hash(uint32(95)) == block_hash(95, fork=1)


def test_reorg_of_pinned_block_raises() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])
    view = ChainView.pin(chain, block_hash(80), uint32(80))
    assert view is not None

    chain.reorg(fork_height=70, new_peak_height=105)
    with pytest.raises(StaleChainViewError):
        view.height_to_hash(uint32(50))
    with pytest.raises(StaleChainViewError):
        view.get_ses_heights()
    with pytest.raises(StaleChainViewError):
        view.get_ses(uint32(50))


def test_rollback_below_pin_raises() -> None:
    chain = FakeChainIndex(peak_height=100, ses_heights=[10, 50, 90])
    view = ChainView.pin(chain, block_hash(80), uint32(80))
    assert view is not None

    chain.reorg(fork_height=60, new_peak_height=60)
    with pytest.raises(StaleChainViewError):
        view.height_to_hash(uint32(50))
