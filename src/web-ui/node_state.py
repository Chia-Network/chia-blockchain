from aiohttp import client_exceptions
from src.rpc.rpc_client import RpcClient


async def init_rpc(app):
    node = {}
    node['title'] = 'Chia Full Node'

    try:
        rpc_client: RpcClient = await RpcClient.create(app['config']['rpc_port'])
        connections = await rpc_client.get_connections()
        blockchain_state = await rpc_client.get_blockchain_state()
        rpc_client.close()

        node['connectionCount'] = len(connections)
        node['connections'] = connections
        node['blockchain_state'] = blockchain_state
        node['state'] = 'Running'

    except client_exceptions.ClientConnectorError:
        node['state'] = 'Not running'

    finally:
        app['node'] = node
