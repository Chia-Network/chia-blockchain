from pathlib import Path
from typing import Any, Callable, Dict, Optional, Type

from chia.rpc.rpc_client import RpcClient
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient

NODE_TYPES: Dict[str, Type[RpcClient]] = {
    "farmer": FarmerRpcClient,
    "wallet": WalletRpcClient,
    "full_node": FullNodeRpcClient,
    "harvester": HarvesterRpcClient,
}


async def add_node_connection(rpc_client: RpcClient, add_connection: str) -> None:
    if ":" not in add_connection:
        print("Enter a valid IP and port in the following format: 10.5.4.3:8000")
    else:
        ip, port = (
            ":".join(add_connection.split(":")[:-1]),
            add_connection.split(":")[-1],
        )
        print(f"Connecting to {ip}, {port}")
        try:
            await rpc_client.open_connection(ip, int(port))
        except Exception:
            print(f"Failed to connect to {ip}:{port}")


async def remove_node_connection(rpc_client: RpcClient, remove_connection: str) -> None:
    from chia.server.outbound_message import NodeType

    result_txt = ""
    if len(remove_connection) != 8:
        result_txt = "Invalid NodeID. Do not include '.'"
    else:
        connections = await rpc_client.get_connections()
        for con in connections:
            if remove_connection == con["node_id"].hex()[:8]:
                print("Attempting to disconnect", "NodeID", remove_connection)
                try:
                    await rpc_client.close_connection(con["node_id"])
                except Exception:
                    result_txt = f"Failed to disconnect NodeID {remove_connection}"
                else:
                    result_txt = f"NodeID {remove_connection}... {NodeType(con['type']).name} "
                    f"{con['peer_host']} disconnected"
            elif result_txt == "":
                result_txt = f"NodeID {remove_connection}... not found"
    print(result_txt)


async def print_connections(rpc_client: RpcClient, trusted_peers: Dict[str, Any]) -> None:
    import time

    from chia.server.outbound_message import NodeType
    from chia.util.network import is_trusted_inner

    connections = await rpc_client.get_connections()
    print("Connections:")
    print("Type      IP                                     Ports       NodeID      Last Connect" + "      MiB Up|Dwn")
    for con in connections:
        last_connect_tuple = time.struct_time(time.localtime(con["last_message_time"]))
        last_connect = time.strftime("%b %d %T", last_connect_tuple)
        mb_down = con["bytes_read"] / (1024 * 1024)
        mb_up = con["bytes_written"] / (1024 * 1024)

        host = con["peer_host"]
        # Strip IPv6 brackets
        host = host.strip("[]")

        trusted: bool = is_trusted_inner(host, con["node_id"], trusted_peers, False)
        # Nodetype length is 9 because INTRODUCER will be deprecated
        if NodeType(con["type"]) is NodeType.FULL_NODE:
            peak_height = con.get("peak_height", None)
            connection_peak_hash = con.get("peak_hash", None)
            if connection_peak_hash is None:
                connection_peak_hash = "No Info"
            else:
                if connection_peak_hash.startswith(("0x", "0X")):
                    connection_peak_hash = connection_peak_hash[2:]
                connection_peak_hash = f"{connection_peak_hash[:8]}..."
            con_str = (
                f"{NodeType(con['type']).name:9} {host:38} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
                f"\n                                                 "
            )
            if peak_height is not None:
                con_str += f"-Height: {peak_height:8.0f}    -Hash: {connection_peak_hash}"
            else:
                con_str += f"-Height: No Info    -Hash: {connection_peak_hash}"
            # Only show when Trusted is True
            if trusted:
                con_str += f"    -Trusted: {trusted}"
        else:
            con_str = (
                f"{NodeType(con['type']).name:9} {host:38} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
            )
        print(con_str)


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
    import traceback


    from chia.util.config import load_config
    from chia.util.ints import uint16

    if node_type not in NODE_TYPES.keys():
        print(f"Invalid node type: {node_type}")
        return
    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    if rpc_port is None:
        rpc_port = config[node_type]["rpc_port"]
    node_client_type = NODE_TYPES[node_type]
    result = None
    try:
        node_client = await node_client_type.create(self_hostname, uint16(rpc_port), root_path, config)
        if check_client_connection(node_client, node_type, rpc_port):
            result = await function(node_client, config, *args)
    finally:
        if node_client is not None:
            node_client.close()
            await node_client.await_closed()
    return result


async def peer_async(
        rpc_client: RpcClient,
        config: Dict[str, Any],
        show_connections: bool,
        add_connection: str,
        remove_connection: str,
        # trusted_peers: Dict[str, Any],
) -> None:
    # Check or edit node connections
    if show_connections:
        trusted_peers: Dict[str, Any] = config["full_node"].get("trusted_peers", {})
        await print_connections(rpc_client, trusted_peers)
        # if called together with state, leave a blank line
    if add_connection:
        await add_node_connection(rpc_client, add_connection)
    if remove_connection:
        await remove_node_connection(rpc_client, remove_connection)
