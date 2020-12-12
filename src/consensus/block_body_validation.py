import collections
from typing import Union, Optional, Set, List, Dict, Tuple

from blspy import AugSchemeMPL, G2Element
from chiabip158 import PyBIP158
from clvm.casts import int_from_bytes

from src.consensus.block_rewards import (
    calculate_pool_reward,
    calculate_base_farmer_reward,
)
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.constants import ConsensusConstants
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.consensus.block_root_validation import validate_block_merkle_roots
from src.full_node.block_store import BlockStore
from src.consensus.blockchain_check_conditions import blockchain_check_conditions_dict
from src.full_node.coin_store import CoinStore
from src.consensus.cost_calculator import calculate_cost_of_program
from src.consensus.sub_block_record import SubBlockRecord
from src.types.coin import Coin
from src.types.coin_record import CoinRecord
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.full_block import FullBlock, additions_for_npc
from src.types.name_puzzle_condition import NPC
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.util.condition_tools import pkm_pairs_for_conditions_dict
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint64, uint32


async def validate_block_body(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    block_store: BlockStore,
    coin_store: CoinStore,
    peak: Optional[SubBlockRecord],
    block: Union[FullBlock, UnfinishedBlock],
    sub_height: uint32,
    height: Optional[uint32],
) -> Optional[Err]:
    """
    This assumes the header block has been completely validated.
    Validates the transactions and body of the block. Returns None if everything
    validates correctly, or an Err if something does not validate.
    """
    if isinstance(block, FullBlock):
        assert sub_height == block.sub_block_height
        if height is not None:
            assert height == block.height
            assert block.is_block()
        else:
            assert not block.is_block()

    # 1. For non block sub-blocks, foliage block, transaction filter, transactions info, and generator must be empty
    # If it is a sub block but not a block, there is no body to validate. Check that all fields are None
    if block.foliage_sub_block.foliage_block_hash is None:
        if (
            block.foliage_block is not None
            or block.transactions_info is not None
            or block.transactions_generator is not None
        ):
            return Err.NOT_BLOCK_BUT_HAS_DATA
        return None  # This means the sub-block is valid

    # 2. For blocks, foliage block, transaction filter, transactions info must not be empty
    if block.foliage_block is None or block.foliage_block.filter_hash is None or block.transactions_info is None:
        return Err.IS_BLOCK_BUT_NO_DATA

    # keeps track of the reward coins that need to be incorporated
    expected_reward_coins: Set[Coin] = set()

    # 3. The transaction info hash in the Foliage block must match the transaction info
    if block.foliage_block.transactions_info_hash != std_hash(block.transactions_info):
        return Err.INVALID_TRANSACTIONS_INFO_HASH

    # 4. The foliage block hash in the foliage sub block must match the foliage block
    if block.foliage_sub_block.foliage_block_hash != std_hash(block.foliage_block):
        return Err.INVALID_FOLIAGE_BLOCK_HASH

    # 5. The prev generators root must be valid
    # TODO(straya): implement prev generators

    # 6. The generator root must be the tree-hash of the generator (or zeroes if no generator)
    if block.transactions_generator is not None:
        if block.transactions_generator.get_tree_hash() != block.transactions_info.generator_root:
            return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT
    else:
        if block.transactions_info.generator_root != bytes([0] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT

    # 7. The reward claims must be valid for the previous sub-blocks, and current block fees
    if sub_height > 0:
        # Add reward claims for all sub-blocks from the prev prev block, until the prev block (including the latter)
        curr_sb = sub_blocks[block.prev_header_hash]

        while not curr_sb.is_block:
            # Finds the prev block
            curr_sb = sub_blocks[curr_sb.prev_hash]
        assert curr_sb.header_hash == block.foliage_block.prev_block_hash

        if curr_sb.sub_block_height == 0:
            curr_height = uint32(0)
        else:
            if curr_sb.is_block:
                curr_height = uint32(curr_sb.height + 1)
            else:
                curr_height = curr_sb.height

        assert curr_sb.fees is not None
        pool_coin = create_pool_coin(
            curr_sb.sub_block_height,
            curr_sb.pool_puzzle_hash,
            calculate_pool_reward(curr_height),
        )
        farmer_coin = create_farmer_coin(
            curr_sb.sub_block_height,
            curr_sb.farmer_puzzle_hash,
            uint64(calculate_base_farmer_reward(curr_height) + curr_sb.fees),
        )
        # Adds the previous block
        expected_reward_coins.add(pool_coin)
        expected_reward_coins.add(farmer_coin)

        # For the second block in the chain, don't go back further
        if curr_sb.sub_block_height > 0:
            curr_sb = sub_blocks[curr_sb.prev_hash]
            curr_height = curr_sb.height
            while not curr_sb.is_block:
                expected_reward_coins.add(
                    create_pool_coin(
                        curr_sb.sub_block_height,
                        curr_sb.pool_puzzle_hash,
                        calculate_pool_reward(curr_height),
                    )
                )
                expected_reward_coins.add(
                    create_farmer_coin(
                        curr_sb.sub_block_height,
                        curr_sb.farmer_puzzle_hash,
                        calculate_base_farmer_reward(curr_height),
                    )
                )
                curr_sb = sub_blocks[curr_sb.prev_hash]

    if set(block.transactions_info.reward_claims_incorporated) != expected_reward_coins:
        return Err.INVALID_REWARD_COINS

    removals: List[bytes32] = []
    coinbase_additions: List[Coin] = list(expected_reward_coins)
    additions: List[Coin] = []
    npc_list: List[NPC] = []
    removals_puzzle_dic: Dict[bytes32, bytes32] = {}
    cost: uint64 = uint64(0)

    if block.transactions_generator is not None:
        # Get List of names removed, puzzles hashes for removed coins and conditions crated
        error, npc_list, cost = calculate_cost_of_program(
            block.transactions_generator, constants.CLVM_COST_RATIO_CONSTANT
        )

        # 8. Check that cost <= MAX_BLOCK_COST_CLVM
        if cost > constants.MAX_BLOCK_COST_CLVM:
            return Err.BLOCK_COST_EXCEEDS_MAX
        if error:
            return error

        for npc in npc_list:
            removals.append(npc.coin_name)
            removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

        additions = additions_for_npc(npc_list)

    # 9. Check that the correct cost is in the transactions info
    if block.transactions_info.cost != cost:
        return Err.INVALID_BLOCK_COST

    additions_dic: Dict[bytes32, Coin] = {}
    # 10. Check additions for max coin amount
    for coin in additions + coinbase_additions:
        additions_dic[coin.name()] = coin
        if coin.amount >= constants.MAX_COIN_AMOUNT:
            return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

    # 11. Validate addition and removal roots
    root_error = validate_block_merkle_roots(
        block.foliage_block.additions_root,
        block.foliage_block.removals_root,
        additions + coinbase_additions,
        removals,
    )
    if root_error:
        return root_error

    # 12. The additions and removals must result in the correct filter
    byte_array_tx: List[bytes32] = []

    for coin in additions + coinbase_additions:
        byte_array_tx.append(bytearray(coin.puzzle_hash))
    for coin_name in removals:
        byte_array_tx.append(bytearray(coin_name))

    bip158: PyBIP158 = PyBIP158(byte_array_tx)
    encoded_filter = bytes(bip158.GetEncoded())
    filter_hash = std_hash(encoded_filter)

    if filter_hash != block.foliage_block.filter_hash:
        return Err.INVALID_TRANSACTIONS_FILTER_HASH

    # 13. Check for duplicate outputs in additions
    addition_counter = collections.Counter(_.name() for _ in additions + coinbase_additions)
    for k, v in addition_counter.items():
        if v > 1:
            return Err.DUPLICATE_OUTPUT

    # 14. Check for duplicate spends inside block
    removal_counter = collections.Counter(removals)
    for k, v in removal_counter.items():
        if v > 1:
            return Err.DOUBLE_SPEND

    # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
    if peak is None or sub_height == 0:
        fork_h: int = -1
    else:
        fork_h = find_fork_point_in_chain(sub_blocks, peak, sub_blocks[block.prev_header_hash])

    # Get additions and removals since (after) fork_h but not including this block
    additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
    removals_since_fork: Set[bytes32] = set()
    coinbases_since_fork: Dict[bytes32, uint32] = {}

    if sub_height > 0:
        curr: Optional[FullBlock] = await block_store.get_full_block(block.prev_header_hash)
        assert curr is not None

        while curr.sub_block_height > fork_h:
            removals_in_curr, additions_in_curr = await curr.tx_removals_and_additions()
            for c_name in removals_in_curr:
                removals_since_fork.add(c_name)
            for c in additions_in_curr:
                additions_since_fork[c.name()] = (c, curr.sub_block_height)

            for coinbase_coin in curr.get_included_reward_coins():
                coinbases_since_fork[coinbase_coin.name()] = curr.sub_block_height
            if curr.sub_block_height == 0:
                break
            curr = await block_store.get_full_block(curr.prev_header_hash)
            assert curr is not None

    removal_coin_records: Dict[bytes32, CoinRecord] = {}
    for rem in removals:
        if rem in additions_dic:
            # Ephemeral coin
            rem_coin: Coin = additions_dic[rem]
            new_unspent: CoinRecord = CoinRecord(
                rem_coin,
                sub_height,
                uint32(0),
                False,
                False,
                block.foliage_block.timestamp,
            )
            removal_coin_records[new_unspent.name] = new_unspent
        else:
            unspent = await coin_store.get_coin_record(rem)
            if unspent is not None and unspent.confirmed_block_index <= fork_h:
                # Spending something in the current chain, confirmed before fork
                # (We ignore all coins confirmed after fork)
                if unspent.spent == 1 and unspent.spent_block_index <= fork_h:
                    # Check for coins spent in an ancestor block
                    return Err.DOUBLE_SPEND
                removal_coin_records[unspent.name] = unspent
            else:
                # This coin is not in the current heaviest chain, so it must be in the fork
                if rem not in additions_since_fork:
                    # Check for spending a coin that does not exist in this fork
                    # TODO: fix this, there is a consensus bug here
                    return Err.UNKNOWN_UNSPENT
                new_coin, confirmed_height = additions_since_fork[rem]
                new_coin_record: CoinRecord = CoinRecord(
                    new_coin,
                    confirmed_height,
                    uint32(0),
                    False,
                    (rem in coinbases_since_fork),
                    block.foliage_block.timestamp,
                )
                removal_coin_records[new_coin_record.name] = new_coin_record

            # This check applies to both coins created before fork (pulled from coin_store),
            # and coins created after fork (additions_since_fork)>
            if rem in removals_since_fork:
                # This coin was spent in the fork
                return Err.DOUBLE_SPEND

    removed = 0
    for unspent in removal_coin_records.values():
        removed += unspent.coin.amount

    added = 0
    for coin in additions:
        added += coin.amount

    # 16. Check that the total coin amount for added is <= removed
    if removed < added:
        return Err.MINTING_COIN

    fees = removed - added
    assert_fee_sum: uint64 = uint64(0)

    for npc in npc_list:
        if ConditionOpcode.ASSERT_FEE in npc.condition_dict:
            fee_list: List[ConditionVarPair] = npc.condition_dict[ConditionOpcode.ASSERT_FEE]
            for cvp in fee_list:
                fee = int_from_bytes(cvp.vars[0])
                assert_fee_sum = assert_fee_sum + fee

    # 17. Check that the assert fee sum <= fees
    if fees < assert_fee_sum:
        return Err.ASSERT_FEE_CONDITION_FAILED

    # 18. Check that the computed fees are equal to the fees in the block header
    if block.transactions_info.fees != fees:
        return Err.INVALID_BLOCK_FEE_AMOUNT

    # 19. Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
    for unspent in removal_coin_records.values():
        if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
            return Err.WRONG_PUZZLE_HASH

    # 20. Verify conditions
    # create hash_key list for aggsig check
    pairs_pks = []
    pairs_msgs = []
    for npc in npc_list:
        assert height is not None
        unspent = removal_coin_records[npc.coin_name]
        error = blockchain_check_conditions_dict(
            unspent,
            removal_coin_records,
            npc.condition_dict,
            height,
            block.foliage_block.timestamp,
        )
        if error:
            return error
        for pk, m in pkm_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name):
            pairs_pks.append(pk)
            pairs_msgs.append(m)

    # 21. Verify aggregated signature
    # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
    if not block.transactions_info.aggregated_signature:
        return Err.BAD_AGGREGATE_SIGNATURE

    if len(pairs_pks) == 0:
        if len(pairs_msgs) != 0 or block.transactions_info.aggregated_signature != G2Element.infinity():
            return Err.BAD_AGGREGATE_SIGNATURE
    else:
        # noinspection PyTypeChecker
        validates = AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature)
        if not validates:
            return Err.BAD_AGGREGATE_SIGNATURE

    return None
