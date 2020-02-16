from aiohttp import client_exceptions
from src.rpc.rpc_client import RpcClient
from src.server.outbound_message import NodeType


async def query_node(app):
    node = {}
    node['title'] = 'Chia Full Node'

    try:
        rpc_client: RpcClient = await RpcClient.create(app['config']['rpc_port'])
        connections = await rpc_client.get_connections()
        for con in connections:
            con['type_name'] = NodeType(con['type']).name

        blockchain_state = await rpc_client.get_blockchain_state()
        rpc_client.close()

        node['connections'] = connections
        node['blockchain_state'] = blockchain_state
        node['state'] = 'Running'

    except client_exceptions.ClientConnectorError:
        node['state'] = 'Not running'

    finally:
        app['node'] = node
