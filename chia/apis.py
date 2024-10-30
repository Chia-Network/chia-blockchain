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

ApiProtocolRegistry: dict[NodeType, ApiProtocol] = {
    NodeType.FULL_NODE: cast(ApiProtocol, FullNodeAPI),
    NodeType.WALLET: cast(ApiProtocol, WalletNodeAPI),
    NodeType.INTRODUCER: cast(ApiProtocol, IntroducerAPI),
    NodeType.TIMELORD: cast(ApiProtocol, TimelordAPI),
    NodeType.FARMER: cast(ApiProtocol, FarmerAPI),
    NodeType.HARVESTER: cast(ApiProtocol, HarvesterAPI),
}
