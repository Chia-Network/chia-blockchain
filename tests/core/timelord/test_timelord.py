# flake8: noqa: F811, F401
import pytest
import asyncio
import traceback
from tests.setup_nodes import setup_timelord_and_node, constants_for_dic
from tests.connection_utils import add_dummy_connection
from tests.time_out_assert import time_out_assert, time_out_messages
from chia.protocols import timelord_protocol, full_node_protocol as fnp, full_node_protocol
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.types.blockchain_format.sized_bytes import bytes32
from tests.block_tools import BlockTools
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.types.unfinished_block import UnfinishedBlock
from chia.consensus.pot_iterations import is_overflow_block
from tests.core.node_height import node_height_at_least


@pytest.fixture(scope="function")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def setup_timelord_and_node_big_disc():
    constants = {
        "DISCRIMINANT_SIZE_BITS": 512,
    }
    async for _ in setup_timelord_and_node(constants):
        yield _


@pytest.fixture(scope="function")
async def setup_timelord_2():
    constants = {
        "DISCRIMINANT_SIZE_BITS": 16,
        "SUB_SLOT_ITERS_STARTING": 2 ** 20,
        "MAX_SUB_SLOT_BLOCKS": 200,
        "EPOCH_BLOCKS": 2000,
        "SUB_EPOCH_BLOCKS": 1000,
    }
    async for _ in setup_timelord_and_node(constants):
        yield _


class TestTimelord:
    @pytest.mark.asyncio
    async def test_have_signage_points_or_eos_from_genesis(self, setup_timelord_and_node_big_disc):
        vdf_client, timelord, timelord_server, full_node, full_node_server, _ = setup_timelord_and_node_big_disc
        incoming_queue, _ = await add_dummy_connection(full_node_server, 12312)
        await time_out_assert(
            300,
            time_out_messages(
                incoming_queue,
                "new_signage_point_or_end_of_sub_slot",
            ),
        )

    @pytest.mark.asyncio
    async def test_have_signage_points_or_eos_from_blocks(self, setup_timelord_and_node_big_disc):
        vdf_client, timelord, timelord_server, full_node, full_node_server, keychain = setup_timelord_and_node_big_disc
        constants = constants_for_dic({"DISCRIMINANT_SIZE_BITS": 512})
        bt = BlockTools(constants, keychain=keychain)
        await bt.setup_keys()
        await bt.setup_plots()
        blocks = bt.get_consecutive_blocks(20)
        for block in blocks:
            await full_node.full_node.respond_block(fnp.RespondBlock(block))
        # Make sure new peak arrived to the timelord.
        await asyncio.sleep(3)
        incoming_queue, _ = await add_dummy_connection(full_node_server, 12312)
        await time_out_assert(
            300,
            time_out_messages(
                incoming_queue,
                "new_signage_point_or_end_of_sub_slot",
            ),
        )

    @pytest.mark.asyncio
    async def test_timelord_infuses_first_block(self, setup_timelord_and_node_big_disc):
        vdf_client, timelord, timelord_server, full_node, full_node_server, keychain = setup_timelord_and_node_big_disc
        constants = constants_for_dic({"DISCRIMINANT_SIZE_BITS": 512})
        bt = BlockTools(constants, keychain=keychain)
        await bt.setup_keys()
        await bt.setup_plots()
        blocks = bt.get_consecutive_blocks(1)
        block = blocks[0]
        unfinished_block = UnfinishedBlock(
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
        await full_node.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unfinished_block), None)
        await time_out_assert(300, node_height_at_least, True, full_node, 0)

    @pytest.mark.asyncio
    async def test_timelord_infuses_from_blocks(self, setup_timelord_and_node_big_disc):
        vdf_client, timelord, timelord_server, full_node, full_node_server, keychain = setup_timelord_and_node_big_disc
        constants = constants_for_dic({"DISCRIMINANT_SIZE_BITS": 512})
        bt = BlockTools(constants, keychain=keychain)
        await bt.setup_keys()
        await bt.setup_plots()
        blocks = bt.get_consecutive_blocks(4, skip_slots=3)
        for block in blocks[:3]:
            await full_node.full_node.respond_block(fnp.RespondBlock(block))
        block = blocks[-1]
        if is_overflow_block(constants, block.reward_chain_block.signage_point_index):
            finished_ss = block.finished_sub_slots[:-1]
        else:
            finished_ss = block.finished_sub_slots
        unfinished_block = UnfinishedBlock(
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
        await full_node.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unfinished_block), None)
        await time_out_assert(300, node_height_at_least, True, full_node, 3)

    @pytest.mark.asyncio
    async def test_timelord_infuses_long_chain(self, setup_timelord_2):
        vdf_client, timelord, timelord_server, full_node, full_node_server, keychain = setup_timelord_2
        constants = constants_for_dic(
            {
                "DISCRIMINANT_SIZE_BITS": 16,
                "SUB_SLOT_ITERS_STARTING": 2 ** 20,
                "MAX_SUB_SLOT_BLOCKS": 200,
                "EPOCH_BLOCKS": 2000,
                "SUB_EPOCH_BLOCKS": 1000,
            }
        )
        bt = BlockTools(constants, keychain=keychain)
        await bt.setup_keys()
        await bt.setup_plots()
        blocks = bt.get_consecutive_blocks(200)
        # NOTE: There seem to be tricky cases around infusing right from genesis: genesis challenge might not be saved
        # in last_state's challenge cache, making some infusions not work properly. For avoiding this issue,
        # it's recommended we start infusing after a relatively stable chain is established.
        for block in blocks[:100]:
            await full_node.full_node.respond_block(fnp.RespondBlock(block))
        for i in range(100, 200):
            block = blocks[i]
            if is_overflow_block(constants, block.reward_chain_block.signage_point_index):
                finished_ss = block.finished_sub_slots[:-1]
            else:
                finished_ss = block.finished_sub_slots
            unfinished_block = UnfinishedBlock(
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
            await full_node.full_node.respond_unfinished_block(fnp.RespondUnfinishedBlock(unfinished_block), None)
            await time_out_assert(300, node_height_at_least, True, full_node, i)
