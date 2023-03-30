from __future__ import annotations

import collections
import logging
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.block_root_validation import validate_block_merkle_roots
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, mempool_check_time_locks
from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.unfinished_block import UnfinishedBlock
from chia.util import cached_bls
from chia.util.condition_tools import pkm_pairs
from chia.util.errors import Err
from chia.util.generator_tools import tx_removals_and_additions
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
    get_block_generator: Callable[[BlockInfo], Awaitable[Optional[BlockGenerator]]],
    *,
    validate_signature: bool = True,
) -> Tuple[Optional[Err], Optional[NPCResult]]:
    """
    This assumes the header block has been completely validated.
    Validates the transactions and body of the block. Returns None for the first value if everything
    validates correctly, or an Err if something does not validate. For the second value, returns a CostResult
    only if validation succeeded, and there are transactions. In other cases it returns None. The NPC result is
    the result of running the generator with the previous generators refs. It is only present for transaction
    blocks which have spent coins.
    """
    if isinstance(block, FullBlock):
        assert height == block.height
    prev_transaction_block_height: uint32 = uint32(0)
    prev_transaction_block_timestamp: uint64 = uint64(0)

    # 1. For non transaction-blocs: foliage block, transaction filter, transactions info, and generator must
    # be empty. If it is a block but not a transaction block, there is no body to validate. Check that all fields are
    # None
    if block.foliage.foliage_transaction_block_hash is None:
        if (
            block.foliage_transaction_block is not None
            or block.transactions_info is not None
            or block.transactions_generator is not None
        ):
            return Err.NOT_BLOCK_BUT_HAS_DATA, None

        prev_tb: BlockRecord = blocks.block_record(block.prev_header_hash)
        while not prev_tb.is_transaction_block:
            prev_tb = blocks.block_record(prev_tb.prev_hash)
        assert prev_tb.timestamp is not None
        if len(block.transactions_generator_ref_list) > 0:
            return Err.NOT_BLOCK_BUT_HAS_DATA, None

        return None, None  # This means the block is valid

    # All checks below this point correspond to transaction blocks
    # 2. For blocks, foliage block, transactions info must not be empty
    if block.foliage_transaction_block is None or block.transactions_info is None:
        return Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, None
    assert block.foliage_transaction_block is not None

    # keeps track of the reward coins that need to be incorporated
    expected_reward_coins: Set[Coin] = set()

    # 3. The transaction info hash in the Foliage block must match the transaction info
    if block.foliage_transaction_block.transactions_info_hash != std_hash(block.transactions_info):
        return Err.INVALID_TRANSACTIONS_INFO_HASH, None

    # 4. The foliage block hash in the foliage block must match the foliage block
    if block.foliage.foliage_transaction_block_hash != std_hash(block.foliage_transaction_block):
        return Err.INVALID_FOLIAGE_BLOCK_HASH, None

    # 5. The reward claims must be valid for the previous blocks, and current block fees
    # If height == 0, expected_reward_coins will be left empty
    if height > 0:
        # Add reward claims for all blocks from the prev prev block, until the prev block (including the latter)
        prev_transaction_block = blocks.block_record(block.foliage_transaction_block.prev_transaction_block_hash)
        prev_transaction_block_height = prev_transaction_block.height
        assert prev_transaction_block.timestamp
        prev_transaction_block_timestamp = prev_transaction_block.timestamp
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

    if len(block.transactions_info.reward_claims_incorporated) != len(expected_reward_coins):
        return Err.INVALID_REWARD_COINS, None

    removals: List[bytes32] = []

    # we store coins paired with their names in order to avoid computing the
    # coin name multiple times, we store it next to the coin while validating
    # the block
    coinbase_additions: List[Tuple[Coin, bytes32]] = [(c, c.name()) for c in expected_reward_coins]
    additions: List[Tuple[Coin, bytes32]] = []
    removals_puzzle_dic: Dict[bytes32, bytes32] = {}
    cost: uint64 = uint64(0)

    # In header validation we check that timestamp is not more than 5 minutes into the future
    # 6. No transactions before INITIAL_TRANSACTION_FREEZE timestamp
    # (this test has been removed)

    # 7a. The generator root must be the hash of the serialized bytes of
    #     the generator for this block (or zeroes if no generator)
    if block.transactions_generator is not None:
        if std_hash(bytes(block.transactions_generator)) != block.transactions_info.generator_root:
            return Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None
    else:
        if block.transactions_info.generator_root != bytes([0] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None

    # 8a. The generator_ref_list must be the hash of the serialized bytes of
    #     the generator ref list for this block (or 'one' bytes [0x01] if no generator)
    # 8b. The generator ref list length must be less than or equal to MAX_GENERATOR_REF_LIST_SIZE entries
    # 8c. The generator ref list must not point to a height >= this block's height
    if block.transactions_generator_ref_list in (None, []):
        if block.transactions_info.generator_refs_root != bytes([1] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None
    else:
        # If we have a generator reference list, we must have a generator
        if block.transactions_generator is None:
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None

        # The generator_refs_root must be the hash of the concatenation of the List[uint32]
        generator_refs_hash = std_hash(b"".join([bytes(i) for i in block.transactions_generator_ref_list]))
        if block.transactions_info.generator_refs_root != generator_refs_hash:
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, None
        if len(block.transactions_generator_ref_list) > constants.MAX_GENERATOR_REF_LIST_SIZE:
            return Err.TOO_MANY_GENERATOR_REFS, None
        if any([index >= height for index in block.transactions_generator_ref_list]):
            return Err.FUTURE_GENERATOR_REFS, None

    if block.transactions_generator is not None:
        # Get List of names removed, puzzles hashes for removed coins and conditions created

        assert npc_result is not None
        cost = npc_result.cost

        # 7. Check that cost <= MAX_BLOCK_COST_CLVM
        log.debug(
            f"Cost: {cost} max: {constants.MAX_BLOCK_COST_CLVM} "
            f"percent full: {round(100 * (cost / constants.MAX_BLOCK_COST_CLVM), 2)}%"
        )
        if cost > constants.MAX_BLOCK_COST_CLVM:
            return Err.BLOCK_COST_EXCEEDS_MAX, None

        # 8. The CLVM program must not return any errors
        if npc_result.error is not None:
            return Err(npc_result.error), None

        assert npc_result.conds is not None

        for spend in npc_result.conds.spends:
            removals.append(bytes32(spend.coin_id))
            removals_puzzle_dic[bytes32(spend.coin_id)] = bytes32(spend.puzzle_hash)
            for puzzle_hash, amount, _ in spend.create_coin:
                c = Coin(bytes32(spend.coin_id), bytes32(puzzle_hash), uint64(amount))
                additions.append((c, c.name()))
    else:
        assert npc_result is None

    # 9. Check that the correct cost is in the transactions info
    if block.transactions_info.cost != cost:
        return Err.INVALID_BLOCK_COST, None

    additions_dic: Dict[bytes32, Coin] = {}
    # 10. Check additions for max coin amount
    # Be careful to check for 64 bit overflows in other languages. This is the max 64 bit unsigned integer
    # We will not even reach here because Coins do type checking (uint64)
    for coin, coin_name in additions + coinbase_additions:
        additions_dic[coin_name] = coin
        if coin.amount < 0:
            return Err.COIN_AMOUNT_NEGATIVE, None

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
    byte_array_tx: List[bytearray] = []

    for coin, _ in additions + coinbase_additions:
        byte_array_tx.append(bytearray(coin.puzzle_hash))
    for coin_name in removals:
        byte_array_tx.append(bytearray(coin_name))

    bip158: PyBIP158 = PyBIP158(byte_array_tx)
    encoded_filter = bytes(bip158.GetEncoded())
    filter_hash = std_hash(encoded_filter)

    if filter_hash != block.foliage_transaction_block.filter_hash:
        return Err.INVALID_TRANSACTIONS_FILTER_HASH, None

    # 13. Check for duplicate outputs in additions
    addition_counter = collections.Counter(coin_name for _, coin_name in additions + coinbase_additions)
    for k, v in addition_counter.items():
        if v > 1:
            return Err.DUPLICATE_OUTPUT, None

    # 14. Check for duplicate spends inside block
    removal_counter = collections.Counter(removals)
    for k, v in removal_counter.items():
        if v > 1:
            return Err.DOUBLE_SPEND, None

    # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
    # The fork point is the last block in common between the peak chain and the chain of `block`
    if peak is None or height == 0:
        fork_h: int = -1
    elif fork_point_with_peak is not None:
        fork_h = fork_point_with_peak
    else:
        fork_h = find_fork_point_in_chain(blocks, peak, blocks.block_record(block.prev_header_hash))

    # Get additions and removals since (after) fork_h but not including this block
    # The values include: the coin that was added, the height of the block in which it was confirmed, and the
    # timestamp of the block in which it was confirmed
    additions_since_fork: Dict[bytes32, Tuple[Coin, uint32, uint64]] = {}  # This includes coinbase additions
    removals_since_fork: Set[bytes32] = set()

    # For height 0, there are no additions and removals before this block, so we can skip
    if height > 0:
        # First, get all the blocks in the fork > fork_h, < block.height
        prev_block: Optional[FullBlock] = await block_store.get_full_block(block.prev_header_hash)
        reorg_blocks: Dict[uint32, FullBlock] = {}
        curr: Optional[FullBlock] = prev_block
        assert curr is not None
        while curr.height > fork_h:
            if curr.height == 0:
                break
            curr = await block_store.get_full_block(curr.prev_header_hash)
            assert curr is not None
            reorg_blocks[curr.height] = curr
        if fork_h != -1:
            assert len(reorg_blocks) == height - fork_h - 1

        curr = prev_block
        assert curr is not None
        while curr.height > fork_h:
            # Coin store doesn't contain coins from fork, we have to run generator for each block in fork
            if curr.transactions_generator is not None:
                # These blocks are in the past and therefore assumed to be valid, so get_block_generator won't raise
                curr_block_generator: Optional[BlockGenerator] = await get_block_generator(curr)
                assert curr_block_generator is not None and curr.transactions_info is not None
                curr_npc_result = get_name_puzzle_conditions(
                    curr_block_generator,
                    min(constants.MAX_BLOCK_COST_CLVM, curr.transactions_info.cost),
                    mempool_mode=False,
                    height=curr.height,
                    constants=constants,
                )
                removals_in_curr, additions_in_curr = tx_removals_and_additions(curr_npc_result.conds)
            else:
                removals_in_curr = []
                additions_in_curr = []

            for c_name in removals_in_curr:
                assert c_name not in removals_since_fork
                removals_since_fork.add(c_name)
            for c in additions_in_curr:
                coin_name = c.name()
                assert coin_name not in additions_since_fork
                assert curr.foliage_transaction_block is not None
                additions_since_fork[coin_name] = (c, curr.height, curr.foliage_transaction_block.timestamp)

            for coinbase_coin in curr.get_included_reward_coins():
                coin_name = coinbase_coin.name()
                assert coin_name not in additions_since_fork
                assert curr.foliage_transaction_block is not None
                additions_since_fork[coin_name] = (
                    coinbase_coin,
                    curr.height,
                    curr.foliage_transaction_block.timestamp,
                )
            if curr.height == 0:
                break
            curr = reorg_blocks[uint32(curr.height - 1)]
            assert curr is not None

    removal_coin_records: Dict[bytes32, CoinRecord] = {}
    # the removed coins we need to look up from the DB
    # i.e. all non-ephemeral coins
    removals_from_db: List[bytes32] = []
    for rem in removals:
        if rem in additions_dic:
            # Ephemeral coin
            rem_coin: Coin = additions_dic[rem]
            new_unspent: CoinRecord = CoinRecord(
                rem_coin,
                height,
                height,
                False,
                block.foliage_transaction_block.timestamp,
            )
            removal_coin_records[new_unspent.name] = new_unspent
        else:
            # This check applies to both coins created before fork (pulled from coin_store),
            # and coins created after fork (additions_since_fork)
            if rem in removals_since_fork:
                # This coin was spent in the fork
                return Err.DOUBLE_SPEND_IN_FORK, None
            removals_from_db.append(rem)

    unspent_records = await coin_store.get_coin_records(removals_from_db)

    # some coin spends we need to ensure exist in the fork branch. Both coins we
    # can't find in the DB, but also coins that were spent after the fork point
    look_in_fork: List[bytes32] = []
    for unspent in unspent_records:
        if unspent.confirmed_block_index <= fork_h:
            # Spending something in the current chain, confirmed before fork
            # (We ignore all coins confirmed after fork)
            if unspent.spent == 1 and unspent.spent_block_index <= fork_h:
                # Check for coins spent in an ancestor block
                return Err.DOUBLE_SPEND, None
            removal_coin_records[unspent.name] = unspent
        else:
            look_in_fork.append(unspent.name)

    if len(unspent_records) != len(removals_from_db):
        # some coins could not be found in the DB. We need to find out which
        # ones and look for them in additions_since_fork
        found: Set[bytes32] = set([u.name for u in unspent_records])
        for rem in removals_from_db:
            if rem in found:
                continue
            look_in_fork.append(rem)

    for rem in look_in_fork:
        # This coin is not in the current heaviest chain, so it must be in the fork
        if rem not in additions_since_fork:
            # Check for spending a coin that does not exist in this fork
            log.error(f"Err.UNKNOWN_UNSPENT: COIN ID: {rem} NPC RESULT: {npc_result}")
            return Err.UNKNOWN_UNSPENT, None
        new_coin, confirmed_height, confirmed_timestamp = additions_since_fork[rem]
        new_coin_record: CoinRecord = CoinRecord(
            new_coin,
            confirmed_height,
            uint32(0),
            False,
            confirmed_timestamp,
        )
        removal_coin_records[new_coin_record.name] = new_coin_record

    removed = 0
    for unspent in removal_coin_records.values():
        removed += unspent.coin.amount

    added = 0
    for coin, _ in additions:
        added += coin.amount

    # 16. Check that the total coin amount for added is <= removed
    if removed < added:
        return Err.MINTING_COIN, None

    fees = removed - added
    assert fees >= 0

    # reserve fee cannot be greater than UINT64_MAX per consensus rule.
    # run_generator() would fail
    assert_fee_sum: uint64 = uint64(0)
    if npc_result:
        assert npc_result.conds is not None
        assert_fee_sum = uint64(npc_result.conds.reserve_fee)

    # 17. Check that the assert fee sum <= fees, and that each reserved fee is non-negative
    if fees < assert_fee_sum:
        return Err.RESERVE_FEE_CONDITION_FAILED, None

    # 18. Check that the fee amount + farmer reward < maximum coin amount
    if fees + calculate_base_farmer_reward(height) > constants.MAX_COIN_AMOUNT:
        return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None

    # 19. Check that the computed fees are equal to the fees in the block header
    if block.transactions_info.fees != fees:
        return Err.INVALID_BLOCK_FEE_AMOUNT, None

    # 20. Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
    for unspent in removal_coin_records.values():
        if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
            return Err.WRONG_PUZZLE_HASH, None

    # 21. Verify conditions
    # verify absolute/relative height/time conditions
    if npc_result is not None:
        assert npc_result.conds is not None

        block_timestamp: uint64
        if height < constants.SOFT_FORK2_HEIGHT:
            block_timestamp = block.foliage_transaction_block.timestamp
        else:
            block_timestamp = prev_transaction_block_timestamp

        error = mempool_check_time_locks(
            removal_coin_records,
            npc_result.conds,
            prev_transaction_block_height,
            block_timestamp,
        )
        if error:
            return error, None

    # create hash_key list for aggsig check
    pairs_pks: List[bytes48] = []
    pairs_msgs: List[bytes] = []
    if npc_result:
        assert npc_result.conds is not None
        pairs_pks, pairs_msgs = pkm_pairs(
            npc_result.conds, constants.AGG_SIG_ME_ADDITIONAL_DATA, soft_fork=height >= constants.SOFT_FORK_HEIGHT
        )

    # 22. Verify aggregated signature
    # TODO: move this to pre_validate_blocks_multiprocessing so we can sync faster
    if not block.transactions_info.aggregated_signature:
        return Err.BAD_AGGREGATE_SIGNATURE, None

    # The pairing cache is not useful while syncing as each pairing is seen
    # only once, so the extra effort of populating it is not justified.
    # However, we force caching of pairings just for unfinished blocks
    # as the cache is likely to be useful when validating the corresponding
    # finished blocks later.
    if validate_signature:
        force_cache: bool = isinstance(block, UnfinishedBlock)
        if not cached_bls.aggregate_verify(
            pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature, force_cache
        ):
            return Err.BAD_AGGREGATE_SIGNATURE, None

    return None, npc_result
