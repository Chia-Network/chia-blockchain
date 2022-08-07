from typing import Tuple, List

import pytest
import pytest_asyncio

from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.server.server import ChiaServer
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol, ReorgProtocol
from chia.types.peer_info import PeerInfo
from chia.wallet.wallet_node import WalletNode
from chia.simulator.block_tools import create_block_tools_async, BlockTools
from chia.util.ints import uint16, uint32, uint64
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_full_node, setup_full_system, test_constants
from chia.simulator.time_out_assert import time_out_assert
from tests.util.keyring import TempKeyring

test_constants_modified = test_constants.replace(
    **{
        "DIFFICULTY_STARTING": 2 ** 8,
        "DISCRIMINANT_SIZE_BITS": 1024,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "MAX_SUB_SLOT_BLOCKS": 50,
        "NUM_SPS_SUB_SLOT": 32,  # Must be a power of 2
        "EPOCH_BLOCKS": 280,
        "SUB_SLOT_ITERS_STARTING": 2 ** 20,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 5,
    }
)


# TODO: Ideally, the db_version should be the (parameterized) db_version
# fixture, to test all versions of the database schema. This doesn't work
# because of a hack in shutting down the full node, which means you cannot run
# more than one simulations per process.
@pytest_asyncio.fixture(scope="function")
async def extra_node(self_hostname):
    with TempKeyring() as keychain:
        b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=keychain)
        async for _ in setup_full_node(
            test_constants_modified,
            "blockchain_test_3.db",
            self_hostname,
            b_tools,
            db_version=1,
        ):
            yield _


@pytest_asyncio.fixture(scope="function")
async def simulation(bt):
    async for _ in setup_full_system(test_constants_modified, bt, db_version=1):
        yield _


class TestSimulation:
    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation, extra_node, self_hostname):
        node1, node2, _, _, _, _, _, _, _, sanitizer_server = simulation
        server1 = node1.server

        node1_port = node1.full_node.server.get_port()
        node2_port = node2.full_node.server.get_port()
        await server1.start_client(PeerInfo(self_hostname, uint16(node2_port)))
        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(600, node_height_at_least, True, node2, 7)
        await sanitizer_server.start_client(PeerInfo(self_hostname, uint16(node2_port)))

        async def has_compact(node1, node2):
            peak_height_1 = node1.full_node.blockchain.get_peak_height()
            headers_1 = await node1.full_node.blockchain.get_header_blocks_in_range(0, peak_height_1 - 6)
            peak_height_2 = node2.full_node.blockchain.get_peak_height()
            headers_2 = await node2.full_node.blockchain.get_header_blocks_in_range(0, peak_height_2 - 6)
            # Commented to speed up.
            # cc_eos = [False, False]
            # icc_eos = [False, False]
            # cc_sp = [False, False]
            # cc_ip = [False, False]
            has_compact = [False, False]
            for index, headers in enumerate([headers_1, headers_2]):
                for header in headers.values():
                    for sub_slot in header.finished_sub_slots:
                        if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
                            # cc_eos[index] = True
                            has_compact[index] = True
                        if (
                            sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                            and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                        ):
                            # icc_eos[index] = True
                            has_compact[index] = True
                    if (
                        header.challenge_chain_sp_proof is not None
                        and header.challenge_chain_sp_proof.normalized_to_identity
                    ):
                        # cc_sp[index] = True
                        has_compact[index] = True
                    if header.challenge_chain_ip_proof.normalized_to_identity:
                        # cc_ip[index] = True
                        has_compact[index] = True

            # return (
            #     cc_eos == [True, True] and icc_eos == [True, True] and cc_sp == [True, True] and cc_ip == [True, True]
            # )
            return has_compact == [True, True]

        await time_out_assert(600, has_compact, True, node1, node2)
        node3 = extra_node
        server3 = node3.full_node.server
        peak_height = max(node1.full_node.blockchain.get_peak_height(), node2.full_node.blockchain.get_peak_height())
        await server3.start_client(PeerInfo(self_hostname, uint16(node1_port)))
        await server3.start_client(PeerInfo(self_hostname, uint16(node2_port)))
        await time_out_assert(600, node_height_at_least, True, node3, peak_height)

    @pytest.mark.asyncio
    async def test_simulator_auto_farm_and_get_coins(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        self_hostname: str,
    ) -> None:
        num_blocks = 2
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        wallet_node.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

        # enable auto_farming
        await full_node_api.update_autofarm_config(True)

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        block_reward = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))
        funds = block_reward

        await time_out_assert(10, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds)
        tx = await wallet.generate_signed_transaction(
            uint64(10),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
        )
        await wallet.push_transaction(tx)
        # wait till out of mempool
        await time_out_assert(10, full_node_api.full_node.mempool_manager.get_spendbundle, None, tx.name)
        # wait until the transaction is confirmed
        await time_out_assert(20, wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to, 3)
        funds += block_reward  # add auto farmed block.
        await time_out_assert(10, wallet.get_confirmed_balance, funds - 10)

        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        funds += block_reward
        # to reduce test flake, check block height again
        await time_out_assert(30, wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to, 5)
        await time_out_assert(10, wallet.get_confirmed_balance, funds - 10)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds - 10)
        # now lets test getting all coins, first only unspent, then all
        # we do this here, because we have a wallet.
        non_spent_coins = await full_node_api.get_all_coins(GetAllCoinsProtocol(False))
        assert len(non_spent_coins) == 11
        spent_and_non_spent_coins = await full_node_api.get_all_coins(GetAllCoinsProtocol(True))
        assert len(spent_and_non_spent_coins) == 12
        # try reorg, then check again.
        # revert to height 2, then go to height 6, so that we don't include the transaction we made.
        await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(2), uint32(6), ph, None))
        reorg_non_spent_coins = await full_node_api.get_all_coins(GetAllCoinsProtocol(False))
        reorg_spent_and_non_spent_coins = await full_node_api.get_all_coins(GetAllCoinsProtocol(True))
        assert len(reorg_non_spent_coins) == 12 and len(reorg_spent_and_non_spent_coins) == 12
        assert tx.additions not in spent_and_non_spent_coins  # just double check that those got reverted.
