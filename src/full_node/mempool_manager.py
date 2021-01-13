import collections
import time
from typing import Dict, Optional, Tuple, List, Set
import logging

from chiabip158 import PyBIP158
from blspy import G1Element, AugSchemeMPL, G2Element

from src.consensus.constants import ConsensusConstants
from src.consensus.sub_block_record import SubBlockRecord
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.full_node.bundle_tools import best_solution_program
from src.types.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.coin_record import CoinRecord
from src.types.mempool_item import MempoolItem
from src.full_node.mempool import Mempool
from src.types.sized_bytes import bytes32
from src.full_node.coin_store import CoinStore
from src.util.errors import Err
from src.util.clvm import int_from_bytes
from src.consensus.cost_calculator import calculate_cost_of_program
from src.full_node.mempool_check_conditions import mempool_check_conditions_dict
from src.util.condition_tools import pkm_pairs_for_conditions_dict
from src.util.ints import uint64, uint32
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from sortedcontainers import SortedDict

from src.wallet.cc_wallet.debug_spend_bundle import debug_spend_bundle

log = logging.getLogger(__name__)


class MempoolManager:
    def __init__(self, coin_store: CoinStore, consensus_constants: ConsensusConstants):
        self.constants: ConsensusConstants = consensus_constants

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self.potential_txs: Dict[bytes32, SpendBundle] = {}
        # Keep track of seen spend_bundles
        self.seen_bundle_hashes: Dict[bytes32, bytes32] = {}

        # old_mempools will contain transactions that were removed in the last 10 blocks
        self.old_mempools: SortedDict[uint32, Dict[bytes32, MempoolItem]] = SortedDict()  # pylint: disable=E1136
        self.coin_store = coin_store

        tx_per_sec = self.constants.TX_PER_SEC
        sec_per_block = self.constants.SUB_SLOT_TIME_TARGET // self.constants.SLOT_SUB_BLOCKS_TARGET
        block_buffer_count = self.constants.MEMPOOL_BLOCK_BUFFER

        # MEMPOOL_SIZE = 60000
        self.mempool_size = int(tx_per_sec * sec_per_block * block_buffer_count)
        self.potential_cache_size = 300
        self.seen_cache_size = 10000

        # The mempool will correspond to a certain peak
        self.peak: Optional[SubBlockRecord] = None
        self.mempool: Mempool = Mempool.create(self.mempool_size)

    async def create_bundle_from_mempool(self, peak_header_hash: bytes32) -> Optional[SpendBundle]:
        """
        Returns aggregated spendbundle that can be used for creating new block
        """
        if self.peak is None or self.peak.header_hash != peak_header_hash:
            return None
        cost_sum = 0
        spend_bundles: List[SpendBundle] = []
        for dic in self.mempool.sorted_spends.values():
            for item in dic.values():
                if item.cost + cost_sum <= self.constants.MAX_BLOCK_COST_CLVM:
                    spend_bundles.append(item.spend_bundle)
                    cost_sum += item.cost
                else:
                    break
        if len(spend_bundles) > 0:
            return SpendBundle.aggregate(spend_bundles)
        else:
            return None

    def get_filter(self) -> bytes:
        all_transactions: Set[bytes32] = set()
        byte_array_list = []
        for key, mempool_item in self.mempool.spends.items():
            if key not in all_transactions:
                all_transactions.add(key)
                byte_array_list.append(bytearray(key))

        tx_filter: PyBIP158 = PyBIP158(byte_array_list)
        return bytes(tx_filter.GetEncoded())

    def is_fee_enough(self, fees: uint64, cost: uint64) -> bool:
        """
        Determines whether any of the pools can accept a transaction with a given fees
        and cost.
        """
        if cost == 0:
            return False
        fees_per_cost = fees / cost
        print("Fee:", fees_per_cost, self.mempool.get_min_fee_rate())
        if not self.mempool.at_full_capacity() or fees_per_cost >= self.mempool.get_min_fee_rate():
            return True
        return False

    def maybe_pop_seen(self):
        while len(self.seen_bundle_hashes) > self.seen_cache_size:
            first_in = list(self.seen_bundle_hashes.keys())[0]
            self.seen_bundle_hashes.pop(first_in)

    async def add_spendbundle(
        self, new_spend: SpendBundle
    ) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
        """
        Tries to add spendbundle to either self.mempools or to_pool if it's specified.
        Returns true if it's added in any of pools, Returns error if it fails.
        """
        if self.peak is None:
            return None, MempoolInclusionStatus.FAILED, Err.MEMPOOL_NOT_INITIALIZED

        self.seen_bundle_hashes[new_spend.name()] = new_spend.name()
        self.maybe_pop_seen()

        # Calculate the cost and fees
        program = best_solution_program(new_spend)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        fail_reason, npc_list, cost = calculate_cost_of_program(program, self.constants.CLVM_COST_RATIO_CONSTANT, True)
        if fail_reason:
            debug_spend_bundle.debug_spend_bundle(new_spend)
            return None, MempoolInclusionStatus.FAILED, fail_reason

        # build removal list
        removal_names: List[bytes32] = new_spend.removal_names()

        additions = new_spend.additions()
        additions_dict: Dict[bytes32, Coin] = {}
        for add in additions:
            additions_dict[add.name()] = add

        addition_amount = uint64(0)

        # Check additions for max coin amount
        for coin in additions:
            if coin.amount >= self.constants.MAX_COIN_AMOUNT:
                return (
                    None,
                    MempoolInclusionStatus.FAILED,
                    Err.COIN_AMOUNT_EXCEEDS_MAXIMUM,
                )
            addition_amount = uint64(addition_amount + coin.amount)

        # Check for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return None, MempoolInclusionStatus.FAILED, Err.DUPLICATE_OUTPUT

        # Check for duplicate inputs
        removal_counter = collections.Counter(name for name in removal_names)
        for k, v in removal_counter.items():
            if v > 1:
                return None, MempoolInclusionStatus.FAILED, Err.DOUBLE_SPEND

        # Skip if already added
        if new_spend.name() in self.mempool.spends:
            return uint64(cost), MempoolInclusionStatus.SUCCESS, None

        removal_record_dict: Dict[bytes32, CoinRecord] = {}
        removal_coin_dict: Dict[bytes32, Coin] = {}

        unknown_unspent_error: bool = False
        removal_amount = uint64(0)
        for name in removal_names:
            removal_record = await self.coin_store.get_coin_record(name)
            if removal_record is None and name not in additions_dict:
                unknown_unspent_error = True
                break
            elif name in additions_dict:
                removal_coin = additions_dict[name]
                # TODO(straya): what timestamp to use here?
                removal_record = CoinRecord(
                    removal_coin,
                    uint32(self.peak.height + 1),
                    uint32(0),
                    False,
                    False,
                    uint64(int(time.time())),
                )

            assert removal_record is not None
            removal_amount = uint64(removal_amount + removal_record.coin.amount)
            removal_record_dict[name] = removal_record
            removal_coin_dict[name] = removal_record.coin

        if unknown_unspent_error:
            return None, MempoolInclusionStatus.FAILED, Err.UNKNOWN_UNSPENT

        if addition_amount > removal_amount:
            print(addition_amount, removal_amount)
            return None, MempoolInclusionStatus.FAILED, Err.MINTING_COIN

        fees = removal_amount - addition_amount
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.ASSERT_FEE in npc.condition_dict:
                fee_list: List[ConditionVarPair] = npc.condition_dict[ConditionOpcode.ASSERT_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    assert_fee_sum = assert_fee_sum + fee

        if fees < assert_fee_sum:
            return (
                None,
                MempoolInclusionStatus.FAILED,
                Err.ASSERT_FEE_CONDITION_FAILED,
            )

        if cost == 0:
            return None, MempoolInclusionStatus.FAILED, Err.UNKNOWN

        fees_per_cost: float = fees / cost

        # If pool is at capacity check the fee, if not then accept even without the fee
        if self.mempool.at_full_capacity():
            if fees == 0:
                return None, MempoolInclusionStatus.FAILED, Err.INVALID_FEE_LOW_FEE
            if fees_per_cost < self.mempool.get_min_fee_rate():
                return None, MempoolInclusionStatus.FAILED, Err.INVALID_FEE_LOW_FEE

        # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
        # Use this information later when constructing a block
        fail_reason, conflicts = await self.check_removals(removal_record_dict)
        # If there is a mempool conflict check if this spendbundle has a higher fee per cost than all others
        tmp_error: Optional[Err] = None
        conflicting_pool_items: Dict[bytes32, MempoolItem] = {}
        if fail_reason is Err.MEMPOOL_CONFLICT:
            for conflicting in conflicts:
                sb: MempoolItem = self.mempool.removals[conflicting.name()]
                conflicting_pool_items[sb.name] = sb
            for item in conflicting_pool_items.values():
                if item.fee_per_cost >= fees_per_cost:
                    self.add_to_potential_tx_set(new_spend)
                    return (
                        uint64(cost),
                        MempoolInclusionStatus.PENDING,
                        Err.MEMPOOL_CONFLICT,
                    )
        elif fail_reason:
            return None, MempoolInclusionStatus.FAILED, fail_reason

        if tmp_error:
            return None, MempoolInclusionStatus.FAILED, tmp_error

        # Verify conditions, create hash_key list for aggsig check
        pks: List[G1Element] = []
        msgs: List[bytes32] = []
        error: Optional[Err] = None
        for npc in npc_list:
            coin_record: CoinRecord = removal_record_dict[npc.coin_name]
            # Check that the revealed removal puzzles actually match the puzzle hash
            if npc.puzzle_hash != coin_record.coin.puzzle_hash:
                log.warning("Mempool rejecting transaction because of wrong puzzle_hash")
                log.warning(f"{npc.puzzle_hash} != {coin_record.coin.puzzle_hash}")
                return None, MempoolInclusionStatus.FAILED, Err.WRONG_PUZZLE_HASH

            error = mempool_check_conditions_dict(
                coin_record, new_spend, npc.condition_dict, uint32(self.peak.height + 1)
            )

            if error:
                if error is Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED or error is Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED:
                    self.add_to_potential_tx_set(new_spend)
                    return uint64(cost), MempoolInclusionStatus.PENDING, error
                break

            for pk, message in pkm_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name):
                pks.append(pk)
                msgs.append(message)

        if error:
            return None, MempoolInclusionStatus.FAILED, error

        # Verify aggregated signature
        if len(pks) == 0 and len(msgs) == 0:
            validates = new_spend.aggregated_signature == G2Element.infinity()
        else:
            validates = AugSchemeMPL.aggregate_verify(pks, msgs, new_spend.aggregated_signature)
        if not validates:
            log.warning(f"{pks} {msgs} {new_spend}")
            return None, MempoolInclusionStatus.FAILED, Err.BAD_AGGREGATE_SIGNATURE

        # Remove all conflicting Coins and SpendBundles
        if fail_reason:
            mempool_item: MempoolItem
            for mempool_item in conflicting_pool_items.values():
                self.mempool.remove_spend(mempool_item)

        new_item = MempoolItem(new_spend, fees_per_cost, uint64(fees), uint64(cost))
        self.mempool.add_to_pool(new_item, additions, removal_coin_dict)
        return uint64(cost), MempoolInclusionStatus.SUCCESS, None

    async def check_removals(self, removals: Dict[bytes32, CoinRecord]) -> Tuple[Optional[Err], List[Coin]]:
        """
        This function checks for double spends, unknown spends and conflicting transactions in mempool.
        Returns Error (if any), dictionary of Unspents, list of coins with conflict errors (if any any).
        """
        assert self.peak is not None
        conflicts: List[Coin] = []

        for record in removals.values():
            removal = record.coin
            # 1. Checks if it's been spent already
            if record.spent == 1:
                return Err.DOUBLE_SPEND, []
            # 2. Checks if there's a mempool conflict
            if removal.name() in self.mempool.removals:
                conflicts.append(removal)

        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, []

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
        if bundle_hash in self.mempool.spends:
            return self.mempool.spends[bundle_hash].spend_bundle
        return None

    async def new_peak(self, new_peak: Optional[SubBlockRecord]):
        """
        Called when a new peak is available, we try to recreate a mempool for the new tip.
        """
        if new_peak is None:
            return
        if self.peak == new_peak:
            return
        self.peak = new_peak

        old_pool = self.mempool
        self.mempool = Mempool.create(self.mempool_size)

        for item in old_pool.spends.values():
            await self.add_spendbundle(item.spend_bundle)

        for tx in self.potential_txs.values():
            await self.add_spendbundle(tx)

    async def get_items_not_in_filter(self, mempool_filter: PyBIP158) -> List[MempoolItem]:
        items: List[MempoolItem] = []
        checked_items: Set[bytes32] = set()

        for key, item in self.mempool.spends.items():
            if key in checked_items:
                continue
            if mempool_filter.Match(bytearray(key)):
                checked_items.add(key)
                continue
            checked_items.add(key)
            items.append(item)

        return items
