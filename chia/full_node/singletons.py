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
    all_recent_singleton_coin_ids: Dict[bytes32, Tuple[uint32, bytes32]]
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
                # TODO: rebuild singleton info
                pass
            else:
                info = dataclasses.replace(info, state_history=new_history, latest_state=latest_coin)
            self.singleton_history[launcher_id] = info

    async def add_state(self, launcher_id: bytes32, latest_state: CoinRecord) -> None:
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

    async def is_recent_singleton(self, coin_id: bytes32) -> bool:
        return coin_id in self.all_recent_singleton_coin_ids

    async def get_latest_coin_record_by_launcher_id(self, launcher_id: bytes32) -> Optional[CoinRecord]:
        return self.singleton_history.get(launcher_id).latest_state

    async def get_latest_coin_record_by_coin_id(self, recent_coin_id: bytes32) -> Optional[CoinRecord]:
        launcher_id_h: Optional[Tuple[uint32, bytes32]] = self.all_recent_singleton_coin_ids.get(recent_coin_id)
        if launcher_id_h is None:
            return None
        return self.singleton_history.get(launcher_id_h[1]).latest_state


class SingletonTracker:
    _singleton_store: SingletonStore
    _coin_store: CoinStore
    fully_started: bool

    def __init__(self, coin_store: CoinStore):
        self._coin_store = coin_store
        self._singleton_store = SingletonStore()
        self.fully_started = False

    async def start1(self, peak_height: uint32) -> None:
        # Call start1 without blockchain lock, then call start2 with blockchain lock
        await self._find_singletons_up_to_height(peak_height - 100)

    async def start2(self, peak_height: uint32) -> None:
        # Call start1 without blockchain lock, then call start2 with blockchain lock
        await self._find_singletons_up_to_height(peak_height)
        self.fully_started = True

    async def new_peak(self, fork_point: uint32, peak_height: uint32) -> None:
        assert self.fully_started
        await self._singleton_store.rollback(fork_point)
        await self._find_singletons_up_to_height(uint32(peak_height + 1))

    async def is_recent_singleton(self, coin_id: bytes32) -> bool:
        assert self.fully_started
        return await self._singleton_store.is_recent_singleton(coin_id)

    async def get_latest_coin_record_by_launcher_id(self, launcher_id: bytes32) -> Optional[CoinRecord]:
        return await self._singleton_store.get_latest_coin_record_by_launcher_id(launcher_id)

    async def get_latest_coin_record_by_coin_id(self, recent_coin_id: bytes32) -> Optional[CoinRecord]:
        return await self._singleton_store.get_latest_coin_record_by_coin_id(recent_coin_id)

    async def _find_singletons_up_to_height(self, end_height: uint32) -> None:
        # Returns a mapping from singleton ID to recent coin IDs, including the last singleton coin ID that happened
        # before or at end_height. If a checkpoint at an older height is provided, we assume that the blockchain
        # has not been reverted past that height, and we only get the diffs from that height. Be careful with
        # calling this method with a recent height, because you might get information that changes when the blockchain
        # changes. Locking the blockchain is recommended in this case. The best way to use this method is to call it
        # twice, first, an initial call without a lock, and with a non-recent end_height (for example 100 blocks in the
        # past). Then, after each block, call it again under the blockchain lock but with the checkpoint, so it can
        # finish quickly.

        recent_threshold_height = end_height - 100

        def confirmed_recently(cr: CoinRecord) -> bool:
            return cr.confirmed_block_index > recent_threshold_height

        if checkpoint is not None:
            if end_height <= checkpoint.height:
                raise ValueError("End height must occur after the checkpoint height")

            start_height = checkpoint.height
            remaining_launcher_coin_and_curr: List[Tuple[bytes32, CoinRecord]] = [
                (info.launcher_id, info.latest_state) for info in checkpoint.singleton_information
            ]
        else:
            start_height = uint32(0)
            remaining_launcher_coin_and_curr = []

        launcher_coins: List[CoinRecord] = await self._coin_store.get_coin_records_by_puzzle_hash(
            True, LAUNCHER_PUZZLE_HASH, start_height=start_height, end_height=end_height
        )
        log.warning(f"Found {len(launcher_coins)} launcher coins")
        recent_coin_ids: Dict[bytes32, List[bytes32]] = {}
        latest_state: Dict[bytes32, CoinRecord] = {}
        chunk_size = 1000
        start_t = time.time()

        remaining_launcher_coin_and_curr += [(lc.name, lc) for lc in launcher_coins]
        active_launcher_coin_and_curr: List[Tuple[bytes32, CoinRecord]] = remaining_launcher_coin_and_curr[:chunk_size]
        remaining_launcher_coin_and_curr = remaining_launcher_coin_and_curr[chunk_size:]

        # Iterates through all launcher coins, which create potential singletons
        while len(active_launcher_coin_and_curr) > 0:
            new_active_launcher_coin_and_curr: List[Tuple[bytes32, CoinRecord]] = []
            to_lookup = []
            for launcher_id, curr in active_launcher_coin_and_curr:
                curr_name = curr.name
                if curr_name != launcher_id and confirmed_recently(curr):
                    # This is a recent spend, so add it to the list
                    if launcher_id not in recent_coin_ids:
                        recent_coin_ids[launcher_id] = []
                    recent_coin_ids[launcher_id].append(curr_name)

                if curr.spent:
                    to_lookup.append(curr_name)

            lookup_results: List[CoinRecord] = await self._coin_store.get_coin_records_by_parent_ids(True, to_lookup)
            lookup_results_by_parent: Dict[bytes32, List[CoinRecord]] = {}
            for cr in lookup_results:
                parent = cr.coin.parent_coin_info
                if parent not in lookup_results_by_parent:
                    lookup_results_by_parent[parent] = []
                lookup_results_by_parent[parent].append(cr)

            for launcher_id, curr in active_launcher_coin_and_curr:
                latest_state[launcher_id] = curr
                children = lookup_results_by_parent.get(curr.name, [])
                if len(children) == 0:
                    # If it's spent but there are no children, we assume it's invalid
                    if launcher_id in recent_coin_ids:
                        recent_coin_ids.pop(launcher_id)
                    continue
                else:
                    # If there is more than one odd child, it's not a valid singleton
                    if len(list(filter(lambda c: c.coin.amount % 2 == 1, children))) != 1:
                        if launcher_id in recent_coin_ids:
                            recent_coin_ids.pop(launcher_id)
                        continue
                    if curr.confirmed_block_index > end_height:
                        # If the spend occurs after end height, add the latest singleton ID that happened before that
                        recent_coin_ids[launcher_id].append(curr.name)
                        continue
                    else:
                        curr = [c for c in children if c.coin.amount % 2 == 1][0]
                        new_active_launcher_coin_and_curr.append((launcher_id, curr))

            add_new_singletons = chunk_size - len(new_active_launcher_coin_and_curr)
            active_launcher_coin_and_curr = (
                new_active_launcher_coin_and_curr.copy() + remaining_launcher_coin_and_curr[:add_new_singletons]
            )
            remaining_launcher_coin_and_curr = remaining_launcher_coin_and_curr[add_new_singletons:]

        log.warning(f"Time taken to lookup singletons: {time.time() - start_t} chunk size: {chunk_size}")
        ret = []
        for launcher_id, history in recent_coin_ids.items():
            ret.append(SingletonInformation(launcher_id, history, latest_state[launcher_id]))

        return BlockchainSingletonState(end_height, recent_threshold_height, ret)
