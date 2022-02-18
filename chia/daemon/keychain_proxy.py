import logging
import ssl

from blspy import AugSchemeMPL, PrivateKey
from chia.cmds.init_funcs import check_keys
from chia.daemon.client import DaemonProxy
from chia.daemon.keychain_server import (
    KEYCHAIN_ERR_KEYERROR,
    KEYCHAIN_ERR_LOCKED,
    KEYCHAIN_ERR_MALFORMED_REQUEST,
    KEYCHAIN_ERR_NO_KEYS,
)
from chia.server.server import ssl_context_for_client
from chia.util.config import load_config
from chia.util.keychain import (
    Keychain,
    KeyringIsLocked,
    bytes_to_mnemonic,
    mnemonic_to_seed,
    supports_keyring_passphrase,
)
from chia.util.ws_message import WsRpcMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class KeyringIsEmpty(Exception):
    pass


class MalformedKeychainRequest(Exception):
    pass


class MalformedKeychainResponse(Exception):
    pass


class KeychainProxyConnectionFailure(Exception):
    pass


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
        uri: str = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        local_keychain: Optional[Keychain] = None,
        user: str = None,
        service: str = None,
    ):
        self.log = log
        if local_keychain:
            self.keychain = local_keychain
        elif not supports_keyring_passphrase():
            self.keychain = Keychain()  # Proxy locally, don't use RPC
        else:
            self.keychain = None  # type: ignore
        self.keychain_user = user
        self.keychain_service = service
        super().__init__(uri or "", ssl_context)

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

    async def get_response_for_request(self, request_name: str, data: Dict[str, Any]) -> Tuple[WsRpcMessage, bool]:
        request = self.format_request(request_name, data)
        response = await self._get(request)
        success = response["data"].get("success", False)
        return response, success

    def handle_error(self, response: WsRpcMessage):
        """
        Common error handling for RPC responses
        """
        error = response["data"].get("error", None)
        if error:
            error_details = response["data"].get("error_details", {})
            if error == KEYCHAIN_ERR_LOCKED:
                raise KeyringIsLocked()
            elif error == KEYCHAIN_ERR_NO_KEYS:
                raise KeyringIsEmpty()
            elif error == KEYCHAIN_ERR_MALFORMED_REQUEST:
                message = error_details.get("message", "")
                raise MalformedKeychainRequest(message)
            else:
                err = f"{response['data'].get('command')} failed with error: {error}"
                self.log.error(f"{err}")
                raise Exception(f"{err}")

    async def add_private_key(self, mnemonic: str, passphrase: str) -> PrivateKey:
        """
        Forwards to Keychain.add_private_key()
        """
        key: PrivateKey
        if self.use_local_keychain():
            key = self.keychain.add_private_key(mnemonic, passphrase)
        else:
            response, success = await self.get_response_for_request(
                "add_private_key", {"mnemonic": mnemonic, "passphrase": passphrase}
            )
            if success:
                seed = mnemonic_to_seed(mnemonic, passphrase)
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

    async def check_keys(self, root_path):
        """
        Forwards to init_funcs.check_keys()
        """
        if self.use_local_keychain():
            check_keys(root_path, self.keychain)
        else:
            response, success = await self.get_response_for_request("check_keys", {"root_path": str(root_path)})
            if not success:
                self.handle_error(response)

    async def delete_all_keys(self):
        """
        Forwards to Keychain.delete_all_keys()
        """
        if self.use_local_keychain():
            self.keychain.delete_all_keys()
        else:
            response, success = await self.get_response_for_request("delete_all_keys", {})
            if not success:
                self.handle_error(response)

    async def delete_key_by_fingerprint(self, fingerprint: int):
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
                    raise MalformedKeychainResponse(f"{err}")
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
                        seed = mnemonic_to_seed(mnemonic, passphrase="")
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
                    raise MalformedKeychainResponse(f"{err}")
                else:
                    pk = private_key.get("pk", None)
                    ent_str = private_key.get("entropy", None)
                    if pk is None or ent_str is None:
                        err = f"Missing pk and/or ent in {response.get('command')} response"
                        self.log.error(f"{err}")
                        raise MalformedKeychainResponse(f"{err}")
                    ent = bytes.fromhex(ent_str)
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, passphrase="")
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
                raise KeyringIsEmpty()
            else:
                if fingerprint is not None:
                    for sk, _ in private_keys:
                        if sk.get_g1().get_fingerprint() == fingerprint:
                            key = sk
                            break
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
                    raise MalformedKeychainResponse(f"{err}")
                else:
                    mnemonic = bytes_to_mnemonic(bytes.fromhex(ent))
                    seed = mnemonic_to_seed(mnemonic, passphrase="")
                    private_key = AugSchemeMPL.key_gen(seed)
                    if bytes(private_key.get_g1()).hex() == pk:
                        key = private_key
                    else:
                        err = "G1Elements don't match"
                        self.log.error(f"{err}")
            else:
                self.handle_error(response)

        return key


def wrap_local_keychain(keychain: Keychain, log: logging.Logger) -> KeychainProxy:
    """
    Wrap an existing local Keychain instance in a KeychainProxy to utilize
    the same interface as a remote Keychain
    """
    return KeychainProxy(local_keychain=keychain, log=log)


async def connect_to_keychain(
    self_hostname: str,
    daemon_port: int,
    ssl_context: Optional[ssl.SSLContext],
    log: logging.Logger,
    user: str = None,
    service: str = None,
) -> KeychainProxy:
    """
    Connect to the local daemon.
    """

    client = KeychainProxy(
        uri=f"wss://{self_hostname}:{daemon_port}", ssl_context=ssl_context, log=log, user=user, service=service
    )
    # Connect to the service if the proxy isn't using a local keychain
    if not client.use_local_keychain():
        await client.start()
    return client


async def connect_to_keychain_and_validate(
    root_path: Path,
    log: logging.Logger,
    *,
    user: str = None,
    service: str = None,
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
        connection = await connect_to_keychain(
            net_config["self_hostname"], net_config["daemon_port"], ssl_context, log, user, service
        )

        # If proxying to a local keychain, don't attempt to ping
        if connection.use_local_keychain():
            return connection

        r = await connection.ping()

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception as e:
        print(f"Keychain(daemon) not started yet: {e}")
        return None
    return None
