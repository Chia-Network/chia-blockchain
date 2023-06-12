from __future__ import annotations

from dataclasses import replace
from typing import List, cast

import pytest
from chia_rs import CoinState

from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.shared_protocol import Error
from chia.protocols.wallet_protocol import GetCoinInfosRequest, GetCoinInfosResponse
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import SimulatorsAndWalletsServices
from chia.types.block import BlockIdentifier
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinInfo
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import int16, uint16, uint32
from chia.util.streamable import Streamable
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_sync_utils import last_change_height_coin_info, sort_coin_infos
from tests.wallet.rpc.test_wallet_rpc import farm_transaction


async def to_coin_infos(
    coin_records: List[CoinRecord], include_spend_info: bool, full_node_api: FullNodeAPI
) -> List[CoinInfo]:
    coin_infos = set()
    for coin_record in coin_records:
        coin_state = CoinState(
            coin=coin_record.coin,
            spent_height=None if coin_record.spent_block_index == 0 else coin_record.spent_block_index,
            created_height=coin_record.confirmed_block_index,
        )
        coin_info = await full_node_api.coin_state_to_coin_info(coin_state, include_spend_info=include_spend_info)
        coin_infos.add(coin_info)
    return sort_coin_infos(coin_infos)


def create_block_identifier(full_node: FullNode, height: int) -> BlockIdentifier:
    block_hash = full_node.blockchain.height_to_hash(uint32(height))
    assert block_hash is not None
    return BlockIdentifier(block_hash, uint32(height))


async def assert_get_coin_infos_response(
    request: GetCoinInfosRequest,
    connection: WSChiaConnection,
    expected_coin_infos: List[CoinInfo],
    include_spend_info: bool,
) -> None:
    assert len(expected_coin_infos) > 0
    response = await connection.call_api(FullNodeAPI.get_coin_infos, request)
    spent = [coin_info.coin for coin_info in expected_coin_infos if coin_info.spent_block is not None]
    unspent = [coin_info.coin for coin_info in expected_coin_infos if coin_info.spent_block is None]
    assert set(response.coin_infos) == set(expected_coin_infos)
    for coin_info in response.coin_infos:
        if coin_info.coin in spent and include_spend_info:
            assert coin_info.spend_info is not None
        if coin_info.coin in unspent:
            assert coin_info.spend_info is None


@pytest.mark.parametrize("include_spend_info", [True, False])
@pytest.mark.asyncio
async def test_get_coin_infos(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    self_hostname: str,
    include_spend_info: bool,
) -> None:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services

    wallet_server = wallet_service._server

    wallet = wallet_service._node.wallet_state_manager.main_wallet
    assert wallet_service.rpc_server is not None
    wallet_rpc_api = cast(WalletRpcApi, wallet_service.rpc_server.rpc_api)
    full_node_server = full_node_service._server
    full_node: FullNode = full_node_service._node
    full_node_api = cast(FullNodeSimulator, full_node_server.api)

    assert await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    connection = wallet_server.all_connections[full_node_server.node_id]

    # Empty coin_ids request
    response: GetCoinInfosResponse = await connection.call_api(FullNodeAPI.get_coin_infos, GetCoinInfosRequest([]))
    assert response.coin_infos == []

    # Generate some coins at different height and spend some of them
    for i in range(3):
        generated = await full_node_api.farm_blocks_to_wallet(3, wallet)
        assert generated > 0
        result = await wallet_rpc_api.send_transaction(
            {
                "wallet_id": 1,
                "amount": int(generated / 2),
                "fee": 0,
                "address": encode_puzzle_hash(bytes32(b"0" * 32), "txch"),
            }
        )
        tx = TransactionRecord.from_json_dict_convenience(result["transaction"])
        assert tx.spend_bundle is not None
        await farm_transaction(full_node_api, wallet_service._node, tx.spend_bundle)

    coin_records = await full_node.coin_store.get_all_coins(True)
    coin_infos = await to_coin_infos(coin_records, include_spend_info, full_node_api)

    # Request all coin_records and validate them
    request = GetCoinInfosRequest(
        coin_ids=[record.name for record in coin_records],
        include_spend_info=include_spend_info,
    )

    await assert_get_coin_infos_response(request, connection, coin_infos, include_spend_info)
    # Test start_block
    start_coin_info = coin_infos[4]
    start_height = last_change_height_coin_info(start_coin_info) + 1
    start_coin_infos = [
        coin_info for coin_info in coin_infos if last_change_height_coin_info(coin_info) >= start_height
    ]
    assert start_coin_info not in start_coin_infos
    start_block = create_block_identifier(full_node, start_height)
    await assert_get_coin_infos_response(
        replace(request, start_block=start_block), connection, start_coin_infos, include_spend_info
    )
    # Test end_block
    end_coin_info = coin_infos[8]
    end_height = last_change_height_coin_info(end_coin_info) - 1
    end_coin_infos = [coin_info for coin_info in coin_infos if last_change_height_coin_info(coin_info) <= end_height]
    assert end_coin_info not in end_coin_infos
    end_block = create_block_identifier(full_node, end_height)
    await assert_get_coin_infos_response(
        replace(request, end_block=end_block), connection, end_coin_infos, include_spend_info
    )
    # Test start_block + end_block
    range_coin_start = coin_infos[4]
    range_coin_end = coin_infos[15]
    range_height_start = last_change_height_coin_info(range_coin_start) + 1
    range_height_end = last_change_height_coin_info(range_coin_end) - 1
    range_block_start = create_block_identifier(full_node, range_height_start)
    range_block_end = create_block_identifier(full_node, range_height_end)
    range_coin_infos = [
        coin_info
        for coin_info in coin_infos
        if range_height_start <= last_change_height_coin_info(coin_info) <= range_height_end
    ]
    assert range_coin_start not in range_coin_infos
    assert range_coin_end not in range_coin_infos
    await assert_get_coin_infos_response(
        replace(request, start_block=range_block_start, end_block=range_block_end),
        connection,
        range_coin_infos,
        include_spend_info,
    )


@pytest.mark.parametrize("unique", [True, False])
@pytest.mark.parametrize(
    "count, include_spend_info",
    [
        # include_spend_info=True
        (FullNodeAPI.max_get_coin_info_ids[True] - 1, True),
        (FullNodeAPI.max_get_coin_info_ids[True], True),
        (FullNodeAPI.max_get_coin_info_ids[True] + 1, True),
        # include_spend_info=False
        (FullNodeAPI.max_get_coin_info_ids[False] - 1, False),
        (FullNodeAPI.max_get_coin_info_ids[False], False),
        (FullNodeAPI.max_get_coin_info_ids[False] + 1, False),
    ],
)
@pytest.mark.asyncio
async def test_get_coin_infos_max_get_coin_info_ids(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    self_hostname: str,
    count: int,
    unique: bool,
    include_spend_info: bool,
) -> None:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services
    wallet_server = wallet_service._server
    full_node_server = full_node_service._server

    assert await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    connection = wallet_server.all_connections[full_node_server.node_id]

    expected_limit = FullNodeAPI.max_get_coin_info_ids[include_spend_info]
    coin_ids = [bytes32(std_hash(i if unique else 0)) for i in range(count)]

    response = await connection.call_api(
        FullNodeAPI.get_coin_infos, GetCoinInfosRequest(coin_ids, include_spend_info=include_spend_info)
    )
    expected_response: Streamable
    if count > expected_limit and unique:
        expected_response = Error(
            int16(Err.INVALID_SIZE.value),
            f"too many coin_ids, maximum unique coin_ids allowed: {expected_limit}",
        )
    else:
        expected_response = GetCoinInfosResponse([])
    assert response == expected_response


@pytest.mark.parametrize(
    "block_identifier, error_code",
    [
        (BlockIdentifier(bytes32(b"0" * 32), uint32(10)), Err.INVALID_HEIGHT),
        (BlockIdentifier(bytes32(b"0" * 32), uint32(0)), Err.INVALID_HASH),
    ],
)
@pytest.mark.asyncio
async def test_get_coin_infos_invalid_blocks(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    block_identifier: BlockIdentifier,
    error_code: Err,
) -> None:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services
    wallet_server = wallet_service._server
    full_node_server = full_node_service._server
    full_node_api = cast(FullNodeSimulator, full_node_server.api)
    full_node: FullNode = full_node_service._node

    assert await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    connection = wallet_server.all_connections[full_node_server.node_id]

    await full_node_api.farm_blocks_to_wallet(1, wallet_service._node.wallet_state_manager.main_wallet)

    for block in ["start_block", "end_block"]:
        request = GetCoinInfosRequest.from_json_dict({"coin_ids": [], block: block_identifier.to_json_dict()})
        response = await connection.call_api(FullNodeAPI.get_coin_infos, request)
        if error_code == Err.INVALID_HEIGHT:
            expected_message = (
                f"{block} not available - height: {block_identifier.height}, "
                f"peak: {full_node.blockchain.get_peak_height()}"
            )
        elif error_code == Err.INVALID_HASH:
            expected_message = (
                f"{block} hash mismatch - expected: {block_identifier.hash} "
                f"got: {full_node.blockchain.height_to_hash(block_identifier.height)}"
            )
        else:
            assert False, "Invalid error code"
        assert response == Error(int16(error_code.value), expected_message)
