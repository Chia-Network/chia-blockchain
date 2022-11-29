from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from chia.consensus.blockchain import StateChangeSummary
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


def get_hints_and_subscription_coin_ids(
    state_change_summary: StateChangeSummary,
    coin_subscriptions: Dict[bytes32, Set[bytes32]],
    ph_subscriptions: Dict[bytes32, Set[bytes32]],
) -> Tuple[List[Tuple[bytes32, bytes]], List[bytes32]]:
    # Precondition: all hints passed in are max 32 bytes long
    # Returns the hints that we need to add to the DB, and the coin ids that need to be looked up

    # Finds the coin IDs that we need to lookup in order to notify wallets of hinted transactions
    hint: Optional[bytes]
    hints_to_add: List[Tuple[bytes32, bytes]] = []

    # Goes through additions and removals for each block and flattens to a map and a set
    lookup_coin_ids: Set[bytes32] = set()

    def add_if_coin_subscription(coin_id: bytes32) -> None:
        if coin_id in coin_subscriptions:
            lookup_coin_ids.add(coin_id)

    def add_if_ph_subscription(puzzle_hash: bytes32, coin_id: bytes32) -> None:
        if puzzle_hash in ph_subscriptions:
            lookup_coin_ids.add(coin_id)

    for npc_result in state_change_summary.new_npc_results:
        if npc_result.conds is not None:
            for spend in npc_result.conds.spends:
                # Record all coin_ids that we are interested in, that had changes
                add_if_coin_subscription(bytes32(spend.coin_id))
                add_if_ph_subscription(bytes32(spend.puzzle_hash), bytes32(spend.coin_id))

                for new_ph, new_am, hint in spend.create_coin:
                    addition_coin: Coin = Coin(bytes32(spend.coin_id), bytes32(new_ph), uint64(new_am))
                    addition_coin_name = addition_coin.name()
                    add_if_coin_subscription(addition_coin_name)
                    add_if_ph_subscription(addition_coin.puzzle_hash, addition_coin_name)
                    if hint is None:
                        continue
                    if len(hint) == 32:
                        add_if_ph_subscription(bytes32(hint), addition_coin_name)

                    if len(hint) > 0:
                        assert len(hint) <= 32
                        hints_to_add.append((addition_coin_name, hint))

    # Goes through all new reward coins
    for reward_coin in state_change_summary.new_rewards:
        reward_coin_name: bytes32 = reward_coin.name()
        add_if_coin_subscription(reward_coin_name)
        add_if_ph_subscription(reward_coin.puzzle_hash, reward_coin_name)

    return hints_to_add, list(lookup_coin_ids)
