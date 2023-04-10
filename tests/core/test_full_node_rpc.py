# flake8: noqa: F811, F401
from __future__ import annotations

from typing import List

import pytest
from blspy import AugSchemeMPL
from clvm.casts import int_to_bytes

from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.signage_point import SignagePoint
from chia.protocols import full_node_protocol
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.server.outbound_message import NodeType
from chia.simulator.block_tools import get_signage_point, test_constants
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.simulator.wallet_tools import WalletTool
from chia.types.coin_spend import compute_additions
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.hash import std_hash
from chia.util.ints import uint8
from tests.blockchain.blockchain_test_utils import _validate_and_add_block
from tests.connection_utils import connect_and_get_peer
from tests.util.rpc import validate_get_routes


class TestRpc:
    @pytest.mark.asyncio
    async def test1(self, two_nodes_sim_and_wallets_services, self_hostname):
        num_blocks = 5
        nodes, _, bt = two_nodes_sim_and_wallets_services
        full_node_service_1, full_node_service_2 = nodes
        full_node_api_1 = full_node_service_1._api
        full_node_api_2 = full_node_service_2._api
        server_2 = full_node_api_2.full_node.server

        try:
            client = await FullNodeRpcClient.create(
                self_hostname,
                full_node_service_1.rpc_server.listen_port,
                full_node_service_1.root_path,
                full_node_service_1.config,
            )
            await validate_get_routes(client, full_node_service_1.rpc_server.rpc_api)
            state = await client.get_blockchain_state()
            assert state["peak"] is None
            assert not state["sync"]["sync_mode"]
            assert state["difficulty"] > 0
            assert state["sub_slot_iters"] > 0

            blocks = bt.get_consecutive_blocks(num_blocks)
            blocks = bt.get_consecutive_blocks(num_blocks, block_list_input=blocks, guarantee_transaction_block=True)

            assert len(await client.get_unfinished_block_headers()) == 0
            assert len((await client.get_block_records(0, 100))) == 0
            for block in blocks:
                if is_overflow_block(test_constants, block.reward_chain_block.signage_point_index):
                    finished_ss = block.finished_sub_slots[:-1]
                else:
                    finished_ss = block.finished_sub_slots

                unf = UnfinishedBlock(
                    finished_ss,
                    block.reward_chain_block.get_unfinished(),
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage,
                    block.foliage_transaction_block,
                    block.transactions_info,
                    block.transactions_generator,
                    [],
                )
                await full_node_api_1.full_node.add_unfinished_block(unf, None)
                await full_node_api_1.full_node.add_block(block, None)

            assert len(await client.get_unfinished_block_headers()) > 0
            assert len(await client.get_all_block(0, 2)) == 2
            state = await client.get_blockchain_state()

            block = await client.get_block(state["peak"].header_hash)
            assert block == blocks[-1]
            assert (await client.get_block(bytes([1] * 32))) is None

            assert (await client.get_block_record_by_height(2)).header_hash == blocks[2].header_hash

            assert len((await client.get_block_records(0, 100))) == num_blocks * 2

            assert (await client.get_block_record_by_height(100)) is None

            ph = list(blocks[-1].get_included_reward_coins())[0].puzzle_hash
            coins = await client.get_coin_records_by_puzzle_hash(ph)
            print(coins)
            assert len(coins) >= 1

            pid = list(blocks[-1].get_included_reward_coins())[0].parent_coin_info
            pid_2 = list(blocks[-1].get_included_reward_coins())[1].parent_coin_info
            coins = await client.get_coin_records_by_parent_ids([pid, pid_2])
            print(coins)
            assert len(coins) == 2

            name = list(blocks[-1].get_included_reward_coins())[0].name()
            name_2 = list(blocks[-1].get_included_reward_coins())[1].name()
            coins = await client.get_coin_records_by_names([name, name_2])
            print(coins)
            assert len(coins) == 2

            additions, removals = await client.get_additions_and_removals(blocks[-1].header_hash)
            assert len(additions) >= 2 and len(removals) == 0

            wallet = WalletTool(full_node_api_1.full_node.constants)
            wallet_receiver = WalletTool(full_node_api_1.full_node.constants, AugSchemeMPL.key_gen(std_hash(b"123123")))
            ph = wallet.get_new_puzzlehash()
            ph_2 = wallet.get_new_puzzlehash()
            ph_receiver = wallet_receiver.get_new_puzzlehash()

            assert len(await client.get_coin_records_by_puzzle_hash(ph)) == 0
            assert len(await client.get_coin_records_by_puzzle_hash(ph_receiver)) == 0
            blocks = bt.get_consecutive_blocks(
                2,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                farmer_reward_puzzle_hash=ph,
                pool_reward_puzzle_hash=ph,
            )
            for block in blocks[-2:]:
                await full_node_api_1.full_node.add_block(block)
            assert len(await client.get_coin_records_by_puzzle_hash(ph)) == 2
            assert len(await client.get_coin_records_by_puzzle_hash(ph_receiver)) == 0

            coin_to_spend = list(blocks[-1].get_included_reward_coins())[0]

            spend_bundle = wallet.generate_signed_transaction(coin_to_spend.amount, ph_receiver, coin_to_spend)

            assert len(await client.get_all_mempool_items()) == 0
            assert len(await client.get_all_mempool_tx_ids()) == 0
            assert (await client.get_mempool_item_by_tx_id(spend_bundle.name())) is None
            assert (await client.get_mempool_item_by_tx_id(spend_bundle.name(), False)) is None

            await client.push_tx(spend_bundle)
            coin = spend_bundle.additions()[0]

            assert len(await client.get_all_mempool_items()) == 1
            assert len(await client.get_all_mempool_tx_ids()) == 1
            assert (
                SpendBundle.from_json_dict(list((await client.get_all_mempool_items()).values())[0]["spend_bundle"])
                == spend_bundle
            )
            assert (await client.get_all_mempool_tx_ids())[0] == spend_bundle.name()
            assert (
                SpendBundle.from_json_dict(
                    (await client.get_mempool_item_by_tx_id(spend_bundle.name()))["spend_bundle"]
                )
                == spend_bundle
            )
            assert (await client.get_coin_record_by_name(coin.name())) is None

            # Verify that the include_pending arg to get_mempool_item_by_tx_id works
            coin_to_spend_pending = list(blocks[-1].get_included_reward_coins())[1]
            ahr = ConditionOpcode.ASSERT_HEIGHT_RELATIVE  # to force pending/potential
            condition_dic = {ahr: [ConditionWithArgs(ahr, [int_to_bytes(100)])]}
            spend_bundle_pending = wallet.generate_signed_transaction(
                coin_to_spend_pending.amount,
                ph_receiver,
                coin_to_spend_pending,
                condition_dic=condition_dic,
            )
            await client.push_tx(spend_bundle_pending)
            assert (
                await client.get_mempool_item_by_tx_id(spend_bundle_pending.name(), False)
            ) is None  # not strictly in the mempool
            assert (
                SpendBundle.from_json_dict(
                    (await client.get_mempool_item_by_tx_id(spend_bundle_pending.name(), True))["spend_bundle"]
                )
                == spend_bundle_pending  # pending entry into mempool, so include_pending fetches
            )

            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

            coin_record = await client.get_coin_record_by_name(coin.name())
            assert coin_record.coin == coin
            assert coin in compute_additions(
                await client.get_puzzle_and_solution(coin.parent_coin_info, coin_record.confirmed_block_index)
            )

            assert len(await client.get_coin_records_by_puzzle_hash(ph_receiver)) == 1
            assert len(list(filter(lambda cr: not cr.spent, (await client.get_coin_records_by_puzzle_hash(ph))))) == 3
            assert len(await client.get_coin_records_by_puzzle_hashes([ph_receiver, ph])) == 5
            assert len(await client.get_coin_records_by_puzzle_hash(ph, False)) == 3
            assert len(await client.get_coin_records_by_puzzle_hash(ph, True)) == 4

            assert len(await client.get_coin_records_by_puzzle_hash(ph, True, 0, 100)) == 4
            assert len(await client.get_coin_records_by_puzzle_hash(ph, True, 50, 100)) == 0
            assert len(await client.get_coin_records_by_puzzle_hash(ph, True, 0, blocks[-1].height + 1)) == 2
            assert len(await client.get_coin_records_by_puzzle_hash(ph, True, 0, 1)) == 0

            coin_records = await client.get_coin_records_by_puzzle_hash(ph, False)

            coin_spends = []

            # Spend 3 coins using standard transaction
            for i in range(3):
                spend_bundle = wallet.generate_signed_transaction(
                    coin_records[i].coin.amount, ph_receiver, coin_records[i].coin
                )
                await client.push_tx(spend_bundle)
                coin_spends = coin_spends + spend_bundle.coin_spends
                await time_out_assert(
                    5, full_node_api_1.full_node.mempool_manager.get_spendbundle, spend_bundle, spend_bundle.name()
                )

            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
            block: FullBlock = (await full_node_api_1.get_all_full_blocks())[-1]

            assert len(block.transactions_generator_ref_list) > 0  # compression has occurred

            block_spends = await client.get_block_spends(block.header_hash)

            assert len(block_spends) == 3
            assert sorted(block_spends, key=lambda x: str(x)) == sorted(coin_spends, key=lambda x: str(x))

            memo = 32 * b"\f"

            for i in range(2):
                await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

                state = await client.get_blockchain_state()
                block = await client.get_block(state["peak"].header_hash)

                coin_to_spend = list(block.get_included_reward_coins())[0]

                spend_bundle = wallet.generate_signed_transaction(coin_to_spend.amount, ph_2, coin_to_spend, memo=memo)
                await client.push_tx(spend_bundle)

            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

            coin_to_spend = (await client.get_coin_records_by_hint(memo))[0].coin

            # Spend the most recent coin so we can test including spent coins later
            spend_bundle = wallet.generate_signed_transaction(coin_to_spend.amount, ph_2, coin_to_spend, memo=memo)
            await client.push_tx(spend_bundle)

            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

            coin_records = await client.get_coin_records_by_hint(memo)

            assert len(coin_records) == 3

            coin_records = await client.get_coin_records_by_hint(memo, include_spent_coins=False)

            assert len(coin_records) == 2

            state = await client.get_blockchain_state()

            # Get coin records by hint
            coin_records = await client.get_coin_records_by_hint(
                memo, start_height=state["peak"].height - 1, end_height=state["peak"].height
            )

            assert len(coin_records) == 1

            assert len(await client.get_connections()) == 0

            await client.open_connection(self_hostname, server_2._port)

            async def num_connections():
                return len(await client.get_connections())

            await time_out_assert(10, num_connections, 1)
            connections = await client.get_connections()
            assert NodeType(connections[0]["type"]) == NodeType.FULL_NODE.value
            assert len(await client.get_connections(NodeType.FULL_NODE)) == 1
            assert len(await client.get_connections(NodeType.FARMER)) == 0
            await client.close_connection(connections[0]["node_id"])
            await time_out_assert(10, num_connections, 0)

            blocks: List[FullBlock] = await client.get_blocks(0, 5)
            assert len(blocks) == 5

            await full_node_api_1.reorg_from_index_to_new_index(ReorgProtocol(2, 55, bytes([0x2] * 32), None))
            new_blocks_0: List[FullBlock] = await client.get_blocks(0, 5)
            assert len(new_blocks_0) == 7

            new_blocks: List[FullBlock] = await client.get_blocks(0, 5, exclude_reorged=True)
            assert len(new_blocks) == 5
            assert blocks[0].header_hash == new_blocks[0].header_hash
            assert blocks[1].header_hash == new_blocks[1].header_hash
            assert blocks[2].header_hash == new_blocks[2].header_hash
            assert blocks[3].header_hash != new_blocks[3].header_hash

        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()

    @pytest.mark.asyncio
    async def test_signage_points(self, two_nodes_sim_and_wallets_services, empty_blockchain):
        nodes, _, bt = two_nodes_sim_and_wallets_services
        full_node_service_1, full_node_service_2 = nodes
        full_node_api_1 = full_node_service_1._api
        full_node_api_2 = full_node_service_2._api
        server_1 = full_node_api_1.full_node.server
        server_2 = full_node_api_2.full_node.server

        config = bt.config
        self_hostname = config["self_hostname"]

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        try:
            client = await FullNodeRpcClient.create(
                self_hostname,
                full_node_service_1.rpc_server.listen_port,
                full_node_service_1.root_path,
                full_node_service_1.config,
            )

            # Only provide one
            res = await client.get_recent_signage_point_or_eos(None, None)
            assert res is None
            res = await client.get_recent_signage_point_or_eos(std_hash(b"0"), std_hash(b"1"))
            assert res is None

            # Not found
            res = await client.get_recent_signage_point_or_eos(std_hash(b"0"), None)
            assert res is None
            res = await client.get_recent_signage_point_or_eos(None, std_hash(b"0"))
            assert res is None

            blocks = bt.get_consecutive_blocks(5)
            for block in blocks:
                await full_node_api_1.full_node.add_block(block)

            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1, force_overflow=True)

            blockchain = full_node_api_1.full_node.blockchain
            second_blockchain = empty_blockchain

            for block in blocks:
                await _validate_and_add_block(second_blockchain, block)

            # Creates a signage point based on the last block
            peak_2 = second_blockchain.get_peak()
            sp: SignagePoint = get_signage_point(
                test_constants,
                blockchain,
                peak_2,
                peak_2.ip_sub_slot_total_iters(test_constants),
                uint8(4),
                [],
                peak_2.sub_slot_iters,
            )

            # Don't have SP yet
            res = await client.get_recent_signage_point_or_eos(sp.cc_vdf.output.get_hash(), None)
            assert res is None

            # Add the last block
            await full_node_api_1.full_node.add_block(blocks[-1])
            await full_node_api_1.respond_signage_point(
                full_node_protocol.RespondSignagePoint(uint8(4), sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof), peer
            )

            assert full_node_api_1.full_node.full_node_store.get_signage_point(sp.cc_vdf.output.get_hash()) is not None

            # Properly fetch a signage point
            res = await client.get_recent_signage_point_or_eos(sp.cc_vdf.output.get_hash(), None)

            assert res is not None
            assert "eos" not in res
            assert res["signage_point"] == sp
            assert not res["reverted"]

            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            selected_eos = blocks[-1].finished_sub_slots[0]

            # Don't have EOS yet
            res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
            assert res is None

            # Properly fetch an EOS
            for eos in blocks[-1].finished_sub_slots:
                await full_node_api_1.full_node.add_end_of_sub_slot(eos, peer)

            res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
            assert res is not None
            assert "signage_point" not in res
            assert res["eos"] == selected_eos
            assert not res["reverted"]

            # Do another one but without sending the slot
            await full_node_api_1.full_node.add_block(blocks[-1])
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            selected_eos = blocks[-1].finished_sub_slots[-1]
            await full_node_api_1.full_node.add_block(blocks[-1])

            res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
            assert res is not None
            assert "signage_point" not in res
            assert res["eos"] == selected_eos
            assert not res["reverted"]

            # Perform a reorg
            blocks = bt.get_consecutive_blocks(12, seed=b"1234")
            for block in blocks:
                await full_node_api_1.full_node.add_block(block)

            # Signage point is no longer in the blockchain
            res = await client.get_recent_signage_point_or_eos(sp.cc_vdf.output.get_hash(), None)
            assert res["reverted"]
            assert res["signage_point"] == sp
            assert "eos" not in res

            # EOS is no longer in the blockchain
            res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
            assert res is not None
            assert "signage_point" not in res
            assert res["eos"] == selected_eos
            assert res["reverted"]

        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()
