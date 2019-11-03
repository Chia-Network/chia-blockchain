# import asyncio
# import logging
# import sys
# from src.full_node import FullNode
# from src.server.server import ChiaServer
# from src.util.network import parse_host_port
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
#     res = await server.start_client(PeerInfo("127.0.0.1", 8004, bytes.fromhex("b2c5ed761a9a1d776e6bfa75f751b2fb110a62d87bec9fe4c9c904ab9532c8e3"),
#                                     NodeType.FULL_NODE, None)
