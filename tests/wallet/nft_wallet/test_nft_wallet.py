from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element
from clvm_tools.binutils import disassemble

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import adjusted_timeout, time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.wallet.wallet_state_manager import WalletStateManager


async def get_nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


async def get_wallet_number(manager: WalletStateManager) -> int:
    return len(manager.wallets)


async def wait_rpc_state_condition(
    timeout: float,
    async_function: Callable[[Dict[str, Any]], Awaitable[Dict]],
    params: List[Dict],
    condition_func: Callable[[Dict[str, Any]], bool],
) -> Dict:
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.monotonic()

    while True:
        resp = await async_function(*params)
        assert isinstance(resp, dict)
        if condition_func(resp):
            return resp

        now = time.monotonic()
        elapsed = now - start
        if elapsed >= timeout:
            raise asyncio.TimeoutError(
                f"timed out while waiting for {async_function.__name__}(): {elapsed} >= {timeout}",
            )

        await asyncio.sleep(0.3)


async def make_new_block_with(resp: Dict, full_node_api: FullNodeSimulator, ph: bytes32) -> SpendBundle:
    assert resp.get("success")
    sb = resp["spend_bundle"]
    assert isinstance(sb, SpendBundle)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    return sb


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_wallet_creation_automatically(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

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

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    coins = await nft_wallet_0.get_current_nfts()
    assert len(coins) == 1, "nft not generated"

    txs = await nft_wallet_0.generate_signed_transaction([uint64(coins[0].coin.amount)], [ph1], coins={coins[0].coin})
    assert len(txs) == 1
    assert txs[0].spend_bundle is not None
    await wallet_node_0.wallet_state_manager.add_pending_transaction(txs[0])
    await time_out_assert_not_none(
        30, full_node_api.full_node.mempool_manager.get_spendbundle, txs[0].spend_bundle.name()
    )
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    async def num_wallets() -> int:
        return len(await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries())

    await time_out_assert(30, num_wallets, 2)
    # Get the new NFT wallet
    nft_wallets = await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries(WalletType.NFT)
    assert len(nft_wallets) == 1
    nft_wallet_1: NFTWallet = wallet_node_1.wallet_state_manager.wallets[nft_wallets[0].id]
    await time_out_assert(30, get_nft_count, 0, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)

    assert await nft_wallet_0.get_nft_count() == 0
    assert await nft_wallet_1.get_nft_count() == 1


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_wallet_creation_and_transfer(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 2
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

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

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 2000000000000)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 2000000000000)
    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(10, get_nft_count, 1, nft_wallet_0)
    await time_out_assert(10, wallet_0.get_unconfirmed_balance, 4000000000000 - 1)
    await time_out_assert(10, wallet_0.get_confirmed_balance, 4000000000000 - 1)
    # Test Reorg mint
    height = full_node_api.full_node.blockchain.get_peak_height()
    if height is None:
        assert False
    await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(height - 1), uint32(height + 1), ph1, None))
    await time_out_assert(30, get_nft_count, 0, nft_wallet_0)
    await time_out_assert(30, get_wallet_number, 2, wallet_node_0.wallet_state_manager)

    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )

    metadata = Program.to(
        [
            ("u", ["https://www.test.net/logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F181"),
        ]
    )

    await time_out_assert(10, wallet_0.get_unconfirmed_balance, 4000000000000 - 1)
    await time_out_assert(10, wallet_0.get_confirmed_balance, 4000000000000)

    sb = await nft_wallet_0.generate_new_nft(metadata)
    assert sb
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await time_out_assert(30, wallet_node_0.wallet_state_manager.lock.locked, False)
    for i in range(1, num_blocks * 2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await time_out_assert(30, get_nft_count, 2, nft_wallet_0)
    coins = await nft_wallet_0.get_current_nfts()
    assert len(coins) == 2, "nft not generated"

    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )
    txs = await nft_wallet_0.generate_signed_transaction([uint64(coins[1].coin.amount)], [ph1], coins={coins[1].coin})
    assert len(txs) == 1
    assert txs[0].spend_bundle is not None
    await wallet_node_0.wallet_state_manager.add_pending_transaction(txs[0])
    await time_out_assert_not_none(
        30, full_node_api.full_node.mempool_manager.get_spendbundle, txs[0].spend_bundle.name()
    )
    assert compute_memos(txs[0].spend_bundle)

    for i in range(1, num_blocks * 2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)

    coins = await nft_wallet_1.get_current_nfts()
    assert len(coins) == 1

    await time_out_assert(30, wallet_1.get_pending_change_balance, 0)

    # Send it back to original owner
    txs = await nft_wallet_1.generate_signed_transaction([uint64(coins[0].coin.amount)], [ph], coins={coins[0].coin})
    assert len(txs) == 1
    assert txs[0].spend_bundle is not None
    await wallet_node_1.wallet_state_manager.add_pending_transaction(txs[0])
    await time_out_assert_not_none(
        30, full_node_api.full_node.mempool_manager.get_spendbundle, txs[0].spend_bundle.name()
    )
    assert compute_memos(txs[0].spend_bundle)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await time_out_assert(30, wallet_node_0.wallet_state_manager.lock.locked, False)
    await time_out_assert(30, get_nft_count, 2, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 0, nft_wallet_1)

    # Test Reorg
    height = full_node_api.full_node.blockchain.get_peak_height()
    if height is None:
        assert False
    await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(height - 1), uint32(height + 2), ph1, None))
    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_wallet_rpc_creation_and_list(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    _ = await wallet_1.get_new_puzzlehash()

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

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(30, wallet_node_0.wallet_state_manager.synced, True)
    api_0 = WalletRpcApi(wallet_node_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    nft_wallet_0 = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(nft_wallet_0, dict)
    assert nft_wallet_0.get("success")
    nft_wallet_0_id = nft_wallet_0["wallet_id"]

    tr1 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["spend_bundle"]

    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await wait_rpc_state_condition(30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"])
    tr2 = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F184",
            "uris": ["https://chialisp.com/img/logo.svg"],
            "meta_uris": [
                "https://bafybeigzcazxeu7epmm4vtkuadrvysv74lbzzbl2evphtae6k57yhgynp4.ipfs.nftstorage.link/6590.json"
            ],
            "meta_hash": "0x6a9cb99b7b9a987309e8dd4fd14a7ca2423858585da68cc9ec689669dd6dd6ab",
        }
    )
    assert isinstance(tr2, dict)
    assert tr2.get("success")
    sb = tr2["spend_bundle"]
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    coins_response = await wait_rpc_state_condition(
        5,
        api_0.nft_get_nfts,
        [{"wallet_id": nft_wallet_0_id}],
        lambda x: x["success"] and len(x["nft_list"]) == 2,
    )
    coins = coins_response["nft_list"]
    uris = []
    for coin in coins:
        assert not coin.supports_did
        uris.append(coin.data_uris[0])
        assert coin.mint_height > 0
    assert len(uris) == 2
    assert "https://chialisp.com/img/logo.svg" in uris
    assert bytes32.fromhex(coins[1].to_json_dict()["nft_coin_id"][2:]) in [x.name() for x in sb.additions()]

    coins_response = await wait_rpc_state_condition(
        5,
        api_0.nft_get_nfts,
        [{"wallet_id": nft_wallet_0_id, "start_index": 1, "num": 1}],
        lambda x: x["success"] and len(x["nft_list"]) == 1,
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].data_hash.hex() == "0xD4584AD463139FA8C0D9F68F4B59F184"[2:].lower()

    # test counts

    resp = await wait_rpc_state_condition(
        10, api_0.nft_count_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: x["success"]
    )
    assert resp["count"] == 2
    resp = await wait_rpc_state_condition(10, api_0.nft_count_nfts, [{}], lambda x: x["success"])
    assert resp["count"] == 2
    resp = await wait_rpc_state_condition(
        10, api_0.nft_count_nfts, [{"wallet_id": 50}], lambda x: x["success"] is False
    )
    assert resp.get("count") is None


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_wallet_rpc_update_metadata(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    from chia.types.blockchain_format.sized_bytes import bytes32

    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph = await wallet_0.get_new_puzzlehash()
    _ = await wallet_1.get_new_puzzlehash()

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

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)

    api_0 = WalletRpcApi(wallet_node_0)
    await time_out_assert(30, wallet_node_0.wallet_state_manager.synced, True)
    await time_out_assert(30, wallet_node_1.wallet_state_manager.synced, True)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    nft_wallet_0 = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(nft_wallet_0, dict)
    assert nft_wallet_0.get("success")
    nft_wallet_0_id = nft_wallet_0["wallet_id"]

    # mint NFT
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "artist_address": ph,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )

    assert resp.get("success")
    sb = resp["spend_bundle"]

    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    coins_response = await wait_rpc_state_condition(
        5, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    assert coins_response["nft_list"], isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    coin = coins[0].to_json_dict()
    assert coin["mint_height"] > 0
    assert coin["data_hash"] == "0xd4584ad463139fa8c0d9f68f4b59f185"
    assert coin["chain_info"] == disassemble(
        Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", hexstr_to_bytes("0xD4584AD463139FA8C0D9F68F4B59F185")),
                ("mu", []),
                ("lu", []),
                ("sn", uint64(1)),
                ("st", uint64(1)),
            ]
        )
    )
    # add another URI using a bech32m nft_coin_id
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    nft_coin_id = encode_puzzle_hash(
        bytes32.from_hexstr(coin["nft_coin_id"]), AddressType.NFT.hrp(api_0.service.config)
    )
    tr1 = await api_0.nft_add_uri(
        {"wallet_id": nft_wallet_0_id, "nft_coin_id": nft_coin_id, "uri": "http://metadata", "key": "mu"}
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert coins_response["nft_list"][0].pending_transaction
    sb = tr1["spend_bundle"]
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    # check that new URI was added
    coins_response = await wait_rpc_state_condition(
        5,
        api_0.nft_get_nfts,
        [dict(wallet_id=nft_wallet_0_id)],
        lambda x: x["nft_list"] and len(x["nft_list"][0].metadata_uris) == 1,
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    coin = coins[0].to_json_dict()
    assert coin["mint_height"] > 0
    uris = coin["data_uris"]
    assert len(uris) == 1
    assert "https://www.chia.net/img/branding/chia-logo.svg" in uris
    assert len(coin["metadata_uris"]) == 1
    assert "http://metadata" == coin["metadata_uris"][0]
    assert len(coin["license_uris"]) == 0

    # add yet another URI, this time using a hex nft_coin_id
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    nft_coin_id = coin["nft_coin_id"]
    tr1 = await api_0.nft_add_uri(
        {
            "wallet_id": nft_wallet_0_id,
            "nft_coin_id": nft_coin_id,
            "uri": "http://data",
            "key": "u",
        }
    )

    assert isinstance(tr1, dict)
    assert tr1.get("success")
    sb = tr1["spend_bundle"]
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    coins_response = await wait_rpc_state_condition(
        5,
        api_0.nft_get_nfts,
        [dict(wallet_id=nft_wallet_0_id)],
        lambda x: x["nft_list"] and len(x["nft_list"][0].data_uris) == 2,
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    coin = coins[0].to_json_dict()
    assert coin["mint_height"] > 0
    uris = coin["data_uris"]
    assert len(uris) == 2
    assert len(coin["metadata_uris"]) == 1
    assert "http://data" == coin["data_uris"][0]


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_with_did_wallet_creation(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    # this shouldn't work
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert res["wallet_id"] == nft_wallet_0_id

    # now create NFT wallet with P2 standard puzzle for inner puzzle
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 0"))
    assert res["wallet_id"] != nft_wallet_0_id
    nft_wallet_p2_puzzle = res["wallet_id"]

    res = await api_0.nft_get_by_did({"did_id": hmr_did_id})
    assert nft_wallet_0_id == res["wallet_id"]
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 3999999999999)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 3999999999999)

    res = await api_0.nft_get_wallets_with_dids({})
    assert res.get("success")
    assert res.get("nft_wallets") == [
        {"wallet_id": nft_wallet_0_id, "did_id": hmr_did_id, "did_wallet_id": did_wallet.id()}
    ]

    res = await api_0.nft_get_wallet_did({"wallet_id": nft_wallet_0_id})
    assert res.get("success")
    assert res.get("did_id") == hmr_did_id

    # Create a NFT with DID
    nft_ph: bytes32 = await wallet_0.get_new_puzzlehash()
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "target_address": encode_puzzle_hash(nft_ph, "txch"),
        }
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]
    # ensure hints are generated correctly
    memos = compute_memos(sb)
    assert memos
    puzhashes = []
    for x in memos.values():
        puzhashes.extend(list(x))
    assert len(puzhashes) > 0
    matched = 0
    for puzhash in puzhashes:
        if puzhash.hex() == nft_ph.hex():
            matched += 1
    assert matched > 0

    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 5999999999999 - 1)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 5999999999999 - 1)
    # Create a NFT without DID, this will go the unassigned NFT wallet
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "did_id": "",
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F181",
            "uris": ["https://url1"],
        }
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]

    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 7999999999998 - 1)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 7999999999998 - 1)
    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        5, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    did_nft = coins[0].to_json_dict()
    assert did_nft["mint_height"] > 0
    assert did_nft["supports_did"]
    assert did_nft["data_uris"][0] == "https://www.chia.net/img/branding/chia-logo.svg"
    assert did_nft["data_hash"] == "0xD4584AD463139FA8C0D9F68F4B59F185".lower()
    assert did_nft["owner_did"][2:] == hex_did_id
    # Check unassigned NFT
    nft_wallets = await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries(WalletType.NFT)
    assert len(nft_wallets) == 2
    coins_response = await wait_rpc_state_condition(
        5, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_p2_puzzle}], lambda x: x["nft_list"]
    )
    assert coins_response["nft_list"]
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    non_did_nft = coins[0].to_json_dict()
    assert non_did_nft["mint_height"] > 0
    assert non_did_nft["supports_did"]
    assert non_did_nft["data_uris"][0] == "https://url1"
    assert non_did_nft["data_hash"] == "0xD4584AD463139FA8C0D9F68F4B59F181".lower()
    assert non_did_nft["owner_did"] is None


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_rpc_mint(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    did_id = encode_puzzle_hash(bytes32.from_hexstr(did_wallet.get_my_DID()), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 5999999999999)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 5999999999999)
    # Create a NFT with DID
    royalty_address = ph1
    data_hash_param = "0xD4584AD463139FA8C0D9F68F4B59F185"
    license_uris = ["http://mylicenseuri"]
    license_hash = "0xcafef00d"
    meta_uris = ["http://metauri"]
    meta_hash = "0xdeadbeef"
    royalty_percentage = 200
    sn = 10
    st = 100
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": data_hash_param,
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "license_uris": license_uris,
            "license_hash": license_hash,
            "meta_hash": meta_hash,
            "edition_number": sn,
            "edition_total": st,
            "meta_uris": meta_uris,
            "royalty_address": royalty_address,
            "target_address": ph,
            "royalty_percentage": royalty_percentage,
        }
    )
    assert resp.get("success")
    nft_id: str = str(resp.get("nft_id"))
    sb = resp["spend_bundle"]

    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 9999999999998)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 9999999999998)
    coins_response = await wait_rpc_state_condition(
        5, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    did_nft = coins[0]
    assert did_nft.royalty_puzzle_hash == royalty_address
    assert did_nft.data_hash == bytes.fromhex(data_hash_param[2:])
    assert did_nft.metadata_hash == bytes.fromhex(meta_hash[2:])
    assert did_nft.metadata_uris == meta_uris
    assert did_nft.license_uris == license_uris
    assert did_nft.license_hash == bytes.fromhex(license_hash[2:])
    assert did_nft.edition_total == st
    assert did_nft.edition_number == sn
    assert did_nft.royalty_percentage == royalty_percentage
    assert decode_puzzle_hash(nft_id) == did_nft.launcher_id


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_transfer_nft_with_did(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    fee = 100
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    api_1 = WalletRpcApi(wallet_node_1)
    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    # Create DID
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # Create NFT wallet
    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    await time_out_assert(30, did_wallet.get_confirmed_balance, 1)
    await time_out_assert(30, did_wallet.get_unconfirmed_balance, 1)

    # Create a NFT with DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "fee": fee,
            "did_id": hmr_did_id,
        }
    )
    await make_new_block_with(resp, full_node_api, ph1)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        5, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 5999999999898)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 5999999999898)
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did.hex() == hex_did_id

    assert len(wallet_1.wallet_state_manager.wallets) == 1, "NFT wallet shouldn't exist yet"
    assert len(wallet_0.wallet_state_manager.wallets) == 3
    # transfer DID to the other wallet
    tx = await did_wallet.transfer_did(ph1, uint64(0), True)
    assert tx
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    await time_out_assert(15, len, 2, wallet_0.wallet_state_manager.wallets)
    # Transfer NFT, wallet will be deleted
    resp = await api_0.nft_transfer_nft(
        dict(
            wallet_id=nft_wallet_0_id,
            target_address=encode_puzzle_hash(ph1, "xch"),
            nft_coin_id=coins[0].nft_coin_id.hex(),
            fee=fee,
        )
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await make_new_block_with(resp, full_node_api, ph1)
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 5999999999798)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 5999999999798)
    await time_out_assert(30, len, 1, wallet_0.wallet_state_manager.wallets)

    # wait for all wallets to be created
    await time_out_assert(30, len, 3, wallet_1.wallet_state_manager.wallets)
    did_wallet_1 = wallet_1.wallet_state_manager.wallets[2]
    assert nft_wallet_0_id not in wallet_node_0.wallet_state_manager.wallets.keys()
    # Check if the NFT owner DID is reset
    resp = await api_1.nft_get_by_did({})
    assert resp.get("success")
    nft_wallet_id_1 = resp.get("wallet_id")
    coins_response = await wait_rpc_state_condition(
        10, api_1.nft_get_nfts, [dict(wallet_id=nft_wallet_id_1)], lambda x: x["nft_list"]
    )
    assert len(coins_response["nft_list"]) == 1
    assert coins_response["nft_list"][0].owner_did is None
    assert coins_response["nft_list"][0].minter_did.hex() == hex_did_id
    nft_coin_id = coins_response["nft_list"][0].nft_coin_id

    await time_out_assert(30, did_wallet_1.get_spendable_balance, 1)

    # Set DID
    resp = await api_1.nft_set_nft_did(
        dict(wallet_id=nft_wallet_id_1, did_id=hmr_did_id, nft_coin_id=nft_coin_id.hex(), fee=fee)
    )
    await make_new_block_with(resp, full_node_api, ph)

    coins_response = await wait_rpc_state_condition(
        5, api_1.nft_get_by_did, [dict(did_id=hmr_did_id)], lambda x: x.get("wallet_id", 0) > 0
    )
    await time_out_assert(30, wallet_1.get_unconfirmed_balance, 12000000000100)
    await time_out_assert(30, wallet_1.get_confirmed_balance, 12000000000100)
    nft_wallet_1_id = coins_response.get("wallet_id")
    assert nft_wallet_1_id
    # Check NFT DID is set now
    resp = await wait_rpc_state_condition(
        10,
        api_1.nft_get_nfts,
        [dict(wallet_id=nft_wallet_1_id)],
        lambda x: x["nft_list"] and x["nft_list"][0].owner_did,
    )
    coins = resp["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did.hex() == hex_did_id


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_update_metadata_for_nft_did(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    await time_out_assert(30, did_wallet.get_confirmed_balance, 1)

    # Create a NFT with DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did": hex_did_id,
        }
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]

    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    # Check DID NFT

    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].minter_did.hex() == hex_did_id
    nft_coin_id = coins[0].nft_coin_id

    # add another URI
    tr1 = await api_0.nft_add_uri(
        {
            "wallet_id": nft_wallet_0_id,
            "nft_coin_id": nft_coin_id.hex(),
            "uri": "http://metadata",
            "key": "mu",
            "fee": 100,
        }
    )
    assert isinstance(tr1, dict)
    assert tr1.get("success")
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert coins_response["nft_list"][0].pending_transaction

    sb = tr1["spend_bundle"]
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
    # check that new URI was added
    await time_out_assert(30, wallet_0.get_unconfirmed_balance, 11999999999898)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 11999999999898)
    coins_response = await wait_rpc_state_condition(
        5,
        api_0.nft_get_info,
        [dict(wallet_id=nft_wallet_0_id, coin_id=nft_coin_id.hex(), latest=True)],
        lambda x: x["nft_info"],
    )

    coin = coins_response["nft_info"].to_json_dict()
    assert coin["minter_did"][2:] == hex_did_id
    assert coin["mint_height"] > 0
    uris = coin["data_uris"]
    assert len(uris) == 1
    assert "https://www.chia.net/img/branding/chia-logo.svg" in uris
    assert len(coin["metadata_uris"]) == 1
    assert "http://metadata" == coin["metadata_uris"][0]
    assert len(coin["license_uris"]) == 0


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_bulk_set_did(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 2
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()

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

    for _ in range(1, num_blocks + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 3999999999999)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]
    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 2"))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_1_id = res["wallet_id"]
    await time_out_assert(30, did_wallet.get_confirmed_balance, 1)

    # Create a NFT with DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did_id": hmr_did_id,
        }
    )
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)
    await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) > 0
    )
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_1_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F186",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did_id": "",
        }
    )
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) == 1
    )
    coins = coins_response["nft_list"]
    nft1 = coins[0]
    assert len(coins) == 1
    assert coins[0].owner_did is not None
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_1_id}], lambda x: len(x["nft_list"]) == 1
    )
    coins = coins_response["nft_list"]
    nft2 = coins[0]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    nft_coin_list = [
        {"wallet_id": nft_wallet_0_id, "nft_coin_id": nft1.nft_coin_id.hex()},
        {"wallet_id": nft_wallet_1_id, "nft_coin_id": nft2.nft_coin_id.hex()},
        {"wallet_id": nft_wallet_1_id},
        {"nft_coin_id": nft2.nft_coin_id.hex()},
    ]
    resp = await api_0.nft_set_did_bulk(dict(did_id=hmr_did_id, nft_coin_list=nft_coin_list, fee=1000))
    assert len(resp["spend_bundle"].coin_spends) == 4
    assert resp["tx_num"] == 3
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) == 1
    )
    coins = coins_response["nft_list"]
    assert coins[0].pending_transaction
    await make_new_block_with(resp, full_node_api, ph)
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_by_did, [dict(did_id=hmr_did_id)], lambda x: x.get("wallet_id", 0) > 0
    )
    nft_wallet_1_id = coins_response.get("wallet_id")
    assert nft_wallet_1_id
    resp = await wait_rpc_state_condition(
        30,
        api_0.nft_get_nfts,
        [dict(wallet_id=nft_wallet_1_id)],
        lambda x: len(x["nft_list"]) > 1 and x["nft_list"][0].owner_did,
    )
    assert await wallet_node_0.wallet_state_manager.wallets[nft_wallet_0_id].get_nft_count() == 2
    coins = resp["nft_list"]
    assert len(coins) == 2
    assert coins[0].owner_did.hex() == hex_did_id
    assert coins[1].owner_did.hex() == hex_did_id


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_bulk_transfer(two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 2
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    api_1 = WalletRpcApi(wallet_node_1)
    ph = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()
    address = encode_puzzle_hash(ph1, AddressType.XCH.hrp(wallet_node_1.config))
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

    await server_0.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)

    for _ in range(1, num_blocks + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    await time_out_assert(30, wallet_0.get_confirmed_balance, 3999999999999)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]
    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 2"))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_1_id = res["wallet_id"]
    await time_out_assert(30, did_wallet.get_confirmed_balance, 1)

    # Create a NFT with DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did_id": hmr_did_id,
        }
    )
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)
    await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) > 0
    )
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_1_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F186",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did_id": "",
        }
    )
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) == 1
    )
    coins = coins_response["nft_list"]
    nft1 = coins[0]
    assert len(coins) == 1
    assert coins[0].owner_did is not None
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_1_id}], lambda x: len(x["nft_list"]) == 1
    )
    coins = coins_response["nft_list"]
    nft2 = coins[0]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    nft_coin_list = [
        {"wallet_id": nft_wallet_0_id, "nft_coin_id": nft1.nft_coin_id.hex()},
        {"wallet_id": nft_wallet_1_id, "nft_coin_id": nft2.nft_coin_id.hex()},
        {"wallet_id": nft_wallet_1_id},
        {"nft_coin_id": nft2.nft_coin_id.hex()},
    ]
    resp = await api_0.nft_transfer_bulk(dict(target_address=address, nft_coin_list=nft_coin_list, fee=1000))
    assert len(resp["spend_bundle"].coin_spends) == 3
    assert resp["tx_num"] == 3
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert(30, get_wallet_number, 2, wallet_node_1.wallet_state_manager)
    coins_response = await wait_rpc_state_condition(
        30, api_1.nft_get_nfts, [{"wallet_id": 2}], lambda x: len(x["nft_list"]) == 2
    )
    coins = coins_response["nft_list"]
    nft_set = {nft1.launcher_id, nft2.launcher_id}
    assert coins[1].launcher_id in nft_set
    assert coins[0].launcher_id in nft_set
    assert coins[0].owner_did is None
    assert coins[1].owner_did is None


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_set_did(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet.id())
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    await time_out_assert(30, did_wallet.get_confirmed_balance, 1)

    # Create a NFT without DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "did_id": "",
        }
    )
    sb = await make_new_block_with(resp, full_node_api, ph)
    # ensure hints are generated
    assert compute_memos(sb)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [{"wallet_id": nft_wallet_0_id}], lambda x: len(x["nft_list"]) > 0
    )
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    nft_coin_id = coins[0].nft_coin_id

    # Test set None -> DID1
    did_wallet1: DIDWallet = await DIDWallet.create_new_did_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, uint64(1)
    )
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet1.id())

    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(30, did_wallet1.get_spendable_balance, 1)
    resp = await api_0.nft_set_nft_did(
        dict(wallet_id=nft_wallet_0_id, did_id=hmr_did_id, nft_coin_id=nft_coin_id.hex())
    )
    await make_new_block_with(resp, full_node_api, ph)
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_by_did, [dict(did_id=hmr_did_id)], lambda x: x.get("wallet_id", 0) > 0
    )

    nft_wallet_1_id = coins_response.get("wallet_id")
    assert nft_wallet_1_id
    resp = await wait_rpc_state_condition(
        30,
        api_0.nft_get_nfts,
        [dict(wallet_id=nft_wallet_1_id)],
        lambda x: len(x["nft_list"]) > 0 and x["nft_list"][0].owner_did,
    )
    assert len(await wallet_node_0.wallet_state_manager.wallets[nft_wallet_0_id].get_current_nfts()) == 0

    coins = resp["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did.hex() == hex_did_id
    nft_coin_id = coins[0].nft_coin_id

    resp = await api_0.nft_get_info(dict(coin_id=nft_coin_id.hex(), latest=True))
    assert resp["success"]
    assert coins[0] == resp["nft_info"]

    # Test set DID1 -> DID2
    hex_did_id = did_wallet1.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(wallet_node_0.config))
    resp = await api_0.nft_set_nft_did(
        dict(wallet_id=nft_wallet_1_id, did_id=hmr_did_id, nft_coin_id=nft_coin_id.hex())
    )

    await make_new_block_with(resp, full_node_api, ph)
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_by_did, [dict(did_id=hmr_did_id)], lambda x: x.get("wallet_id") is not None
    )

    nft_wallet_2_id = coins_response.get("wallet_id")
    assert nft_wallet_2_id
    await time_out_assert(30, len, 6, wallet_node_0.wallet_state_manager.wallets)

    # Check NFT DID
    resp = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_2_id)], lambda x: len(x["nft_list"]) > 0
    )
    assert resp.get("success")
    coins = resp["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did.hex() == hex_did_id
    nft_coin_id = coins[0].nft_coin_id
    resp = await api_0.nft_get_info(dict(coin_id=nft_coin_id.hex(), latest=True))
    assert resp["success"]
    assert coins[0] == resp["nft_info"]
    # Test set DID2 -> None
    resp = await api_0.nft_set_nft_did(dict(wallet_id=nft_wallet_2_id, nft_coin_id=nft_coin_id.hex()))
    await make_new_block_with(resp, full_node_api, ph)

    # Check NFT DID
    resp = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: x["nft_list"]
    )
    coins = resp["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    assert nft_wallet_2_id in wallet_node_0.wallet_state_manager.wallets.keys()
    nft_coin_id = coins[0].nft_coin_id
    resp = await api_0.nft_get_info(dict(coin_id=nft_coin_id.hex(), latest=True))
    assert resp["success"]
    assert coins[0] == resp["nft_info"]


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_set_nft_status(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    # Create a NFT without DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]

    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await make_new_block_with(resp, full_node_api, ph)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: len(x["nft_list"]) > 0
    )
    assert coins_response["nft_list"], isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    assert not coins[0].pending_transaction
    nft_coin_id = coins[0].nft_coin_id
    # Set status
    resp = await api_0.nft_set_nft_status(
        dict(wallet_id=nft_wallet_0_id, coin_id=nft_coin_id.hex(), in_transaction=True)
    )
    assert resp.get("success")
    coins_response = await api_0.nft_get_nfts(dict(wallet_id=nft_wallet_0_id))
    assert coins_response["nft_list"], isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert coins[0].pending_transaction


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_nft_sign_message(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 5
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    api_0 = WalletRpcApi(wallet_node_0)
    ph = await wallet_0.get_new_puzzlehash()

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

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks - 1)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    res = await api_0.create_new_wallet(dict(wallet_type="nft_wallet", name="NFT WALLET 1"))
    assert isinstance(res, dict)
    assert res.get("success")
    nft_wallet_0_id = res["wallet_id"]

    # Create a NFT without DID
    resp = await api_0.nft_mint_nft(
        {
            "wallet_id": nft_wallet_0_id,
            "hash": "0xD4584AD463139FA8C0D9F68F4B59F185",
            "uris": ["https://www.chia.net/img/branding/chia-logo.svg"],
            "mu": ["https://www.chia.net/img/branding/chia-logo.svg"],
        }
    )
    assert resp.get("success")
    sb = resp["spend_bundle"]

    # ensure hints are generated
    assert compute_memos(sb)
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await make_new_block_with(resp, full_node_api, ph)

    # Check DID NFT
    coins_response = await wait_rpc_state_condition(
        30, api_0.nft_get_nfts, [dict(wallet_id=nft_wallet_0_id)], lambda x: len(x["nft_list"]) > 0
    )
    assert coins_response["nft_list"], isinstance(coins_response, dict)
    assert coins_response.get("success")
    coins = coins_response["nft_list"]
    assert len(coins) == 1
    assert coins[0].owner_did is None
    assert not coins[0].pending_transaction
    # Test general string
    message = "Hello World"
    response = await api_0.sign_message_by_id(
        {"id": encode_puzzle_hash(coins[0].launcher_id, AddressType.NFT.value), "message": message}
    )
    puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
        puzzle.get_tree_hash(),
        G2Element.from_bytes(bytes.fromhex(response["signature"])),
    )
    # Test hex string
    message = "0123456789ABCDEF"
    response = await api_0.sign_message_by_id(
        {"id": encode_puzzle_hash(coins[0].launcher_id, AddressType.NFT.value), "message": message, "is_hex": True}
    )
    puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
        puzzle.get_tree_hash(),
        G2Element.from_bytes(bytes.fromhex(response["signature"])),
    )
