import collections
import sys
import traceback
from typing import Dict, Optional, Tuple, List, Set
import logging

from chiabip158 import PyBIP158

from src.consensus.constants import constants as consensus_constants
from src.util.bundle_tools import best_solution_program
from src.types.full_block import FullBlock
from src.types.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.coin_record import CoinRecord
from src.types.header import Header
from src.types.mempool_item import MempoolItem
from src.full_node.mempool import Mempool
from src.types.sized_bytes import bytes32
from src.full_node.coin_store import CoinStore
from src.util.errors import Err
from src.util.cost_calculator import calculate_cost_of_program
from src.util.mempool_check_conditions import mempool_check_conditions_dict
from src.util.condition_tools import hash_key_pairs_for_conditions_dict
from src.util.ints import uint64, uint32
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from sortedcontainers import SortedDict


log = logging.getLogger(__name__)


class MempoolManager:
    def __init__(self, unspent_store: CoinStore, override_constants: Dict = {}):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants.copy()
        for key, value in override_constants.items():
            self.constants[key] = value

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self.potential_txs: Dict[bytes32, SpendBundle] = {}
        # Keep track of seen spend_bundles
        self.seen_bundle_hashes: Dict[bytes32, bytes32] = {}
        # Mempool for each tip
        self.mempools: Dict[bytes32, Mempool] = {}

        # old_mempools will contain transactions that were removed in the last 10 blocks
        self.old_mempools: SortedDict[uint32, Dict[bytes32, MempoolItem]] = SortedDict()
        self.unspent_store = unspent_store

        tx_per_sec = self.constants["TX_PER_SEC"]
        sec_per_block = self.constants["BLOCK_TIME_TARGET"]
        block_buffer_count = self.constants["MEMPOOL_BLOCK_BUFFER"]

        # MEMPOOL_SIZE = 60000
        self.mempool_size = tx_per_sec * sec_per_block * block_buffer_count
        self.potential_cache_size = 300
        self.seen_cache_size = 10000
        self.coinbase_freeze = self.constants["COINBASE_FREEZE_PERIOD"]

    async def create_bundle_for_tip(self, header: Header) -> Optional[SpendBundle]:
        """
        Returns aggregated spendbundle that can be used for creating new block
        """
        if header.header_hash in self.mempools:
            mempool: Mempool = self.mempools[header.header_hash]
            cost_sum = 0
            spend_bundles: List[SpendBundle] = []
            for dic in mempool.sorted_spends.values():
                for item in dic.values():
                    if (
                        item.cost + cost_sum
                        <= self.constants["MAX_BLOCK_COST_CLVM"]
                    ):
                        spend_bundles.append(item.spend_bundle)
                        cost_sum += item.cost
                    else:
                        break
            if len(spend_bundles) > 0:
                block_bundle = SpendBundle.aggregate(spend_bundles)
                return block_bundle
            else:
                return None
        else:
            return None

    def get_filter(self) -> bytes:
        all_transactions: Set[bytes32] = set()
        byte_array_list = []
        for _, mempool in self.mempools.items():
            for key, mempool_item in mempool.spends.items():
                if key not in all_transactions:
                    all_transactions.add(key)
                    byte_array_list.append(bytearray(key))

        filter: PyBIP158 = PyBIP158(byte_array_list)
        return bytes(filter.GetEncoded())

    def is_fee_enough(self, fees: uint64, cost: uint64) -> bool:
        """
        Determines whether any of the pools can accept a transaction with a given fees
        and cost.
        """
        if fees < 0 or cost < 1:
            return False
        fees_per_cost = fees / cost
        for pool in self.mempools.values():
            if not pool.at_full_capacity() or fees_per_cost >= pool.get_min_fee_rate():
                return True
        return False

    def maybe_pop_seen(self):
        while len(self.seen_bundle_hashes) > self.seen_cache_size:
            first_in = list(self.seen_bundle_hashes.keys())[0]
            self.seen_bundle_hashes.pop(first_in)

    async def add_spendbundle(
        self, new_spend: SpendBundle, to_pool: Mempool = None
    ) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
        """
        Tries to add spendbundle to either self.mempools or to_pool if it's specified.
        Returns true if it's added in any of pools, Returns error if it fails.
        """
        self.seen_bundle_hashes[new_spend.name()] = new_spend.name()
        self.maybe_pop_seen()

        # Calculate the cost and fees
        program = best_solution_program(new_spend)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        fail_reason, npc_list, cost = calculate_cost_of_program(program)
        if fail_reason:
            return None, MempoolInclusionStatus.FAILED, fail_reason

        fees = new_spend.fees()

        if cost == 0:
            return None, MempoolInclusionStatus.FAILED, Err.UNKNOWN
        fees_per_cost: float = fees / cost

        # build removal list
        removals_dic: Dict[bytes32, Coin] = new_spend.removals_dict()
        additions = new_spend.additions()

        # Check additions for max coin amount
        for coin in additions:
            if coin.amount >= uint64.from_bytes(self.constants["MAX_COIN_AMOUNT"]):
                return (
                    None,
                    MempoolInclusionStatus.FAILED,
                    Err.COIN_AMOUNT_EXCEEDS_MAXIMUM,
                )

        #  Watch out for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return None, MempoolInclusionStatus.FAILED, Err.DUPLICATE_OUTPUT

        # Spend might be valid for on pool but not for others
        added_count = 0
        errors: List[Err] = []
        targets: List[Mempool]

        # If the trasaction is added to potential set (to be retried), this is set.
        added_to_potential: bool = False
        potential_error: Optional[Err] = None

        if to_pool is not None:
            targets = [to_pool]
        else:
            targets = list(self.mempools.values())
        for pool in targets:
            # Check if more is created than spent
            if fees < 0:
                errors.append(Err.MINTING_COIN)
                continue
            # If pool is at capacity check the fee, if not then accept even without the fee
            if pool.at_full_capacity():
                if fees == 0:
                    errors.append(Err.INVALID_FEE_LOW_FEE)
                    continue
                if fees_per_cost < pool.get_min_fee_rate():
                    errors.append(Err.INVALID_FEE_LOW_FEE)
                    continue

            # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
            # Use this information later when constructing a block
            fail_reason, unspents, conflicts = await self.check_removals(
                new_spend.additions(), new_spend.removals(), pool
            )
            # If there is a mempool conflict check if this spendbundle has a higher fee per cost than all others
            tmp_error: Optional[Err] = None
            conflicting_pool_items: Dict[bytes32, MempoolItem] = {}
            if fail_reason is Err.MEMPOOL_CONFLICT:
                for conflicting in conflicts:
                    sb: MempoolItem = pool.removals[conflicting.name()]
                    conflicting_pool_items[sb.name] = sb
                for item in conflicting_pool_items.values():
                    if item.fee_per_cost >= fees_per_cost:
                        tmp_error = Err.MEMPOOL_CONFLICT
                        self.add_to_potential_tx_set(new_spend)
                        added_to_potential = True
                        potential_error = Err.MEMPOOL_CONFLICT
                        break
            elif fail_reason:
                errors.append(fail_reason)
                continue

            if tmp_error:
                errors.append(tmp_error)
                continue

            # Check that the revealed removal puzzles actually match the puzzle hash
            for unspent in unspents.values():
                coin = removals_dic[unspent.coin.name()]
                if unspent.coin.puzzle_hash != coin.puzzle_hash:
                    return None, MempoolInclusionStatus.FAILED, Err.WRONG_PUZZLE_HASH

            # Verify conditions, create hash_key list for aggsig check
            hash_key_pairs = []
            error: Optional[Err] = None
            for npc in npc_list:
                coin_record: CoinRecord = unspents[npc.coin_name]
                error = mempool_check_conditions_dict(
                    coin_record, new_spend, npc.condition_dict, pool
                )
                if error:
                    if (
                        error is Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
                        or error is Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
                    ):
                        self.add_to_potential_tx_set(new_spend)
                        added_to_potential = True
                        potential_error = error
                    break
                hash_key_pairs.extend(
                    hash_key_pairs_for_conditions_dict(
                        npc.condition_dict, npc.coin_name
                    )
                )
            if error:
                errors.append(error)
                continue

            # Verify aggregated signature
            if not new_spend.aggregated_signature.validate(hash_key_pairs):
                return None, MempoolInclusionStatus.FAILED, Err.BAD_AGGREGATE_SIGNATURE

            # Remove all conflicting Coins and SpendBundles
            if fail_reason:
                mitem: MempoolItem
                for mitem in conflicting_pool_items.values():
                    pool.remove_spend(mitem)

            new_item = MempoolItem(new_spend, fees_per_cost, uint64(fees), uint64(cost))
            pool.add_to_pool(new_item, additions, removals_dic)

            added_count += 1

        if added_count > 0:
            return uint64(cost), MempoolInclusionStatus.SUCCESS, None
        elif added_to_potential:
            return uint64(cost), MempoolInclusionStatus.PENDING, potential_error
        else:
            return None, MempoolInclusionStatus.FAILED, errors[0]

    async def check_removals(
        self, additions: List[Coin], removals: List[Coin], mempool: Mempool
    ) -> Tuple[Optional[Err], Dict[bytes32, CoinRecord], List[Coin]]:
        """
        This function checks for double spends, unknown spends and conflicting transactions in mempool.
        Returns Error (if any), dictionary of Unspents, list of coins with conflict errors (if any any).
        """
        removals_counter: Dict[bytes32, int] = {}
        coin_records: Dict[bytes32, CoinRecord] = {}
        conflicts: List[Coin] = []
        for removal in removals:
            # 0. Checks for double spend inside same spend_bundle
            if not removal.name() in removals_counter:
                removals_counter[removal.name()] = 1
            else:
                return Err.DOUBLE_SPEND, {}, []
            # 1. Checks if removed coin is created in spend_bundle (For ephemeral coins)
            if removal in additions:
                # Setting ephemeral coin confirmed index to current + 1
                if removal.name() in coin_records:
                    return Err.DOUBLE_SPEND, {}, []
                coin_records[removal.name()] = CoinRecord(
                    removal, mempool.header.height + 1, uint32(0), False, False
                )
                continue
            # 2. Checks we have it in the unspent_store
            unspent: Optional[CoinRecord] = await self.unspent_store.get_coin_record(
                removal.name(), mempool.header
            )
            if unspent is None:
                return Err.UNKNOWN_UNSPENT, {}, []
            # 3. Checks if it's been spent already
            if unspent.spent == 1:
                return Err.DOUBLE_SPEND, {}, []
            # 4. Checks if there's a mempool conflict
            if removal.name() in mempool.removals:
                conflicts.append(removal)
            if unspent.coinbase == 1:
                if (
                    mempool.header.height + 1
                    < unspent.confirmed_block_index + self.coinbase_freeze
                ):
                    return Err.COINBASE_NOT_YET_SPENDABLE, {}, []

            coin_records[unspent.coin.name()] = unspent
        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, coin_records, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, coin_records, []

    def add_to_potential_tx_set(self, spend: SpendBundle):
        """
        Adds SpendBundles that have failed to be added to the pool in potential tx set.
        This is later used to retry to add them.
        """
        self.potential_txs[spend.name()] = spend

        while len(self.potential_txs) > self.potential_cache_size:
            first_in = list(self.potential_txs.keys())[0]
            self.potential_txs.pop(first_in)

    def seen(self, bundle_hash: bytes32) -> bool:
        """ Return true if we saw this spendbundle before """
        if bundle_hash in self.seen_bundle_hashes:
            return True
        else:
            return False

    def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        """ Returns a full SpendBundle if it's inside one the mempools"""
        for pool in self.mempools.values():
            if bundle_hash in pool.spends:
                return pool.spends[bundle_hash].spend_bundle
        return None

    async def new_tips(self, new_tips: List[FullBlock]):
        """
        Called when new tips are available, we try to recreate a mempool for each of the new tips.
        For tip that we already have mempool we don't do anything.
        """
        new_pools: Dict[bytes32, Mempool] = {}

        min_mempool_height = sys.maxsize
        for pool in self.mempools.values():
            if pool.header.height < min_mempool_height:
                min_mempool_height = pool.header.height

        for tip in new_tips:
            if tip.header_hash in self.mempools:
                # Nothing to change, we already have mempool for this head
                new_pools[tip.header_hash] = self.mempools[tip.header_hash]
                continue

            new_pool = Mempool.create(tip.header, self.mempool_size)
            if tip.height < min_mempool_height:
                # Update old mempool
                if len(self.old_mempools) > 0:
                    log.info(f"Creating new pool: {new_pool.header}")

                    # If old spends height is bigger than the new tip height, try adding spends to the pool
                    for height in self.old_mempools.keys():
                        old_spend_dict: Dict[
                            bytes32, MempoolItem
                        ] = self.old_mempools[height]
                        await self.add_old_spends_to_pool(new_pool, old_spend_dict)

            await self.initialize_pool_from_current_pools(new_pool)
            await self.add_potential_spends_to_pool(new_pool)
            new_pools[new_pool.header.header_hash] = new_pool

        for pool in self.mempools.values():
            if pool.header.header_hash not in new_pools:
                await self.add_to_old_mempool_cache(list(pool.spends.values()), pool.header)

        self.mempools = new_pools

    async def create_filter_for_pools(self) -> bytes:
        # Create filter for items in mempools
        byte_array_tx: List[bytes32] = []
        added_items: Set[bytes32] = set()
        for mempool in self.mempools:
            for key, item in mempool.spends.items():
                if key in added_items:
                    continue
                added_items.add(key)
                byte_array_tx.append(bytearray(item.name()))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter = bytes(bip158.GetEncoded())

        return encoded_filter

    async def get_items_not_in_filter(
        self, mempool_filter: PyBIP158
    ) -> List[MempoolItem]:
        items: List[MempoolItem] = []
        checked_items: Set[bytes32] = set()

        for _, mempool in self.mempools.items():
            for key, item in mempool.spends.items():
                if key in checked_items:
                    continue
                if mempool_filter.Match(bytearray(key)):
                    checked_items.add(key)
                    continue
                checked_items.add(key)
                items.append(item)

        return items

    async def add_to_old_mempool_cache(self, items: List[MempoolItem], header: Header):
        dic_for_height: Dict[bytes32, MempoolItem]

        # Store them in proper dictionary for the height they were farmed at
        if header.height in self.old_mempools:
            dic_for_height = self.old_mempools[header.height]
        else:
            dic_for_height = {}
            self.old_mempools[header.height] = dic_for_height

        for item in items:
            if item.name in dic_for_height:
                continue
            dic_for_height[item.name] = item

        # Keep only last 10 heights in cache
        while len(dic_for_height) > 10:
            keys = list(dic_for_height.keys())
            lowest_h = keys[0]
            dic_for_height.pop(lowest_h)

    async def initialize_pool_from_current_pools(self, pool: Mempool):
        tried_already: Dict[bytes32, bytes32] = {}
        current_pool: Mempool
        for current_pool in self.mempools.values():
            for item in current_pool.spends.values():
                # Don't try to add same mempool item twice
                if item.name in tried_already:
                    continue
                tried_already[item.name] = item.name
                await self.add_spendbundle(item.spend_bundle, pool)

    async def add_old_spends_to_pool(
        self, pool: Mempool, old_spends: Dict[bytes32, MempoolItem]
    ):
        for old in old_spends.values():
            await self.add_spendbundle(old.spend_bundle, pool)

    async def add_potential_spends_to_pool(self, pool: Mempool):
        for tx in self.potential_txs.values():
            await self.add_spendbundle(tx, pool)
