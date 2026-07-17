from __future__ import annotations

from collections.abc import Awaitable, Callable

from chia.rpc.rpc_client import RpcClient
from chia.util.streamable import Streamable
from chia.wallet.conditions import Condition, ConditionValidTimes
from chia.wallet.util.clvm_streamable import json_deserialize_with_clvm_streamable
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.wallet_request_types import Empty
from chia.wallet.wallet_rpc_metadata import WALLET_RPC_ENDPOINT_METADATA, WalletRpcMetadata

# Client method names that differ from the RPC endpoint path (historical CLI/test API).
# TODO: change these to match
CLIENT_METHOD_NAME_OVERRIDES: dict[str, str] = {
    "create_signed_transaction": "create_signed_transactions",
    "did_get_did": "get_did_id",
    "did_get_info": "get_did_info",
    "did_create_backup_file": "create_did_backup_file",
    "did_update_metadata": "update_did_metadata",
    "did_get_pubkey": "get_did_pubkey",
    "did_get_metadata": "get_did_metadata",
    "did_find_lost_did": "find_lost_did",
    "cat_get_asset_id": "get_cat_asset_id",
    "cat_get_name": "get_cat_name",
    "cat_set_name": "set_cat_name",
    "nft_mint_nft": "mint_nft",
    "nft_add_uri": "add_uri_to_nft",
    "nft_get_info": "get_nft_info",
    "nft_transfer_nft": "transfer_nft",
    "nft_count_nfts": "count_nfts",
    "nft_get_nfts": "list_nfts",
    "nft_get_by_did": "get_nft_wallet_by_did",
    "nft_set_nft_did": "set_nft_did",
    "nft_set_nft_status": "set_nft_status",
    "nft_get_wallet_did": "get_nft_wallet_did",
    "nft_get_wallets_with_dids": "get_nft_wallets_with_dids",
    "nft_set_did_bulk": "set_nft_did_bulk",
    "nft_transfer_bulk": "transfer_nft_bulk",
}


EndpointMethod = (
    Callable[
        ["WalletRpcClient", Streamable, TXConfig, tuple[Condition, ...], ConditionValidTimes],
        Awaitable[Streamable | None],
    ]
    | Callable[["WalletRpcClient", Streamable], Awaitable[Streamable | None]]
    | Callable[["WalletRpcClient"], Awaitable[Streamable | None]]
)


def client_method_name(endpoint_name: str) -> str:
    return CLIENT_METHOD_NAME_OVERRIDES.get(endpoint_name, endpoint_name)


def _make_endpoint_method(meta: WalletRpcMetadata) -> EndpointMethod:
    endpoint_name = meta.endpoint_name
    request_type = meta.request_type
    response_type = meta.response_type
    empty_request = request_type is Empty
    empty_response = response_type is Empty

    if meta.tx_endpoint:

        async def tx_method(
            self: WalletRpcClient,
            request: Streamable,
            tx_config: TXConfig,
            extra_conditions: tuple[Condition, ...] = tuple(),
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> Streamable | None:
            payload = request.json_serialize_for_transport(  # type: ignore[attr-defined]
                tx_config, extra_conditions, timelock_info
            )
            result = await self.fetch(meta.endpoint_name, payload)
            if empty_response:
                return None
            return json_deserialize_with_clvm_streamable(result, response_type)

        tx_method.__name__ = client_method_name(endpoint_name)
        tx_method.__qualname__ = f"WalletRpcClient.{tx_method.__name__}"
        return tx_method

    if empty_request:

        async def no_arg_method(
            self: WalletRpcClient,
        ) -> Streamable | None:
            result = await self.fetch(meta.endpoint_name, {})
            if empty_response:
                return None
            return meta.response_type.from_json_dict(result)

        no_arg_method.__name__ = client_method_name(endpoint_name)
        no_arg_method.__qualname__ = f"WalletRpcClient.{no_arg_method.__name__}"
        return no_arg_method

    async def request_method(
        self: WalletRpcClient,
        request: Streamable,
    ) -> Streamable | None:
        result = await self.fetch(meta.endpoint_name, request.to_json_dict())
        if empty_response:
            return None
        return meta.response_type.from_json_dict(result)

    request_method.__name__ = client_method_name(endpoint_name)
    request_method.__qualname__ = f"WalletRpcClient.{request_method.__name__}"
    return request_method


class WalletRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.

    Methods are generated at import time from WALLET_RPC_ENDPOINT_METADATA. See
    wallet_rpc_client.pyi for the typed surface used by editors / type checkers.
    """


for _meta in WALLET_RPC_ENDPOINT_METADATA:
    setattr(WalletRpcClient, client_method_name(_meta.endpoint_name), _make_endpoint_method(_meta))


__all__ = [
    "CLIENT_METHOD_NAME_OVERRIDES",
    "WalletRpcClient",
    "client_method_name",
]
