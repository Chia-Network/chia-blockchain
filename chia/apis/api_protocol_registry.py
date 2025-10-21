from __future__ import annotations

from chia.apis.farmer_stub import FarmerApiStub
from chia.apis.full_node_stub import FullNodeApiStub
from chia.apis.harvester_stub import HarvesterApiStub
from chia.apis.introducer_stub import IntroducerApiStub
from chia.apis.solver_stub import SolverApiStub
from chia.apis.timelord_stub import TimelordApiStub
from chia.apis.wallet_stub import WalletNodeApiStub
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocol

ApiProtocolRegistry: dict[NodeType, type[ApiProtocol]] = {
    NodeType.FULL_NODE: FullNodeApiStub,
    NodeType.WALLET: WalletNodeApiStub,
    NodeType.INTRODUCER: IntroducerApiStub,
    NodeType.TIMELORD: TimelordApiStub,
    NodeType.FARMER: FarmerApiStub,
    NodeType.HARVESTER: HarvesterApiStub,
    NodeType.SOLVER: SolverApiStub,
}
