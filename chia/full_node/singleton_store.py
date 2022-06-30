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
    """

    _singleton_history: Dict[bytes32, SingletonInformation]
    _peak_height: uint32()
    _singleton_lock: asyncio.Lock

    def __init__(self, lock: asyncio.Lock):
        self._singleton_history = {}
        self._peak_height = uint32(0)
        self._singleton_lock = lock

    def is_recent(self, height: uint32) -> bool:
        return height >= (self._peak_height - MAX_REORG_SIZE)

    async def rollback(self, fork_height: uint32, coin_store: CoinStore):
        async with self._singleton_lock:
            assert fork_height < self._peak_height
            self._peak_height = fork_height

            for launcher_id, singleton_info in self._singleton_history.items():
                if singleton_info.launcher_spent_height > fork_height:
                    await self.remove_singleton(launcher_id)
                    continue
                elif singleton_info.last_non_recent_state is not None:
                    all_recent = [t for t in singleton_info.recent_history if t[0] <= fork_height]

                    curr: Optional[CoinRecord] = await coin_store.get_coin_record(
                        singleton_info.last_non_recent_state[1]
                    )
                    assert curr is not None and curr.name != launcher_id
                    while curr.name != launcher_id:
                        all_recent = [(curr.confirmed_block_index, curr.name)] + all_recent
                        curr = await coin_store.get_coin_record(curr.coin.parent_coin_info)
                    new_recent = list(filter(lambda t: self.is_recent(t[0]), all_recent))

                    if len(new_recent) == len(all_recent):
                        last_non_recent_state = None
                    else:
                        last_non_recent_state = all_recent[len(all_recent) - len(new_recent) - 1]
                    latest_state: Optional[CoinRecord] = await coin_store.get_coin_record(all_recent[-1][1])

                else:
                    # All states are in recent history. Remove only the ones that are rolled back. LNRC stays None.
                    assert singleton_info.last_non_recent_state is None
                    assert len(singleton_info.recent_history) > 0
                    if singleton_info.recent_history[-1][0] <= fork_height:
                        # No states rolled back
                        return
                    new_recent = [t for t in singleton_info.recent_history if t[0] <= fork_height]
                    latest_state = await coin_store.get_coin_record(new_recent[-1][1])
                    last_non_recent_state = None

                assert latest_state is not None and latest_state.confirmed_block_index <= fork_height
                self._singleton_history[launcher_id] = dataclasses.replace(
                    singleton_info,
                    recent_history=new_recent,
                    latest_state=latest_state,
                    last_non_recent_state=last_non_recent_state,
                )

    async def add_singleton(
        self, launcher_id: bytes32, launcher_spend_height: uint32, first_singleton_cr: CoinRecord
    ) -> None:
        async with self._singleton_lock:
            if launcher_id in self._singleton_history:
                raise ValueError(f"Singleton {launcher_id} already exists.")
            self._singleton_history[launcher_id] = SingletonInformation(
                launcher_spend_height, None, [], first_singleton_cr
            )

    async def add_state(self, launcher_id: bytes32, latest_state: CoinRecord) -> None:
        async with self._singleton_lock:
            if launcher_id not in self._singleton_history:
                raise ValueError(f"Singleton {launcher_id} does not exist.")

            info = self._singleton_history[launcher_id]
            if latest_state == info.latest_state:
                raise ValueError(f"Already have state: {latest_state}")

            if latest_state.coin.parent_coin_info != info.latest_state.name:
                raise ValueError(f"Invalid state {latest_state.coin} does not follow {latest_state.coin}")

            # Double check that we have past states in the history (or empty)
            # assert len(info.state_history) == 0 or info.latest_state.coin.parent_coin_info == info.state_history[-1]
            if self.is_recent(latest_state.confirmed_block_index):
                info = dataclasses.replace(
                    info,
                    last_non_recent_state=info.last_non_recent_state,
                    latest_state=latest_state,
                    recent_history=info.recent_history
                    + [(info.latest_state.confirmed_block_index, latest_state.coin.parent_coin_info)],
                )
            self._singleton_history[launcher_id] = info

    async def set_peak_height(self, height: uint32) -> None:
        async with self._singleton_lock:
            assert height >= self._peak_height  # If going back, use rollback instead
            self._peak_height = height

            # Periodically update the cache to remove things from the recent list
            if height % 10 == 0:
                for launcher_id, singleton_info in self._singleton_history.items():
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
            return self._singleton_history.get(launcher_id).latest_state

    async def remove_singleton(self, launcher_id: bytes32) -> None:
        async with self._singleton_lock:
            if launcher_id not in self._singleton_history:
                return
            self._singleton_history.pop(launcher_id)
