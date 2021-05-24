from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple, Dict, Union

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
        yet. The user could technically farm to this puzzlehash, but we simplify
        the GUI but not allowing plotting or use of the PoolWallet until the singleton
        is created.

    `SELF_POOLING`: The singleton exists on the blockchain, and we are farming
        block rewards to a wallet address controlled by the user

    `LEAVING_POOL`: The singleton exists, and we have entered the "escaping" state.

    `FARMING_TO_POOL`: The singleton exists, and it is assigned to a pool.

    `CLAIMING_SELF_POOLED_REWARDS`: We have submitted a transaction to sweep our
        self-pooled funds.
    """

    PENDING_CREATION = 1
    SELF_POOLING = 2
    LEAVING_POOL = 3
    FARMING_TO_POOL = 4

    # Revise this: we need to transition through the pending
    # "claim rewards" tx, then the "leave self-pooling" tx
    # CLAIMING_SELF_POOLED_REWARDS = 5


PENDING_CREATION = PoolSingletonState.PENDING_CREATION
SELF_POOLING = PoolSingletonState.SELF_POOLING
LEAVING_POOL = PoolSingletonState.LEAVING_POOL
FARMING_TO_POOL = PoolSingletonState.FARMING_TO_POOL


@dataclass(frozen=True)
@streamable
class PoolState(Streamable):
    """
    `PoolState` is a type that is serialized to the blockchain to track the state of the user's pool
    `target_puzzlehash` is either the pool address, or the self-pooling address that pool rewards will be paid to.
    `target_puzzlehash` is NOT the p2_singleton puzzle that block rewards are sent to.
    The `p2_singleton` address is the initial address, and the `target_puzzlehash` is the final destination.
    """

    version: uint8
    state: uint8  # PoolSingletonState
    target_puzzlehash: bytes32
    # Fields below are only valid in `FARMING_TO_POOL` state
    pool_url: Optional[str]
    relative_lock_height: Optional[uint32]


def pool_state_from_dict(state_dict: Dict) -> Union[Tuple[str, None], Tuple[None, PoolState]]:
    state_str = state_dict["state"]
    if state_str not in ["SELF_POOLING", "FARMING_TO_POOL"]:
        return "Initial State must be SELF_POOLING or FARMING_TO_POOL", None
    singleton_state = PoolSingletonState[state_str]
    target_puzzlehash = None
    pool_url = None
    relative_lock_height = None
    if "target_puzzlehash" in state_dict:
        target_puzzlehash = bytes32(hexstr_to_bytes(state_dict["target_puzzlehash"]))
    if singleton_state == PoolSingletonState.FARMING_TO_POOL:
        pool_url = state_dict["pool_url"]
        relative_lock_height = state_dict["relative_lock_height"]
    # TODO: change create_pool_state to return error messages, as well
    return None, create_pool_state(singleton_state, target_puzzlehash, pool_url, relative_lock_height)


def normalize_pool_state():
    pass


def create_pool_state(
    state: PoolSingletonState,
    target_puzzlehash: bytes32,
    pool_url: Optional[str],
    relative_lock_height: Optional[uint32],
) -> PoolState:
    if state not in set(s.value for s in PoolSingletonState):
        raise AssertionError("state {state} is not a valid PoolSingletonState,")
    ps = PoolState(POOL_PROTOCOL_VERSION, uint8(state), target_puzzlehash, pool_url, relative_lock_height)
    # TODO verify here, as well.
    return ps


# pool wallet transaction types:
@dataclass(frozen=True)
@streamable
class PoolWalletInfo(Streamable):
    """
    Internal Pool Wallet state, not destined for the blockchain
    """

    current: PoolState
    target: PoolState
    pending_transaction: Optional[TransactionRecord]
    origin_coin: Optional[Coin]  # puzzlehash of this coin is our Singleton state
    parent_list: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
    current_inner: Optional[Program]  # represents a Program as bytes
    self_pooled_reward_list: List[bytes32]
    # current_derivation_path: DerivationRecord # this is the rewards_pubkey and rewards_puzzlehash
    # current_rewards_pubkey: bytes  # a pubkey from our default wallet
    # current_rewards_puzhash: bytes32  # A puzzlehash we control
