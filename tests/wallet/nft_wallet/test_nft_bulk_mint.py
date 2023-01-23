from __future__ import annotations

import asyncio
from secrets import token_bytes
from typing import Any, Dict

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.util.address_type import AddressType


async def nft_count(wallet: NFTWallet) -> int:
    nfts = await wallet.nft_store.get_nft_list()
    return len(nfts)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_did(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph_maker = await wallet_0.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    # for _ in range(1, num_blocks):
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)

    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    await time_out_assert(5, did_wallet.get_confirmed_balance, 1)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1", did_id=did_id
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )

    royalty_pc = uint16(300)
    royalty_addr = ph_maker

    mint_total = 10
    fee = uint64(100)
    metadata_list = [
        {
            "program": Program.to(
                [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", token_bytes(32).hex())]
            ),
            "royalty_pc": royalty_pc,
            "royalty_ph": royalty_addr,
        }
        for x in range(mint_total)
    ]

    target_list = [(await wallet_1.get_new_puzzlehash()) for x in range(mint_total)]

    sb = await nft_wallet_maker.mint_from_did(
        metadata_list, target_list=target_list, mint_number_start=1, mint_total=mint_total, fee=fee
    )

    await api_0.push_tx({"spend_bundle": bytes(sb).hex()})

    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, nft_count, mint_total, nft_wallet_taker)
    await time_out_assert(30, nft_count, 0, nft_wallet_maker)

    expected_xch_bal = funds - fee - mint_total - 1
    await time_out_assert(30, wallet_0.get_confirmed_balance, expected_xch_bal)

    nfts = await nft_wallet_taker.get_current_nfts()
    matched_data = dict(zip(target_list, metadata_list))

    # Check targets and metadata entries match in the final nfts
    for nft in nfts:
        mod, args = nft.full_puzzle.uncurry()
        unft = UncurriedNFT.uncurry(mod, args)
        assert isinstance(unft, UncurriedNFT)
        inner_args = unft.inner_puzzle.uncurry()[1]
        inner_ph = inner_args.at("rrrf").get_tree_hash()
        meta = unft.metadata.at("rfr").as_atom()
        # check that the target puzzle hashes of transferred nfts matches the metadata entry
        assert matched_data[inner_ph]["program"].at("rfr").as_atom() == meta
        # Check the did is set for each nft
        assert nft.minter_did == did_id


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_did_rpc(two_wallet_nodes: Any, trusted: Any, self_hostname: str) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    bt = full_node_api.bt
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds)

    api_maker = WalletRpcApi(wallet_node_maker)
    api_taker = WalletRpcApi(wallet_node_taker)
    config = bt.config
    daemon_port = config["daemon_port"]

    def stop_node_cb() -> None:
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_server_node = await start_rpc_server(
        full_node_rpc_api,
        self_hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    rpc_server = await start_rpc_server(
        api_maker,
        self_hostname,
        daemon_port,
        uint16(0),
        lambda x: None,  # type: ignore
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    client = await WalletRpcClient.create(self_hostname, rpc_server.listen_port, bt.root_path, config)
    client_node = await FullNodeRpcClient.create(self_hostname, rpc_server_node.listen_port, bt.root_path, config)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(config))

    nft_wallet_maker = await api_maker.create_new_wallet(
        dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id)
    )
    assert isinstance(nft_wallet_maker, dict)
    assert nft_wallet_maker.get("success")

    nft_wallet_taker = await api_taker.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 2"))

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    try:
        n = 10
        metadata_list = [
            {
                "hash": bytes32(token_bytes(32)).hex(),
                "uris": ["https://data.com/{}".format(i)],
                "meta_hash": bytes32(token_bytes(32)).hex(),
                "meta_uris": ["https://meatadata.com/{}".format(i)],
                "license_hash": bytes32(token_bytes(32)).hex(),
                "license_uris": ["https://license.com/{}".format(i)],
                "edition_number": i + 1,
                "edition_total": n,
            }
            for i in range(n)
        ]
        target_list = [encode_puzzle_hash((ph_taker), "xch") for x in range(n)]
        royalty_address = encode_puzzle_hash(bytes32(token_bytes(32)), "xch")
        royalty_percentage = 300
        fee = 100
        required_amount = n + (fee * n)
        xch_coins = await client.select_coins(amount=required_amount, wallet_id=wallet_maker.id())
        funding_coin = xch_coins[0]
        assert funding_coin.amount >= required_amount
        funding_coin_dict = xch_coins[0].to_json_dict()
        chunk = 5
        next_coin = funding_coin
        did_coin = (await client.select_coins(amount=1, wallet_id=2))[0]
        did_lineage_parent = None
        spends = []
        nft_ids = set([])
        for i in range(0, n, chunk):
            resp: Dict[str, Any] = await client.nft_mint_bulk(
                wallet_id=nft_wallet_maker["wallet_id"],
                metadata_list=metadata_list[i : i + chunk],
                target_list=target_list[i : i + chunk],
                royalty_percentage=royalty_percentage,
                royalty_address=royalty_address,
                mint_number_start=i + 1,
                mint_total=n,
                xch_coins=[next_coin.to_json_dict()],
                xch_change_target=funding_coin_dict["puzzle_hash"],
                did_coin=did_coin.to_json_dict(),
                did_lineage_parent=did_lineage_parent,
                mint_from_did=True,
                fee=fee,
            )
            assert resp["success"]
            sb: SpendBundle = SpendBundle.from_json_dict(resp["spend_bundle"])
            did_lineage_parent = [cn for cn in sb.removals() if cn.name() == did_coin.name()][0].parent_coin_info.hex()
            did_coin = [cn for cn in sb.additions() if (cn.parent_coin_info == did_coin.name()) and (cn.amount == 1)][0]
            spends.append(sb)
            xch_adds = [c for c in sb.additions() if c.puzzle_hash == funding_coin.puzzle_hash]
            assert len(xch_adds) == 1
            next_coin = xch_adds[0]
            for nft_id in resp["nft_id_list"]:
                nft_ids.add(decode_puzzle_hash(nft_id))
        for sb in spends:
            resp = await client_node.push_tx(sb)
            assert resp["success"]
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
            await asyncio.sleep(2)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

        async def get_taker_nfts() -> int:
            nfts = (await api_taker.nft_get_nfts({"wallet_id": nft_wallet_taker["wallet_id"]}))["nft_list"]
            return len(nfts)

        # We are using a long time out here because it can take a long time for the NFTs to show up
        # Even with only 10 NFTs it regularly takes longer than 30-40s for them to be found
        await time_out_assert(60, get_taker_nfts, n)

        # check NFT edition numbers
        nfts = (await api_taker.nft_get_nfts({"wallet_id": nft_wallet_taker["wallet_id"]}))["nft_list"]
        for nft in nfts:
            edition_num = nft.edition_number
            meta_dict = metadata_list[edition_num - 1]
            assert meta_dict["hash"] == nft.data_hash.hex()
            assert meta_dict["uris"] == nft.data_uris
            assert meta_dict["meta_hash"] == nft.metadata_hash.hex()
            assert meta_dict["meta_uris"] == nft.metadata_uris
            assert meta_dict["license_hash"] == nft.license_hash.hex()
            assert meta_dict["license_uris"] == nft.license_uris
            assert meta_dict["edition_number"] == nft.edition_number
            assert meta_dict["edition_total"] == nft.edition_total
            assert nft.launcher_id in nft_ids
    finally:
        client.close()
        client_node.close()
        rpc_server.close()
        rpc_server_node.close()
        await client.await_closed()
        await client_node.await_closed()
        await rpc_server.await_closed()
        await rpc_server_node.await_closed()


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_did_rpc_no_royalties(two_wallet_nodes: Any, trusted: Any, self_hostname: str) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    bt = full_node_api.bt
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds)

    api_maker = WalletRpcApi(wallet_node_maker)
    api_taker = WalletRpcApi(wallet_node_taker)
    config = bt.config
    daemon_port = config["daemon_port"]

    def stop_node_cb() -> None:
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_server_node = await start_rpc_server(
        full_node_rpc_api,
        self_hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    rpc_server = await start_rpc_server(
        api_maker,
        self_hostname,
        daemon_port,
        uint16(0),
        lambda x: None,  # type: ignore
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    client = await WalletRpcClient.create(self_hostname, rpc_server.listen_port, bt.root_path, config)
    client_node = await FullNodeRpcClient.create(self_hostname, rpc_server_node.listen_port, bt.root_path, config)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(config))

    nft_wallet_maker = await api_maker.create_new_wallet(
        dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id)
    )
    assert isinstance(nft_wallet_maker, dict)
    assert nft_wallet_maker.get("success")

    nft_wallet_taker = await api_taker.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 2"))

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    try:
        n = 10
        metadata_list = [
            {
                "hash": bytes32(token_bytes(32)).hex(),
                "uris": ["https://data.com/{}".format(i)],
                "meta_hash": bytes32(token_bytes(32)).hex(),
                "meta_uris": ["https://meatadata.com/{}".format(i)],
                "license_hash": bytes32(token_bytes(32)).hex(),
                "license_uris": ["https://license.com/{}".format(i)],
                "edition_number": i + 1,
                "edition_total": n,
            }
            for i in range(n)
        ]
        target_list = [encode_puzzle_hash((ph_taker), "xch") for x in range(n)]
        royalty_address = None
        royalty_percentage = None
        required_amount = n
        xch_coins = await client.select_coins(amount=required_amount, wallet_id=wallet_maker.id())
        funding_coin = xch_coins[0]
        assert funding_coin.amount >= required_amount
        funding_coin_dict = xch_coins[0].to_json_dict()
        chunk = 5
        next_coin = funding_coin
        did_coin = (await client.select_coins(amount=1, wallet_id=2))[0]
        did_lineage_parent = None
        spends = []

        for i in range(0, n, chunk):
            resp: Dict[str, Any] = await client.nft_mint_bulk(
                wallet_id=nft_wallet_maker["wallet_id"],
                metadata_list=metadata_list[i : i + chunk],
                target_list=target_list[i : i + chunk],
                royalty_percentage=royalty_percentage,
                royalty_address=royalty_address,
                mint_number_start=i + 1,
                mint_total=n,
                xch_coins=[next_coin.to_json_dict()],
                xch_change_target=funding_coin_dict["puzzle_hash"],
                did_coin=did_coin.to_json_dict(),
                did_lineage_parent=did_lineage_parent,
                mint_from_did=True,
            )
            assert resp["success"]
            sb: SpendBundle = SpendBundle.from_json_dict(resp["spend_bundle"])
            did_lineage_parent = [cn for cn in sb.removals() if cn.name() == did_coin.name()][0].parent_coin_info.hex()
            did_coin = [cn for cn in sb.additions() if (cn.parent_coin_info == did_coin.name()) and (cn.amount == 1)][0]
            spends.append(sb)
            xch_adds = [c for c in sb.additions() if c.puzzle_hash == funding_coin.puzzle_hash]
            assert len(xch_adds) == 1
            next_coin = xch_adds[0]

        for sb in spends:
            resp = await client_node.push_tx(sb)
            assert resp["success"]
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
            await asyncio.sleep(2)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

        async def get_taker_nfts() -> int:
            nfts = (await api_taker.nft_get_nfts({"wallet_id": nft_wallet_taker["wallet_id"]}))["nft_list"]
            return len(nfts)

        await time_out_assert(60, get_taker_nfts, n)

    finally:
        client.close()
        client_node.close()
        rpc_server.close()
        rpc_server_node.close()
        await client.await_closed()
        await client_node.await_closed()
        await rpc_server.await_closed()
        await rpc_server_node.await_closed()


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_did_multiple_xch(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_maker = wallet_node_0.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds)

    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallet_maker.get_pending_change_balance, 0)

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    await time_out_assert(5, did_wallet.get_confirmed_balance, 1)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1", did_id=did_id
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    # construct sample metadata
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    royalty_pc = uint16(300)
    royalty_addr = ph_maker

    mint_total = 1
    fee = uint64(100)
    metadata_list = [
        {"program": metadata, "royalty_pc": royalty_pc, "royalty_ph": royalty_addr} for x in range(mint_total)
    ]

    # Grab two coins for testing that we can create a bulk minting with more than 1 xch coin
    xch_coins_1 = await wallet_maker.select_coins(amount=10000)
    xch_coins_2 = await wallet_maker.select_coins(amount=10000, exclude=xch_coins_1)
    xch_coins = xch_coins_1.union(xch_coins_2)

    target_list = [ph_taker for x in range(mint_total)]

    sb = await nft_wallet_maker.mint_from_did(
        metadata_list,
        target_list=target_list,
        mint_number_start=1,
        mint_total=mint_total,
        xch_coins=xch_coins,
        fee=fee,
    )

    await api_0.push_tx({"spend_bundle": bytes(sb).hex()})

    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, nft_count, mint_total, nft_wallet_taker)
    await time_out_assert(30, nft_count, 0, nft_wallet_maker)

    # confirm that the spend uses the right amount of xch
    expected_xch_bal = funds - fee - mint_total - 1
    await time_out_assert(30, wallet_maker.get_confirmed_balance, expected_xch_bal)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_xch(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph_maker = await wallet_0.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    # for _ in range(1, num_blocks):
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)

    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    await time_out_assert(5, did_wallet.get_confirmed_balance, 1)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1", did_id=did_id
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )

    royalty_pc = uint16(300)
    royalty_addr = ph_maker

    mint_total = 1
    fee = uint64(100)
    metadata_list = [
        {
            "program": Program.to(
                [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", token_bytes(32).hex())]
            ),
            "royalty_pc": royalty_pc,
            "royalty_ph": royalty_addr,
        }
        for x in range(mint_total)
    ]

    target_list = [(await wallet_1.get_new_puzzlehash()) for x in range(mint_total)]

    sb = await nft_wallet_maker.mint_from_xch(
        metadata_list, target_list=target_list, mint_number_start=1, mint_total=mint_total, fee=fee
    )

    await api_0.push_tx({"spend_bundle": bytes(sb).hex()})

    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, nft_count, mint_total, nft_wallet_taker)
    await time_out_assert(30, nft_count, 0, nft_wallet_maker)

    expected_xch_bal = funds - fee - mint_total - 1
    await time_out_assert(30, wallet_0.get_confirmed_balance, expected_xch_bal)

    nfts = await nft_wallet_taker.get_current_nfts()
    matched_data = dict(zip(target_list, metadata_list))

    # Check targets and metadata entries match in the final nfts
    for nft in nfts:
        mod, args = nft.full_puzzle.uncurry()
        unft = UncurriedNFT.uncurry(mod, args)
        assert isinstance(unft, UncurriedNFT)
        inner_args = unft.inner_puzzle.uncurry()[1]
        inner_ph = inner_args.at("rrrf").get_tree_hash()
        meta = unft.metadata.at("rfr").as_atom()
        # check that the target puzzle hashes of transferred nfts matches the metadata entry
        assert matched_data[inner_ph]["program"].at("rfr").as_atom() == meta
        assert not nft.minter_did


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_xch_rpc(two_wallet_nodes: Any, trusted: Any, self_hostname: str) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    bt = full_node_api.bt
    full_node_server = full_node_api.server
    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_maker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_taker.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_maker.config["trusted_peers"] = {}
        wallet_node_taker.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_taker.get_confirmed_balance, funds)

    api_maker = WalletRpcApi(wallet_node_maker)
    api_taker = WalletRpcApi(wallet_node_taker)
    config = bt.config
    daemon_port = config["daemon_port"]

    def stop_node_cb() -> None:
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_server_node = await start_rpc_server(
        full_node_rpc_api,
        self_hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    rpc_server = await start_rpc_server(
        api_maker,
        self_hostname,
        daemon_port,
        uint16(0),
        lambda x: None,  # type: ignore
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    client = await WalletRpcClient.create(self_hostname, rpc_server.listen_port, bt.root_path, config)
    client_node = await FullNodeRpcClient.create(self_hostname, rpc_server_node.listen_port, bt.root_path, config)

    did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
        did_wallet_maker.id()
    )

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds - 1)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds - 1)

    hex_did_id = did_wallet_maker.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(config))

    nft_wallet_maker = await api_maker.create_new_wallet(
        dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id)
    )
    assert isinstance(nft_wallet_maker, dict)
    assert nft_wallet_maker.get("success")

    nft_wallet_taker = await api_taker.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 2"))

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    try:
        n = 10
        metadata_list = [
            {
                "hash": bytes32(token_bytes(32)).hex(),
                "uris": ["https://data.com/{}".format(i)],
                "meta_hash": bytes32(token_bytes(32)).hex(),
                "meta_uris": ["https://meatadata.com/{}".format(i)],
                "license_hash": bytes32(token_bytes(32)).hex(),
                "license_uris": ["https://license.com/{}".format(i)],
                "edition_number": i + 1,
                "edition_total": n,
            }
            for i in range(n)
        ]
        target_list = [encode_puzzle_hash((ph_taker), "xch") for x in range(n)]
        royalty_address = encode_puzzle_hash(bytes32(token_bytes(32)), "xch")
        royalty_percentage = 300
        fee = 100
        required_amount = n + (fee * n)
        xch_coins = await client.select_coins(amount=required_amount, wallet_id=wallet_maker.id())
        funding_coin = xch_coins[0]
        assert funding_coin.amount >= required_amount
        funding_coin_dict = xch_coins[0].to_json_dict()
        chunk = 5
        next_coin = funding_coin
        spends = []

        for i in range(0, n, chunk):
            resp: Dict[str, Any] = await client.nft_mint_bulk(
                wallet_id=nft_wallet_maker["wallet_id"],
                metadata_list=metadata_list[i : i + chunk],
                target_list=target_list[i : i + chunk],
                royalty_percentage=royalty_percentage,
                royalty_address=royalty_address,
                mint_number_start=i + 1,
                mint_total=n,
                xch_coins=[next_coin.to_json_dict()],
                xch_change_target=funding_coin_dict["puzzle_hash"],
                mint_from_did=False,
                fee=fee,
            )
            assert resp["success"]
            sb: SpendBundle = SpendBundle.from_json_dict(resp["spend_bundle"])
            spends.append(sb)
            xch_adds = [c for c in sb.additions() if c.puzzle_hash == funding_coin.puzzle_hash]
            assert len(xch_adds) == 1
            next_coin = xch_adds[0]

        for sb in spends:
            resp = await client_node.push_tx(sb)
            assert resp["success"]
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
            await asyncio.sleep(2)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

        async def get_taker_nfts() -> int:
            nfts = (await api_taker.nft_get_nfts({"wallet_id": nft_wallet_taker["wallet_id"]}))["nft_list"]
            return len(nfts)

        # We are using a long time out here because it can take a long time for the NFTs to show up
        # Even with only 10 NFTs it regularly takes longer than 30-40s for them to be found
        await time_out_assert(60, get_taker_nfts, n)

        # check NFT edition numbers
        nfts = (await api_taker.nft_get_nfts({"wallet_id": nft_wallet_taker["wallet_id"]}))["nft_list"]
        for nft in nfts:
            edition_num = nft.edition_number
            meta_dict = metadata_list[edition_num - 1]
            assert meta_dict["hash"] == nft.data_hash.hex()
            assert meta_dict["uris"] == nft.data_uris
            assert meta_dict["meta_hash"] == nft.metadata_hash.hex()
            assert meta_dict["meta_uris"] == nft.metadata_uris
            assert meta_dict["license_hash"] == nft.license_hash.hex()
            assert meta_dict["license_uris"] == nft.license_uris
            assert meta_dict["edition_number"] == nft.edition_number
            assert meta_dict["edition_total"] == nft.edition_total

    finally:
        client.close()
        client_node.close()
        rpc_server.close()
        rpc_server_node.close()
        await client.await_closed()
        await client_node.await_closed()
        await rpc_server.await_closed()
        await rpc_server_node.await_closed()


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_mint_from_xch_multiple_xch(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_maker = wallet_node_0.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_maker.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_maker.get_confirmed_balance, funds)

    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallet_maker.get_pending_change_balance, 0)

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.fromhex(hex_did_id)

    await time_out_assert(5, did_wallet.get_confirmed_balance, 1)

    nft_wallet_maker = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_maker, name="NFT WALLET 1", did_id=did_id
    )

    nft_wallet_taker = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_taker, name="NFT WALLET 2"
    )

    # construct sample metadata
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    royalty_pc = uint16(300)
    royalty_addr = ph_maker

    mint_total = 1
    fee = uint64(100)
    metadata_list = [
        {"program": metadata, "royalty_pc": royalty_pc, "royalty_ph": royalty_addr} for x in range(mint_total)
    ]

    # Grab two coins for testing that we can create a bulk minting with more than 1 xch coin
    xch_coins_1 = await wallet_maker.select_coins(amount=10000)
    xch_coins_2 = await wallet_maker.select_coins(amount=10000, exclude=xch_coins_1)
    xch_coins = xch_coins_1.union(xch_coins_2)

    target_list = [ph_taker for x in range(mint_total)]

    sb = await nft_wallet_maker.mint_from_xch(
        metadata_list,
        target_list=target_list,
        mint_number_start=1,
        mint_total=mint_total,
        xch_coins=xch_coins,
        fee=fee,
    )

    await api_0.push_tx({"spend_bundle": bytes(sb).hex()})

    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await time_out_assert(30, nft_count, mint_total, nft_wallet_taker)
    await time_out_assert(30, nft_count, 0, nft_wallet_maker)

    # confirm that the spend uses the right amount of xch
    expected_xch_bal = funds - fee - mint_total - 1
    await time_out_assert(30, wallet_maker.get_confirmed_balance, expected_xch_bal)
