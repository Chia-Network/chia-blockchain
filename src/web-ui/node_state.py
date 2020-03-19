from aiohttp import client_exceptions
from typing import Dict
from src.rpc.rpc_client import RpcClient
from src.server.outbound_message import NodeType
from src.util.ints import uint64


async def query_node(app):
    node = {}

    try:
        rpc_client: RpcClient = await RpcClient.create(app['config']['rpc_port'])
        connections = await rpc_client.get_connections()
        for con in connections:
            con['type_name'] = NodeType(con['type']).name

        blockchain_state = await rpc_client.get_blockchain_state()
        pool_balances = await rpc_client.get_pool_balances()

        coin_balances: Dict[
            bytes, uint64
        ] = pool_balances

        top_winners = sorted(
            [(rewards, key, bytes(key).hex()) for key, rewards in coin_balances.items()],
            reverse=True,
        )[: 10]

        our_winners = [
            (coin_balances[bytes(pk)], bytes(pk), bytes(pk).hex())
            if bytes(pk) in coin_balances
            else (0, bytes(pk), bytes(pk).hex())
            for pk in app['key_config']['pool_pks']
        ]

        rpc_client.close()

        node['connections'] = connections
        node['blockchain_state'] = blockchain_state
        node['pool_balances'] = pool_balances
        node['top_winners'] = top_winners
        node['our_winners'] = our_winners
        node['state'] = 'Running'

    except client_exceptions.ClientConnectorError:
        node['state'] = 'Not running'

    finally:
        app['node'] = node
        app['ready'] = True


def find_block(block_list, blockid):
    for block in block_list:
        hash = str(block.challenge.proof_of_space_hash)
        if hash == blockid:
            return block

    return {}
