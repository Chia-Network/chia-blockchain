from typing import Dict

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.util.bech32m import decode_puzzle_hash


class SimulatorFullNodeRpcApi(FullNodeRpcApi):
    def get_routes(self) -> Dict[str, Endpoint]:
        routes = super().get_routes()
        routes["/farm_block"] = self.farm_tx_block
        routes["/auto_farm"] = self.auto_farm
        return routes

    async def farm_tx_block(self, _request: Dict[str, object]) -> EndpointResult:
        request_address = str(_request["address"])
        guarantee_tx_block = bool(_request.get("guarantee_tx_block", False))
        blocks = int(str(_request.get("blocks", 1)))  # mypy made me do this
        ph = decode_puzzle_hash(request_address)
        req = FarmNewBlockProtocol(ph)
        if guarantee_tx_block:
            for i in range(blocks):  # these can only be tx blocks
                await self.service.server.api.farm_new_transaction_block(req)
        else:
            for i in range(blocks):  # these can either be full blocks or tx blocks
                await self.service.server.api.farm_new_block(req)
        return {}

    async def auto_farm(self, _request: Dict[str, object]) -> EndpointResult:
        enable_auto_farm = _request["auto_farm"]
        if enable_auto_farm is None:
            return {"auto_farm_enabled": self.service.server.api.auto_farm}
        enable_auto_farm = bool(enable_auto_farm)
        result = await self.service.server.api.update_autofarm_config(enable_auto_farm)
        return {"auto_farm_enabled": result}
