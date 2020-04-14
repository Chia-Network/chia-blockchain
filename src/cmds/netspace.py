import aiohttp
import asyncio
import time
from time import struct_time, localtime
import datetime

# from src.server.connection import NodeType
# from src.types.header_block import HeaderBlock
from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint32
# from src.util.config import str2bool
from src.full_node.full_node import FullNode


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


async def get_total_miniters(rpc_client, old_block, new_block):
    """
    Calculates the sum of min_iters from all blocks starting from old and up to and including
    new_block.
    # TODO: compute real min_iters for multiple epochs, using height RPC
    """
    old_block_parent = await rpc_client.get_header(old_block.prev_header_hash)
    new_block_parent = await rpc_client.get_header(new_block.prev_header_hash)
    old_diff = old_block.weight - old_block_parent.weight
    new_diff = new_block.weight - new_block_parent.weight
    mi1 = calculate_min_iters_from_iterations(
        old_block.proof_of_space, old_diff, old_block.proof_of_time.number_of_iterations
    )
    mi2 = calculate_min_iters_from_iterations(
        new_block.proof_of_space, new_diff, new_block.proof_of_time.number_of_iterations
    )
    return (new_block.height - old_block.height) * ((mi2 + mi1) / 2)


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
            block_older = await client.get_block(hexstr_to_bytes(args.old_block))
            block_newer = await client.get_block(hexstr_to_bytes(args.new_block))
            if block_older is not None:
                block_older_time_string = human_local_time(block_older.header.data.timestamp)
                block_newer_time_string = human_local_time(block_newer.header.data.timestamp)
                elapsed_time_seconds = block_newer.header.data.timestamp - block_older.header.data.timestamp
                time_delta = datetime.timedelta(seconds=elapsed_time_seconds)
                print("Older Block", block_older.header.data.height, ":")
                print(
                    f"Header Hash            0x{args.old_block}\n"
                    f"Timestamp              {block_older_time_string}\n"
                    f"Weight                 {block_older.header.data.weight}\n"
                    f"Total VDF Iterations   {block_older.header.data.total_iters}\n"
                )
                print("Newer Block", block_newer.header.data.height, ":")
                print(
                    f"Header Hash            0x{args.new_block}\n"
                    f"Timestamp              {block_newer_time_string}\n"
                    f"Weight                 {block_newer.header.data.weight}\n"
                    f"Total VDF Iterations   {block_newer.header.data.total_iters}\n"
                )
                delta_weight = block_newer.header.data.weight - block_older.header.data.weight
                delta_iters = block_newer.header.data.total_iters - block_older.header.data.total_iters
                weight_div_iters = delta_weight / delta_iters
                network_space_constant = 2**32  # 2^32
                network_space_bytes_estimate = weight_div_iters * network_space_constant
                network_space_terrabytes_estimate = network_space_bytes_estimate / 1024**4
                print(
                    f"The elapsed time between blocks is reported as {time_delta}.\n"
                    f"The network has an estimated {network_space_terrabytes_estimate:.2f}TB"
                )
            else:
                print("Block with header hash", args.old_block, "not found.")
        if args.delta_block_height:
            # Get lca
            blockchain_state = await client.get_blockchain_state()
            lca_block_hash = blockchain_state["lca"].header_hash
            lca_block_height = blockchain_state["lca"].data.height
            older_block_height = lca_block_height - int(args.delta_block_height)
            #print (lca_block_hash)
            print(f"LCA Block Height is {lca_block_height} - Comparing to {older_block_height}")
            older_block = await client.get_header_by_height(older_block_height)
            print ("Older block previous hash", older_block.header.data.prev_header_hash)
            # subtract delta
            # Call calculate function

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()


def netspace(args, parser):
    return asyncio.run(netstorge_async(args, parser))
