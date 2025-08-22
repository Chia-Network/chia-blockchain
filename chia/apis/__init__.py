from __future__ import annotations

from chia.apis.farmer_api_schema import FarmerApiSchema
from chia.apis.full_node_api_schema import FullNodeApiSchema
from chia.apis.harvester_api_schema import HarvesterApiSchema
from chia.apis.introducer_api_schema import IntroducerApiSchema
from chia.apis.timelord_api_schema import TimelordApiSchema
from chia.apis.wallet_api_schema import WalletNodeApiSchema
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocol

ApiProtocolRegistry: dict[NodeType, type[ApiProtocol]] = {
    NodeType.FULL_NODE: FullNodeApiSchema,
    NodeType.WALLET: WalletNodeApiSchema,
    NodeType.INTRODUCER: IntroducerApiSchema,
    NodeType.TIMELORD: TimelordApiSchema,
    NodeType.FARMER: FarmerApiSchema,
    NodeType.HARVESTER: HarvesterApiSchema,
}
