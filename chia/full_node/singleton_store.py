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


@dataclasses.dataclass
class SingletonInformation:
    launcher_id: bytes32
    state_history: List[bytes32]  # Only includes recent coin IDs + the latest coin ID. Launcher id not included
    latest_state: CoinRecord  # This is the latest state that we know of, for this singleton. It might not be spent.


class SingletonStore:
    recent_threshold: int
    recent_at_least: uint32
    all_recent_singleton_coin_ids: Dict[bytes32, Tuple[uint32, bytes32]]  # Coin ID -> (height, launcherID)
    singleton_history: Dict[bytes32, SingletonInformation]

    def __init__(self, recent_threshold: int = 500):
        self.recent_threshold = recent_threshold
        self.all_recent_singleton_coin_ids = {}
        self.singleton_history = {}
        self.recent_at_least = uint32(0)

    async def rollback(self, fork_height: uint32, coin_store: CoinStore):
        remove_coin_ids: Set[bytes32] = set()
        modify_singletons: Set[bytes32] = set()
        for coin_id, (h, launcher_id) in self.all_recent_singleton_coin_ids.items():
            if h <= fork_height:
                remove_coin_ids.add(coin_id)
                modify_singletons.add(launcher_id)
        for coin_id in remove_coin_ids:
            self.all_recent_singleton_coin_ids.pop(coin_id)
        for launcher_id in modify_singletons:
            info: SingletonInformation = self.singleton_history[launcher_id]
            latest_coin: Optional[CoinRecord] = None
            new_history: List[bytes32] = []
            for index, coin_id in enumerate(reversed(info.state_history)):
                latest_coin = await coin_store.get_coin_record(coin_id)
                if latest_coin is None or latest_coin.confirmed_block_index > fork_height:
                    # Not latest coin, it no longer exists
                    continue
                else:
                    # Found a coin which exists, so break
                    new_history = info.state_history[:-index]
                    break
            if latest_coin is None:
                launcher_coin: Optional[CoinRecord] = await coin_store.get_coin_record(launcher_id)
                if launcher_coin is None:
                    self.singleton_history.pop(launcher_id)
                    continue
                curr: CoinRecord = launcher_coin
                history: List[bytes32] = []
                while curr.spent:
                    if curr != launcher_coin and curr.confirmed_block_index > (fork_height - 100):
                        history.append(curr.name)
                    children: List[CoinRecord] = await coin_store.get_coin_records_by_parent_ids(
                        True, [curr.name], end_height=uint32(fork_height + 1)
                    )
                    if len(children) > 0:
                        # If there is more than one odd child, it's not a valid singleton
                        if len(list(filter(lambda c: c.coin.amount % 2 == 1, children))) != 1:
                            await self.remove_singleton(launcher_id)
                            break
                        curr = [c for c in children if c.coin.amount % 2 == 1][0]
                    elif curr.spent_block_index <= fork_height:
                        # This is a spent singleton without any children, so it's no longer valid
                        await self.remove_singleton(launcher_id)
                        break
                    else:
                        # This is a spent singleton that was spent after the end_height, so we will ignore it
                        if curr.name not in history:
                            history.append(curr.name)
                        break
                if launcher_id not in self.singleton_history:
                    # Singleton was removed
                    continue
                info = SingletonInformation(launcher_id, state_history=history, latest_state=curr)

            else:
                info = dataclasses.replace(info, state_history=new_history, latest_state=latest_coin)
            self.singleton_history[launcher_id] = info
            # TODO: remove from singleton history if non existing

    async def add_state(self, launcher_id: bytes32, latest_state: CoinRecord) -> None:
        if launcher_id not in self.singleton_history:
            self.singleton_history[launcher_id] = SingletonInformation(launcher_id, [], latest_state=latest_state)
            return

        info = self.singleton_history[launcher_id]
        if latest_state == info.latest_state:
            # Already have state
            return
        if latest_state.coin.parent_coin_info != info.latest_state.name:
            raise ValueError(f"Invalid state {latest_state.coin} does not follow {latest_state.coin}")

        # Double check that we have past states in the history (or empty)
        assert len(info.state_history) == 0 or info.latest_state.coin.parent_coin_info == info.state_history[-1]
        info = dataclasses.replace(
            info, latest_state=latest_state, state_history=info.state_history + [latest_state.coin.parent_coin_info]
        )
        self.singleton_history[launcher_id] = info

    async def set_recent_at_least(self, height: uint32):
        new_launcher_ids = {}
        self.recent_at_least = height

    async def get_latest_coin_record_by_launcher_id(self, launcher_id: bytes32) -> Optional[CoinRecord]:
        return self.singleton_history.get(launcher_id).latest_state

    async def remove_singleton(self, launcher_id: bytes32) -> None:
        if launcher_id not in self.singleton_history:
            return
        for coin_id in self.singleton_history[launcher_id].state_history:
            self.all_recent_singleton_coin_ids.pop(coin_id)
        self.singleton_history.pop(launcher_id)
