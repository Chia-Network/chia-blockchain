from typing import List

from chia.protocols.wallet_protocol import CoinState


def filter_coin_states(all_coins_state: List[CoinState], fork_height: int) -> List[CoinState]:
    # We only want to apply changes before the fork point, since we are synced to another peer
    # We are just validating that there is no missing information
    final_coin_state: List[CoinState] = []
    for coin_state_entry in all_coins_state:
        if coin_state_entry.spent_height is not None:
            if coin_state_entry.spent_height <= fork_height:
                final_coin_state.append(coin_state_entry)
        elif coin_state_entry.created_height is not None:
            if coin_state_entry.created_height <= fork_height:
                final_coin_state.append(coin_state_entry)
    return final_coin_state
