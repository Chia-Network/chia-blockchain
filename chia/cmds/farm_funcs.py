from typing import Any, Dict, List, Optional

import aiohttp

from chia.cmds.units import units
from chia.consensus.block_record import BlockRecord
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.util.misc import format_minutes

SECONDS_PER_BLOCK = (24 * 3600) / 4608


async def get_plots(harvester_rpc_port: int) -> Optional[Dict[str, Any]]:
    plots = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if harvester_rpc_port is None:
            harvester_rpc_port = config["harvester"]["rpc_port"]
        harvester_client = await HarvesterRpcClient.create(
            self_hostname, uint16(harvester_rpc_port), DEFAULT_ROOT_PATH, config
        )
        plots = await harvester_client.get_plots()
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if harvester is running at {harvester_rpc_port}")
        else:
            print(f"Exception from 'harvester' {e}")

    harvester_client.close()
    await harvester_client.await_closed()
    return plots


async def get_blockchain_state(rpc_port: int) -> Optional[Dict[str, Any]]:
    blockchain_state = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        blockchain_state = await client.get_blockchain_state()
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {rpc_port}")
        else:
            print(f"Exception from 'full node' {e}")

    client.close()
    await client.await_closed()
    return blockchain_state


async def get_average_block_time(rpc_port: int) -> float:
    try:
        blocks_to_compare = 500
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["full_node"]["rpc_port"]
        client = await FullNodeRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        blockchain_state = await client.get_blockchain_state()
        curr: Optional[BlockRecord] = blockchain_state["peak"]
        if curr is None or curr.height < (blocks_to_compare + 100):
            client.close()
            await client.await_closed()
            return SECONDS_PER_BLOCK
        while curr is not None and curr.height > 0 and not curr.is_transaction_block:
            curr = await client.get_block_record(curr.prev_hash)
        if curr is None:
            client.close()
            await client.await_closed()
            return SECONDS_PER_BLOCK

        past_curr = await client.get_block_record_by_height(curr.height - blocks_to_compare)
        while past_curr is not None and past_curr.height > 0 and not past_curr.is_transaction_block:
            past_curr = await client.get_block_record(past_curr.prev_hash)
        if past_curr is None:
            client.close()
            await client.await_closed()
            return SECONDS_PER_BLOCK

        client.close()
        await client.await_closed()
        return (curr.timestamp - past_curr.timestamp) / (curr.height - past_curr.height)

    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {rpc_port}")
        else:
            print(f"Exception from 'full node' {e}")

    client.close()
    await client.await_closed()
    return SECONDS_PER_BLOCK


async def get_wallets_stats(wallet_rpc_port: int) -> Optional[Dict[str, Any]]:
    amounts = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
        amounts = await wallet_client.get_farmed_amount()
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if wallet is running at {wallet_rpc_port}")
        else:
            print(f"Exception from 'wallet' {e}")

    wallet_client.close()
    await wallet_client.await_closed()
    return amounts


async def is_farmer_running(farmer_rpc_port: int) -> bool:
    is_running = False
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if farmer_rpc_port is None:
            farmer_rpc_port = config["farmer"]["rpc_port"]
        farmer_client = await FarmerRpcClient.create(self_hostname, uint16(farmer_rpc_port), DEFAULT_ROOT_PATH, config)
        await farmer_client.get_connections()
        is_running = True
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if farmer is running at {farmer_rpc_port}")
        else:
            print(f"Exception from 'farmer' {e}")

    farmer_client.close()
    await farmer_client.await_closed()
    return is_running


async def get_challenges(farmer_rpc_port: int) -> Optional[List[Dict[str, Any]]]:
    signage_points = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if farmer_rpc_port is None:
            farmer_rpc_port = config["farmer"]["rpc_port"]
        farmer_client = await FarmerRpcClient.create(self_hostname, uint16(farmer_rpc_port), DEFAULT_ROOT_PATH, config)
        signage_points = await farmer_client.get_signage_points()
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(f"Connection error. Check if farmer is running at {farmer_rpc_port}")
        else:
            print(f"Exception from 'farmer' {e}")

    farmer_client.close()
    await farmer_client.await_closed()
    return signage_points


async def challenges(farmer_rpc_port: int, limit: int) -> None:
    signage_points = await get_challenges(farmer_rpc_port)
    if signage_points is None:
        return

    signage_points.reverse()
    if limit != 0:
        signage_points = signage_points[:limit]

    for signage_point in signage_points:
        print(
            (
                f"Hash: {signage_point['signage_point']['challenge_hash']}"
                f"Index: {signage_point['signage_point']['signage_point_index']}"
            )
        )


class Summary:
    def __init__(self):
        self.status = None
        self.total_chia_farmed = None
        self.user_transaction_fees = None
        self.block_rewards = None
        self.last_height_farmed = None
        self.total_plot_size = None
        self.plot_count = None
        self.estimated_network_space = None
        self.expected_time_to_win = None

    def __str__(self):
        def format(name: str, value: str) -> str:
            output = f"{name}: "
            if value is None:
                output += "Unknown"
            else:
                output += f"{value}"
            output += "\n"
            return output

        output = format("Farming status", self.status)
        output += format("Total chia farmed", self.total_chia_farmed)
        output += format("User transaction fees", self.user_transaction_fees)
        output += format("Block rewards", self.block_rewards)
        output += format("Last height farmed", self.last_height_farmed)
        output += format("Plot count", self.plot_count)

        output += "Total size of plots: "
        if self.total_plot_size is None:
            output += "Unknown"
        else:
            plots_space_human_readable = self.total_plot_size / 1024 ** 3
            unit = "GiB"
            if plots_space_human_readable >= 1024 ** 2:
                plots_space_human_readable = plots_space_human_readable / (1024 ** 2)
                unit = "PiB"
            elif plots_space_human_readable >= 1024:
                plots_space_human_readable = plots_space_human_readable / 1024
                unit = "TiB"
            output += f"{plots_space_human_readable:.3f} {unit}"
        output += "\n"

        output += "Estimated network space: "
        if self.estimated_network_space is None:
            output += "Unknown"
        else:
            unit = "TiB"
            network_space_human_readable = self.estimated_network_space / 1024 ** 4
            if network_space_human_readable >= 1024:
                network_space_human_readable = network_space_human_readable / 1024
                unit = "PiB"
            output += f"{network_space_human_readable:.3f} {unit}"
        output += "\n"

        output += "Expected time to win: " + format_minutes(self.expected_time_to_win) + "\n"
        output += "Note: log into your key using 'chia wallet show' to see rewards for each key"
        return output


async def summary(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int,
                  farmer_rpc_port: int) -> Summary:
    amounts = await get_wallets_stats(wallet_rpc_port)
    plots = await get_plots(harvester_rpc_port)
    blockchain_state = await get_blockchain_state(rpc_port)
    farmer_running = await is_farmer_running(farmer_rpc_port)

    summary = Summary()
    if blockchain_state is None:
        summary.status = "Not available"
    elif blockchain_state["sync"]["sync_mode"]:
        summary.status = "Syncing"
    elif not blockchain_state["sync"]["synced"]:
        summary.status = "Not synced or not connected to peers"
    elif not farmer_running:
        summary.status = "Not running"
    else:
        summary.status = "Farming"

    if amounts is not None:
        summary.total_chia_farmed = amounts['farmed_amount'] / units['chia']
        summary.user_transaction_fees = amounts['fee_amount'] / units['chia']
        summary.block_rewards = (amounts['farmer_reward_amount'] +
                                 amounts['pool_reward_amount']) / units['chia']
        summary.last_height_farmed = amounts['last_height_farmed']

    if plots is not None:
        summary.total_plot_size = sum(map(lambda x: x["file_size"],
                                          plots["plots"]))
        summary.plot_count = len(plots['plots'])

    if blockchain_state is not None:
        summary.estimated_network_space = blockchain_state["space"]

    if blockchain_state is not None and plots is not None:
        total_plot_size = summary.total_plot_size or 0
        proportion = total_plot_size / blockchain_state["space"] if blockchain_state["space"] else -1
        minutes = int((await get_average_block_time(rpc_port) / 60) / proportion) if proportion else -1
        summary.expected_time_to_win = minutes
    return summary
