from typing import Dict

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import Endpoint
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.util.bech32m import decode_puzzle_hash


class SimulatorFullNodeRpcApi(FullNodeRpcApi):
    def get_routes(self) -> Dict[str, Endpoint]:
        routes = super().get_routes()
        routes["/farm_block"] = self.farm_block
        routes["/auto_farm"] = self.auto_farm
        return routes

    async def farm_block(self, _request: Dict[str, object]) -> Dict[str, object]:
        request_address = str(_request["address"])
        block_type = str(_request.get("block_type", "tx_block"))  # tx_block or full_block
        blocks = int(str(_request.get("blocks", 1)))  # mypy made me do this
        ph = decode_puzzle_hash(request_address)
        req = FarmNewBlockProtocol(ph)
        if block_type == "tx_block":
            for i in range(blocks):
                await self.service.server.api.farm_new_transaction_block(req)  # these can only be tx blocks
        elif block_type == "full_block":
            for i in range(blocks):
                await self.service.server.api.farm_new_block(req)  # these can either be full blocks or tx blocks
        else:
            raise ValueError(f"Unknown block type: {block_type}")
        return {}

    async def auto_farm(self, _request: Dict[str, object]) -> Dict[str, object]:
        enable_auto_farm = _request["auto_farm"]
        if enable_auto_farm is None:
            return {"auto_farm_enabled": await self.service.server.api.update_autofarm_config()}
        enable_auto_farm = bool(enable_auto_farm)
        result = await self.service.server.api.update_autofarm_config(enable_auto_farm)
        return {"auto_farm_enabled": result}
