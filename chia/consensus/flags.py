"""Consensus flag helpers for testing INTERNED_GENERATOR activation."""

from __future__ import annotations

from chia_rs import ConsensusConstants, get_flags_for_height_and_constants

# ConsensusFlags::INTERNED_GENERATOR = 0x0800_0000
# Not yet wired in chia_rs get_flags_for_height_and_constants,
# but the run_block_generator code already supports it.
INTERNED_GENERATOR: int = 0x0800_0000


def get_flags_for_height_and_constants_interned(
    prev_tx_height: int,
    constants: ConsensusConstants,
) -> int:
    flags = get_flags_for_height_and_constants(prev_tx_height, constants)
    if prev_tx_height >= constants.HARD_FORK2_HEIGHT:
        flags |= INTERNED_GENERATOR
    return flags
