from __future__ import annotations

from typing import Any, Optional, cast

from chia_rs import BlockRecord, CoinSpend, EndOfSubSlotBundle, FullBlock, SpendBundle
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.signage_point import SignagePoint
from chia.rpc.rpc_client import RpcClient
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpendWithConditions
from chia.types.unfinished_header_block import UnfinishedHeaderBlock


def coin_record_dict_backwards_compat(coin_record: dict[str, Any]) -> dict[str, Any]:
    del coin_record["spent"]
    return coin_record


class FullNodeRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local full node. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP that provides easy access
    to the full node.
    """

    async def get_blockchain_state(self) -> dict[str, Any]:
        response = await self.fetch("get_blockchain_state", {})
        if response["blockchain_state"]["peak"] is not None:
            response["blockchain_state"]["peak"] = BlockRecord.from_json_dict(response["blockchain_state"]["peak"])
        return cast(dict[str, Any], response["blockchain_state"])

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        try:
            response = await self.fetch("get_block", {"header_hash": header_hash.hex()})
        except Exception:
            return None
        return FullBlock.from_json_dict(response["block"])

    async def get_blocks(self, start: int, end: int, exclude_reorged: bool = False) -> list[FullBlock]:
        response = await self.fetch(
            "get_blocks", {"start": start, "end": end, "exclude_header_hash": True, "exclude_reorged": exclude_reorged}
        )
        return [FullBlock.from_json_dict(block) for block in response["blocks"]]

    async def get_block_record_by_height(self, height: int) -> Optional[BlockRecord]:
        try:
            response = await self.fetch("get_block_record_by_height", {"height": height})
        except Exception:
            return None
        return BlockRecord.from_json_dict(response["block_record"])

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        try:
            response = await self.fetch("get_block_record", {"header_hash": header_hash.hex()})
            if response["block_record"] is None:
                return None
        except Exception:
            return None
        return BlockRecord.from_json_dict(response["block_record"])

    async def get_unfinished_block_headers(self) -> list[UnfinishedHeaderBlock]:
        response = await self.fetch("get_unfinished_block_headers", {})
        return [UnfinishedHeaderBlock.from_json_dict(r) for r in response["headers"]]

    async def get_all_block(self, start: uint32, end: uint32) -> list[FullBlock]:
        response = await self.fetch("get_blocks", {"start": start, "end": end, "exclude_header_hash": True})
        return [FullBlock.from_json_dict(r) for r in response["blocks"]]

    async def get_network_space(self, newer_block_header_hash: bytes32, older_block_header_hash: bytes32) -> int:
        network_space_bytes_estimate = await self.fetch(
            "get_network_space",
            {
                "newer_block_header_hash": newer_block_header_hash.hex(),
                "older_block_header_hash": older_block_header_hash.hex(),
            },
        )

        return cast(int, network_space_bytes_estimate["space"])

    async def get_coin_record_by_name(self, coin_id: bytes32) -> Optional[CoinRecord]:
        try:
            response = await self.fetch("get_coin_record_by_name", {"name": coin_id.hex()})
        except Exception:
            return None

        return CoinRecord.from_json_dict(coin_record_dict_backwards_compat(response["coin_record"]))

    async def get_coin_records_by_names(
        self,
        names: list[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        names_hex = [name.hex() for name in names]
        d = {"names": names_hex, "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_names", d)
        return [CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin)) for coin in response["coin_records"]]

    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        d = {"puzzle_hash": puzzle_hash.hex(), "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_puzzle_hash", d)
        return [CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin)) for coin in response["coin_records"]]

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        puzzle_hashes_hex = [ph.hex() for ph in puzzle_hashes]
        d = {"puzzle_hashes": puzzle_hashes_hex, "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_puzzle_hashes", d)
        return [CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin)) for coin in response["coin_records"]]

    async def get_coin_records_by_parent_ids(
        self,
        parent_ids: list[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        parent_ids_hex = [pid.hex() for pid in parent_ids]
        d = {"parent_ids": parent_ids_hex, "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_parent_ids", d)
        return [CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin)) for coin in response["coin_records"]]

    async def get_aggsig_additional_data(self) -> bytes32:
        result = await self.fetch("get_aggsig_additional_data", {})
        return bytes32.from_hexstr(result["additional_data"])

    async def get_coin_records_by_hint(
        self,
        hint: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        d = {"hint": hint.hex(), "include_spent_coins": include_spent_coins}
        if start_height is not None:
            d["start_height"] = start_height
        if end_height is not None:
            d["end_height"] = end_height

        response = await self.fetch("get_coin_records_by_hint", d)
        return [CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin)) for coin in response["coin_records"]]

    async def get_additions_and_removals(self, header_hash: bytes32) -> tuple[list[CoinRecord], list[CoinRecord]]:
        try:
            response = await self.fetch("get_additions_and_removals", {"header_hash": header_hash.hex()})
        except Exception:
            return [], []
        removals = []
        additions = []
        for coin_record in response["removals"]:
            removals.append(CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin_record)))
        for coin_record in response["additions"]:
            additions.append(CoinRecord.from_json_dict(coin_record_dict_backwards_compat(coin_record)))
        return additions, removals

    async def get_block_records(self, start: int, end: int) -> list[dict[str, Any]]:
        try:
            response = await self.fetch("get_block_records", {"start": start, "end": end})
            if response["block_records"] is None:
                return []
        except Exception:
            return []
        # TODO: return block records
        return cast(list[dict[str, Any]], response["block_records"])

    async def get_block_spends(self, header_hash: bytes32) -> Optional[list[CoinSpend]]:
        try:
            response = await self.fetch("get_block_spends", {"header_hash": header_hash.hex()})
            block_spends = []
            for block_spend in response["block_spends"]:
                block_spends.append(CoinSpend.from_json_dict(block_spend))
            return block_spends
        except Exception:
            return None

    async def get_block_spends_with_conditions(self, header_hash: bytes32) -> Optional[list[CoinSpendWithConditions]]:
        try:
            response = await self.fetch("get_block_spends_with_conditions", {"header_hash": header_hash.hex()})
            block_spends: list[CoinSpendWithConditions] = []
            for block_spend in response["block_spends_with_conditions"]:
                block_spends.append(CoinSpendWithConditions.from_json_dict(block_spend))
            return block_spends

        except Exception:
            return None

    async def push_tx(self, spend_bundle: SpendBundle) -> dict[str, Any]:
        return await self.fetch("push_tx", {"spend_bundle": spend_bundle.to_json_dict()})

    async def get_puzzle_and_solution(self, coin_id: bytes32, height: uint32) -> Optional[CoinSpend]:
        try:
            response = await self.fetch("get_puzzle_and_solution", {"coin_id": coin_id.hex(), "height": height})
            return CoinSpend.from_json_dict(response["coin_solution"])
        except Exception:
            return None

    async def get_all_mempool_tx_ids(self) -> list[bytes32]:
        response = await self.fetch("get_all_mempool_tx_ids", {})
        return [bytes32.from_hexstr(tx_id_hex) for tx_id_hex in response["tx_ids"]]

    async def get_all_mempool_items(self) -> dict[bytes32, dict[str, Any]]:
        response = await self.fetch("get_all_mempool_items", {})
        converted: dict[bytes32, dict[str, Any]] = {}
        for tx_id_hex, item in response["mempool_items"].items():
            converted[bytes32.from_hexstr(tx_id_hex)] = item
        return converted

    async def get_mempool_item_by_tx_id(
        self,
        tx_id: bytes32,
        include_pending: bool = False,
    ) -> Optional[dict[str, Any]]:
        try:
            response = await self.fetch(
                "get_mempool_item_by_tx_id", {"tx_id": tx_id.hex(), "include_pending": include_pending}
            )
            return cast(dict[str, Any], response["mempool_item"])
        except Exception:
            return None

    async def get_mempool_items_by_coin_name(self, coin_name: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_mempool_items_by_coin_name", {"coin_name": coin_name.hex()})
        return response

    async def create_block_generator(self) -> Optional[dict[str, Any]]:
        response = await self.fetch("create_block_generator", {})
        return response

    async def get_recent_signage_point_or_eos(
        self, sp_hash: Optional[bytes32], challenge_hash: Optional[bytes32]
    ) -> Optional[Any]:
        try:
            if sp_hash is not None:
                assert challenge_hash is None
                response = await self.fetch("get_recent_signage_point_or_eos", {"sp_hash": sp_hash.hex()})
                return {
                    "signage_point": SignagePoint.from_json_dict(response["signage_point"]),
                    "time_received": response["time_received"],
                    "reverted": response["reverted"],
                }
            else:
                assert challenge_hash is not None
                response = await self.fetch("get_recent_signage_point_or_eos", {"challenge_hash": challenge_hash.hex()})
                return {
                    "eos": EndOfSubSlotBundle.from_json_dict(response["eos"]),
                    "time_received": response["time_received"],
                    "reverted": response["reverted"],
                }
        except Exception:
            return None

    async def get_fee_estimate(
        self,
        target_times: Optional[list[int]],
        cost: Optional[int],
    ) -> dict[str, Any]:
        response = await self.fetch("get_fee_estimate", {"cost": cost, "target_times": target_times})
        return response
