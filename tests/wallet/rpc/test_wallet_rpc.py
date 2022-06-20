import dataclasses
import json
import logging
from operator import attrgetter
from typing import Any, Dict, List, Optional, Tuple

import pytest
import pytest_asyncio
from blspy import G2Element

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import lock_and_load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from tests.block_tools import BlockTools
from tests.pools.test_pool_rpc import wallet_is_synced
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


@dataclasses.dataclass
class WalletBundle:
    node: WalletNode
    rpc_client: WalletRpcClient
    wallet: Wallet


@dataclasses.dataclass
class FullNodeBundle:
    server: ChiaServer
    api: FullNodeSimulator
    rpc_client: FullNodeRpcClient


@dataclasses.dataclass
class WalletRpcTestEnvironment:
    wallet_1: WalletBundle
    wallet_2: WalletBundle
    full_node: FullNodeBundle


async def farm_transaction_block(full_node_api: FullNodeSimulator, wallet_node: WalletNode):
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(b"\00" * 32)))
    await time_out_assert(10, wallet_is_synced, True, wallet_node, full_node_api)


async def farm_transaction(full_node_api: FullNodeSimulator, wallet_node: WalletNode, spend_bundle: SpendBundle):
    await time_out_assert(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle, spend_bundle.name())
    await farm_transaction_block(full_node_api, wallet_node)
    assert full_node_api.full_node.mempool_manager.get_spendbundle(spend_bundle.name()) is None


async def generate_funds(full_node_api: FullNodeSimulator, wallet_bundle: WalletBundle, num_blocks: int = 1):
    wallet_id = 1
    initial_balances = await wallet_bundle.rpc_client.get_wallet_balance(str(wallet_id))
    ph: bytes32 = decode_puzzle_hash(await wallet_bundle.rpc_client.get_next_address(str(wallet_id), True))
    generated_funds = 0
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        peak_height = full_node_api.full_node.blockchain.get_peak_height()
        assert peak_height is not None
        generated_funds += calculate_pool_reward(peak_height) + calculate_base_farmer_reward(peak_height)

    # Farm a dummy block to confirm the created funds
    await farm_transaction_block(full_node_api, wallet_bundle.node)

    expected_confirmed = initial_balances["confirmed_wallet_balance"] + generated_funds
    expected_unconfirmed = initial_balances["unconfirmed_wallet_balance"] + generated_funds
    await time_out_assert(10, get_confirmed_balance, expected_confirmed, wallet_bundle.rpc_client, wallet_id)
    await time_out_assert(10, get_unconfirmed_balance, expected_unconfirmed, wallet_bundle.rpc_client, wallet_id)
    await time_out_assert(10, wallet_bundle.rpc_client.get_synced)

    return generated_funds


@pytest_asyncio.fixture(scope="function", params=[True, False])
async def wallet_rpc_environment(two_wallet_nodes, request, bt: BlockTools, self_hostname):
    full_node, wallets = two_wallet_nodes
    full_node_api = full_node[0]
    full_node_server = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    wallet_node_2, server_3 = wallets[1]
    wallet = wallet_node.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

    wallet_rpc_api = WalletRpcApi(wallet_node)
    wallet_rpc_api_2 = WalletRpcApi(wallet_node_2)

    config = bt.config
    hostname = config["self_hostname"]
    daemon_port = config["daemon_port"]

    if request.param:
        wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    def stop_node_cb():
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_cleanup_node, test_rpc_port_node = await start_rpc_server(
        full_node_rpc_api,
        hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    rpc_cleanup, test_rpc_port = await start_rpc_server(
        wallet_rpc_api,
        hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    rpc_cleanup_2, test_rpc_port_2 = await start_rpc_server(
        wallet_rpc_api_2,
        hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_3.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    client = await WalletRpcClient.create(hostname, test_rpc_port, bt.root_path, config)
    client_2 = await WalletRpcClient.create(hostname, test_rpc_port_2, bt.root_path, config)
    client_node = await FullNodeRpcClient.create(hostname, test_rpc_port_node, bt.root_path, config)

    wallet_bundle_1: WalletBundle = WalletBundle(wallet_node, client, wallet)
    wallet_bundle_2: WalletBundle = WalletBundle(wallet_node_2, client_2, wallet_2)
    node_bundle: FullNodeBundle = FullNodeBundle(full_node_server, full_node_api, client_node)

    yield WalletRpcTestEnvironment(wallet_bundle_1, wallet_bundle_2, node_bundle)

    # Checks that the RPC manages to stop the node
    client.close()
    client_2.close()
    client_node.close()
    await client.await_closed()
    await client_2.await_closed()
    await client_node.await_closed()
    await rpc_cleanup()
    await rpc_cleanup_2()
    await rpc_cleanup_node()


async def create_tx_outputs(wallet: Wallet, output_args: List[Tuple[int, Optional[List[str]]]]) -> List[Dict[str, Any]]:
    outputs = []
    for args in output_args:
        output = {"amount": uint64(args[0]), "puzzle_hash": await wallet.get_new_puzzlehash()}
        if args[1] is not None:
            assert len(args[1]) > 0
            output["memos"] = args[1]
        outputs.append(output)
    return outputs


async def assert_wallet_types(client: WalletRpcClient, expected: Dict[WalletType, int]) -> None:
    for wallet_type in WalletType:
        wallets = await client.get_wallets(wallet_type)
        wallet_count = len(wallets)
        if wallet_type in expected:
            assert wallet_count == expected.get(wallet_type, 0)
            for wallet in wallets:
                assert wallet["type"] == wallet_type.value


def assert_tx_amounts(
    tx: TransactionRecord, outputs: List[Dict[str, Any]], *, amount_fee: uint64, change_expected: bool
) -> None:
    assert tx.fee_amount == amount_fee
    assert tx.amount == sum(output["amount"] for output in outputs)
    expected_additions = len(outputs) if change_expected is None else len(outputs) + 1
    assert len(tx.additions) == expected_additions
    addition_amounts = [addition.amount for addition in tx.additions]
    removal_amounts = [removal.amount for removal in tx.removals]
    for output in outputs:
        assert output["amount"] in addition_amounts
    assert (sum(removal_amounts) - sum(addition_amounts)) == amount_fee


async def assert_push_tx_error(node_rpc: FullNodeRpcClient, tx: TransactionRecord):
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None
    # check error for a ASSERT_ANNOUNCE_CONSUMED_FAILED and if the error is not there throw a value error
    try:
        await node_rpc.push_tx(spend_bundle)
    except ValueError as error:
        error_string = error.args[0]["error"]  # noqa:  # pylint: disable=E1126
        if error_string.find("ASSERT_ANNOUNCE_CONSUMED_FAILED") == -1:
            raise ValueError from error


async def tx_in_mempool(client: WalletRpcClient, transaction_id: bytes32):
    tx = await client.get_transaction("1", transaction_id)
    return tx.is_in_mempool()


async def get_confirmed_balance(client: WalletRpcClient, wallet_id: int):
    return (await client.get_wallet_balance(str(wallet_id)))["confirmed_wallet_balance"]


async def get_unconfirmed_balance(client: WalletRpcClient, wallet_id: int):
    return (await client.get_wallet_balance(str(wallet_id)))["unconfirmed_wallet_balance"]


@pytest.mark.asyncio
async def test_send_transaction(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    tx_amount = uint64(15600000)
    with pytest.raises(ValueError):
        await client.send_transaction("1", uint64(100000000000000001), addr)

    # Tests sending a basic transaction
    tx = await client.send_transaction("1", tx_amount, addr, memos=["this is a basic tx"])
    transaction_id = tx.name

    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await time_out_assert(5, tx_in_mempool, True, client, transaction_id)
    await time_out_assert(5, get_unconfirmed_balance, generated_funds - tx_amount, client, 1)

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Checks that the memo can be retrieved
    tx_confirmed = await client.get_transaction("1", transaction_id)
    assert tx_confirmed.confirmed
    assert len(tx_confirmed.get_memos()) == 1
    assert [b"this is a basic tx"] in tx_confirmed.get_memos().values()
    assert list(tx_confirmed.get_memos().keys())[0] in [a.name() for a in spend_bundle.additions()]

    await time_out_assert(5, get_confirmed_balance, generated_funds - tx_amount, client, 1)


@pytest.mark.parametrize(
    "output_args, fee, select_coin",
    [
        ([(348026, None)], 0, False),
        ([(1270495230, ["memo_1"]), (902347, ["memo_2"])], 1, True),
        ([(84920, ["memo_1_0", "memo_1_1"]), (1, ["memo_2_0"])], 0, False),
        ([(32058710, ["memo_1_0", "memo_1_1"]), (1, ["memo_2_0"]), (923, ["memo_3_0", "memo_3_1"])], 32804, True),
    ],
)
@pytest.mark.asyncio
async def test_create_signed_transaction(
    wallet_rpc_environment: WalletRpcTestEnvironment,
    output_args: List[Tuple[int, Optional[List[str]]]],
    fee: int,
    select_coin: bool,
):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    full_node_rpc: FullNodeRpcClient = env.full_node.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    outputs = await create_tx_outputs(wallet_2, output_args)
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(fee)
    amount_total = amount_outputs + amount_fee

    selected_coin = None
    if select_coin:
        selected_coin = await wallet_1_rpc.select_coins(amount=amount_total, wallet_id=1)
        assert len(selected_coin) == 1

    tx = await wallet_1_rpc.create_signed_transaction(
        outputs,
        coins=selected_coin,
        fee=amount_fee,
    )
    assert_tx_amounts(tx, outputs, amount_fee=amount_fee, change_expected=not select_coin)

    # Farm the transaction and make sure the wallet balance reflects it correct
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None
    push_res = await full_node_rpc.push_tx(spend_bundle)
    assert push_res["success"]
    await farm_transaction(full_node_api, wallet_1_node, spend_bundle)
    await time_out_assert(5, get_confirmed_balance, generated_funds - amount_total, wallet_1_rpc, 1)

    # Validate the memos
    for output in outputs:
        if "memos" in outputs:
            found: bool = False
            for addition in spend_bundle.additions():
                if addition.amount == output["amount"] and addition.puzzle_hash.hex() == output["puzzle_hash"]:
                    cr: Optional[CoinRecord] = await full_node_rpc.get_coin_record_by_name(addition.name())
                    assert cr is not None
                    spend: Optional[CoinSpend] = await full_node_rpc.get_puzzle_and_solution(
                        addition.parent_coin_info, cr.confirmed_block_index
                    )
                    assert spend is not None
                    sb: SpendBundle = SpendBundle([spend], G2Element())
                    assert compute_memos(sb) == {addition.name(): [memo.encode() for memo in output["memos"]]}
                    found = True
            assert found


@pytest.mark.asyncio
async def test_create_signed_transaction_with_coin_announcement(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_node: FullNodeRpcClient = env.full_node.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    signed_tx_amount = uint64(888000)
    tx_coin_announcements = [
        Announcement(
            std_hash(b"coin_id_1"),
            std_hash(b"message"),
            b"\xca",
        ),
        Announcement(
            std_hash(b"coin_id_2"),
            bytes(Program.to("a string")),
        ),
    ]
    outputs = await create_tx_outputs(wallet_2, [(signed_tx_amount, None)])
    tx_res: TransactionRecord = await client.create_signed_transaction(
        outputs, coin_announcements=tx_coin_announcements
    )
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=False)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.asyncio
async def test_create_signed_transaction_with_puzzle_announcement(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_node: FullNodeRpcClient = env.full_node.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    signed_tx_amount = uint64(888000)
    tx_puzzle_announcements = [
        Announcement(
            std_hash(b"puzzle_hash_1"),
            b"message",
            b"\xca",
        ),
        Announcement(
            std_hash(b"puzzle_hash_2"),
            bytes(Program.to("a string")),
        ),
    ]
    outputs = await create_tx_outputs(wallet_2, [(signed_tx_amount, None)])
    tx_res = await client.create_signed_transaction(outputs, puzzle_announcements=tx_puzzle_announcements)
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=True)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.asyncio
async def test_send_transaction_multi(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    outputs = await create_tx_outputs(wallet_2, [(uint64(1), ["memo_1"]), (uint64(2), ["memo_2"])])
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(amount_outputs + 1)

    send_tx_res: TransactionRecord = await client.send_transaction_multi(
        "1",
        outputs,
        fee=amount_fee,
    )
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    assert send_tx_res is not None

    assert_tx_amounts(send_tx_res, outputs, amount_fee=amount_fee, change_expected=True)

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    await time_out_assert(5, get_confirmed_balance, generated_funds - amount_outputs - amount_fee, client, 1)

    # Checks that the memo can be retrieved
    tx_confirmed = await client.get_transaction("1", send_tx_res.name)
    assert tx_confirmed.confirmed
    memos = tx_confirmed.get_memos()
    assert len(memos) == len(outputs)
    for output in outputs:
        assert [output["memos"][0].encode()] in memos.values()
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    for key in memos.keys():
        assert key in [a.name() for a in spend_bundle.additions()]


@pytest.mark.asyncio
async def test_get_transactions(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1, 5)

    all_transactions = await client.get_transactions("1")
    assert len(all_transactions) >= 10
    # Test transaction pagination
    some_transactions = await client.get_transactions("1", 0, 5)
    some_transactions_2 = await client.get_transactions("1", 5, 10)
    assert some_transactions == all_transactions[0:5]
    assert some_transactions_2 == all_transactions[5:10]

    # Testing sorts
    # Test the default sort (CONFIRMED_AT_HEIGHT)
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"))
    all_transactions = await client.get_transactions("1", reverse=True)
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"), reverse=True)

    # Test RELEVANCE
    await client.send_transaction(
        "1", uint64(1), encode_puzzle_hash(await wallet.get_new_puzzlehash(), "txch")
    )  # Create a pending tx

    all_transactions = await client.get_transactions("1", sort_key=SortKey.RELEVANCE)
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"))
    assert all_transactions == sorted_transactions

    all_transactions = await client.get_transactions("1", sort_key=SortKey.RELEVANCE, reverse=True)
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"), reverse=True)
    assert all_transactions == sorted_transactions

    # Test get_transactions to address
    ph_by_addr = await wallet.get_new_puzzlehash()
    await client.send_transaction("1", uint64(1), encode_puzzle_hash(ph_by_addr, "txch"))
    await client.farm_block(encode_puzzle_hash(ph_by_addr, "txch"))
    await time_out_assert(10, wallet_is_synced, True, wallet_node, full_node_api)
    tx_for_address = await client.get_transactions("1", to_address=encode_puzzle_hash(ph_by_addr, "txch"))
    assert len(tx_for_address) == 1
    assert tx_for_address[0].to_puzzle_hash == ph_by_addr


@pytest.mark.asyncio
async def test_get_transaction_count(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    all_transactions = await client.get_transactions("1")
    assert len(all_transactions) > 0
    transaction_count = await client.get_transaction_count("1")
    assert transaction_count == len(all_transactions)


@pytest.mark.asyncio
async def test_cat_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_node: WalletNode = env.wallet_1.node

    client: WalletRpcClient = env.wallet_1.rpc_client
    client_2: WalletRpcClient = env.wallet_2.rpc_client

    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(full_node_api, env.wallet_1, 1)
    await generate_funds(full_node_api, env.wallet_2, 1)

    # Creates a CAT wallet with 100 mojos and a CAT with 20 mojos
    await client.create_new_cat_and_wallet(uint64(100))
    res = await client.create_new_cat_and_wallet(uint64(20))
    assert res["success"]
    cat_0_id = res["wallet_id"]
    asset_id = bytes32.fromhex(res["asset_id"])
    assert len(asset_id) > 0

    await assert_wallet_types(client, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 2})
    await assert_wallet_types(client_2, {WalletType.STANDARD_WALLET: 1})

    bal_0 = await client.get_wallet_balance(cat_0_id)
    assert bal_0["confirmed_wallet_balance"] == 0
    assert bal_0["pending_coin_removal_count"] == 1
    col = await client.get_cat_asset_id(cat_0_id)
    assert col == asset_id
    assert (await client.get_cat_name(cat_0_id)) == CATWallet.default_wallet_name_for_unknown_cat(asset_id.hex())
    await client.set_cat_name(cat_0_id, "My cat")
    assert (await client.get_cat_name(cat_0_id)) == "My cat"
    result = await client.cat_asset_id_to_name(col)
    assert result is not None
    wid, name = result
    assert wid == cat_0_id
    assert name == "My cat"
    result = await client.cat_asset_id_to_name(bytes32([0] * 32))
    assert result is None
    verified_asset_id = next(iter(DEFAULT_CATS.items()))[1]["asset_id"]
    result = await client.cat_asset_id_to_name(bytes32.from_hexstr(verified_asset_id))
    assert result is not None
    should_be_none, name = result
    assert should_be_none is None
    assert name == next(iter(DEFAULT_CATS.items()))[1]["name"]

    # TODO: Investigate why farming only one block here makes it flaky
    await farm_transaction_block(full_node_api, wallet_node)
    await farm_transaction_block(full_node_api, wallet_node)

    await time_out_assert(10, get_confirmed_balance, 20, client, cat_0_id)
    bal_0 = await client.get_wallet_balance(cat_0_id)
    assert bal_0["pending_coin_removal_count"] == 0
    assert bal_0["unspent_coin_count"] == 1

    # Creates a second wallet with the same CAT
    res = await client_2.create_wallet_for_existing_cat(asset_id)
    assert res["success"]
    cat_1_id = res["wallet_id"]
    cat_1_asset_id = bytes.fromhex(res["asset_id"])
    assert cat_1_asset_id == asset_id

    await assert_wallet_types(client, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 2})
    await assert_wallet_types(client_2, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 1})

    await farm_transaction_block(full_node_api, wallet_node)

    bal_1 = await client_2.get_wallet_balance(cat_1_id)
    assert bal_1["confirmed_wallet_balance"] == 0

    addr_0 = await client.get_next_address(cat_0_id, False)
    addr_1 = await client_2.get_next_address(cat_1_id, False)

    assert addr_0 != addr_1

    tx_res = await client.cat_spend(cat_0_id, uint64(4), addr_1, uint64(0), ["the cat memo"])
    spend_bundle = tx_res.spend_bundle
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Test unacknowledged CAT
    assert wallet_node.wallet_state_manager is not None
    await wallet_node.wallet_state_manager.interested_store.add_unacknowledged_token(
        asset_id, "Unknown", uint32(10000), bytes32(b"\00" * 32)
    )
    cats = await client.get_stray_cats()
    assert len(cats) == 1

    await time_out_assert(10, get_confirmed_balance, 16, client, cat_0_id)
    await time_out_assert(10, get_confirmed_balance, 4, client_2, cat_1_id)

    # Test CAT coin selection
    selected_coins = await client.select_coins(amount=1, wallet_id=cat_0_id)
    assert len(selected_coins) > 0


@pytest.mark.asyncio
async def test_offer_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(full_node_api, env.wallet_1, 1)
    await generate_funds(full_node_api, env.wallet_2, 1)

    # Creates a CAT wallet with 20 mojos
    res = await wallet_1_rpc.create_new_cat_and_wallet(uint64(20))
    cat_wallet_id = res["wallet_id"]
    cat_asset_id = bytes32.fromhex(res["asset_id"])
    # TODO: Investigate why farming only two blocks here makes it flaky
    await farm_transaction_block(full_node_api, wallet_node)
    await farm_transaction_block(full_node_api, wallet_node)
    await farm_transaction_block(full_node_api, wallet_node)
    await time_out_assert(10, get_confirmed_balance, 20, wallet_1_rpc, cat_wallet_id)

    # Creates a wallet for the same CAT on wallet_2 and send 4 CAT from wallet_1 to it
    await wallet_2_rpc.create_wallet_for_existing_cat(cat_asset_id)
    wallet_2_address = await wallet_2_rpc.get_next_address(cat_wallet_id, False)
    tx_res = await wallet_1_rpc.cat_spend(cat_wallet_id, uint64(4), wallet_2_address, uint64(0), ["the cat memo"])
    spend_bundle = tx_res.spend_bundle
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)
    await time_out_assert(10, get_confirmed_balance, 4, wallet_2_rpc, cat_wallet_id)

    # Create an offer of 5 chia for one CAT
    offer, trade_record = await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1}, validate_only=True
    )
    all_offers = await wallet_1_rpc.get_all_offers()
    assert len(all_offers) == 0
    assert offer is None

    driver_dict: Dict[str, Any] = {cat_asset_id.hex(): {"type": "CAT", "tail": "0x" + cat_asset_id.hex()}}

    offer, trade_record = await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1},
        driver_dict=driver_dict,
        fee=uint64(1),
    )
    assert offer is not None

    summary = await wallet_1_rpc.get_offer_summary(offer)
    assert summary == {"offered": {"xch": 5}, "requested": {cat_asset_id.hex(): 1}, "infos": driver_dict, "fees": 1}

    assert await wallet_1_rpc.check_offer_validity(offer)

    all_offers = await wallet_1_rpc.get_all_offers(file_contents=True)
    assert len(all_offers) == 1
    assert TradeStatus(all_offers[0].status) == TradeStatus.PENDING_ACCEPT
    assert all_offers[0].offer == bytes(offer)

    trade_record = await wallet_2_rpc.take_offer(offer, fee=uint64(1))
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CONFIRM

    await wallet_1_rpc.cancel_offer(offer.name(), secure=False)

    trade_record = await wallet_1_rpc.get_offer(offer.name(), file_contents=True)
    assert trade_record.offer == bytes(offer)
    assert TradeStatus(trade_record.status) == TradeStatus.CANCELLED

    await wallet_1_rpc.cancel_offer(offer.name(), fee=uint64(1), secure=True)

    trade_record = await wallet_1_rpc.get_offer(offer.name())
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CANCEL

    new_offer, new_trade_record = await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_wallet_id: 1}, fee=uint64(1)
    )
    all_offers = await wallet_1_rpc.get_all_offers()
    assert len(all_offers) == 2

    await farm_transaction_block(full_node_api, wallet_node)

    async def is_trade_confirmed(client, trade) -> bool:
        trade_record = await client.get_offer(trade.name())
        return TradeStatus(trade_record.status) == TradeStatus.CONFIRMED

    await time_out_assert(15, is_trade_confirmed, True, wallet_1_rpc, offer)

    # Test trade sorting
    def only_ids(trades):
        return [t.trade_id for t in trades]

    trade_record = await wallet_1_rpc.get_offer(offer.name())
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True)  # confirmed at index descending
    assert len(all_offers) == 2
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, reverse=True)  # confirmed at index ascending
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, sort_key="RELEVANCE")  # most relevant
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(
        include_completed=True, sort_key="RELEVANCE", reverse=True
    )  # least relevant
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    # Test pagination
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=0, end=1)
    assert len(all_offers) == 1
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=50)
    assert len(all_offers) == 0
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=0, end=50)
    assert len(all_offers) == 2


@pytest.mark.asyncio
async def test_did_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    from chia.wallet.did_wallet.did_info import DID_HRP

    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_1: Wallet = env.wallet_1.wallet
    wallet_2: Wallet = env.wallet_2.wallet
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_2_node: WalletNode = env.wallet_2.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_1_id = wallet_1.id()

    await generate_funds(env.full_node.api, env.wallet_1, 5)

    # Create a DID wallet
    res = await wallet_1_rpc.create_new_did_wallet(amount=1, name=None)
    assert res["success"]
    did_wallet_id_0 = res["wallet_id"]
    did_id_0 = res["my_did"]

    # Get wallet name
    res = await wallet_1_rpc.did_get_wallet_name(did_wallet_id_0)
    assert res["success"]
    assert res["name"] == "Profile 1"

    # Set wallet name
    new_wallet_name = "test name"
    res = await wallet_1_rpc.did_set_wallet_name(did_wallet_id_0, new_wallet_name)
    assert res["success"]
    res = await wallet_1_rpc.did_get_wallet_name(did_wallet_id_0)
    assert res["success"]
    assert res["name"] == new_wallet_name
    with pytest.raises(ValueError, match="Wallet id 1 is not a DID wallet"):
        await wallet_1_rpc.did_set_wallet_name(wallet_1_id, new_wallet_name)

    # Check DID ID
    res = await wallet_1_rpc.get_did_id(did_wallet_id_0)
    assert res["success"]
    assert did_id_0 == res["my_did"]
    # Create backup file
    res = await wallet_1_rpc.create_did_backup_file(did_wallet_id_0, "backup.did")
    assert res["success"]

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    # Update recovery list
    res = await wallet_1_rpc.update_did_recovery_list(did_wallet_id_0, [did_id_0], 1)
    assert res["success"]
    res = await wallet_1_rpc.get_did_recovery_list(did_wallet_id_0)
    assert res["num_required"] == 1
    assert res["recovery_list"][0] == did_id_0

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    # Update metadata
    with pytest.raises(ValueError, match="Wallet with id 1 is not a DID one"):
        await wallet_1_rpc.update_did_metadata(wallet_1_id, {"Twitter": "Https://test"})
    res = await wallet_1_rpc.update_did_metadata(did_wallet_id_0, {"Twitter": "Https://test"})
    assert res["success"]

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    res = await wallet_1_rpc.get_did_metadata(did_wallet_id_0)
    assert res["metadata"]["Twitter"] == "Https://test"

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    # Transfer DID
    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    res = await wallet_1_rpc.did_transfer_did(did_wallet_id_0, addr, 0, True)
    assert res["success"]

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    assert wallet_2_node.wallet_state_manager is not None

    did_wallets = list(
        filter(
            lambda w: (w.type == WalletType.DISTRIBUTED_ID),
            await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    did_wallet_2: DIDWallet = wallet_2_node.wallet_state_manager.wallets[did_wallets[0].id]
    assert encode_puzzle_hash(bytes32.from_hexstr(did_wallet_2.get_my_DID()), DID_HRP) == did_id_0
    metadata = json.loads(did_wallet_2.did_info.metadata)
    assert metadata["Twitter"] == "Https://test"


@pytest.mark.asyncio
async def test_nft_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):

    from chia.wallet.nft_wallet.nft_info import NFT_HRP

    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2: Wallet = env.wallet_2.wallet
    wallet_2_node: WalletNode = env.wallet_2.node
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(env.full_node.api, env.wallet_1, 5)

    res = await wallet_1_rpc.create_new_nft_wallet(None)
    nft_wallet_id = res["wallet_id"]
    res = await wallet_1_rpc.mint_nft(
        nft_wallet_id,
        None,
        None,
        "0xD4584AD463139FA8C0D9F68F4B59F185",
        ["https://www.chia.net/img/branding/chia-logo.svg"],
    )
    assert res["success"]

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    assert wallet_1_node.wallet_state_manager is not None

    nft_wallet: NFTWallet = wallet_1_node.wallet_state_manager.wallets[nft_wallet_id]
    # Test with the hex version of nft_id
    nft_id = nft_wallet.get_current_nfts()[0].coin.name().hex()
    nft_info = (await wallet_1_rpc.get_nft_info(nft_id))["nft_info"]
    assert nft_info["nft_coin_id"][2:] == nft_wallet.get_current_nfts()[0].coin.name().hex()
    # Test with the bech32m version of nft_id
    hmr_nft_id = encode_puzzle_hash(nft_wallet.get_current_nfts()[0].coin.name(), NFT_HRP)
    nft_info = (await wallet_1_rpc.get_nft_info(hmr_nft_id))["nft_info"]
    assert nft_info["nft_coin_id"][2:] == nft_wallet.get_current_nfts()[0].coin.name().hex()

    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    res = await wallet_1_rpc.transfer_nft(nft_wallet_id, nft_id, addr, 0)
    assert res["success"]

    for _ in range(3):
        await farm_transaction_block(full_node_api, wallet_1_node)

    assert wallet_2_node.wallet_state_manager is not None

    nft_wallet_id_1 = (
        await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.NFT)
    )[0].id
    nft_wallet_1: NFTWallet = wallet_2_node.wallet_state_manager.wallets[nft_wallet_id_1]
    nft_info_1 = (await wallet_1_rpc.get_nft_info(nft_id, False))["nft_info"]
    assert nft_info_1 == nft_info
    nft_info_1 = (await wallet_1_rpc.get_nft_info(nft_id))["nft_info"]
    assert nft_info_1["nft_coin_id"][2:] == nft_wallet_1.get_current_nfts()[0].coin.name().hex()
    # Cross-check NFT
    nft_info_2 = (await wallet_2_rpc.list_nfts(nft_wallet_id_1))["nft_list"][0]
    assert nft_info_1 == nft_info_2


@pytest.mark.asyncio
async def test_key_and_address_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client

    address = await client.get_next_address("1", True)
    assert len(address) > 10

    pks = await client.get_public_keys()
    assert len(pks) == 1

    await generate_funds(env.full_node.api, env.wallet_1)

    assert (await client.get_height_info()) > 0

    ph = await wallet.get_new_puzzlehash()
    addr = encode_puzzle_hash(ph, "txch")
    tx_amount = uint64(15600000)

    created_tx = await client.send_transaction("1", tx_amount, addr)

    await time_out_assert(5, tx_in_mempool, True, client, created_tx.name)
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 1
    await client.delete_unconfirmed_transactions("1")
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 0

    sk_dict = await client.get_private_key(pks[0])
    assert sk_dict["fingerprint"] == pks[0]
    assert sk_dict["sk"] is not None
    assert sk_dict["pk"] is not None
    assert sk_dict["seed"] is not None

    mnemonic = await client.generate_mnemonic()
    assert len(mnemonic) == 24

    await client.add_key(mnemonic)

    pks = await client.get_public_keys()
    assert len(pks) == 2

    await client.log_in(pks[1])
    sk_dict = await client.get_private_key(pks[1])
    assert sk_dict["fingerprint"] == pks[1]

    # Add in reward addresses into farmer and pool for testing delete key checks
    # set farmer to first private key
    sk = await wallet_node.get_key_for_fingerprint(pks[0])
    test_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1())
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = encode_puzzle_hash(test_ph, "txch")
        # set pool to second private key
        sk = await wallet_node.get_key_for_fingerprint(pks[1])
        test_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1())
        test_config["pool"]["xch_target_address"] = encode_puzzle_hash(test_ph, "txch")
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check first key
    sk_dict = await client.check_delete_key(pks[0])
    assert sk_dict["fingerprint"] == pks[0]
    assert sk_dict["used_for_farmer_rewards"] is True
    assert sk_dict["used_for_pool_rewards"] is False

    # Check second key
    sk_dict = await client.check_delete_key(pks[1])
    assert sk_dict["fingerprint"] == pks[1]
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is True

    # Check unknown key
    sk_dict = await client.check_delete_key(123456, 10)
    assert sk_dict["fingerprint"] == 123456
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is False

    # Add in observer reward addresses into farmer and pool for testing delete key checks
    # set farmer to first private key
    sk = await wallet_node.get_key_for_fingerprint(pks[0])
    test_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk_unhardened(sk, uint32(0)).get_g1())
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = encode_puzzle_hash(test_ph, "txch")
        # set pool to second private key
        sk = await wallet_node.get_key_for_fingerprint(pks[1])
        test_ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk_unhardened(sk, uint32(0)).get_g1())
        test_config["pool"]["xch_target_address"] = encode_puzzle_hash(test_ph, "txch")
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check first key
    sk_dict = await client.check_delete_key(pks[0])
    assert sk_dict["fingerprint"] == pks[0]
    assert sk_dict["used_for_farmer_rewards"] is True
    assert sk_dict["used_for_pool_rewards"] is False

    # Check second key
    sk_dict = await client.check_delete_key(pks[1])
    assert sk_dict["fingerprint"] == pks[1]
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is True

    # Check unknown key
    sk_dict = await client.check_delete_key(123456, 10)
    assert sk_dict["fingerprint"] == 123456
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is False

    await client.delete_key(pks[0])
    await client.log_in(pks[1])
    assert len(await client.get_public_keys()) == 1

    assert not (await client.get_sync_status())

    wallets = await client.get_wallets()
    assert len(wallets) == 1
    assert await get_unconfirmed_balance(client, int(wallets[0]["id"])) == 0

    with pytest.raises(ValueError):
        await client.send_transaction(wallets[0]["id"], uint64(100), addr)

    # Delete all keys
    await client.delete_all_keys()
    assert len(await client.get_public_keys()) == 0
