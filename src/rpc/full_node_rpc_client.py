from typing import Dict, Optional, List, Tuple
from src.types.full_block import FullBlock
from src.consensus.block_record import BlockRecord
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint32, uint64
from src.types.coin_record import CoinRecord
from src.rpc.rpc_client import RpcClient


class FullNodeRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local full node. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    async def get_blockchain_state(self) -> Dict:
        response = await self.fetch("get_blockchain_state", {})
        if response["blockchain_state"]["peak"] is not None:
            response["blockchain_state"]["peak"] = BlockRecord.from_json_dict(response["blockchain_state"]["peak"])
        return response["blockchain_state"]

    async def get_block(self, header_hash) -> Optional[FullBlock]:
        try:
            response = await self.fetch("get_block", {"header_hash": header_hash.hex()})
        except Exception:
            return None
        return FullBlock.from_json_dict(response["block"])

    async def get_block_record_by_height(self, height) -> Optional[BlockRecord]:
        try:
            response = await self.fetch("get_block_record_by_height", {"height": height})
        except Exception:
            return None
        return BlockRecord.from_json_dict(response["block_record"])

    async def get_block_record(self, header_hash) -> Optional[BlockRecord]:
        try:
            response = await self.fetch("get_block_record", {"header_hash": header_hash.hex()})
            if response["block_record"] is None:
                return None
        except Exception:
            return None
        return BlockRecord.from_json_dict(response["block_record"])

    async def get_unfinished_block_headers(self) -> List[UnfinishedHeaderBlock]:
        response = await self.fetch("get_unfinished_block_headers", {})
        return [UnfinishedHeaderBlock.from_json_dict(r) for r in response["headers"]]

    async def get_all_block(self, start: uint32, end: uint32) -> List[FullBlock]:
        response = await self.fetch("get_blocks", {"start": start, "end": end, "exclude_header_hash": True})
        return [FullBlock.from_json_dict(r) for r in response["blocks"]]

    async def get_network_space(
        self, newer_block_header_hash: bytes32, older_block_header_hash: bytes32
    ) -> Optional[uint64]:
        try:
            network_space_bytes_estimate = await self.fetch(
                "get_network_space",
                {
                    "newer_block_header_hash": newer_block_header_hash.hex(),
                    "older_block_header_hash": older_block_header_hash.hex(),
                },
            )
        except Exception:
            return None
        return network_space_bytes_estimate["space"]

    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List:
        d = {"puzzle_hash": puzzle_hash.hex(), "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height
        return [
            CoinRecord.from_json_dict(coin)
            for coin in ((await self.fetch("get_coin_records_by_puzzle_hash", d))["coin_records"])
        ]

    async def get_additions_and_removals(self, header_hash: bytes32) -> Tuple[List[CoinRecord], List[CoinRecord]]:
        try:
            response = await self.fetch("get_additions_and_removals", {"header_hash": header_hash.hex()})
        except Exception:
            return [], []
        removals = []
        additions = []
        for coin_record in response["removals"]:
            removals.append(CoinRecord.from_json_dict(coin_record))
        for coin_record in response["additions"]:
            additions.append(CoinRecord.from_json_dict(coin_record))
        return additions, removals

    async def get_block_records(self, start: int, end: int) -> List:
        try:
            response = await self.fetch("get_block_records", {"start": start, "end": end})
            if response["block_records"] is None:
                return []
        except Exception:
            return []
        # TODO: return block records
        return response["block_records"]

    async def push_tx(self, spend_bundle: SpendBundle):
        return await self.fetch("push_tx", {"spend_bundle": spend_bundle.to_json_dict()})

    async def get_all_mempool_tx_ids(self) -> List[bytes32]:
        response = await self.fetch("get_all_mempool_tx_ids", {})
        return [bytes32(hexstr_to_bytes(tx_id_hex)) for tx_id_hex in response["tx_ids"]]

    async def get_all_mempool_items(self) -> Dict[bytes32, Dict]:
        response: Dict = await self.fetch("get_all_mempool_items", {})
        converted: Dict[bytes32, Dict] = {}
        for tx_id_hex, item in response["mempool_items"].items():
            converted[bytes32(hexstr_to_bytes(tx_id_hex))] = item
        return converted

    async def get_mempool_item_by_tx_id(self, tx_id: bytes32) -> Optional[Dict]:
        try:
            response = await self.fetch("get_mempool_item_by_tx_id", {"tx_id": tx_id.hex()})
            return response["mempool_item"]
        except Exception:
            return None
