from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Type, TypeVar

from aiohttp import ClientConnectorCertificateError, ClientConnectorError

from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.rpc_client import RpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_submission_status import MempoolSubmissionStatus
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.errors import CliRpcConnectionError
from chia.util.ints import uint16
from chia.util.keychain import KeyData
from chia.wallet.transaction_record import TransactionRecord

NODE_TYPES: Dict[str, Type[RpcClient]] = {
    "farmer": FarmerRpcClient,
    "wallet": WalletRpcClient,
    "full_node": FullNodeRpcClient,
    "harvester": HarvesterRpcClient,
    "data_layer": DataLayerRpcClient,
    "simulator": SimulatorFullNodeRpcClient,
}

node_config_section_names: Dict[Type[RpcClient], str] = {
    FarmerRpcClient: "farmer",
    WalletRpcClient: "wallet",
    FullNodeRpcClient: "full_node",
    HarvesterRpcClient: "harvester",
    DataLayerRpcClient: "data_layer",
    SimulatorFullNodeRpcClient: "full_node",
}

_T_RpcClient = TypeVar("_T_RpcClient", bound=RpcClient)


def transaction_submitted_msg(tx: TransactionRecord) -> str:
    sent_to = [MempoolSubmissionStatus(s[0], s[1], s[2]).to_json_dict_convenience() for s in tx.sent_to]
    return f"Transaction submitted to nodes: {sent_to}"


def transaction_status_msg(fingerprint: int, tx_id: bytes32) -> str:
    return f"Run 'chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}' to get status"


async def validate_client_connection(
    rpc_client: RpcClient,
    node_type: str,
    rpc_port: int,
    consume_errors: bool = True,
) -> None:
    try:
        await rpc_client.healthz()
    except ClientConnectorError as e:
        if not consume_errors:
            raise

        lines = [f"Connection error: {type(e).__name__}: {e}"]
        node_type_name = node_type.replace("_", " ")

        if isinstance(e, ClientConnectorCertificateError):
            lines.append(f"Check if {node_type_name} client and rpc (port: {rpc_port}) certificates match")
        else:
            lines.append(f"Check if {node_type_name} rpc is running at {rpc_port}")
            lines.append(f"This is normal if {node_type_name} is still starting up")

        # this error is handled by click.
        raise CliRpcConnectionError("\n".join(lines))


@asynccontextmanager
async def get_any_service_client(
    client_type: Type[_T_RpcClient],
    rpc_port: Optional[int] = None,
    root_path: Path = DEFAULT_ROOT_PATH,
    consume_errors: bool = True,
) -> AsyncIterator[Tuple[_T_RpcClient, Dict[str, Any]]]:
    """
    Yields a tuple with a RpcClient for the applicable node type a dictionary of the node's configuration,
    and a fingerprint if applicable. However, if connecting to the node fails then we will return None for
    the RpcClient.
    """

    node_type = node_config_section_names.get(client_type)
    if node_type is None:
        # Click already checks this, so this should never happen
        raise ValueError(f"Invalid client type requested: {client_type.__name__}")
    # load variables from config file
    config = load_config(root_path, "config.yaml", fill_missing_services=issubclass(client_type, DataLayerRpcClient))
    self_hostname = config["self_hostname"]
    if rpc_port is None:
        rpc_port = config[node_type]["rpc_port"]
    # select node client type based on string
    node_client = await client_type.create(self_hostname, uint16(rpc_port), root_path, config)
    try:
        # check if we can connect to node
        await validate_client_connection(node_client, node_type, rpc_port, consume_errors)
        yield node_client, config
    except Exception as e:  # this is only here to make the errors more user-friendly.
        if not consume_errors or isinstance(e, CliRpcConnectionError):
            # CliRpcConnectionError will be handled by click.
            raise
        print(f"Exception from '{node_type}' {e}:\n{traceback.format_exc()}")

    finally:
        node_client.close()  # this can run even if already closed, will just do nothing.
        await node_client.await_closed()


async def get_wallet(root_path: Path, wallet_client: WalletRpcClient, fingerprint: Optional[int]) -> int:
    selected_fingerprint: int
    keychain_proxy: Optional[KeychainProxy] = None
    all_keys: List[KeyData] = []

    try:
        if fingerprint is not None:
            selected_fingerprint = fingerprint
        else:
            keychain_proxy = await connect_to_keychain_and_validate(root_path, log=logging.getLogger(__name__))
            if keychain_proxy is None:
                raise RuntimeError("Failed to connect to keychain")
            # we're only interested in the fingerprints and labels
            all_keys = await keychain_proxy.get_keys(include_secrets=False)
            # we don't immediately close the keychain proxy connection because it takes a noticeable amount of time
            fingerprints = [key.fingerprint for key in all_keys]
            if len(fingerprints) == 0:
                raise CliRpcConnectionError("No keys loaded. Run 'chia keys generate' or import a key")
            elif len(fingerprints) == 1:
                # if only a single key is available, select it automatically
                selected_fingerprint = fingerprints[0]
            else:
                logged_in_fingerprint: Optional[int] = await wallet_client.get_logged_in_fingerprint()
                logged_in_key: Optional[KeyData] = None
                if logged_in_fingerprint is not None:
                    logged_in_key = next((key for key in all_keys if key.fingerprint == logged_in_fingerprint), None)
                current_sync_status: str = ""
                indent = "   "
                if logged_in_key is not None:
                    if await wallet_client.get_synced():
                        current_sync_status = "Synced"
                    elif await wallet_client.get_sync_status():
                        current_sync_status = "Syncing"
                    else:
                        current_sync_status = "Not Synced"

                    print()
                    print("Active Wallet Key (*):")
                    print(f"{indent}{'-Fingerprint:'.ljust(23)} {logged_in_key.fingerprint}")
                    if logged_in_key.label is not None:
                        print(f"{indent}{'-Label:'.ljust(23)} {logged_in_key.label}")
                    print(f"{indent}{'-Sync Status:'.ljust(23)} {current_sync_status}")
                max_key_index_width = 5  # e.g. "12) *", "1)  *", or "2)   "
                max_fingerprint_width = 10  # fingerprint is a 32-bit number
                print()
                print("Wallet Keys:")
                for i, key in enumerate(all_keys):
                    key_index_str = f"{(str(i + 1) + ')'):<4}"
                    key_index_str += "*" if key.fingerprint == logged_in_fingerprint else " "
                    print(
                        f"{key_index_str:<{max_key_index_width}} "
                        f"{key.fingerprint:<{max_fingerprint_width}}"
                        f"{(indent + key.label) if key.label else ''}"
                    )
                val = None
                prompt: str = (
                    f"Choose a wallet key [1-{len(fingerprints)}]"
                    f" ('q' to quit, or Enter to use {logged_in_fingerprint}): "
                )
                while val is None:
                    val = input(prompt)
                    if val == "q":
                        raise CliRpcConnectionError("No Fingerprint Selected")
                    elif val == "" and logged_in_fingerprint is not None:
                        fp = logged_in_fingerprint
                        break
                    elif not val.isdigit():
                        val = None
                    else:
                        index = int(val) - 1
                        if index < 0 or index >= len(fingerprints):
                            print("Invalid value")
                            val = None
                            continue
                        else:
                            fp = fingerprints[index]

                selected_fingerprint = fp

        if selected_fingerprint is not None:
            log_in_response = await wallet_client.log_in(selected_fingerprint)

            if log_in_response["success"] is False:
                raise CliRpcConnectionError(f"Login failed for fingerprint {selected_fingerprint}: {log_in_response}")
    finally:
        # Closing the keychain proxy takes a moment, so we wait until after the login is complete
        if keychain_proxy is not None:
            await keychain_proxy.close()

    return selected_fingerprint


@asynccontextmanager
async def get_wallet_client(
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    root_path: Path = DEFAULT_ROOT_PATH,
    consume_errors: bool = True,
) -> AsyncIterator[Tuple[WalletRpcClient, int, Dict[str, Any]]]:
    async with get_any_service_client(WalletRpcClient, wallet_rpc_port, root_path, consume_errors) as (
        wallet_client,
        config,
    ):
        new_fp = await get_wallet(root_path, wallet_client, fingerprint)
        yield wallet_client, new_fp, config
