import asyncio
import argparse
import sys
import aiohttp
import pprint
import json
import datetime
import time
from time import struct_time, localtime

from typing import Callable, List, Optional, Tuple, Dict

from src.server.connection import NodeType
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.rpc.rpc_client import RpcClient
from src.util.byte_types import hexstr_to_bytes


def str2bool(v: str) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


async def main():
    parser = argparse.ArgumentParser(description="Manage a Chia Full Node from the command line.",
        epilog = "You can combine -s and -c. Try 'watch -n 10 python -m script.cli -s -c' if you have 'watch' installed."
    )

    parser.add_argument(
        "-b",
        "--block_header_hash",
        help="Look up a block by block header hash string.",
        type=str,
        default="",
    )
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
        "-p",
        "--rpc-port",
        help="Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml. Defaults to 8555",
        type=int,
        default=8555,
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

    args = parser.parse_args(args=None if sys.argv[1:] else ['--help'])

    #print(args)
    try:
        client = await RpcClient.create(args.rpc_port)

        #print (dir(client))
        # TODO: Add other rpc calls
        # TODO: pretty print response
        if args.state:
            blockchain_state = await client.get_blockchain_state()
            lca_block = blockchain_state["lca"]
            tips = blockchain_state["tips"]
            difficulty = blockchain_state["difficulty"]
            ips = blockchain_state["ips"]
            sync_mode = blockchain_state["sync_mode"]
            total_iters = lca_block.data.total_iters
            num_blocks: int = 10

            if sync_mode:
                sync_max_block = await client.get_heaviest_block_seen()
                #print (max_block)
                print ("Current Blockchain Status. Full Node Syncing to", sync_max_block.data.height)
            else:
                print ("Current Blockchain Status. Full Node Synced")
            print("Current least common ancestor ", lca_block.header_hash)
            #print ("LCA time",time.ctime(lca_block.data.timestamp),"LCA height:",lca_block.height)
            lca_time = struct_time(localtime(lca_block.data.timestamp))
            print ("LCA time",time.strftime("%a %b %d %Y %T %Z", lca_time),"LCA height:",lca_block.height)
            print ("Heights of tips: " + str([h.height for h in tips]))
            print (f"Current difficulty: {difficulty}")
            print (f"Current VDF iterations per second: {ips:.0f}")
            #print("LCA data:\n", lca_block.data)
            print("Total iterations since genesis:",total_iters)
            print ("")
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
                latest_blocks_labels.append (
                    f"{b.height}:{b.header_hash}"
                    f" {'LCA' if b.header_hash == lca_block.header_hash else ''}"
                    f" {'TIP' if b.header_hash in [h.header_hash for h in tips] else ''}"
                    )
            for i in range(len(latest_blocks_labels)):
                if (i<2):
                    print (latest_blocks_labels[i])
                elif (i==2):
                    print (latest_blocks_labels[i],"\n","                                -----")
                else:
                    print ("",latest_blocks_labels[i])
            #if called together with other arguments, leave a blank line
            if args.connections:
                print ("")
        if args.connections:
            connections = await client.get_connections()
            print ("Connections")
            print ("Type      IP                                      Ports      NodeID        Last Connect       MB Up|Dwn")
            for con in connections:
                last_connect_tuple = struct_time(localtime(con['last_message_time']))
                #last_connect = time.ctime(con['last_message_time'])
                last_connect = time.strftime("%b %d %T", last_connect_tuple)
                mb_down = con['bytes_read']/1024
                mb_up = con['bytes_written']/1024
                #print (last_connect)
                con_str = (
                    f"{NodeType(con['type']).name:9} {con['peer_host']:39} "
                    f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                    f"{con['node_id'].hex()[:10]}... "
                    f"{last_connect}  "
                    f"{mb_down:7.1f}|{mb_up:<7.1f}"
                )
                print (con_str)
            #if called together with other arguments, leave a blank line
            if args.state:
                print ("")
        if args.exit_node:
            node_stop = await client.stop_node()
            print (node_stop, "Node stopped.")
        if args.add_connection:
            if ":" not in args.add_connection:
                print ("Enter a valid IP and port in the following format: 10.5.4.3:8000")
            else:
                ip, port = ":".join(args.add_connection.split(":")[:-1]), args.add_connection.split(":")[-1]
            print(f"Connecting to {ip}, {port}")
            try:
                await client.open_connection(ip, int(port))
            except BaseException:
                # TODO: catch right exception
                print(f"Failed to connect to {ip}:{port}")
        if args.remove_connection:
            result_txt = ""
            if len(args.remove_connection)!=10:
                result_txt = "Invalid NodeID"
            else:
                connections = await client.get_connections()
                for con in (connections):
                    if args.remove_connection == con['node_id'].hex()[:10]:
                        print ("Attempting to disconnect","NodeID",args.remove_connection)
                        try:
                            await client.close_connection(con["node_id"])
                        except BaseException:
                            result_txt = f"Failed to disconnect NodeID {args.remove_connection}"
                        else:
                            result_txt = f"NodeID {args.remove_connection}... {NodeType(con['type']).name} {con['peer_host']} disconnected."
                    elif (result_txt == ""):
                         result_txt = f"NodeID {args.remove_connection}... not found."
            print (result_txt)
        elif args.block_header_hash != "":
            block = await client.get_block(hexstr_to_bytes(args.block_header_hash))
            #print(dir(block))
            if block is not None:
                print ("Block header:")
                print (block.header)
                block_time = struct_time(localtime(block.header.data.timestamp))
                print ("Block time:",time.strftime("%a %b %d %Y %T %Z", block_time))
            else:
                print ("Block hash", args.block_header_hash, "not found.")

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {args.rpc_port}")
        else:
            print(f"Exception {e}")

    client.close()
    await client.await_closed()

asyncio.run(main())
