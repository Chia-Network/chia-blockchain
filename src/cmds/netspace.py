import aiohttp
import asyncio
import time
from time import struct_time, localtime
import datetime

from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes
from src.consensus.pot_iterations import calculate_min_iters_from_iterations


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
    block_older_header = await client.get_header(hexstr_to_bytes(oldblock_hash))
    block_newer_header = await client.get_header(hexstr_to_bytes(newblock_hash))
    if block_older_header is not None:
        block_older_time_string = human_local_time(
            block_older_header.data.timestamp
        )
        block_newer_time_string = human_local_time(
            block_newer_header.data.timestamp
        )
        elapsed_time_seconds = (
            block_newer_header.data.timestamp
            - block_older_header.data.timestamp
        )
        time_delta = datetime.timedelta(seconds=elapsed_time_seconds)
        print("Older Block", block_older_header.data.height, ":")
        print(
            f"Header Hash            0x{oldblock_hash}\n"
            f"Timestamp              {block_older_time_string}\n"
            f"Weight                 {block_older_header.data.weight}\n"
            f"Total VDF Iterations   {block_older_header.data.total_iters}\n"
        )
        print("Newer Block", block_newer_header.data.height, ":")
        print(
            f"Header Hash            0x{newblock_hash}\n"
            f"Timestamp              {block_newer_time_string}\n"
            f"Weight                 {block_newer_header.data.weight}\n"
            f"Total VDF Iterations   {block_newer_header.data.total_iters}\n"
        )
        delta_weight = (
            block_newer_header.data.weight - block_older_header.data.weight
        )
        delta_iters = (
            block_newer_header.data.total_iters
            - block_older_header.data.total_iters
        )

        block_older = await client.get_block(hexstr_to_bytes(oldblock_hash))
        block_newer = await client.get_block(hexstr_to_bytes(newblock_hash))
        delta_iters -= await get_total_miniters(
            client, block_older, block_newer
        )
        weight_div_iters = delta_weight / delta_iters
        tips_adjustment_constant = 0.65
        network_space_constant = 2 ** 32  # 2^32
        network_space_bytes_estimate = (
            weight_div_iters * network_space_constant * tips_adjustment_constant
        )
        network_space_terrabytes_estimate = (
            network_space_bytes_estimate / 1024**4
        )
        print(
            f"The elapsed time between blocks is reported as {time_delta}.\n"
            f"The network has an estimated {network_space_terrabytes_estimate:.2f}TB"
        )
    else:
        print("Block with header hash", oldblock_hash, "not found.")

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
