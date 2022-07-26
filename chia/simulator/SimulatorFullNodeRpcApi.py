from typing import Dict

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import Endpoint
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.util.bech32m import decode_puzzle_hash


class SimulatorFullNodeRpcApi(FullNodeRpcApi):
    def get_routes(self) -> Dict[str, Endpoint]:
        routes = super().get_routes()
        routes["/farm_tx_block"] = self.farm_tx_block
        return routes

    async def farm_tx_block(self, _request: Dict[str, object]) -> Dict[str, object]:
        request_address = str(_request["address"])
        ph = decode_puzzle_hash(request_address)
        req = FarmNewBlockProtocol(ph)
        await self.service.server.api.farm_new_transaction_block(req)
        return {}
