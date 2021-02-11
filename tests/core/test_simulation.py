import pytest
from tests.core.full_node.test_full_sync import node_height_at_least
from tests.setup_nodes import setup_full_system, test_constants, self_hostname
from src.util.ints import uint16
from tests.time_out_assert import time_out_assert
from src.types.peer_info import PeerInfo

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


class TestSimulation:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants_modified):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation):
        node1, node2, _, _, _, _, _, server1 = simulation
        await server1.start_client(PeerInfo(self_hostname, uint16(21238)))
        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(1000, node_height_at_least, True, node2, 7)


#         # async def has_compact(node1, node2, max_height):
#         #     for h in range(1, max_height):
#         #         blocks_1: List[FullBlock] = await node1.full_node.block_store.get_full_blocks_at([uint32(h)])
#         #         blocks_2: List[FullBlock] = await node2.full_node.block_store.get_full_blocks_at([uint32(h)])
#         #         has_compact_1 = False
#         #         has_compact_2 = False
#         #         for block in blocks_1:
#         #             assert block.proof_of_time is not None
#         #             if block.proof_of_time.witness_type == 0:
#         #                 has_compact_1 = True
#         #                 break
#         #         for block in blocks_2:
#         #             assert block.proof_of_time is not None
#         #             if block.proof_of_time.witness_type == 0:
#         #                 has_compact_2 = True
#         #                 break
#         #         if has_compact_1 and has_compact_2:
#         #             return True
#         #     return True
#         #
#         # await time_out_assert_custom_interval(120, 2, has_compact, True, node1, node2, max_height)
