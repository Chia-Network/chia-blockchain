from __future__ import annotations

import re
from typing import Any, List, Tuple

import pytest
import pytest_asyncio

from chia.full_node.full_node import FullNode
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.wallet_node import WalletNode


@pytest_asyncio.fixture(scope="function")
async def setup_node_and_rpc(
    two_wallet_nodes_services: Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools],
) -> Tuple[FullNodeRpcClient, FullNodeRpcApi]:
    full_nodes, wallets, bt = two_wallet_nodes_services
    wallet = wallets[0]._node.wallet_state_manager.main_wallet
    full_node_apis = [full_node_service._api for full_node_service in full_nodes]
    full_node_api = full_node_apis[0]
    full_node_service_1 = full_nodes[0]
    assert full_node_service_1.rpc_server is not None
    client = await FullNodeRpcClient.create(
        bt.config["self_hostname"],
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    )
    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    ph = await wallet.get_new_puzzlehash()

    for i in range(4):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    return client, full_node_rpc_api


@pytest_asyncio.fixture(scope="function")
async def one_node_no_blocks(
    one_node: Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools]
) -> Tuple[FullNodeRpcClient, FullNodeRpcApi]:
    full_nodes, wallets, bt = one_node
    full_node_apis = [full_node_service._api for full_node_service in full_nodes]
    full_node_api = full_node_apis[0]
    full_node_service_1 = full_nodes[0]
    assert full_node_service_1.rpc_server is not None
    client = await FullNodeRpcClient.create(
        bt.config["self_hostname"],
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    )
    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    return client, full_node_rpc_api


@pytest.mark.asyncio
async def test_get_blockchain_state(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    # Confirm full node setup correctly
    client, _ = setup_node_and_rpc
    response = await client.get_blockchain_state()
    assert response["genesis_challenge_initialized"] is True


@pytest.mark.asyncio
async def test_empty_request(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc

    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({})


@pytest.mark.asyncio
async def test_empty_peak(one_node_no_blocks: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = one_node_no_blocks
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1})
    del response["node_time_utc"]
    assert response == {
        "estimates": [],
        "target_times": [],
        "current_fee_rate": 0,
        "mempool_size": 0,
        "mempool_max_size": 0,
        "full_node_synced": False,
        "peak_height": 0,
        "last_peak_timestamp": 0,
        "fee_rate_last_block": 0.0,
        "fees_last_block": 0,
        "last_block_cost": 0,
        "last_tx_block_height": 0,
        "mempool_fees": 0,
        "num_spends": 0,
    }


@pytest.mark.asyncio
async def test_no_target_times(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": 1})


@pytest.mark.asyncio
async def test_negative_time(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": 1, "target_times": [-1]})


@pytest.mark.asyncio
async def test_negative_cost(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": -1, "target_times": [1]})


@pytest.mark.asyncio
async def test_no_cost_or_tx(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": []})


@pytest.mark.asyncio
async def test_both_cost_and_tx(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1, "spend_bundle": "80"})


@pytest.mark.asyncio
async def test_target_times_invalid_type(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(TypeError):
        await full_node_rpc_api.get_fee_estimate({"target_times": 1, "cost": 1})


@pytest.mark.asyncio
async def test_cost_invalid_type(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": "a lot"})


@pytest.mark.asyncio
async def test_tx_invalid_type(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(TypeError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "spend_bundle": 1})


#####################


@pytest.mark.asyncio
async def test_empty_target_times(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1})
    assert response["estimates"] == []
    assert response["target_times"] == []


@pytest.mark.asyncio
async def test_cost(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1], "cost": 1})
    assert response["estimates"] == [0]
    assert response["target_times"] == [1]


@pytest.mark.asyncio
async def test_tx(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    wallet_a: WalletTool = bt.get_pool_wallet_tool()
    my_puzzle_hash = wallet_a.get_new_puzzlehash()
    recevier_puzzle_hash = bytes32(b"0" * 32)
    coin_to_spend = Coin(bytes32(b"0" * 32), my_puzzle_hash, uint64(1750000000000))
    spend_bundle = wallet_a.generate_signed_transaction(
        uint64(coin_to_spend.amount), recevier_puzzle_hash, coin_to_spend
    )
    response = await full_node_rpc_api.get_fee_estimate(
        {"target_times": [1], "spend_bundle": spend_bundle.to_json_dict()}
    )
    assert response["estimates"] == [0]
    assert response["target_times"] == [1]


@pytest.mark.asyncio
async def test_multiple(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1, 5, 10, 15, 60, 120, 180, 240], "cost": 1})
    assert response["estimates"] == [0, 0, 0, 0, 0, 0, 0, 0]
    assert response["target_times"] == [1, 5, 10, 15, 60, 120, 180, 240]


def get_test_spendbundle(bt: BlockTools) -> SpendBundle:
    wallet_a: WalletTool = bt.get_pool_wallet_tool()
    my_puzzle_hash = wallet_a.get_new_puzzlehash()
    recevier_puzzle_hash = bytes32(b"0" * 32)
    coin_to_spend = Coin(bytes32(b"0" * 32), my_puzzle_hash, uint64(1750000000000))
    return wallet_a.generate_signed_transaction(uint64(coin_to_spend.amount), recevier_puzzle_hash, coin_to_spend)


@pytest.mark.asyncio
async def test_validate_fee_estimate_cost_err(
    setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools
) -> None:
    spend_bundle = get_test_spendbundle(bt)
    client, full_node_rpc_api = setup_node_and_rpc
    bad_arglist: List[List[Any]] = [
        [["foo", "bar"]],
        [["spend_bundle", spend_bundle.to_json_dict()], ["cost", 1]],
        [["spend_bundle", spend_bundle.to_json_dict()], ["spend_type", "send_xch_transaction"]],
        [["cost", 1], ["spend_type", "send_xch_transaction"]],
        [["spend_bundle", spend_bundle.to_json_dict()], ["cost", 1], ["spend_type", "send_xch_transaction"]],
    ]
    for args in bad_arglist:
        print(args)
        request = {"target_times": [1]}
        for var, val in args:
            print(var)
            request[var] = val
        with pytest.raises(
            ValueError, match=re.escape("Request must contain exactly one of ['spend_bundle', 'cost', 'spend_type']")
        ):
            _ = await full_node_rpc_api.get_fee_estimate(request)


@pytest.mark.asyncio
async def test_validate_fee_estimate_cost_ok(
    setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools
) -> None:
    spend_bundle = get_test_spendbundle(bt)
    client, full_node_rpc_api = setup_node_and_rpc

    good_arglist: List[List[Any]] = [
        ["spend_bundle", spend_bundle.to_json_dict()],
        ["cost", 1],
        ["spend_type", "send_xch_transaction"],
    ]
    for var, val in good_arglist:
        request = {"target_times": [1]}
        request[var] = val
        _ = await full_node_rpc_api.get_fee_estimate(request)


@pytest.mark.asyncio
async def test_get_spendbundle_type_cost_missing(
    setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools
) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(KeyError, match=re.escape("INVALID")):
        request = {"target_times": [1], "spend_type": "INVALID"}
        _ = await full_node_rpc_api.get_fee_estimate(request)


@pytest.mark.asyncio
async def test_get_spendbundle_type_cost_spend_count_ok(
    setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools
) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    spend_counts = [0, 1, 2]
    for spend_count in spend_counts:
        request = {"target_times": [1], "spend_type": "send_xch_transaction", "spend_count": spend_count}
        ret = await full_node_rpc_api.get_fee_estimate(request)
        print(spend_count, ret)


@pytest.mark.asyncio
async def test_get_spendbundle_type_cost_spend_count_bad(
    setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi], bt: BlockTools
) -> None:
    client, full_node_rpc_api = setup_node_and_rpc
    with pytest.raises(ValueError):
        request = {"target_times": [1], "spend_type": "send_xch_transaction", "spend_count": -1}
        _ = await full_node_rpc_api.get_fee_estimate(request)
