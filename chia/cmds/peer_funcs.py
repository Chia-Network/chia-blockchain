from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

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


async def print_connections(
    rpc_client: RpcClient,
    trusted_peers: Dict[str, Any],
    json_output: bool = False,
    show_wide: bool = False,
) -> None:
    import time

    from chia.server.outbound_message import NodeType

    connections = bytes_to_str(await rpc_client.get_connections())

    if json_output:
        print(json.dumps(connections, indent=4))
        return

    if not connections:
        print("No connections available.")
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

    default_columns = [
        f"{'Type':<{type_width}}",
        f"{'IP':<{ip_width}}",
        f"{'Ports':<{port_width}}",
        f"{'MiB ↑/↓':<{mib_up_down_width}}",
        f"{'Height':<{height_width}}",
    ]

    wide_columns = []
    if show_wide:
        wide_columns = [
            f"{'NodeID':<{node_id_width}}",
            f"{'Last Connect':<{last_connect_width}}",
            f"{'Peak Hash':<{hash_width}}",
        ]

    all_columns = default_columns + wide_columns

    print("╭" + "┬".join("─" * len(col) for col in all_columns) + "╮")
    print("│" + "│".join(all_columns) + "│")
    print("├" + "┼".join("─" * len(col) for col in all_columns) + "┤")

    for con in connections:
        ports_str = f"{con['peer_port']}/{con['peer_server_port']}"
        ports_str = f"{ports_str:<{port_width}}"
        peak_height = con.get("peak_height")
        peak_height_str = f"{peak_height:<{height_width}}" if peak_height is not None else "No Info "

        connection_peak_hash = con.get("peak_hash")
        connection_peak_hash_str = (
            f"{connection_peak_hash[:8]}… "
            if connection_peak_hash and connection_peak_hash.startswith(("0x", "0X"))
            else "No Info   "
        )

        row = [
            f"{NodeType(con['type']).name:<{type_width}}",
            f"{con['peer_host']:<{ip_width}}",
            ports_str,
            f"{con['bytes_written'] / (1024 * 1024):.1f}/{con['bytes_read'] / (1024 * 1024):.1f} ",
            peak_height_str,
        ]

        if show_wide:
            row += [
                f"{con['node_id'][:8]}… ",
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(con['last_message_time'])):<{last_connect_width}}",
                connection_peak_hash_str,
            ]

        print("│" + "│".join(row) + "│")

    print("╰" + "┴".join("─" * len(col) for col in all_columns) + "╯")


async def peer_async(
    node_type: str,
    rpc_port: Optional[int],
    root_path: Path,
    show_connections: bool,
    add_connection: str,
    remove_connection: str,
    json_output: bool,
    show_wide: bool,
) -> None:
    client_type = NODE_TYPES[node_type]
    async with get_any_service_client(client_type, rpc_port, root_path) as (rpc_client, config):
        # Check or edit node connections
        if show_connections:
            trusted_peers: Dict[str, Any] = config["full_node"].get("trusted_peers", {})
            await print_connections(rpc_client, trusted_peers, json_output, show_wide)
            # if called together with state, leave a blank line
        if add_connection:
            await add_node_connection(rpc_client, add_connection)
        if remove_connection:
            await remove_node_connection(rpc_client, remove_connection)
