import math
from typing import Optional, Dict, Any, List
import asyncio
from decimal import Decimal

import click

import aiohttp

from src.rpc.wallet_rpc_client import WalletRpcClient
from src.rpc.harvester_rpc_client import HarvesterRpcClient
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.rpc.farmer_rpc_client import FarmerRpcClient
from src.util.config import load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.ints import uint16
from src.wallet.util.transaction_type import TransactionType

MINUTES_PER_BLOCK = (24 * 60) / 4608  # 0.3125


def compute_wallets_stats(wallets):
    biggest_height = 0
    biggest_reward_height = 0
    pool_coins = 0
    farmer_coins = 0

    pool_coins = Decimal(0)
    for wallet in wallets:
        if "transactions" not in wallet:
            continue

        for tx in wallet["transactions"] or []:
            if len(tx.additions) == 0:
                continue

            if tx.type == TransactionType.COINBASE_REWARD:
                pool_coins += tx.amount
            if tx.type == TransactionType.FEE_REWARD:
                farmer_coins += tx.amount

            is_from_reward = tx.type in [TransactionType.COINBASE_REWARD, TransactionType.FEE_REWARD]
            biggest_height = max(tx.confirmed_at_height, biggest_height)

            if is_from_reward:
                biggest_reward_height = max(tx.confirmed_at_height, biggest_reward_height)

    total_chia_farmed = pool_coins + farmer_coins
    total_block_rewards = (pool_coins * 8) / 7
    user_transaction_fees = (farmer_coins - total_block_rewards) / 8
    block_rewards = pool_coins + farmer_coins - user_transaction_fees

    return {
        "total_chia_farmed": total_chia_farmed,
        "biggest_height": biggest_height,
        "biggest_reward_height": biggest_reward_height,
        "pool_coins": pool_coins,
        "farmer_coins": farmer_coins,
        "total_block_rewards": total_block_rewards,
        "user_transaction_fees": user_transaction_fees,
        "block_rewards": block_rewards,
    }


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
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
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
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if full node is running at {rpc_port}")
        else:
            print(f"Exception from 'full node' {e}")

    client.close()
    await client.await_closed()
    return blockchain_state


async def get_wallets_stats(wallet_rpc_port: int) -> Optional[Dict[str, Any]]:
    stats = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
        wallets = await wallet_client.get_wallets()
        stats = compute_wallets_stats(wallets)
    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if wallet is running at {wallet_rpc_port}")
        else:
            print(f"Exception from 'wallet' {e}")

    wallet_client.close()
    await wallet_client.await_closed()
    return stats


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
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
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
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
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


async def summary(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    wallets_stats = await get_wallets_stats(wallet_rpc_port)
    plots = await get_plots(harvester_rpc_port)
    blockchain_state = await get_blockchain_state(rpc_port)
    farmer_running = await is_farmer_running(farmer_rpc_port)

    print("Farming status: ", end="")
    if blockchain_state is None:
        print("Not available")
    elif blockchain_state["sync"]["sync_mode"]:
        print("Syncing")
    elif not blockchain_state["sync"]["synced"]:
        print("Not available")
    elif not farmer_running:
        print("Not running")
    else:
        print("Farming")

    if wallets_stats is not None:
        print(f"Total chia farmed: {wallets_stats['total_chia_farmed']}")
        print(f"User transaction fees: {wallets_stats['user_transaction_fees']}")
        print(f"Block rewards: {wallets_stats['block_rewards']}")
        print(f"Last height farmerd: {wallets_stats['biggest_reward_height']}")
    else:
        print("Total chia farmed: Unknown")
        print("User transaction fees: Unknown")
        print("Block rewards: Unkown")
        print("Last height farmed: Unkown")

    total_plot_size = 0
    if plots is not None:
        total_plot_size = sum(map(lambda x: x["file_size"], plots["plots"]))

        print(f"Plot count: {len(plots['plots'])}")

        print("Total size of plots: ", end="")
        plots_space_human_readable = total_plot_size / 1024 ** 3
        if plots_space_human_readable >= 1024 ** 2:
            plots_space_human_readable = plots_space_human_readable / 1024
            print(f"{plots_space_human_readable:.3f} PiB")
        elif plots_space_human_readable >= 1024:
            print(f"{plots_space_human_readable:.3f} TiB")
        else:
            print(f"{plots_space_human_readable:.3f} GiB")
    else:
        print("Plot count: Unknown")
        print("Total size of plots: Unknown")

    if blockchain_state is not None:
        print("Estimated network space: ", end="")
        network_space_human_readable = blockchain_state["space"] / 1024 ** 4
        if network_space_human_readable >= 1024:
            network_space_human_readable = network_space_human_readable / 1024
            print(f"{network_space_human_readable:.3f} PiB")
        else:
            print(f"{network_space_human_readable:.3f} TiB")
    else:
        print("Estimated network space: Unknown")

    if blockchain_state is not None and plots is not None:
        proportion = total_plot_size / blockchain_state["space"] if blockchain_state["space"] else 0
        minutes = MINUTES_PER_BLOCK / proportion if proportion else 0

        print("Expected time to win: ", end="")
        if minutes == 0:
            print("Unknown")
        elif minutes > 60 * 24:
            print(f"{math.floor(minutes/(60*24))} days")
        elif minutes > 60:
            print(f"{math.floor(minutes/60)} hours")
        else:
            print(f"{math.floor(minutes)} minutes")
    else:
        print("Expected time to win: Unknown")


@click.group("farm", short_help="Manage your farm")
def farm_cmd() -> None:
    pass


@farm_cmd.command("summary", short_help="Summary farming information")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=8555,
    show_default=True,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=9256,
    show_default=True,
)
@click.option(
    "-hp",
    "--harvester-rpc-port",
    help=(
        "Set the port where the Harvester is hosting the RPC interface"
        "See the rpc_port under harvester in config.yaml"
    ),
    type=int,
    default=8560,
    show_default=True,
)
@click.option(
    "-fp",
    "--farmer-rpc-port",
    help=(
        "Set the port where the Farmer is hosting the RPC interface. " "See the rpc_port under farmer in config.yaml"
    ),
    type=int,
    default=8559,
    show_default=True,
)
def summary_cmd(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    asyncio.run(summary(rpc_port, wallet_rpc_port, harvester_rpc_port, farmer_rpc_port))


@farm_cmd.command("challenges", short_help="Show the lastest challenges")
@click.option(
    "-fp",
    "--farmer-rpc-port",
    help="Set the port where the Farmer is hosting the RPC interface. See the rpc_port under farmer in config.yaml",
    type=int,
    default=8559,
    show_default=True,
)
@click.option(
    "-l",
    "--limit",
    help="Limit the number of challenges shown. Use 0 to disable the limit",
    type=click.IntRange(0),
    default=20,
    show_default=True,
)
def challenges_cmd(farmer_rpc_port: int, limit: int) -> None:
    asyncio.run(challenges(farmer_rpc_port, limit))
