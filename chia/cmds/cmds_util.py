from pathlib import Path
from typing import Any, Callable, Dict, Optional, Type

from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.rpc_client import RpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_submission_status import MempoolSubmissionStatus
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.wallet.transaction_record import TransactionRecord

NODE_TYPES: Dict[str, Type[RpcClient]] = {
    "farmer": FarmerRpcClient,
    "wallet": WalletRpcClient,
    "full_node": FullNodeRpcClient,
    "harvester": HarvesterRpcClient,
}


def transaction_submitted_msg(tx: TransactionRecord) -> str:
    sent_to = [MempoolSubmissionStatus(s[0], s[1], s[2]).to_json_dict_convenience() for s in tx.sent_to]
    return f"Transaction submitted to nodes: {sent_to}"


def transaction_status_msg(fingerprint: int, tx_id: bytes32) -> str:
    return f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}' to get status"


async def check_client_connection(rpc_client: RpcClient, node_type: str, rpc_port: int) -> bool:
    from aiohttp import ClientConnectorError

    try:
        await rpc_client.healthz()
    except ClientConnectorError:
        print(f"Connection error. Check if {node_type.replace('_', ' ')} rpc is running at {rpc_port}")
        print(f"This is normal if {node_type.replace('_', ' ')} is still starting up")
        return False
    return True


async def execute_with_any_node(
    node_type: str,
    rpc_port: Optional[int],
    function: Callable,
    root_path: Path = DEFAULT_ROOT_PATH,
    *args,
) -> Any:
    from chia.util.config import load_config
    from chia.util.ints import uint16

    if node_type not in NODE_TYPES.keys():
        print(f"Invalid node type: {node_type}")
        return
    # load variables from config file
    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    if rpc_port is None:
        rpc_port = config[node_type]["rpc_port"]
    # select node client type based on string
    node_client_type = NODE_TYPES[node_type]
    result = None
    try:
        node_client = await node_client_type.create(self_hostname, uint16(rpc_port), root_path, config)
        # check if we can connect to node, this makes the code cleaner
        if await check_client_connection(node_client, node_type, rpc_port):
            result = await function(node_client, config, *args)
    finally:
        if node_client is not None:
            node_client.close()
            await node_client.await_closed()
    return result
