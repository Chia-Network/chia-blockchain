import aiohttp
import asyncio
import time
from time import struct_time, localtime

from typing import List, Optional

from src.server.connection import NodeType
from src.types.header_block import HeaderBlock
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.util.byte_types import hexstr_to_bytes
from src.util.config import str2bool


def make_parser(parser):

    parser.add_argument(
        "-s",
        "--state",
        help="Show the current state of the blockchain.",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
    )

    parser.add_argument(
        "-c",
        "--connections",
        help="List nodes connected to this Full Node.",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
    )

    parser.add_argument(
        "-b",
        "--block-by-header-hash",
        help="Look up a block by block header hash.",
        type=str,
        default="",
    )

    parser.add_argument(
        "-bh",
        "--block-header-hash-by-height",
        help="Look up a block header hash by block height.",
        type=str,
        default="",
    )

    parser.add_argument(
        "-a",
        "--add-connection",
        help="Connect to another Full Node by ip:port",
        type=str,
        default="",
    )

    parser.add_argument(
        "-r",
        "--remove-connection",
        help="Remove a Node by the first 10 characters of NodeID",
        type=str,
        default="",
    )

    parser.add_argument(
        "-e",
        "--exit-node",
        help="Shut down the running Full Node",
        nargs="?",
        const=True,
        default=False,
    )

    parser.add_argument(
        "-p",
        "--rpc-port",
        help="Set the port where the Full Node is hosting the RPC interface."
        + " See the rpc_port under full_node in config.yaml."
        + "Defaults to 8555",
        type=int,
        default=8555,
    )
    parser.set_defaults(function=show)


async def show_async(args, parser):

    # TODO read configuration for rpc_port instead of assuming default
    try:
        client = await FullNodeRpcClient.create(args.rpc_port)

        if args.state:
            blockchain_state = await client.get_blockchain_state()
            lca_block = blockchain_state["lca"]
            tips = blockchain_state["tips"]
            difficulty = blockchain_state["difficulty"]
            ips = blockchain_state["ips"]
            sync_mode = blockchain_state["sync"]["sync_mode"]
            total_iters = lca_block.data.total_iters
            num_blocks: int = 10

            if sync_mode:
                sync_max_block = blockchain_state["sync"]["sync_tip_height"]
                sync_current_block = blockchain_state["sync"]["sync_progress_height"]
                # print (max_block)
                print(
                    "Current Blockchain Status: Full Node syncing to",
                    sync_max_block,
                    "\nCurrently synched to tip:",
                    sync_current_block,
                )
            else:
                print("Current Blockchain Status: Full Node Synced")
            print("Latest Common Ancestor:\n    ", lca_block.header_hash)
            lca_time = struct_time(localtime(lca_block.data.timestamp))
            # Should auto format the align right of LCA height
            print(
                "     LCA time:",
                time.strftime("%a %b %d %Y %T %Z", lca_time),
                "       LCA height:",
                lca_block.height,
            )
            print("Heights of tips: " + str([h.height for h in tips]))
            print(f"Current difficulty: {difficulty}")
            print(f"Current VDF iterations per second: {ips:.0f}")
            print("Total iterations since genesis:", total_iters)
            print("")
            heads: List[HeaderBlock] = tips
            added_blocks: List[HeaderBlock] = []
            while len(added_blocks) < num_blocks and len(heads) > 0:
                heads = sorted(heads, key=lambda b: b.height, reverse=True)
                max_block = heads[0]
                if max_block not in added_blocks:
                    added_blocks.append(max_block)
                heads.remove(max_block)
                prev: Optional[HeaderBlock] = await client.get_header(
                    max_block.prev_header_hash
                )
                if prev is not None:
                    heads.append(prev)

            latest_blocks_labels = []
            for i, b in enumerate(added_blocks):
                latest_blocks_labels.append(
                    f"{b.height}:{b.header_hash}"
                    f" {'LCA' if b.header_hash == lca_block.header_hash else ''}"
                    f" {'TIP' if b.header_hash in [h.header_hash for h in tips] else ''}"
                )
            for i in range(len(latest_blocks_labels)):
                if i < 2:
                    print(latest_blocks_labels[i])
                elif i == 2:
                    print(
                        latest_blocks_labels[i],
                        "\n",
                        "                                -----",
                    )
                else:
                    print("", latest_blocks_labels[i])
            # if called together with connections, leave a blank line
            if args.connections:
                print("")
        if args.connections:
            connections = await client.get_connections()
            print("Connections")
            print(
                "Type      IP                                      Ports      NodeID        Last Connect"
                + "       MB Up|Dwn"
            )
            for con in connections:
                last_connect_tuple = struct_time(localtime(con["last_message_time"]))
                # last_connect = time.ctime(con['last_message_time'])
                last_connect = time.strftime("%b %d %T", last_connect_tuple)
                mb_down = con["bytes_read"] / 1024
                mb_up = con["bytes_written"] / 1024
                # print (last_connect)
                con_str = (
                    f"{NodeType(con['type']).name:9} {con['peer_host']:39} "
                    f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                    f"{con['node_id'].hex()[:10]}... "
                    f"{last_connect}  "
                    f"{mb_down:7.1f}|{mb_up:<7.1f}"
                )
                print(con_str)
            # if called together with state, leave a blank line
            if args.state:
                print("")
        if args.exit_node:
            node_stop = await client.stop_node()
            print(node_stop, "Node stopped.")
        if args.add_connection:
            if ":" not in args.add_connection:
                print(
                    "Enter a valid IP and port in the following format: 10.5.4.3:8000"
                )
            else:
                ip, port = (
                    ":".join(args.add_connection.split(":")[:-1]),
                    args.add_connection.split(":")[-1],
                )
            print(f"Connecting to {ip}, {port}")
            try:
                await client.open_connection(ip, int(port))
            except BaseException:
                # TODO: catch right exception
                print(f"Failed to connect to {ip}:{port}")
        if args.remove_connection:
            result_txt = ""
            if len(args.remove_connection) != 10:
                result_txt = "Invalid NodeID"
            else:
                connections = await client.get_connections()
                for con in connections:
                    if args.remove_connection == con["node_id"].hex()[:10]:
                        print(
                            "Attempting to disconnect", "NodeID", args.remove_connection
                        )
                        try:
                            await client.close_connection(con["node_id"])
                        except BaseException:
                            result_txt = (
                                f"Failed to disconnect NodeID {args.remove_connection}"
                            )
                        else:
                            result_txt = f"NodeID {args.remove_connection}... {NodeType(con['type']).name} "
                            f"{con['peer_host']} disconnected."
                    elif result_txt == "":
                        result_txt = f"NodeID {args.remove_connection}... not found."
            print(result_txt)
        if args.block_header_hash_by_height != "":
            block_header = await client.get_header_by_height(
                args.block_header_hash_by_height
            )
            if block_header is not None:
                block_header_string = str(block_header.get_hash())
                print(
                    f"Header hash of block {args.block_header_hash_by_height}: {block_header_string}"
                )
            else:
                print("Block height", args.block_header_hash_by_height, "not found.")
        if args.block_by_header_hash != "":
            block = await client.get_block(hexstr_to_bytes(args.block_by_header_hash))
            # Would like to have a verbose flag for this
            if block is not None:
                prev_block_header_hash = block.header.data.prev_header_hash
                prev_block_header = await client.get_block(prev_block_header_hash)
                block_time = struct_time(localtime(block.header.data.timestamp))
                block_time_string = time.strftime("%a %b %d %Y %T %Z", block_time)
                if block.header.data.aggregated_signature is None:
                    aggregated_signature = block.header.data.aggregated_signature
                else:
                    aggregated_signature = block.header.data.aggregated_signature.sig
                print("Block", block.header.data.height, ":")
                print(
                    f"Header Hash            0x{args.block_by_header_hash}\n"
                    f"Timestamp              {block_time_string}\n"
                    f"Height                 {block.header.data.height}\n"
                    f"Weight                 {block.header.data.weight}\n"
                    f"Previous Block         0x{block.header.data.prev_header_hash}\n"
                    f"Cost                   {block.header.data.cost}\n"
                    f"Difficulty             {block.header.data.weight-prev_block_header.header.data.weight}\n"
                    f"Total VDF Iterations   {block.header.data.total_iters}\n"
                    f"Block VDF Iterations   {block.proof_of_time.number_of_iterations}\n"
                    f"PoTime Witness Type    {block.proof_of_time.witness_type}\n"
                    f"PoSpace 'k' Size       {block.proof_of_space.size}\n"
                    # f"Plot Public Key            0x{block.proof_of_space.plot_pubkey}\n"
                    # f"Pool Public Key            0x{block.proof_of_space.pool_pubkey}\n"
                    f"Tx Filter Hash         {b'block.transactions_filter'.hex()}\n"
                    f"Tx Generator Hash      {block.transactions_generator}\n"
                    f"Coinbase Amount        {block.header.data.coinbase.amount/1000000000000}\n"
                    f"Coinbase Puzzle Hash   0x{block.header.data.coinbase.puzzle_hash}\n"
                    f"Fees Amount            {block.header.data.fees_coin.amount/1000000000000}\n"
                    f"Fees Puzzle Hash       0x{block.header.data.fees_coin.puzzle_hash}\n"
                    f"Aggregated Signature   {aggregated_signature}"
                )
            else:
                print("Block with header hash", args.block_by_header_hash, "not found.")

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception from 'show' {e}")

    client.close()
    await client.await_closed()


def show(args, parser):
    return asyncio.run(show_async(args, parser))
