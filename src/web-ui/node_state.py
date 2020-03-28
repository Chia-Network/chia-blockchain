from aiohttp import client_exceptions
from src.rpc.rpc_client import RpcClient
from src.server.outbound_message import NodeType
from src.util.ints import uint64
from typing import List, Optional, Dict
from src.types.header_block import SmallHeaderBlock
import datetime
import base64


async def query_node(port, pool_pks) -> dict:
    node = {}

    try:
        rpc_client: RpcClient = await RpcClient.create(port)

        connections = await rpc_client.get_connections()
        for con in connections:
            con['type_name'] = NodeType(con['type']).name
            node_id = con['node_id']
            con['node_id'] =node_id.hex()

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
            for pk in pool_pks
        ]

        latest_blocks = await get_latest_blocks(rpc_client, blockchain_state["tips"])

        rpc_client.close()

        node['connections'] = connections
        node['blockchain_state'] = blockchain_state
        node['pool_balances'] = pool_balances
        node['top_winners'] = top_winners
        node['our_winners'] = our_winners
        node['latest_blocks'] = latest_blocks
        node['state'] = 'Running'
        node['last_refresh'] = datetime.datetime.now()

    except client_exceptions.ClientConnectorError as e:
        node['state'] = 'Not running'
        print(e)

    except Exception as e1:
        print(str(e1))
        raise e1

    finally:
        return node


def find_block(block_list, blockid):
    for block in block_list:
        hash = str(block.challenge.proof_of_space_hash)
        if hash == blockid:
            return block

    return {}


def find_connection(connection_list, connectionid):
    for connection in connection_list:
        hash = str(connection['node_id'])
        if hash == connectionid:
            return connection

    return {}


async def get_latest_blocks(rpc_client: RpcClient, heads: List[SmallHeaderBlock]) -> List[SmallHeaderBlock]:
    added_blocks: List[SmallHeaderBlock] = []
    num_blocks = 10
    while len(added_blocks) < num_blocks and len(heads) > 0:
        heads = sorted(heads, key=lambda b: b.height, reverse=True)
        max_block = heads[0]
        if max_block not in added_blocks:
            added_blocks.append(max_block)
        heads.remove(max_block)
        prev: Optional[SmallHeaderBlock] = await rpc_client.get_header(max_block.prev_header_hash)
        if prev is not None:
            heads.append(prev)

    return added_blocks


async def stop_node(port) -> None:
    try:
        rpc_client: RpcClient = await RpcClient.create(port)
        await rpc_client.stop_node()
        rpc_client.close()

    except client_exceptions.ClientConnectorError:
        print("exception occured while stopping node")


async def disconnect_peer(port, node_id) -> None:
    try:
        rpc_client: RpcClient = await RpcClient.create(port)
        await rpc_client.close_connection(node_id)
        rpc_client.close()

    except client_exceptions.ClientConnectorError:
        print("exception occured while disconnecting peer")