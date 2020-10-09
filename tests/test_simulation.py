import asyncio
import pytest
from typing import List
from tests.setup_nodes import setup_full_system
from src.util.ints import uint16, uint32
from src.types.full_block import FullBlock
from src.util.make_test_constants import make_test_constants_with_genesis
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from src.types.peer_info import PeerInfo

test_constants, bt = make_test_constants_with_genesis(
    {
        "DIFFICULTY_STARTING": 1000,
        "MIN_ITERS_STARTING": 100000,
        "NUMBER_ZERO_BITS_CHALLENGE_SIG": 1,
    }
)


def node_height_at_least(node, h):
    if (max([h.height for h in node.blockchain.get_current_tips()])) >= h:
        return True
    return False


class TestSimulation:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation):
        node1, node2, _, _, _, _, _, _, _, server1 = simulation
        await asyncio.sleep(10)
        await server1.start_client(PeerInfo("::1", uint16(21238)))
        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(500, node_height_at_least, True, node2, 10)

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
