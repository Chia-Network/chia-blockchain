import aiohttp
import asyncio
import time
from time import struct_time, localtime
import datetime

from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint64
from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.consensus.constants import constants


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
        "--old_block",
        help="Older block hash used to calculate estimated total network space.",
        type=str,
        default="",
    )
    parser.add_argument(
        "-n",
        "--new_block",
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
    new_block, but not including old_block.
    """
    old_block_parent = await rpc_client.get_header(old_block.prev_header_hash)
    old_diff = old_block.weight - old_block_parent.weight
    curr_mi = calculate_min_iters_from_iterations(
        old_block.proof_of_space, old_diff, old_block.proof_of_time.number_of_iterations
    )
    # We do not count the min iters in the old block, since it's not included in the range
    total_mi: uint64 = uint64(0)
    for curr_h in range(old_block.height + 1, new_block.height + 1):
        if (curr_h % constants["DIFFICULTY_EPOCH"]) == constants["DIFFICULTY_DELAY"]:
            curr_b_header = await rpc_client.get_header_by_height(curr_h)
            curr_b_block = await rpc_client.get_block(curr_b_header.header_hash)
            curr_parent = await rpc_client.get_header(curr_b_block.prev_header_hash)
            curr_diff = curr_b_block.weight - curr_parent.weight
            curr_mi = calculate_min_iters_from_iterations(
                curr_b_block.proof_of_space,
                curr_diff,
                curr_b_block.proof_of_time.number_of_iterations,
            )
        total_mi = uint64(total_mi + curr_mi)

    print("Min iters:", total_mi)
    return total_mi


async def compare_block_headers(client, oldblock_hash, newblock_hash):
    """
    Calculates the estimated space on the network given two block header hases
    # TODO: remove grubby hack of getting both blocks for get_total_miniters
    """
    block_older_header = await client.get_header(hexstr_to_bytes(oldblock_hash))
    block_newer_header = await client.get_header(hexstr_to_bytes(newblock_hash))
    if block_older_header is not None:
        block_older_time_string = human_local_time(block_older_header.data.timestamp)
        block_newer_time_string = human_local_time(block_newer_header.data.timestamp)
        elapsed_time_seconds = (
            block_newer_header.data.timestamp - block_older_header.data.timestamp
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
        delta_weight = block_newer_header.data.weight - block_older_header.data.weight
        delta_iters = (
            block_newer_header.data.total_iters - block_older_header.data.total_iters
        )

        block_older = await client.get_block(hexstr_to_bytes(oldblock_hash))
        block_newer = await client.get_block(hexstr_to_bytes(newblock_hash))
        delta_iters -= await get_total_miniters(client, block_older, block_newer)
        weight_div_iters = delta_weight / delta_iters
        tips_adjustment_constant = 0.65
        network_space_constant = 2 ** 32  # 2^32
        network_space_bytes_estimate = (
            weight_div_iters * network_space_constant * tips_adjustment_constant
        )
        network_space_terrabytes_estimate = network_space_bytes_estimate / 1024 ** 4
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
            print(
                f"LCA Block Height is {lca_block_height} - Comparing to {older_block_height}\n"
            )
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
