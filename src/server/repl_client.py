# import asyncio
# import logging
# import sys
# from src.full_node import FullNode
# from src.server.server import ChiaServer
# from src.util.network import parse_host_port, create_node_id
# from src.server.outbound_message import NodeType
# from src.types.peer_info import PeerInfo
# from src.store.full_node_store import FullNodeStore
# from src.blockchain import Blockchain


# async def start_client_to_full_node(host, port):
#     store = FullNodeStore()
#     await store.initialize()
#     blockchain = Blockchain(store)
#     await blockchain.initialize()
#     full_node = FullNode(store, blockchain)
#     server = ChiaServer(9000, full_node, NodeType.FULL_NODE)
#     res = await server.start_client(PeerInfo(host, port, create_node_id(NodeType.FULL_NODE)), None)
