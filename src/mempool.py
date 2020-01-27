import collections
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List

from src.consensus.constants import constants as consensus_constants
from src.types.full_block import FullBlock
from src.types.hashable import SpendBundle, CoinName, Coin, Unspent
from src.types.hashable.SpendBundle import BundleHash
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.unspent_store import UnspentStore
from src.util.Conditions import ConditionOpcode, ConditionVarPair
from src.util.ConsensusError import Err
from src.util.check_conditions import get_name_puzzle_conditions, check_conditions_dict
from src.util.consensus import hash_key_pairs_for_conditions_dict
from src.util.ints import uint64, uint32
from sortedcontainers import SortedDict

tx_per_sec = 20
sec_per_block = 5 * 60
block_buffer_count = 10
# 60000
mempool_size = tx_per_sec * sec_per_block * block_buffer_count
POTENTIAL_CACHE_SIZE = 300


@dataclass(frozen=True)
class MempoolItem:
    spend_bundle: SpendBundle
    fee_per_cost: float
    fee: uint64
    cost: uint64

    def __lt__(self, other):
        # TODO test to see if it's < or >
        return self.fee_per_cost < other.fee_per_cost

    @property
    def name(self) -> bytes32:
        return self.spend_bundle.name()


class Pool:
    header_block: HeaderBlock
    spends: Dict[BundleHash, MempoolItem]
    sorted_spends: SortedDict[float, Dict[BundleHash, MempoolItem]]
    additions: Dict[CoinName, MempoolItem]
    removals: Dict[CoinName, MempoolItem]
    min_fee: uint64

    # if new min fee is added
    @staticmethod
    async def create(head: HeaderBlock):
        self = Pool()
        self.spends = {}
        self.additions = {}
        self.removals = {}
        self.min_fee = 0
        self.sorted_spends = SortedDict()
        return self

    def get_min_fee_rate(self) -> float:
        if self.at_full_capacity():
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            return fee_per_cost
        else:
            return 0

    def remove_spend(self, item: MempoolItem):
        removals: List[Coin] = item.spend_bundle.removals()
        additions: List[Coin] = item.spend_bundle.additions()
        for rem in removals:
            del self.removals[rem.name()]
        for add in additions:
            del self.additions[add.name()]
        del self.spends[item.name]
        del self.sorted_spends[item.fee_per_cost][item.name]
        dic = self.sorted_spends[item.fee_per_cost]
        if len(dic.values) == 0:
            del self.sorted_spends[item.fee_per_cost]

    def add_to_pool(self, item: MempoolItem, additions: List[Coin], removals_dic: Dict[bytes32, Coin]):
        if self.at_full_capacity():
            # Val is Dict[hash, MempoolItem]
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            to_remove = val.values()[0]
            self.remove_spend(to_remove)

        self.spends[item.name] = item
        self.sorted_spends[item.fee_per_cost] = item

        for add in additions:
            self.additions[add.name()] = item
        for key in removals_dic.keys():
            self.removals[key] = item

    def at_full_capacity(self) -> bool:
        return len(self.spends.keys()) >= mempool_size


@dataclass(frozen=True)
class NPC:
    coin_name: bytes32
    puzzle_hash: bytes32
    condition_dict: Dict[ConditionOpcode, List[ConditionVarPair]]


MAX_COIN_AMOUNT = int(1 << 48)


class Mempool:
    def __init__(self, unspent_store: UnspentStore, override_constants: Dict = None):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self.potential_txs: Dict[bytes32, SpendBundle] = {}

        self.allSpend: Dict[bytes32: SpendBundle] = {}
        self.allSeen: Dict[bytes32: bytes32] = {}
        # Mempool for each tip
        self.mempools: Dict[bytes32, Pool] = {}

        # old_mempools will contain transactions that were removed in the last 10 blocks
        self.old_mempools: SortedDict[uint32, Dict[bytes32, MempoolItem]] = SortedDict()
        self.unspent_store = unspent_store

    # TODO implement creating block from mempool
    # TODO Aggregate all SpendBundles for the tip and return only one
    # TODO 6000 cost units
    async def create_bundle_for_tip(self, header_block: HeaderBlock) -> Optional[SpendBundle]:
        """
        Returns aggregated spendbundle that can be used for creating new block
        """
        return None

    async def add_spendbundle(self, new_spend: SpendBundle, to_pool: Pool = None) -> Tuple[bool, Optional[Err]]:
        self.allSeen[new_spend.name()] = new_spend.name()

        # Calculate the cost and fees
        cost = new_spend.get_signature_count()
        fees = new_spend.fees()
        # TODO Cost is hack, currently it just counts number of signatures (count can be 0)
        # TODO Remove when real cost function is implemented
        if cost == 0:
            return False, Err.UNKNOWN
        fees_per_cost: float = fees / cost

        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        fail_reason, npc_list = get_name_puzzle_conditions(new_spend)
        if fail_reason:
            return False, fail_reason

        # build removal list
        removals_dic: Dict[bytes32, Coin] = new_spend.removals_dict()
        additions = new_spend.additions()

        # Check additions for max coin amount
        for coin in additions:
            if coin.amount >= MAX_COIN_AMOUNT:
                return False, Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

        #  Watch out for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return False, Err.DUPLICATE_OUTPUT

        # Spend might be valid for on pool but not for others
        added_count = 0
        errors: List[Err] = []
        targets: List[Pool]

        if to_pool:
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
                    errors.append(Err.INVALID_FEE_NO_FEE)
                    continue
                if fees_per_cost < pool.get_min_fee_rate():
                    # Add to potential tx set, maybe fee get's lower in future
                    errors.append(Err.INVALID_FEE_LOW_FEE)
                    continue

            # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
            # Use this information later when constructing a block
            fail_reason, unspents, conflicts = await self.check_removals(new_spend.additions(), new_spend.removals(),
                                                                         pool)
            # If there is a mempool conflict check if this spendbundle has a higher fee per cost than all others
            tmp_error: Optional[Err] = None
            conflicting_pool_items: Dict[bytes32: MempoolItem] = {}
            if fail_reason is Err.MEMPOOL_CONFLICT:
                for conflicting in conflicts:
                    sb: MempoolItem = pool.removals[conflicting.name()]
                    conflicting_pool_items[sb.name] = sb
                for item in conflicting_pool_items.values():
                    if item.fee_per_cost >= fees_per_cost:
                        tmp_error = Err.MEMPOOL_CONFLICT
                        await self.add_to_potential_tx_set(new_spend)
                        break
            elif fail_reason:
                errors.append(fail_reason)
                continue

            if tmp_error:
                errors.append(tmp_error)
                continue

            # Check that the revealed removal puzzles actually match the puzzle hash
            for unspent in unspents:
                coin = removals_dic[unspent.coin.name()]
                if unspent.coin.puzzle_hash != coin.puzzle_hash:
                    return False, Err.WRONG_PUZZLE_HASH

            # Verify conditions, create hash_key list for aggsig check
            hash_key_pairs = []
            error: Optional[Err] = None
            for npc in npc_list:
                unspent: Unspent = unspents[npc.coin_name]
                error = check_conditions_dict(unspent, new_spend, npc.condition_dict, pool)
                if error:
                    if (error is Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
                            or
                            error is Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED):
                        await self.add_to_potential_tx_set(new_spend)
                    break
                hash_key_pairs.extend(hash_key_pairs_for_conditions_dict(npc.condition_dict))
            if error:
                errors.append(error)
                continue

            # Verify aggregated signature
            if not new_spend.aggregated_signature.validate(hash_key_pairs):
                return False, Err.BAD_AGGREGATE_SIGNATURE

            # Remove all conflicting Coins and SpendBundles
            if fail_reason:
                item: MempoolItem
                for item in conflicting_pool_items.values():
                    pool.remove_spend(item)

            new_item = MempoolItem(new_spend, fees_per_cost, uint64(fees), cost)
            pool.add_to_pool(new_item, additions, removals_dic)
            self.allSpend[new_spend.name] = new_spend
            added_count += 1

        return added_count > 0, None

    async def check_removals(self, additions: List[Coin], removals: List[Coin],
                             mempool: Pool) -> Tuple[Optional[Err], Dict[bytes32, Unspent], Optional[List[Coin]]]:
        """
        This function checks for double spends, unknown spends and conflicting transactions in mempool.
        Returns Error (if any), dictionary of Unspents, list of coins with conflict errors (if any any).
        """
        removals_counter: Dict[CoinName, int] = {}
        unspents: Dict[bytes32, Unspent] = {}
        conflicts: List[Coin] = []
        for removal in removals:
            # 0. Checks for double spend inside same spend_bundle
            if not removals_counter[removal.name()]:
                removals_counter[removal.name()] = 1
            else:
                return Err.DOUBLE_SPEND, {}, None
            # 1. Checks if removed coin is created in spend_bundle (For ephemeral coins)
            if removal in additions:
                # Setting ephemeral coin confirmed index to current + 1
                if removal.name() in unspents:
                    return Err.DOUBLE_SPEND, {}, None
                unspents[removal.name()] = Unspent(removal, mempool.header_block.height + 1, 0, 0)
                continue
            # 2. Checks we have it in the unspent_store
            unspent: Optional[Unspent] = await self.unspent_store.get_unspent(removal.name(), mempool.header_block)
            if unspent is None:
                return Err.UNKNOWN_UNSPENT, {}, None
            # 3. Checks if it's been spent already
            if unspent.spent == 1:
                return Err.DOUBLE_SPEND, {}, None
            # 4. Checks if there's a mempool conflict
            if removal.name() in mempool.removals:
                conflicts.append(removal)

            unspents[unspent.coin.name()] = unspent
        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, unspents, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, unspents, None

    async def add_to_potential_tx_set(self, spend: SpendBundle):
        self.potential_txs[spend.name] = spend

        while len(self.potential_txs) > POTENTIAL_CACHE_SIZE:
            first_in = self.potential_txs.keys()[0]
            del self.potential_txs[first_in]

    async def seen(self, bundle_hash: bytes32) -> bool:
        """ Return true if we saw this spendbundle before """
        if self.allSeen[bundle_hash] is None:
            return False
        else:
            return True

    async def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        """ Returns a full SpendBundle for a given bundle_hash """
        if bundle_hash in self.allSpend:
            return self.allSpend[bundle_hash]
        return None

    async def new_tips(self, new_tips: List[FullBlock]):
        new_pools: Dict[bytes32, Pool] = {}
        for tip in new_tips:
            if tip.header_hash in self.mempools:
                # Nothing to change, we already have mempool for this head
                new_pools[tip.header_hash] = self.mempools[tip.header_hash]
                continue
            if tip.prev_header_hash in self.mempools:
                # Update old mempool
                new_pool: Pool = self.mempools[tip.prev_header_hash]
                await self.update_pool(new_pool, tip)
            else:
                # Create mempool for new head
                if len(self.old_mempools) > 0:
                    new_pool: Pool = await Pool.create(tip.header_block)

                    # If old spends height is bigger than the new tip height, try adding spends to the pool
                    for height in self.old_mempools.keys():
                        if height > tip.height:
                            old_spend_dict: Dict[bytes32, MempoolItem] = self.old_mempools[height]
                            await self.add_old_spends_to_pool(new_pool, old_spend_dict)

                    await self.initialize_pool_from_current_pools(new_pool)
                else:
                    new_pool: Pool = await Pool.create(tip.header_block)
                    await self.initialize_pool_from_current_pools(new_pool)

            await self.add_potential_spends_to_pool(new_pool)
            new_pools[new_pool.header_block.header_hash] = new_pool

        self.mempools = new_pools

    async def update_pool(self, pool: Pool, new_tip: FullBlock):
        removals, additions = new_tip.removals_and_additions()
        pool.header_block = new_tip.header_block
        items: Dict[bytes32, MempoolItem] = {}

        # Remove transactions that were included in new block, and save them in old_mempool cache
        for rem in removals:
            if rem in pool.removals:
                rem_item = pool.removals[rem]
                items[rem_item.name] = rem_item

        for add_coin in additions:
            if add_coin.name() in pool.additions:
                rem_item = pool.additions[add_coin.name()]
                items[rem_item.name] = rem_item

        for item in items.values():
            pool.remove_spend(item)

        await self.add_to_old_mempool_cache(list(items.values()), new_tip.header_block)

    async def add_to_old_mempool_cache(self, items: List[MempoolItem], header: HeaderBlock):
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
            keys = dic_for_height.keys()
            lowest_h = keys[0]
            dic_for_height.pop(lowest_h)

    async def initialize_pool_from_current_pools(self, pool: Pool):
        tried_already: Dict[bytes32, bytes32] = {}
        current_pool: Pool
        for current_pool in self.mempools:
            for item in current_pool.spends.values():
                # Don't try to add same mempool item twice
                if item.name in tried_already:
                    continue
                tried_already[item.name] = item.name
                res, err = await self.add_spendbundle(item.spend_bundle, pool)

    async def add_old_spends_to_pool(self, pool: Pool, old_spends: Dict[bytes32, MempoolItem]):
        for old in old_spends.values():
            await self.add_spendbundle(old.spend_bundle, pool)

    async def add_potential_spends_to_pool(self, pool: Pool):
        for tx in self.potential_txs.values():
            await self.add_spendbundle(tx, pool)
