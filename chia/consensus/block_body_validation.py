from __future__ import annotations

import collections
import logging
from collections.abc import Awaitable, Collection
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    FullBlock,
    SpendBundleConditions,
    UnfinishedBlock,
    compute_merkle_set_root,
    is_canonical_serialization,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from chiabip158 import PyBIP158

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.check_time_locks import check_time_locks
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.types.blockchain_format.coin import Coin, hash_coin_ids
from chia.types.coin_record import CoinRecord
from chia.util.errors import Err
from chia.util.hash import std_hash

log = logging.getLogger(__name__)

#  peak->  o
#  main    |
#  chain   o  o <- peak_height  \ additions and removals
#          |  |    peak_hash    | from these blocks are
#          o  o                 / recorded
#          \ /
#           o <- fork_height
#           |    this block is shared by the main chain
#           o    and the fork
#           :


@dataclass(frozen=True)
class ForkAdd:
    coin: Coin
    confirmed_height: uint32
    timestamp: uint64
    hint: Optional[bytes]
    is_coinbase: bool
    # This means matching parent puzzle hash and amount
    same_as_parent: bool


@dataclass(frozen=True)
class ForkRem:
    puzzle_hash: bytes32
    height: uint32


@dataclass
class ForkInfo:
    # defines the last block shared by the fork and the main chain. additions
    # and removals are from the block following this height up to and including
    # the peak_height
    fork_height: int
    # the ForkInfo object contain all additions and removals made by blocks
    # starting at fork_height+1 up to and including peak_height.
    # When validating the block at height 0, the peak_height is -1, that's why
    # it needs to be signed
    peak_height: int
    # the header hash of the peak block of this fork
    peak_hash: bytes32
    # The additions include coinbase additions
    additions_since_fork: dict[bytes32, ForkAdd] = field(default_factory=dict)
    # coin-id, ForkRem
    removals_since_fork: dict[bytes32, ForkRem] = field(default_factory=dict)
    # the header hashes of the blocks, starting with the one-past fork_height
    # i.e. the header hash of fork_height + 1 is stored in block_hashes[0]
    # followed by fork_height + 2, and so on.
    block_hashes: list[bytes32] = field(default_factory=list)

    def reset(self, fork_height: int, header_hash: bytes32) -> None:
        self.fork_height = fork_height
        self.peak_height = fork_height
        self.peak_hash = header_hash
        self.additions_since_fork = {}
        self.removals_since_fork = {}
        self.block_hashes = []

    def update_fork_peak(self, block: FullBlock, header_hash: bytes32) -> None:
        """Updates `self` with `block`'s height and `header_hash`."""
        assert self.peak_height == block.height - 1
        assert len(self.block_hashes) == self.peak_height - self.fork_height
        assert block.height == self.fork_height + 1 + len(self.block_hashes)
        self.block_hashes.append(header_hash)
        self.peak_height = int(block.height)
        self.peak_hash = header_hash

    def include_reward_coins(self, block: FullBlock) -> None:
        """Updates `self` with `block`'s reward coins."""
        for coin in block.get_included_reward_coins():
            assert block.foliage_transaction_block is not None
            timestamp = block.foliage_transaction_block.timestamp
            coin_id = coin.name()
            assert coin_id not in self.additions_since_fork
            self.additions_since_fork[coin_id] = ForkAdd(
                coin, block.height, timestamp, hint=None, is_coinbase=True, same_as_parent=False
            )

    def include_spends(self, conds: Optional[SpendBundleConditions], block: FullBlock, header_hash: bytes32) -> None:
        self.update_fork_peak(block, header_hash)
        if conds is not None:
            assert block.foliage_transaction_block is not None
            timestamp = block.foliage_transaction_block.timestamp
            for spend in conds.spends:
                spend_coin_id = bytes32(spend.coin_id)
                self.removals_since_fork[spend_coin_id] = ForkRem(bytes32(spend.puzzle_hash), block.height)
                for puzzle_hash, amount, hint in spend.create_coin:
                    coin = Coin(spend_coin_id, bytes32(puzzle_hash), uint64(amount))
                    same_as_parent = coin.puzzle_hash == spend.puzzle_hash and amount == spend.coin_amount
                    self.additions_since_fork[coin.name()] = ForkAdd(
                        coin, block.height, timestamp, hint=hint, is_coinbase=False, same_as_parent=same_as_parent
                    )
        self.include_reward_coins(block)

    def include_block(
        self,
        additions: list[tuple[Coin, Optional[bytes]]],
        removals: list[tuple[bytes32, Coin]],
        block: FullBlock,
        header_hash: bytes32,
    ) -> None:
        self.update_fork_peak(block, header_hash)
        if block.foliage_transaction_block is not None:
            timestamp = block.foliage_transaction_block.timestamp
            spent_coins: dict[bytes32, Coin] = {}
            for spend_id, spend in removals:
                spent_coins[bytes32(spend_id)] = spend
                self.removals_since_fork[bytes32(spend_id)] = ForkRem(bytes32(spend.puzzle_hash), block.height)
            for coin, hint in additions:
                parent = spent_coins.get(coin.parent_coin_info)
                assert parent is not None
                same_as_parent = coin.puzzle_hash == parent.puzzle_hash and coin.amount == parent.amount
                self.additions_since_fork[coin.name()] = ForkAdd(
                    coin, block.height, timestamp, hint=hint, is_coinbase=False, same_as_parent=same_as_parent
                )
        self.include_reward_coins(block)

    def rollback(self, header_hash: bytes32, height: int) -> None:
        assert height <= self.peak_height
        self.peak_height = height
        self.peak_hash = header_hash
        self.additions_since_fork = {k: v for k, v in self.additions_since_fork.items() if v.confirmed_height <= height}
        self.removals_since_fork = {k: v for k, v in self.removals_since_fork.items() if v.height <= height}


def validate_block_merkle_roots(
    block_additions_root: bytes32,
    block_removals_root: bytes32,
    tx_additions: list[tuple[Coin, bytes32]],
    tx_removals: list[bytes32],
) -> Optional[Err]:
    # Create addition Merkle set
    puzzlehash_coins_map: dict[bytes32, list[bytes32]] = {}

    for coin, coin_name in tx_additions:
        if coin.puzzle_hash in puzzlehash_coins_map:
            puzzlehash_coins_map[coin.puzzle_hash].append(coin_name)
        else:
            puzzlehash_coins_map[coin.puzzle_hash] = [coin_name]

    # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    additions_merkle_items: list[bytes32] = []
    for puzzle, coin_ids in puzzlehash_coins_map.items():
        additions_merkle_items.append(puzzle)
        additions_merkle_items.append(hash_coin_ids(coin_ids))

    additions_root = bytes32(compute_merkle_set_root(additions_merkle_items))
    removals_root = bytes32(compute_merkle_set_root(tx_removals))

    if block_additions_root != additions_root:
        return Err.BAD_ADDITION_ROOT
    if block_removals_root != removals_root:
        return Err.BAD_REMOVAL_ROOT

    return None


async def validate_block_body(
    constants: ConsensusConstants,
    records: BlockRecordsProtocol,
    get_coin_records: Callable[[Collection[bytes32]], Awaitable[list[CoinRecord]]],
    block: Union[FullBlock, UnfinishedBlock],
    height: uint32,
    conds: Optional[SpendBundleConditions],
    fork_info: ForkInfo,
    *,
    log_coins: bool = False,
) -> Optional[Err]:
    """
    This assumes the header block has been completely validated.
    Validates the transactions and body of the block.
    Returns None if everything validates correctly, or an Err if something does
        not validate.
    conds is the result of running the generator with the previous generators
        refs. It must be set for transaction blocks and must be None for
        non-transaction blocks.
    fork_info specifies the fork context of this block. In case the block
        extends the main chain, it can be empty, but if the block extends a fork
        of the main chain, the fork info is mandatory in order to validate the block.
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
            return Err.NOT_BLOCK_BUT_HAS_DATA

        prev_tb: Optional[BlockRecord] = records.block_record(block.prev_header_hash)
        assert prev_tb is not None
        while not prev_tb.is_transaction_block:
            prev_tb = records.block_record(prev_tb.prev_hash)
            assert prev_tb is not None
        assert prev_tb.timestamp is not None
        if len(block.transactions_generator_ref_list) > 0:
            return Err.NOT_BLOCK_BUT_HAS_DATA

        assert fork_info.peak_height == height - 1

        assert conds is None
        # This means the block is valid
        return None

    # All checks below this point correspond to transaction blocks
    # 2. For blocks, foliage block, transactions info must not be empty
    if block.foliage_transaction_block is None or block.transactions_info is None:
        return Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA
    assert block.foliage_transaction_block is not None

    # keeps track of the reward coins that need to be incorporated
    expected_reward_coins: set[Coin] = set()

    # 3. The transaction info hash in the Foliage block must match the transaction info
    if block.foliage_transaction_block.transactions_info_hash != std_hash(block.transactions_info):
        return Err.INVALID_TRANSACTIONS_INFO_HASH

    # 4. The foliage block hash in the foliage block must match the foliage block
    if block.foliage.foliage_transaction_block_hash != std_hash(block.foliage_transaction_block):
        return Err.INVALID_FOLIAGE_BLOCK_HASH

    # 5. The reward claims must be valid for the previous blocks, and current block fees
    # If height == 0, expected_reward_coins will be left empty
    if height > 0:
        # Add reward claims for all blocks from the prev prev block, until the prev block (including the latter)
        prev_transaction_block = records.block_record(block.foliage_transaction_block.prev_transaction_block_hash)
        assert prev_transaction_block is not None
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
            curr_b = records.block_record(prev_transaction_block.prev_hash)
            assert curr_b is not None
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
                curr_b = records.block_record(curr_b.prev_hash)
                assert curr_b is not None

    if set(block.transactions_info.reward_claims_incorporated) != expected_reward_coins:
        return Err.INVALID_REWARD_COINS

    if len(block.transactions_info.reward_claims_incorporated) != len(expected_reward_coins):
        return Err.INVALID_REWARD_COINS

    removals: list[bytes32] = []

    # we store coins paired with their names in order to avoid computing the
    # coin name multiple times, we store it next to the coin while validating
    # the block
    coinbase_additions: list[tuple[Coin, bytes32]] = [(c, c.name()) for c in expected_reward_coins]
    additions: list[tuple[Coin, bytes32]] = []
    removals_puzzle_dic: dict[bytes32, bytes32] = {}
    cost: uint64 = uint64(0)

    # In header validation we check that timestamp is not more than 5 minutes into the future
    # 6. No transactions before INITIAL_TRANSACTION_FREEZE timestamp
    # (this test has been removed)

    # 7a. The generator root must be the hash of the serialized bytes of
    #     the generator for this block (or zeroes if no generator)
    if block.transactions_generator is not None:
        if std_hash(bytes(block.transactions_generator)) != block.transactions_info.generator_root:
            return Err.INVALID_TRANSACTIONS_GENERATOR_HASH
    else:
        if block.transactions_info.generator_root != bytes([0] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_HASH

    # 8a. The generator_ref_list must be the hash of the serialized bytes of
    #     the generator ref list for this block (or 'one' bytes [0x01] if no generator)
    # 8b. The generator ref list length must be less than or equal to MAX_GENERATOR_REF_LIST_SIZE entries
    # 8c. The generator ref list must not point to a height >= this block's height
    if block.transactions_generator_ref_list in (None, []):
        if block.transactions_info.generator_refs_root != bytes([1] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    else:
        # If we have a generator reference list, we must have a generator
        if block.transactions_generator is None:
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT

        # The generator_refs_root must be the hash of the concatenation of the list[uint32]
        generator_refs_hash = std_hash(b"".join([i.stream_to_bytes() for i in block.transactions_generator_ref_list]))
        if block.transactions_info.generator_refs_root != generator_refs_hash:
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
        if len(block.transactions_generator_ref_list) > constants.MAX_GENERATOR_REF_LIST_SIZE:
            return Err.TOO_MANY_GENERATOR_REFS
        if any([index >= height for index in block.transactions_generator_ref_list]):
            return Err.FUTURE_GENERATOR_REFS

    if block.transactions_generator is not None:
        # Get List of names removed, puzzles hashes for removed coins and conditions created

        cost = uint64(0 if conds is None else conds.cost)

        # 7. Check that cost <= MAX_BLOCK_COST_CLVM
        log.debug(
            f"Cost: {cost} max: {constants.MAX_BLOCK_COST_CLVM} "
            f"percent full: {round(100 * (cost / constants.MAX_BLOCK_COST_CLVM), 2)}%"
        )
        if cost > constants.MAX_BLOCK_COST_CLVM:
            return Err.BLOCK_COST_EXCEEDS_MAX

        # 8. The CLVM program must not return any errors
        assert conds is not None
        assert conds.validated_signature

        if prev_transaction_block_height >= constants.HARD_FORK2_HEIGHT:
            if not is_canonical_serialization(bytes(block.transactions_generator)):
                return Err.INVALID_TRANSACTIONS_GENERATOR_ENCODING

        for spend in conds.spends:
            removals.append(bytes32(spend.coin_id))
            removals_puzzle_dic[bytes32(spend.coin_id)] = bytes32(spend.puzzle_hash)
            for puzzle_hash, amount, _ in spend.create_coin:
                c = Coin(bytes32(spend.coin_id), bytes32(puzzle_hash), uint64(amount))
                additions.append((c, c.name()))
    else:
        assert conds is None

    # 9. Check that the correct cost is in the transactions info
    if block.transactions_info.cost != cost:
        return Err.INVALID_BLOCK_COST

    additions_dic: dict[bytes32, Coin] = {}
    # 10. Check additions for max coin amount
    # Be careful to check for 64 bit overflows in other languages. This is the max 64 bit unsigned integer
    # We will not even reach here because Coins do type checking (uint64)
    for coin, coin_name in additions + coinbase_additions:
        additions_dic[coin_name] = coin
        if coin.amount < 0:
            return Err.COIN_AMOUNT_NEGATIVE

        if coin.amount > constants.MAX_COIN_AMOUNT:
            return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

    # 11. Validate addition and removal roots
    root_error = validate_block_merkle_roots(
        block.foliage_transaction_block.additions_root,
        block.foliage_transaction_block.removals_root,
        additions + coinbase_additions,
        removals,
    )
    if root_error is not None:
        return root_error

    # 12. The additions and removals must result in the correct filter
    byte_array_tx: list[bytearray] = []

    for coin, _ in additions + coinbase_additions:
        byte_array_tx.append(bytearray(coin.puzzle_hash))
    for coin_name in removals:
        byte_array_tx.append(bytearray(coin_name))

    bip158: PyBIP158 = PyBIP158(byte_array_tx)
    encoded_filter = bytes(bip158.GetEncoded())
    filter_hash = std_hash(encoded_filter)

    if filter_hash != block.foliage_transaction_block.filter_hash:
        return Err.INVALID_TRANSACTIONS_FILTER_HASH

    # 13. Check for duplicate outputs in additions
    addition_counter = collections.Counter(coin_name for _, coin_name in additions + coinbase_additions)
    for count in addition_counter.values():
        if count > 1:
            return Err.DUPLICATE_OUTPUT

    # 14. Check for duplicate spends inside block
    removal_counter = collections.Counter(removals)
    for count in removal_counter.values():
        if count > 1:
            return Err.DOUBLE_SPEND

    # 15. Check if removals exist and were not previously spent. (unspent_db + diff_store + this_block)
    # The fork point is the last block in common between the peak chain and the chain of `block`

    assert fork_info.fork_height < height
    assert fork_info.peak_height == height - 1

    removal_coin_records: dict[bytes32, CoinRecord] = {}
    # the removed coins we need to look up from the DB
    # i.e. all non-ephemeral coins
    removals_from_db: list[bytes32] = []
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
            if rem in fork_info.removals_since_fork:
                # This coin was spent in the fork
                log.error(f"Err.DOUBLE_SPEND_IN_FORK {fork_info.removals_since_fork[rem]}")
                return Err.DOUBLE_SPEND_IN_FORK
            removals_from_db.append(rem)

    unspent_records = await get_coin_records(removals_from_db)

    # some coin spends we need to ensure exist in the fork branch. Both coins we
    # can't find in the DB, but also coins that were spent after the fork point
    look_in_fork: list[bytes32] = []
    for unspent in unspent_records:
        if unspent.confirmed_block_index <= fork_info.fork_height:
            # Spending something in the current chain, confirmed before fork
            # (We ignore all coins confirmed after fork)
            if unspent.spent == 1 and unspent.spent_block_index <= fork_info.fork_height:
                # Check for coins spent in an ancestor block
                return Err.DOUBLE_SPEND
            removal_coin_records[unspent.name] = unspent
        else:
            look_in_fork.append(unspent.name)

    if log_coins and len(look_in_fork) > 0:
        log.info("%d coins spent after fork", len(look_in_fork))

    if len(unspent_records) != len(removals_from_db):
        # some coins could not be found in the DB. We need to find out which
        # ones and look for them in additions_since_fork
        found: set[bytes32] = {u.name for u in unspent_records}
        for rem in removals_from_db:
            if rem in found:
                continue
            look_in_fork.append(rem)

    if log_coins and len(look_in_fork) > 0:
        log.info("coins spent in fork: %s", ",".join([f"{name}"[0:6] for name in look_in_fork]))

    for rem in look_in_fork:
        # This coin is not in the current heaviest chain, so it must be in the fork
        if rem not in fork_info.additions_since_fork:
            # Check for spending a coin that does not exist in this fork
            log.error(f"Err.UNKNOWN_UNSPENT: COIN ID: {rem} fork_info: {fork_info}")
            return Err.UNKNOWN_UNSPENT
        addition: ForkAdd = fork_info.additions_since_fork[rem]
        new_coin_record: CoinRecord = CoinRecord(
            addition.coin,
            addition.confirmed_height,
            uint32(0),
            False,
            addition.timestamp,
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
        return Err.MINTING_COIN

    fees = removed - added
    assert fees >= 0

    # reserve fee cannot be greater than UINT64_MAX per consensus rule.
    # run_generator() would fail
    assert_fee_sum = uint64(0 if conds is None else conds.reserve_fee)

    # 17. Check that the assert fee sum <= fees, and that each reserved fee is non-negative
    if fees < assert_fee_sum:
        return Err.RESERVE_FEE_CONDITION_FAILED

    # 18. Check that the fee amount + farmer reward < maximum coin amount
    if fees + calculate_base_farmer_reward(height) > constants.MAX_COIN_AMOUNT:
        return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

    # 19. Check that the computed fees are equal to the fees in the block header
    if block.transactions_info.fees != fees:
        return Err.INVALID_BLOCK_FEE_AMOUNT

    # 20. Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
    for unspent in removal_coin_records.values():
        if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
            return Err.WRONG_PUZZLE_HASH

    # 21. Verify conditions
    # verify absolute/relative height/time conditions
    if conds is not None:
        error = check_time_locks(
            removal_coin_records,
            conds,
            prev_transaction_block_height,
            prev_transaction_block_timestamp,
        )
        if error is not None:
            return error

    # 22. Verify aggregated signature is done in pre-validation
    if not block.transactions_info.aggregated_signature:
        return Err.BAD_AGGREGATE_SIGNATURE

    return None
