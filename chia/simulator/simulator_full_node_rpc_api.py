from __future__ import annotations

from secrets import token_bytes
from typing import Dict, List

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol, ReorgProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.util.bech32m import decode_puzzle_hash
from chia.util.ints import uint32


class SimulatorFullNodeRpcApi(FullNodeRpcApi):
    @property
    def simulator_api(self) -> FullNodeSimulator:
        assert isinstance(self.service.server.api, FullNodeSimulator)
        return self.service.server.api

    def get_routes(self) -> Dict[str, Endpoint]:
        routes = super().get_routes()
        routes["/get_all_blocks"] = self.get_all_blocks
        routes["/farm_block"] = self.farm_block
        routes["/set_auto_farming"] = self.set_auto_farming
        routes["/get_auto_farming"] = self.get_auto_farming
        routes["/get_farming_ph"] = self.get_farming_ph
        routes["/get_all_coins"] = self.get_all_coins
        routes["/get_all_puzzle_hashes"] = self.get_all_puzzle_hashes
        routes["/revert_blocks"] = self.revert_blocks
        routes["/reorg_blocks"] = self.reorg_blocks
        return routes

    async def get_all_blocks(self, _request: Dict[str, object]) -> EndpointResult:
        all_blocks: List[FullBlock] = await self.simulator_api.get_all_full_blocks()
        return {"blocks": [block.to_json_dict() for block in all_blocks]}

    async def farm_block(self, _request: Dict[str, object]) -> EndpointResult:
        request_address = str(_request["address"])
        guarantee_tx_block = bool(_request.get("guarantee_tx_block", False))
        blocks = int(str(_request.get("blocks", 1)))  # mypy made me do this
        ph = decode_puzzle_hash(request_address)
        req = FarmNewBlockProtocol(ph)
        cur_height = self.service.blockchain.get_peak_height()
        if guarantee_tx_block:
            for i in range(blocks):  # these can only be tx blocks
                await self.simulator_api.farm_new_transaction_block(req)
        else:
            for i in range(blocks):  # these can either be full blocks or tx blocks
                await self.simulator_api.farm_new_block(req)
        return {"new_peak_height": (cur_height if cur_height is not None else 0) + blocks}

    async def set_auto_farming(self, _request: Dict[str, object]) -> EndpointResult:
        auto_farm = bool(_request["auto_farm"])
        result = await self.simulator_api.update_autofarm_config(auto_farm)
        return {"auto_farm_enabled": result}

    async def get_auto_farming(self, _request: Dict[str, object]) -> EndpointResult:
        return {"auto_farm_enabled": self.simulator_api.auto_farm}

    async def get_farming_ph(self, _request: Dict[str, object]) -> EndpointResult:
        return {"puzzle_hash": self.simulator_api.bt.farmer_ph.hex()}

    async def get_all_coins(self, _request: Dict[str, object]) -> EndpointResult:
        p_request = GetAllCoinsProtocol(bool((_request.get("include_spent_coins", False))))
        result: List[CoinRecord] = await self.simulator_api.get_all_coins(p_request)
        return {"coin_records": [coin_record.to_json_dict() for coin_record in result]}

    async def get_all_puzzle_hashes(self, _request: Dict[str, object]) -> EndpointResult:
        result = await self.simulator_api.get_all_puzzle_hashes()
        return {
            "puzzle_hashes": {puzzle_hash.hex(): (amount, num_tx) for (puzzle_hash, (amount, num_tx)) in result.items()}
        }

    async def revert_blocks(self, _request: Dict[str, object]) -> EndpointResult:
        blocks = int(str(_request.get("num_of_blocks", 1)))  # number of blocks to revert
        all_blocks = bool(_request.get("delete_all_blocks", False))  # revert all blocks
        height = self.service.blockchain.get_peak_height()
        if height is None:
            raise ValueError("No blocks to revert")
        new_height = (height - blocks) if not all_blocks else 1
        assert new_height >= 1
        await self.simulator_api.revert_block_height(uint32(new_height))
        return {"new_peak_height": new_height}

    async def reorg_blocks(self, _request: Dict[str, object]) -> EndpointResult:
        fork_blocks = int(str(_request.get("num_of_blocks_to_rev", 1)))  # number of blocks to go back
        new_blocks = int(str(_request.get("num_of_new_blocks", 1)))  # how many extra blocks should we add
        all_blocks = bool(_request.get("revert_all_blocks", False))  # fork all blocks
        use_random_seed = bool(_request.get("random_seed", True))  # randomize the seed to differentiate reorgs
        random_seed = bytes32(token_bytes(32)) if use_random_seed else None
        cur_height = self.service.blockchain.get_peak_height()
        if cur_height is None:
            raise ValueError("No blocks to revert")
        fork_height = (cur_height - fork_blocks) if not all_blocks else 1
        new_height = cur_height + new_blocks  # any number works as long as its not 0
        assert fork_height >= 1 and new_height - 1 >= cur_height
        request = ReorgProtocol(uint32(fork_height), uint32(new_height), self.simulator_api.bt.farmer_ph, random_seed)
        await self.simulator_api.reorg_from_index_to_new_index(request)
        return {"new_peak_height": new_height}
