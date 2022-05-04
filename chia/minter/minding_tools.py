from typing import Optional, List, Set

from blspy import G2Element, AugSchemeMPL, PrivateKey

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    solution_for_conditions,
    calculate_synthetic_secret_key,
    DEFAULT_HIDDEN_PUZZLE_HASH,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_create_coin_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_assert_my_coin_id_condition,
    make_reserve_fee_condition,
    make_create_coin_announcement,
    make_assert_coin_announcement,
    make_create_puzzle_announcement,
    make_assert_puzzle_announcement,
)
from chia.wallet.util.wallet_types import AmountWithPuzzlehash


def make_solution(
    primaries: List[AmountWithPuzzlehash],
    min_time=0,
    me=None,
    coin_announcements: Optional[Set[bytes]] = None,
    coin_announcements_to_assert: Optional[Set[bytes32]] = None,
    puzzle_announcements: Optional[Set[bytes]] = None,
    puzzle_announcements_to_assert: Optional[Set[bytes32]] = None,
    fee=0,
) -> Program:
    assert fee >= 0
    condition_list = []
    if len(primaries) > 0:
        for primary in primaries:
            if "memos" in primary:
                memos: Optional[List[bytes]] = primary["memos"]
                if memos is not None and len(memos) == 0:
                    memos = None
            else:
                memos = None
            condition_list.append(make_create_coin_condition(primary["puzzlehash"], primary["amount"], memos))
    if min_time > 0:
        condition_list.append(make_assert_absolute_seconds_exceeds_condition(min_time))
    if me:
        condition_list.append(make_assert_my_coin_id_condition(me["id"]))
    if fee:
        condition_list.append(make_reserve_fee_condition(fee))
    if coin_announcements:
        for announcement in coin_announcements:
            condition_list.append(make_create_coin_announcement(announcement))
    if coin_announcements_to_assert:
        for announcement_hash in coin_announcements_to_assert:
            condition_list.append(make_assert_coin_announcement(announcement_hash))
    if puzzle_announcements:
        for announcement in puzzle_announcements:
            condition_list.append(make_create_puzzle_announcement(announcement))
    if puzzle_announcements_to_assert:
        for announcement_hash in puzzle_announcements_to_assert:
            condition_list.append(make_assert_puzzle_announcement(announcement_hash))
    return solution_for_conditions(condition_list)


async def sign(wallet_sk: PrivateKey, spends: List[CoinSpend], constants) -> SpendBundle:
    sigs: List[G2Element] = []
    for spend in spends:
        matched, puzzle_args = did_wallet_puzzles.match_did_puzzle(spend.puzzle_reveal.to_program())
        if matched:
            p2_puzzle, _, _, _, _ = puzzle_args
            puzzle_hash = p2_puzzle.get_tree_hash()
            synthetic_secret_key = calculate_synthetic_secret_key(wallet_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
            error, conditions, cost = conditions_dict_for_solution(
                spend.puzzle_reveal.to_program(),
                spend.solution.to_program(),
                constants.MAX_BLOCK_COST_CLVM,
            )

            if conditions is not None:
                synthetic_pk = synthetic_secret_key.get_g1()
                for pk, msg in pkm_pairs_for_conditions_dict(
                    conditions, spend.coin.name(), constants.AGG_SIG_ME_ADDITIONAL_DATA
                ):
                    try:
                        assert bytes(synthetic_pk) == pk
                        sigs.append(AugSchemeMPL.sign(synthetic_secret_key, msg))
                    except AssertionError:
                        raise ValueError("This spend bundle cannot be signed by the DID wallet")

    agg_sig = AugSchemeMPL.aggregate(sigs)
    return SpendBundle(spends, agg_sig)
