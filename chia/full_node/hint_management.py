from typing import List, Tuple, Dict, Set

from chia.consensus.blockchain import StateChangeSummary
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.generator_tools import tx_removals_additions_and_hints


def get_hints_and_subscription_coin_ids(
    state_change_summary: StateChangeSummary,
    coin_subscriptions: Dict[bytes32, Set[bytes32]],
    ph_subscriptions: Dict[bytes32, Set[bytes32]],
) -> Tuple[List[Tuple[bytes32, bytes]], Set[bytes32]]:
    # Adds hints to the database based on recent changes, and compiles a list of changes to send to wallets

    # Finds the coin IDs that we need to lookup in order to notify wallets of hinted transactions
    hint: bytes
    hints_to_add: List[Tuple[bytes32, bytes]] = []

    # Goes through additions and removals for each block and flattens to a map and a set
    potential_ph_to_coin_id: Dict[bytes32, bytes32] = {}
    potential_coin_ids: Set[bytes32] = set()
    for npc_result in state_change_summary.new_npc_results:
        removals, additions_with_h = tx_removals_additions_and_hints(npc_result.conds)

        # Record all coin_ids that we are interested in, that had changes
        for removal_coin_id, removal_ph in removals:
            potential_coin_ids.add(removal_coin_id)
            potential_ph_to_coin_id[removal_ph] = removal_coin_id

        for addition_coin, hint in additions_with_h:
            addition_coin_name = addition_coin.name()
            potential_coin_ids.add(addition_coin_name)
            potential_ph_to_coin_id[addition_coin.puzzle_hash] = addition_coin_name
            if len(hint) == 32:
                potential_ph_to_coin_id[bytes32(hint)] = addition_coin_name

            if len(hint) > 0:
                hints_to_add.append((addition_coin_name, hint))

    # Goes through all new reward coins
    for reward_coin in state_change_summary.new_rewards:
        potential_coin_ids.add(reward_coin.name())
        potential_ph_to_coin_id[reward_coin.puzzle_hash] = reward_coin.name()

    # Filters out any coin ID that connected wallets are not interested in
    lookup_coin_ids: Set[bytes32] = {coin_id for coin_id in potential_coin_ids if coin_id in coin_subscriptions}
    lookup_coin_ids.update({coin_id for ph, coin_id in potential_ph_to_coin_id.items() if ph in ph_subscriptions})

    return hints_to_add, lookup_coin_ids
