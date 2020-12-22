from typing import Dict, Optional, List, Tuple
from src.types.full_block import FullBlock
from src.consensus.sub_block_record import SubBlockRecord
from src.types.sized_bytes import bytes32
from src.types.unfinished_header_block import UnfinishedHeaderBlock
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
            response["blockchain_state"]["peak"] = FullBlock.from_json_dict(response["blockchain_state"]["peak"])
        return response["blockchain_state"]

    async def get_sub_block(self, header_hash) -> Optional[FullBlock]:
        try:
            response = await self.fetch("get_sub_block", {"header_hash": header_hash.hex()})
        except Exception:
            return None
        return FullBlock.from_json_dict(response["sub_block"])

    async def get_sub_block_record_by_sub_height(self, sub_height) -> Optional[SubBlockRecord]:
        try:
            response = await self.fetch("get_sub_block_record_by_sub_height", {"sub_height": sub_height})
        except Exception:
            return None
        return SubBlockRecord.from_json_dict(response["sub_block_record"])

    async def get_sub_block_record(self, header_hash) -> Optional[SubBlockRecord]:
        try:
            response = await self.fetch("get_sub_block_record", {"header_hash": header_hash.hex()})
            if response["sub_block_record"] is None:
                return None
        except Exception:
            return None
        return SubBlockRecord.from_json_dict(response["sub_block_record"])

    async def get_unfinished_sub_block_headers(self, sub_height: uint32) -> List[UnfinishedHeaderBlock]:
        response = await self.fetch("get_unfinished_sub_block_headers", {"sub_height": sub_height})
        return [UnfinishedHeaderBlock.from_json_dict(r) for r in response["headers"]]

    async def get_all_block(self, start: uint32, end: uint32) -> List[FullBlock]:
        response = await self.fetch("get_blocks", {"start": start, "end": end})
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

    async def get_unspent_coins(self, puzzle_hash: bytes32) -> List:
        d = {"puzzle_hash": puzzle_hash.hex()}
        return [
            CoinRecord.from_json_dict(coin) for coin in ((await self.fetch("get_unspent_coins", d))["coin_records"])
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
