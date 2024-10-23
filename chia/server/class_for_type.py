from __future__ import annotations

from typing import cast

from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester_api import HarvesterAPI
from chia.introducer.introducer_api import IntroducerAPI
from chia.server.api_protocol import ApiProtocol
from chia.server.outbound_message import NodeType
from chia.timelord.timelord_api import TimelordAPI
from chia.wallet.wallet_node_api import WalletNodeAPI


def register_all(d: dict[NodeType, ApiProtocol]) -> None:
    for k, v in [
        (NodeType.FULL_NODE, FullNodeAPI),
        (NodeType.WALLET, WalletNodeAPI),
        (NodeType.INTRODUCER, IntroducerAPI),
        (NodeType.TIMELORD, TimelordAPI),
        (NodeType.FARMER, FarmerAPI),
        (NodeType.HARVESTER, HarvesterAPI),
    ]:
        d[k] = cast(ApiProtocol, v)


GLOBAL_REGISTRY: dict[NodeType, ApiProtocol] = {}

register_all(GLOBAL_REGISTRY)

class_for_type: dict[NodeType, ApiProtocol] = GLOBAL_REGISTRY
