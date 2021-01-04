import aiohttp
import asyncio
import time
from time import struct_time, localtime
from src.util.config import load_config
from src.util.default_root import DEFAULT_ROOT_PATH

from src.rpc.full_node_rpc_client import FullNodeRpcClient


def make_parser(parser):

    parser.add_argument(
        "-d",
        "--delta-block-height",
        help="Compare a block X blocks older."
        + "Defaults to 192 sub-blocks (~1 hour) and Peak sub-block as the starting block."
        + "Use --start BLOCK_HEIGHT to specify starting block",
        type=str,
        default="192",
    )
    parser.add_argument(
        "-s",
        "--start",
        help="Newest block used to calculate estimated total network space. Defaults to Peak sub-block.",
        type=str,
        default="",
    )
    parser.add_argument(
        "-p",
        "--rpc-port",
        help="Set the port where the Full Node is hosting the RPC interface."
        + "See the rpc_port under full_node in config.yaml. Defaults to 8555",
        type=int,
    )
    parser.set_defaults(function=netspace)


def human_local_time(timestamp):
    time_local = struct_time(localtime(timestamp))
    return time.strftime("%a %b %d %Y %T %Z", time_local)


async def netstorge_async(args, parser):
    """
    Calculates the estimated space on the network given two block header hases
    # TODO: add help on failure/no args
    """
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if "rpc_port" not in args or args.rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        else:
            rpc_port = args.rpc_port
        client = await FullNodeRpcClient.create(self_hostname, rpc_port, DEFAULT_ROOT_PATH, config)

        # print (args.blocks)
        if args.delta_block_height:
            # Get lca or newer block
            if args.start == "":
                blockchain_state = await client.get_blockchain_state()
                if blockchain_state["peak"] is None:
                    print("No sub-blocks in blockchain")

                newer_block_height = blockchain_state["peak"].sub_block_height
            else:
                newer_block_height = int(args.start)  # Starting block height in args

            newer_block_header = await client.get_sub_block_record_by_sub_height(newer_block_height)
            older_block_height = max(0, newer_block_height - int(args.delta_block_height))
            older_block_header = await client.get_sub_block_record_by_sub_height(older_block_height)
            network_space_bytes_estimate = await client.get_network_space(
                newer_block_header.header_hash, older_block_header.header_hash
            )
            print(
                f"Older Sub-block Height: {older_block_header.sub_block_height}\n"
                f"Older Height: {older_block_header.height}\n"
                f"Header Hash: 0x{older_block_header.header_hash}\n"
                f"Weight:      {older_block_header.weight}\n"
                f"Total VDF\n"
                f"Iterations:  {older_block_header.total_iters}\n"
            )
            print(
                f"Newer Sub-block Height: {newer_block_header.sub_block_height}\n"
                f"Newer Height: {newer_block_header.height}\n"
                f"Header Hash: 0x{newer_block_header.header_hash}\n"
                f"Weight:      {newer_block_header.weight}\n"
                f"Total VDF\n"
                f"Iterations:  {newer_block_header.total_iters}\n"
            )
            network_space_terabytes_estimate = network_space_bytes_estimate / 1024 ** 4
            print(f"The network has an estimated {network_space_terabytes_estimate:.2f}TiB")

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


def netspace(args, parser):
    return asyncio.run(netstorge_async(args, parser))
