import asyncio
import time

import pytest
import clvm
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward
from src.wallet.did_wallet.did_wallet import DIDWallet
from src.wallet.did_wallet import did_wallet_puzzles
from clvm_tools import binutils
from src.types.program import Program
from src.wallet.derivation_record import DerivationRecord
from src.types.coin_solution import CoinSolution
from src.types.BLSSignature import BLSSignature
from src.types.spend_bundle import SpendBundle
from src.wallet.transaction_record import TransactionRecord


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSimulator:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 5}
        ):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(
            3, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    async def time_out_assert(self, timeout: int, function, value, arg=None):
        start = time.time()
        while time.time() - start < timeout:
            if arg is None:
                function_result = await function()
            else:
                function_result = await function(arg)
            if value == function_result:
                return
            await asyncio.sleep(1)
        assert False
    """
    @pytest.mark.asyncio
    async def test_identity_creation(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

    @pytest.mark.asyncio
    async def test_did_spend(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        await did_wallet.create_spend(ph)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)
        await self.time_out_assert(15, wallet.get_confirmed_balance, 400000000000000)
        await self.time_out_assert(15, wallet.get_unconfirmed_balance, 400000000000000)

    @pytest.mark.asyncio
    async def test_did_recovery(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        ph = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        recovery_list = [bytes.fromhex(did_wallet.get_my_ID())]

        did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(100), recovery_list
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        assert did_wallet_2.did_info.backup_ids == recovery_list
        coins = await did_wallet_2.select_coins(1)
        coin = coins.pop()
        spend_bundle = await did_wallet.create_attestment(coin.name(), ph)
        info = await did_wallet.get_info_for_recovery()
        info = "(" + info + ")"
        await did_wallet_2.recovery_spend(coin, ph, info, spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, wallet2.get_confirmed_balance, 400000000000000)
        await self.time_out_assert(15, wallet2.get_unconfirmed_balance, 400000000000000)
        await self.time_out_assert(15, did_wallet_2.get_confirmed_balance, 0)
        await self.time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_did_update_recovery_info(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        recovery_list = [bytes.fromhex(did_wallet.get_my_ID())]

        did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(100), recovery_list
        )
        ph = await wallet.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        assert did_wallet_2.did_info.backup_ids == recovery_list

        recovery_list = [bytes.fromhex(did_wallet_2.get_my_ID())]
        await did_wallet.update_recovery_list(recovery_list)

        assert did_wallet.did_info.backup_ids == recovery_list

        # Update coin with new ID info
        updated_puz = await did_wallet.get_new_puzzle()
        # breakpoint()
        await did_wallet.create_spend(updated_puz.get_tree_hash())

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        # Recovery spend with new info
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        spend_bundle = await did_wallet_2.create_attestment(coin.name(), ph)
        info = await did_wallet_2.get_info_for_recovery()
        info = "(" + info + ")"

        await did_wallet.recovery_spend(coin, ph, info, spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, wallet.get_confirmed_balance, 400000000000000)
        await self.time_out_assert(15, wallet.get_unconfirmed_balance, 400000000000000)
        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_did_recovery_with_empty_set(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        info = "()"
        await did_wallet.recovery_spend(coin, ph, info)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, wallet.get_confirmed_balance, 400000000000000)
        await self.time_out_assert(15, wallet.get_unconfirmed_balance, 400000000000000)

    @pytest.mark.asyncio
    async def test_did_attest_after_recovery(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)
        recovery_list = [bytes.fromhex(did_wallet.get_my_ID())]

        did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(100), recovery_list
        )
        ph = await wallet.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))
        await self.time_out_assert(15, did_wallet_2.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 100)
        assert did_wallet_2.did_info.backup_ids == recovery_list

        # Update coin with new ID info
        recovery_list = [bytes.fromhex(did_wallet_2.get_my_ID())]
        await did_wallet.update_recovery_list(recovery_list)
        assert did_wallet.did_info.backup_ids == recovery_list
        updated_puz = await did_wallet.get_new_puzzle()
        await did_wallet.create_spend(updated_puz.get_tree_hash())

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        # DID Wallet 2 recovers into itself with new innerpuz
        new_puz = await did_wallet_2.get_new_puzzle()
        new_ph = new_puz.get_tree_hash()
        coins = await did_wallet_2.select_coins(1)
        coin = coins.pop()
        spend_bundle = await did_wallet.create_attestment(coin.name(), new_ph)
        info = await did_wallet.get_info_for_recovery()
        info = "(" + info + ")"
        await did_wallet_2.recovery_spend(coin, new_ph, info, spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, did_wallet_2.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 100)

        # Recovery spend
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        spend_bundle = await did_wallet_2.create_attestment(coin.name(), ph)
        info = await did_wallet_2.get_info_for_recovery()
        info = "(" + info + ")"

        await did_wallet.recovery_spend(coin, ph, info, spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await self.time_out_assert(15, wallet.get_confirmed_balance, 544000000000000)
        await self.time_out_assert(15, wallet.get_unconfirmed_balance, 544000000000000)
        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)
    """

    @pytest.mark.asyncio
    async def test_make_double_output(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await self.time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )
        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        # Lock up with non DID innerpuz so that we can create two outputs
        # Innerpuz will output the innersol, so we just pass in ((51 0xMyPuz 49) (51 0xMyPuz 51))
        innerpuz = "(a)"
        innerpuzhash = Program(binutils.assemble(innerpuz)).get_tree_hash()
        puz = did_wallet_puzzles.create_fullpuz(innerpuzhash, did_wallet.did_info.my_core)
        compiled_puz = Program(binutils.assemble(puz))

        # Add the hacked puzzle to the puzzle store so that it is recognised as "our" puzzle
        old_devrec = await did_wallet.wallet_state_manager.get_unused_derivation_record(did_wallet.wallet_info.id)
        devrec = DerivationRecord(old_devrec.index, compiled_puz.get_tree_hash(), old_devrec.pubkey, old_devrec.wallet_type, old_devrec.wallet_id)
        await did_wallet.wallet_state_manager.puzzle_store.add_derivation_paths([devrec])
        await did_wallet.create_spend(Program(compiled_puz).get_tree_hash())

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        await self.time_out_assert(15, did_wallet.get_confirmed_balance, 100)
        await self.time_out_assert(15, did_wallet.get_unconfirmed_balance, 100)

        # Create spend by hand so that we can use the weird innersol
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        # innerpuz is our desired output
        innersol = f"((51 0x{coin.puzzle_hash} 45) (51 0x{coin.puzzle_hash} 55)))"
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz_str = did_wallet.did_info.current_inner
        full_puzzle: str = puz
        parent_info = await did_wallet.get_parent_for_coin(coin)

        fullsol = f"(0x{Program(binutils.assemble(did_wallet.did_info.my_core)).get_tree_hash()} \
(0x{parent_info.parent_name} 0x{parent_info.inner_puzzle_hash} {parent_info.amount})\
{coin.amount} {innerpuz_str} {innersol})"
        list_of_solutions = [
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        Program(binutils.assemble(full_puzzle)),
                        Program(binutils.assemble(fullsol)),
                    ]
                ),
            )
        ]
        sigs = []
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=compiled_puz.get_tree_hash(),
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=did_wallet.wallet_info.id,
            sent_to=[],
        )
        await did_wallet.standard_wallet.push_transaction(did_record)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        coins = await did_wallet.select_coins(99)
        assert len(coins) == 1
