import collections
import logging
from typing import Dict, List, Optional, Set, Tuple, Union, Callable

from blspy import AugSchemeMPL
from chiabip158 import PyBIP158
from clvm.casts import int_from_bytes

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.block_root_validation import validate_block_merkle_roots
from chia.consensus.blockchain_check_conditions import blockchain_check_conditions_dict
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult, calculate_cost_of_program
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.network_type import NetworkType
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.name_puzzle_condition import NPC
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.condition_tools import (
    pkm_pairs_for_conditions_dict,
    coin_announcements_names_for_npc,
    puzzle_announcements_names_for_npc,
)
from chia.util.errors import Err
from chia.util.generator_tools import (
    additions_for_npc,
    tx_removals_and_additions,
)
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)


async def validate_block_body(
    constants: ConsensusConstants,
    blocks: BlockchainInterface,
    block_store: BlockStore,
    coin_store: CoinStore,
    peak: Optional[BlockRecord],
    block: Union[FullBlock, UnfinishedBlock],
    height: uint32,
    npc_result: Optional[NPCResult],
    fork_point_with_peak: Optional[uint32],
    get_block_generator: Callable,
) -> Tuple[Optional[Err], Optional[NPCResult]]:
    """
    This assumes the header block has been completely validated.
    Validates the transactions and body of the block. Returns None for the first value if everything
    validates correctly, or an Err if something does not validate. For the second value, returns a CostResult
    if validation succeeded, and there are transactions
    """
    if isinstance(block, FullBlock):
        assert height == block.height
    prev_transaction_block_height: uint32 = uint32(0)

    # 1. For non block blocks, foliage block, transaction filter, transactions info, and generator must be empty
    # If it is a block but not a transaction block, there is no body to validate. Check that all fields are None
    if block.foliage.foliage_transaction_block_hash is None:
        if (
            block.foliage_transaction_block is not None
            or block.transactions_info is not None
            or block.transactions_generator is not None
        ):
            return Err.NOT_BLOCK_BUT_HAS_DATA, None
        return None, None  # This means the block is valid

    # 2. For blocks, foliage block, transaction filter, transactions info must not be empty
    if (
        block.foliage_transaction_block is None
        or block.foliage_transaction_block.filter_hash is None
        or block.transactions_info is None
    ):
        return Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, None

    # keeps track of the reward coins that need to be incorporated
    expected_reward_coins: Set[Coin] = set()

    # 3. The transaction info hash in the Foliage block must match the transaction info
    if block.foliage_transaction_block.transactions_info_hash != std_hash(block.transactions_info):
        return Err.INVALID_TRANSACTIONS_INFO_HASH, None

    # 4. The foliage block hash in the foliage block must match the foliage block
    if block.foliage.foliage_transaction_block_hash != std_hash(block.foliage_transaction_block):
        return Err.INVALID_FOLIAGE_BLOCK_HASH, None

    # 7. The reward claims must be valid for the previous blocks, and current block fees
    if height > 0:
        # Add reward claims for all blocks from the prev prev block, until the prev block (including the latter)
        prev_transaction_block = blocks.block_record(block.foliage_transaction_block.prev_transaction_block_hash)
        prev_transaction_block_height = prev_transaction_block.height
        assert prev_transaction_block.fees is not None
        pool_coin = create_pool_coin(
            prev_transaction_block_height,
            prev_transaction_block.pool_puzzle_hash,
            calculate_pool_reward(prev_transaction_block.height),
            constants.GENESIS_CHALLENGE,
        )
        farmer_coin = create_farmer_coin(
            prev_transaction_block_height,
            prev_transaction_block.farmer_puzzle_hash,
            uint64(calculate_base_farmer_reward(prev_transaction_block.height) + prev_transaction_block.fees),
            constants.GENESIS_CHALLENGE,
        )
        # Adds the previous block
        expected_reward_coins.add(pool_coin)
        expected_reward_coins.add(farmer_coin)

        # For the second block in the chain, don't go back further
        if prev_transaction_block.height > 0:
            curr_b = blocks.block_record(prev_transaction_block.prev_hash)
            while not curr_b.is_transaction_block:
                expected_reward_coins.add(
                    create_pool_coin(
                        curr_b.height,
                        curr_b.pool_puzzle_hash,
                        calculate_pool_reward(curr_b.height),
                        constants.GENESIS_CHALLENGE,
                    )
                )
                expected_reward_coins.add(
                    create_farmer_coin(
                        curr_b.height,
                        curr_b.farmer_puzzle_hash,
                        calculate_base_farmer_reward(curr_b.height),
                        constants.GENESIS_CHALLENGE,
                    )
                )
                curr_b = blocks.block_record(curr_b.prev_hash)

    if set(block.transactions_info.reward_claims_incorporated) != expected_reward_coins:
        return Err.INVALID_REWARD_COINS, None

    removals: List[bytes32] = []
    coinbase_additions: List[Coin] = list(expected_reward_coins)
    additions: List[Coin] = []
    coin_announcement_names: Set[bytes32] = set()
    puzzle_announcement_names: Set[bytes32] = set()
    npc_list: List[NPC] = []
    removals_puzzle_dic: Dict[bytes32, bytes32] = {}
    cost: uint64 = uint64(0)

    if height <= constants.INITIAL_FREEZE_PERIOD and block.transactions_generator is not None:
        return Err.INITIAL_TRANSACTION_FREEZE, None

    if height > constants.INITIAL_FREEZE_PERIOD and constants.NETWORK_TYPE == NetworkType.MAINNET:
        return Err.INITIAL_TRANSACTION_FREEZE, None
    else:
        # 6a. The generator root must be the hash of the serialized bytes of
        #     the generator for this block (or zeroes if no generator)
        if block.transactions_generator is not None:
            if std_hash(bytes(block.transactions_generator)) != block.transactions_info.generator_root:
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT, None
        else:
            if block.transactions_info.generator_root != bytes([0] * 32):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT, None

        # 6b. The generator_ref_list must be the hash of the serialized bytes of
        #     the generator ref list for this block (or 'one' bytes [0x01] if no generator)
        # 6c. The generator ref list length must be less than or equal to MAX_GENERATOR_REF_LIST_SIZE entries
        if block.transactions_generator_ref_list in (None, []):
            if block.transactions_info.generator_refs_root != bytes([1] * 32):
                return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None
        else:
            # If we have a generator reference list, we must have a generator
            if block.transactions_generator is None:
                return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None

            # The generator_refs_root must be the hash of the concatenation of the List[uint32]
            generator_refs_hash = std_hash(
                b"".join([i.to_bytes(4, byteorder="big") for i in block.transactions_generator_ref_list])
            )
            if block.transactions_info.generator_refs_root != generator_refs_hash:
                return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None
            if len(block.transactions_generator_ref_list) > constants.MAX_GENERATOR_REF_LIST_SIZE:
                return Err.PRE_SOFT_FORK_TOO_MANY_GENERATOR_REFS, None

        if block.transactions_generator is not None:
            # The generator must be less than MAX_GENERATOR_SIZE bytes in length
            if len(bytes(block.transactions_generator)) > constants.MAX_GENERATOR_SIZE:


                return Err.PRE_SOFT_FORK_MAX_GENERATOR_SIZE, None

            # Get List of names removed, puzzles hashes for removed coins and conditions created
            if cached_cost_result is not None:
                result: Optional[CostResult] = cached_cost_result
            else:
                result = calculate_cost_of_program(block.transactions_generator, constants.COST_PER_BYTE)
            # The call to calculate cost runs the generator program
            if result is None:
                return Err.INVALID_COST_RESULT, None

            assert npc_result is not None
            cost = calculate_cost_of_program(
                block.transactions_generator, npc_result, constants.CLVM_COST_RATIO_CONSTANT
            )
            npc_list = npc_result.npc_list

            # 8. Check that cost <= MAX_BLOCK_COST_CLVM
            if cost > constants.MAX_BLOCK_COST_CLVM:
                return Err.BLOCK_COST_EXCEEDS_MAX, None
            if npc_result.error is not None:
                return Err.GENERATOR_RUNTIME_ERROR, None

            for npc in npc_list:
                removals.append(npc.coin_name)
                removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

            additions = additions_for_npc(npc_list)
            coin_announcement_names = coin_announcements_names_for_npc(npc_list)
            puzzle_announcement_names = puzzle_announcements_names_for_npc(npc_list)
        else:
            npc_result = None

        # 9. Check that the correct cost is in the transactions info
        if block.transactions_info.cost != cost:
            return Err.INVALID_BLOCK_COST, None

        additions_dic: Dict[bytes32, Coin] = {}
        # 10. Check additions for max coin amount
        # Be careful to check for 64 bit overflows in other languages. This is the max 64 bit unsigned integer
        for coin in additions + coinbase_additions:
            additions_dic[coin.name()] = coin
            if coin.amount > constants.MAX_COIN_AMOUNT:
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None

        # 11. Validate addition and removal roots
        root_error = validate_block_merkle_roots(
            block.foliage_transaction_block.additions_root,
            block.foliage_transaction_block.removals_root,
            additions + coinbase_additions,
            removals,
        )
        if root_error:
            return root_error, None

        # 12. The additions and removals must result in the correct filter
        byte_array_tx: List[bytes32] = []

        for coin in additions + coinbase_additions:
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin_name in removals:
            byte_array_tx.append(bytearray(coin_name))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())
        filter_hash = std_hash(encoded_filter)

        if filter_hash != block.foliage_transaction_block.filter_hash:
            return Err.INVALID_TRANSACTIONS_FILTER_HASH, None

        # 13. Check for duplicate outputs in additions
        addition_counter = collections.Counter(_.name() for _ in additions + coinbase_additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT, None

        # 14. Check for duplicate spends inside block
        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                return Err.DOUBLE_SPEND, None

        # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
        if peak is None or height == 0:
            fork_h: int = -1
        elif fork_point_with_peak is not None:
            fork_h = fork_point_with_peak
        else:
            fork_h = find_fork_point_in_chain(blocks, peak, blocks.block_record(block.prev_header_hash))

        if fork_h == -1:
            coin_store_reorg_height = -1
        else:
            last_block_in_common = await blocks.get_block_record_from_db(blocks.height_to_hash(uint32(fork_h)))
            assert last_block_in_common is not None
            coin_store_reorg_height = last_block_in_common.height

        # Get additions and removals since (after) fork_h but not including this block
        additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
        removals_since_fork: Set[bytes32] = set()
        coinbases_since_fork: Dict[bytes32, uint32] = {}

        if height > 0:
            prev_block: Optional[FullBlock] = await block_store.get_full_block(block.prev_header_hash)
            reorg_blocks: Dict[int, FullBlock] = {}
            curr: Optional[FullBlock] = prev_block
            assert curr is not None
            reorg_blocks[curr.height] = curr
            while curr.height > fork_h:
                if curr.height == 0:
                    break
                curr = await block_store.get_full_block(curr.prev_header_hash)
                assert curr is not None
                reorg_blocks[curr.height] = curr

            curr = prev_block
            assert curr is not None
            while curr.height > fork_h:
                # Coin store doesn't contain coins from fork, we have to run generator for each block in fork
                if curr.transactions_generator is not None:
                    curr_block_generator: Optional[BlockGenerator] = await get_block_generator(curr)
                    assert curr_block_generator is not None
                    npc_result = get_name_puzzle_conditions(curr_block_generator, False)
                    removals_in_curr, additions_in_curr = tx_removals_and_additions(npc_result.npc_list)
                else:
                    removals_in_curr = []
                    additions_in_curr = []

                for c_name in removals_in_curr:
                    removals_since_fork.add(c_name)
                for c in additions_in_curr:
                    additions_since_fork[c.name()] = (c, curr.height)

                for coinbase_coin in curr.get_included_reward_coins():
                    additions_since_fork[coinbase_coin.name()] = (coinbase_coin, curr.height)
                    coinbases_since_fork[coinbase_coin.name()] = curr.height
                if curr.height == 0:
                    break
                curr = reorg_blocks[curr.height - 1]
                assert curr is not None

        removal_coin_records: Dict[bytes32, CoinRecord] = {}
        for rem in removals:
            if rem in additions_dic:
                # Ephemeral coin
                rem_coin: Coin = additions_dic[rem]
                new_unspent: CoinRecord = CoinRecord(
                    rem_coin,
                    height,
                    uint32(0),
                    False,
                    (rem in coinbases_since_fork),
                    block.foliage_transaction_block.timestamp,
                )
                removal_coin_records[new_unspent.name] = new_unspent
            else:
                unspent = await coin_store.get_coin_record(rem)
                if unspent is not None and unspent.confirmed_block_index <= coin_store_reorg_height:
                    # Spending something in the current chain, confirmed before fork
                    # (We ignore all coins confirmed after fork)
                    if unspent.spent == 1 and unspent.spent_block_index <= coin_store_reorg_height:
                        # Check for coins spent in an ancestor block
                        return Err.DOUBLE_SPEND, None
                    removal_coin_records[unspent.name] = unspent
                else:
                    # This coin is not in the current heaviest chain, so it must be in the fork
                    if rem not in additions_since_fork:
                        # Check for spending a coin that does not exist in this fork
                        # TODO: fix this, there is a consensus bug here
                        return Err.UNKNOWN_UNSPENT, None
                    new_coin, confirmed_height = additions_since_fork[rem]
                    new_coin_record: CoinRecord = CoinRecord(
                        new_coin,
                        confirmed_height,
                        uint32(0),
                        False,
                        (rem in coinbases_since_fork),
                        block.foliage_transaction_block.timestamp,
                    )
                    removal_coin_records[new_coin_record.name] = new_coin_record

                # This check applies to both coins created before fork (pulled from coin_store),
                # and coins created after fork (additions_since_fork)>
                if rem in removals_since_fork:
                    # This coin was spent in the fork
                    return Err.DOUBLE_SPEND, None

        removed = 0
        for unspent in removal_coin_records.values():
            removed += unspent.coin.amount

        added = 0
        for coin in additions:
            added += coin.amount

        # 16. Check that the total coin amount for added is <= removed
        if removed < added:
            return Err.MINTING_COIN, None

        fees = removed - added
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.RESERVE_FEE in npc.condition_dict:
                fee_list: List[ConditionWithArgs] = npc.condition_dict[ConditionOpcode.RESERVE_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    assert_fee_sum = assert_fee_sum + fee

        # 17. Check that the assert fee sum <= fees
        if fees < assert_fee_sum:
            return Err.RESERVE_FEE_CONDITION_FAILED, None

        # 18. Check that the assert fee amount < maximum coin amount
        if fees > constants.MAX_COIN_AMOUNT:
            return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None

        # 19. Check that the computed fees are equal to the fees in the block header
        if block.transactions_info.fees != fees:
            return Err.INVALID_BLOCK_FEE_AMOUNT, None

        # 20. Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
        for unspent in removal_coin_records.values():
            if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
                return Err.WRONG_PUZZLE_HASH, None

        # 21. Verify conditions
        # create hash_key list for aggsig check
        pairs_pks = []
        pairs_msgs = []
        for npc in npc_list:
            assert height is not None
            unspent = removal_coin_records[npc.coin_name]
            error = blockchain_check_conditions_dict(
                unspent,
                coin_announcement_names,
                puzzle_announcement_names,
                npc.condition_dict,
                prev_transaction_block_height,
                block.foliage_transaction_block.timestamp,
            )
            if error:
                return error, None
            for pk, m in pkm_pairs_for_conditions_dict(
                npc.condition_dict, npc.coin_name, constants.AGG_SIG_ME_ADDITIONAL_DATA
            ):
                pairs_pks.append(pk)
                pairs_msgs.append(m)

        # 22. Verify aggregated signature
        # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
        if not block.transactions_info.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE, None

            # noinspection PyTypeChecker
        if not AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature):
            return Err.BAD_AGGREGATE_SIGNATURE, None

        return None, npc_result
