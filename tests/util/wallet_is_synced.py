from typing import List

from chia.full_node.full_node_api import FullNodeAPI
from chia.wallet.wallet_node import WalletNode


async def wallet_is_synced(wallet_node: WalletNode, full_node_api: FullNodeAPI) -> bool:
    wallet_height = await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()
    full_node_height = full_node_api.full_node.blockchain.get_peak_height()
    return wallet_height == full_node_height


async def wallets_are_synced(wns: List[WalletNode], full_node_api: FullNodeAPI) -> bool:
    return all([await wallet_is_synced(wn, full_node_api) for wn in wns])
