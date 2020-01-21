import collections
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple, List

import clvm

from src.consensus.constants import constants as consensus_constants
from src.farming.farming_tools import best_solution_program
from src.types.full_block import FullBlock
from src.types.hashable import SpendBundle, CoinName, ProgramHash, Program, Coin, Unspent
from src.types.hashable.SpendBundle import BundleHash
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.unspent_store import UnspentStore
from src.util.Conditions import ConditionOpcode, ConditionVarPair
from src.util.ConsensusError import Err
from src.util.consensus import conditions_dict_for_solution, hash_key_pairs_for_conditions_dict
from src.util.ints import uint32


@dataclass(frozen=True)
class Pool:
    header_block: HeaderBlock
    spends: Dict[BundleHash: SpendBundle]
    additions: Dict[CoinName: SpendBundle]
    removals: Dict[CoinName: SpendBundle]
    conflicting: Dict[BundleHash: BundleHash]


@dataclass(frozen=True)
class NPC:
    coin_name: bytes32
    puzzle_hash: bytes32
    condition_dict: Dict[ConditionOpcode, List[ConditionVarPair]]


MAX_COIN_AMOUNT = int(1 << 48)


async def get_name_puzzle_conditions(spend_bundle: SpendBundle) -> Tuple[Optional[Err], Optional[List[NPC]]]:
    """
    Return a list of tuples of (coin_name, solved_puzzle_hash, conditions_dict)
    """
    program = best_solution_program(spend_bundle)
    try:
        sexp = clvm.eval_f(clvm.eval_f, program, [])
    except clvm.EvalError.EvalError:
        breakpoint()
        return Err.INVALID_COIN_SOLUTION, None

    npc_list = []
    for name_solution in sexp.as_iter():
        _ = name_solution.as_python()
        if len(_) != 2:
            return Err.INVALID_COIN_SOLUTION, None
        if not isinstance(_[0], bytes) or len(_[0]) != 32:
            return Err.INVALID_COIN_SOLUTION, None
        coin_name = CoinName(_[0])
        if not isinstance(_[1], list) or len(_[1]) != 2:
            return Err.INVALID_COIN_SOLUTION, None
        puzzle_solution_program = name_solution.rest().first()
        puzzle_program = puzzle_solution_program.first()
        puzzle_hash = ProgramHash(Program(puzzle_program))
        try:
            error, conditions_dict = conditions_dict_for_solution(puzzle_solution_program)
            if error:
                return error, None
        except clvm.EvalError.EvalError:
            return Err.INVALID_COIN_SOLUTION, None
        npc: NPC = NPC(coin_name, puzzle_hash, conditions_dict)
        npc_list.append(npc)

    return None, npc_list


# TODO keep some mempool spendbundle history for the purpose of restoring in case of reorg
class Mempool:
    def __init__(self, unspent_store: UnspentStore, override_constants: Dict = {}):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        # Transactions that were unable to enter mempool
        self.potential_transactions = dict()
        self.allSpend: Dict[bytes32: SpendBundle] = []
        self.allSeen: Dict[bytes32: bytes32] = []
        # Mempool for each tip
        self.mempools: Tuple[Optional[Pool], Optional[Pool], Optional[Pool]] = None, None, None
        self.unspent_store = unspent_store

    # TODO implement creating block from mempool
    # TODO Maximize transaction fees, handle conflicting transactions
    # TODO Aggregate all SpendBundles for the tip and return only one
    async def create_bundle_for_tip(self, header_block: HeaderBlock) -> Optional[SpendBundle]:
        """
        Returns aggregated spendbundle that can be used for creating new block
        """
        return None

    async def add_spendbundle(self, new_spend: SpendBundle) -> Tuple[bool, Optional[Err]]:
        self.allSeen[new_spend.name()] = new_spend.name()

        # Calculate the cost and fees
        cost: uint32 = new_spend.get_signature_count()
        fees: uint32 = new_spend.fees()
        fees_per_cost = fees / cost

        # TODO if pools is not full accept even without fee
        if fees == 0:
            return False, Err.INVALID_FEE_NO_FEE
        if fees_per_cost < 1:
            return False, Err.INVALID_FEE_LOW_FEE

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
        for pool in self.mempools:

            # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
            # TODO Keep track of Mempool conflicts
            # TODO Use this information later when constructing a block
            fail_reason, unspents, conflicts = await self.check_removals(new_spend.additions(), new_spend.removals(),
                                                                         pool)
            if fail_reason:
                continue

            # Check that the revealed removal puzzles actually match the puzzle hash
            for unspent in unspents:
                coin = removals_dic[unspent.coin.name()]
                if unspent.coin.puzzle_hash != coin.puzzle_hash:
                    return False, Err.WRONG_PUZZLE_HASH

            # Verify conditions, create hash_key list for aggsig check
            hash_key_pairs = []
            error = None
            for npc in npc_list:
                unspent: Unspent = unspents[npc.coin_name]
                error = self.check_conditions_dict(unspent, new_spend, npc.condition_dict, pool)
                if error:
                    break
                hash_key_pairs.extend(hash_key_pairs_for_conditions_dict(npc.condition_dict))
            if error:
                continue

            # Verify aggregated signature
            if not new_spend.aggregated_signature.validate(hash_key_pairs):
                return False, Err.BAD_AGGREGATE_SIGNATURE

            pool.spends[new_spend.name()] = new_spend
            for add in additions:
                pool.additions[add.name()] = new_spend
            for key in removals_dic.keys():
                pool.removals[key] = new_spend
            # TODO mark conflicting
            added_count += 1

        return added_count > 0, None

    async def check_removals(self, additions: List[Coin], removals: List[Coin],
                             mempool: Pool) -> Tuple[Optional[Err], Dict[bytes32, Unspent], Optional[List[Coin]]]:
        """
        This function checks for double spends and unknown spends, if it fails returns why
        0: Checks for double spend inside same spend_bundle
        1: Checks if removed coin is created in spend_bundle (For ephemeral coins)
        2: Checks we have it in the unspent_store
        3: Checks if it's been spent already
        4: Checks if there's mempool conflict
        5: If coins can be spent return list of unspents as we see them in local storage
        Returns Error (if any), Dict of Unspents, List of coins with conflict error (if any any)
        """
        removals_counter: Dict[CoinName, int] = {}
        unspents: Dict[bytes32, Unspent] = {}
        conflicts: List[Coin] = []
        for removal in removals:
            # 0:
            if not removals_counter[removal.name()]:
                removals_counter[removal.name()] = 1
            else:
                return Err.DOUBLE_SPEND, {}, None
            # 1:
            if removal in additions:
                # Setting ephemeral coin confirmed index to current + 1
                unspents[removal.name()] = Unspent(removal, mempool.header_block.height + 1, 0, 0)
                continue
            # 2:
            unspent: Optional[Unspent] = await self.unspent_store.get_unspent(removal.name(), mempool.header_block)
            if unspent is None:
                return Err.UNKNOWN_UNSPENT, {}, None
            # 3:
            if unspent.spent == 1:
                return Err.DOUBLE_SPEND, {}, None
            # 4:
            if removal.name() in mempool.removals:
                conflicts.append(removal)

            unspents[unspent.coin.name()] = unspent
        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, unspents, conflicts
        # 5:
        return None, unspents, None

    async def seen(self, bundle_hash: bytes32) -> bool:
        """ Return true if we saw this spendbundle before """
        if self.allSeen[bundle_hash] is None:
            return False
        else:
            return True

    async def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        """ Returns a full SpendBundle for a given bundle_hash """
        return self.allSpend[bundle_hash]

    # TODO create new mempool for this tip
    # TODO Logic for extending and replacing existing ones
    async def add_tip(self, add_tip: FullBlock, remove_tip: Optional[HeaderBlock]):
        if remove_tip:
            await self.remove_tip(remove_tip)

    # TODO Remove mempool
    async def remove_tip(self, removed_tip: HeaderBlock):
        """ Removes mempool for given tip """
        del self.mempools[removed_tip]
        print("remove tip")

    def assert_coin_consumed(self, condition: ConditionVarPair, spend_bundle: SpendBundle, mempool: Pool) -> Optional[
        Err]:
        """
        Checks coin consumed conditions
        Returns None if conditions are met, if not returns the reason why it failed
        """
        # TODO figure out if this opcode takes single coin_id or a list of coin_ids
        bundle_removals = spend_bundle.removals_dict()
        coin_name = condition.var1
        if coin_name not in mempool.removals and \
                coin_name not in bundle_removals:
            return Err.ASSERT_COIN_CONSUMED_FAILED

    def assert_my_coin_id(self, condition: ConditionVarPair, unspent: Unspent) -> Optional[Err]:
        if unspent.coin.name() != condition.var1:
            return Err.ASSERT_MY_COIN_ID_FAILED
        return None

    def assert_block_index_exceeds(self, condition: ConditionVarPair, unspent: Unspent, mempool: Pool) -> Optional[Err]:
        try:
            expected_block_index = clvm.casts.int_from_bytes(condition.var1)
        except ValueError:
            return Err.INVALID_CONDITION
        # + 1 because min block it can be included is +1 from current
        if mempool.header_block.height + 1 <= expected_block_index:
            return Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
        return None

    def assert_block_age_exceeds(self, condition: ConditionVarPair, unspent: Unspent, mempool: Pool) -> Optional[Err]:
        try:
            expected_block_age = clvm.casts.int_from_bytes(condition.var1)
            expected_block_index = expected_block_age + unspent.confirmed_block_index
        except ValueError:
            return Err.INVALID_CONDITION
        if mempool.header_block.height + 1 <= expected_block_index:
            return Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
        return None

    def check_conditions_dict(self, unspent: Unspent, spend_bundle: SpendBundle,
                              conditions_dict: Dict[ConditionOpcode, ConditionVarPair], mempool: Pool) -> Optional[Err]:
        """
        Check all conditions against current state.
        """
        for condition_id, cvp in conditions_dict.items():
            error = None
            if condition_id is ConditionOpcode.ASSERT_COIN_CONSUMED:
                error = self.assert_coin_consumed(cvp, spend_bundle, mempool)
            elif condition_id is ConditionOpcode.ASSERT_MY_COIN_ID:
                error = self.assert_my_coin_id(cvp, unspent)
            elif condition_id is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                error = self.assert_block_index_exceeds(cvp, unspent, mempool)
            elif condition_id is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                error = self.assert_block_age_exceeds(cvp, unspent, mempool)
            # TODO add stuff from Will's pull req

            if error:
                return error

        return None
