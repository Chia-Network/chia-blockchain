import collections
import logging
from typing import Dict, List, Optional, Set, Tuple, Union

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
from chia.consensus.cost_calculator import CostResult, calculate_cost_of_program
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.network_type import NetworkType
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_var_pair import ConditionVarPair
from chia.types.full_block import FullBlock, additions_for_npc, announcements_for_npc
from chia.types.name_puzzle_condition import NPC
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.condition_tools import pkm_pairs_for_conditions_dict
from chia.util.errors import Err
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
    cached_cost_result: Optional[CostResult] = None,
    fork_point_with_peak: Optional[uint32] = None,
) -> Tuple[Optional[Err], Optional[CostResult]]:
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

    # 5. The prev generators root must be valid
    # TODO(straya): implement prev generators

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
    announcements: List[Announcement] = []
    npc_list: List[NPC] = []
    removals_puzzle_dic: Dict[bytes32, bytes32] = {}
    cost: uint64 = uint64(0)

    if height <= constants.INITIAL_FREEZE_PERIOD and block.transactions_generator is not None:
        return Err.INITIAL_TRANSACTION_FREEZE, None

    if height > constants.INITIAL_FREEZE_PERIOD and constants.NETWORK_TYPE == NetworkType.MAINNET:
        return Err.INITIAL_TRANSACTION_FREEZE, None
    else:
        # 6. The generator root must be the tree-hash of the generator (or zeroes if no generator)
        if block.transactions_generator is not None:
            if block.transactions_generator.get_tree_hash() != block.transactions_info.generator_root:
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT, None
        else:
            if block.transactions_info.generator_root != bytes([0] * 32):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ROOT, None

        if block.transactions_generator_ref_list is not None:
            if len(bytes(block.transactions_generator_ref_list)) > constants.MAX_GENERATOR_REF_LIST_SIZE:
                return Err.PRE_SOFT_FORK_MAX_GENERATOR_REF_LIST_SIZE, None

        if block.transactions_generator is not None:
            # Get List of names removed, puzzles hashes for removed coins and conditions crated
            if cached_cost_result is not None:
                result: Optional[CostResult] = cached_cost_result
            else:
                result = calculate_cost_of_program(block.transactions_generator, constants.CLVM_COST_RATIO_CONSTANT)
            assert result is not None
            cost = result.cost
            npc_list = result.npc_list

            # 8. Check that cost <= MAX_BLOCK_COST_CLVM
            if cost > constants.MAX_BLOCK_COST_CLVM:
                return Err.BLOCK_COST_EXCEEDS_MAX, None
            if result.error is not None:
                return Err(result.error), None

            for npc in npc_list:
                removals.append(npc.coin_name)
                removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

            additions = additions_for_npc(npc_list)
            announcements = announcements_for_npc(npc_list)
        else:
            result = None

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
            curr: Optional[FullBlock] = await block_store.get_full_block(block.prev_header_hash)
            assert curr is not None

            while curr.height > fork_h:
                removals_in_curr, additions_in_curr = curr.tx_removals_and_additions()
                for c_name in removals_in_curr:
                    removals_since_fork.add(c_name)
                for c in additions_in_curr:
                    additions_since_fork[c.name()] = (c, curr.height)

                for coinbase_coin in curr.get_included_reward_coins():
                    additions_since_fork[coinbase_coin.name()] = (coinbase_coin, curr.height)
                    coinbases_since_fork[coinbase_coin.name()] = curr.height
                if curr.height == 0:
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
                fee_list: List[ConditionVarPair] = npc.condition_dict[ConditionOpcode.RESERVE_FEE]
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
                announcements,
                npc.condition_dict,
                prev_transaction_block_height,
                block.foliage_transaction_block.timestamp,
            )
            if error:
                return error, None
            for pk, m in pkm_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name):
                pairs_pks.append(pk)
                pairs_msgs.append(m)

        # 22. Verify aggregated signature
        # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
        if not block.transactions_info.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE, None

            # noinspection PyTypeChecker
        if not AugSchemeMPL.aggregate_verify(pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature):
            return Err.BAD_AGGREGATE_SIGNATURE, None

        return None, result
