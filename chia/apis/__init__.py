from __future__ import annotations

from chia.apis.farmer_api_schema import FarmerApiSchema
from chia.apis.full_node_api_schema import FullNodeApiSchema
from chia.apis.harvester_api_schema import HarvesterApiSchema
from chia.apis.introducer_api_schema import IntroducerApiSchema
from chia.apis.solver_api_schema import SolverApiSchema
from chia.apis.timelord_api_schema import TimelordApiSchema
from chia.apis.wallet_api_schema import WalletNodeApiSchema
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiSchemaProtocol

ApiProtocolRegistry: dict[NodeType, type[ApiSchemaProtocol]] = {
    NodeType.FARMER: FarmerApiSchema,
    NodeType.FULL_NODE: FullNodeApiSchema,
    NodeType.HARVESTER: HarvesterApiSchema,
    NodeType.INTRODUCER: IntroducerApiSchema,
    NodeType.SOLVER: SolverApiSchema,
    NodeType.TIMELORD: TimelordApiSchema,
    NodeType.WALLET: WalletNodeApiSchema,
}
