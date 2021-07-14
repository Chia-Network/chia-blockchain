import aiohttp
import asyncio
import functools
import json
import time

from pprint import pprint
from typing import List, Dict, Optional, Callable

from chia.cmds.wallet_funcs import print_balance, wallet_coin_unit
from chia.pools.pool_wallet_info import PoolWalletInfo, PoolSingletonState
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
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
    prompt = not args.get("yes", False)

    # Could use initial_pool_state_from_dict to simplify
    if state == "SELF_POOLING":
        pool_url: Optional[str] = None
        relative_lock_height = uint32(0)
        target_puzzle_hash = None  # wallet will fill this in
    elif state == "FARMING_TO_POOL":
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        enforce_https = config["full_node"]["selected_network"] == "mainnet"
        pool_url = str(args["pool_url"])
        if enforce_https and not pool_url.startswith("https://"):
            print(f"Pool URLs must be HTTPS on mainnet {pool_url}. Aborting.")
            return
        json_dict = await create_pool_args(pool_url)
        relative_lock_height = json_dict["relative_lock_height"]
        target_puzzle_hash = hexstr_to_bytes(json_dict["target_puzzle_hash"])
    else:
        raise ValueError("Plot NFT must be created in SELF_POOLING or FARMING_TO_POOL state.")

    pool_msg = f" and join pool: {pool_url}" if pool_url else ""
    print(f"Will create a plot NFT{pool_msg}.")
    if prompt:
        user_input: str = input("Confirm [n]/y: ")
    else:
        user_input = "yes"

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


async def pprint_pool_wallet_state(
    wallet_client: WalletRpcClient,
    wallet_id: int,
    pool_wallet_info: PoolWalletInfo,
    address_prefix: str,
    pool_state_dict: Dict,
    unconfirmed_transactions: List[TransactionRecord],
):
    if pool_wallet_info.current.state == PoolSingletonState.LEAVING_POOL and pool_wallet_info.target is None:
        expected_leave_height = pool_wallet_info.singleton_block_height + pool_wallet_info.current.relative_lock_height
        print(f"Current state: INVALID_STATE. Please leave/join again after block height {expected_leave_height}")
    else:
        print(f"Current state: {PoolSingletonState(pool_wallet_info.current.state).name}")
    print(f"Current state from block height: {pool_wallet_info.singleton_block_height}")
    print(f"Launcher ID: {pool_wallet_info.launcher_id}")
    print(
        "Target address (not for plotting): "
        f"{encode_puzzle_hash(pool_wallet_info.current.target_puzzle_hash, address_prefix)}"
    )
    print(f"Owner public key: {pool_wallet_info.current.owner_pubkey}")

    print(
        f"P2 singleton address (pool contract address for plotting): "
        f"{encode_puzzle_hash(pool_wallet_info.p2_singleton_puzzle_hash, address_prefix)}"
    )
    if pool_wallet_info.target is not None:
        print(f"Target state: {PoolSingletonState(pool_wallet_info.target.state).name}")
        print(f"Target pool URL: {pool_wallet_info.target.pool_url}")
    if pool_wallet_info.current.state == PoolSingletonState.SELF_POOLING.value:
        balances: Dict = await wallet_client.get_wallet_balance(str(wallet_id))
        balance = balances["confirmed_wallet_balance"]
        typ = WalletType(int(WalletType.POOLING_WALLET))
        address_prefix, scale = wallet_coin_unit(typ, address_prefix)
        print(f"Claimable balance: {print_balance(balance, scale, address_prefix)}")
    if pool_wallet_info.current.state == PoolSingletonState.FARMING_TO_POOL:
        print(f"Current pool URL: {pool_wallet_info.current.pool_url}")
        if pool_wallet_info.launcher_id in pool_state_dict:
            print(f"Current difficulty: {pool_state_dict[pool_wallet_info.launcher_id]['current_difficulty']}")
            print(f"Points balance: {pool_state_dict[pool_wallet_info.launcher_id]['current_points']}")
        print(f"Relative lock height: {pool_wallet_info.current.relative_lock_height} blocks")
        payout_instructions: str = pool_state_dict[pool_wallet_info.launcher_id]["pool_config"]["payout_instructions"]
        try:
            payout_address = encode_puzzle_hash(bytes32.fromhex(payout_instructions), address_prefix)
            print(f"Payout instructions (pool will pay to this address): {payout_address}")
        except Exception:
            print(f"Payout instructions (pool will pay you with this): {payout_instructions}")
    if pool_wallet_info.current.state == PoolSingletonState.LEAVING_POOL:
        expected_leave_height = pool_wallet_info.singleton_block_height + pool_wallet_info.current.relative_lock_height
        if pool_wallet_info.target is not None:
            print(f"Expected to leave after block height: {expected_leave_height}")


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
        pool_wallet_info, unconfirmed_transactions = await wallet_client.pw_status(wallet_id_passed_in)
        await pprint_pool_wallet_state(
            wallet_client,
            wallet_id_passed_in,
            pool_wallet_info,
            address_prefix,
            pool_state_dict,
            unconfirmed_transactions,
        )
    else:
        print(f"Wallet height: {await wallet_client.get_height_info()}")
        print(f"Sync status: {'Synced' if (await wallet_client.get_synced()) else 'Not synced'}")
        for summary in summaries_response:
            wallet_id = summary["id"]
            typ = WalletType(int(summary["type"]))
            if typ == WalletType.POOLING_WALLET:
                print(f"Wallet id {wallet_id}: ")
                pool_wallet_info, unconfirmed_transactions = await wallet_client.pw_status(wallet_id)
                await pprint_pool_wallet_state(
                    wallet_client,
                    wallet_id,
                    pool_wallet_info,
                    address_prefix,
                    pool_state_dict,
                    unconfirmed_transactions,
                )
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


async def submit_tx_with_confirmation(
    message: str, prompt: bool, func: Callable, wallet_client: WalletRpcClient, fingerprint: int, wallet_id: int
):
    print(message)
    if prompt:
        user_input: str = input("Confirm [n]/y: ")
    else:
        user_input = "yes"

    if user_input.lower() == "y" or user_input.lower() == "yes":
        try:
            tx_record: TransactionRecord = await func()
            start = time.time()
            while time.time() - start < 10:
                await asyncio.sleep(0.1)
                tx = await wallet_client.get_transaction(str(1), tx_record.name)
                if len(tx.sent_to) > 0:
                    print(f"Transaction submitted to nodes: {tx.sent_to}")
                    print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_record.name} to get status")
                    return None
        except Exception as e:
            print(f"Error performing operation on Plot NFT -f {fingerprint} wallet id: {wallet_id}: {e}")
        return
    print("Aborting.")


async def join_pool(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    enforce_https = config["full_node"]["selected_network"] == "mainnet"
    pool_url: str = args["pool_url"]
    if enforce_https and not pool_url.startswith("https://"):
        print(f"Pool URLs must be HTTPS on mainnet {pool_url}. Aborting.")
        return
    wallet_id = args.get("id", None)
    prompt = not args.get("yes", False)
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

    pprint(json_dict)
    msg = f"\nWill join pool: {pool_url} with Plot NFT {fingerprint}."
    func = functools.partial(
        wallet_client.pw_join_pool,
        wallet_id,
        hexstr_to_bytes(json_dict["target_puzzle_hash"]),
        pool_url,
        json_dict["relative_lock_height"],
    )

    await submit_tx_with_confirmation(msg, prompt, func, wallet_client, fingerprint, wallet_id)


async def self_pool(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args.get("id", None)
    prompt = not args.get("yes", False)

    msg = f"Will start self-farming with Plot NFT on wallet id {wallet_id} fingerprint {fingerprint}."
    func = functools.partial(wallet_client.pw_self_pool, wallet_id)
    await submit_tx_with_confirmation(msg, prompt, func, wallet_client, fingerprint, wallet_id)


async def inspect_cmd(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args.get("id", None)
    pool_wallet_info, unconfirmed_transactions = await wallet_client.pw_status(wallet_id)
    print(
        {
            "pool_wallet_info": pool_wallet_info,
            "unconfirmed_transactions": [
                {"sent_to": tx.sent_to, "transaction_id": tx.name.hex()} for tx in unconfirmed_transactions
            ],
        }
    )


async def claim_cmd(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args.get("id", None)
    msg = f"\nWill claim rewards for wallet ID: {wallet_id}."
    func = functools.partial(
        wallet_client.pw_absorb_rewards,
        wallet_id,
    )
    await submit_tx_with_confirmation(msg, False, func, wallet_client, fingerprint, wallet_id)
