from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash


class SimulatorFullNodeRpcClient(FullNodeRpcClient):
    async def farm_block(self, target_ph: bytes32, number_of_blocks: int = 1) -> None:
        address = encode_puzzle_hash(target_ph, "txch")
        await self.fetch("farm_block", {"address": address, "blocks": number_of_blocks})

    async def farm_transaction_block(self, target_ph: bytes32, number_of_blocks: int = 1) -> None:
        address = encode_puzzle_hash(target_ph, "txch")
        await self.fetch("farm_block", {"address": address, "blocks": number_of_blocks, "guarantee_tx_block": True})

    async def enable_auto_farming(self, enable_auto_farming: bool) -> bool:
        result = (await self.fetch("auto_farm", {"auto_farm": enable_auto_farming}))["auto_farm_enabled"]
        assert result == enable_auto_farming
        return bool(result)

    async def get_auto_farming_status(self) -> bool:
        return bool((await self.fetch("auto_farm", {"auto_farm": None}))["auto_farm_enabled"])
