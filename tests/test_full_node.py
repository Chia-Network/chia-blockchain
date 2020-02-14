# import asyncio

# import pytest

# from src.protocols import full_node_protocol
# from src.types.peer_info import PeerInfo
# from src.util.ints import uint16
# from tests.setup_nodes import setup_two_nodes, test_constants, bt


# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop


# class TestFullNode:
#     @pytest.fixture(scope="function")
#     async def two_nodes(self):
#         async for _ in setup_two_nodes():
#             yield _
#
# @pytest.mark.asyncio
# async def test_unfinished_blocks_load(self, two_nodes):
#     num_blocks = 10
#     full_node_1, full_node_2, server_1, server_2 = two_nodes
#     blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)

#     for i in range(1, num_blocks - 1):
#         async for _ in full_node_1.respond_block(
#             full_node_protocol.RespondBlock(blocks[i])
#         ):
#             pass

#     await server_2.start_client(
#         PeerInfo(server_1._host, uint16(server_1._port)), None
#     )
# await asyncio.sleep(2)  # Allow connections to get made
