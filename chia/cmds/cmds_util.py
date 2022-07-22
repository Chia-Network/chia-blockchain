from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple, Type

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


async def get_any_node_client(
    node_type: str,
    rpc_port: Optional[int] = None,
    root_path: Path = DEFAULT_ROOT_PATH,
    fingerprint: Optional[int] = None,
) -> AsyncIterator[Tuple[Any, Dict[str, Any], Optional[int]]]:
    # in the return the dict is the config & the first element is the rpc client.
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
    try:
        node_client = await node_client_type.create(self_hostname, uint16(rpc_port), root_path, config)
        # check if we can connect to node, this makes the code cleaner
        if await check_client_connection(node_client, node_type, rpc_port):
            # if we are a wallet, attempt to login with fingerprint
            if node_client_type == WalletRpcClient:
                wallet_and_f = await get_wallet(node_client, fingerprint=fingerprint)
                if wallet_and_f is not None:
                    node_client, fingerprint = wallet_and_f
                    yield node_client, config, fingerprint
            else:
                yield node_client, config, fingerprint
    finally:
        if node_client is not None:
            node_client.close()
            await node_client.await_closed()


async def get_wallet(wallet_client: WalletRpcClient, fingerprint: int = None) -> Optional[Tuple[WalletRpcClient, int]]:
    if fingerprint is not None:
        fingerprints = [fingerprint]
    else:
        fingerprints = await wallet_client.get_public_keys()
    if len(fingerprints) == 0:
        print("No keys loaded. Run 'chia keys generate' or import a key")
        return None
    if len(fingerprints) == 1:
        fingerprint = fingerprints[0]
    if fingerprint is not None:
        log_in_response = await wallet_client.log_in(fingerprint)
    else:
        logged_in_fingerprint: Optional[int] = await wallet_client.get_logged_in_fingerprint()
        spacing: str = "  " if logged_in_fingerprint is not None else ""
        current_sync_status: str = ""
        if logged_in_fingerprint is not None:
            if await wallet_client.get_synced():
                current_sync_status = "Synced"
            elif await wallet_client.get_sync_status():
                current_sync_status = "Syncing"
            else:
                current_sync_status = "Not Synced"
        print("Wallet keys:")
        for i, fp in enumerate(fingerprints):
            row: str = f"{i+1}) "
            row += "* " if fp == logged_in_fingerprint else spacing
            row += f"{fp}"
            if fp == logged_in_fingerprint and len(current_sync_status) > 0:
                row += f" ({current_sync_status})"
            print(row)
        val = None
        prompt: str = (
            f"Choose a wallet key [1-{len(fingerprints)}] ('q' to quit, or Enter to use {logged_in_fingerprint}): "
        )
        while val is None:
            val = input(prompt)
            if val == "q":
                return None
            elif val == "" and logged_in_fingerprint is not None:
                fingerprint = logged_in_fingerprint
                break
            elif not val.isdigit():
                val = None
            else:
                index = int(val) - 1
                if index < 0 or index >= len(fingerprints):
                    print("Invalid value")
                    val = None
                    continue
                else:
                    fingerprint = fingerprints[index]
        assert fingerprint is not None
        log_in_response = await wallet_client.log_in(fingerprint)

    if log_in_response["success"] is False:
        print(f"Login failed: {log_in_response}")
        return None
    return wallet_client, fingerprint
