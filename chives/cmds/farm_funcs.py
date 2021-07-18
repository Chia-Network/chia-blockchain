from typing import Any, Dict, List, Optional

import aiohttp

from chives.cmds.units import units
from chives.consensus.block_record import BlockRecord
from chives.rpc.farmer_rpc_client import FarmerRpcClient
from chives.rpc.full_node_rpc_client import FullNodeRpcClient
from chives.rpc.harvester_rpc_client import HarvesterRpcClient
from chives.rpc.wallet_rpc_client import WalletRpcClient
from chives.util.config import load_config
from chives.util.default_root import DEFAULT_ROOT_PATH
from chives.util.ints import uint16
from chives.util.misc import format_bytes
from chives.util.misc import format_minutes

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
    #
    # Don't catch any exceptions, the caller will handle it
    #
    finally:
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
        return None

    signage_points.reverse()
    if limit != 0:
        signage_points = signage_points[:limit]
    
    #print(signage_points)
    for signage_point in signage_points:
        print(
            (
                f"Hash: {signage_point['signage_point']['challenge_hash']} "
                f"Index: {signage_point['signage_point']['signage_point_index']}"
            )
        )


async def summary(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    plots = await get_plots(harvester_rpc_port)
    blockchain_state = await get_blockchain_state(rpc_port)
    farmer_running = await is_farmer_running(farmer_rpc_port)

    wallet_not_ready: bool = False
    wallet_not_running: bool = False
    amounts = None
    try:
        amounts = await get_wallets_stats(wallet_rpc_port)
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            wallet_not_running = True
        else:
            wallet_not_ready = True

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
        print(f"Total chives farmed: {amounts['farmed_amount'] / units['chives']}")
        print(f"User transaction fees: {amounts['fee_amount'] / units['chives']}")
        print(f"Block rewards: {(amounts['farmer_reward_amount'] + amounts['community_reward_amount'] + amounts['pool_reward_amount']) / units['chives']}")
        print(f"Last height farmed: {amounts['last_height_farmed']}")
        print(f"Farmer Reward: {amounts['farmer_reward_amount'] / units['chives']}")
        print(f"Pool Reward: {amounts['pool_reward_amount'] / units['chives']}")

    total_plot_size = 0
    if plots is not None:
        total_plot_size = sum(map(lambda x: x["file_size"], plots["plots"]))

        print(f"Plot count: {len(plots['plots'])}")

        print("Total size of plots: ", end="")
        print(format_bytes(total_plot_size))
    else:
        print("Plot count: Unknown")
        print("Total size of plots: Unknown")

    if blockchain_state is not None:
        print("Estimated network space: ", end="")
        print(format_bytes(blockchain_state["space"]))
    else:
        print("Estimated network space: Unknown")

    minutes = -1
    if blockchain_state is not None and plots is not None:
        proportion = total_plot_size / blockchain_state["space"] if blockchain_state["space"] else -1
        minutes = int((await get_average_block_time(rpc_port) / 60) / proportion) if proportion else -1

    if plots is not None and len(plots["plots"]) == 0:
        print("Expected time to win: Never (no plots)")
    else:
        print("Expected time to win: " + format_minutes(minutes))

    if amounts is None:
        if wallet_not_running:
            print("For details on farmed rewards and fees you should run 'chives start wallet' and 'chives wallet show'")
        elif wallet_not_ready:
            print("For details on farmed rewards and fees you should run 'chives wallet show'")
    else:
        print("Note: log into your key using 'chives wallet show' to see rewards for each key")


async def uploadfarmerdata(rpc_port: int, wallet_rpc_port: int, harvester_rpc_port: int, farmer_rpc_port: int) -> None:
    plots = await get_plots(harvester_rpc_port)
    blockchain_state = await get_blockchain_state(rpc_port)
    farmer_running = await is_farmer_running(farmer_rpc_port)

    wallet_not_ready: bool = False
    wallet_not_running: bool = False
    amounts = None
    try:
        amounts = await get_wallets_stats(wallet_rpc_port)
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            wallet_not_running = True
        else:
            wallet_not_ready = True

    FarmingStatus = ""
    if blockchain_state is None:
        FarmingStatus = "Not available"
    elif blockchain_state["sync"]["sync_mode"]:
        FarmingStatus = "Syncing"
    elif not blockchain_state["sync"]["synced"]:
        FarmingStatus = "Not synced or not connected to peers"
    elif not farmer_running:
        FarmingStatus = "Not running"
    else:
        FarmingStatus = "Farming"

    total_plot_size = 0
    if plots is not None:
        total_plot_size = sum(map(lambda x: x["file_size"], plots["plots"]))
        PlotCount = len(plots['plots'])
        TotalSizeOfPlots = format_bytes(total_plot_size)
    else:
        PlotCount = "Unknown"
        TotalSizeOfPlots = "Unknown"

    if blockchain_state is not None:
        EstimatedNetworkSpace = format_bytes(blockchain_state["space"])
    else:
        EstimatedNetworkSpace = "Unknown"

    minutes = -1
    if blockchain_state is not None and plots is not None:
        proportion = total_plot_size / blockchain_state["space"] if blockchain_state["space"] else -1
        minutes = int((await get_average_block_time(rpc_port) / 60) / proportion) if proportion else -1

    if plots is not None and len(plots["plots"]) == 0:
        ExpectedTimeToWin = "Never (no plots)"
    else:
        ExpectedTimeToWin = format_minutes(minutes)
    
    signage_points = await get_challenges(farmer_rpc_port)
    if signage_points is None:
        ""
    else:
        signage_points.reverse()
        limit = 10
        if limit != 0:
            signage_points = signage_points[:limit]
    
    #get wallet address and fingerprint
    from typing import List
    from blspy import AugSchemeMPL, G1Element, G2Element
    from chives.consensus.coinbase import create_puzzlehash_for_pk
    from chives.util.bech32m import encode_puzzle_hash
    from chives.util.config import load_config
    from chives.util.default_root import DEFAULT_ROOT_PATH
    from chives.util.ints import uint32
    from chives.util.keychain import Keychain, bytes_to_mnemonic, generate_mnemonic
    from chives.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk

    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, "config.yaml")
    keychain: Keychain = Keychain()
    private_keys = keychain.get_all_private_keys()
    selected = config["selected_network"]
    prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    if len(private_keys) == 0:
        FingerPrint = "No private keys"
    else:
        for sk, seed in private_keys:
            FingerPrint = sk.get_g1().get_fingerprint()
            FingerPrint = str(FingerPrint)[0:6]
            Address = encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1()), prefix)
            break
    
    from hashlib import sha256
    RETURN_TEXT     = {}
    RETURN_TEXT['FingerPrint'] = FingerPrint
    RETURN_TEXT['Address0'] = Address[0:45]
    RETURN_TEXT['Address'] = sha256(Address[0:45].encode('utf-8')).hexdigest()
    RETURN_TEXT['FarmingStatus'] = FarmingStatus
    RETURN_TEXT['PlotCount'] = PlotCount
    RETURN_TEXT['TotalSizeOfPlots'] = TotalSizeOfPlots
    RETURN_TEXT['EstimatedNetworkSpace'] = EstimatedNetworkSpace
    RETURN_TEXT['amounts'] = amounts
    RETURN_TEXT['wallet_not_running'] = wallet_not_running
    RETURN_TEXT['wallet_not_ready'] = wallet_not_ready
    RETURN_TEXT['signage_points'] = signage_points
    return RETURN_TEXT
    #print(signage_points)
    