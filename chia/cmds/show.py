from chia.types.blockchain_format.sized_bytes import bytes32
import click
from typing import Any, Union


async def show_async(
    state: bool,
    exit_node: bool,
    block_header_hash_by_height: str,
    block_by_header_hash: str,
) -> None:
    import aiohttp
    import traceback
    import time
    from typing import List, Optional
    from chia.consensus.block_record import BlockRecord
    from chia.rpc.full_node_rpc_client import FullNodeRpcClient
    from chia.types.full_block import FullBlock
    from chia.util.bech32m import encode_puzzle_hash
    from chia.util.byte_types import hexstr_to_bytes
    from chia.util.config import load_config
    from chia.util.default_root import DEFAULT_ROOT_PATH
    from chia.util.ints import uint16
    from chia.util.misc import format_bytes

    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        rpc_port = config["full_node"]["rpc_port"]
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)

        if state:
            blockchain_state = await client.get_blockchain_state()
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
                print(f"Current Blockchain Status: Syncing {sync_current_block}/{sync_max_block}.")
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
                    curr = await client.get_block_record(peak_hash)
                    while curr is not None and not curr.is_transaction_block:
                        curr = await client.get_block_record(curr.prev_hash)
                    peak_time = curr.timestamp
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
                curr = await client.get_block_record(peak.header_hash)
                while curr is not None and len(added_blocks) < num_blocks and curr.height > 0:
                    added_blocks.append(curr)
                    curr = await client.get_block_record(curr.prev_hash)

                for b in added_blocks:
                    print(f"{b.height:>9} | {b.header_hash}")
            else:
                print("Blockchain has no blocks yet")

        if exit_node:
            node_stop = await client.stop_node()
            print(node_stop, "Node stopped")

        if block_header_hash_by_height != "":
            block_header = await client.get_block_record_by_height(block_header_hash_by_height)
            if block_header is not None:
                print(f"Header hash of block {block_header_hash_by_height}: " f"{block_header.header_hash.hex()}")
            else:
                print("Block height", block_header_hash_by_height, "not found")
        if block_by_header_hash != "":
            block: Optional[BlockRecord] = await client.get_block_record(hexstr_to_bytes(block_by_header_hash))
            full_block: Optional[FullBlock] = await client.get_block(hexstr_to_bytes(block_by_header_hash))
            # Would like to have a verbose flag for this
            if block is not None:
                assert full_block is not None
                prev_b = await client.get_block_record(block.prev_hash)
                if prev_b is not None:
                    difficulty = block.weight - prev_b.weight
                else:
                    difficulty = block.weight
                if block.is_transaction_block:
                    assert full_block.transactions_info is not None
                    block_time = time.struct_time(
                        time.localtime(
                            full_block.foliage_transaction_block.timestamp
                            if full_block.foliage_transaction_block
                            else None
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

    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if full node rpc is running at {rpc_port}")
            print("This is normal if full node is still starting up")
        else:
            tb = traceback.format_exc()
            print(f"Exception from 'show' {tb}")

    client.close()
    await client.await_closed()


@click.command("show", short_help="Show node information")
@click.option("-s", "--state", help="Show the current state of the blockchain", is_flag=True, type=bool, default=False)
@click.option("-e", "--exit-node", help="Shut down the running Full Node", is_flag=True, default=False)
@click.option(
    "-bh", "--block-header-hash-by-height", help="Look up a block header hash by block height", type=str, default=""
)
@click.option("-b", "--block-by-header-hash", help="Look up a block by block header hash", type=str, default="")
def show_cmd(
    state: bool,
    exit_node: bool,
    block_header_hash_by_height: str,
    block_by_header_hash: str,
) -> None:
    import asyncio

    asyncio.run(
        show_async(
            state,
            exit_node,
            block_header_hash_by_height,
            block_by_header_hash,
        )
    )
