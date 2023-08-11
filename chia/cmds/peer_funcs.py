from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Dict, Optional

from chia.cmds.cmds_util import NODE_TYPES, get_any_service_client
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
            result = await rpc_client.open_connection(ip, int(port))
            err = result.get("error")
            if result["success"] is False or err is not None:
                print(err)
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


def bytes_to_str(data: List[Dict[Any, Any]]) -> List[Dict[Any, Any]]:
    new_data = []
    for item in data:
        new_item = {key: value.hex() if isinstance(value, bytes) else value for key, value in item.items()}
        new_data.append(new_item)
    return new_data


async def print_connections(rpc_client: RpcClient, trusted_peers: Dict[str, Any], json_output: bool = False) -> None:
    import time

    from chia.server.outbound_message import NodeType

    connections = bytes_to_str(await rpc_client.get_connections())
    if json_output:
        # Print the connections in JSON format
        print(json.dumps(connections, indent=4))
        return
    # Determine the width of each column
    type_width = max(len(NodeType(con["type"]).name) for con in connections) + 1
    ip_width = max(len(con["peer_host"]) for con in connections) + 1
    port_width = max(len(f"{con['peer_port']}/{con['peer_server_port']}") for con in connections) + 1
    node_id_width = 10  # Fixed width for node ID
    last_connect_width = 20  # Fixed width for last connect
    mib_up_down_width = (
        max(
            len(f"{con['bytes_written'] / (1024 * 1024):.1f}/{con['bytes_read'] / (1024 * 1024):.1f}")
            for con in connections
        )
        + 1
    )
    height_width = max(len(str(con.get("peak_height", "No Info"))) for con in connections) + 1
    hash_width = 10  # Fixed width for peak hash

    # Header definition
    header = f"{'Type':<{type_width}}│{'IP':<{ip_width}}│{'Ports':<{port_width}}│{'NodeID':<{node_id_width}}│{'Last Connect':<{last_connect_width}}│{'MiB ↑/↓':<{mib_up_down_width}}│{'Height':<{height_width}}│{'Peak Hash':<{hash_width}}"
    table_width = len(header)

    # Print the table header
    print(
        "╭"
        + "─" * (type_width)
        + "┬"
        + "─" * (ip_width)
        + "┬"
        + "─" * (port_width)
        + "┬"
        + "─" * (node_id_width)
        + "┬"
        + "─" * (last_connect_width)
        + "┬"
        + "─" * (mib_up_down_width)
        + "┬"
        + "─" * (height_width)
        + "┬"
        + "─" * (hash_width)
        + "╮"
    )
    print(f"│{header}│")
    print(
        "├"
        + "─" * (type_width)
        + "┼"
        + "─" * (ip_width)
        + "┼"
        + "─" * (port_width)
        + "┼"
        + "─" * (node_id_width)
        + "┼"
        + "─" * (last_connect_width)
        + "┼"
        + "─" * (mib_up_down_width)
        + "┼"
        + "─" * (height_width)
        + "┼"
        + "─" * (hash_width)
        + "┤"
    )

    # Print the table rows
    for con in connections:
        last_connect = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(con["last_message_time"]))
        peak_height = con.get("peak_height", "No Info")
        mib_up_down_str = f"{con['bytes_written'] / (1024 * 1024):.1f}/{con['bytes_read'] / (1024 * 1024):.1f}"
        ports_str = f"{con['peer_port']}/{con['peer_server_port']}"
        connection_peak_hash = con.get("peak_hash", "No Info")
        if connection_peak_hash and connection_peak_hash.startswith(("0x", "0X")):
            connection_peak_hash = f"{connection_peak_hash[2:10]}…"

        row_str = f"│{NodeType(con['type']).name:<{type_width}}│{con['peer_host']:<{ip_width}}│{ports_str:<{port_width}}│{con['node_id'][:8]}… │{last_connect:<{last_connect_width}}│{mib_up_down_str:<{mib_up_down_width}}│{peak_height:<{height_width}}│{connection_peak_hash:<{hash_width}}│"
        print(row_str)

    print(
        "╰"
        + "─" * (type_width)
        + "┴"
        + "─" * (ip_width)
        + "┴"
        + "─" * (port_width)
        + "┴"
        + "─" * (node_id_width)
        + "┴"
        + "─" * (last_connect_width)
        + "┴"
        + "─" * (mib_up_down_width)
        + "┴"
        + "─" * (height_width)
        + "┴"
        + "─" * (hash_width)
        + "╯"
    )


async def peer_async(
    node_type: str,
    rpc_port: Optional[int],
    root_path: Path,
    show_connections: bool,
    add_connection: str,
    remove_connection: str,
    json_output: bool,
) -> None:
    client_type = NODE_TYPES[node_type]
    async with get_any_service_client(client_type, rpc_port, root_path) as (rpc_client, config):
        # Check or edit node connections
        if show_connections:
            trusted_peers: Dict[str, Any] = config["full_node"].get("trusted_peers", {})
            await print_connections(rpc_client, trusted_peers, json_output)
            # if called together with state, leave a blank line
        if add_connection:
            await add_node_connection(rpc_client, add_connection)
        if remove_connection:
            await remove_node_connection(rpc_client, remove_connection)
