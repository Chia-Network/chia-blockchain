from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional
from unittest.mock import MagicMock

import pytest
from aiosqlite import Error as AIOSqliteError
from chia_rs import confirm_not_included_already_hashed
from colorlog import getLogger

from chia._tests.connection_utils import disconnect_all, disconnect_all_and_reconnect
from chia._tests.util.blockchain_mock import BlockchainMock
from chia._tests.util.misc import add_blocks_in_batches, wallet_height_at_least
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert, time_out_assert_not_none
from chia._tests.weight_proof.test_weight_proof import load_blocks_dont_validate
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.protocols.wallet_protocol import (
    CoinState,
    RequestAdditions,
    RespondAdditions,
    RespondBlockHeaders,
    SendTransaction,
)
from chia.server.outbound_message import Message, make_msg
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.payment import Payment
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.util.wallet_types import WalletIdentifier
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.wallet_weight_proof_handler import get_wp_fork_point


async def get_tx_count(wsm: WalletStateManager, wallet_id: int) -> int:
    txs = await wsm.get_all_transactions(wallet_id)
    return len(txs)


async def get_nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


log = getLogger(__name__)


pytestmark = pytest.mark.standard_block_tools


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_request_block_headers(
    simulator_and_wallet: OldSimulatorsAndWallets, default_400_blocks: List[FullBlock]
) -> None:
    # Tests the edge case of receiving funds right before the recent blocks  in weight proof
    [full_node_api], [(wallet_node, _)], bt = simulator_and_wallet

    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    await add_blocks_in_batches(default_400_blocks[:100], full_node_api.full_node)

    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(10), uint32(15), False))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.respond_block_headers.value
    res_block_headers = RespondBlockHeaders.from_bytes(msg.data)
    bh = res_block_headers.header_blocks
    assert len(bh) == 6
    assert [x.reward_chain_block.height for x in default_400_blocks[10:16]] == [x.reward_chain_block.height for x in bh]
    assert [x.foliage for x in default_400_blocks[10:16]] == [x.foliage for x in bh]
    assert [x.transactions_filter for x in bh] == [b"\x00"] * 6

    num_blocks = 20
    new_blocks = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks, pool_reward_puzzle_hash=ph)
    await add_blocks_in_batches(new_blocks, full_node_api.full_node)
    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(110), uint32(115), True))
    assert msg is not None
    res_block_headers = RespondBlockHeaders.from_bytes(msg.data)
    bh = res_block_headers.header_blocks
    assert len(bh) == 6


# @pytest.mark.parametrize(
#     "test_case",
#     [(1_000_000, 10_000_010, False, ProtocolMessageTypes.reject_block_headers)],
#     [(80, 99, False, ProtocolMessageTypes.respond_block_headers)],
#     [(10, 8, False, None)],
# )
@pytest.mark.anyio
async def test_request_block_headers_rejected(
    simulator_and_wallet: OldSimulatorsAndWallets, default_400_blocks: List[FullBlock]
) -> None:
    # Tests the edge case of receiving funds right before the recent blocks  in weight proof
    [full_node_api], _, _ = simulator_and_wallet

    # start_height, end_height, return_filter, expected_res = test_case

    msg = await full_node_api.request_block_headers(
        wallet_protocol.RequestBlockHeaders(uint32(1_000_000), uint32(1_000_010), False)
    )
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value

    await add_blocks_in_batches(default_400_blocks[:150], full_node_api.full_node)
    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(80), uint32(99), False))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.respond_block_headers.value
    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(10), uint32(8), False))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value

    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(10), uint32(8), True))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value

    # test for 128 blocks to fetch at once limit
    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(10), uint32(140), True))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value

    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(90), uint32(160), False))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value
    msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(uint32(90), uint32(160), True))
    assert msg is not None
    assert msg.type == ProtocolMessageTypes.reject_block_headers.value


@pytest.mark.parametrize(
    "two_wallet_nodes",
    [dict(disable_capabilities=[Capability.BLOCK_HEADERS]), dict(disable_capabilities=[Capability.BASE])],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_basic_sync_wallet(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    use_delta_sync: bool,
) -> None:
    [full_node_api], wallets, bt = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    await add_blocks_in_batches(default_400_blocks, full_node)
    for wallet_node, wallet_server in wallets:
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    for wallet_node, wallet_server in wallets:
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

    # Tests a reorg with the wallet
    num_blocks = 30
    blocks_reorg = bt.get_consecutive_blocks(num_blocks - 1, block_list_input=default_400_blocks[:-5])
    blocks_reorg = bt.get_consecutive_blocks(1, blocks_reorg, guarantee_transaction_block=True, current_time=True)

    await add_blocks_in_batches(blocks_reorg[1:], full_node, blocks_reorg[0].header_hash)

    for wallet_node, wallet_server in wallets:
        await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

    for wallet_node, wallet_server in wallets:
        await time_out_assert(
            100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) + num_blocks - 5 - 1
        )
        await time_out_assert(20, wallet_node.wallet_state_manager.synced)
        await disconnect_all(wallet_server)
        assert not (await wallet_node.wallet_state_manager.synced())


@pytest.mark.parametrize(
    "two_wallet_nodes",
    [dict(disable_capabilities=[Capability.BLOCK_HEADERS]), dict(disable_capabilities=[Capability.BASE])],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_almost_recent(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    blockchain_constants: ConsensusConstants,
    use_delta_sync: bool,
) -> None:
    # Tests the edge case of receiving funds right before the recent blocks  in weight proof
    [full_node_api], wallets, bt = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    base_num_blocks = 400
    await add_blocks_in_batches(default_400_blocks, full_node)

    all_blocks = default_400_blocks
    both_phs = []
    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        both_phs.append(await wallet.get_new_puzzlehash())

    for i in range(20):
        # Tests a reorg with the wallet
        ph = both_phs[i % 2]
        all_blocks = bt.get_consecutive_blocks(1, block_list_input=all_blocks, pool_reward_puzzle_hash=ph)
        await full_node.add_block(all_blocks[-1])

    new_blocks = bt.get_consecutive_blocks(
        blockchain_constants.WEIGHT_PROOF_RECENT_BLOCKS + 10, block_list_input=all_blocks
    )

    await add_blocks_in_batches(
        new_blocks[base_num_blocks + 20 :], full_node, new_blocks[base_num_blocks + 19].header_hash
    )

    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await time_out_assert(30, wallet.get_confirmed_balance, 10 * calculate_pool_reward(uint32(1000)))


@pytest.mark.anyio
async def test_backtrack_sync_wallet(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    use_delta_sync: bool,
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    for block in default_400_blocks[:20]:
        await full_node_api.full_node.add_block(block)

    for wallet_node, wallet_server in wallets:
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    for wallet_node, wallet_server in wallets:
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, 19)


# Tests a reorg with the wallet
@pytest.mark.anyio
async def test_short_batch_sync_wallet(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    use_delta_sync: bool,
) -> None:
    [full_node_api], wallets, _ = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    await add_blocks_in_batches(default_400_blocks[:200], full_node)

    for wallet_node, wallet_server in wallets:
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    for wallet_node, wallet_server in wallets:
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, 199)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_long_sync_wallet(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_1000_blocks: List[FullBlock],
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    use_delta_sync: bool,
) -> None:
    [full_node_api], wallets, bt = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    await add_blocks_in_batches(default_400_blocks, full_node)

    for wallet_node, wallet_server in wallets:
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    for wallet_node, wallet_server in wallets:
        await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

    # Tests a long reorg
    await add_blocks_in_batches(default_1000_blocks, full_node)

    for wallet_node, wallet_server in wallets:
        await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

        log.info(f"wallet node height is {await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()}")
        await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) - 1)

        await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

    # Tests a short reorg
    num_blocks = 30
    blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_1000_blocks[:-5])

    block_record = await full_node.blockchain.get_block_record_from_db(blocks_reorg[-num_blocks - 10].header_hash)
    sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
        full_node.constants, True, block_record, full_node.blockchain
    )
    await full_node.add_block_batch(
        blocks_reorg[-num_blocks - 10 : -1],
        PeerInfo("0.0.0.0", 0),
        None,
        current_ssi=sub_slot_iters,
        current_difficulty=difficulty,
    )
    await full_node.add_block(blocks_reorg[-1])

    for wallet_node, wallet_server in wallets:
        await time_out_assert(
            120, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) + num_blocks - 5 - 1
        )


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_wallet_reorg_sync(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    use_delta_sync: bool,
) -> None:
    num_blocks = 5
    [full_node_api], wallets, bt = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    wallets[0][0].config["use_delta_sync"] = use_delta_sync

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}
    wallets[1][0].config["use_delta_sync"] = use_delta_sync

    phs = []
    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        phs.append(await wallet.get_new_puzzlehash())
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    # Insert 400 blocks
    await full_node.add_block(default_400_blocks[0])
    await add_blocks_in_batches(default_400_blocks[1:], full_node)
    # Farm few more with reward
    for _ in range(num_blocks - 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(phs[0]))

    for _ in range(num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(phs[1]))

    # Confirm we have the funds
    funds = sum(
        calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
    )

    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        await time_out_assert(60, wallet.get_confirmed_balance, funds)
        await time_out_assert(60, get_tx_count, 2 * (num_blocks - 1), wallet_node.wallet_state_manager, 1)

    # Reorg blocks that carry reward
    num_blocks = 30
    blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])

    for block in blocks_reorg[-30:]:
        await full_node.add_block(block)

    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        await time_out_assert(60, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
        await time_out_assert(60, wallet.get_confirmed_balance, 0)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_wallet_reorg_get_coinbase(
    two_wallet_nodes: OldSimulatorsAndWallets, default_400_blocks: List[FullBlock], self_hostname: str
) -> None:
    [full_node_api], wallets, bt = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}

    for wallet_node, wallet_server in wallets:
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    # Insert 400 blocks
    await add_blocks_in_batches(default_400_blocks, full_node)

    # Reorg blocks that carry reward
    num_blocks_reorg = 30
    blocks_reorg = bt.get_consecutive_blocks(num_blocks_reorg, block_list_input=default_400_blocks[:-5])
    await add_blocks_in_batches(blocks_reorg[:-6], full_node)

    await full_node.add_block(blocks_reorg[-6])

    for wallet_node, wallet_server in wallets:
        await time_out_assert(30, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=30)

    num_blocks_reorg_1 = 40
    all_blocks_reorg_2 = blocks_reorg[:-30]
    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        all_blocks_reorg_2 = bt.get_consecutive_blocks(
            1, pool_reward_puzzle_hash=ph, farmer_reward_puzzle_hash=ph, block_list_input=all_blocks_reorg_2
        )
    blocks_reorg_2 = bt.get_consecutive_blocks(num_blocks_reorg_1, block_list_input=all_blocks_reorg_2)
    block_record = await full_node.blockchain.get_block_record_from_db(blocks_reorg_2[-45].header_hash)
    sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
        full_node.constants, True, block_record, full_node.blockchain
    )
    await full_node.add_block_batch(
        blocks_reorg_2[-44:],
        PeerInfo("0.0.0.0", 0),
        None,
        current_ssi=sub_slot_iters,
        current_difficulty=difficulty,
    )

    for wallet_node, wallet_server in wallets:
        await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

    # Confirm we have the funds
    funds = calculate_pool_reward(uint32(len(all_blocks_reorg_2))) + calculate_base_farmer_reward(
        uint32(len(all_blocks_reorg_2))
    )

    for wallet_node, wallet_server in wallets:
        wallet = wallet_node.wallet_state_manager.main_wallet
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=60)

        await time_out_assert(20, get_tx_count, 2, wallet_node.wallet_state_manager, 1)
        await time_out_assert(20, wallet.get_confirmed_balance, funds)


@pytest.mark.anyio
async def test_request_additions_errors(simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    wallet_node, wallet_server = wallets[0]
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()

    full_node_api = full_nodes[0]
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

    for _ in range(2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
    assert last_block is not None

    # Invalid height
    with pytest.raises(ValueError):
        await full_node_api.request_additions(RequestAdditions(uint32(100), last_block.header_hash, [ph]))

    # Invalid header hash
    with pytest.raises(ValueError):
        await full_node_api.request_additions(RequestAdditions(last_block.height, std_hash(b""), [ph]))

    # No results
    fake_coin = std_hash(b"")
    assert ph != fake_coin
    res1 = await full_node_api.request_additions(
        RequestAdditions(last_block.height, last_block.header_hash, [fake_coin])
    )
    assert res1 is not None
    response = RespondAdditions.from_bytes(res1.data)
    assert response.height == last_block.height
    assert response.header_hash == last_block.header_hash
    assert response.proofs is not None
    assert len(response.proofs) == 1
    assert len(response.coins) == 1
    full_block = await full_node_api.full_node.block_store.get_full_block(last_block.header_hash)
    assert full_block is not None
    assert full_block.foliage_transaction_block is not None
    root = full_block.foliage_transaction_block.additions_root
    assert confirm_not_included_already_hashed(root, response.proofs[0][0], response.proofs[0][1])
    # proofs is a tuple of (puzzlehash, proof, proof_2)
    # proof is a proof of inclusion (or exclusion) of that puzzlehash
    # proof_2 is a proof of all the coins with that puzzlehash
    # all coin names are concatenated and hashed into one entry in the merkle set for proof_2
    # the response contains the list of coins so you can check the proof_2

    assert response.proofs[0][0] == std_hash(b"")
    assert response.proofs[0][1] is not None
    assert response.proofs[0][2] is None


@pytest.mark.anyio
async def test_request_additions_success(simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    wallet_node, wallet_server = wallets[0]
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()

    full_node_api = full_nodes[0]
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

    for _ in range(2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    payees: List[Payment] = []
    for i in range(10):
        payee_ph = await wallet.get_new_puzzlehash()
        payees.append(Payment(payee_ph, uint64(i + 100)))
        payees.append(Payment(payee_ph, uint64(i + 200)))

    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    last_block = full_node_api.full_node.blockchain.get_peak()
    assert last_block is not None
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    res2 = await full_node_api.request_additions(
        RequestAdditions(last_block.height, None, [payees[0].puzzle_hash, payees[2].puzzle_hash, std_hash(b"1")])
    )

    assert res2 is not None
    response = RespondAdditions.from_bytes(res2.data)
    assert response.height == last_block.height
    assert response.header_hash == last_block.header_hash
    assert response.proofs is not None
    assert len(response.proofs) == 3

    # First two PHs are included
    for i in range(2):
        assert response.proofs[i][0] in {payees[j].puzzle_hash for j in (0, 2)}
        assert response.proofs[i][1] is not None
        assert response.proofs[i][2] is not None

    # Third PH is not included
    assert response.proofs[2][2] is None

    coin_list_dict = {p: coin_list for p, coin_list in response.coins}

    assert len(coin_list_dict) == 3
    for p, coin_list in coin_list_dict.items():
        if p == std_hash(b"1"):
            # this is the one that is not included
            assert len(coin_list) == 0
        else:
            for coin in coin_list:
                assert coin.puzzle_hash == p
            # The other ones are included
            assert len(coin_list) == 2

    # None for puzzle hashes returns all coins and no proofs
    res3 = await full_node_api.request_additions(RequestAdditions(last_block.height, last_block.header_hash, None))

    assert res3 is not None
    response = RespondAdditions.from_bytes(res3.data)
    assert response.height == last_block.height
    assert response.header_hash == last_block.header_hash
    assert response.proofs is None
    assert len(response.coins) == 12
    assert sum(len(c_list) for _, c_list in response.coins) == 24

    # [] for puzzle hashes returns nothing
    res4 = await full_node_api.request_additions(RequestAdditions(last_block.height, last_block.header_hash, []))
    assert res4 is not None
    response = RespondAdditions.from_bytes(res4.data)
    assert response.proofs == []
    assert len(response.coins) == 0


@pytest.mark.anyio
async def test_get_wp_fork_point(
    default_10000_blocks: List[FullBlock], blockchain_constants: ConsensusConstants
) -> None:
    blocks = default_10000_blocks
    header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks, blockchain_constants)
    wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries))
    wp1 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9_000)]].header_hash)
    assert wp1 is not None
    wp2 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9_030)]].header_hash)
    assert wp2 is not None
    wp3 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(7_500)]].header_hash)
    assert wp3 is not None
    wp4 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(8_700)]].header_hash)
    assert wp4 is not None
    wp5 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9_700)]].header_hash)
    assert wp5 is not None
    wp6 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9_010)]].header_hash)
    assert wp6 is not None
    fork12 = get_wp_fork_point(blockchain_constants, wp1, wp2)
    fork13 = get_wp_fork_point(blockchain_constants, wp3, wp1)
    fork14 = get_wp_fork_point(blockchain_constants, wp4, wp1)
    fork23 = get_wp_fork_point(blockchain_constants, wp3, wp2)
    fork24 = get_wp_fork_point(blockchain_constants, wp4, wp2)
    fork34 = get_wp_fork_point(blockchain_constants, wp3, wp4)
    fork45 = get_wp_fork_point(blockchain_constants, wp4, wp5)
    fork16 = get_wp_fork_point(blockchain_constants, wp1, wp6)

    # overlap between recent chain in wps, fork point is the tip of the shorter wp
    assert fork12 == wp1.recent_chain_data[-1].height
    assert fork16 == wp1.recent_chain_data[-1].height

    # if there is an overlap between the recent chains we can find the exact fork point
    # if not we should get the latest block with a sub epoch summary that exists in both wp's
    # this can happen in fork24 and fork14 since they are not very far and also not very close

    if wp2.recent_chain_data[0].height > wp4.recent_chain_data[-1].height:
        assert fork24 in summaries.keys()
        assert fork24 < wp4.recent_chain_data[-1].height
    else:
        assert fork24 == wp4.recent_chain_data[-1].height

    if wp1.recent_chain_data[0].height > wp4.recent_chain_data[-1].height:
        assert fork14 in summaries.keys()
        assert fork14 < wp4.recent_chain_data[-1].height
    else:
        assert fork14 == wp4.recent_chain_data[-1].height

    # no overlap between recent chain in wps, fork point
    # is the latest block with a sub epoch summary that exists in both wp's
    assert fork13 in summaries.keys()
    assert fork13 < wp3.recent_chain_data[-1].height
    assert fork23 in summaries.keys()
    assert fork23 < wp3.recent_chain_data[-1].height
    assert fork34 in summaries.keys()
    assert fork23 < wp3.recent_chain_data[-1].height
    assert fork45 in summaries.keys()
    assert fork45 < wp4.recent_chain_data[-1].height


"""
This tests that a wallet filters out the dust properly.
It runs in seven phases:
1. Create a single dust coin.
    Typically (though there are edge cases), this coin will not be filtered.
2. Create dust coins until the filter threshold has been reached.
    At this point, none of the dust should be filtered.
3. Create 10 coins that are exactly the size of the filter threshold.
    These should not be filtered because they are not dust.
4. Create one more dust coin. This coin should be filtered.
5. Create 5 coins below the threshold and 5 at or above.
    Those below the threshold should get filtered, and those above should not.
6. Clear all coins from the dust wallet.
    Send to the dust wallet "spam_filter_after_n_txs" coins that are equal in value to "xch_spam_amount".
    Send 1 mojo from the dust wallet. The dust wallet should receive a change coin valued at "xch_spam_amount-1".
7: Create an NFT wallet for the farmer wallet, and generate an NFT in that wallet.
    Create an NFT wallet for the dust wallet.
    Send the NFT to the dust wallet. The NFT should not be filtered.
"""


@pytest.mark.anyio
@pytest.mark.parametrize(
    "spam_filter_after_n_txs, xch_spam_amount, dust_value",
    [
        # In the following tests, the filter is run right away:
        (0, 1, 1),  # nothing is filtered
        # In the following tests, 1 coin will be created in part 1, and 9 in part 2:
        (10, 10_000_000_000, 1),  # everything is dust
        (10, 10_000_000_000, 10_000_000_000),  # max dust threshold, dust is same size so not filtered
        # Test with more coins
        (105, 1_000_000, 1),  # default filter level (1m mojos), default dust size (1)
    ],
)
async def test_dusted_wallet(
    self_hostname: str,
    two_wallet_nodes_custom_spam_filtering: OldSimulatorsAndWallets,
    spam_filter_after_n_txs: int,
    xch_spam_amount: int,
    dust_value: int,
    use_delta_sync: bool,
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes_custom_spam_filtering

    farm_wallet_node, farm_wallet_server = wallets[0]
    farm_wallet_node.config["use_delta_sync"] = use_delta_sync
    dust_wallet_node, dust_wallet_server = wallets[1]
    dust_wallet_node.config["use_delta_sync"] = use_delta_sync

    # Create two wallets, one for farming (not used for testing), and one for testing dust.
    farm_wallet = farm_wallet_node.wallet_state_manager.main_wallet
    dust_wallet = dust_wallet_node.wallet_state_manager.main_wallet
    ph = await farm_wallet.get_new_puzzlehash()

    full_node_api = full_nodes[0]

    # It's also possible to obtain the current settings for spam_filter_after_n_txs and xch_spam_amount
    # spam_filter_after_n_txs = wallets[0][0].config["spam_filter_after_n_txs"]
    # xch_spam_amount = wallets[0][0].config["xch_spam_amount"]
    # dust_value=1

    # Verify legal values for the settings to be tested
    # If spam_filter_after_n_txs is greater than 250, this test will take a long time to run.
    # Current max value for xch_spam_amount is 0.01 XCH.
    # If needed, this could be increased but we would need to farm more blocks.
    # The max dust_value could be increased, but would require farming more blocks.
    assert spam_filter_after_n_txs >= 0
    assert spam_filter_after_n_txs <= 250
    assert xch_spam_amount >= 1
    assert xch_spam_amount <= 10_000_000_000
    assert dust_value >= 1
    assert dust_value <= 10_000_000_000

    # start both clients
    await farm_wallet_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)
    await dust_wallet_server.start_client(PeerInfo(self_hostname, full_node_api.full_node.server.get_port()), None)

    # Farm two blocks
    for _ in range(2):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    # sync both nodes
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Part 1: create a single dust coin
    payees: List[Payment] = []
    payee_ph = await dust_wallet.get_new_puzzlehash()
    payees.append(Payment(payee_ph, uint64(dust_value)))

    # construct and send tx
    async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # The dust is only filtered at this point if spam_filter_after_n_txs is 0 and xch_spam_amount is > dust_value.
    if spam_filter_after_n_txs > 0:
        dust_coins = 1
        large_dust_coins = 0
        large_dust_balance = 0
    elif xch_spam_amount <= dust_value:
        dust_coins = 0
        large_dust_coins = 1
        large_dust_balance = dust_value
    else:
        dust_coins = 0
        large_dust_coins = 0
        large_dust_balance = 0

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    log.info(f"all_unspent is {all_unspent}")
    small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
    balance = await dust_wallet.get_confirmed_balance()
    async with dust_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        num_coins = len(await dust_wallet.select_coins(uint64(balance), action_scope))

    log.info(f"Small coin count is {small_unspent_count}")
    log.info(f"Wallet balance is {balance}")
    log.info(f"Number of coins is {num_coins}")

    log.info(f"spam_filter_after_n_txs {spam_filter_after_n_txs}")
    log.info(f"xch_spam_amount {xch_spam_amount}")
    log.info(f"dust_value {dust_value}")

    # Verify balance and number of coins not filtered.
    assert balance == dust_coins * dust_value + large_dust_balance
    assert num_coins == dust_coins + large_dust_coins

    # Part 2: Create dust coins until the filter threshold has been reached.
    # Nothing should be filtered yet (unless spam_filter_after_n_txs is 0).
    payees = []

    # Determine how much dust to create, recalling that there already is one dust coin.
    new_dust = spam_filter_after_n_txs - 1
    dust_remaining = new_dust

    while dust_remaining > 0:
        payee_ph = await dust_wallet.get_new_puzzlehash()
        payees.append(Payment(payee_ph, uint64(dust_value)))

        # After every 100 (at most) coins added, push the tx and advance the chain
        # This greatly speeds up the overall process
        if dust_remaining % 100 == 0 and dust_remaining != new_dust:
            # construct and send tx
            async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
            [tx] = action_scope.side_effects.transactions
            assert tx.spend_bundle is not None
            await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

            # advance the chain and sync both wallets
            await full_node_api.wait_transaction_records_entered_mempool([tx])
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
            # reset payees
            payees = []

        dust_remaining -= 1

    # Only need to create tx if there was new dust to be added
    if new_dust >= 1:
        # construct and send tx
        async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.wait_transaction_records_entered_mempool([tx])
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
    balance = await dust_wallet.get_confirmed_balance()
    # Selecting coins by using the wallet's coin selection algorithm won't work for large
    # numbers of coins, so we'll use the state manager for the rest of the test
    spendable_coins = await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1)
    num_coins = len(spendable_coins)

    log.info(f"Small coin count is {small_unspent_count}")
    log.info(f"Wallet balance is {balance}")
    log.info(f"Number of coins is {num_coins}")

    # obtain the total expected coins (new_dust could be negative)
    if new_dust > 0:
        dust_coins += new_dust

    # Make sure the number of coins matches the expected number.
    # At this point, nothing should be getting filtered unless spam_filter_after_n_txs is 0.
    assert dust_coins == spam_filter_after_n_txs
    assert balance == dust_coins * dust_value + large_dust_balance
    assert num_coins == dust_coins + large_dust_coins

    # Part 3: Create 10 coins that are exactly the size of the filter threshold.
    # These should not get filtered.
    large_coins = 10

    payees = []

    for _ in range(large_coins):
        payee_ph = await dust_wallet.get_new_puzzlehash()
        payees.append(Payment(payee_ph, uint64(xch_spam_amount)))

    # construct and send tx
    async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
    balance = await dust_wallet.get_confirmed_balance()
    spendable_coins = await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1)
    num_coins = len(spendable_coins)

    log.info(f"Small coin count is {small_unspent_count}")
    log.info(f"Wallet balance is {balance}")
    log.info(f"Number of coins is {num_coins}")

    large_coin_balance = large_coins * xch_spam_amount

    # Determine whether the filter should have been activated.
    # Make sure the number of coins matches the expected number.
    # At this point, nothing should be getting filtered unless spam_filter_after_n_txs is 0.
    assert dust_coins == spam_filter_after_n_txs
    assert balance == dust_coins * dust_value + large_coins * xch_spam_amount + large_dust_balance
    assert num_coins == dust_coins + large_coins + large_dust_coins

    # Part 4: Create one more dust coin to test the threshold
    payees = []

    payee_ph = await dust_wallet.get_new_puzzlehash()
    payees.append(Payment(payee_ph, uint64(dust_value)))

    # construct and send tx
    async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
    balance = await dust_wallet.get_confirmed_balance()
    spendable_coins = await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1)
    num_coins = len(spendable_coins)

    log.info(f"Small coin count is {small_unspent_count}")
    log.info(f"Wallet balance is {balance}")
    log.info(f"Number of coins is {num_coins}")

    # In the edge case where the new "dust" is larger than the threshold,
    # then it is actually a large dust coin that won't get filtered.
    if dust_value >= xch_spam_amount:
        large_dust_coins += 1
        large_dust_balance += dust_value

    assert dust_coins == spam_filter_after_n_txs
    assert balance == dust_coins * dust_value + large_coins * xch_spam_amount + large_dust_balance
    assert num_coins == dust_coins + large_dust_coins + large_coins

    # Part 5: Create 5 coins below the threshold and 5 at or above.
    # Those below the threshold should get filtered, and those above should not.
    payees = []

    for i in range(5):
        payee_ph = await dust_wallet.get_new_puzzlehash()

        # Create a large coin and add on the appropriate balance.
        payees.append(Payment(payee_ph, uint64(xch_spam_amount + i)))
        large_coins += 1
        large_coin_balance += xch_spam_amount + i

        payee_ph = await dust_wallet.get_new_puzzlehash()

        # Make sure we are always creating coins with a positive value.
        if xch_spam_amount - dust_value - i > 0:
            payees.append(Payment(payee_ph, uint64(xch_spam_amount - dust_value - i)))
        else:
            payees.append(Payment(payee_ph, uint64(dust_value)))
        # In cases where xch_spam_amount is sufficiently low,
        # the new dust should be considered a large coina and not be filtered.
        if xch_spam_amount <= dust_value:
            large_dust_coins += 1
            large_dust_balance += dust_value

    # construct and send tx
    async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
    balance = await dust_wallet.get_confirmed_balance()
    spendable_coins = await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1)
    num_coins = len(spendable_coins)

    log.info(f"Small coin count is {small_unspent_count}")
    log.info(f"Wallet balance is {balance}")
    log.info(f"Number of coins is {num_coins}")

    # The filter should have automatically been activated by now, regardless of filter value
    assert dust_coins == spam_filter_after_n_txs
    assert balance == dust_coins * dust_value + large_coin_balance + large_dust_balance
    assert num_coins == dust_coins + large_dust_coins + large_coins

    # Part 6: Clear all coins from the dust wallet.
    # Send to the dust wallet "spam_filter_after_n_txs" coins that are equal in value to "xch_spam_amount".
    # Send 1 mojo from the dust wallet. The dust wallet should receive a change coin valued at "xch_spam_amount-1".

    payee_ph = await farm_wallet.get_new_puzzlehash()
    payees = [Payment(payee_ph, uint64(balance))]

    # construct and send tx
    async with dust_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dust_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    unspent_count = len(all_unspent)
    balance = await dust_wallet.get_confirmed_balance()

    # Make sure the dust wallet is empty
    assert unspent_count == 0
    assert balance == 0

    # create the same number of dust coins as the filter
    if spam_filter_after_n_txs > 0:
        coins_remaining = spam_filter_after_n_txs
    else:
        # in the edge case, create one coin
        coins_remaining = 1

    # The size of the coin to send the dust wallet is the same as xch_spam_amount
    if xch_spam_amount > 1:
        coin_value = xch_spam_amount
    else:
        # Handle the edge case to make sure the coin is at least 2 mojos
        # This is needed to receive change
        coin_value = 2

    while coins_remaining > 0:
        payee_ph = await dust_wallet.get_new_puzzlehash()
        payees.append(Payment(payee_ph, uint64(coin_value)))

        # After every 100 (at most) coins added, push the tx and advance the chain
        # This greatly speeds up the overall process
        if coins_remaining % 100 == 0 and coins_remaining != spam_filter_after_n_txs:
            # construct and send tx
            async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
            [tx] = action_scope.side_effects.transactions
            assert tx.spend_bundle is not None
            await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))
            await full_node_api.wait_transaction_records_entered_mempool([tx])
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
            # reset payees
            payees = []

        coins_remaining -= 1

    # construct and send tx
    async with farm_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    unspent_count = len(all_unspent)
    balance = await dust_wallet.get_confirmed_balance()

    # Verify the number of coins and value
    if spam_filter_after_n_txs > 0:
        assert unspent_count == spam_filter_after_n_txs
    else:
        # in the edge case there should be 1 coin
        assert unspent_count == 1
    assert balance == unspent_count * coin_value

    # Send a 1 mojo coin from the dust wallet to the farm wallet
    payee_ph = await farm_wallet.get_new_puzzlehash()
    payees = [Payment(payee_ph, uint64(1))]

    # construct and send tx
    async with dust_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dust_wallet.generate_signed_transaction(uint64(0), ph, action_scope, primaries=payees)
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

    # advance the chain and sync both wallets
    await full_node_api.wait_transaction_records_entered_mempool([tx])
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Obtain and log important values
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    unspent_count = len(all_unspent)
    balance = await dust_wallet.get_confirmed_balance()

    # Make sure the dust wallet received a change coin worth 1 mojo less than the original coin size
    if spam_filter_after_n_txs > 0:
        assert unspent_count == spam_filter_after_n_txs
    else:
        # in the edge case there should be 1 coin
        assert unspent_count == 1
    assert balance == (unspent_count * coin_value) - 1

    # Part 7: Create NFT wallets for the farmer and dust wallets.
    #         Generate an NFT in the farmer wallet.
    #         Send the NFT to the dust wallet, which already has enough coins to trigger the dust filter.
    #         The NFT should not be filtered.

    # Start with new puzzlehashes for each wallet
    farm_ph = await farm_wallet.get_new_puzzlehash()
    dust_ph = await dust_wallet.get_new_puzzlehash()

    # Create an NFT wallet for the farmer and dust wallet
    farm_nft_wallet = await NFTWallet.create_new_nft_wallet(
        farm_wallet_node.wallet_state_manager, farm_wallet, name="FARM NFT WALLET"
    )
    dust_nft_wallet = await NFTWallet.create_new_nft_wallet(
        dust_wallet_node.wallet_state_manager, dust_wallet, name="DUST NFT WALLET"
    )

    # Create a new NFT and send it to the farmer's NFT wallet
    metadata = Program.to(
        [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", "0xD4584AD463139FA8C0D9F68F4B59F185")]
    )
    async with farm_nft_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_nft_wallet.generate_new_nft(metadata, action_scope)
    for tx in action_scope.side_effects.transactions:
        if tx.spend_bundle is not None:
            assert len(compute_memos(tx.spend_bundle)) > 0
            await time_out_assert_not_none(
                20, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle.name()
            )

    # Farm a new block
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Make sure the dust wallet has enough unspent coins in that the next coin would be filtered
    # if it were a normal dust coin (and not an NFT)
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    assert len(all_unspent) >= spam_filter_after_n_txs

    # Make sure the NFT is in the farmer's NFT wallet, and the dust NFT wallet is empty
    await time_out_assert(15, get_nft_count, 1, farm_nft_wallet)
    await time_out_assert(15, get_nft_count, 0, dust_nft_wallet)

    nft_coins = await farm_nft_wallet.get_current_nfts()
    # Send the NFT to the dust wallet
    async with farm_nft_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await farm_nft_wallet.generate_signed_transaction(
            [uint64(nft_coins[0].coin.amount)], [dust_ph], action_scope, coins={nft_coins[0].coin}
        )
    assert len(action_scope.side_effects.transactions) == 1
    txs = await farm_wallet_node.wallet_state_manager.add_pending_transactions(action_scope.side_effects.transactions)
    assert txs[0].spend_bundle is not None
    assert len(compute_memos(txs[0].spend_bundle)) > 0

    # Farm a new block.
    await full_node_api.wait_transaction_records_entered_mempool(txs)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[farm_wallet_node, dust_wallet_node], timeout=20)

    # Make sure the dust wallet has enough unspent coins in that the next coin would be filtered
    # if it were a normal dust coin (and not an NFT)
    all_unspent = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
    assert len(all_unspent) >= spam_filter_after_n_txs

    # The dust wallet should now hold the NFT. It should not be filtered
    await time_out_assert(15, get_nft_count, 0, farm_nft_wallet)
    await time_out_assert(15, get_nft_count, 1, dust_nft_wallet)


@pytest.mark.anyio
async def test_retry_store(
    two_wallet_nodes: OldSimulatorsAndWallets, self_hostname: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.full_node.server

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

    # Trusted node sync
    wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

    # Untrusted node sync
    wallets[1][0].config["trusted_peers"] = {}

    @dataclass
    class FlakinessInfo:
        coin_state_flaky: bool = True
        fetch_children_flaky: bool = True
        get_timestamp_flaky: bool = True
        db_flaky: bool = True

    def flaky_get_coin_state(
        flakiness_info: FlakinessInfo,
        func: Callable[[List[bytes32], WSChiaConnection, Optional[uint32]], Awaitable[List[CoinState]]],
    ) -> Callable[[List[bytes32], WSChiaConnection, Optional[uint32]], Awaitable[List[CoinState]]]:
        async def new_func(
            coin_names: List[bytes32], peer: WSChiaConnection, fork_height: Optional[uint32] = None
        ) -> List[CoinState]:
            if flakiness_info.coin_state_flaky:
                flakiness_info.coin_state_flaky = False
                raise PeerRequestException()
            else:
                return await func(coin_names, peer, fork_height)

        return new_func

    request_puzzle_solution_failure_tested = False

    def flaky_request_puzzle_solution(
        func: Callable[[wallet_protocol.RequestPuzzleSolution], Awaitable[Optional[Message]]]
    ) -> Callable[[wallet_protocol.RequestPuzzleSolution], Awaitable[Optional[Message]]]:
        @functools.wraps(func)
        async def new_func(request: wallet_protocol.RequestPuzzleSolution) -> Optional[Message]:
            nonlocal request_puzzle_solution_failure_tested
            if not request_puzzle_solution_failure_tested:
                request_puzzle_solution_failure_tested = True
                # This can just return None if we have `none_response` enabled.
                reject = wallet_protocol.RejectPuzzleSolution(bytes32([0] * 32), uint32(0))
                return make_msg(ProtocolMessageTypes.reject_puzzle_solution, reject)
            else:
                return await func(request)

        return new_func

    def flaky_fetch_children(
        flakiness_info: FlakinessInfo,
        func: Callable[[bytes32, WSChiaConnection, Optional[uint32]], Awaitable[List[CoinState]]],
    ) -> Callable[[bytes32, WSChiaConnection, Optional[uint32]], Awaitable[List[CoinState]]]:
        async def new_func(
            coin_name: bytes32, peer: WSChiaConnection, fork_height: Optional[uint32] = None
        ) -> List[CoinState]:
            if flakiness_info.fetch_children_flaky:
                flakiness_info.fetch_children_flaky = False
                raise PeerRequestException()
            else:
                return await func(coin_name, peer, fork_height)

        return new_func

    def flaky_get_timestamp(
        flakiness_info: FlakinessInfo, func: Callable[[uint32], Awaitable[uint64]]
    ) -> Callable[[uint32], Awaitable[uint64]]:
        async def new_func(height: uint32) -> uint64:
            if flakiness_info.get_timestamp_flaky:
                flakiness_info.get_timestamp_flaky = False
                raise PeerRequestException()
            else:
                return await func(height)

        return new_func

    def flaky_info_for_puzhash(
        flakiness_info: FlakinessInfo, func: Callable[[bytes32], Awaitable[Optional[WalletIdentifier]]]
    ) -> Callable[[bytes32], Awaitable[Optional[WalletIdentifier]]]:
        async def new_func(puzzle_hash: bytes32) -> Optional[WalletIdentifier]:
            if flakiness_info.db_flaky:
                flakiness_info.db_flaky = False
                raise AIOSqliteError()
            else:
                return await func(puzzle_hash)

        return new_func

    with monkeypatch.context() as m:
        m.setattr(
            full_node_api,
            "request_puzzle_solution",
            flaky_request_puzzle_solution(full_node_api.request_puzzle_solution),
        )

        for wallet_node, wallet_server in wallets:
            wallet_node.coin_state_retry_seconds = 1
            request_puzzle_solution_failure_tested = False
            flakiness_info = FlakinessInfo()
            m.setattr(wallet_node, "get_coin_state", flaky_get_coin_state(flakiness_info, wallet_node.get_coin_state))
            m.setattr(wallet_node, "fetch_children", flaky_fetch_children(flakiness_info, wallet_node.fetch_children))
            m.setattr(
                wallet_node,
                "get_timestamp_for_height",
                flaky_get_timestamp(flakiness_info, wallet_node.get_timestamp_for_height),
            )
            m.setattr(
                wallet_node.wallet_state_manager.puzzle_store,
                "get_wallet_identifier_for_puzzle_hash",
                flaky_info_for_puzhash(
                    flakiness_info, wallet_node.wallet_state_manager.puzzle_store.get_wallet_identifier_for_puzzle_hash
                ),
            )

            await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

            wallet = wallet_node.wallet_state_manager.main_wallet
            ph = await wallet.get_new_puzzlehash()
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

            async def retry_store_empty() -> bool:
                return len(await wallet_node.wallet_state_manager.retry_store.get_all_states_to_retry()) == 0

            async def assert_coin_state_retry() -> None:
                # Wait for retry coin states to show up
                await time_out_assert(15, retry_store_empty, False)
                # And become retried/removed
                await time_out_assert(30, retry_store_empty, True)

            await assert_coin_state_retry()

            async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                await wallet.generate_signed_transaction(
                    uint64(1_000_000_000_000), bytes32([0] * 32), action_scope, memos=[ph]
                )
            [tx] = action_scope.side_effects.transactions
            await time_out_assert(30, wallet.get_confirmed_balance, 2_000_000_000_000)

            async def tx_in_mempool() -> bool:
                return full_node_api.full_node.mempool_manager.get_spendbundle(tx.name) is not None

            await time_out_assert(15, tx_in_mempool)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

            await assert_coin_state_retry()

            assert not flakiness_info.coin_state_flaky
            assert request_puzzle_solution_failure_tested
            assert not flakiness_info.fetch_children_flaky
            assert not flakiness_info.get_timestamp_flaky
            assert not flakiness_info.db_flaky
            await time_out_assert(30, wallet.get_confirmed_balance, 1_000_000_000_000)


# TODO: fix this test
@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
@pytest.mark.skip("the test fails with 'wallet_state_manager not assigned'. This test doesn't work, skip it for now")
async def test_bad_peak_mismatch(
    two_wallet_nodes: OldSimulatorsAndWallets,
    default_1000_blocks: List[FullBlock],
    self_hostname: str,
    blockchain_constants: ConsensusConstants,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [full_node_api], [(wallet_node, wallet_server), _], _ = two_wallet_nodes
    full_node = full_node_api.full_node
    full_node_server = full_node.server
    blocks = default_1000_blocks
    header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks, blockchain_constants)
    wpf = WeightProofHandler(blockchain_constants, BlockchainMock(sub_blocks, header_cache, height_to_hash, summaries))

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await add_blocks_in_batches(blocks, full_node)

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    # make wp for lower height
    wp = await wpf.get_proof_of_weight(height_to_hash[uint32(800)])
    assert wp is not None
    # create the node respond with the lighter proof
    wp_msg = make_msg(
        ProtocolMessageTypes.respond_proof_of_weight,
        full_node_protocol.RespondProofOfWeight(wp, wp.recent_chain_data[-1].header_hash),
    )
    with monkeypatch.context() as m:
        f: asyncio.Future[Optional[Message]] = asyncio.Future()
        f.set_result(wp_msg)
        m.setattr(full_node_api, "request_proof_of_weight", MagicMock(return_value=f))

        # create the node respond with the lighter header block
        header_block_msg = make_msg(
            ProtocolMessageTypes.respond_block_header,
            wallet_protocol.RespondBlockHeader(wp.recent_chain_data[-1]),
        )
        f2: asyncio.Future[Optional[Message]] = asyncio.Future()
        f2.set_result(header_block_msg)
        m.setattr(full_node_api, "request_block_header", MagicMock(return_value=f2))

        # create new fake peak msg
        fake_peak_height = uint32(11_000)
        fake_peak_weight = uint128(1_000_000_000)
        msg = wallet_protocol.NewPeakWallet(
            blocks[-1].header_hash, fake_peak_height, fake_peak_weight, uint32(max(blocks[-1].height - 1, uint32(0)))
        )
        await asyncio.sleep(3)
        await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await wallet_node.new_peak_wallet(msg, wallet_server.all_connections.popitem()[1])
        await asyncio.sleep(3)
        peak = await wallet_node.wallet_state_manager.blockchain.get_peak_block()
        assert peak is not None
        assert peak.height != fake_peak_height


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_long_sync_untrusted_break(
    setup_two_nodes_and_wallet: OldSimulatorsAndWallets,
    default_1000_blocks: List[FullBlock],
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    use_delta_sync: bool,
) -> None:
    [trusted_full_node_api, untrusted_full_node_api], [(wallet_node, wallet_server)], _ = setup_two_nodes_and_wallet
    trusted_full_node_server = trusted_full_node_api.full_node.server
    untrusted_full_node_server = untrusted_full_node_api.full_node.server
    wallet_node.config["trusted_peers"] = {trusted_full_node_server.node_id.hex(): None}
    wallet_node.config["use_delta_sync"] = use_delta_sync

    sync_canceled = False

    async def register_interest_in_puzzle_hash() -> None:
        nonlocal sync_canceled
        # Just sleep a long time here to simulate a long-running untrusted sync
        try:
            await asyncio.sleep(120)
        except Exception:
            sync_canceled = True
            raise

    def wallet_syncing() -> bool:
        return wallet_node.wallet_state_manager.sync_mode

    def check_sync_canceled() -> bool:
        return sync_canceled

    def synced_to_trusted() -> bool:
        return trusted_full_node_server.node_id in wallet_node.synced_peers

    def only_trusted_peer() -> bool:
        trusted_peers = sum(wallet_node.is_trusted(peer) for peer in wallet_server.all_connections.values())
        untrusted_peers = sum(not wallet_node.is_trusted(peer) for peer in wallet_server.all_connections.values())
        return trusted_peers == 1 and untrusted_peers == 0

    await add_blocks_in_batches(default_400_blocks, trusted_full_node_api.full_node)

    await add_blocks_in_batches(default_1000_blocks[:400], untrusted_full_node_api.full_node)

    with monkeypatch.context() as m:
        m.setattr(
            untrusted_full_node_api,
            "register_interest_in_puzzle_hash",
            MagicMock(return_value=register_interest_in_puzzle_hash()),
        )

        # Connect to the untrusted peer and wait until the long sync started
        await wallet_server.start_client(PeerInfo(self_hostname, untrusted_full_node_server.get_port()), None)
        await time_out_assert(30, wallet_syncing)
        with caplog.at_level(logging.INFO):
            # Connect to the trusted peer and make sure the running untrusted long sync gets interrupted via disconnect
            await wallet_server.start_client(PeerInfo(self_hostname, trusted_full_node_server.get_port()), None)
            await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)
            assert time_out_assert(10, synced_to_trusted)
            assert untrusted_full_node_server.node_id not in wallet_node.synced_peers
            assert "Connected to a synced trusted peer, disconnecting from all untrusted nodes." in caplog.text

        # Make sure the sync was interrupted
        assert time_out_assert(30, check_sync_canceled)
        # And that we only have a trusted peer left
        assert time_out_assert(30, only_trusted_peer)
