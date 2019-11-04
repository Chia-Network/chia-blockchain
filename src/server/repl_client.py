# import asyncio
# import logging
# import sys
# from src.full_node import FullNode
# from src.server.server import ChiaServer
# from src.util.network import parse_host_port, create_node_id
# from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
# from src.types.peer_info import PeerInfo
# from src.db.database import FullNodeStore
# from src.blockchain import Blockchain


# async def start_client_to_full_node(host, port):
#     store = FullNodeStore()
#     await store.initialize()
#     blockchain = Blockchain(store)
#     await blockchain.initialize()
#     full_node = FullNode(store, blockchain)
#     server = ChiaServer(9000, full_node, NodeType.FULL_NODE)
#     res = await server.start_client(PeerInfo(host, port), None)
#     print(res)
#     m = Message("block", {})
#     server.push_message(OutboundMessage(NodeType.FULL_NODE, m, Delivery.BROADCAST))
#     await server.await_closed()


# asyncio.run(start_client_to_full_node("beast.44monty.chia.net", 8444))
