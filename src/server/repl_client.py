# import asyncio
# import logging
# import sys
# from src.full_node import FullNode
# from src.server.server import ChiaServer
# from src.util.network import parse_host_port, create_node_id
# from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
# from src.types.peer_info import PeerInfo
# from src.store.full_node_store import FullNodeStore
# from src.blockchain import Blockchain

# logging.basicConfig(format='Farmer %(name)-25s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
#                     level=logging.INFO,
#                     datefmt='%H:%M:%S'
#                     )
# log = logging.getLogger(__name__)

# async def start_client_to_full_node(host, port):
#     store = FullNodeStore()
#     await store.initialize()
#     blockchain = Blockchain(store)
#     await blockchain.initialize()
#     full_node = FullNode(store, blockchain)
#     server = ChiaServer(9000, full_node, NodeType.FULL_NODE)
#     res = await server.start_client(PeerInfo(host, port), None)
#     log.info("ASFd")
#     m = Message("block", {})
#     server.push_message(OutboundMessage(NodeType.FULL_NODE, m, Delivery.BROADCAST))
#     await server.await_closed()


# asyncio.run(start_client_to_full_node("127.0.0.1", 8444))
