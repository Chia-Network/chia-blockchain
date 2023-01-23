# type: ignore

from __future__ import annotations

import asyncio
from typing import List

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import LegacyCATInfo
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_info import WalletInfo
from tests.util.wallet_is_synced import wallet_is_synced

SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_MOD: Program = load_clvm("dao_proposal.clvm")
DAO_TREASURY_MOD: Program = load_clvm("dao_treasury.clvm")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_or_delayed_puzhash.clvm")


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_cat_spend(self_hostname, two_wallet_nodes, trusted):
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node, server_2 = wallets[0]
    wallet_node_2, server_3 = wallets[1]
    wallet = wallet_node.wallet_state_manager.main_wallet
    wallet2 = wallet_node_2.wallet_state_manager.main_wallet

    ph = await wallet.get_new_puzzlehash()
    if trusted:
        wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}
    await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_3.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks + 1)]
    )

    await time_out_assert(20, wallet.get_confirmed_balance, funds)

    async with wallet_node.wallet_state_manager.lock:
        cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
        )
    tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 100)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 100)

    assert cat_wallet.cat_info.limitations_program_hash is not None
    asset_id = cat_wallet.get_asset_id()

    cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
        wallet_node_2.wallet_state_manager, wallet2, asset_id
    )

    assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

    cat_2_hash = await cat_wallet_2.get_new_inner_hash()
    tx_records = await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], fee=uint64(1))
    for tx_record in tx_records:
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)
        if tx_record.spend_bundle is not None:
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )
        if tx_record.wallet_id is cat_wallet.id():
            assert tx_record.to_puzzle_hash == cat_2_hash

    await time_out_assert(20, cat_wallet.get_pending_change_balance, 40)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

    await time_out_assert(30, wallet.get_confirmed_balance, funds - 101)

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 40)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 40)

    await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 60)
    await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 60)

    cat_hash = await cat_wallet.get_new_inner_hash()
    tx_records = await cat_wallet_2.generate_signed_transaction([uint64(15)], [cat_hash])
    for tx_record in tx_records:
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 55)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 55)

    height = full_node_api.full_node.blockchain.get_peak_height()
    await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(height - 1, height + 1, 32 * b"1", None))
    await time_out_assert(20, cat_wallet.get_confirmed_balance, 40)

    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    PREVIOUS_VOTES: List[bytes] = [0xFADEDDAB]

    proposal_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    current_votes: uint64 = uint64(0)
    total_votes: uint64 = uint64(0)
    proposal_innerpuz: Program = Program.to(1)
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        current_votes,
        total_votes,
        proposal_innerpuz,
    )
