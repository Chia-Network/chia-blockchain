from __future__ import annotations

from typing import List, Tuple

import pytest
from blspy import G2Element
from clvm_tools import binutils

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from tests.core.full_node.test_conditions import check_spend_bundle_validity, initial_blocks

SINGLETON_MOD = load_clvm("singleton_top_layer.clsp")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clsp")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clsp")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clsp")
POOL_WAITINGROOM_MOD = load_clvm("pool_waitingroom_innerpuz.clsp")

LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()

POOL_REWARD_PREFIX_MAINNET = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000")


def check_coin_spend(coin_spend: CoinSpend):
    try:
        cost, result = coin_spend.puzzle_reveal.run_with_cost(INFINITE_COST, coin_spend.solution)
    except Exception as ex:
        print(ex)


def adaptor_for_singleton_inner_puzzle(puzzle: Program) -> Program:
    # this is prety slow
    return Program.to(binutils.assemble("(a (q . %s) 3)" % binutils.disassemble(puzzle)))


def launcher_conditions_and_spend_bundle(
    parent_coin_id: bytes32,
    launcher_amount: uint64,
    initial_singleton_inner_puzzle: Program,
    metadata: List[Tuple[str, str]],
    launcher_puzzle: Program = LAUNCHER_PUZZLE,
) -> Tuple[Program, bytes32, List[Program], SpendBundle]:
    launcher_puzzle_hash = launcher_puzzle.get_tree_hash()
    launcher_coin = Coin(parent_coin_id, launcher_puzzle_hash, launcher_amount)
    singleton_full_puzzle = SINGLETON_MOD.curry(
        SINGLETON_MOD_HASH, launcher_coin.name(), launcher_puzzle_hash, initial_singleton_inner_puzzle
    )
    singleton_full_puzzle_hash = singleton_full_puzzle.get_tree_hash()
    message_program = Program.to([singleton_full_puzzle_hash, launcher_amount, metadata])
    expected_announcement = Announcement(launcher_coin.name(), message_program.get_tree_hash())
    expected_conditions = []
    expected_conditions.append(
        Program.to(
            binutils.assemble(f"(0x{ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT.hex()} 0x{expected_announcement.name()})")
        )
    )
    expected_conditions.append(
        Program.to(
            binutils.assemble(f"(0x{ConditionOpcode.CREATE_COIN.hex()} 0x{launcher_puzzle_hash} {launcher_amount})")
        )
    )
    launcher_solution = Program.to([singleton_full_puzzle_hash, launcher_amount, metadata])
    coin_spend = CoinSpend(launcher_coin, launcher_puzzle, launcher_solution)
    spend_bundle = SpendBundle([coin_spend], G2Element())
    lineage_proof = Program.to([parent_coin_id, launcher_amount])
    return lineage_proof, launcher_coin.name(), expected_conditions, spend_bundle


def singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, launcher_puzzle_hash, inner_puzzle)


def singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> bytes32:
    return singleton_puzzle(launcher_id, launcher_puzzle_hash, inner_puzzle).get_tree_hash()


def solution_for_singleton_puzzle(lineage_proof: Program, my_amount: int, inner_solution: Program) -> Program:
    return Program.to([lineage_proof, my_amount, inner_solution])


def p2_singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, launcher_puzzle_hash)


def p2_singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32) -> bytes32:
    return p2_singleton_puzzle(launcher_id, launcher_puzzle_hash).get_tree_hash()


@pytest.mark.asyncio
async def test_only_odd_coins_0(bt):
    blocks = await initial_blocks(bt)
    farmed_coin = list(blocks[-1].get_included_reward_coins())[0]

    metadata = [("foo", "bar")]
    ANYONE_CAN_SPEND_PUZZLE = Program.to(1)
    launcher_amount = uint64(1)
    launcher_puzzle = LAUNCHER_PUZZLE
    launcher_puzzle_hash = launcher_puzzle.get_tree_hash()
    initial_singleton_puzzle = adaptor_for_singleton_inner_puzzle(ANYONE_CAN_SPEND_PUZZLE)
    lineage_proof, launcher_id, condition_list, launcher_spend_bundle = launcher_conditions_and_spend_bundle(
        farmed_coin.name(), launcher_amount, initial_singleton_puzzle, metadata, launcher_puzzle
    )

    conditions = Program.to(condition_list)
    coin_spend = CoinSpend(farmed_coin, ANYONE_CAN_SPEND_PUZZLE, conditions)
    spend_bundle = SpendBundle.aggregate([launcher_spend_bundle, SpendBundle([coin_spend], G2Element())])
    coins_added, coins_removed = await check_spend_bundle_validity(bt, blocks, spend_bundle)

    coin_set_added = set([_.coin for _ in coins_added])
    coin_set_removed = set([_.coin for _ in coins_removed])

    launcher_coin = launcher_spend_bundle.coin_spends[0].coin

    assert launcher_coin in coin_set_added
    assert launcher_coin in coin_set_removed

    assert farmed_coin in coin_set_removed

    singleton_expected_puzzle_hash = singleton_puzzle_hash(launcher_id, launcher_puzzle_hash, initial_singleton_puzzle)
    expected_singleton_coin = Coin(launcher_coin.name(), singleton_expected_puzzle_hash, launcher_amount)
    assert expected_singleton_coin in coin_set_added

    # next up: spend the expected_singleton_coin
    # it's an adapted `ANYONE_CAN_SPEND_PUZZLE`

    # then try a bad lineage proof
    # then try writing two odd coins
    # then try writing zero odd coins

    # then, destroy the singleton with the -113 hack

    return 0
