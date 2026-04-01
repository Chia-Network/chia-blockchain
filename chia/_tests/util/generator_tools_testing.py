from __future__ import annotations

from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia._tests.util.get_name_puzzle_conditions import get_name_puzzle_conditions
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.generator_tools import tx_removals_and_additions
from chia.types.blockchain_format.coin import Coin
from chia.types.generator_types import BlockGenerator


def run_and_get_removals_and_additions(
    block: FullBlock,
    max_cost: int,
    *,
    height: uint32,
    constants: ConsensusConstants = DEFAULT_CONSTANTS,
    mempool_mode: bool = False,
) -> tuple[list[bytes32], list[Coin]]:
    removals: list[bytes32] = []
    additions: list[Coin] = []

    assert len(block.transactions_generator_ref_list) == 0
    if not block.is_transaction_block():
        return [], []

    if block.transactions_generator is not None:
        npc_result = get_name_puzzle_conditions(
            BlockGenerator(block.transactions_generator, []),
            max_cost,
            mempool_mode=mempool_mode,
            height=height,
            constants=constants,
        )
        assert npc_result.error is None
        rem, add = tx_removals_and_additions(npc_result.conds)
        # build removals list
        removals.extend(rem)
        additions.extend(add)

    rewards = block.get_included_reward_coins()
    additions.extend(rewards)
    return removals, additions
