from __future__ import annotations

# mypy: ignore-errors
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.dao_wallet.dao_wallet import DAOWallet

# from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.transaction_record import TransactionRecord

SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_alternate_proposal_timer.clvm")
DAO_PROPOSAL_MOD: Program = load_clvm("dao_alternate_proposal.clvm")
DAO_TREASURY_MOD: Program = load_clvm("dao_alternate_treasury.clvm")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_or_delayed_puzhash.clvm")


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32) -> bool:
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


puzzle_hash_0 = bytes32(32 * b"0")
puzzle_hash_1 = bytes32(32 * b"1")


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_cat_spend(self_hostname: str, two_wallet_nodes: SimulatorsAndWallets, trusted: bool) -> None:
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
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

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
    assert tx_record.spend_bundle
    await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name())

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 100)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 100)

    assert cat_wallet.cat_info.limitations_program_hash is not None
    asset_id = cat_wallet.get_asset_id()

    cat_wallet_2: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_2.wallet_state_manager, wallet2, asset_id
    )

    assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

    cat_2_hash = await cat_wallet_2.get_new_inner_hash()
    tx_records = await cat_wallet.generate_signed_transactions([uint64(60)], [cat_2_hash], fee=uint64(1))
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
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await time_out_assert(30, wallet.get_confirmed_balance, funds - 101)

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 40)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 40)

    await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 60)
    await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 60)

    cat_hash = await cat_wallet.get_new_inner_hash()
    tx_records = await cat_wallet_2.generate_signed_transactions([uint64(15)], [cat_hash])
    for tx_record in tx_records:
        assert tx_record.spend_bundle
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 55)
    await time_out_assert(20, cat_wallet.get_unconfirmed_balance, 55)

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height
    await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(height - 1, height + 1, puzzle_hash_1, None))
    await time_out_assert(20, cat_wallet.get_confirmed_balance, 40)

    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
    )

    dao_wallet = await DAOWallet.create_new_dao_for_existing_cat(
        wallet_node.wallet_state_manager,
        wallet,
        bytes.fromhex(asset_id),
        dao_rules,
    )

    dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
        wallet_node.wallet_state_manager,
        wallet,
        asset_id,
    )
    assert dao_wallet is not None
    assert dao_cat_wallet is not None

    # cat wallet balance is 55
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await time_out_assert(20, cat_wallet.get_confirmed_balance, 55)
    await time_out_assert(20, dao_cat_wallet.get_votable_balance, 55)
    await time_out_assert(20, dao_cat_wallet.get_votable_balance, 0, include_free_cats=False)

    txs, new_cats = await dao_cat_wallet.create_new_dao_cats(35, push=True)
    await time_out_assert(
        15, tx_in_pool, True, full_node_api.full_node.mempool_manager, txs[0].spend_bundle.name()
    )
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    # coins = await cat_wallet.select_coins(55)

    await time_out_assert(20, cat_wallet.get_spendable_balance, 20)
    await time_out_assert(20, cat_wallet.get_confirmed_balance, 20)
    await time_out_assert(20, dao_cat_wallet.get_votable_balance, 55)
    await time_out_assert(20, dao_cat_wallet.get_votable_balance, 35, include_free_cats=False)
