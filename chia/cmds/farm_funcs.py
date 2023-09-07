from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.cmds.units import units
from chia.consensus.block_record import BlockRecord
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.misc import format_bytes, format_minutes
from chia.util.network import is_localhost

SECONDS_PER_BLOCK = (24 * 3600) / 4608


async def get_harvesters_summary(
    farmer_rpc_port: Optional[int], root_path: Path = DEFAULT_ROOT_PATH
) -> Optional[Dict[str, Any]]:
    async with get_any_service_client(FarmerRpcClient, farmer_rpc_port, root_path) as (farmer_client, _):
        return await farmer_client.get_harvesters_summary()


async def get_blockchain_state(
    rpc_port: Optional[int], root_path: Path = DEFAULT_ROOT_PATH
) -> Optional[Dict[str, Any]]:
    async with get_any_service_client(FullNodeRpcClient, rpc_port, root_path) as (client, _):
        return await client.get_blockchain_state()


async def get_average_block_time(rpc_port: Optional[int], root_path: Path = DEFAULT_ROOT_PATH) -> float:
    async with get_any_service_client(FullNodeRpcClient, rpc_port, root_path) as (client, _):
        blocks_to_compare = 500
        blockchain_state = await client.get_blockchain_state()
        curr: Optional[BlockRecord] = blockchain_state["peak"]
        if curr is None or curr.height < (blocks_to_compare + 100):
            return SECONDS_PER_BLOCK
        while curr is not None and curr.height > 0 and not curr.is_transaction_block:
            curr = await client.get_block_record(curr.prev_hash)
        if curr is None or curr.timestamp is None or curr.height is None:
            # stupid mypy
            return SECONDS_PER_BLOCK
        past_curr = await client.get_block_record_by_height(curr.height - blocks_to_compare)
        while past_curr is not None and past_curr.height > 0 and not past_curr.is_transaction_block:
            past_curr = await client.get_block_record(past_curr.prev_hash)
        if past_curr is None or past_curr.timestamp is None or past_curr.height is None:
            # stupid mypy
            return SECONDS_PER_BLOCK
        return (curr.timestamp - past_curr.timestamp) / (curr.height - past_curr.height)


async def get_wallets_stats(
    wallet_rpc_port: Optional[int], root_path: Path = DEFAULT_ROOT_PATH
) -> Optional[Dict[str, Any]]:
    async with get_any_service_client(WalletRpcClient, wallet_rpc_port, root_path) as (wallet_client, _):
        return await wallet_client.get_farmed_amount()


async def get_challenges(farmer_rpc_port: Optional[int]) -> Optional[List[Dict[str, Any]]]:
    async with get_any_service_client(FarmerRpcClient, farmer_rpc_port) as (farmer_client, _):
        return await farmer_client.get_signage_points()


async def challenges(farmer_rpc_port: Optional[int], limit: int) -> None:
    signage_points = await get_challenges(farmer_rpc_port)
    if signage_points is None:
        return None

    signage_points.reverse()
    if limit != 0:
        signage_points = signage_points[:limit]

    for signage_point in signage_points:
        print(
            (
                f"Hash: {signage_point['signage_point']['challenge_hash']} "
                f"Index: {signage_point['signage_point']['signage_point_index']}"
            )
        )


async def summary(
    rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    harvester_rpc_port: Optional[int],
    farmer_rpc_port: Optional[int],
    root_path: Path = DEFAULT_ROOT_PATH,
) -> None:
    harvesters_summary = await get_harvesters_summary(farmer_rpc_port, root_path)
    blockchain_state = await get_blockchain_state(rpc_port, root_path)
    farmer_running = False if harvesters_summary is None else True  # harvesters uses farmer rpc too

    wallet_not_ready: bool = False
    amounts = None
    try:
        amounts = await get_wallets_stats(wallet_rpc_port, root_path)
    except Exception:
        wallet_not_ready = True
    wallet_not_running: bool = True if amounts is None else False

    print("Farming status: ", end="")
    if blockchain_state is None:
        print("Not available")
    elif blockchain_state["sync"]["sync_mode"]:
        print("Syncing")
    elif not blockchain_state["sync"]["synced"]:
        print("Not synced or not connected to peers")
    elif not farmer_running:
        print("Not running")
    else:
        print("Farming")

    if amounts is not None:
        print(f"Total chia farmed: {amounts['farmed_amount'] / units['chia']}")
        print(f"User transaction fees: {amounts['fee_amount'] / units['chia']}")
        print(f"Block rewards: {(amounts['farmer_reward_amount'] + amounts['pool_reward_amount']) / units['chia']}")
        print(f"Last height farmed: {amounts['last_height_farmed']}")

    class PlotStats:
        total_plot_size = 0
        total_effective_plot_size = 0
        total_plots = 0

    if harvesters_summary is not None:
        harvesters_local: Dict[str, Dict[str, Any]] = {}
        harvesters_remote: Dict[str, Dict[str, Any]] = {}
        for harvester in harvesters_summary["harvesters"]:
            ip = harvester["connection"]["host"]
            if is_localhost(ip):
                harvesters_local[harvester["connection"]["node_id"]] = harvester
            else:
                if ip not in harvesters_remote:
                    harvesters_remote[ip] = {}
                harvesters_remote[ip][harvester["connection"]["node_id"]] = harvester

        def process_harvesters(harvester_peers_in: Dict[str, Dict[str, Any]]) -> None:
            for harvester_peer_id, harvester_dict in harvester_peers_in.items():
                syncing = harvester_dict["syncing"]
                if syncing is not None and syncing["initial"]:
                    print(f"   Loading plots: {syncing['plot_files_processed']} / {syncing['plot_files_total']}")
                else:
                    total_plot_size_harvester = harvester_dict["total_plot_size"]
                    total_effective_plot_size_harvester = harvester_dict["total_effective_plot_size"]
                    plot_count_harvester = harvester_dict["plots"]
                    PlotStats.total_plot_size += total_plot_size_harvester
                    PlotStats.total_effective_plot_size += total_effective_plot_size_harvester
                    PlotStats.total_plots += plot_count_harvester
                    print(
                        f"   {plot_count_harvester} plots of size: {format_bytes(total_plot_size_harvester)} on-disk, "
                        f"{format_bytes(total_effective_plot_size_harvester)}e (effective)"
                    )

        if len(harvesters_local) > 0:
            print(f"Local Harvester{'s' if len(harvesters_local) > 1 else ''}")
            process_harvesters(harvesters_local)
        for harvester_ip, harvester_peers in harvesters_remote.items():
            print(f"Remote Harvester{'s' if len(harvester_peers) > 1 else ''} for IP: {harvester_ip}")
            process_harvesters(harvester_peers)

        print(f"Plot count for all harvesters: {PlotStats.total_plots}")

        print(
            f"Total size of plots: {format_bytes(PlotStats.total_plot_size)}, "
            f"{format_bytes(PlotStats.total_effective_plot_size)}e (effective)"
        )
    else:
        print("Plot count: Unknown")
        print("Total size of plots: Unknown")

    if blockchain_state is not None:
        print("Estimated network space: ", end="")
        print(format_bytes(blockchain_state["space"]))
    else:
        print("Estimated network space: Unknown")

    minutes = -1
    if blockchain_state is not None and harvesters_summary is not None:
        proportion = (
            PlotStats.total_effective_plot_size / blockchain_state["space"] if blockchain_state["space"] else -1
        )
        minutes = int((await get_average_block_time(rpc_port, root_path) / 60) / proportion) if proportion else -1

    if harvesters_summary is not None and PlotStats.total_plots == 0:
        print("Expected time to win: Never (no plots)")
    else:
        print("Expected time to win: " + format_minutes(minutes))

    if amounts is None:
        if wallet_not_running:
            print("For details on farmed rewards and fees you should run 'chia start wallet' and 'chia wallet show'")
        elif wallet_not_ready:
            print("For details on farmed rewards and fees you should run 'chia wallet show'")
    else:
        print("Note: log into your key using 'chia wallet show' to see rewards for each key")
