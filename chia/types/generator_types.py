from __future__ import annotations

from dataclasses import dataclass, field

from chia_rs import Coin, G2Element
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.util.streamable import Streamable, streamable


# This holds what we need to pre validate a block generator
@streamable
@dataclass(frozen=True)
class BlockGenerator(Streamable):
    program: SerializedProgram = field(default_factory=SerializedProgram.default)
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
