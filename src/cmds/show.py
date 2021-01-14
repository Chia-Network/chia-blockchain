import aiohttp
import asyncio
import time
from time import struct_time, localtime

from typing import List, Optional

from src.consensus.sub_block_record import SubBlockRecord
from src.server.outbound_message import NodeType
from src.types.full_block import FullBlock
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.util.byte_types import hexstr_to_bytes
from src.util.config import str2bool
from src.util.config import load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.chech32 import encode_puzzle_hash


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
        "--sub-block-by-header-hash",
        help="Look up a sub-block by block header hash.",
        type=str,
        default="",
    )

    parser.add_argument(
        "-bh",
        "--sub-block-header-hash-by-sub-height",
        help="Look up a sub-block header hash by block height.",
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

    parser.add_argument(
        "-wp",
        "--wallet-rpc-port",
        help="Set the port where the Wallet is hosting the RPC interface."
        + " See the rpc_port under wallet in config.yaml."
        + "Defaults to 9256",
        type=int,
        default=9256,
    )

    parser.set_defaults(function=show)


async def show_async(args, parser):

    # TODO read configuration for rpc_port instead of assuming default

    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if "rpc_port" not in args or args.rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        else:
            rpc_port = args.rpc_port
        client = await FullNodeRpcClient.create(self_hostname, rpc_port, DEFAULT_ROOT_PATH, config)

        if args.state:
            blockchain_state = await client.get_blockchain_state()
            if blockchain_state is None:
                return "There is no blockchain found yet. Try again shortly."
            peak: Optional[FullBlock] = blockchain_state["peak"]
            difficulty = blockchain_state["difficulty"]
            sub_slot_iters = blockchain_state["sub_slot_iters"]
            sync_mode = blockchain_state["sync"]["sync_mode"]
            total_iters = peak.total_iters if peak is not None else 0
            num_blocks: int = 10

            if sync_mode:
                sync_max_block = blockchain_state["sync"]["sync_tip_height"]
                sync_current_block = blockchain_state["sync"]["sync_progress_height"]
                print(
                    "Current Blockchain Status: Full Node syncing to sub block",
                    sync_max_block,
                    "\nCurrently synced to block:",
                    sync_current_block,
                )
            elif peak is not None and peak.height > 2:
                print("Current Blockchain Status: Full Node Synced")
                print("\nPeak: Hash:", peak.header_hash)
            else:
                print("\nSearching for an initial chain.")
                print("You may be able to expedite with 'chia show -a host:port' using a known node.\n")
                print("Errors that follow can be safely ignored:\n")
            if peak is not None and peak.is_block():
                peak_time = peak.foliage_block.timestamp
            else:
                peak_hash = peak.header_hash
                curr = await client.get_sub_block_record(peak_hash)
                while curr is not None and not curr.is_block:
                    curr = await client.get_sub_block_record(curr.prev_hash)
                peak_time = curr.timestamp

            peak_time = struct_time(localtime(peak_time))

            # Should auto format the align right of LCA height
            print(
                "      Time:",
                f"{time.strftime('%a %b %d %Y %T %Z', peak_time)}",
                f"Height: {peak.height:>7}",
                f"SB height: {peak.sub_block_height:>8}\n",
            )

            print("Estimated network space: ", end="")
            network_space_human_readable = blockchain_state["space"] / 1024 ** 4
            if network_space_human_readable >= 1024:
                network_space_human_readable = network_space_human_readable / 1024
                print(f"{network_space_human_readable:.3f}PiB")
            else:
                print(f"{network_space_human_readable:.3f}TiB")
            print(f"Current difficulty: {difficulty}")
            print(f"Current VDF sub_slot_iters: {sub_slot_iters}")
            print("Total iterations since the start of the blockchain:", total_iters)
            print("")
            print("SB Height |   Height  | Hash:")

            added_blocks: List[SubBlockRecord] = []
            curr = await client.get_sub_block_record(peak.header_hash)
            while curr is not None and len(added_blocks) < num_blocks:
                added_blocks.append(curr)
                curr = await client.get_sub_block_record(curr.prev_hash)

            for b in added_blocks:
                print(f"{b.sub_block_height:>8}  | {b.height:>7}   | {b.header_hash}")

            # if called together with connections, leave a blank line
            if args.connections:
                print("")
        if args.connections:
            connections = await client.get_connections()
            print("Connections:")
            print(
                "Type      IP                                     Ports       NodeID      Last Connect"
                + "       MB Up|Dwn"
            )
            for con in connections:
                last_connect_tuple = struct_time(localtime(con["last_message_time"]))
                last_connect = time.strftime("%b %d %T", last_connect_tuple)
                mb_down = con["bytes_read"] / 1000000
                mb_up = con["bytes_written"] / 1000000

                host = con["peer_host"]
                # Strip IPv6 brackets
                if host[0] == "[":
                    host = host[1:39]
                # Nodetype length is 9 because INTRODUCER will be deprecated
                if NodeType(con["type"]) is NodeType.FULL_NODE:
                    peak_sub_height = con["peak_sub_height"]
                    peak_hash = con["peak_hash"]
                    if peak_hash is None:
                        peak_hash = "No Info"
                    if peak_sub_height is None:
                        peak_sub_height = 0
                    con_str = (
                        f"{NodeType(con['type']).name:9} {host:38} "
                        f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                        f" {con['node_id'].hex()[:8]}... "
                        f"{last_connect}  "
                        f"{mb_down:7.1f}|{mb_up:<7.1f}"
                        f"\n                                                 "
                        f"-SB Height: {peak_sub_height:8.0f}    -Hash: {peak_hash[2:10]}..."
                    )
                else:
                    con_str = (
                        f"{NodeType(con['type']).name:9} {host:38} "
                        f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                        f" {con['node_id'].hex()[:8]}... "
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
                print("Enter a valid IP and port in the following format: 10.5.4.3:8000")
            else:
                ip, port = (
                    ":".join(args.add_connection.split(":")[:-1]),
                    args.add_connection.split(":")[-1],
                )
            print(f"Connecting to {ip}, {port}")
            try:
                await client.open_connection(ip, int(port))
            except Exception:
                # TODO: catch right exception
                print(f"Failed to connect to {ip}:{port}")
        if args.remove_connection:
            result_txt = ""
            if len(args.remove_connection) != 8:
                result_txt = "Invalid NodeID. Do not include '.'."
            else:
                connections = await client.get_connections()
                for con in connections:
                    if args.remove_connection == con["node_id"].hex()[:8]:
                        print("Attempting to disconnect", "NodeID", args.remove_connection)
                        try:
                            await client.close_connection(con["node_id"])
                        except Exception:
                            result_txt = f"Failed to disconnect NodeID {args.remove_connection}"
                        else:
                            result_txt = f"NodeID {args.remove_connection}... {NodeType(con['type']).name} "
                            f"{con['peer_host']} disconnected."
                    elif result_txt == "":
                        result_txt = f"NodeID {args.remove_connection}... not found."
            print(result_txt)
        if args.sub_block_header_hash_by_sub_height != "":
            block_header = await client.get_sub_block_record_by_sub_height(args.sub_block_header_hash_by_sub_height)
            if block_header is not None:
                print(
                    f"Header hash of sub-block {args.sub_block_header_hash_by_sub_height}: "
                    f"{block_header.header_hash.hex()}"
                )
            else:
                print("Sub block height", args.sub_block_header_hash_by_sub_height, "not found.")
        if args.sub_block_by_header_hash != "":
            sub_block: Optional[SubBlockRecord] = await client.get_sub_block_record(
                hexstr_to_bytes(args.sub_block_by_header_hash)
            )
            full_block: Optional[FullBlock] = await client.get_sub_block(hexstr_to_bytes(args.sub_block_by_header_hash))
            # Would like to have a verbose flag for this
            if sub_block is not None:
                assert full_block is not None
                prev_sb = await client.get_sub_block_record(sub_block.prev_hash)
                if prev_sb is not None:
                    difficulty = sub_block.weight - prev_sb.weight
                else:
                    difficulty = sub_block.weight
                if sub_block.is_block:
                    assert full_block.transactions_info is not None
                    block_time = struct_time(localtime(full_block.foliage_block.timestamp))
                    block_time_string = time.strftime("%a %b %d %Y %T %Z", block_time)
                    cost = full_block.transactions_info.cost
                    tx_filter_hash = full_block.foliage_block.filter_hash
                else:
                    block_time_string = "Not a block"
                    cost = "Not a block"
                    tx_filter_hash = "Not a block"
                print("Sub block at sub-height", sub_block.sub_block_height, ":")
                print(
                    f"Header Hash            0x{sub_block.header_hash.hex()}\n"
                    f"Timestamp              {block_time_string}\n"
                    f"Sub-block Height       {sub_block.sub_block_height}\n"
                    f"Height                 {sub_block.height}\n"
                    f"Weight                 {sub_block.weight}\n"
                    f"Previous Block         0x{sub_block.prev_hash.hex()}\n"
                    f"Difficulty             {difficulty}\n"
                    f"Sub-slot iters         {sub_block.sub_slot_iters}\n"
                    f"Cost                   {cost}\n"
                    f"Total VDF Iterations   {sub_block.total_iters}\n"
                    f"Is a Block?            {sub_block.is_block}\n"
                    f"Deficit                {sub_block.deficit}\n"
                    f"PoSpace 'k' Size       {full_block.reward_chain_sub_block.proof_of_space.size}\n"
                    f"Plot Public Key        0x{full_block.reward_chain_sub_block.proof_of_space.plot_public_key}\n"
                    f"Pool Public Key        0x{full_block.reward_chain_sub_block.proof_of_space.pool_public_key}\n"
                    f"Pool Contract PH       0x"
                    f"{full_block.reward_chain_sub_block.proof_of_space.pool_contract_puzzle_hash}\n"
                    f"Tx Filter Hash         {tx_filter_hash}\n"
                    f"Farmer Address         {encode_puzzle_hash(sub_block.farmer_puzzle_hash)}\n"
                    f"Pool Address           {encode_puzzle_hash(sub_block.pool_puzzle_hash)}\n"
                    f"Fees Amount            {sub_block.fees}\n"
                )
            else:
                print("Sub-block with header hash", args.sub_block_header_hash_by_sub_height, "not found.")

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {args.rpc_port}")
        else:
            print(f"Exception from 'show' {e}")

    client.close()
    await client.await_closed()


def show(args, parser):
    return asyncio.run(show_async(args, parser))
