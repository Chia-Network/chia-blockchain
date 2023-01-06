from __future__ import annotations

import asyncio
import logging
import ssl
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import ClientConnectorError, ClientSession
from blspy import AugSchemeMPL, PrivateKey

from chia.cmds.init_funcs import check_keys
from chia.daemon.client import DaemonProxy
from chia.daemon.keychain_server import (
    KEYCHAIN_ERR_KEY_NOT_FOUND,
    KEYCHAIN_ERR_KEYERROR,
    KEYCHAIN_ERR_LOCKED,
    KEYCHAIN_ERR_MALFORMED_REQUEST,
    KEYCHAIN_ERR_NO_KEYS,
)
from chia.server.server import ssl_context_for_client
from chia.util.config import load_config
from chia.util.errors import (
    KeychainIsEmpty,
    KeychainIsLocked,
    KeychainKeyNotFound,
    KeychainMalformedRequest,
    KeychainMalformedResponse,
    KeychainProxyConnectionTimeout,
)
from chia.util.keychain import Keychain, KeyData, bytes_to_mnemonic, mnemonic_to_seed
from chia.util.ws_message import WsRpcMessage


class KeychainProxy(DaemonProxy):
    """
    KeychainProxy can act on behalf of a local or remote keychain. In the case of
    wrapping a local keychain, the proxy object simply forwards-along the calls to
    the underlying local keychain. In the remote case, calls are made to the daemon
    over the RPC interface, allowing the daemon to act as the keychain authority.
    """

    def __init__(
        self,
        log: logging.Logger,
        uri: str = "",
        ssl_context: Optional[ssl.SSLContext] = None,
        local_keychain: Optional[Keychain] = None,
        user: Optional[str] = None,
        service: Optional[str] = None,
        heartbeat: int = 300,
    ):
        super().__init__(uri, ssl_context, heartbeat=heartbeat)
        self.log = log
        if local_keychain:
            self.keychain = local_keychain
        else:
            self.keychain = None  # type: ignore
        self.keychain_user = user
        self.keychain_service = service
        # these are used to track and close the keychain connection
        self.keychain_connection_task: Optional[asyncio.Task[None]] = None
        self.shut_down: bool = False
        self.connection_established: asyncio.Event = asyncio.Event()

    def use_local_keychain(self) -> bool:
        """
        Indicates whether the proxy forwards calls to a local keychain
        """
        return self.keychain is not None

    def format_request(self, command: str, data: Dict[str, Any]) -> WsRpcMessage:
        """
        Overrides DaemonProxy.format_request() to add keychain-specific RPC params
        """
        if data is None:
            data = {}

        if self.keychain_user or self.keychain_service:
            data["kc_user"] = self.keychain_user
            data["kc_service"] = self.keychain_service

        return super().format_request(command, data)

    async def _get(self, request: WsRpcMessage) -> WsRpcMessage:
        """
        Overrides DaemonProxy._get() to handle the connection state
        """
        try:
            if not self.shut_down:  # if we are shut down, and we send a request we should throw original error.
                await asyncio.wait_for(self.connection_established.wait(), timeout=30)  # in case of heavy swap usage.
            else:
                self.log.error("Attempting to send request to a keychain-proxy that has shut down.")
            self.log.debug(f"Sending request to keychain command: {request['command']} from {request['origin']}.")
            return await super()._get(request)
        except asyncio.TimeoutError:
            raise KeychainProxyConnectionTimeout()

    async def start(self) -> None:
        self.keychain_connection_task = asyncio.create_task(self.connect_to_keychain())
        await self.connection_established.wait()  # wait until connection is established.

    async def connect_to_keychain(self) -> None:
        while not self.shut_down:
            try:
                self.client_session = ClientSession()
                self.websocket = await self.client_session.ws_connect(
                    self._uri,
                    autoclose=True,
                    autoping=True,
                    heartbeat=self.heartbeat,
                    ssl_context=self.ssl_context,
                    max_msg_size=self.max_message_size,
                )
                await self.listener()
            except ClientConnectorError:
                self.log.warning(f"Can not connect to keychain at {self._uri}.")
            except Exception as e:
                tb = traceback.format_exc()
                self.log.warning(f"Exception: {tb} {type(e)}")
            self.log.info(f"Reconnecting to keychain at {self._uri}.")
            self.connection_established.clear()
            if self.websocket is not None:
                await self.websocket.close()
            if self.client_session is not None:
                await self.client_session.close()
            self.websocket = None
            self.client_session = None
            await asyncio.sleep(2)

    async def listener(self) -> None:
        self.connection_established.set()  # mark connection as active.
        await super().listener()
        self.log.info("Close signal received from keychain, we probably timed out.")

    async def close(self) -> None:
        self.shut_down = True
        await super().close()
        if self.keychain_connection_task is not None:
            await self.keychain_connection_task

    async def get_response_for_request(self, request_name: str, data: Dict[str, Any]) -> Tuple[WsRpcMessage, bool]:
        request = self.format_request(request_name, data)
        response = await self._get(request)
        success = response["data"].get("success", False)
        return response, success

    def handle_error(self, response: WsRpcMessage) -> None:
        """
        Common error handling for RPC responses
        """
        error = response["data"].get("error", None)
        if error:
            error_details = response["data"].get("error_details", {})
            if error == KEYCHAIN_ERR_LOCKED:
                raise KeychainIsLocked()
            elif error == KEYCHAIN_ERR_NO_KEYS:
                raise KeychainIsEmpty()
            elif error == KEYCHAIN_ERR_KEY_NOT_FOUND:
                raise KeychainKeyNotFound()
            elif error == KEYCHAIN_ERR_MALFORMED_REQUEST:
                message = error_details.get("message", "")
                raise KeychainMalformedRequest(message)
            else:
                # Try to construct a more informative error message including the call that failed
                if "command" in response["data"]:
                    err = f"{response['data'].get('command')} failed with error: {error}"
                    raise Exception(f"{err}")
                raise Exception(f"{error}")

    async def add_private_key(self, mnemonic: str, label: Optional[str] = None) -> PrivateKey:
        """
        Forwards to Keychain.add_private_key()
        """
        key: PrivateKey
        if self.use_local_keychain():
            key = self.keychain.add_private_key(mnemonic, label)
        else:
            response, success = await self.get_response_for_request(
                "add_private_key", {"mnemonic": mnemonic, "label": label}
            )
            if success:
                seed = mnemonic_to_seed(mnemonic)
                key = AugSchemeMPL.key_gen(seed)
            else:
                error = response["data"].get("error", None)
                if error == KEYCHAIN_ERR_KEYERROR:
                    error_details = response["data"].get("error_details", {})
                    word = error_details.get("word", "")
                    raise KeyError(word)
                else:
                    self.handle_error(response)

        return key

    async def check_keys(self, root_path: Path) -> None:
        """
        Forwards to init_funcs.check_keys()
        """
        if self.use_local_keychain():
            check_keys(root_path, self.keychain)
        else:
            response, success = await self.get_response_for_request("check_keys", {"root_path": str(root_path)})
            if not success:
                self.handle_error(response)

    async def delete_all_keys(self) -> None:
        """
        Forwards to Keychain.delete_all_keys()
        """
        if self.use_local_keychain():
            self.keychain.delete_all_keys()
        else:
            response, success = await self.get_response_for_request("delete_all_keys", {})
            if not success:
                self.handle_error(response)

    async def delete_key_by_fingerprint(self, fingerprint: int) -> None:
        """
        Forwards to Keychain.delete_key_by_fingerprint()
        """
        if self.use_local_keychain():
            self.keychain.delete_key_by_fingerprint(fingerprint)
        else:
            response, success = await self.get_response_for_request(
                "delete_key_by_fingerprint", {"fingerprint": fingerprint}
            )
            if not success:
                self.handle_error(response)

    async def get_all_private_keys(self) -> List[Tuple[PrivateKey, bytes]]:
        """
        Forwards to Keychain.get_all_private_keys()
        """
        keys: List[Tuple[PrivateKey, bytes]] = []
        if self.use_local_keychain():
            keys = self.keychain.get_all_private_keys()
        else:
            response, success = await self.get_response_for_request("get_all_private_keys", {})
            if success:
                private_keys = response["data"].get("private_keys", None)
                if private_keys is None:
                    err = f"Missing private_keys in {response.get('command')} response"
                    self.log.error(f"{err}")
                    raise KeychainMalformedResponse(f"{err}")
                else:
                    for key_dict in private_keys:
                        pk = key_dict.get("pk", None)
                        ent_str = key_dict.get("entropy", None)
                        if pk is None or ent_str is None:
                            err = f"Missing pk and/or ent in {response.get('command')} response"
                            self.log.error(f"{err}")
                            continue  # We'll skip the incomplete key entry
                        ent = bytes.fromhex(ent_str)
                        mnemonic = bytes_to_mnemonic(ent)
                        seed = mnemonic_to_seed(mnemonic)
                        key = AugSchemeMPL.key_gen(seed)
                        if bytes(key.get_g1()).hex() == pk:
                            keys.append((key, ent))
                        else:
                            err = "G1Elements don't match"
                            self.log.error(f"{err}")
            else:
                self.handle_error(response)

        return keys

    async def get_first_private_key(self) -> Optional[PrivateKey]:
        """
        Forwards to Keychain.get_first_private_key()
        """
        key: Optional[PrivateKey] = None
        if self.use_local_keychain():
            sk_ent = self.keychain.get_first_private_key()
            if sk_ent:
                key = sk_ent[0]
        else:
            response, success = await self.get_response_for_request("get_first_private_key", {})
            if success:
                private_key = response["data"].get("private_key", None)
                if private_key is None:
                    err = f"Missing private_key in {response.get('command')} response"
                    self.log.error(f"{err}")
                    raise KeychainMalformedResponse(f"{err}")
                else:
                    pk = private_key.get("pk", None)
                    ent_str = private_key.get("entropy", None)
                    if pk is None or ent_str is None:
                        err = f"Missing pk and/or ent in {response.get('command')} response"
                        self.log.error(f"{err}")
                        raise KeychainMalformedResponse(f"{err}")
                    ent = bytes.fromhex(ent_str)
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic)
                    sk = AugSchemeMPL.key_gen(seed)
                    if bytes(sk.get_g1()).hex() == pk:
                        key = sk
                    else:
                        err = "G1Elements don't match"
                        self.log.error(f"{err}")
            else:
                self.handle_error(response)

        return key

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        """
        Locates and returns a private key matching the provided fingerprint
        """
        key: Optional[PrivateKey] = None
        if self.use_local_keychain():
            private_keys = self.keychain.get_all_private_keys()
            if len(private_keys) == 0:
                raise KeychainIsEmpty()
            else:
                if fingerprint is not None:
                    for sk, _ in private_keys:
                        if sk.get_g1().get_fingerprint() == fingerprint:
                            key = sk
                            break
                    if key is None:
                        raise KeychainKeyNotFound(fingerprint)
                else:
                    key = private_keys[0][0]
        else:
            response, success = await self.get_response_for_request(
                "get_key_for_fingerprint", {"fingerprint": fingerprint}
            )
            if success:
                pk = response["data"].get("pk", None)
                ent = response["data"].get("entropy", None)
                if pk is None or ent is None:
                    err = f"Missing pk and/or ent in {response.get('command')} response"
                    self.log.error(f"{err}")
                    raise KeychainMalformedResponse(f"{err}")
                else:
                    mnemonic = bytes_to_mnemonic(bytes.fromhex(ent))
                    seed = mnemonic_to_seed(mnemonic)
                    private_key = AugSchemeMPL.key_gen(seed)
                    if bytes(private_key.get_g1()).hex() == pk:
                        key = private_key
                    else:
                        err = "G1Elements don't match"
                        self.log.error(f"{err}")
            else:
                self.handle_error(response)

        return key

    async def get_key(self, fingerprint: int, include_secrets: bool = False) -> Optional[KeyData]:
        """
        Locates and returns KeyData matching the provided fingerprint
        """
        key_data: Optional[KeyData] = None
        if self.use_local_keychain():
            key_data = self.keychain.get_key(fingerprint, include_secrets)
        else:
            response, success = await self.get_response_for_request(
                "get_key", {"fingerprint": fingerprint, "include_secrets": include_secrets}
            )
            if success:
                key_data = KeyData.from_json_dict(response["data"]["key"])
            else:
                self.handle_error(response)
        return key_data

    async def get_keys(self, include_secrets: bool = False) -> List[KeyData]:
        """
        Returns all KeyData
        """
        keys: List[KeyData] = []
        if self.use_local_keychain():
            keys = self.keychain.get_keys(include_secrets)
        else:
            response, success = await self.get_response_for_request("get_keys", {"include_secrets": include_secrets})
            if success:
                keys = [KeyData.from_json_dict(key) for key in response["data"]["keys"]]
            else:
                self.handle_error(response)
        return keys


def wrap_local_keychain(keychain: Keychain, log: logging.Logger) -> KeychainProxy:
    """
    Wrap an existing local Keychain instance in a KeychainProxy to utilize
    the same interface as a remote Keychain
    """
    return KeychainProxy(local_keychain=keychain, log=log)


async def connect_to_keychain(
    self_hostname: str,
    daemon_port: int,
    daemon_heartbeat: int,
    ssl_context: Optional[ssl.SSLContext],
    log: logging.Logger,
    user: Optional[str] = None,
    service: Optional[str] = None,
) -> KeychainProxy:
    """
    Connect to the local daemon.
    """

    client = KeychainProxy(
        uri=f"wss://{self_hostname}:{daemon_port}",
        heartbeat=daemon_heartbeat,
        ssl_context=ssl_context,
        log=log,
        user=user,
        service=service,
    )
    # Connect to the service if the proxy isn't using a local keychain
    if not client.use_local_keychain():
        await client.start()
    return client


async def connect_to_keychain_and_validate(
    root_path: Path,
    log: logging.Logger,
    user: Optional[str] = None,
    service: Optional[str] = None,
) -> Optional[KeychainProxy]:
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
    try:
        net_config = load_config(root_path, "config.yaml")
        crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        key_path = root_path / net_config["daemon_ssl"]["private_key"]
        ca_crt_path = root_path / net_config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / net_config["private_ssl_ca"]["key"]
        ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path, log=log)
        daemon_heartbeat = net_config.get("daemon_heartbeat", 300)
        connection = await connect_to_keychain(
            net_config["self_hostname"], net_config["daemon_port"], daemon_heartbeat, ssl_context, log, user, service
        )

        # If proxying to a local keychain, don't attempt to ping
        if connection.use_local_keychain():
            return connection

        r = await connection.ping()  # this is purposely using the base classes _get method

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception as e:
        print(f"Keychain(daemon) not started yet: {e}")
    return None
