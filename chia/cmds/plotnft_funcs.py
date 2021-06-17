import aiohttp
import asyncio
import json
import time
from pprint import pprint
from typing import List, Dict, Optional

from chia.pools.pool_wallet_info import PoolWalletInfo, PoolSingletonState
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType


async def create_pool_args(pool_url: str) -> Dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{pool_url}/pool_info") as response:
                if response.ok:
                    json_dict = json.loads(await response.text())
                else:
                    raise ValueError(f"Response from {pool_url} not OK: {response.status}")
    except Exception as e:
        raise ValueError(f"Error connecting to pool {pool_url}: {e}")

    if json_dict["relative_lock_height"] > 1000:
        raise ValueError("Relative lock height too high for this pool, cannot join")
    if json_dict["protocol_version"] != POOL_PROTOCOL_VERSION:
        raise ValueError(f"Incorrect version: {json_dict['protocol_version']}, should be {POOL_PROTOCOL_VERSION}")

    header_msg = f"\n---- Pool parameters fetched from {pool_url} ----"
    print(header_msg)
    pprint(json_dict)
    print("-" * len(header_msg))
    return json_dict


async def create(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    state = args["state"]

    # Could use initial_pool_state_from_dict to simplify
    if state == "SELF_POOLING":
        pool_url: Optional[str] = None
        relative_lock_height = uint32(0)
        new_address = await wallet_client.get_next_address("1", True)
        target_puzzle_hash: bytes32 = decode_puzzle_hash(new_address)
    elif state == "FARMING_TO_POOL":
        pool_url = str(args["pool_url"])
        json_dict = await create_pool_args(pool_url)
        relative_lock_height = json_dict["relative_lock_height"]
        target_puzzle_hash = hexstr_to_bytes(json_dict["target_puzzle_hash"])
    else:
        raise ValueError("Plot NFT must be created in SELF_POOLING or FARMING_TO_POOL state.")

    pool_msg = f" and join pool: {pool_url}" if pool_url else ""
    print(f"Will create a plot NFT{pool_msg}.")

    user_input: str = input("Confirm [n]/y: ")
    if user_input.lower() == "y" or user_input.lower() == "yes":
        try:
            tx_record: TransactionRecord = await wallet_client.create_new_pool_wallet(
                target_puzzle_hash,
                pool_url,
                relative_lock_height,
                "localhost:5000",
                "new",
                state,
            )
            start = time.time()
            while time.time() - start < 10:
                await asyncio.sleep(0.1)
                tx = await wallet_client.get_transaction(str(1), tx_record.name)
                if len(tx.sent_to) > 0:
                    print(f"Transaction submitted to nodes: {tx.sent_to}")
                    print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_record.name} to get status")
                    return None
        except Exception as e:
            print(f"Error creating plot NFT: {e}")
        return
    print("Aborting.")


def pprint_pool_wallet_state(
    pool_wallet_info: PoolWalletInfo,
    address_prefix: str,
    pool_state_dict: Dict,
):
    print(f"Current state: {PoolSingletonState(pool_wallet_info.current.state).name}")
    print(f"Launcher ID: {pool_wallet_info.launcher_id}")
    print(f"Target address: {encode_puzzle_hash(pool_wallet_info.current.target_puzzle_hash, address_prefix)}")
    print(f"Pool URL: {pool_wallet_info.current.pool_url}")
    print(f"Owner public key: {pool_wallet_info.current.owner_pubkey}")
    print(f"Relative lock height: {pool_wallet_info.current.relative_lock_height} blocks")
    if pool_wallet_info.launcher_id in pool_state_dict:
        print(f"Current difficulty: {pool_state_dict[pool_wallet_info.launcher_id]['current_difficulty']}")
        print(f"Points balance: {pool_state_dict[pool_wallet_info.launcher_id]['current_points']}")
    print(
        f"P2 singleton address (pool contract address for plotting):"
        f"{encode_puzzle_hash(pool_wallet_info.p2_singleton_puzzle_hash, address_prefix)}"
    )
    if pool_wallet_info.target is not None:
        print(f"Target state: {PoolSingletonState(pool_wallet_info.target.state).name}")
        print(f"Pool URL: {pool_wallet_info.target.pool_url}")


async def show(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:

    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    self_hostname = config["self_hostname"]
    farmer_rpc_port = config["farmer"]["rpc_port"]
    farmer_client = await FarmerRpcClient.create(self_hostname, uint16(farmer_rpc_port), DEFAULT_ROOT_PATH, config)
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    summaries_response = await wallet_client.get_wallets()
    wallet_id_passed_in = args.get("id", None)
    try:
        pool_state_list: List = (await farmer_client.get_pool_state())["pool_state"]
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(
                f"Connection error. Check if farmer is running at {farmer_rpc_port}."
                f" You can run the farmer by:\n    chia start farmer-only"
            )
        else:
            print(f"Exception from 'wallet' {e}")
        farmer_client.close()
        await farmer_client.await_closed()
        return
    pool_state_dict: Dict[bytes32, Dict] = {
        hexstr_to_bytes(pool_state_item["pool_config"]["launcher_id"]): pool_state_item
        for pool_state_item in pool_state_list
    }
    if wallet_id_passed_in is not None:
        for summary in summaries_response:
            typ = WalletType(int(summary["type"]))
            if summary["id"] == wallet_id_passed_in and typ != WalletType.POOLING_WALLET:
                print(f"Wallet with id: {wallet_id_passed_in} is not a pooling wallet. Please provide a different id.")
                return
        response: PoolWalletInfo = await wallet_client.pw_status(wallet_id_passed_in)

        pprint_pool_wallet_state(response, address_prefix, pool_state_dict)
    else:
        print(f"Wallet height: {await wallet_client.get_height_info()}")
        print(f"Sync status: {'Synced' if (await wallet_client.get_synced()) else 'Not synced'}")
        for summary in summaries_response:
            wallet_id = summary["id"]
            typ = WalletType(int(summary["type"]))
            if typ == WalletType.POOLING_WALLET:
                print(f"Wallet id {wallet_id}: ")
                response = await wallet_client.pw_status(wallet_id)
                pprint_pool_wallet_state(response, address_prefix, pool_state_dict)
                print("")
    farmer_client.close()
    await farmer_client.await_closed()


async def get_login_link(launcher_id_str: str) -> None:
    launcher_id: bytes32 = hexstr_to_bytes(launcher_id_str)
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    self_hostname = config["self_hostname"]
    farmer_rpc_port = config["farmer"]["rpc_port"]
    farmer_client = await FarmerRpcClient.create(self_hostname, uint16(farmer_rpc_port), DEFAULT_ROOT_PATH, config)
    try:
        login_link: Optional[str] = await farmer_client.get_pool_login_link(launcher_id)
        if login_link is None:
            print("Was not able to get login link.")
        else:
            print(login_link)
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(
                f"Connection error. Check if farmer is running at {farmer_rpc_port}."
                f" You can run the farmer by:\n    chia start farmer-only"
            )
        else:
            print(f"Exception from 'farmer' {e}")
    finally:
        farmer_client.close()
        await farmer_client.await_closed()


async def join_pool(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    pool_url = args["pool_url"]
    wallet_id = args.get("id", None)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{pool_url}/pool_info") as response:
                if response.ok:
                    json_dict = json.loads(await response.text())
                else:
                    print(f"Response not OK: {response.status}")
                    return
    except Exception as e:
        print(f"Error connecting to pool {pool_url}: {e}")
        return

    if json_dict["relative_lock_height"] > 1000:
        print("Relative lock height too high for this pool, cannot join")
        return
    if json_dict["protocol_version"] != POOL_PROTOCOL_VERSION:
        print(f"Incorrect version: {json_dict['protocol_version']}, should be {POOL_PROTOCOL_VERSION}")
        return

    print(f"Will join pool: {pool_url} with Plot NFT {fingerprint}.")
    pprint(json_dict)
    user_input: str = input("Confirm [n]/y: ")
    if user_input.lower() == "y" or user_input.lower() == "yes":
        try:
            tx_record: TransactionRecord = await wallet_client.pw_join_pool(
                wallet_id,
                hexstr_to_bytes(json_dict["target_puzzle_hash"]),
                pool_url,
                json_dict["relative_lock_height"],
            )
            start = time.time()
            while time.time() - start < 10:
                await asyncio.sleep(0.1)
                tx = await wallet_client.get_transaction(str(1), tx_record.name)
                if len(tx.sent_to) > 0:
                    print(f"Transaction submitted to nodes: {tx.sent_to}")
                    print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_record.name} to get status")
                    return None
        except Exception as e:
            print(f"Error joining pool {pool_url} with Plot NFT {fingerprint}: {e}")
        return
    print("Aborting.")


async def self_pool(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args.get("id", None)

    print(f"Will start self-farming with Plot NFT {fingerprint}.")
    user_input: str = input("Confirm [n]/y: ")
    if user_input.lower() == "y" or user_input.lower() == "yes":
        try:
            tx_record: TransactionRecord = await wallet_client.pw_self_pool(wallet_id)
            start = time.time()
            while time.time() - start < 10:
                await asyncio.sleep(0.1)
                tx = await wallet_client.get_transaction(str(1), tx_record.name)
                if len(tx.sent_to) > 0:
                    print(f"Transaction submitted to nodes: {tx.sent_to}")
                    print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_record.name} to get status")
                    return None
        except Exception as e:
            print(f"Error attempting to self-farm with Plot NFT {fingerprint}: {e}")
        return
    print("Aborting.")
