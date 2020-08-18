import aiohttp
from typing import Dict, Optional, List
from src.types.full_block import FullBlock
from src.types.header import Header
from src.types.sized_bytes import bytes32
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
        response["blockchain_state"]["tips"] = [
            Header.from_json_dict(tip) for tip in response["blockchain_state"]["tips"]
        ]
        response["blockchain_state"]["lca"] = Header.from_json_dict(
            response["blockchain_state"]["lca"]
        )
        return response["blockchain_state"]

    async def get_block(self, header_hash) -> Optional[FullBlock]:
        try:
            response = await self.fetch("get_block", {"header_hash": header_hash.hex()})
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return FullBlock.from_json_dict(response["block"])

    async def get_header_by_height(self, header_height) -> Optional[Header]:
        try:
            response = await self.fetch(
                "get_header_by_height", {"height": header_height}
            )
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return Header.from_json_dict(response["header"])

    async def get_header(self, header_hash) -> Optional[Header]:
        try:
            response = await self.fetch(
                "get_header", {"header_hash": header_hash.hex()}
            )
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return Header.from_json_dict(response["header"])

    async def get_unfinished_block_headers(self, height: uint32) -> List[Header]:
        response = await self.fetch("get_unfinished_block_headers", {"height": height})
        return [Header.from_json_dict(r) for r in response["headers"]]

    async def get_network_space(
        self, newer_block_header_hash: str, older_block_header_hash: str
    ) -> Optional[uint64]:
        try:
            network_space_bytes_estimate = await self.fetch(
                "get_network_space",
                {
                    "newer_block_header_hash": newer_block_header_hash,
                    "older_block_header_hash": older_block_header_hash,
                },
            )
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return network_space_bytes_estimate["space"]

    async def get_unspent_coins(
        self, puzzle_hash: bytes32, header_hash: Optional[bytes32] = None
    ) -> List:
        if header_hash is not None:
            d = {"puzzle_hash": puzzle_hash.hex(), "header_hash": header_hash.hex()}
        else:
            d = {"puzzle_hash": puzzle_hash.hex()}
        return [
            CoinRecord.from_json_dict(coin)
            for coin in ((await self.fetch("get_unspent_coins", d))["coin_records"])
        ]

    async def get_heaviest_block_seen(self) -> Header:
        response = await self.fetch("get_heaviest_block_seen", {})
        return Header.from_json_dict(response["tip"])
