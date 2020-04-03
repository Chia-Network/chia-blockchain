from dataclasses import dataclass
from typing import Tuple, List, Optional

from src.types.name_puzzle_condition import NPC
from src.types.program import Program
from src.types.coin import Coin
from src.types.header import Header
from src.types.sized_bytes import bytes32
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.util.condition_tools import created_outputs_for_conditions_dict
from src.util.ints import uint32, uint128
from src.util.streamable import Streamable, streamable
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime


def additions_for_npc(npc_list: List[NPC]) -> List[Coin]:
    additions: List[Coin] = []

    for npc in npc_list:
        for coin in created_outputs_for_conditions_dict(
            npc.condition_dict, npc.coin_name
        ):
            additions.append(coin)

    return additions


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    proof_of_space: ProofOfSpace
    proof_of_time: Optional[ProofOfTime]
    header: Header
    transactions_generator: Optional[Program]
    transactions_filter: Optional[bytes]

    @property
    def prev_header_hash(self) -> bytes32:
        return self.header.data.prev_header_hash

    @property
    def height(self) -> uint32:
        return self.header.height

    @property
    def weight(self) -> uint128:
        return self.header.data.weight

    @property
    def header_hash(self) -> bytes32:
        return self.header.header_hash

    def additions(self) -> List[Coin]:
        additions: List[Coin] = []

        if self.transactions_generator is not None:
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = get_name_puzzle_conditions(
                self.transactions_generator
            )
            # created coins
            if npc_list is not None:
                additions.extend(additions_for_npc(npc_list))

        additions.append(self.header.data.coinbase)
        additions.append(self.header.data.fees_coin)

        return additions

    async def tx_removals_and_additions(self) -> Tuple[List[bytes32], List[Coin]]:
        """
        Doesn't return coinbase and fee reward.
        This call assumes that this block has been validated already,
        get_name_puzzle_conditions should not return error here
        """
        removals: List[bytes32] = []
        additions: List[Coin] = []

        if self.transactions_generator is not None:
            # This should never throw here, block must be valid if it comes to here
            err, npc_list, cost = get_name_puzzle_conditions(
                self.transactions_generator
            )
            # build removals list
            if npc_list is None:
                return [], []
            for npc in npc_list:
                removals.append(npc.coin_name)

            additions.extend(additions_for_npc(npc_list))

        return removals, additions
