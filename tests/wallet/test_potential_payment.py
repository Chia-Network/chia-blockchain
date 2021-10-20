import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cc_wallet.cc_utils import construct_cc_puzzle
from chia.wallet.cc_wallet.cc_wallet import CCWallet
from chia.wallet.cc_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.payment import Payment
from chia.wallet.potential_payment import PotentialPayment, DependencyGraph
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.wallet.transaction_record import TransactionRecord
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop

async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True

class TestPotentialPayment:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.asyncio
    async def test_colour_creation(self, two_wallet_nodes):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cc_wallet: CCWallet = await CCWallet.create_new_cc_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )

        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_spendable_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        pp_1 = await PotentialPayment.create(wallet, 10, 5)
        pp_2 = await PotentialPayment.create(cc_wallet, 50, 15)

        await pp_1.set_payments([Payment(ph, 10, [b'$', None, b'$'], extra_conditions=[
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(pp_2.origin_id + b'$$$')]
        ])])
        await pp_2.set_payments([Payment(ph, 40, [], extra_conditions=[
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, b'$$$']
        ])])

        dgraph = DependencyGraph([pp_1,pp_2])
        bundle = PotentialPayment.bundle([pp_1, pp_2])

        breakpoint()
