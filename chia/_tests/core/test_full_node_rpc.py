from __future__ import annotations

import pytest
from chia_rs import AugSchemeMPL, BlockRecord, FullBlock, UnfinishedBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia import __version__
from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.conftest import ConsensusMode
from chia._tests.connection_utils import connect_and_get_peer
from chia._tests.util.rpc import validate_get_routes
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.blockchain import Blockchain
from chia.consensus.pot_iterations import is_overflow_block
from chia.consensus.signage_point import SignagePoint
from chia.full_node.full_node_rpc_api import get_average_block_time, get_nearest_transaction_block
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.protocols import full_node_protocol
from chia.protocols.outbound_message import NodeType
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import get_signage_point
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.casts import int_to_bytes
from chia.util.hash import std_hash
from chia.wallet.util.compute_additions import compute_additions
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


@pytest.mark.anyio
async def test1(
    two_nodes_sim_and_wallets_services: SimulatorsAndWalletsServices, self_hostname: str, consensus_mode: ConsensusMode
) -> None:
    num_blocks = 5
    nodes, _, bt = two_nodes_sim_and_wallets_services
    full_node_service_1, full_node_service_2 = nodes
    full_node_api_1 = full_node_service_1._api
    full_node_api_2 = full_node_service_2._api
    server_2 = full_node_api_2.full_node.server
    assert full_node_service_1.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    ) as client:
        await validate_get_routes(client, full_node_service_1.rpc_server.rpc_api)
        state = await client.get_blockchain_state()
        assert state["peak"] is None
        assert not state["sync"]["sync_mode"]
        assert state["difficulty"] > 0
        assert state["sub_slot_iters"] > 0

        blocks = bt.get_consecutive_blocks(num_blocks)
        blocks = bt.get_consecutive_blocks(num_blocks, block_list_input=blocks, guarantee_transaction_block=True)

        assert len(await client.get_unfinished_block_headers()) == 0
        assert len(await client.get_block_records(0, 100)) == 0
        for block in blocks:
            if is_overflow_block(bt.constants, block.reward_chain_block.signage_point_index):
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
        assert len(await client.get_all_block(uint32(0), uint32(2))) == 2
        state = await client.get_blockchain_state()

        peak_block = await client.get_block(state["peak"].header_hash)
        assert peak_block == blocks[-1]
        with pytest.raises(ValueError, match="not found"):
            await client.get_block(bytes32([1] * 32))
        block_record = await client.get_block_record_by_height(2)
        assert block_record is not None
        assert block_record.header_hash == blocks[2].header_hash

        assert len(await client.get_block_records(0, 100)) == num_blocks * 2

        assert (await client.get_block_record_by_height(100)) is None

        # NOTE: indexing and hard coded values below depend on the ordering
        included_reward_coins = sorted(blocks[-1].get_included_reward_coins(), key=lambda c: c.amount)

        ph = included_reward_coins[0].puzzle_hash
        coins = await client.get_coin_records_by_puzzle_hash(ph)
        print(coins)
        assert len(coins) >= 1

        pid = included_reward_coins[0].parent_coin_info
        pid_2 = included_reward_coins[1].parent_coin_info
        coins = await client.get_coin_records_by_parent_ids([pid, pid_2])
        print(coins)
        assert len(coins) == 2

        name = included_reward_coins[0].name()
        name_2 = included_reward_coins[1].name()
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

        # NOTE: indexing and hard coded values below depend on the ordering
        included_reward_coins = sorted(blocks[-1].get_included_reward_coins(), key=lambda c: c.amount)

        coin_to_spend = included_reward_coins[0]

        spend_bundle = wallet.generate_signed_transaction(coin_to_spend.amount, ph_receiver, coin_to_spend)

        assert len(await client.get_all_mempool_items()) == 0
        assert len(await client.get_all_mempool_tx_ids()) == 0
        with pytest.raises(ValueError, match="not in the mempool"):
            await client.get_mempool_item_by_tx_id(spend_bundle.name())
        with pytest.raises(ValueError, match="not in the mempool"):
            await client.get_mempool_item_by_tx_id(spend_bundle.name(), False)

        await client.push_tx(spend_bundle)
        coin = spend_bundle.additions()[0]

        assert len(await client.get_all_mempool_items()) == 1
        assert len(await client.get_all_mempool_tx_ids()) == 1
        assert (
            WalletSpendBundle.from_json_dict(
                next(iter((await client.get_all_mempool_items()).values()))["spend_bundle"]
            )
            == spend_bundle
        )
        assert (await client.get_all_mempool_tx_ids())[0] == spend_bundle.name()
        mempool_item = await client.get_mempool_item_by_tx_id(spend_bundle.name())
        assert mempool_item is not None
        assert WalletSpendBundle.from_json_dict(mempool_item["spend_bundle"]) == spend_bundle
        with pytest.raises(ValueError, match="not found"):
            await client.get_coin_record_by_name(coin.name())

        # Verify that the include_pending arg to get_mempool_item_by_tx_id works
        coin_to_spend_pending = included_reward_coins[1]
        ahr = ConditionOpcode.ASSERT_HEIGHT_RELATIVE  # to force pending/potential
        condition_dic = {ahr: [ConditionWithArgs(ahr, [int_to_bytes(100)])]}
        spend_bundle_pending = wallet.generate_signed_transaction(
            coin_to_spend_pending.amount,
            ph_receiver,
            coin_to_spend_pending,
            condition_dic=condition_dic,
        )
        await client.push_tx(spend_bundle_pending)
        with pytest.raises(ValueError, match="not in the mempool"):
            # not strictly in the mempool
            await client.get_mempool_item_by_tx_id(spend_bundle_pending.name(), False)
        # pending entry into mempool, so include_pending fetches
        mempool_item = await client.get_mempool_item_by_tx_id(spend_bundle_pending.name(), True)
        assert WalletSpendBundle.from_json_dict(mempool_item["spend_bundle"]) == spend_bundle_pending

        await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

        coin_record = await client.get_coin_record_by_name(coin.name())
        assert coin_record is not None
        assert coin_record.coin == coin
        coin_spend = await client.get_puzzle_and_solution(coin.parent_coin_info, coin_record.confirmed_block_index)
        assert coin_spend is not None
        assert coin in compute_additions(coin_spend)

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
            coin_spends += spend_bundle.coin_spends
            await time_out_assert(
                5, full_node_api_1.full_node.mempool_manager.get_spendbundle, spend_bundle, spend_bundle.name()
            )

        await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
        block = (await full_node_api_1.get_all_full_blocks())[-1]

        # since the hard fork, we no longer compress blocks using
        # block references anymore
        assert block.transactions_generator_ref_list == []

        block_spends = await client.get_block_spends(block.header_hash)
        assert block_spends is not None
        assert len(block_spends) == 3
        assert sorted(block_spends, key=str) == sorted(coin_spends, key=str)

        block_spends_with_conditions = await client.get_block_spends_with_conditions(block.header_hash)
        assert block_spends_with_conditions is not None
        assert len(block_spends_with_conditions) == 3

        block_spends_with_conditions = sorted(block_spends_with_conditions, key=lambda x: str(x.coin_spend))

        coin_spend_with_conditions = block_spends_with_conditions[1]

        assert coin_spend_with_conditions.coin_spend.coin == Coin(
            bytes.fromhex("e3b0c44298fc1c149afbf4c8996fb9240000000000000000000000000000000a"),
            bytes.fromhex("8488947a2213b2c2551fe019bbb708db86eab3dd5133eb57e801515e9e4ad82a"),
            uint64(1_750_000_000_000),
        )
        assert coin_spend_with_conditions.coin_spend.puzzle_reveal == SerializedProgram.fromhex(
            "ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252aff018080"
        )
        assert coin_spend_with_conditions.coin_spend.solution == SerializedProgram.fromhex(
            "ff80ffff01ffff33ffa063c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575cff8601977420dc0080ffff3cffa0a2366d6d8e1ce7496175528f5618a13da8401b02f2bac1eaae8f28aea9ee54798080ff8080"
        )

        expected = [
            ConditionWithArgs(
                ConditionOpcode(b"2"),
                [
                    bytes.fromhex(
                        "a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252a"
                    ),
                    bytes.fromhex("49b6f533000b967f049bb6e7b29d0b6f465ebccd5733bc75340f98dae782aa08"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"3"),
                [
                    bytes.fromhex("63c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575c"),
                    bytes.fromhex("01977420dc00"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"<"),
                [
                    bytes.fromhex("a2366d6d8e1ce7496175528f5618a13da8401b02f2bac1eaae8f28aea9ee5479"),
                ],
            ),
        ]

        assert coin_spend_with_conditions.conditions == expected

        coin_spend_with_conditions = block_spends_with_conditions[2]

        assert coin_spend_with_conditions.coin_spend.coin == Coin(
            bytes.fromhex("e3b0c44298fc1c149afbf4c8996fb9240000000000000000000000000000000b"),
            bytes.fromhex("8488947a2213b2c2551fe019bbb708db86eab3dd5133eb57e801515e9e4ad82a"),
            uint64(1_750_000_000_000),
        )
        assert coin_spend_with_conditions.coin_spend.puzzle_reveal == SerializedProgram.fromhex(
            "ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252aff018080"
        )
        assert coin_spend_with_conditions.coin_spend.solution == SerializedProgram.fromhex(
            "ff80ffff01ffff33ffa063c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575cff8601977420dc0080ffff3cffa04f6d4d12e97e83b2024fd0970e3b9e8a1c2e509625c15ff4145940c45b51974f8080ff8080"
        )
        assert coin_spend_with_conditions.conditions == [
            ConditionWithArgs(
                ConditionOpcode(b"2"),
                [
                    bytes.fromhex(
                        "a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252a"
                    ),
                    bytes.fromhex("95df50b31bb746a37df6ab448f10436fb98bb659990c61ee6933a196f6a06465"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"3"),
                [
                    bytes.fromhex("63c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575c"),
                    bytes.fromhex("01977420dc00"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"<"),
                [
                    bytes.fromhex("4f6d4d12e97e83b2024fd0970e3b9e8a1c2e509625c15ff4145940c45b51974f"),
                ],
            ),
        ]

        coin_spend_with_conditions = block_spends_with_conditions[0]

        assert coin_spend_with_conditions.coin_spend.coin == Coin(
            bytes.fromhex("27ae41e4649b934ca495991b7852b8550000000000000000000000000000000b"),
            bytes.fromhex("8488947a2213b2c2551fe019bbb708db86eab3dd5133eb57e801515e9e4ad82a"),
            uint64(250_000_000_000),
        )
        assert coin_spend_with_conditions.coin_spend.puzzle_reveal == SerializedProgram.fromhex(
            "ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252aff018080"
        )
        assert coin_spend_with_conditions.coin_spend.solution == SerializedProgram.fromhex(
            "ff80ffff01ffff33ffa063c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575cff853a3529440080ffff3cffa0617d9951551dc9e329fcab835f37fe4602c9ea57626cc2069228793f7007716f8080ff8080"
        )
        assert coin_spend_with_conditions.conditions == [
            ConditionWithArgs(
                ConditionOpcode(b"2"),
                [
                    bytes.fromhex(
                        "a499b52c7eba3465c3d74070a25d5ac5f5df25ed07d1c9c0c0509b00140da3e3bb60b584eaa30a1204ec0e5839f1252a"
                    ),
                    bytes.fromhex("f3dd65f1ca4b030a726182e0194174fe95ff7a66f54381cad3aab168b8e75ee7"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"3"),
                [
                    bytes.fromhex("63c767818f8b7cc8f3760ce34a09b7f34cd9ddf09d345c679b6897e7620c575c"),
                    bytes.fromhex("3a35294400"),
                ],
            ),
            ConditionWithArgs(
                ConditionOpcode(b"<"),
                [
                    bytes.fromhex("617d9951551dc9e329fcab835f37fe4602c9ea57626cc2069228793f7007716f"),
                ],
            ),
        ]

        memo = bytes32(32 * b"\f")

        for i in range(2):
            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

            state = await client.get_blockchain_state()
            peak_block = await client.get_block(state["peak"].header_hash)
            assert peak_block is not None
            coin_to_spend = peak_block.get_included_reward_coins()[0]

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

        assert server_2._port is not None
        await client.open_connection(self_hostname, server_2._port)

        async def num_connections() -> int:
            return len(await client.get_connections())

        await time_out_assert(10, num_connections, 1)
        connections = await client.get_connections()
        assert NodeType(connections[0]["type"]) == NodeType.FULL_NODE.value
        assert len(await client.get_connections(NodeType.FULL_NODE)) == 1
        assert len(await client.get_connections(NodeType.FARMER)) == 0
        await client.close_connection(connections[0]["node_id"])
        await time_out_assert(10, num_connections, 0)

        blocks = await client.get_blocks(0, 5)
        assert len(blocks) == 5

        await full_node_api_1.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(2), uint32(55), bytes32([0x2] * 32), None)
        )
        new_blocks_0: list[FullBlock] = await client.get_blocks(0, 5)
        assert len(new_blocks_0) == 7

        new_blocks: list[FullBlock] = await client.get_blocks(0, 5, exclude_reorged=True)
        assert len(new_blocks) == 5
        assert blocks[0].header_hash == new_blocks[0].header_hash
        assert blocks[1].header_hash == new_blocks[1].header_hash
        assert blocks[2].header_hash == new_blocks[2].header_hash
        assert blocks[3].header_hash != new_blocks[3].header_hash


@pytest.mark.anyio
async def test_signage_points(
    two_nodes_sim_and_wallets_services: SimulatorsAndWalletsServices, empty_blockchain: Blockchain
) -> None:
    nodes, _, bt = two_nodes_sim_and_wallets_services
    full_node_service_1, full_node_service_2 = nodes
    full_node_api_1 = full_node_service_1._api
    full_node_api_2 = full_node_service_2._api
    server_1 = full_node_api_1.full_node.server
    server_2 = full_node_api_2.full_node.server

    config = bt.config
    self_hostname = config["self_hostname"]

    peer = await connect_and_get_peer(server_1, server_2, self_hostname)
    assert full_node_service_1.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    ) as client:
        # Only provide one
        with pytest.raises(ValueError, match="sp_hash or challenge_hash must be provided"):
            await client.get_recent_signage_point_or_eos(None, None)
        with pytest.raises(ValueError, match="Either sp_hash or challenge_hash must be provided, not both"):
            await client.get_recent_signage_point_or_eos(std_hash(b"0"), std_hash(b"1"))
        # Not found
        with pytest.raises(ValueError, match="in cache"):
            await client.get_recent_signage_point_or_eos(std_hash(b"0"), None)
        with pytest.raises(ValueError, match="in cache"):
            await client.get_recent_signage_point_or_eos(None, std_hash(b"0"))
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
        assert peak_2 is not None
        sp: SignagePoint = get_signage_point(
            bt.constants,
            blockchain,
            peak_2,
            peak_2.ip_sub_slot_total_iters(bt.constants),
            uint8(4),
            [],
            peak_2.sub_slot_iters,
        )
        assert sp.cc_proof is not None
        assert sp.cc_vdf is not None
        assert sp.rc_proof is not None
        assert sp.rc_vdf is not None
        # Don't have SP yet
        with pytest.raises(ValueError, match="Did not find sp"):
            await client.get_recent_signage_point_or_eos(sp.cc_vdf.output.get_hash(), None)

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
        with pytest.raises(ValueError, match="Did not find eos"):
            await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
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
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2)
        selected_eos = blocks[-1].finished_sub_slots[-1]
        await full_node_api_1.full_node.add_block(blocks[-1])

        res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
        assert res is not None
        assert "signage_point" not in res
        assert res["eos"] == selected_eos
        assert not res["reverted"]

        # Perform a reorg
        blocks = bt.get_consecutive_blocks(12, seed=b"1234")
        await add_blocks_in_batches(blocks, full_node_api_1.full_node)

        # Signage point is no longer in the blockchain
        res = await client.get_recent_signage_point_or_eos(sp.cc_vdf.output.get_hash(), None)
        assert res is not None
        assert res["reverted"]
        assert res["signage_point"] == sp
        assert "eos" not in res

        # EOS is no longer in the blockchain
        res = await client.get_recent_signage_point_or_eos(None, selected_eos.challenge_chain.get_hash())
        assert res is not None
        assert "signage_point" not in res
        assert res["eos"] == selected_eos
        assert res["reverted"]


@pytest.mark.anyio
async def test_get_network_info(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, self_hostname: str
) -> None:
    nodes, _, _bt = one_wallet_and_one_simulator_services
    (full_node_service_1,) = nodes
    assert full_node_service_1.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    ) as client:
        await validate_get_routes(client, full_node_service_1.rpc_server.rpc_api)
        network_info = await client.fetch("get_network_info", {})
        assert network_info == {
            "network_name": "testnet0",
            "network_prefix": "txch",
            "genesis_challenge": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "success": True,
        }


@pytest.mark.anyio
async def test_get_version(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, self_hostname: str
) -> None:
    nodes, _, _bt = one_wallet_and_one_simulator_services
    (full_node_service_1,) = nodes
    assert full_node_service_1.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service_1.rpc_server.listen_port,
        full_node_service_1.root_path,
        full_node_service_1.config,
    ) as client:
        version = await client.fetch("get_version", {})
        assert version == {
            "success": True,
            "version": __version__,
        }


@pytest.mark.anyio
async def test_get_blockchain_state(
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, self_hostname: str
) -> None:
    num_blocks = 5
    nodes, _, bt = one_wallet_and_one_simulator_services
    (full_node_service_1,) = nodes
    full_node_api_1 = full_node_service_1._api
    assert full_node_service_1.rpc_server is not None
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
        assert state["space"] == 0
        assert state["average_block_time"] is None

        blocks: list[FullBlock] = bt.get_consecutive_blocks(num_blocks)
        blocks = bt.get_consecutive_blocks(num_blocks, block_list_input=blocks, guarantee_transaction_block=True)

        for block in blocks:
            unf = UnfinishedBlock(
                block.finished_sub_slots,
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

        state = await client.get_blockchain_state()

        assert state["space"] > 0
        assert state["average_block_time"] > 0

        block_records = []
        for rec in blocks:
            record = await full_node_api_1.full_node.blockchain.get_block_record_from_db(rec.header_hash)
            if record is not None:
                block_records.append(record)
        first_non_transaction_block_index = -1
        for i, b in enumerate(block_records):
            if not b.is_transaction_block:
                first_non_transaction_block_index = i
                break
        # Genesis block(height=0) must be a transaction block
        # so first_non_transaction_block_index != 0
        assert first_non_transaction_block_index > 0

        transaction_blocks: list[BlockRecord] = [b for b in block_records if b.is_transaction_block]
        non_transaction_block: list[BlockRecord] = [b for b in block_records if not b.is_transaction_block]
        assert len(transaction_blocks) > 0
        assert len(non_transaction_block) > 0
        assert transaction_blocks[0] == await get_nearest_transaction_block(
            full_node_api_1.full_node.blockchain, transaction_blocks[0]
        )

        nearest_transaction_block = block_records[first_non_transaction_block_index - 1]
        expected_nearest_transaction_block = await get_nearest_transaction_block(
            full_node_api_1.full_node.blockchain, block_records[first_non_transaction_block_index]
        )
        assert expected_nearest_transaction_block == nearest_transaction_block
        # When supplying genesis block, there are no older blocks so `None` should be returned
        assert await get_average_block_time(full_node_api_1.full_node.blockchain, block_records[0], 4608) is None
        assert await get_average_block_time(full_node_api_1.full_node.blockchain, block_records[-1], 4608) is not None
        # Test that get_aggsig_additional_data() returns correctly
        assert (
            full_node_api_1.full_node.constants.AGG_SIG_ME_ADDITIONAL_DATA == await client.get_aggsig_additional_data()
        )

    finally:
        # Checks that the RPC manages to stop the node
        client.close()
        await client.await_closed()


@pytest.mark.anyio
async def test_coin_name_not_in_request(one_node: SimulatorsAndWalletsServices, self_hostname: str) -> None:
    [full_node_service], _, _ = one_node
    assert full_node_service.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service.rpc_server.listen_port,
        full_node_service.root_path,
        full_node_service.config,
    ) as client:
        with pytest.raises(ValueError, match="No coin_name in request"):
            await client.fetch("get_mempool_items_by_coin_name", {})


@pytest.mark.anyio
async def test_coin_name_not_found_in_mempool(one_node: SimulatorsAndWalletsServices, self_hostname: str) -> None:
    [full_node_service], _, _ = one_node
    assert full_node_service.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service.rpc_server.listen_port,
        full_node_service.root_path,
        full_node_service.config,
    ) as client:
        empty_coin_name = bytes32.zeros
        mempool_item = await client.get_mempool_items_by_coin_name(empty_coin_name)
        assert mempool_item["success"]
        assert "mempool_items" in mempool_item
        assert len(mempool_item["mempool_items"]) == 0


@pytest.mark.anyio
async def test_coin_name_found_in_mempool(one_node: SimulatorsAndWalletsServices, self_hostname: str) -> None:
    [full_node_service], _, bt = one_node
    full_node_api = full_node_service._api
    assert full_node_service.rpc_server is not None
    async with FullNodeRpcClient.create_as_context(
        self_hostname,
        full_node_service.rpc_server.listen_port,
        full_node_service.root_path,
        full_node_service.config,
    ) as client:
        blocks = bt.get_consecutive_blocks(2)
        blocks = bt.get_consecutive_blocks(2, block_list_input=blocks, guarantee_transaction_block=True)

        for block in blocks:
            unf = UnfinishedBlock(
                block.finished_sub_slots,
                block.reward_chain_block.get_unfinished(),
                block.challenge_chain_sp_proof,
                block.reward_chain_sp_proof,
                block.foliage,
                block.foliage_transaction_block,
                block.transactions_info,
                block.transactions_generator,
                [],
            )
            await full_node_api.full_node.add_unfinished_block(unf, None)
            await full_node_api.full_node.add_block(block, None)

        wallet = WalletTool(full_node_api.full_node.constants)
        wallet_receiver = WalletTool(full_node_api.full_node.constants, AugSchemeMPL.key_gen(std_hash(b"123123")))
        ph = wallet.get_new_puzzlehash()
        ph_receiver = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=ph,
            pool_reward_puzzle_hash=ph,
        )
        for block in blocks[-2:]:
            await full_node_api.full_node.add_block(block)

        # empty mempool
        assert len(await client.get_all_mempool_items()) == 0

        coin_to_spend = blocks[-1].get_included_reward_coins()[0]
        spend_bundle = wallet.generate_signed_transaction(coin_to_spend.amount, ph_receiver, coin_to_spend)
        await client.push_tx(spend_bundle)

        # mempool with one item
        assert len(await client.get_all_mempool_items()) == 1

        mempool_item = await client.get_mempool_items_by_coin_name(coin_to_spend.name())

        # found coin in coin spends
        assert mempool_item["success"]
        assert "mempool_items" in mempool_item
        assert len(mempool_item["mempool_items"]) > 0
        for item in mempool_item["mempool_items"]:
            removals = [Coin.from_json_dict(coin) for coin in item["removals"]]
            assert coin_to_spend.name() in [coin.name() for coin in removals]
