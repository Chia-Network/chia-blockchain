from typing import Optional, Tuple, List
from blspy import G1Element

from chia.clvm.singleton import P2_SINGLETON_MOD
from chia.consensus.block_rewards import calculate_pool_reward
from chia.consensus.coinbase import pool_parent_id
from chia.pools.pool_wallet_info import PoolState, LEAVING_POOL, PoolWalletInfo

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.wallet.puzzles.load_clvm import load_clvm

from chia.util.ints import uint32, uint64

# "Full" is the outer singleton, with the inner puzzle filled in
from tests.wallet.test_singleton import singleton_puzzle, LAUNCHER_PUZZLE_HASH

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
POOL_ESCAPING_MOD = load_clvm("pool_escaping_innerpuz.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_OUTER_MOD = SINGLETON_MOD
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")

POOL_MEMBER_HASH = POOL_MEMBER_MOD.get_tree_hash()
P2_SINGLETON_HASH = P2_SINGLETON_MOD.get_tree_hash()
POOL_OUTER_MOD_HASH = POOL_OUTER_MOD.get_tree_hash()
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
SINGLETON_MOD_HASH = POOL_OUTER_MOD_HASH

SINGLETON_MOD_HASH_HASH = Program.to(SINGLETON_MOD_HASH).get_tree_hash()

# same challenge for every P2_SINGLETON puzzle
P2_SINGLETON_GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")


def create_escaping_inner_puzzle(
    target_puzzle_hash: bytes32, relative_lock_height: uint32, owner_pubkey: G1Element
) -> Program:
    return POOL_ESCAPING_MOD.curry(target_puzzle_hash, relative_lock_height, bytes(owner_pubkey), P2_SINGLETON_HASH)


def create_pooling_inner_puzzle(
    target_puzzle_hash: bytes, pool_escaping_inner_hash: bytes32, owner_pubkey: G1Element
) -> Program:
    return POOL_MEMBER_MOD.curry(target_puzzle_hash, pool_escaping_inner_hash, P2_SINGLETON_HASH, bytes(owner_pubkey))


def create_full_puzzle(inner_puzzle: Program, launcher_id: bytes32) -> Program:
    return POOL_OUTER_MOD.curry(POOL_OUTER_MOD_HASH, launcher_id, inner_puzzle)


def create_p2_singleton_puzzle(singleton_mod_hash: bytes, launcher_id: bytes32) -> Program:
    # TODO: Test these hash conversions
    return P2_SINGLETON_MOD.curry(POOL_OUTER_MOD_HASH, Program.to(singleton_mod_hash).get_tree_hash(), launcher_id)


def launcher_id_to_p2_puzzle_hash(launcher_id: bytes32) -> bytes32:
    return create_p2_singleton_puzzle(SINGLETON_MOD_HASH, launcher_id).get_tree_hash()


######################################


def is_escaping_inner_puzzle(inner_f: Program) -> bool:
    return inner_f == POOL_ESCAPING_MOD


def is_pooling_inner_puzzle(inner_f: Program) -> bool:
    return inner_f == POOL_MEMBER_MOD


def is_pool_protocol_inner_puzzle(inner_f: Program) -> bool:
    return is_pooling_inner_puzzle(inner_f) or is_escaping_inner_puzzle(inner_f)


# Verify that a puzzle is a Pool Wallet Singleton
def is_pool_singleton_inner_puzzle(puzzle: Program) -> bool:
    r = puzzle.uncurry()
    if r is None:
        return False
    inner_f, args = r
    return is_escaping_inner_puzzle(inner_f) or is_pooling_inner_puzzle(inner_f)


def create_escape_spend(last_coin_solution: CoinSolution, pool_info: PoolWalletInfo) -> CoinSolution:
    inner_puzzle: Program = pool_state_to_inner_puzzle(pool_info.current)
    if is_pooling_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([1, 0, 0, bytes(pool_info.current)])
    elif is_escaping_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, destination_puzhash, pool_reward_amount, pool_reward_height, extra_data)
        destination_inner: Program = pool_state_to_inner_puzzle(pool_info.target)
        inner_sol: Program = Program.to([1, destination_inner, 0, 0, bytes(pool_info.target)])
    else:
        raise ValueError
    # full sol = (parent_info, my_amount, inner_solution)
    coin: Coin = get_most_recent_singleton_coin_from_coin_solution(last_coin_solution)
    if coin.parent_coin_info == pool_info.launcher_coin.name():
        parent_info = Program.to([pool_info.launcher_coin.parent_coin_info, pool_info.launcher_coin.amount])
    else:
        parent_info: Program = Program.to(
            [
                last_coin_solution.coin.name(),
                get_inner_puzzle_from_puzzle(last_coin_solution.puzzle_reveal).get_tree_hash(),
                last_coin_solution.coin.amount,
            ]
        )
    full_solution: Program = Program.to(parent_info, last_coin_solution.coin.amount, inner_sol)
    full_puzzle: Program = create_full_puzzle(inner_puzzle, pool_info.launcher_coin.name())
    return CoinSolution(
        coin, SerializedProgram.from_program(full_puzzle), SerializedProgram.from_program(full_solution)
    )


def create_absorb_spend(
    last_coin_solution: CoinSolution, pool_info: PoolWalletInfo, height: uint32
) -> List[CoinSolution]:
    inner_puzzle: Program = pool_state_to_inner_puzzle(pool_info.current)
    reward_amount: uint64 = calculate_pool_reward(height)
    if is_pooling_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([0, reward_amount, height, 0])
    elif is_escaping_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, destination_puzhash, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([0, 0, reward_amount, height, 0])
    else:
        raise ValueError
    # full sol = (parent_info, my_amount, inner_solution)
    coin: Coin = get_most_recent_singleton_coin_from_coin_solution(last_coin_solution)
    if coin.parent_coin_info == pool_info.launcher_coin.name():
        parent_info = Program.to([pool_info.launcher_coin.parent_coin_info, pool_info.launcher_coin.amount])
    else:
        parent_info: Program = Program.to(
            [
                last_coin_solution.coin.name(),
                get_inner_puzzle_from_puzzle(last_coin_solution.puzzle_reveal).get_tree_hash(),
                last_coin_solution.coin.amount,
            ]
        )
    full_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to(parent_info, last_coin_solution.coin.amount, inner_sol)
    )
    full_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_full_puzzle(inner_puzzle, pool_info.launcher_coin.name())
    )

    reward_parent: bytes32 = pool_parent_id(height, P2_SINGLETON_GENESIS_CHALLENGE)
    p2_singleton_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_p2_singleton_puzzle(SINGLETON_MOD_HASH, pool_info.launcher_coin.name())
    )
    reward_coin: Coin = Coin(reward_parent, p2_singleton_puzzle.get_tree_hash(), reward_amount)
    p2_singleton_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to(inner_puzzle.get_tree_hash(), reward_coin.name())
    )
    return [
        CoinSolution(coin, full_puzzle, full_solution),
        CoinSolution(reward_coin, p2_singleton_puzzle, p2_singleton_solution),
    ]


def get_most_recent_singleton_coin_from_coin_solution(coin_sol: CoinSolution) -> Optional[Coin]:
    additions: List[Coin] = coin_sol.additions()
    for coin in additions:
        if coin.amount % 2 == 1:
            return coin
    return None


def get_pubkey_from_member_inner_puzzle(inner_puzzle: Program) -> G1Element:
    args = uncurry_pool_member_inner_puzzle(inner_puzzle)
    if args is not None:
        pool_puzzle_hash, relative_lock_height, pubkey_program = args
        # pubkey_program = args[0]
    else:
        raise ValueError("Unable to extract pubkey")
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def uncurry_pool_member_inner_puzzle(inner_puzzle: Program) -> Optional[Tuple[Program, Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    r = inner_puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_pooling_inner_puzzle(inner_f):
        return None

    pool_puzzle_hash, relative_lock_height, pool_escaping_inner_hash, p2_singleton_hash, pubkey = list(args.as_iter())
    assert p2_singleton_hash == P2_SINGLETON_HASH

    return pool_puzzle_hash, relative_lock_height, pubkey


def get_inner_puzzle_from_puzzle(full_puzzle: Program) -> Optional[Program]:
    r = full_puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_pool_protocol_inner_puzzle(inner_f):
        return None
    mod_hash, genesis_id, inner_puzzle = list(args.as_iter())
    return inner_puzzle


def solution_to_extra_data(full_spend: CoinSolution) -> Optional[PoolState]:
    full_solution_ser: SerializedProgram = full_spend.solution
    full_solution: Program = Program.from_bytes(bytes(full_solution_ser))

    if full_spend.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
        # Launcher spend
        extra_data = full_solution.rest().rest().first().as_atom()
        return PoolState.from_bytes(extra_data)

    # Not launcher spend
    inner_solution: Program = full_solution.rest().rest().first()
    inner_spend_type: int = inner_solution.first().as_int()

    if inner_spend_type == 0:
        # Absorb
        return None

    # Spend which is not absorb, and is not the launcher
    num_args = len(inner_solution.as_atom_list())
    assert num_args == 4 or num_args == 5

    if num_args == 4:
        # pool member
        extra_data = inner_solution.rest().rest().rest().first().as_atom()
    else:
        # pool escaping
        extra_data = inner_solution.rest().rest().rest().rest().first().as_atom()
    return PoolState.from_bytes(extra_data)


def pool_state_to_inner_puzzle(pool_state: PoolState) -> Program:
    escaping_inner_puzzle: Program = create_escaping_inner_puzzle(
        pool_state.target_puzzle_hash, pool_state.relative_lock_height, pool_state.owner_pubkey
    )
    if pool_state.state == LEAVING_POOL:
        return escaping_inner_puzzle
    else:
        return create_pooling_inner_puzzle(
            pool_state.target_puzzle_hash, escaping_inner_puzzle.get_tree_hash(), pool_state.owner_pubkey
        )
