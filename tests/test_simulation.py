import asyncio
import pytest
import time
from typing import Dict, Any, List
from tests.setup_nodes import setup_full_system
from tests.block_tools import BlockTools
from src.consensus.constants import constants as consensus_constants
from src.util.ints import uint32
from src.types.full_block import FullBlock
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval

bt = BlockTools()
test_constants: Dict[str, Any] = consensus_constants.copy()
test_constants.update({"DIFFICULTY_STARTING": 500, "MIN_ITERS_STARTING": 500})

test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


def node_height_at_least(node, h):
    if (max([h.height for h in node.blockchain.get_current_tips()])) >= h:
        return True
    return False


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimulation:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation):
        node1, node2, _, _, _, _, _, _, _ = simulation

        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(60, node_height_at_least, True, node2, 7)

        # Wait additional 2 minutes to get a compact block.
        max_height = node1.blockchain.lca_block.height

        async def has_compact(node1, node2, max_height):
            for h in range(1, max_height):
                blocks_1: List[FullBlock] = await node1.block_store.get_blocks_at(
                    [uint32(h)]
                )
                blocks_2: List[FullBlock] = await node2.block_store.get_blocks_at(
                    [uint32(h)]
                )
                has_compact_1 = False
                has_compact_2 = False
                for block in blocks_1:
                    assert block.proof_of_time is not None
                    if block.proof_of_time.witness_type == 0:
                        has_compact_1 = True
                        break
                for block in blocks_2:
                    assert block.proof_of_time is not None
                    if block.proof_of_time.witness_type == 0:
                        has_compact_2 = True
                        break
                if has_compact_1 and has_compact_2:
                    return True
            return True

        await time_out_assert_custom_interval(
            120, 2, has_compact, True, node1, node2, max_height
        )
