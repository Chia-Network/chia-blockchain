import aiohttp
import asyncio
import time
from time import struct_time, localtime
import datetime

# from src.server.connection import NodeType
# from src.types.header_block import HeaderBlock
from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes
# from src.util.ints import uint32
# from src.util.config import str2bool
# from src.full_node.full_node import FullNode


def make_parser(parser):

    parser.add_argument(
        "-p",
        "--rpc-port",
        help=f"Set the port where the Full Node is hosting the RPC interface. See the rpc_port "
        f"under full_node in config.yaml. Defaults to 8555",
        type=int,
        default=8555,
    )
    parser.add_argument(
        "-o",
        "--old-block",
        help="Older block hash used to calculate estimated total network space.",
        type=str,
        default="",
    )
    parser.add_argument(
        "-n",
        "--new-block",
        help="Newer block hash used to calculate estimated total network space.",
        type=str,
        default="",
    )
    parser.add_argument(
        "-d",
        "--delta-block-height",
        help="Compare LCA to a block X blocks older.",
        type=str,
        default="",
    )
    parser.set_defaults(function=netspace)


def human_local_time(timestamp):
    time_local = struct_time(localtime(timestamp))
    return time.strftime("%a %b %d %Y %T %Z", time_local)

async def compare_block_headers(client, oldblock_hash, newblock_hash):
    block_older = await client.get_header(hexstr_to_bytes(oldblock_hash))
    block_newer = await client.get_header(hexstr_to_bytes(newblock_hash))
    if block_older is not None:
        block_older_time_string = human_local_time(block_older.data.timestamp)
        block_newer_time_string = human_local_time(block_newer.data.timestamp)
        elapsed_time_seconds = block_newer.data.timestamp - block_older.data.timestamp
        time_delta = datetime.timedelta(seconds=elapsed_time_seconds)
        print("Older Block", block_older.data.height, ":")
        print(
            f"Header Hash            0x{oldblock_hash}\n"
            f"Timestamp              {block_older_time_string}\n"
            f"Weight                 {block_older.data.weight}\n"
            f"Total VDF Iterations   {block_older.data.total_iters}\n"
        )
        print("Newer Block", block_newer.data.height, ":")
        print(
            f"Header Hash            0x{newblock_hash}\n"
            f"Timestamp              {block_newer_time_string}\n"
            f"Weight                 {block_newer.data.weight}\n"
            f"Total VDF Iterations   {block_newer.data.total_iters}\n"
        )
        delta_weight = block_newer.data.weight - block_older.data.weight
        delta_iters = block_newer.data.total_iters - block_older.data.total_iters
        weight_div_iters = delta_weight / delta_iters
        network_space_constant = 2**32  # 2^32
        network_space_bytes_estimate = weight_div_iters * network_space_constant
        network_space_terrabytes_estimate = network_space_bytes_estimate / 1024**4
        print(
            f"The elapsed time between blocks is reported as {time_delta}.\n"
            f"The network has an estimated {network_space_terrabytes_estimate:.2f}TB"
        )
    else:
        print("Block with header hash", oldblock_hash, "not found.")

async def netstorge_async(args, parser):

    # add config.yaml check for rpc-port
    # add help on failure/no args
    # add "x blocks back" by block height
    # self.blockchain.height_to_hash[block.height]
    # print(args)
    try:
        client = await RpcClient.create(args.rpc_port)

        # print (args.blocks)
        if args.old_block != "":
            await compare_block_headers(client, args.old_block, args.new_block)
        if args.delta_block_height:
            # Get lca
            blockchain_state = await client.get_blockchain_state()
            lca_block_hash = str(blockchain_state["lca"].header_hash)
            lca_block_height = blockchain_state["lca"].data.height
            older_block_height = lca_block_height - int(args.delta_block_height)
            print(f"LCA Block Height is {lca_block_height} - Comparing to {older_block_height}\n")
            older_block_header = await client.get_header_by_height(older_block_height)
            older_block_header_hash = str(older_block_header.get_hash())
            await compare_block_headers(client, older_block_header_hash, lca_block_hash)

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


def netspace(args, parser):
    return asyncio.run(netstorge_async(args, parser))
