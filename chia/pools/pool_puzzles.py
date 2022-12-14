from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from blspy import G1Element
from clvm.casts import int_from_bytes, int_to_bytes

from chia.clvm.singleton import SINGLETON_LAUNCHER
from chia.consensus.block_rewards import calculate_pool_reward
from chia.consensus.coinbase import pool_parent_id
from chia.pools.pool_wallet_info import LEAVING_POOL, SELF_POOLING, PoolState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint32, uint64
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer import puzzle_for_singleton

log = logging.getLogger(__name__)
# "Full" is the outer singleton, with the inner puzzle filled in
SINGLETON_MOD = load_clvm_maybe_recompile("singleton_top_layer.clvm")
POOL_WAITING_ROOM_MOD = load_clvm_maybe_recompile("pool_waitingroom_innerpuz.clvm")
POOL_MEMBER_MOD = load_clvm_maybe_recompile("pool_member_innerpuz.clvm")
P2_SINGLETON_MOD = load_clvm_maybe_recompile("p2_singleton_or_delayed_puzhash.clvm")
POOL_OUTER_MOD = SINGLETON_MOD

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
    delay_time: uint64,
    delay_ph: bytes32,
) -> Program:
    pool_reward_prefix = bytes32(genesis_challenge[:16] + b"\x00" * 16)
    p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(launcher_id, delay_time, delay_ph)
    return POOL_WAITING_ROOM_MOD.curry(
        target_puzzle_hash, p2_singleton_puzzle_hash, bytes(owner_pubkey), pool_reward_prefix, relative_lock_height
    )


def create_pooling_inner_puzzle(
    target_puzzle_hash: bytes,
    pool_waiting_room_inner_hash: bytes32,
    owner_pubkey: G1Element,
    launcher_id: bytes32,
    genesis_challenge: bytes32,
    delay_time: uint64,
    delay_ph: bytes32,
) -> Program:
    pool_reward_prefix = bytes32(genesis_challenge[:16] + b"\x00" * 16)
    p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(launcher_id, delay_time, delay_ph)
    return POOL_MEMBER_MOD.curry(
        target_puzzle_hash,
        p2_singleton_puzzle_hash,
        bytes(owner_pubkey),
        pool_reward_prefix,
        pool_waiting_room_inner_hash,
    )


def create_full_puzzle(inner_puzzle: Program, launcher_id: bytes32) -> Program:
    return puzzle_for_singleton(launcher_id, inner_puzzle)


def create_p2_singleton_puzzle(
    singleton_mod_hash: bytes,
    launcher_id: bytes32,
    seconds_delay: uint64,
    delayed_puzzle_hash: bytes32,
) -> Program:
    # curry params are SINGLETON_MOD_HASH LAUNCHER_ID LAUNCHER_PUZZLE_HASH SECONDS_DELAY DELAYED_PUZZLE_HASH
    return P2_SINGLETON_MOD.curry(
        singleton_mod_hash, launcher_id, SINGLETON_LAUNCHER_HASH, seconds_delay, delayed_puzzle_hash
    )


def launcher_id_to_p2_puzzle_hash(launcher_id: bytes32, seconds_delay: uint64, delayed_puzzle_hash: bytes32) -> bytes32:
    return create_p2_singleton_puzzle(
        SINGLETON_MOD_HASH, launcher_id, int_to_bytes(seconds_delay), delayed_puzzle_hash
    ).get_tree_hash()


def get_delayed_puz_info_from_launcher_spend(coinsol: CoinSpend) -> Tuple[uint64, bytes32]:
    extra_data = Program.from_bytes(bytes(coinsol.solution)).rest().rest().first()
    # Extra data is (pool_state delayed_puz_info)
    # Delayed puz info is (seconds delayed_puzzle_hash)
    seconds: Optional[uint64] = None
    delayed_puzzle_hash: Optional[bytes32] = None
    for key, value in extra_data.as_python():
        if key == b"t":
            seconds = int_from_bytes(value)
        if key == b"h":
            delayed_puzzle_hash = bytes32(value)
    assert seconds is not None
    assert delayed_puzzle_hash is not None
    return seconds, delayed_puzzle_hash


######################################


def get_template_singleton_inner_puzzle(inner_puzzle: Program):
    r = inner_puzzle.uncurry()
    if r is None:
        return False
    uncurried_inner_puzzle, args = r
    return uncurried_inner_puzzle


def get_seconds_and_delayed_puzhash_from_p2_singleton_puzzle(puzzle: Program) -> Tuple[uint64, bytes32]:
    r = puzzle.uncurry()
    if r is None:
        return False
    inner_f, args = r
    singleton_mod_hash, launcher_id, launcher_puzzle_hash, seconds_delay, delayed_puzzle_hash = list(args.as_iter())
    seconds_delay = uint64(seconds_delay.as_int())
    return seconds_delay, delayed_puzzle_hash.as_atom()


# Verify that a puzzle is a Pool Wallet Singleton
def is_pool_singleton_inner_puzzle(inner_puzzle: Program) -> bool:
    inner_f = get_template_singleton_inner_puzzle(inner_puzzle)
    return inner_f in [POOL_WAITING_ROOM_MOD, POOL_MEMBER_MOD]


def is_pool_waitingroom_inner_puzzle(inner_puzzle: Program) -> bool:
    inner_f = get_template_singleton_inner_puzzle(inner_puzzle)
    return inner_f in [POOL_WAITING_ROOM_MOD]


def is_pool_member_inner_puzzle(inner_puzzle: Program) -> bool:
    inner_f = get_template_singleton_inner_puzzle(inner_puzzle)
    return inner_f in [POOL_MEMBER_MOD]


# This spend will use the escape-type spend path for whichever state you are currently in
# If you are currently a waiting inner puzzle, then it will look at your target_state to determine the next
# inner puzzle hash to go to. The member inner puzzle is already committed to its next puzzle hash.
def create_travel_spend(
    last_coin_spend: CoinSpend,
    launcher_coin: Coin,
    current: PoolState,
    target: PoolState,
    genesis_challenge: bytes32,
    delay_time: uint64,
    delay_ph: bytes32,
) -> Tuple[CoinSpend, Program]:
    inner_puzzle: Program = pool_state_to_inner_puzzle(
        current,
        launcher_coin.name(),
        genesis_challenge,
        delay_time,
        delay_ph,
    )
    if is_pool_member_inner_puzzle(inner_puzzle):
        # inner sol is key_value_list ()
        # key_value_list is:
        # "p" -> poolstate as bytes
        inner_sol: Program = Program.to([[("p", bytes(target))], 0])
    elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, key_value_list, pool_reward_height)
        destination_inner: Program = pool_state_to_inner_puzzle(
            target, launcher_coin.name(), genesis_challenge, delay_time, delay_ph
        )
        log.debug(
            f"create_travel_spend: waitingroom: target PoolState bytes:\n{bytes(target).hex()}\n"
            f"{target}"
            f"hash:{Program.to(bytes(target)).get_tree_hash()}"
        )
        # key_value_list is:
        # "p" -> poolstate as bytes
        inner_sol = Program.to([1, [("p", bytes(target))], destination_inner.get_tree_hash()])  # current or target
    else:
        raise ValueError

    current_singleton: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(last_coin_spend)
    assert current_singleton is not None

    if current_singleton.parent_coin_info == launcher_coin.name():
        parent_info_list = Program.to([launcher_coin.parent_coin_info, launcher_coin.amount])
    else:
        p = Program.from_bytes(bytes(last_coin_spend.puzzle_reveal))
        last_coin_spend_inner_puzzle: Optional[Program] = get_inner_puzzle_from_puzzle(p)
        assert last_coin_spend_inner_puzzle is not None
        parent_info_list = Program.to(
            [
                last_coin_spend.coin.parent_coin_info,
                last_coin_spend_inner_puzzle.get_tree_hash(),
                last_coin_spend.coin.amount,
            ]
        )
    full_solution: Program = Program.to([parent_info_list, current_singleton.amount, inner_sol])
    full_puzzle: Program = create_full_puzzle(inner_puzzle, launcher_coin.name())

    return (
        CoinSpend(
            current_singleton,
            SerializedProgram.from_program(full_puzzle),
            SerializedProgram.from_program(full_solution),
        ),
        inner_puzzle,
    )


def create_absorb_spend(
    last_coin_spend: CoinSpend,
    current_state: PoolState,
    launcher_coin: Coin,
    height: uint32,
    genesis_challenge: bytes32,
    delay_time: uint64,
    delay_ph: bytes32,
) -> List[CoinSpend]:
    inner_puzzle: Program = pool_state_to_inner_puzzle(
        current_state, launcher_coin.name(), genesis_challenge, delay_time, delay_ph
    )
    reward_amount: uint64 = calculate_pool_reward(height)
    if is_pool_member_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol: Program = Program.to([reward_amount, height])
    elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
        # inner sol is (spend_type, destination_puzhash, pool_reward_amount, pool_reward_height, extra_data)
        inner_sol = Program.to([0, reward_amount, height])
    else:
        raise ValueError
    # full sol = (parent_info, my_amount, inner_solution)
    coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(last_coin_spend)
    assert coin is not None

    if coin.parent_coin_info == launcher_coin.name():
        parent_info: Program = Program.to([launcher_coin.parent_coin_info, launcher_coin.amount])
    else:
        p = Program.from_bytes(bytes(last_coin_spend.puzzle_reveal))
        last_coin_spend_inner_puzzle: Optional[Program] = get_inner_puzzle_from_puzzle(p)
        assert last_coin_spend_inner_puzzle is not None
        parent_info = Program.to(
            [
                last_coin_spend.coin.parent_coin_info,
                last_coin_spend_inner_puzzle.get_tree_hash(),
                last_coin_spend.coin.amount,
            ]
        )
    full_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to([parent_info, last_coin_spend.coin.amount, inner_sol])
    )
    full_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_full_puzzle(inner_puzzle, launcher_coin.name())
    )
    assert coin.puzzle_hash == full_puzzle.get_tree_hash()

    reward_parent: bytes32 = pool_parent_id(height, genesis_challenge)
    p2_singleton_puzzle: SerializedProgram = SerializedProgram.from_program(
        create_p2_singleton_puzzle(SINGLETON_MOD_HASH, launcher_coin.name(), delay_time, delay_ph)
    )
    reward_coin: Coin = Coin(reward_parent, p2_singleton_puzzle.get_tree_hash(), reward_amount)
    p2_singleton_solution: SerializedProgram = SerializedProgram.from_program(
        Program.to([inner_puzzle.get_tree_hash(), reward_coin.name()])
    )
    assert p2_singleton_puzzle.get_tree_hash() == reward_coin.puzzle_hash
    assert full_puzzle.get_tree_hash() == coin.puzzle_hash
    assert get_inner_puzzle_from_puzzle(Program.from_bytes(bytes(full_puzzle))) is not None

    coin_spends = [
        CoinSpend(coin, full_puzzle, full_solution),
        CoinSpend(reward_coin, p2_singleton_puzzle, p2_singleton_solution),
    ]
    return coin_spends


def get_most_recent_singleton_coin_from_coin_spend(coin_sol: CoinSpend) -> Optional[Coin]:
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
        raise ValueError("Attempting to unpack a non-waitingroom inner puzzle")
    r = inner_puzzle.uncurry()
    if r is None:
        raise ValueError("Failed to unpack inner puzzle")
    inner_f, args = r
    # p2_singleton_hash is the tree hash of the unique, curried P2_SINGLETON_MOD. See `create_p2_singleton_puzzle`
    # escape_puzzlehash is of the unique, curried POOL_WAITING_ROOM_MOD. See `create_waiting_room_inner_puzzle`
    target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash = tuple(args.as_iter())
    return inner_f, target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash


def uncurry_pool_waitingroom_inner_puzzle(inner_puzzle: Program) -> Tuple[Program, Program, Program, Program]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    if not is_pool_waitingroom_inner_puzzle(inner_puzzle):
        raise ValueError("Attempting to unpack a non-waitingroom inner puzzle")
    r = inner_puzzle.uncurry()
    if r is None:
        raise ValueError("Failed to unpack inner puzzle")
    inner_f, args = r
    v = args.as_iter()
    target_puzzle_hash, p2_singleton_hash, owner_pubkey, genesis_challenge, relative_lock_height = tuple(v)
    return target_puzzle_hash, relative_lock_height, owner_pubkey, p2_singleton_hash


def get_inner_puzzle_from_puzzle(full_puzzle: Program) -> Optional[Program]:
    p = Program.from_bytes(bytes(full_puzzle))
    r = p.uncurry()
    if r is None:
        return None
    _, args = r

    _, inner_puzzle = list(args.as_iter())
    if not is_pool_singleton_inner_puzzle(inner_puzzle):
        return None
    return inner_puzzle


def pool_state_from_extra_data(extra_data: Program) -> Optional[PoolState]:
    state_bytes: Optional[bytes] = None
    try:
        for key, value in extra_data.as_python():
            if key == b"p":
                state_bytes = value
                break
        if state_bytes is None:
            return None
        return PoolState.from_bytes(state_bytes)
    except TypeError as e:
        log.error(f"Unexpected return from PoolWallet Smart Contract code {e}")
        return None


def solution_to_pool_state(full_spend: CoinSpend) -> Optional[PoolState]:
    full_solution_ser: SerializedProgram = full_spend.solution
    full_solution: Program = Program.from_bytes(bytes(full_solution_ser))

    if full_spend.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
        # Launcher spend
        extra_data: Program = full_solution.rest().rest().first()
        return pool_state_from_extra_data(extra_data)

    # Not launcher spend
    inner_solution: Program = full_solution.rest().rest().first()

    # Spend which is not absorb, and is not the launcher
    num_args = len(inner_solution.as_python())
    assert num_args in (2, 3)

    if num_args == 2:
        # pool member
        if inner_solution.rest().first().as_int() != 0:
            return None

        # This is referred to as p1 in the chialisp code
        # spend_type is absorbing money if p1 is a cons box, spend_type is escape if p1 is an atom
        # TODO: The comment above, and in the CLVM, seems wrong
        extra_data = inner_solution.first()
        if isinstance(extra_data.as_python(), bytes):
            # Absorbing
            return None
        return pool_state_from_extra_data(extra_data)
    else:
        # pool waitingroom
        if inner_solution.first().as_int() == 0:
            return None
        extra_data = inner_solution.rest().first()
        return pool_state_from_extra_data(extra_data)


def pool_state_to_inner_puzzle(
    pool_state: PoolState, launcher_id: bytes32, genesis_challenge: bytes32, delay_time: uint64, delay_ph: bytes32
) -> Program:
    escaping_inner_puzzle: Program = create_waiting_room_inner_puzzle(
        pool_state.target_puzzle_hash,
        pool_state.relative_lock_height,
        pool_state.owner_pubkey,
        launcher_id,
        genesis_challenge,
        delay_time,
        delay_ph,
    )
    if pool_state.state in [LEAVING_POOL, SELF_POOLING]:
        return escaping_inner_puzzle
    else:
        return create_pooling_inner_puzzle(
            pool_state.target_puzzle_hash,
            escaping_inner_puzzle.get_tree_hash(),
            pool_state.owner_pubkey,
            launcher_id,
            genesis_challenge,
            delay_time,
            delay_ph,
        )
