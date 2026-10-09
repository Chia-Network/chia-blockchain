from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from chia_rs import SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class StaleChainViewError(Exception):
    """The block a ChainView was pinned to is no longer on the main chain."""


class ChainIndexProtocol(Protocol):
    """The synchronous chain-index read surface a ChainView is built over.

    Answers questions about the current main chain: which block is at
    height N, and which heights included sub-epoch summaries. Blockchain
    satisfies this protocol (backed by BlockHeightMap today).
    """

    def height_to_hash(self, height: uint32) -> bytes32 | None: ...
    def get_ses_heights(self) -> list[uint32]: ...
    def get_ses(self, height: uint32) -> SubEpochSummary: ...


@dataclass(frozen=True)
class ChainView:
    """Chain-index reads pinned to one specific block (the view's peak).

    "The block at height N" is ambiguous on its own -- the answer depends on
    which chain you are on, and it can change under a caller that interleaves
    reads with awaits. A ChainView makes the chain explicit: height N
    resolves to the ancestor of THIS peak at height N.

    For as long as the pinned block remains on the main chain:

    - reads at heights <= the pinned height return the ancestors of the
      pinned block, unaffected by the chain advancing or reorging above the
      pin (a chain passing through the pinned block at its height has
      exactly one possible ancestry below it);
    - reads above the pinned height resolve through the live main chain,
      which necessarily passes through the pinned block, so they return
      descendants of the pin -- but they may change between reads as the
      chain advances.

    If the pinned block is reorged off the main chain, every subsequent read
    raises StaleChainViewError instead of silently answering from a
    different chain. A long height walk that pins once at the start either
    completes against a single coherent chain or fails loudly.

    The pin re-check and the read are both synchronous, so they are atomic
    with respect to the event loop; the underlying map only mutates in the
    synchronous peak-update sections of Blockchain.add_block.
    """

    source: ChainIndexProtocol
    peak_header_hash: bytes32
    peak_height: uint32

    @classmethod
    def pin(cls, source: ChainIndexProtocol, peak_header_hash: bytes32, peak_height: uint32) -> ChainView | None:
        """Pin a view to the given block, or None if it is not on the main chain."""
        if source.height_to_hash(peak_height) != peak_header_hash:
            return None
        return cls(source, peak_header_hash, peak_height)

    def _check_pin(self) -> None:
        if self.source.height_to_hash(self.peak_height) != self.peak_header_hash:
            raise StaleChainViewError(
                f"block {self.peak_header_hash.hex()} at height {self.peak_height} is no longer on the main chain"
            )

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        self._check_pin()
        return self.source.height_to_hash(height)

    def get_ses_heights(self) -> list[uint32]:
        """Sub-epoch summary heights up to and including the pinned height."""
        self._check_pin()
        return [h for h in self.source.get_ses_heights() if h <= self.peak_height]

    def get_ses(self, height: uint32) -> SubEpochSummary:
        self._check_pin()
        if height > self.peak_height:
            raise KeyError(height)
        return self.source.get_ses(height)
