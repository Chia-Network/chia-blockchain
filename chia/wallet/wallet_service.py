from __future__ import annotations

from chia.server.start_service import Service
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
from chia.wallet.wallet_rpc_api import WalletRpcApi

WalletService = Service[WalletNode, WalletNodeAPI, WalletRpcApi]
