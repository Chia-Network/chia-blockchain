from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Optional, Union

import click

from chia.cmds.units import units
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint64
from chia.util.network import is_trusted_inner


def print_coins(
    verbose: bool,
    name: str,
    address_prefix: str,
    mojo_per_unit: int,
    coin_record: CoinRecord,
) -> None:
    if verbose:
        print(coin_record)
    else:
        chia_amount = Decimal(int(coin_record.coin.amount)) / mojo_per_unit
        coin_address = encode_puzzle_hash(coin_record.coin.puzzle_hash, address_prefix)
        confirmed_block = coin_record.confirmed_block_index
        print(f"Coin 0x{coin_record.name}")
        print(f"Wallet Address: {coin_address}")
        print(
            "Status: "
            f"{f'Confirmed at block: {confirmed_block}' if coin_record.confirmed_block_index != 0 else 'Pending'}"
        )
        print(f"Spent: {f'At Block {coin_record}' if not coin_record.spent else 'No'}")
        print(f"Amount {'sent'}: {chia_amount} {name}")
        print(f"Parent Coin ID: 0x{coin_record.coin.parent_coin_info}")
        print("Created at:", datetime.fromtimestamp(float(coin_record.timestamp)).strftime("%Y-%m-%d %H:%M:%S"))
        print("")


async def print_connections(node_client, time, NodeType, trusted_peers: Dict):
    connections = await node_client.get_connections()
    print("Connections:")
    print("Type      IP                                     Ports       NodeID      Last Connect" + "      MiB Up|Dwn")
    for con in connections:
        last_connect_tuple = time.struct_time(time.localtime(con["last_message_time"]))
        last_connect = time.strftime("%b %d %T", last_connect_tuple)
        mb_down = con["bytes_read"] / (1024 * 1024)
        mb_up = con["bytes_written"] / (1024 * 1024)

        host = con["peer_host"]
        # Strip IPv6 brackets
        host = host.strip("[]")

        trusted: bool = is_trusted_inner(host, con["node_id"], trusted_peers, False)
        # Nodetype length is 9 because INTRODUCER will be deprecated
        if NodeType(con["type"]) is NodeType.FULL_NODE:
            peak_height = con.get("peak_height", None)
            connection_peak_hash = con.get("peak_hash", None)
            if connection_peak_hash is None:
                connection_peak_hash = "No Info"
            else:
                if connection_peak_hash.startswith(("0x", "0X")):
                    connection_peak_hash = connection_peak_hash[2:]
                connection_peak_hash = f"{connection_peak_hash[:8]}..."
            con_str = (
                f"{NodeType(con['type']).name:9} {host:38} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
                f"\n                                                 "
            )
            if peak_height is not None:
                con_str += f"-Height: {peak_height:8.0f}    -Hash: {connection_peak_hash}"
            else:
                con_str += f"-Height: No Info    -Hash: {connection_peak_hash}"
            # Only show when Trusted is True
            if trusted:
                con_str += f"    -Trusted: {trusted}"
        else:
            con_str = (
                f"{NodeType(con['type']).name:9} {host:38} "
                f"{con['peer_port']:5}/{con['peer_server_port']:<5}"
                f" {con['node_id'].hex()[:8]}... "
                f"{last_connect}  "
                f"{mb_up:7.1f}|{mb_down:<7.1f}"
            )
        print(con_str)


async def execute_with_node(rpc_port: Optional[int], function: Callable, *args):
    import traceback

    import aiohttp

    from chia.util.config import load_config
    from chia.util.default_root import DEFAULT_ROOT_PATH
    from chia.util.ints import uint16
    from chia.rpc.full_node_rpc_client import FullNodeRpcClient

    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        node_client: FullNodeRpcClient = await FullNodeRpcClient.create(
            self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config
        )
        await function(node_client, config, *args)

    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {rpc_port}")
            print("This is normal if full node is still starting up")
        else:
            tb = traceback.format_exc()
            print(f"Exception from 'show' {tb}")

    node_client.close()
    await node_client.await_closed()


async def show_async(
    node_client: FullNodeRpcClient,
    config: Dict,
    state: bool,
    show_connections: bool,
    exit_node: bool,
    add_connection: str,
    remove_connection: str,
    block_header_hash_by_height: str,
    block_by_header_hash: str,
    coins_by_address: str,
    coin_by_coin_id: str,
    verbose: bool,
    offset: int,
    paginate: bool,
) -> None:
    import time
    from typing import List, Optional

    from chia.consensus.block_record import BlockRecord
    from chia.server.outbound_message import NodeType
    from chia.types.full_block import FullBlock
    from chia.util.byte_types import hexstr_to_bytes
    from chia.util.misc import format_bytes

    if state:
        blockchain_state = await node_client.get_blockchain_state()
        if blockchain_state is None:
            print("There is no blockchain found yet. Try again shortly")
            return None
        peak: Optional[BlockRecord] = blockchain_state["peak"]
        node_id = blockchain_state["node_id"]
        difficulty = blockchain_state["difficulty"]
        sub_slot_iters = blockchain_state["sub_slot_iters"]
        synced = blockchain_state["sync"]["synced"]
        sync_mode = blockchain_state["sync"]["sync_mode"]
        total_iters = peak.total_iters if peak is not None else 0
        num_blocks: int = 10
        network_name = config["selected_network"]
        genesis_challenge = config["farmer"]["network_overrides"]["constants"][network_name]["GENESIS_CHALLENGE"]
        full_node_port = config["full_node"]["port"]
        full_node_rpc_port = config["full_node"]["rpc_port"]

        print(f"Network: {network_name}    Port: {full_node_port}   Rpc Port: {full_node_rpc_port}")
        print(f"Node ID: {node_id}")

        print(f"Genesis Challenge: {genesis_challenge}")

        if synced:
            print("Current Blockchain Status: Full Node Synced")
            print("\nPeak: Hash:", peak.header_hash if peak is not None else "")
        elif peak is not None and sync_mode:
            sync_max_block = blockchain_state["sync"]["sync_tip_height"]
            sync_current_block = blockchain_state["sync"]["sync_progress_height"]
            print(
                f"Current Blockchain Status: Syncing {sync_current_block}/{sync_max_block} "
                f"({sync_max_block - sync_current_block} behind)."
            )
            print("Peak: Hash:", peak.header_hash if peak is not None else "")
        elif peak is not None:
            print(f"Current Blockchain Status: Not Synced. Peak height: {peak.height}")
        else:
            print("\nSearching for an initial chain\n")
            print("You may be able to expedite with 'chia show -a host:port' using a known node.\n")
        if peak is not None:
            if peak.is_transaction_block:
                peak_time = peak.timestamp
            else:
                peak_hash = peak.header_hash
                curr = await node_client.get_block_record(peak_hash)
                while curr is not None and not curr.is_transaction_block:
                    curr = await node_client.get_block_record(curr.prev_hash)
                if curr is not None:
                    peak_time = curr.timestamp
                else:
                    peak_time = uint64(0)
            peak_time_struct = time.struct_time(time.localtime(peak_time))

            print(
                "      Time:",
                f"{time.strftime('%a %b %d %Y %T %Z', peak_time_struct)}",
                f"                 Height: {peak.height:>10}\n",
            )

            print("Estimated network space: ", end="")
            print(format_bytes(blockchain_state["space"]))
            print(f"Current difficulty: {difficulty}")
            print(f"Current VDF sub_slot_iters: {sub_slot_iters}")
            print("Total iterations since the start of the blockchain:", total_iters)
            print("")
            print("  Height: |   Hash:")

            added_blocks: List[BlockRecord] = []
            curr = await node_client.get_block_record(peak.header_hash)
            while curr is not None and len(added_blocks) < num_blocks and curr.height > 0:
                added_blocks.append(curr)
                curr = await node_client.get_block_record(curr.prev_hash)

            for b in added_blocks:
                print(f"{b.height:>9} | {b.header_hash}")
        else:
            print("Blockchain has no blocks yet")

        # if called together with show_connections, leave a blank line
        if show_connections:
            print("")
    if show_connections:
        trusted_peers: Dict = config["full_node"].get("trusted_peers", {})
        await print_connections(node_client, time, NodeType, trusted_peers)
        # if called together with state, leave a blank line
        if state:
            print("")
    if exit_node:
        node_stop = await node_client.stop_node()
        print(node_stop, "Node stopped")
    if add_connection:
        if ":" not in add_connection:
            print("Enter a valid IP and port in the following format: 10.5.4.3:8000")
        else:
            ip, port = (
                ":".join(add_connection.split(":")[:-1]),
                add_connection.split(":")[-1],
            )
            print(f"Connecting to {ip}, {port}")
            try:
                await node_client.open_connection(ip, int(port))
            except Exception:
                print(f"Failed to connect to {ip}:{port}")
    if remove_connection:
        result_txt = ""
        if len(remove_connection) != 8:
            result_txt = "Invalid NodeID. Do not include '.'"
        else:
            connections = await node_client.get_connections()
            for con in connections:
                if remove_connection == con["node_id"].hex()[:8]:
                    print("Attempting to disconnect", "NodeID", remove_connection)
                    try:
                        await node_client.close_connection(con["node_id"])
                    except Exception:
                        result_txt = f"Failed to disconnect NodeID {remove_connection}"
                    else:
                        result_txt = f"NodeID {remove_connection}... {NodeType(con['type']).name} "
                        f"{con['peer_host']} disconnected"
                elif result_txt == "":
                    result_txt = f"NodeID {remove_connection}... not found"
        print(result_txt)
    if block_header_hash_by_height != "":
        block_header = await node_client.get_block_record_by_height(block_header_hash_by_height)
        if block_header is not None:
            print(f"Header hash of block {block_header_hash_by_height}: " f"{block_header.header_hash.hex()}")
        else:
            print("Block height", block_header_hash_by_height, "not found")
    if block_by_header_hash != "":
        block: Optional[BlockRecord] = await node_client.get_block_record(hexstr_to_bytes(block_by_header_hash))
        full_block: Optional[FullBlock] = await node_client.get_block(hexstr_to_bytes(block_by_header_hash))
        # Would like to have a verbose flag for this
        if block is not None:
            assert full_block is not None
            prev_b = await node_client.get_block_record(block.prev_hash)
            if prev_b is not None:
                difficulty = block.weight - prev_b.weight
            else:
                difficulty = block.weight
            if block.is_transaction_block:
                assert full_block.transactions_info is not None
                block_time = time.struct_time(
                    time.localtime(
                        full_block.foliage_transaction_block.timestamp if full_block.foliage_transaction_block else None
                    )
                )
                block_time_string = time.strftime("%a %b %d %Y %T %Z", block_time)
                cost = str(full_block.transactions_info.cost)
                tx_filter_hash: Union[str, bytes32] = "Not a transaction block"
                if full_block.foliage_transaction_block:
                    tx_filter_hash = full_block.foliage_transaction_block.filter_hash
                fees: Any = block.fees
            else:
                block_time_string = "Not a transaction block"
                cost = "Not a transaction block"
                tx_filter_hash = "Not a transaction block"
                fees = "Not a transaction block"
            address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
            farmer_address = encode_puzzle_hash(block.farmer_puzzle_hash, address_prefix)
            pool_address = encode_puzzle_hash(block.pool_puzzle_hash, address_prefix)
            pool_pk = (
                full_block.reward_chain_block.proof_of_space.pool_public_key
                if full_block.reward_chain_block.proof_of_space.pool_public_key is not None
                else "Pay to pool puzzle hash"
            )
            print(
                f"Block Height           {block.height}\n"
                f"Header Hash            0x{block.header_hash.hex()}\n"
                f"Timestamp              {block_time_string}\n"
                f"Weight                 {block.weight}\n"
                f"Previous Block         0x{block.prev_hash.hex()}\n"
                f"Difficulty             {difficulty}\n"
                f"Sub-slot iters         {block.sub_slot_iters}\n"
                f"Cost                   {cost}\n"
                f"Total VDF Iterations   {block.total_iters}\n"
                f"Is a Transaction Block?{block.is_transaction_block}\n"
                f"Deficit                {block.deficit}\n"
                f"PoSpace 'k' Size       {full_block.reward_chain_block.proof_of_space.size}\n"
                f"Plot Public Key        0x{full_block.reward_chain_block.proof_of_space.plot_public_key}\n"
                f"Pool Public Key        {pool_pk}\n"
                f"Tx Filter Hash         {tx_filter_hash}\n"
                f"Farmer Address         {farmer_address}\n"
                f"Pool Address           {pool_address}\n"
                f"Fees Amount            {fees}\n"
            )
        else:
            print("Block with header hash", block_header_hash_by_height, "not found")
    if coins_by_address != "" or coin_by_coin_id != "":
        coin_records: List[CoinRecord] = []
        import sys

        if coins_by_address != "":
            try:
                from chia.util.bech32m import decode_puzzle_hash

                ph: bytes32 = decode_puzzle_hash(coins_by_address)
            except ValueError:
                print("Invalid address")
            else:
                coin_records = await node_client.get_coin_records_by_puzzle_hash(ph)
                if len(coin_records) == 0:
                    print("There are no transactions to this address")
        else:
            try:
                from chia.util.byte_types import hexstr_to_bytes

                coin_id: bytes32 = bytes32(hexstr_to_bytes(coin_by_coin_id))
            except ValueError:
                print("Invalid coin id")
            else:
                coin_record = await node_client.get_coin_record_by_name(coin_id)
                if coin_record is None:
                    print("Invalid CoinID: This coin does not exist.")
                else:
                    coin_records = [coin_record]
        if len(coin_records) != 0:
            if paginate is None:
                paginate = sys.stdout.isatty()
            address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
            name = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"].upper()
            mojo_per_unit = units["chia"]
            num_per_screen = 5 if paginate else len(coin_records)

            for i in range(offset, len(coin_records), num_per_screen):
                for j in range(0, num_per_screen):
                    if i + j >= len(coin_records):
                        break
                    print_coins(
                        coin_record=coin_records[i + j],
                        verbose=(verbose > 0),
                        name=name,
                        address_prefix=address_prefix,
                        mojo_per_unit=mojo_per_unit,
                    )
                if i + num_per_screen <= len(coin_records):
                    print("Press q to quit, or c to continue")
                    while True:
                        entered_key = sys.stdin.read(1)
                        if entered_key == "q":
                            return None
                        elif entered_key == "c":
                            break


@click.command("show", short_help="Show node information")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-s", "--state", help="Show the current state of the blockchain", is_flag=True, type=bool, default=False)
@click.option(
    "-c", "--connections", help="List nodes connected to this Full Node", is_flag=True, type=bool, default=False
)
@click.option("-e", "--exit-node", help="Shut down the running Full Node", is_flag=True, default=False)
@click.option("-a", "--add-connection", help="Connect to another Full Node by ip:port", type=str, default="")
@click.option(
    "-r", "--remove-connection", help="Remove a Node by the first 8 characters of NodeID", type=str, default=""
)
@click.option(
    "-bh", "--block-header-hash-by-height", help="Look up a block header hash by block height", type=str, default=""
)
@click.option("-b", "--block-by-header-hash", help="Look up a block by block header hash", type=str, default="")
@click.option("-address", "--coins-by-address", help="Look up coins by an address.", type=str, default="")
@click.option("-coin", "--coin-by-coin-id", help="Find a coin with its coin id.", type=str, default="")
@click.option(
    "-v",
    "--verbose",
    help="Show more information (only used in --coins-by-address & --coin-by-coin-id)",
    type=int,
    default=0,
)
@click.option(
    "--offset", help="Offset for pagination (only used in --coins-by-address & --coin-by-coin-id)", type=int, default=0
)
@click.option(
    "--paginate",
    help="Paginate output (only used in --coins-by-address & --coin-by-coin-id)",
    is_flag=True,
    type=bool,
    default=None,
)
def show_cmd(
    rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    state: bool,
    connections: bool,
    exit_node: bool,
    add_connection: str,
    remove_connection: str,
    block_header_hash_by_height: str,
    block_by_header_hash: str,
    coins_by_address: str,
    coin_by_coin_id: str,
    verbose: bool,
    offset: int,
    paginate: bool,
) -> None:
    import asyncio

    asyncio.run(
        execute_with_node(
            rpc_port,
            show_async,
            state,
            connections,
            exit_node,
            add_connection,
            remove_connection,
            block_header_hash_by_height,
            block_by_header_hash,
            coins_by_address,
            coin_by_coin_id,
            verbose,
            offset,
            paginate,
        )
    )
