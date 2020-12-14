# import asyncio
# import pytest
# from typing import List
#
# from tests.full_node.test_full_sync import node_height_at_least
# from tests.setup_nodes import setup_full_system, test_constants
# from src.util.ints import uint16, uint32
# from src.types.full_block import FullBlock
# from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
# from src.types.peer_info import PeerInfo
# from src.consensus.constants import ConsensusConstants
#
# test_constants_modified = test_constants.replace(
#     **{
#         "DIFFICULTY_STARTING": 2 ** 8,
#         "DISCRIMINANT_SIZE_BITS": 1024,
#         "SUB_EPOCH_SUB_BLOCKS": 140,
#         "MAX_SUB_SLOT_SUB_BLOCKS": 50,
#         "EPOCH_SUB_BLOCKS": 280,
#         "SUB_SLOT_ITERS_STARTING": 2 ** 14,
#         "NUMBER_ZERO_BITS_PLOT_FILTER": 1,
#     }
# )
#
#
# class TestSimulation:
#     @pytest.fixture(scope="function")
#     async def simulation(self):
#         async for _ in setup_full_system(test_constants):
#             yield _
#
#     @pytest.mark.asyncio
#     async def test_simulation_1(self, simulation):
#         node1, node2, _, _, _, _, _, server1 = simulation
#         # await asyncio.sleep(1)
#         await server1.start_client(PeerInfo("localhost", uint16(21238)))
#         # Use node2 to test node communication, since only node1 extends the chain.
#         await time_out_assert(500, node_height_at_least, True, node2, 10)
#
#         # Wait additional 2 minutes to get a compact block.
#         # max_height = node1.full_node.blockchain.lca_block.height
#
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
