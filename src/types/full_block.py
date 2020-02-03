from dataclasses import dataclass
from typing import Tuple, List, Optional

from src.types.name_puzzle_condition import NPC
from src.types.body import Body
from src.types.hashable.Coin import Coin
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ConsensusError import Err
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.util.consensus import created_outputs_for_conditions_dict
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable


def additions_for_npc(npc_list: List[NPC]) -> List[Coin]:
    additions: List[Coin] = []

    for npc in npc_list:
        for coin in created_outputs_for_conditions_dict(npc.condition_dict, npc.coin_name):
            additions.append(coin)

    return additions


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    header_block: HeaderBlock
    body: Body

    @property
    def prev_header_hash(self) -> bytes32:
        return self.header_block.header.data.prev_header_hash

    @property
    def height(self) -> uint32:
        return self.header_block.height

    @property
    def weight(self) -> uint64:
        if self.header_block.challenge:
            return self.header_block.challenge.total_weight
        else:
            return uint64(0)

    @property
    def header_hash(self) -> bytes32:
        return self.header_block.header.header_hash

    async def tx_removals_and_additions(self) -> Tuple[List[bytes32], List[Coin]]:
        """
        Doesn't return coinbase and fee reward.
        This call assumes that this block has been validated already,
        get_name_puzzle_conditions should not return error here
        """
        removals: List[bytes32] = []
        additions: List[Coin] = []

        if self.body.transactions is not None:
            # ensure block program generates solutions
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = await get_name_puzzle_conditions(self.body.transactions)
            # build removals list
            for npc in npc_list:
                removals.append(npc.coin_name)

            additions.extend(additions_for_npc(npc_list))

        return removals, additions

