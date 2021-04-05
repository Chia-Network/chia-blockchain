import asyncio

import aiohttp
import click

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16


async def netstorge_async(rpc_port: int, delta_block_height: str, start: str) -> None:
    """
    Calculates the estimated space on the network given two block header hashes.
    """
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)

        if delta_block_height:
            if start == "":
                blockchain_state = await client.get_blockchain_state()
                if blockchain_state["peak"] is None:
                    print("No blocks in blockchain")
                    client.close()
                    await client.await_closed()
                    return None

                newer_block_height = blockchain_state["peak"].height
            else:
                newer_block = await client.get_block_record(hexstr_to_bytes(start))
                if newer_block is None:
                    print("Block header hash", start, "not found.")
                    client.close()
                    await client.await_closed()
                    return None
                else:
                    print("newer_height", newer_block.height)
                    newer_block_height = newer_block.height

            newer_block_header = await client.get_block_record_by_height(newer_block_height)
            older_block_height = max(0, newer_block_height - int(delta_block_height))
            older_block_header = await client.get_block_record_by_height(older_block_height)
            network_space_bytes_estimate = await client.get_network_space(
                newer_block_header.header_hash, older_block_header.header_hash
            )
            print(
                "Older Block\n"
                f"Block Height: {older_block_header.height}\n"
                f"Weight:           {older_block_header.weight}\n"
                f"VDF Iterations:   {older_block_header.total_iters}\n"
                f"Header Hash:      0x{older_block_header.header_hash}\n"
            )
            print(
                "Newer Block\n"
                f"Block Height: {newer_block_header.height}\n"
                f"Weight:           {newer_block_header.weight}\n"
                f"VDF Iterations:   {newer_block_header.total_iters}\n"
                f"Header Hash:      0x{newer_block_header.header_hash}\n"
            )
            network_space_terabytes_estimate = network_space_bytes_estimate / 1024 ** 4
            if network_space_terabytes_estimate > 1024:
                print(f"The network has an estimated {network_space_terabytes_estimate / 1024:.3f} PiB")
            else:
                print(f"The network has an estimated {network_space_terabytes_estimate:.3f} TiB")

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


@click.command("netspace", short_help="Estimate total farmed space on the network")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml. "
        "[default: 8555]"
    ),
    type=int,
    default=None,
)
@click.option(
    "-d",
    "--delta-block-height",
    help=(
        "Compare a block X blocks older to estimate total network space. "
        "Defaults to 1000 blocks (~5.2 hours) and Peak block as the starting block. "
        "Use --start BLOCK_HEIGHT to specify starting block. "
        "Use 192 blocks to estimate over the last hour."
    ),
    type=str,
    default="1000",
)
@click.option(
    "-s",
    "--start",
    help="Newest block used to calculate estimated total network space. Defaults to Peak block.",
    type=str,
    default="",
)
def netspace_cmd(rpc_port: int, delta_block_height: str, start: str) -> None:
    """
    Calculates the estimated space on the network given two block header hashes.
    """
    asyncio.run(netstorge_async(rpc_port, delta_block_height, start))
