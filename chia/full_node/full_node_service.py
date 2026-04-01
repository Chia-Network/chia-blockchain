from __future__ import annotations

from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_rpc_api import FullNodeRpcApi
from chia.server.start_service import Service

FullNodeService = Service[FullNode, FullNodeAPI, FullNodeRpcApi]
