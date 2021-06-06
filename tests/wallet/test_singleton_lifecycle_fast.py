from typing import List, Tuple

from blspy import G2Element
from clvm_tools import binutils

from chia.types.blockchain_format.program import Program, INFINITE_COST, SerializedProgram
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.cc_wallet.debug_spend_bundle import debug_spend_bundle
from chia.wallet.puzzles.load_clvm import load_clvm

from tests.clvm.coin_store import CoinStore, CoinTimestamp


SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
POOL_WAITINGROOM_MOD = load_clvm("pool_waitingroom_innerpuz.clvm")

LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()

POOL_REWARD_PREFIX_MAINNET = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000")


def check_coin_solution(coin_solution: CoinSolution):
    breakpoint()
    try:
        cost, result = coin_solution.puzzle_reveal.run_with_cost(INFINITE_COST, coin_solution.solution)
    except Exception as ex:
        print(ex)
        breakpoint()
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
    coin_solution = CoinSolution(launcher_coin, SerializedProgram.from_program(launcher_puzzle), launcher_solution)
    spend_bundle = SpendBundle([coin_solution], G2Element())
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


def test_lifecycle_with_coinstore():
    metadata = [("foo", "bar")]
    ANYONE_CAN_SPEND_PUZZLE = Program.to(1)

    coin_store = CoinStore(int.from_bytes(POOL_REWARD_PREFIX_MAINNET, "big"))
    now = CoinTimestamp(10012300, 1)
    parent_coin_amount = 100000
    farmed_coin = coin_store.farm_coin(ANYONE_CAN_SPEND_PUZZLE.get_tree_hash(), now, amount=parent_coin_amount)
    now.seconds += 500
    now.height += 1

    launcher_amount: uint64 = uint64(1)
    launcher_puzzle = LAUNCHER_PUZZLE
    launcher_puzzle_hash = launcher_puzzle.get_tree_hash()
    initial_singleton_puzzle = adaptor_for_singleton_inner_puzzle(ANYONE_CAN_SPEND_PUZZLE)
    lineage_proof, launcher_id, condition_list, launcher_spend_bundle = launcher_conditions_and_spend_bundle(
        farmed_coin.name(), launcher_amount, initial_singleton_puzzle, metadata, launcher_puzzle
    )

    conditions = Program.to(condition_list)
    coin_solution = CoinSolution(farmed_coin, ANYONE_CAN_SPEND_PUZZLE, conditions)
    spend_bundle = SpendBundle.aggregate([launcher_spend_bundle, SpendBundle([coin_solution], G2Element())])

    debug_spend_bundle(spend_bundle)
    coin_store.update_coin_store_for_spend_bundle(spend_bundle, now)

    launcher_coin = launcher_spend_bundle.coin_solutions[0].coin

    assert coin_store.coin_record(launcher_coin.name()).spent
    assert coin_store.coin_record(farmed_coin.name()).spent

    singleton_expected_puzzle = singleton_puzzle(launcher_id, launcher_puzzle_hash, initial_singleton_puzzle)
    singleton_expected_puzzle_hash = singleton_expected_puzzle.get_tree_hash()
    expected_singleton_coin = Coin(launcher_coin.name(), singleton_expected_puzzle_hash, launcher_amount)
    assert coin_store.coin_record(expected_singleton_coin.name()).spent is False

    # farm a `p2_singleton`

    pool_reward_puzzle_hash = p2_singleton_puzzle_hash(launcher_id, launcher_puzzle_hash)
    p2_singleton_coin = coin_store.farm_coin(pool_reward_puzzle_hash, now)
    assert p2_singleton_coin.puzzle_hash == pool_reward_puzzle_hash

    # now collect the `p2_singleton`

    # build `CoinSolution` for the `p2_singleton`
    singleton_inner_puzzle_hash = initial_singleton_puzzle.get_tree_hash()
    p2_singleton_solution = Program.to([singleton_inner_puzzle_hash, p2_singleton_coin.name()])
    p2_singleton_coin_solution = CoinSolution(
        p2_singleton_coin, p2_singleton_puzzle(launcher_id, launcher_puzzle_hash), p2_singleton_solution
    )

    # build `CoinSolution` for the singleton
    expected_p2_singleton_announcement = Announcement(p2_singleton_coin.name(), bytes([0x80])).name()
    conditions = [
        Program.to([ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, p2_singleton_coin.name()]),
        Program.to([ConditionOpcode.CREATE_COIN, singleton_inner_puzzle_hash, 1]),
        Program.to([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, expected_p2_singleton_announcement]),
    ]
    singleton_inner_solution = conditions
    singleton_solution = Program.to([lineage_proof, expected_singleton_coin.amount, singleton_inner_solution])
    singleton_coin_solution = CoinSolution(expected_singleton_coin, singleton_expected_puzzle, singleton_solution)

    spend_bundle = SpendBundle([p2_singleton_coin_solution, singleton_coin_solution], G2Element())

    debug_spend_bundle(spend_bundle)

    coin_store.update_coin_store_for_spend_bundle(spend_bundle, now)

    # spend_bundle = claim_p2_singleton(p2_singleton_coin, singleton_inner_puzzle_hash, my_id)

    # next up: spend the expected_singleton_coin
    # it's an adapted `ANYONE_CAN_SPEND_PUZZLE`

    # then try a bad lineage proof
    # then try writing two odd coins
    # then try writing zero odd coins

    # then do a `p2_singleton` and collect it

    # then commit to a pool
    # then do a `p2_singleton` and collect it

    # then escape the pool
    # then do a `p2_singleton` and collect it
    # then finish leaving the pool

    # then, destroy the singleton with the -113 hack

    return 0
