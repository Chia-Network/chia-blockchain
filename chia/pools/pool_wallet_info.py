from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple, Dict, Union

from blspy import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint8
from chia.util.streamable import streamable, Streamable
from chia.wallet.cc_wallet.ccparent import CCParent

from chia.wallet.transaction_record import TransactionRecord


POOL_PROTOCOL_VERSION = uint8(1)


class PoolSingletonState(IntEnum):
    """
    From the user's point of view, a pool group can be in these states:
    `PENDING_CREATION`: The puzzle controlling the pool group has been created,
        but the genesis coin / singleton has not appeared on the blockchain
        yet. The user could technically farm to this puzzle_hash, but we simplify
        the GUI but not allowing plotting or use of the PoolWallet until the singleton
        is created.

    `SELF_POOLING`: The singleton exists on the blockchain, and we are farming
        block rewards to a wallet address controlled by the user

    `LEAVING_POOL`: The singleton exists, and we have entered the "escaping" state.

    `FARMING_TO_POOL`: The singleton exists, and it is assigned to a pool.

    `CLAIMING_SELF_POOLED_REWARDS`: We have submitted a transaction to sweep our
        self-pooled funds.
    """

    SELF_POOLING = 1
    LEAVING_POOL = 2
    FARMING_TO_POOL = 3

    # Revise this: we need to transition through the pending
    # "claim rewards" tx, then the "leave self-pooling" tx
    # CLAIMING_SELF_POOLED_REWARDS = 5


SELF_POOLING = PoolSingletonState.SELF_POOLING
LEAVING_POOL = PoolSingletonState.LEAVING_POOL
FARMING_TO_POOL = PoolSingletonState.FARMING_TO_POOL


@dataclass(frozen=True)
@streamable
class TargetState(Streamable):
    """
    User description of the
    Does not include information that is fixed at PoolWallet creation time, per-pool
    """

    pass


class PoolKeys:
    # `target_puzzle_hash` is the ph the script is locked to pay to
    # Note: If we allowed setting target_puzzle_hash in the self-pooling state,
    # We might want to check that the target_puzzle_hash is spendable by the current
    # user wallet. For now, let's choose it ourselves in the self-pooling case.
    target_puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class PoolState(Streamable):
    """
    `PoolState` is a type that is serialized to the blockchain to track the state of the user's pool singleton
    `target_puzzle_hash` is either the pool address, or the self-pooling address that pool rewards will be paid to.
    `target_puzzle_hash` is NOT the p2_singleton puzzle that block rewards are sent to.
    The `p2_singleton` address is the initial address, and the `target_puzzle_hash` is the final destination.
    `relative_lock_height` is zero when in SELF_POOLING state
    """

    version: uint8
    state: uint8  # PoolSingletonState
    # `target_puzzle_hash`: A puzzle_hash we pay to
    # Either set by the main wallet in the self-pool case,
    # or sent by the pool
    target_puzzle_hash: bytes32
    # owner_pubkey is set by the wallet, once
    owner_pubkey: G1Element
    # Fields below are only valid in `FARMING_TO_POOL` state
    pool_url: Optional[str]
    relative_lock_height: uint32


def pool_state_from_dict(
    state_dict: Dict, owner_pubkey: G1Element, owner_puzzle_hash: bytes32
) -> Union[Tuple[str, None], Tuple[None, PoolState]]:
    state_str = state_dict["state"]
    if state_str not in ["SELF_POOLING", "FARMING_TO_POOL"]:
        return "Initial State must be SELF_POOLING or FARMING_TO_POOL", None

    singleton_state = PoolSingletonState[state_str]
    pool_url = None
    relative_lock_height = None
    target_puzzle_hash = None

    if singleton_state == SELF_POOLING:
        target_puzzle_hash = owner_puzzle_hash
        relative_lock_height = 0
    elif singleton_state == FARMING_TO_POOL:
        target_puzzle_hash = bytes32(hexstr_to_bytes(state_dict["target_puzzle_hash"]))
        pool_url = state_dict["pool_url"]
        relative_lock_height = state_dict["relative_lock_height"]

    # TODO: change create_pool_state to return error messages, as well
    return None, create_pool_state(singleton_state, target_puzzle_hash, owner_pubkey, pool_url, relative_lock_height)


def normalize_pool_state():
    pass


def create_pool_state(
    state: PoolSingletonState,
    target_puzzle_hash: bytes32,
    owner_pubkey: G1Element,
    pool_url: Optional[str],
    relative_lock_height: Optional[uint32],
) -> PoolState:
    if state not in set(s.value for s in PoolSingletonState):
        raise AssertionError("state {state} is not a valid PoolSingletonState,")
    ps = PoolState(
        POOL_PROTOCOL_VERSION, uint8(state), target_puzzle_hash, owner_pubkey, pool_url, relative_lock_height
    )
    # TODO Move verify here
    return ps


# pool wallet transaction types:


@dataclass(frozen=True)
@streamable
class PoolWalletInfo(Streamable):
    """
    Internal Pool Wallet state, not destined for the blockchain
    """

    # Regarding target state, reorgs and the same pool wallet id on
    # multiple computers:
    # * If our state is reverted on the blockchain, because of a reorg, or another computer
    #   with the same wallet,
    # How long will the main_wallet retry a transaction?
    # * Conflicting transaction:

    # done with reorg? reset target
    #
    current: PoolState
    target: Optional[PoolState]
    launcher_coin: Coin
    current_inner: Program  # Inner puzzle in current singleton, not revealed yet
    tip_singleton_coin_id: bytes32
