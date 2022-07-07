from typing import Dict, Optional

import click

from chia.util.network import is_trusted_inner


async def print_connections(client, time, NodeType, trusted_peers: Dict[str, str]) -> None:
    connections = await client.get_connections()
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
                con_str += f"-Height: {peak_height:8.0f}    -Hash: {connection_peak_hash}    -Trusted: {trusted}"
            else:
                con_str += f"-Height: No Info    -Hash: {connection_peak_hash}     -Trusted: {trusted}"
        else:
            con_str = (
                f"{NodeType(con['type']).name:9} {host:38} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
            )
        print(con_str)


async def peer_async(
    show_connections: bool,
    add_connection: str,
    remove_connection: str,
    rpc_port: Optional[int],
) -> None:
    import time
    import traceback

    import aiohttp

    from chia.rpc.full_node_rpc_client import FullNodeRpcClient
    from chia.server.outbound_message import NodeType
    from chia.util.config import load_config
    from chia.util.default_root import DEFAULT_ROOT_PATH
    from chia.util.ints import uint16

    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        rpc_port = config["full_node"]["rpc_port"]
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)

        if show_connections:
            trusted_peers: Dict[str, str] = config["full_node"].get("trusted_peers", {})
            await print_connections(client, time, NodeType, trusted_peers)
        if add_connection:
            if ":" not in add_connection:
                print("Enter a valid IP and port in the following format: 10.5.4.3:8000")
            else:
                ip, port = (
                    ":".join(add_connection.split(":")[:-1]),
                    add_connection.split(":")[-1],
                )
                print(f"Connecting to {ip}, {port}")
                try:
                    await client.open_connection(ip, int(port))
                except Exception:
                    print(f"Failed to connect to {ip}:{port}")
        if remove_connection:
            result_txt = ""
            if len(remove_connection) != 8:
                result_txt = "Invalid NodeID. Do not include '.'"
            else:
                connections = await client.get_connections()
                for con in connections:
                    if remove_connection == con["node_id"].hex()[:8]:
                        print("Attempting to disconnect", "NodeID", remove_connection)
                        try:
                            await client.close_connection(con["node_id"])
                        except Exception:
                            result_txt = f"Failed to disconnect NodeID {remove_connection}"
                        else:
                            result_txt = f"NodeID {remove_connection}... {NodeType(con['type']).name} "
                            f"{con['peer_host']} disconnected"
                    elif result_txt == "":
                        result_txt = f"NodeID {remove_connection}... not found"
            print(result_txt)
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {rpc_port}")
            print("This is normal if full node is still starting up")
        else:
            tb = traceback.format_exc()
            print(f"Exception from 'peer' {tb}")

    client.close()
    await client.await_closed()


@click.command("peer", short_help="Show, or modify peering connections", no_args_is_help=True)
@click.option(
    "-c", "--connections", help="List nodes connected to this Full Node", is_flag=True, type=bool, default=True
)
@click.option("-a", "--add-connection", help="Connect to another Full Node by ip:port", type=str, default="")
@click.option(
    "-r", "--remove-connection", help="Remove a Node by the first 8 characters of NodeID", type=str, default=""
)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
def peer_cmd(
    connections: bool,
    add_connection: str,
    remove_connection: str,
    rpc_port: Optional[int],
) -> None:
    import asyncio

    asyncio.run(
        peer_async(
            connections,
            add_connection,
            remove_connection,
            rpc_port,
        )
    )
