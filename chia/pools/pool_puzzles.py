import logging
from typing import Tuple, List, Optional
from blspy import G1Element

from chia.clvm.singleton import SINGLETON_LAUNCHER
from chia.consensus.block_rewards import calculate_pool_reward
from chia.consensus.coinbase import pool_parent_id
from chia.pools.pool_wallet_info import PoolState, LEAVING_POOL

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.wallet.puzzles.load_clvm import load_clvm

from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)
# "Full" is the outer singleton, with the inner puzzle filled in
SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
POOL_WAITING_ROOM_MOD = load_clvm("pool_waitingroom_innerpuz.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_OUTER_MOD = SINGLETON_MOD
# SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")

POOL_MEMBER_HASH = POOL_MEMBER_MOD.get_tree_hash()
POOL_WAITING_ROOM_HASH = POOL_WAITING_ROOM_MOD.get_tree_hash()
P2_SINGLETON_HASH = P2_SINGLETON_MOD.get_tree_hash()
POOL_OUTER_MOD_HASH = POOL_OUTER_MOD.get_tree_hash()
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
SINGLETON_MOD_HASH = POOL_OUTER_MOD_HASH

SINGLETON_MOD_HASH_HASH = Program.to(SINGLETON_MOD_HASH).get_tree_hash()


def create_waiting_room_inner_puzzle(
    target_puzzle_hash: bytes32,
    relative_lock_height: uint32,
    owner_pubkey: G1Element,
    launcher_id: bytes32,
    genesis_challenge: bytes32,
) -> Program:
    pool_reward_prefix = bytes32(genesis_challenge[:16] + b"\x00" * 16)
    p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(launcher_id)
    return POOL_WAITING_ROOM_MOD.curry(
        target_puzzle_hash, p2_singleton_puzzle_hash, bytes(owner_pubkey), pool_reward_prefix, relative_lock_height
    )


def create_pooling_inner_puzzle(
    target_puzzle_hash: bytes,
    pool_waiting_room_inner_hash: bytes32,
    owner_pubkey: G1Element,
    launcher_id: bytes32,
    genesis_challenge: bytes32,
) -> Program:
    pool_reward_prefix = bytes32(genesis_challenge[:16] + b"\x00" * 16)
    p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(launcher_id)
    return POOL_MEMBER_MOD.curry(
        target_puzzle_hash,
        p2_singleton_puzzle_hash,
        bytes(owner_pubkey),
        pool_reward_prefix,
        pool_waiting_room_inner_hash,
    )


def create_full_puzzle(inner_puzzle: Program, launcher_id: bytes32) -> Program:
    return POOL_OUTER_MOD.curry(POOL_OUTER_MOD_HASH, launcher_id, SINGLETON_LAUNCHER_HASH, inner_puzzle)


def create_p2_singleton_puzzle(singleton_mod_hash: bytes, launcher_id: bytes32) -> Program:
    # TODO: Test these hash conversions
    return P2_SINGLETON_MOD.curry(singleton_mod_hash, launcher_id, SINGLETON_LAUNCHER_HASH)


def launcher_id_to_p2_puzzle_hash(launcher_id: bytes32) -> bytes32:
    return create_p2_singleton_puzzle(SINGLETON_MOD_HASH, launcher_id).get_tree_hash()


######################################


def uncurry_singleton_inner_puzzle(puzzle: Program):
    r = puzzle.uncurry()
    if r is None:
        return False
    inner_f, args = r
    return inner_f


# Verify that a puzzle is a Pool Wallet Singleton
def is_pool_singleton_inner_puzzle(puzzle: Program) -> bool:
    inner_f = uncurry_singleton_inner_puzzle(puzzle)
    return inner_f in [POOL_WAITING_ROOM_MOD, POOL_MEMBER_MOD]


def is_pool_waitingroom_inner_puzzle(puzzle: Program) -> bool:
    inner_f = uncurry_singleton_inner_puzzle(puzzle)
    return inner_f in [POOL_WAITING_ROOM_MOD]


def is_pool_member_inner_puzzle(puzzle: Program) -> bool:
    inner_f = uncurry_singleton_inner_puzzle(puzzle)
    return inner_f in [POOL_MEMBER_MOD]


# This spend will use the escape-type spend path for whichever state you are currently in
# If you are currently a waiting inner puzzle, then it will look at your target_state to determine the next
# inner puzzle hash to go to. The member inner puzzle is already committed to its next puzzle hash.
def create_travel_spend(
    last_coin_solution: CoinSolution,
    launcher_coin: Coin,
    current: PoolState,
    target: PoolState,
    genesis_challenge: bytes32,
) -> Tuple[CoinSolution, Program, Program]:
    #    -> Tuple[CoinSolution, bytes32]:
    pool_reward_prefix = bytes32(genesis_challenge[:16] + b"\x00" * 16)
    inner_puzzle: Program = pool_state_to_inner_puzzle(current, pool_reward_prefix)
    if is_pool_member_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([1, 0, 0, bytes(current)])
    elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, destination_puz hash, pool_reward_amount, pool_reward_height, extra_data)
        destination_inner: Program = pool_state_to_inner_puzzle(current, launcher_coin.name(), genesis_challenge)
        inner_sol = Program.to([1, destination_inner.get_tree_hash(), 0, 0, bytes(target)])
    else:
        raise ValueError
    # full sol = (parent_info, my_amount, inner_solution)
    coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_solution(last_coin_solution)
    assert coin is not None
    if coin.parent_coin_info == launcher_coin.name():
        parent_info = Program.to([launcher_coin.parent_coin_info, launcher_coin.amount])
    else:
        p = Program.from_bytes(bytes(last_coin_solution.puzzle_reveal))
        last_coin_solution_inner_puzzle: Optional[Program] = get_inner_puzzle_from_puzzle(p)
        assert last_coin_solution_inner_puzzle is not None
        parent_info = Program.to(
            [
                last_coin_solution.coin.parent_coin_info,
                last_coin_solution_inner_puzzle.get_tree_hash(),
                last_coin_solution.coin.amount,
            ]
        )
    full_solution: Program = Program.to([parent_info, last_coin_solution.coin.amount, inner_sol])
    full_puzzle: Program = create_full_puzzle(inner_puzzle, launcher_coin.name())

    return (
        CoinSolution(coin, SerializedProgram.from_program(full_puzzle), SerializedProgram.from_program(full_solution)),
        full_puzzle,
        inner_puzzle,
    )


def create_absorb_spend(
    last_coin_solution: CoinSolution,
    current_state: PoolState,
    launcher_coin: Coin,
    height: uint32,
    genesis_challenge: bytes32,
) -> List[CoinSolution]:
    inner_puzzle: Program = pool_state_to_inner_puzzle(current_state, launcher_coin.name(), genesis_challenge)
    reward_amount: uint64 = calculate_pool_reward(height)
    if is_pool_member_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([0, reward_amount, height, 0])
    elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, destination_puzhash, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol = Program.to([0, 0, reward_amount, height, 0])
    else:
        raise ValueError
    # full sol = (parent_info, my_amount, inner_solution)
    coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_solution(last_coin_solution)
    assert coin is not None

    if coin.parent_coin_info == launcher_coin.name():
        parent_info: Program = Program.to([launcher_coin.parent_coin_info, launcher_coin.amount])
    else:
        p = Program.from_bytes(bytes(last_coin_solution.puzzle_reveal))
        last_coin_solution_inner_puzzle: Optional[Program] = get_inner_puzzle_from_puzzle(p)
        assert last_coin_solution_inner_puzzle is not None
        parent_info = Program.to(
            [
                last_coin_solution.coin.parent_coin_info,
                last_coin_solution_inner_puzzle.get_tree_hash(),
                last_coin_solution.coin.amount,
            ]
        )
    full_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to([parent_info, last_coin_solution.coin.amount, inner_sol])
    )
    full_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_full_puzzle(inner_puzzle, launcher_coin.name())
    )

    reward_parent: bytes32 = pool_parent_id(height, genesis_challenge)
    p2_singleton_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_p2_singleton_puzzle(SINGLETON_MOD_HASH, launcher_coin.name())
    )
    reward_coin: Coin = Coin(reward_parent, p2_singleton_puzzle.get_tree_hash(), reward_amount)
    p2_singleton_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to([inner_puzzle.get_tree_hash(), reward_coin.name()])
    )
    assert p2_singleton_puzzle.get_tree_hash() == reward_coin.puzzle_hash
    assert full_puzzle.get_tree_hash() == coin.puzzle_hash
    if get_inner_puzzle_from_puzzle(Program.from_bytes(bytes(full_puzzle))) is None:
        assert get_inner_puzzle_from_puzzle(Program.from_bytes(bytes(full_puzzle))) is not None

    coin_solutions = [
        CoinSolution(coin, full_puzzle, full_solution),
        CoinSolution(reward_coin, p2_singleton_puzzle, p2_singleton_solution),
    ]
    return coin_solutions


def get_most_recent_singleton_coin_from_coin_solution(coin_sol: CoinSolution) -> Optional[Coin]:
    additions: List[Coin] = coin_sol.additions()
    for coin in additions:
        if coin.amount % 2 == 1:
            return coin
    return None


def get_pubkey_from_member_inner_puzzle(inner_puzzle: Program) -> G1Element:
    args = uncurry_pool_member_inner_puzzle(inner_puzzle)
    if args is not None:
        (
            _inner_f,
            _target_puzzle_hash,
            _p2_singleton_hash,
            pubkey_program,
            _pool_reward_prefix,
            _escape_puzzlehash,
        ) = args
    else:
        raise ValueError("Unable to extract pubkey")
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def uncurry_pool_member_inner_puzzle(inner_puzzle: Program):  # -> Optional[Tuple[Program, Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    if not is_pool_member_inner_puzzle(inner_puzzle):
        return None
    r = inner_puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r

    # TARGET_PUZZLE_HASH P2_SINGLETON_PUZZLEHASH OWNER_PUBKEY POOL_REWARD_PREFIX ESCAPE_MODE_PUZZLEHASH
    target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash = list(args.as_iter())
    # assert p2_singleton_hash == P2_SINGLETON_HASH

    # return target_puzzle_hash, owner_pubkey
    return inner_f, target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash


def uncurry_pool_waitingroom_inner_puzzle(inner_puzzle: Program):  # -> Optional[Tuple[Program, Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    if not is_pool_member_inner_puzzle(inner_puzzle):
        return None
    r = inner_puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r

    # TARGET_PUZHASH RELATIVE_LOCK_HEIGHT OWNER_PUBKEY P2_SINGLETON_PUZHASH
    target_puzzle_hash, relative_lock_height, owner_pubkey, p2_singleton_hash = list(args.as_iter())
    # assert p2_singleton_hash == P2_SINGLETON_HASH

    return target_puzzle_hash, relative_lock_height, owner_pubkey, p2_singleton_hash


def get_inner_puzzle_from_puzzle(full_puzzle: Program) -> Optional[Program]:
    p = Program.from_bytes(bytes(full_puzzle))
    r = p.uncurry()
    if r is None:
        return None
    inner_f, args = r

    # TODO(adam): fix
    # if not is_pool_singleton_inner_puzzle(inner_f):
    #     return None
    mod_hash, launcher_id, launcher_puzzle_hash, inner_puzzle = list(args.as_iter())
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
    assert num_args in (4, 5)

    if num_args == 4:
        # pool member
        extra_data = inner_solution.rest().rest().rest().first().as_atom()
    else:
        # pool escaping
        extra_data = inner_solution.rest().rest().rest().rest().first().as_atom()
    return PoolState.from_bytes(extra_data)


def pool_state_to_inner_puzzle(pool_state: PoolState, launcher_id: bytes32, genesis_challenge: bytes32) -> Program:
    escaping_inner_puzzle: Program = create_waiting_room_inner_puzzle(
        pool_state.target_puzzle_hash,
        pool_state.relative_lock_height,
        pool_state.owner_pubkey,
        launcher_id,
        genesis_challenge,
    )
    if pool_state.state == LEAVING_POOL:
        return escaping_inner_puzzle
    else:
        return create_pooling_inner_puzzle(
            pool_state.target_puzzle_hash,
            escaping_inner_puzzle.get_tree_hash(),
            pool_state.owner_pubkey,
            launcher_id,
            genesis_challenge,
        )
