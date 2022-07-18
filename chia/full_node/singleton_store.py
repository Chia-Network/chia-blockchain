import asyncio
import dataclasses
import logging
import time
from typing import List, Tuple, Dict, Optional, Set

from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm

log = logging.getLogger(__name__)

LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
MAX_REORG_SIZE = 100


@dataclasses.dataclass
class SingletonInformation:
    launcher_spent_height: uint32
    last_non_recent_state: Optional[
        Tuple[uint32, bytes32]
    ]  # If None, all singleton states are recent (or only latest_state)
    recent_history: List[
        Tuple[uint32, bytes32]
    ]  # Only includes recent coin IDs. Excludes last non-recent state, launcher, and latest state
    latest_state: CoinRecord  # This is the latest state that we know of, for this singleton. It might not be spent.


class SingletonStore:
    """
    Maintains recent singletons and spends corresponding to the current peak of the blockchain.

    Usage:
    1. add_state
    2. set_peak_height

    The states added in step 1 must not be confirmed after the peak height provided in 2.
    add_state can only be called after creating the singleton (add_singleton).
    Rollback can be called, which reverses all outdated states.
    # TODO: optimize to not keep in memory things that are never used.
    """

    _singleton_history: Dict[bytes32, SingletonInformation]
    _latest_id_to_launcher_id: Dict[bytes32, bytes32]
    _peak_height: uint32
    _unspent_launcher_ids: Set[bytes32]
    _singleton_lock: asyncio.Lock

    def __init__(self, lock: asyncio.Lock):
        self._singleton_history = {}
        self._latest_id_to_launcher_id = {}
        self._peak_height = uint32(0)
        self._singleton_lock = lock
        self._unspent_launcher_ids = set()

    def is_recent(self, height: uint32) -> bool:
        return height >= (self._peak_height - MAX_REORG_SIZE)

    async def rollback(self, fork_height: uint32, coin_store: CoinStore):
        # TODO: test a few more edge cases in this method
        async with self._singleton_lock:
            assert fork_height < self._peak_height
            self._peak_height = fork_height

            to_remove: List[bytes32] = []
            for launcher_id, singleton_info in self._singleton_history.items():
                if singleton_info.launcher_spent_height > fork_height:
                    to_remove.append(launcher_id)
                    continue
                elif singleton_info.last_non_recent_state is not None:
                    new_recent = [t for t in singleton_info.recent_history if t[0] <= fork_height]

                    curr: Optional[CoinRecord] = await coin_store.get_coin_record(
                        singleton_info.last_non_recent_state[1]
                    )
                    assert curr is not None and curr.name != launcher_id
                    while curr.name != launcher_id and self.is_recent(curr.confirmed_block_index):
                        if curr.confirmed_block_index <= fork_height:
                            new_recent = [(curr.confirmed_block_index, curr.name)] + new_recent
                        curr = await coin_store.get_coin_record(curr.coin.parent_coin_info)

                    if curr.name != launcher_id:
                        last_non_recent_state = (curr.confirmed_block_index, curr.name)
                    else:
                        last_non_recent_state = None

                else:
                    # All states are in recent history. Remove only the ones that are rolled back. LNRC stays None.
                    assert singleton_info.last_non_recent_state is None
                    assert len(singleton_info.recent_history) > 0
                    if singleton_info.recent_history[-1][0] <= fork_height:
                        # No states rolled back
                        continue
                    new_recent = [t for t in singleton_info.recent_history if t[0] <= fork_height]
                    last_non_recent_state = None

                if singleton_info.latest_state.confirmed_block_index <= fork_height:
                    latest_state = singleton_info.latest_state
                elif len(new_recent) > 0:
                    latest_state: Optional[CoinRecord] = await coin_store.get_coin_record(new_recent[-1][1])
                    new_recent = new_recent[:-1]
                else:
                    latest_state = await coin_store.get_coin_record(last_non_recent_state[1])
                    last_non_recent_state = None

                assert latest_state is not None and latest_state.confirmed_block_index <= fork_height
                assert len(new_recent) == 0 or latest_state.coin.name() != new_recent[-1][1]
                self._latest_id_to_launcher_id.pop(singleton_info.latest_state.name)
                self._singleton_history[launcher_id] = dataclasses.replace(
                    singleton_info,
                    recent_history=new_recent,
                    latest_state=latest_state,
                    last_non_recent_state=last_non_recent_state,
                )
                self._latest_id_to_launcher_id[latest_state.name] = launcher_id
            for launcher_id in to_remove:
                await self.remove_singleton(launcher_id, acquire_lock=False)

    async def add_state(self, launcher_id: bytes32, latest_state: CoinRecord) -> None:
        # Adds a state that is confirmed at or before peak height
        # We do not adjust or prune recent history here

        assert latest_state.confirmed_block_index <= self._peak_height
        async with self._singleton_lock:
            if latest_state.coin.parent_coin_info == launcher_id:
                # Creation of singleton
                if launcher_id in self._unspent_launcher_ids:
                    self._unspent_launcher_ids.remove(launcher_id)

                if launcher_id in self._singleton_history:
                    raise ValueError(f"Singleton {launcher_id} already exists.")
                self._singleton_history[launcher_id] = SingletonInformation(
                    latest_state.confirmed_block_index, None, [], latest_state
                )
                self._latest_id_to_launcher_id[latest_state.name] = launcher_id
                return
            # Spend of already created singleton
            if launcher_id not in self._singleton_history:
                raise ValueError(f"Singleton {launcher_id} does not exist.")

            info = self._singleton_history[launcher_id]
            if latest_state == info.latest_state:
                raise ValueError(f"Already have state: {latest_state}")

            if latest_state.coin.parent_coin_info != info.latest_state.name:
                raise ValueError(f"Invalid state {latest_state.coin} does not follow {latest_state.coin}")

            if len(info.recent_history) > 0 or self.is_recent(info.latest_state.confirmed_block_index):
                new_info = dataclasses.replace(
                    info,
                    last_non_recent_state=info.last_non_recent_state,
                    latest_state=latest_state,
                    recent_history=info.recent_history
                    + [(info.latest_state.confirmed_block_index, latest_state.coin.parent_coin_info)],
                )
            else:
                new_info = dataclasses.replace(
                    info,
                    last_non_recent_state=(info.latest_state.confirmed_block_index, latest_state.coin.parent_coin_info),
                    latest_state=latest_state,
                    recent_history=[],
                )
            self._latest_id_to_launcher_id.pop(info.latest_state.name)
            self._singleton_history[launcher_id] = new_info
            self._latest_id_to_launcher_id[latest_state.name] = launcher_id

    async def set_peak_height(
        self, height: uint32, unspent_launcher_ids: Set[bytes32], force_update_of_recent: bool = True
    ) -> None:
        async with self._singleton_lock:
            assert height >= self._peak_height  # If going back, use rollback instead
            self._peak_height = height
            self._unspent_launcher_ids.update(unspent_launcher_ids)

            # Periodically update the cache to remove things from the recent list
            if force_update_of_recent:
                for launcher_id, singleton_info in self._singleton_history.items():
                    assert singleton_info.latest_state.confirmed_block_index <= height
                    no_longer_recent: List[Tuple[uint32, bytes32]] = []
                    for h, coin_id in singleton_info.recent_history:
                        if not self.is_recent(h):
                            no_longer_recent.append((h, coin_id))
                        else:
                            break
                    if len(no_longer_recent) > 0:
                        self._singleton_history[launcher_id] = SingletonInformation(
                            launcher_spent_height=singleton_info.launcher_spent_height,
                            last_non_recent_state=no_longer_recent[-1],
                            recent_history=singleton_info.recent_history[len(no_longer_recent) :],
                            latest_state=singleton_info.latest_state,
                        )

    async def get_peak_height(self) -> uint32:
        async with self._singleton_lock:
            return self._peak_height

    async def get_latest_coin_record_by_launcher_id(self, launcher_id: bytes32) -> Optional[CoinRecord]:
        async with self._singleton_lock:
            cr: Optional[CoinRecord] = self._singleton_history.get(launcher_id)
            if cr is None:
                return None
            return cr.latest_state

    def get_all_singletons(self) -> Dict[bytes32, SingletonInformation]:
        return self._singleton_history

    def get_unspent_launcher_ids(self) -> Set[bytes32]:
        return self._unspent_launcher_ids

    def latest_state_to_launcher_id(self, latest_coin_id: bytes32) -> Optional[bytes32]:
        return self._latest_id_to_launcher_id.get(latest_coin_id, None)

    async def remove_singleton(self, launcher_id: bytes32, acquire_lock: bool = True) -> None:
        if launcher_id not in self._singleton_history:
            return
        latest_state_name: bytes32 = self._singleton_history[launcher_id].latest_state.name
        if not acquire_lock:
            self._singleton_history.pop(launcher_id)
            self._latest_id_to_launcher_id.pop(latest_state_name)
            return

        async with self._singleton_lock:
            self._singleton_history.pop(launcher_id)
            self._latest_id_to_launcher_id.pop(latest_state_name)
