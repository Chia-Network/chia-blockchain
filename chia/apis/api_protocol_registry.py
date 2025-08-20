from __future__ import annotations

from chia.apis.farmer_stub import FarmerApiStub
from chia.apis.full_node_stub import FullNodeApiStub
from chia.apis.harvester_stub import HarvesterApiStub
from chia.apis.introducer_stub import IntroducerApiStub
from chia.apis.timelord_stub import TimelordApiStub
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocol
from chia.wallet.wallet_node_api import WalletNodeAPI

ApiProtocolRegistry: dict[NodeType, type[ApiProtocol]] = {
    NodeType.FULL_NODE: FullNodeApiStub,
    NodeType.WALLET: WalletNodeAPI,
    NodeType.INTRODUCER: IntroducerApiStub,
    NodeType.TIMELORD: TimelordApiStub,
    NodeType.FARMER: FarmerApiStub,
    NodeType.HARVESTER: HarvesterApiStub,
}
