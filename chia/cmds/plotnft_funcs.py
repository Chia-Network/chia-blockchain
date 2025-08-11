from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import Awaitable
from dataclasses import replace
from pathlib import Path
from pprint import pprint
from typing import Any, Callable, Optional

import aiohttp
import click
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.cmds.cmd_helpers import WalletClientInfo
from chia.cmds.cmds_util import (
    cli_confirm,
    get_any_service_client,
    transaction_status_msg,
    transaction_submitted_msg,
)
from chia.cmds.param_types import CliAddress
from chia.cmds.wallet_funcs import print_balance, wallet_coin_unit
from chia.farmer.farmer_rpc_client import FarmerRpcClient
from chia.pools.pool_config import (
    PoolWalletConfig,
    load_pool_config,
    update_pool_config,
)
from chia.pools.pool_wallet_info import PoolSingletonState, PoolWalletInfo
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.rpc.rpc_client import ResponseFailureError
from chia.server.server import ssl_context_for_root
from chia.ssl.create_ssl import get_mozilla_ca_crt
from chia.util.bech32m import encode_puzzle_hash
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.errors import CliRpcConnectionError
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_request_types import (
    GetTransaction,
    GetWalletBalance,
    GetWallets,
    PWAbsorbRewards,
    PWJoinPool,
    PWSelfPool,
    PWStatus,
    TransactionEndpointResponse,
    WalletInfoResponse,
)
from chia.wallet.wallet_rpc_client import WalletRpcClient


async def create_pool_args(pool_url: str) -> dict[str, Any]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{pool_url}/pool_info", ssl=ssl_context_for_root(get_mozilla_ca_crt())) as response:
                if response.ok:
                    json_dict: dict[str, Any] = json.loads(await response.text())
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


async def create(
    wallet_info: WalletClientInfo,
    pool_url: Optional[str],
    state: str,
    fee: uint64,
    *,
    prompt: bool,
) -> None:
    target_puzzle_hash: Optional[bytes32]
    # Could use initial_pool_state_from_dict to simplify
    if state == "SELF_POOLING":
        pool_url = None
        relative_lock_height = uint32(0)
        target_puzzle_hash = None  # wallet will fill this in
    elif state == "FARMING_TO_POOL":
        enforce_https = wallet_info.config["selected_network"] == "mainnet"
        assert pool_url is not None
        if enforce_https and not pool_url.startswith("https://"):
            raise CliRpcConnectionError(f"Pool URLs must be HTTPS on mainnet {pool_url}.")
        json_dict = await create_pool_args(pool_url)
        relative_lock_height = json_dict["relative_lock_height"]
        target_puzzle_hash = bytes32.from_hexstr(json_dict["target_puzzle_hash"])
    else:
        raise ValueError("Plot NFT must be created in SELF_POOLING or FARMING_TO_POOL state.")

    pool_msg = f" and join pool: {pool_url}" if pool_url else ""
    print(f"Will create a plot NFT{pool_msg}.")
    if prompt:
        cli_confirm("Confirm (y/n): ", "Aborting.")

    try:
        tx_record: TransactionRecord = await wallet_info.client.create_new_pool_wallet(
            target_puzzle_hash,
            pool_url,
            relative_lock_height,
            "localhost:5000",
            "new",
            state,
            fee,
        )
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = (await wallet_info.client.get_transaction(GetTransaction(tx_record.name))).transaction
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(wallet_info.fingerprint, tx_record.name))
                return None
    except Exception as e:
        raise CliRpcConnectionError(
            f"Error creating plot NFT: {e}\n    Please start both farmer and wallet with: chia start -r farmer"
        )


async def pprint_pool_wallet_state(
    wallet_client: WalletRpcClient,
    wallet_id: int,
    pool_wallet_info: PoolWalletInfo,
    address_prefix: str,
    pool_state_dict: Optional[dict[str, Any]],
) -> None:
    print(f"Wallet ID: {wallet_id}")
    if pool_wallet_info.current.state == PoolSingletonState.LEAVING_POOL.value and pool_wallet_info.target is None:
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
    print(f"Number of plots: {0 if pool_state_dict is None else pool_state_dict['plot_count']}")
    print(f"Owner public key: {pool_wallet_info.current.owner_pubkey}")

    print(
        f"Pool contract address (use ONLY for plotting - do not send money to this address): "
        f"{encode_puzzle_hash(pool_wallet_info.p2_singleton_puzzle_hash, address_prefix)}"
    )
    if pool_wallet_info.target is not None:
        print(f"Target state: {PoolSingletonState(pool_wallet_info.target.state).name}")
        print(f"Target pool URL: {pool_wallet_info.target.pool_url}")
    if pool_wallet_info.current.state == PoolSingletonState.SELF_POOLING.value:
        balances = (await wallet_client.get_wallet_balance(GetWalletBalance(uint32(wallet_id)))).wallet_balance
        balance = balances.confirmed_wallet_balance
        typ = WalletType(int(WalletType.POOLING_WALLET))
        address_prefix, scale = wallet_coin_unit(typ, address_prefix)
        print(f"Claimable balance: {print_balance(balance, scale, address_prefix)}")
    if pool_wallet_info.current.state == PoolSingletonState.FARMING_TO_POOL.value:
        print(f"Current pool URL: {pool_wallet_info.current.pool_url}")
        if pool_state_dict is not None:
            print(f"Current difficulty: {pool_state_dict['current_difficulty']}")
            print(f"Points balance: {pool_state_dict['current_points']}")
            points_found_24h = [points for timestamp, points in pool_state_dict["points_found_24h"]]
            points_acknowledged_24h = [points for timestamp, points in pool_state_dict["points_acknowledged_24h"]]
            summed_points_found_24h = sum(points_found_24h)
            summed_points_acknowledged_24h = sum(points_acknowledged_24h)
            if summed_points_found_24h == 0:
                success_pct = 0.0
            else:
                success_pct = summed_points_acknowledged_24h / summed_points_found_24h
            print(f"Points found (24h): {summed_points_found_24h}")
            print(f"Percent Successful Points (24h): {success_pct:.2%}")
            payout_instructions: str = pool_state_dict["pool_config"]["payout_instructions"]
            try:
                payout_address = encode_puzzle_hash(bytes32.fromhex(payout_instructions), address_prefix)
                print(f"Payout instructions (pool will pay to this address): {payout_address}")
            except Exception:
                print(f"Payout instructions (pool will pay you with this): {payout_instructions}")
        print(f"Relative lock height: {pool_wallet_info.current.relative_lock_height} blocks")
    if pool_wallet_info.current.state == PoolSingletonState.LEAVING_POOL.value:
        expected_leave_height = pool_wallet_info.singleton_block_height + pool_wallet_info.current.relative_lock_height
        if pool_wallet_info.target is not None:
            print(f"Expected to leave after block height: {expected_leave_height}")


async def pprint_all_pool_wallet_state(
    wallet_client: WalletRpcClient,
    get_wallets_response: list[WalletInfoResponse],
    address_prefix: str,
    pool_state_dict: dict[bytes32, dict[str, Any]],
) -> None:
    print(f"Wallet height: {(await wallet_client.get_height_info()).height}")
    print(f"Sync status: {'Synced' if (await wallet_client.get_sync_status()).synced else 'Not synced'}")
    for wallet_info in get_wallets_response:
        pool_wallet_id = wallet_info.id
        typ = WalletType(int(wallet_info.type))
        if typ == WalletType.POOLING_WALLET:
            pool_wallet_info = (await wallet_client.pw_status(PWStatus(uint32(pool_wallet_id)))).state
            await pprint_pool_wallet_state(
                wallet_client,
                pool_wallet_id,
                pool_wallet_info,
                address_prefix,
                pool_state_dict.get(pool_wallet_info.launcher_id),
            )
            print("")


async def show(
    wallet_info: WalletClientInfo,
    root_path: Path,
    wallet_id_passed_in: Optional[int],
) -> None:
    summaries_response = await wallet_info.client.get_wallets(GetWallets())
    config = wallet_info.config
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    pool_state_dict: dict[bytes32, dict[str, Any]] = dict()
    if wallet_id_passed_in is not None:
        await wallet_id_lookup_and_check(wallet_info.client, wallet_id_passed_in)
    try:
        async with get_any_service_client(
            client_type=FarmerRpcClient,
            root_path=root_path,
        ) as (farmer_client, _):
            pool_state_list = (await farmer_client.get_pool_state())["pool_state"]
            pool_state_dict = {
                bytes32.from_hexstr(pool_state_item["pool_config"]["launcher_id"]): pool_state_item
                for pool_state_item in pool_state_list
            }
            if wallet_id_passed_in is not None:
                pool_wallet_info = (await wallet_info.client.pw_status(PWStatus(uint32(wallet_id_passed_in)))).state
                await pprint_pool_wallet_state(
                    wallet_info.client,
                    wallet_id_passed_in,
                    pool_wallet_info,
                    address_prefix,
                    pool_state_dict.get(pool_wallet_info.launcher_id),
                )
            else:
                await pprint_all_pool_wallet_state(
                    wallet_info.client, summaries_response.wallets, address_prefix, pool_state_dict
                )
    except CliRpcConnectionError:  # we want to output this if we can't connect to the farmer
        await pprint_all_pool_wallet_state(
            wallet_info.client, summaries_response.wallets, address_prefix, pool_state_dict
        )


async def get_login_link(launcher_id: bytes32, root_path: Path) -> None:
    async with get_any_service_client(FarmerRpcClient, root_path=root_path) as (farmer_client, _):
        login_link: Optional[str] = await farmer_client.get_pool_login_link(launcher_id)
        if login_link is None:
            raise CliRpcConnectionError("Was not able to get login link.")
        else:
            print(login_link)


async def submit_tx_with_confirmation(
    message: str,
    prompt: bool,
    func: Callable[[], Awaitable[TransactionEndpointResponse]],
    wallet_client: WalletRpcClient,
    fingerprint: int,
    wallet_id: int,
) -> None:
    print(message)
    if prompt:
        cli_confirm("Confirm (y/n): ", "Aborting.")
    try:
        result = await func()
        start = time.time()
        for tx_record in result.transactions:
            if tx_record.spend_bundle is None:
                continue
            while time.time() - start < 10:
                await asyncio.sleep(0.1)
                tx = (await wallet_client.get_transaction(GetTransaction(tx_record.name))).transaction
                if len(tx.sent_to) > 0:
                    print(transaction_submitted_msg(tx))
                    print(transaction_status_msg(fingerprint, tx_record.name))
                    return
    except ResponseFailureError:
        raise
    except Exception as e:
        print(f"Error performing operation on Plot NFT -f {fingerprint} wallet id: {wallet_id}: {e}")


async def wallet_id_lookup_and_check(wallet_client: WalletRpcClient, wallet_id: Optional[int]) -> int:
    selected_wallet_id: int

    # absent network errors, this should not fail with an error
    pool_wallets = (await wallet_client.get_wallets(GetWallets(type=uint16(WalletType.POOLING_WALLET)))).wallets

    if wallet_id is None:
        if len(pool_wallets) == 0:
            raise CliRpcConnectionError(
                "No pool wallet found. Use 'chia plotnft create' to create a new pooling wallet."
            )
        if len(pool_wallets) > 1:
            raise CliRpcConnectionError("More than one pool wallet found. Use -i to specify pool wallet id.")
        selected_wallet_id = pool_wallets[0].id
    else:
        selected_wallet_id = wallet_id

    if not any(wallet.id == selected_wallet_id for wallet in pool_wallets):
        raise CliRpcConnectionError(f"Wallet with id: {selected_wallet_id} is not a pool wallet.")

    return selected_wallet_id


async def join_pool(
    *,
    wallet_info: WalletClientInfo,
    pool_url: str,
    fee: uint64,
    wallet_id: Optional[int],
    prompt: bool,
) -> None:
    selected_wallet_id = await wallet_id_lookup_and_check(wallet_info.client, wallet_id)

    sync_status = await wallet_info.client.get_sync_status()
    if not sync_status.synced:
        raise click.ClickException("Wallet must be synced before joining a pool.")

    pool_wallet_info = (await wallet_info.client.pw_status(PWStatus(uint32(selected_wallet_id)))).state
    if (
        pool_wallet_info.current.state == PoolSingletonState.FARMING_TO_POOL.value
        and pool_wallet_info.current.pool_url == pool_url
    ):
        raise click.ClickException(f"Wallet id: {wallet_id} is already farming to pool {pool_url}")

    enforce_https = wallet_info.config["selected_network"] == "mainnet"

    if enforce_https and not pool_url.startswith("https://"):
        raise CliRpcConnectionError(f"Pool URLs must be HTTPS on mainnet {pool_url}.")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{pool_url}/pool_info", ssl=ssl_context_for_root(get_mozilla_ca_crt())) as response:
                if response.ok:
                    json_dict = json.loads(await response.text())
                else:
                    raise CliRpcConnectionError(f"Response not OK: {response.status}")
    except Exception as e:
        raise CliRpcConnectionError(f"Error connecting to pool {pool_url}: {e}")

    if json_dict["relative_lock_height"] > 1000:
        raise CliRpcConnectionError("Relative lock height too high for this pool, cannot join")

    if json_dict["protocol_version"] != POOL_PROTOCOL_VERSION:
        raise CliRpcConnectionError(
            f"Incorrect version: {json_dict['protocol_version']}, should be {POOL_PROTOCOL_VERSION}"
        )

    pprint(json_dict)
    msg = f"\nWill join pool: {pool_url} with Plot NFT {wallet_info.fingerprint}."
    func = functools.partial(
        wallet_info.client.pw_join_pool,
        PWJoinPool(
            wallet_id=uint32(selected_wallet_id),
            target_puzzlehash=bytes32.from_hexstr(json_dict["target_puzzle_hash"]),
            pool_url=pool_url,
            relative_lock_height=json_dict["relative_lock_height"],
            fee=fee,
            push=True,
        ),
        DEFAULT_TX_CONFIG,
    )

    await submit_tx_with_confirmation(
        msg,
        prompt,
        func,
        wallet_info.client,
        wallet_info.fingerprint,
        selected_wallet_id,
    )


async def self_pool(*, wallet_info: WalletClientInfo, fee: uint64, wallet_id: Optional[int], prompt: bool) -> None:
    selected_wallet_id = await wallet_id_lookup_and_check(wallet_info.client, wallet_id)
    msg = (
        "Will start self-farming with Plot NFT on wallet id "
        f"{selected_wallet_id} fingerprint {wallet_info.fingerprint}."
    )
    func = functools.partial(
        wallet_info.client.pw_self_pool,
        PWSelfPool(wallet_id=uint32(selected_wallet_id), fee=fee, push=True),
        DEFAULT_TX_CONFIG,
    )
    await submit_tx_with_confirmation(
        msg, prompt, func, wallet_info.client, wallet_info.fingerprint, selected_wallet_id
    )


async def inspect_cmd(wallet_info: WalletClientInfo, wallet_id: Optional[int]) -> None:
    selected_wallet_id = await wallet_id_lookup_and_check(wallet_info.client, wallet_id)
    res = await wallet_info.client.pw_status(PWStatus(uint32(selected_wallet_id)))
    print(
        json.dumps(
            {
                "pool_wallet_info": res.state.to_json_dict(),
                "unconfirmed_transactions": [
                    {"sent_to": tx.sent_to, "transaction_id": tx.name.hex()} for tx in res.unconfirmed_transactions
                ],
            }
        )
    )


async def claim_cmd(*, wallet_info: WalletClientInfo, fee: uint64, wallet_id: Optional[int]) -> None:
    selected_wallet_id = await wallet_id_lookup_and_check(wallet_info.client, wallet_id)
    msg = f"\nWill claim rewards for wallet ID: {selected_wallet_id}."
    func = functools.partial(
        wallet_info.client.pw_absorb_rewards,
        PWAbsorbRewards(
            wallet_id=uint32(selected_wallet_id),
            fee=fee,
            push=True,
        ),
        DEFAULT_TX_CONFIG,
    )
    await submit_tx_with_confirmation(msg, False, func, wallet_info.client, wallet_info.fingerprint, selected_wallet_id)


async def change_payout_instructions(launcher_id: bytes32, address: CliAddress, root_path: Optional[Path]) -> None:
    new_pool_configs: list[PoolWalletConfig] = []
    id_found = False
    puzzle_hash = address.validate_address_type_get_ph(AddressType.XCH)
    if root_path is None:
        root_path = DEFAULT_ROOT_PATH

    old_configs: list[PoolWalletConfig] = load_pool_config(root_path)
    for pool_config in old_configs:
        if pool_config.launcher_id == launcher_id:
            id_found = True
            new_pool_config = replace(pool_config, payout_instructions=puzzle_hash.hex())
        else:
            new_pool_config = pool_config
        new_pool_configs.append(new_pool_config)
    if id_found:
        print(f"Launcher Id: {launcher_id.hex()} Found, Updating Config.")
        await update_pool_config(root_path, new_pool_configs)
        print(f"Payout Instructions for launcher id: {launcher_id.hex()} successfully updated to: {address}.")
        print(f"You will need to change the payout instructions on every device you use to: {address}.")
    else:
        print(f"Launcher Id: {launcher_id.hex()} Not found.")
