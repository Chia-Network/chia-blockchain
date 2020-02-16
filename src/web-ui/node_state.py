from aiohttp import client_exceptions
from src.rpc.rpc_client import RpcClient


async def init_rpc(app):
    node = {}
    node['connectionCount'] = 0

    try:
        rpc_client: RpcClient = await RpcClient.create(app['config']['rpc_port'])
        connections = await rpc_client.get_connections()
        c = len(connections)
        rpc_client.close()

        node['connectionCount'] = c
        node['state'] = 'Running'

    except client_exceptions.ClientConnectorError:
        node['state'] = 'Not running'

    finally:
        app['node'] = node
