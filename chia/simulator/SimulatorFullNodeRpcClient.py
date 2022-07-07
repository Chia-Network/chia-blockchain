from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash


class SimulatorFullNodeRpcClient(FullNodeRpcClient):
    async def farm_block(self, target_ph: bytes32, number_of_blocks: int = 1, guarantee_tx_block: bool = False) -> None:
        address = encode_puzzle_hash(target_ph, "txch")
        await self.fetch(
            "farm_block", {"address": address, "blocks": number_of_blocks, "guarantee_tx_block": guarantee_tx_block}
        )

    async def set_auto_farming(self, set_auto_farming: bool) -> bool:
        result = await self.fetch("set_auto_farming", {"set_auto_farming": set_auto_farming})
        result = result["auto_farm_enabled"]
        assert result == set_auto_farming
        return bool(result)

    async def get_auto_farming(self) -> bool:
        result = await self.fetch("get_auto_farming", {})
        return bool(result["auto_farm_enabled"])
