import collections

from typing import Awaitable, Callable, Dict, List, Optional
from blspy import AugSchemeMPL, G1Element
from clvm.casts import int_from_bytes

from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import mempool_check_conditions_dict, get_name_puzzle_conditions
from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import pkm_pairs
from chia.util.errors import Err, ValidationError
from chia.util.generator_tools import additions_for_npc
from chia.util.ints import uint32, uint64


async def check_spend_bundle(
    bundle: SpendBundle,
    constants: ConsensusConstants,
    current_height: uint32,
    current_time: uint64,
    get_coin_states: Callable[[List[bytes32]], Awaitable[List[CoinState]]],
    height_to_time: Callable[[uint32], Awaitable[uint64]],
) -> Optional[Err]:
    try:
        generator = simple_solution_generator(bundle)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        npc_result: NPCResult = get_name_puzzle_conditions(
            generator, constants.MAX_BLOCK_COST_CLVM, cost_per_byte=constants.COST_PER_BYTE, mempool_mode=True
        )

        if npc_result.error is not None:
            return Err(npc_result.error)

        pks: List[bytes48]
        msgs: List[bytes]
        pks, msgs = pkm_pairs(npc_result.npc_list, constants.AGG_SIG_ME_ADDITIONAL_DATA)
        pks = [G1Element.from_bytes(pk) for pk in pks]

        # Verify aggregated signature
        if not AugSchemeMPL.aggregate_verify(pks, msgs, bundle.aggregated_signature):
            return Err.BAD_AGGREGATE_SIGNATURE

        npc_list = npc_result.npc_list
        assert npc_result.error is None
        cost = npc_result.cost

        if cost > constants.MAX_BLOCK_COST_CLVM:
            # we shouldn't ever end up here, since the cost is limited when we
            # execute the CLVM program.
            return Err.BLOCK_COST_EXCEEDS_MAX

        removal_names: List[bytes32] = [npc.coin_name for npc in npc_list]
        if set(removal_names) != set([s.name() for s in bundle.removals()]):
            return Err.INVALID_SPEND_BUNDLE

        additions = additions_for_npc(npc_list)

        additions_dict: Dict[bytes32, Coin] = {}
        for add in additions:
            additions_dict[add.name()] = add

        addition_amount: int = 0
        # Check additions for max coin amount
        for coin in additions:
            if coin.amount < 0:
                return Err.COIN_AMOUNT_NEGATIVE
            if coin.amount > constants.MAX_COIN_AMOUNT:
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM
            addition_amount = addition_amount + coin.amount
        # Check for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT
        # Check for duplicate inputs
        removal_counter = collections.Counter(name for name in removal_names)
        for k, v in removal_counter.items():
            if v > 1:
                return Err.DOUBLE_SPEND

        coins_to_check_unspent: List[bytes32] = []
        removal_amount: int = sum(r.amount for r in bundle.removals())
        for name in removal_names:
            if name not in additions_dict:
                coins_to_check_unspent.append(name)

        if addition_amount > removal_amount:
            return Err.MINTING_COIN

        fees = uint64(removal_amount - addition_amount)
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.RESERVE_FEE in npc.condition_dict:
                fee_list: List[ConditionWithArgs] = npc.condition_dict[ConditionOpcode.RESERVE_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    if fee < 0:
                        return Err.RESERVE_FEE_CONDITION_FAILED
                    assert_fee_sum = assert_fee_sum + fee
        if fees < assert_fee_sum:
            return Err.RESERVE_FEE_CONDITION_FAILED

        if cost == 0:
            return Err.UNKNOWN

        coin_states: List[CoinState] = await get_coin_states(coins_to_check_unspent)
        if len(coin_states) != len(coins_to_check_unspent):
            return Err.UNKNOWN_UNSPENT
        for cs in coin_states:
            if cs.created_height is None:
                return Err.UNKNOWN_UNSPENT
            if cs.spent_height is not None:
                return Err.DOUBLE_SPEND

        # Verify conditions, create hash_key list for aggsig check
        for npc in npc_list:
            coin_state: CoinState = next(cs for cs in coin_states if cs.coin.name() == npc.coin_name)
            assert coin_state.created_height is not None
            # Check that the revealed removal puzzles actually match the puzzle hash
            if npc.puzzle_hash != cs.coin.puzzle_hash:
                return Err.WRONG_PUZZLE_HASH

            error = mempool_check_conditions_dict(
                CoinRecord(
                    coin_state.coin,
                    coin_state.created_height,
                    uint32(0),
                    False,  # doesn't matter
                    (await height_to_time(coin_state.created_height)),
                ),
                npc.condition_dict,
                current_height,
                current_time,
            )

            if error:
                return error

        return None
    except ValidationError as e:
        return e.code
    except Exception:
        return Err.UNKNOWN
