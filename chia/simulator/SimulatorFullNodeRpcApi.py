from typing import Dict, List

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import decode_puzzle_hash


class SimulatorFullNodeRpcApi(FullNodeRpcApi):
    def get_routes(self) -> Dict[str, Endpoint]:
        routes = super().get_routes()
        routes["/farm_block"] = self.farm_block
        routes["/set_auto_farming"] = self.set_auto_farming
        routes["/get_auto_farming"] = self.get_auto_farming
        routes["/get_farming_ph"] = self.get_farming_ph
        routes["/get_all_coins"] = self.get_all_coins
        routes["/get_all_puzzle_hashes"] = self.get_all_puzzle_hashes
        return routes

    async def farm_block(self, _request: Dict[str, object]) -> EndpointResult:
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

    async def set_auto_farming(self, _request: Dict[str, object]) -> EndpointResult:
        auto_farm = bool(_request["auto_farm"])
        result = await self.service.server.api.update_autofarm_config(auto_farm)
        return {"auto_farm_enabled": result}

    async def get_auto_farming(self, _request: Dict[str, object]) -> EndpointResult:
        return {"auto_farm_enabled": self.service.server.api.auto_farm}

    async def get_farming_ph(self, _request: Dict[str, object]) -> EndpointResult:
        return {"puzzle_hash": self.service.server.api.bt.farmer_ph.hex()}

    async def get_all_coins(self, _request: Dict[str, object]) -> EndpointResult:
        p_request = GetAllCoinsProtocol((_request.get("include_spent_coins", False)))
        result: List[CoinRecord] = await self.service.server.api.get_all_coins(p_request)
        return {"coin_records": [coin_record.to_json_dict() for coin_record in result]}

    async def get_all_puzzle_hashes(self, _request: Dict[str, object]) -> EndpointResult:
        result = await self.service.server.api.get_all_puzzle_hashes()
        return {"puzzle_hashes": {puzzle_hash.hex(): amount for (puzzle_hash, amount) in result.items()}}
