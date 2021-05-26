import json
from pprint import pprint
from typing import Dict

from chia.pools.pool_wallet_info import PoolWalletInfo, PoolSingletonState
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.util.wallet_types import WalletType
import aiohttp


async def create(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    pool_url = args["pool_url"]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{pool_url}/pool_info") as response:
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

    print(f"Will create a pool NFT and join pool: {pool_url}.")
    pprint(json_dict)
    user_input: str = input("Confirm [n]/y: ")
    if user_input.lower() == "y" or user_input.lower() == "yes":
        try:
            response: Dict = await wallet_client.create_new_pool_wallet(
                hexstr_to_bytes(json_dict["target_puzzle_hash"]),
                pool_url,
                json_dict["relative_lock_height"],
                "localhost:5000",
            )
            pprint(response)
        except Exception as e:
            print(f"Error creating pool NFT: {e}")
        return
    print("Aborting.")


def pprint_pool_wallet_state(pool_wallet_info: PoolWalletInfo):
    print(f"Current state: {PoolSingletonState(pool_wallet_info.current.state).name}")
    pprint(pool_wallet_info.current)
    if pool_wallet_info.target.state is not None:
        print(f"Target state: {PoolSingletonState(pool_wallet_info.target.state).name}")
        pprint(pool_wallet_info.target)


async def show(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    summaries_response = await wallet_client.get_wallets()
    wallet_id_passed_in = args.get("id", None)
    if wallet_id_passed_in is not None:
        for summary in summaries_response:
            typ = WalletType(int(summary["type"]))
            if summary["id"] == wallet_id_passed_in and typ != WalletType.POOLING_WALLET:
                print(f"Wallet with id: {wallet_id_passed_in} is not a pooling wallet. Please provide a different id.")
                return
        response: PoolWalletInfo = await wallet_client.pw_status(wallet_id_passed_in)
        pprint_pool_wallet_state(response)
    else:
        print(f"Wallet height: {await wallet_client.get_height_info()}")
        print(f"Sync status: {'Synced' if (await wallet_client.get_synced()) else 'Not synced'}")
        for summary in summaries_response:
            wallet_id = summary["id"]
            typ = WalletType(int(summary["type"]))
            if typ == WalletType.POOLING_WALLET:
                print(f"Wallet id {wallet_id}: ")
                response: PoolWalletInfo = await wallet_client.pw_status(wallet_id)
                pprint_pool_wallet_state(response)
                print("")
