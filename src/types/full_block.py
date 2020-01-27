from dataclasses import dataclass
from typing import Tuple, List

from src.types.body import Body
from src.types.hashable import Coin
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.chain_utils import name_puzzle_conditions_list
from src.util.consensus import created_outputs_for_conditions_dict
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable


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

    def additions_for_npc(self, npc_list) -> List[Coin]:
        additions: List[Coin] = []

        for coin_name, puzzle_hash, conditions_dict in npc_list:
            for coin in created_outputs_for_conditions_dict(conditions_dict, coin_name):
                additions.append(coin)

        return additions

    def removals_and_additions(self) -> Tuple[List[bytes32], List[Coin]]:
        removals: List[bytes32] = []
        additions: List[Coin] = [self.body.coinbase, self.body.fees_coin]

        if self.body.transactions is not None:
            # ensure block program generates solutions
            # This should never throw here, block must be valid if it comes to here
            npc_list = name_puzzle_conditions_list(self.body.transactions)
            # build removals list
            for coin_name, ph, con in npc_list:
                removals.append(coin_name)

            additions.extend(self.additions_for_npc(npc_list))

        return removals, additions

