import aiohttp
import asyncio
import time
from time import struct_time, localtime
import datetime

from src.rpc.full_node_rpc_client import FullNodeRpcClient


def make_parser(parser):

    parser.add_argument(
        "-d",
        "--delta-block-height",
        help="Compare a block X blocks older."
        + "Defaults to 24 blocks and LCA as the starting block."
        + "Use --start BLOCK_HEIGHT to specify starting block",
        type=str,
        default="24",
    )
    parser.add_argument(
        "-s",
        "--start",
        help="Newest block used to calculate estimated total network space. Defaults to LCA.",
        type=str,
        default="",
    )
    parser.add_argument(
        "-p",
        "--rpc-port",
        help="Set the port where the Full Node is hosting the RPC interface."
        + "See the rpc_port under full_node in config.yaml. Defaults to 8555",
        type=int,
        default=8555,
    )
    parser.set_defaults(function=netspace)


def human_local_time(timestamp):
    time_local = struct_time(localtime(timestamp))
    return time.strftime("%a %b %d %Y %T %Z", time_local)


async def netstorge_async(args, parser):
    """
    Calculates the estimated space on the network given two block header hases
    # TODO: add config.yaml check for rpc-port
            add help on failure/no args
    """
    try:
        client = await FullNodeRpcClient.create(args.rpc_port)

        # print (args.blocks)
        if args.delta_block_height:
            # Get lca or newer block
            if args.start == "":
                blockchain_state = await client.get_blockchain_state()
                newer_block_height = blockchain_state["lca"].data.height
            else:
                newer_block_height = int(args.start)  # Starting block height in args
            newer_block_header = await client.get_header_by_height(newer_block_height)
            older_block_height = newer_block_height - int(args.delta_block_height)
            older_block_header = await client.get_header_by_height(older_block_height)
            newer_block_header_hash = str(newer_block_header.get_hash())
            older_block_header_hash = str(older_block_header.get_hash())
            elapsed_time = (
                newer_block_header.data.timestamp - older_block_header.data.timestamp
            )
            newer_block_time_string = human_local_time(
                newer_block_header.data.timestamp
            )
            older_block_time_string = human_local_time(
                older_block_header.data.timestamp
            )
            time_delta = datetime.timedelta(seconds=elapsed_time)
            network_space_bytes_estimate = await client.get_network_space(
                newer_block_header_hash, older_block_header_hash
            )
            print(
                f"Older Block: {older_block_header.data.height}\n"
                f"Header Hash: 0x{older_block_header_hash}\n"
                f"Timestamp:   {older_block_time_string}\n"
                f"Weight:      {older_block_header.data.weight}\n"
                f"Total VDF\n"
                f"Iterations:  {older_block_header.data.total_iters}\n"
            )
            print(
                f"Newer Block: {newer_block_header.data.height}\n"
                f"Header Hash: 0x{newer_block_header_hash}\n"
                f"Timestamp:   {newer_block_time_string}\n"
                f"Weight:      {newer_block_header.data.weight}\n"
                f"Total VDF\n"
                f"Iterations:  {newer_block_header.data.total_iters}\n"
            )
            network_space_terrabytes_estimate = network_space_bytes_estimate / 1024 ** 4
            print(
                f"The elapsed time between blocks is reported as {time_delta}.\n"
                f"The network has an estimated {network_space_terrabytes_estimate:.2f}TB"
            )

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


def netspace(args, parser):
    return asyncio.run(netstorge_async(args, parser))
