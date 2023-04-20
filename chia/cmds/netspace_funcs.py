from __future__ import annotations

from typing import Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.byte_types import hexstr_to_bytes
from chia.util.misc import format_bytes

from datetime import datetime, timedelta, timezone

from chia.consensus.block_record import BlockRecord


async def netstorge_async(rpc_port: Optional[int], delta_block_height: str, start: str) -> None:
    """
    Calculates the estimated space on the network given two block header hashes.
    """
    async with get_any_service_client(FullNodeRpcClient, rpc_port) as node_config_fp:
        client, _, _ = node_config_fp
        if client is not None:
            my_start = 0
            my_step = 4608
            my_stop = 1_000_000
            estimated_seconds_per_block = 9.375
            blockchain_state = await client.get_blockchain_state()
            peak = blockchain_state["peak"]
            peak_height = peak.height
            print(f"peak height: {peak_height}")

            step = timedelta(days=1)

            start_height = 1
            start_block_header = await client.get_block_record_by_height(start_height)
            start_time = datetime.fromtimestamp(start_block_header.timestamp, tz=timezone.utc)
            end_limit_time = start_time.replace(hour=0, minute=0, second=0) + timedelta(days=1)
            # print(f"{end_limit_time=} {end_limit_time - start_time=}")

            for _ in range(1000):
                last_block_header = await get_block_range_for_day(
                    client, end_limit_time, estimated_seconds_per_block, start_height, start_time, step
                )
                netspace = await client.get_network_space(start_block_header.header_hash, last_block_header.header_hash)
                print(
                    f"{start_time.isoformat()},{start_height},{last_block_header.height},{netspace},{netspace//1_000_000_000_000_000}"
                )
                start_block_header = last_block_header
                start_height = last_block_header.height + 1
                start_time = end_limit_time
                end_limit_time = start_time.replace(hour=0, minute=0, second=0) + timedelta(days=1)
            return
            # while height

            for height in range(my_start + my_step, my_stop, my_step):
                if delta_block_height:
                    # if start == "":
                    #     blockchain_state = await client.get_blockchain_state()
                    #     if blockchain_state["peak"] is None:
                    #         print("No blocks in blockchain")
                    #         return None
                    #
                    #     newer_block_height = blockchain_state["peak"].height
                    # else:
                    #     newer_block = await client.get_block_record(hexstr_to_bytes(start))
                    #     if newer_block is None:
                    #         print("Block header hash", start, "not found.")
                    #         return None
                    #     else:
                    #         print("newer_height", newer_block.height)
                    #         newer_block_height = newer_block.height

                    newer_block_height = height
                    delta_block_height = my_step

                    newer_block_header = await client.get_block_record_by_height(newer_block_height)
                    older_block_height = max(0, newer_block_height - int(delta_block_height))
                    older_block_header = await client.get_block_record_by_height(older_block_height)
                    assert newer_block_header is not None and older_block_header is not None
                    network_space_bytes_estimate = await client.get_network_space(
                        newer_block_header.header_hash, older_block_header.header_hash
                    )
                    assert network_space_bytes_estimate is not None
                    # print(
                    #     "Older Block\n"
                    #     f"Block Height: {older_block_header.height}\n"
                    #     f"Weight:           {older_block_header.weight}\n"
                    #     f"VDF Iterations:   {older_block_header.total_iters}\n"
                    #     f"Header Hash:      0x{older_block_header.header_hash}\n"
                    # )
                    # print(
                    #     "Newer Block\n"
                    #     f"Block Height: {newer_block_header.height}\n"
                    #     f"Weight:           {newer_block_header.weight}\n"
                    #     f"VDF Iterations:   {newer_block_header.total_iters}\n"
                    #     f"Header Hash:      0x{newer_block_header.header_hash}\n"
                    # )
                    print(format_bytes(network_space_bytes_estimate))


async def get_block_range_for_day(
    client, end_limit_time, estimated_seconds_per_block, start_height, start_time, step
) -> BlockRecord:
    for _ in range(25):
        # print(" ====")
        estimated_end_time = start_time + step
        estimated_blocks = int((end_limit_time - start_time).total_seconds() / estimated_seconds_per_block)
        estimated_end_block_height = start_height + estimated_blocks
        # print(f"{start_height=} {estimated_blocks=} {estimated_end_block_height=}")
        while True:
            block_header = await client.get_block_record_by_height(estimated_end_block_height)

            if block_header.timestamp is not None:
                break

            estimated_end_block_height += 1
        end_time = datetime.fromtimestamp(block_header.timestamp, tz=timezone.utc)

        actual_block_height_delta = block_header.height - start_height
        actual_time_delta = end_time - start_time
        estimated_seconds_per_block = actual_time_delta.total_seconds() / actual_block_height_delta

        # print(f"{end_time=}")
        # print(f"{start_time=} {actual_block_height_delta=} {actual_time_delta.total_seconds()/(24*60*60)=}")
        # print(f"{block_header.height=} {end_time=}")

        if abs((end_time - end_limit_time).total_seconds()) < 20 * 60:
            break
    else:
        raise Exception("didn't get close enough")

    return block_header
