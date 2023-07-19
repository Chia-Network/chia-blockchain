from __future__ import annotations

import contextlib
import io
import sys
from decimal import Decimal

import click.testing
import pytest

from chia.cmds.wallet_funcs import (
    add_uri_to_nft,
    cancel_offer,
    did_message_spend,
    make_offer,
    set_nft_did,
    take_offer,
    update_did_metadata,
)
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import SimulatorsAndWalletsServices
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG


def check_mempool_spend_count(full_node_api: FullNodeSimulator, num_of_spends: int) -> bool:
    return full_node_api.full_node.mempool_manager.mempool.size() == num_of_spends


@pytest.mark.asyncio
async def test_make_and_take_and_cancel_offer(two_wallet_nodes_services: SimulatorsAndWalletsServices) -> None:
    # Wallet environment setup
    num_blocks = 1
    full_nodes, wallets, bt = two_wallet_nodes_services
    full_node_api = full_nodes[0]._api
    full_node_server = full_node_api.server
    wallet_service_0 = wallets[0]
    wallet_service_1 = wallets[1]
    wallet_node_0 = wallet_service_0._node
    wallet_node_1 = wallet_service_1._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    assert wallet_service_0.rpc_server is not None
    assert wallet_service_1.rpc_server is not None

    wallet_node_0.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }
    wallet_node_1.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await wallet_node_0.server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await wallet_node_1.server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)

    cat_wallet_0: CATWallet = await CATWallet.create_new_cat_wallet(
        wallet_node_0.wallet_state_manager,
        wallet_0,
        {"identifier": "genesis_by_id"},
        uint64(100),
        DEFAULT_TX_CONFIG,
    )
    await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_1.wallet_state_manager, wallet_1, cat_wallet_0.get_asset_id()
    )

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    assert wallet_service_0.rpc_server.webserver is not None
    assert wallet_service_1.rpc_server.webserver is not None
    fingerprint_0 = wallet_0.wallet_state_manager.private_key.get_g1().get_fingerprint()
    fingerprint_1 = wallet_1.wallet_state_manager.private_key.get_g1().get_fingerprint()

    with click.testing.CliRunner().isolated_filesystem():
        f = io.StringIO()

        sys.stdin = io.StringIO("y")
        with contextlib.redirect_stdout(f):
            await make_offer(
                wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
                fp=fingerprint_0,
                d_fee=Decimal("0.0"),
                offers=[f"{cat_wallet_0.id()}:0.1"],
                requests=["1:1"],
                filepath="./test.offer",
                reuse_puzhash=True,
                root_path=wallet_service_0.root_path,
            )

        assert "Creating Offer" in f.getvalue()
        f.truncate(0)

        sys.stdin = io.StringIO("y")
        with contextlib.redirect_stdout(f):
            await cancel_offer(
                wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
                fp=fingerprint_0,
                d_fee=Decimal("0.0"),
                offer_id_hex=(await wallet_0.wallet_state_manager.trade_manager.get_all_trades())[0].trade_id.hex(),
                secure=True,
                root_path=wallet_service_0.root_path,
            )

        assert "Cancelled offer" in f.getvalue()
        f.truncate(0)

        await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
        await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

        sys.stdin = io.StringIO("y")
        with contextlib.redirect_stdout(f):
            await make_offer(
                wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
                fp=fingerprint_0,
                d_fee=Decimal("0.0"),
                offers=[f"{cat_wallet_0.id()}:0.1"],
                requests=["1:1"],
                filepath="./test.offer",
                reuse_puzhash=True,
                root_path=wallet_service_0.root_path,
            )

        assert "Creating Offer" in f.getvalue()
        f.truncate(0)

        sys.stdin = io.StringIO("y")
        with contextlib.redirect_stdout(f):
            await take_offer(
                wallet_rpc_port=wallet_service_1.rpc_server.webserver.listen_port,
                fp=fingerprint_1,
                d_fee=Decimal("0.0"),
                file="./test.offer",
                examine_only=False,
                root_path=wallet_service_1.root_path,
            )

        assert "Accepted offer" in f.getvalue()

        await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)


@pytest.mark.asyncio
async def test_update_did_metadata_and_did_message_spend(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
) -> None:
    # Wallet environment setup
    num_blocks = 1
    full_nodes, wallets, bt = one_wallet_and_one_simulator_services
    full_node_api = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_node_0 = wallet_service_0._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    assert wallet_service_0.rpc_server is not None

    wallet_node_0.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await wallet_node_0.server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
    )

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    assert wallet_service_0.rpc_server.webserver is not None
    fingerprint_0 = wallet_0.wallet_state_manager.private_key.get_g1().get_fingerprint()

    f = io.StringIO()

    with contextlib.redirect_stdout(f):
        await did_message_spend(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fp=fingerprint_0,
            did_wallet_id=did_wallet.id(),
            puzzle_announcements=[],
            coin_announcements=[],
            root_path=wallet_service_0.root_path,
        )

    assert "Message Spend Bundle:" in f.getvalue()
    f.truncate(0)

    with contextlib.redirect_stdout(f):
        await update_did_metadata(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fp=fingerprint_0,
            did_wallet_id=did_wallet.id(),
            metadata='{"meta": "data"}',
            reuse_puzhash=True,
            root_path=wallet_service_0.root_path,
        )

    assert "Successfully updated DID wallet ID: 2" in f.getvalue()

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)


@pytest.mark.asyncio
async def test_add_uri_to_nft_and_set_nft_did(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
) -> None:
    # Wallet environment setup
    num_blocks = 1
    full_nodes, wallets, bt = one_wallet_and_one_simulator_services
    full_node_api = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_node_0 = wallet_service_0._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    assert wallet_service_0.rpc_server is not None

    wallet_node_0.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await wallet_node_0.server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
    )
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    assert did_wallet_0.did_info.origin_coin is not None
    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager,
        wallet_0,
        name="NFT WALLET 1",
        did_id=did_wallet_0.did_info.origin_coin.name(),
    )
    await nft_wallet_0.generate_new_nft(
        Program.to([("u", ["test.com"])]),
        DEFAULT_TX_CONFIG,
        royalty_puzzle_hash=bytes32([0] * 32),
        percentage=uint16(100),
    )

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    assert wallet_service_0.rpc_server.webserver is not None
    fingerprint_0 = wallet_0.wallet_state_manager.private_key.get_g1().get_fingerprint()

    f = io.StringIO()

    with contextlib.redirect_stdout(f):
        await add_uri_to_nft(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fp=fingerprint_0,
            wallet_id=nft_wallet_0.id(),
            d_fee=Decimal("0.0"),
            nft_coin_id=(await nft_wallet_0.get_current_nfts())[0].coin.name().hex(),
            uri="test.com",
            metadata_uri=None,
            license_uri=None,
            reuse_puzhash=True,
            root_path=wallet_service_0.root_path,
        )

    assert "URI added successfully" in f.getvalue()
    f.truncate(0)

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    with contextlib.redirect_stdout(f):
        await set_nft_did(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fp=fingerprint_0,
            wallet_id=nft_wallet_0.id(),
            d_fee=Decimal("0.0"),
            nft_coin_id=(await nft_wallet_0.get_current_nfts())[0].coin.name().hex(),
            did_id=encode_puzzle_hash(did_wallet_0.did_info.origin_coin.name(), "did:1"),
            reuse_puzhash=True,
            root_path=wallet_service_0.root_path,
        )

    assert "Transaction to set DID on NFT has been initiated" in f.getvalue()

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
