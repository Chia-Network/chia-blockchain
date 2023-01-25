from __future__ import annotations

from typing import AsyncIterator, List, Tuple

import pytest
import pytest_asyncio

from chia.cmds.units import units
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools, create_block_tools_async, test_constants
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_nodes import SimulatorsAndWallets, setup_full_system, setup_simulators_and_wallets
from chia.simulator.setup_services import setup_full_node
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.wallet_node import WalletNode

test_constants_modified = test_constants.replace(
    **{
        "DIFFICULTY_STARTING": 2**8,
        "DISCRIMINANT_SIZE_BITS": 1024,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "MAX_SUB_SLOT_BLOCKS": 50,
        "NUM_SPS_SUB_SLOT": 32,  # Must be a power of 2
        "EPOCH_BLOCKS": 280,
        "SUB_SLOT_ITERS_STARTING": 2**20,
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
        async for service in setup_full_node(
            test_constants_modified,
            "blockchain_test_3.db",
            self_hostname,
            b_tools,
            db_version=1,
        ):
            yield service._api


@pytest_asyncio.fixture(scope="function")
async def simulation(bt):
    async for _ in setup_full_system(test_constants_modified, bt, db_version=1):
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_wallet_node() -> AsyncIterator[SimulatorsAndWallets]:
    async for _ in setup_simulators_and_wallets(simulator_count=1, wallet_count=1, dic={}):
        yield _


class TestSimulation:
    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation, extra_node, self_hostname):
        node1, node2, _, _, _, _, _, _, _, sanitizer_server = simulation
        server1: ChiaServer = node1.full_node.server

        node1_port: uint16 = server1.get_port()
        node2_port: uint16 = node2.full_node.server.get_port()

        # Connect node 1 to node 2
        connected: bool = await server1.start_client(PeerInfo(self_hostname, node2_port))
        assert connected, f"node1 was unable to connect to node2 on port {node2_port}"
        assert len(server1.get_connections(NodeType.FULL_NODE, outbound=True)) >= 1

        # Connect node3 to node1 and node2 - checks come later
        node3: Service[FullNode] = extra_node
        server3: ChiaServer = node3.full_node.server
        connected = await server3.start_client(PeerInfo(self_hostname, node1_port))
        assert connected, f"server3 was unable to connect to node1 on port {node1_port}"
        connected = await server3.start_client(PeerInfo(self_hostname, node2_port))
        assert connected, f"server3 was unable to connect to node2 on port {node2_port}"
        assert len(server3.get_connections(NodeType.FULL_NODE, outbound=True)) >= 2

        # wait up to 10 mins for node2 to sync the chain to height 7
        await time_out_assert(600, node2.full_node.blockchain.get_peak_height, 7)

        connected = await sanitizer_server.start_client(PeerInfo(self_hostname, node2_port))
        assert connected, f"sanitizer_server was unable to connect to node2 on port {node2_port}"

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

        # check node3 has synced to the proper height
        peak_height: uint32 = max(
            node1.full_node.blockchain.get_peak_height(), node2.full_node.blockchain.get_peak_height()
        )
        # wait up to 10 mins for node3 to sync
        await time_out_assert(600, node3.full_node.blockchain.get_peak_height, peak_height)

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
    async def test_simulation_farm_blocks_to_puzzlehash(
        self,
        count,
        one_wallet_node: SimulatorsAndWallets,
    ):
        [[full_node_api], _, _] = one_wallet_node

        # Starting at the beginning.
        assert full_node_api.full_node.blockchain.get_peak_height() is None

        await full_node_api.farm_blocks_to_puzzlehash(count=count)

        # The requested number of blocks had been processed.
        expected_height = None if count == 0 else count
        assert full_node_api.full_node.blockchain.get_peak_height() == expected_height

    @pytest.mark.asyncio
    @pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
    async def test_simulation_farm_blocks(
        self,
        self_hostname: str,
        count,
        one_wallet_node: SimulatorsAndWallets,
    ):
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute error below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        # Starting at the beginning.
        assert full_node_api.full_node.blockchain.get_peak_height() is None

        rewards = await full_node_api.farm_blocks_to_wallet(count=count, wallet=wallet)

        # The requested number of blocks had been processed plus 1 to handle the final reward
        # transactions in the case of a non-zero count.
        expected_height = count
        if count > 0:
            expected_height += 1

        peak_height = full_node_api.full_node.blockchain.get_peak_height()
        if peak_height is None:
            peak_height = uint32(0)

        assert peak_height == expected_height

        # The expected rewards have been received and confirmed.
        unconfirmed_balance = await wallet.get_unconfirmed_balance()
        confirmed_balance = await wallet.get_confirmed_balance()
        assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]

        # Test that we can change the time per block
        new_time_per_block = uint64(1000)
        full_node_api.time_per_block = new_time_per_block
        if count > 0:
            peak = full_node_api.full_node.blockchain.get_peak()
            assert isinstance(peak, BlockRecord)
            start_time = peak.timestamp
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
            peak = full_node_api.full_node.blockchain.get_peak()
            assert isinstance(peak, BlockRecord)
            end_time = peak.timestamp
            assert isinstance(start_time, uint64)
            assert isinstance(end_time, uint64)
            assert end_time - start_time >= new_time_per_block

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        argnames=["amount", "coin_count"],
        argvalues=[
            [0, 0],
            [1, 2],
            [(2 * units["chia"]) - 1, 2],
            [2 * units["chia"], 2],
            [(2 * units["chia"]) + 1, 4],
            [3 * units["chia"], 4],
            [10 * units["chia"], 10],
        ],
    )
    async def test_simulation_farm_rewards(
        self,
        self_hostname: str,
        amount: int,
        coin_count: int,
        one_wallet_node: SimulatorsAndWallets,
    ):
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute error below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        rewards = await full_node_api.farm_rewards_to_wallet(amount=amount, wallet=wallet)

        # At least the requested amount was farmed.
        assert rewards >= amount

        # The rewards amount is both received and confirmed.
        unconfirmed_balance = await wallet.get_unconfirmed_balance()
        confirmed_balance = await wallet.get_confirmed_balance()
        assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]

        # The expected number of coins were received.
        spendable_coins = await wallet.wallet_state_manager.get_spendable_coins_for_wallet(wallet.id())
        assert len(spendable_coins) == coin_count

    @pytest.mark.asyncio
    async def test_wait_transaction_records_entered_mempool(
        self,
        self_hostname: str,
        one_wallet_node: SimulatorsAndWallets,
    ) -> None:
        repeats = 50
        tx_amount = uint64(1)
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute hint issue below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        # generate some coins for repetitive testing
        await full_node_api.farm_rewards_to_wallet(amount=repeats * tx_amount, wallet=wallet)
        coins = await full_node_api.create_coins_with_amounts(amounts=[tx_amount] * repeats, wallet=wallet)
        assert len(coins) == repeats

        # repeating just to try to expose any flakiness
        for coin in coins:
            tx = await wallet.generate_signed_transaction(
                amount=uint64(tx_amount),
                puzzle_hash=await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash(),
                coins={coin},
            )
            await wallet.push_transaction(tx)

            await full_node_api.wait_transaction_records_entered_mempool(records=[tx])
            assert tx.spend_bundle is not None
            assert full_node_api.full_node.mempool_manager.get_spendbundle(tx.spend_bundle.name()) is not None
            # TODO: this fails but it seems like it shouldn't when above passes
            # assert tx.is_in_mempool()

    @pytest.mark.parametrize(argnames="records_or_bundles_or_coins", argvalues=["records", "bundles", "coins"])
    @pytest.mark.asyncio
    async def test_process_transactions(
        self,
        self_hostname: str,
        one_wallet_node: SimulatorsAndWallets,
        records_or_bundles_or_coins: str,
    ) -> None:
        repeats = 20
        tx_amount = uint64(1)
        tx_per_repeat = 2
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute hint issue below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        # generate some coins for repetitive testing
        await full_node_api.farm_rewards_to_wallet(amount=tx_amount * repeats * tx_per_repeat, wallet=wallet)
        all_coins = await full_node_api.create_coins_with_amounts(
            amounts=[tx_amount] * repeats * tx_per_repeat, wallet=wallet
        )
        assert len(all_coins) == repeats * tx_per_repeat

        coins_iter = iter(all_coins)
        # repeating just to try to expose any flakiness
        for repeat in range(repeats):
            coins = [next(coins_iter) for _ in range(tx_per_repeat)]
            transactions = [
                await wallet.generate_signed_transaction(
                    amount=uint64(tx_amount),
                    puzzle_hash=await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash(),
                    coins={coin},
                )
                for coin in coins
            ]
            for tx in transactions:
                assert tx.spend_bundle is not None, "the above created transaction is missing the expected spend bundle"
                await wallet.push_transaction(tx)

            if records_or_bundles_or_coins == "records":
                await full_node_api.process_transaction_records(records=transactions)
            elif records_or_bundles_or_coins == "bundles":
                await full_node_api.process_spend_bundles(
                    bundles=[tx.spend_bundle for tx in transactions if tx.spend_bundle is not None]
                )
            elif records_or_bundles_or_coins == "coins":
                await full_node_api.process_coin_spends(
                    coins=[
                        coin
                        for tx in transactions
                        if tx.spend_bundle is not None
                        for coin in tx.spend_bundle.additions()
                    ]
                )
            else:
                raise Exception("unexpected parametrization")
            for coin in coins:
                coin_record = await full_node_api.full_node.coin_store.get_coin_record(coin.name())
                assert coin_record is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        argnames="amounts",
        argvalues=[
            *[pytest.param([uint64(1)] * n, id=f"1 mojo x {n}") for n in [0, 1, 10, 49, 51, 103]],
            *[
                pytest.param(list(uint64(x) for x in range(1, n + 1)), id=f"incrementing x {n}")
                for n in [1, 10, 49, 51, 103]
            ],
        ],
    )
    async def test_create_coins_with_amounts(
        self,
        self_hostname: str,
        amounts: List[uint64],
        one_wallet_node: SimulatorsAndWallets,
    ) -> None:
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute hint issue below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        await full_node_api.farm_rewards_to_wallet(amount=sum(amounts), wallet=wallet)
        # Get some more coins.  The creator helper doesn't get you all the coins you
        # need yet.
        await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet)
        coins = await full_node_api.create_coins_with_amounts(amounts=amounts, wallet=wallet)

        assert sorted(coin.amount for coin in coins) == sorted(amounts)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        argnames="amounts",
        argvalues=[
            [uint64(0)],
            # cheating on type since -5 can't be heald in a proper uint64
            [uint64(5), -5],
            [uint64(4), uint64(0)],
        ],
        ids=lambda amounts: ", ".join(str(amount) for amount in amounts),
    )
    async def test_create_coins_with_invalid_amounts_raises(
        self,
        self_hostname: str,
        amounts: List[uint64],
        one_wallet_node: SimulatorsAndWallets,
    ) -> None:
        [[full_node_api], [[wallet_node, wallet_server]], _] = one_wallet_node

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.server._port)), None)

        # Avoiding an attribute hint issue below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        with pytest.raises(Exception, match="Coins must have a positive value"):
            await full_node_api.create_coins_with_amounts(amounts=amounts, wallet=wallet)
