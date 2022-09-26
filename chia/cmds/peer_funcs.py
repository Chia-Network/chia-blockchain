from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.rpc_client import RpcClient


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
                    result_txt = (
                        f"NodeID {remove_connection}... {NodeType(con['type']).name} {con['peer_host']} disconnected"
                    )
            elif result_txt == "":
                result_txt = f"NodeID {remove_connection}... not found"
    print(result_txt)


async def print_connections(rpc_client: RpcClient, trusted_peers: Dict[str, Any]) -> None:
    import time

    from chia.server.outbound_message import NodeType
    from chia.util.network import is_trusted_inner

    connections = await rpc_client.get_connections()
    print("Connections:")
    print("Type      IP                                      Ports       NodeID      Last Connect" + "      MiB Up|Dwn")
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
                f"{NodeType(con['type']).name:9} {host:39} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
                f"\n                                                  "
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
                f"{NodeType(con['type']).name:9} {host:39} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
            )
        print(con_str)


async def peer_async(
    node_type: str,
    rpc_port: Optional[int],
    root_path: Path,
    show_connections: bool,
    add_connection: str,
    remove_connection: str,
) -> None:
    rpc_client: Optional[RpcClient]
    async with get_any_service_client(node_type, rpc_port, root_path) as node_config_fp:
        rpc_client, config, _ = node_config_fp
        if rpc_client is not None:
            # Check or edit node connections
            if show_connections:
                trusted_peers: Dict[str, Any] = config["full_node"].get("trusted_peers", {})
                await print_connections(rpc_client, trusted_peers)
                # if called together with state, leave a blank line
            if add_connection:
                await add_node_connection(rpc_client, add_connection)
            if remove_connection:
                await remove_node_connection(rpc_client, remove_connection)
