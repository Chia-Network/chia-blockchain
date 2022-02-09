from typing import Dict, Tuple, Any, Optional, List

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32


class PeerRequestCache:
    blocks: Dict[uint32, HeaderBlock]
    block_requests: Dict[Tuple[int, int], Any]
    ses_requests: Dict[int, Any]
    states_validated: Dict[bytes32, CoinState]

    def __init__(self):
        self.blocks = {}
        self.ses_requests = {}
        self.block_requests = {}
        self.states_validated = {}

    def clear_after_height(self, height: int):
        # Remove any cached item which relates to an event that happened at a height above height.
        self.blocks = {k: v for k, v in self.blocks.items() if k <= height}
        self.block_requests = {k: v for k, v in self.block_requests.items() if k[0] <= height and k[1] <= height}
        self.ses_requests = {k: v for k, v in self.ses_requests.items() if k <= height}

        remove_keys_states: List[bytes32] = []
        for k4, coin_state in self.states_validated.items():
            if coin_state.created_height is not None and coin_state.created_height > height:
                remove_keys_states.append(k4)
            elif coin_state.spent_height is not None and coin_state.spent_height > height:
                remove_keys_states.append(k4)
        for k5 in remove_keys_states:
            self.states_validated.pop(k5)


async def can_use_peer_request_cache(
    coin_state: CoinState, peer_request_cache: PeerRequestCache, fork_height: Optional[uint32]
):
    if coin_state.get_hash() not in peer_request_cache.states_validated:
        return False
    if fork_height is None:
        return True
    if coin_state.created_height is None and coin_state.spent_height is None:
        # Performing a reorg
        return False
    if coin_state.created_height is not None and coin_state.created_height > fork_height:
        return False
    if coin_state.spent_height is not None and coin_state.spent_height > fork_height:
        return False
    return True
