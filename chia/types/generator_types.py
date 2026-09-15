from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from chia_rs import Coin, G2Element
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.util.streamable import Streamable, streamable, streamable_enum


# The two encodings a block generator's bytes can be in. Values mirror the
# wire-version convention already used for FullBlock/UnfinishedBlock.version
# (see chia/consensus/block_creation.py): 0 for pre-HF2 blocks, 1 for post-HF2.
@streamable_enum(uint8)
class GeneratorFormat(IntEnum):
    CLASSIC = 0
    SERDE_2026 = 1


# This holds what we need to pre validate a block generator
@streamable
@dataclass(frozen=True)
class BlockGenerator(Streamable):
    program: bytes
    # the encoding of `program` above. There's no reasonable default here:
    # the caller always knows which encoding it built or read, and picking
    # one implicitly would silently assume classic CLVM.
    format: GeneratorFormat
    # to run the block generator, we need the actual bytes of the previous
    # generators it may reference. These are parameters passed in to the block
    # generator
    generator_refs: list[bytes] = field(default_factory=list)


# When we create a new block, this object holds the block generator and
# additional information we need to create the UnfinishedBlock from it.
# When creating a block, we still need to be able to run it, to compute its cost
# and validate it. Therefore, this is a superset of the BlockGenerator class.
@dataclass(frozen=True)
class NewBlockGenerator(BlockGenerator):
    # when creating a block, we include the block heights of the generators we
    # reference. Tese are block heights and generator_refs contain the
    # corresponding bytes of the generator programs
    block_refs: list[uint32] = field(default_factory=list)
    # the aggregate signature of all AGG_SIG_* conditions returned by the block
    # generator.
    signature: G2Element = G2Element()
    # all CREATE_COIN outputs created by the block generator
    additions: list[Coin] = field(default_factory=list)
    # all coins being spent by the block generator
    removals: list[Coin] = field(default_factory=list)
    # the total cost of the block generator, CLVM + bytes + conditions
    cost: uint64 = field(default=uint64(0))
