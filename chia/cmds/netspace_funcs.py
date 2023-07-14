from __future__ import annotations

from typing import Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.misc import format_bytes


async def netstorge_async(rpc_port: Optional[int], delta_block_height: str, start: str) -> None:
    """
    Calculates the estimated space on the network given two block header hashes.
    """
    async with get_any_service_client(FullNodeRpcClient, rpc_port) as (client, _):
        if delta_block_height:
            if start == "":
                blockchain_state = await client.get_blockchain_state()
                if blockchain_state["peak"] is None:
                    print("No blocks in blockchain")
                    return None

                newer_block_height = blockchain_state["peak"].height
            else:
                newer_block = await client.get_block_record(bytes32.from_hexstr(start))
                if newer_block is None:
                    print("Block header hash", start, "not found.")
                    return None
                else:
                    print("newer_height", newer_block.height)
                    newer_block_height = newer_block.height

            newer_block_header = await client.get_block_record_by_height(newer_block_height)
            older_block_height = max(0, newer_block_height - int(delta_block_height))
            older_block_header = await client.get_block_record_by_height(older_block_height)
            assert newer_block_header is not None and older_block_header is not None
            network_space_bytes_estimate = await client.get_network_space(
                newer_block_header.header_hash, older_block_header.header_hash
            )
            print(
                "Older Block\n"
                f"Block Height: {older_block_header.height}\n"
                f"Weight:           {older_block_header.weight}\n"
                f"VDF Iterations:   {older_block_header.total_iters}\n"
                f"Header Hash:      0x{older_block_header.header_hash}\n"
            )
            print(
                "Newer Block\n"
                f"Block Height: {newer_block_header.height}\n"
                f"Weight:           {newer_block_header.weight}\n"
                f"VDF Iterations:   {newer_block_header.total_iters}\n"
                f"Header Hash:      0x{newer_block_header.header_hash}\n"
            )
            print(format_bytes(network_space_bytes_estimate))
