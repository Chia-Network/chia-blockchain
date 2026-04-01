from __future__ import annotations

from chia.apis.farmer_stub import FarmerApiStub
from chia.apis.full_node_stub import FullNodeApiStub
from chia.apis.harvester_stub import HarvesterApiStub
from chia.apis.introducer_stub import IntroducerApiStub
from chia.apis.solver_stub import SolverApiStub
from chia.apis.timelord_stub import TimelordApiStub
from chia.apis.wallet_stub import WalletNodeApiStub
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiMetadata

StubMetadataRegistry: dict[NodeType, ApiMetadata] = {
    NodeType.FULL_NODE: FullNodeApiStub.metadata,
    NodeType.WALLET: WalletNodeApiStub.metadata,
    NodeType.INTRODUCER: IntroducerApiStub.metadata,
    NodeType.TIMELORD: TimelordApiStub.metadata,
    NodeType.FARMER: FarmerApiStub.metadata,
    NodeType.HARVESTER: HarvesterApiStub.metadata,
    NodeType.SOLVER: SolverApiStub.metadata,
}
