from typing import Tuple

import pytest

from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


@pytest.fixture
async def setup_node_and_rpc(two_wallet_nodes_services) -> Tuple[FullNodeRpcClient, FullNodeRpcApi]:
    full_nodes, wallets, bt = two_wallet_nodes_services
    wallet = wallets[0]._node.wallet_state_manager.main_wallet
    full_node_apis = [full_node_service._api for full_node_service in full_nodes]
    full_node_api = full_node_apis[0]
    full_node_service_1 = full_nodes[0]
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


@pytest.mark.asyncio
async def test_get_blockchain_state(setup_node_and_rpc) -> None:
    # Confirm full node setup correctly
    client, _ = await setup_node_and_rpc
    response = await client.get_blockchain_state()
    assert response["genesis_challenge_initialized"] is True


@pytest.mark.asyncio
async def test_empty_request(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc

    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({})


@pytest.mark.asyncio
async def test_no_target_times(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": 1})


@pytest.mark.asyncio
async def test_negative_time(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": 1, "target_times": [-1]})


@pytest.mark.asyncio
async def test_negative_cost(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"cost": -1, "target_times": [1]})


# TODO:
# Time out of range
# Cost out of range


@pytest.mark.asyncio
async def test_no_cost_or_tx(setup_node_and_rpc: Tuple[FullNodeRpcClient, FullNodeRpcApi]) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": []})


@pytest.mark.asyncio
async def test_both_cost_and_tx(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1, "spend_bundle": "80"})


@pytest.mark.asyncio
async def test_target_times_invalid_type(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(TypeError):
        await full_node_rpc_api.get_fee_estimate({"target_times": 1, "cost": 1})


@pytest.mark.asyncio
async def test_cost_invalid_type(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(ValueError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": "a lot"})


@pytest.mark.asyncio
async def test_tx_invalid_type(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    with pytest.raises(TypeError):
        await full_node_rpc_api.get_fee_estimate({"target_times": [], "spend_bundle": 1})


#####################


@pytest.mark.asyncio
async def test_empty_target_times(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1})
    assert response["estimates"] == []
    assert response["target_times"] == []


@pytest.mark.asyncio
async def test_cost(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1], "cost": 1})
    assert response["estimates"] == [0]
    assert response["target_times"] == [1]


@pytest.mark.asyncio
async def test_tx(setup_node_and_rpc, bt) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
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
async def test_multiple(setup_node_and_rpc) -> None:
    client, full_node_rpc_api = await setup_node_and_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1, 5, 10, 15, 60, 120, 180, 240], "cost": 1})
    assert response["estimates"] == [0, 0, 0, 0, 0, 0, 0, 0]
    assert response["target_times"] == [1, 5, 10, 15, 60, 120, 180, 240]


# TODO: Tests for
# Each algo
# load config
# return min / max fee rate
# return current fee rate
# return predicted fee rates

# TODO: client & command line
# assert response["success"] is True
