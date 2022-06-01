import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32


@pytest.mark.asyncio
async def test_get_blockchain_state(setup_node_rpc):
    # Confirm full node setup correctly
    client, _ = setup_node_rpc
    response = await client.get_blockchain_state()
    assert response["genesis_challenge_initialized"] is True


@pytest.mark.asyncio
async def test_empty_request(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({})


@pytest.mark.asyncio
async def test_no_target_times(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"cost": 1})


@pytest.mark.asyncio
async def test_negative_time(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"cost": 1, "target_times": [-1]})


@pytest.mark.asyncio
async def test_negative_cost(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"cost": -1, "target_times": [1]})

# TODO:
# Time out of range
# Cost out of range


@pytest.mark.asyncio
async def test_no_cost_or_tx(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"target_times": []})


@pytest.mark.asyncio
async def test_both_cost_and_tx(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1, "spend_bundle": "80"})


@pytest.mark.asyncio
async def test_target_times_invalid_type(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(TypeError):
        response = await full_node_rpc_api.get_fee_estimate({"target_times": 1, "cost": 1})


@pytest.mark.asyncio
async def test_cost_invalid_type(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(ValueError):
        response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": "a lot"})


@pytest.mark.asyncio
async def test_tx_invalid_type(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    with pytest.raises(TypeError):
        response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "spend_bundle": 1})
#####################


@pytest.mark.asyncio
async def test_empty_target_times(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [], "cost": 1})
    assert response == {'estimates': [], 'target_times': []}


@pytest.mark.asyncio
async def test_cost(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1], "cost": 1})
    assert response == {'estimates': [0], 'target_times': [1]}


@pytest.mark.asyncio
async def test_tx(setup_node_rpc, wallet_a):
    client, full_node_rpc_api = setup_node_rpc
    my_puzzle_hash = wallet_a.get_new_puzzlehash()
    recevier_puzzle_hash = bytes32(b"0" * 32)
    coin_to_spend = Coin(bytes32(b"0" * 32), my_puzzle_hash, 1750000000000)
    spend_bundle = wallet_a.generate_signed_transaction(coin_to_spend.amount, recevier_puzzle_hash, coin_to_spend)
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1], "spend_bundle": spend_bundle.to_json_dict()})
    assert response == {'estimates': [0], 'target_times': [1]}


@pytest.mark.asyncio
async def test_multiple(setup_node_rpc):
    client, full_node_rpc_api = setup_node_rpc
    response = await full_node_rpc_api.get_fee_estimate({"target_times": [1, 5, 10, 15, 60, 120, 180, 240], "cost": 1})
    assert response == {'estimates': [0, 0, 0, 0, 0, 0, 0, 0], 'target_times': [1, 5, 10, 15, 60, 120, 180, 240]}


# TODO:
# Specify algo
# load config
# return min / max fee rate
# return current fee rate
# return predicted fee rates

# TODO: client & command line
#assert response["success"] is True
