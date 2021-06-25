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
from chia.util.keychain import Keychain, KeyringIsLocked, bytes_to_mnemonic, mnemonic_to_seed, supports_keyring_password
from chia.util.ws_message import WsRpcMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class KeyringIsEmpty(Exception):
    pass


class MalformedKeychainRequest(Exception):
    pass


class MalformedKeychainResponse(Exception):
    pass


class KeychainProxy(DaemonProxy):
    keychain: Keychain  # If the keyring doesn't support a master password, we'll proxy calls locally
    log: logging.Logger

    def __init__(
        self, uri: str, ssl_context: Optional[ssl.SSLContext], log: logging.Logger, local_keychain: Optional[Keychain]
    ):
        self.log = log
        if local_keychain:
            self.keychain = local_keychain
        elif not supports_keyring_password():
            self.keychain = Keychain()  # Proxy locally, don't use RPC
        else:
            self.keychain = None  # type: ignore
        super().__init__(uri, ssl_context)

    def use_local_keychain(self) -> bool:
        return self.keychain is not None

    def handle_error(self, response: WsRpcMessage):
        error = response["data"].get("error", None)
        error_details = response["data"].get("error_details", {})
        if error:
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
        key: PrivateKey
        if self.use_local_keychain():
            key = self.keychain.add_private_key(mnemonic, passphrase)
        else:
            data = {"mnemonic": mnemonic, "passphrase": passphrase}
            request = self.format_request("add_private_key", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
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
        if self.use_local_keychain():
            check_keys(root_path)
        else:
            data = {"root_path": str(root_path)}
            request = self.format_request("check_keys", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
            if not success:
                self.handle_error(response)

    async def delete_all_keys(self):
        if self.use_local_keychain():
            self.keychain.delete_all_keys()
        else:
            data = {}
            request = self.format_request("delete_all_keys", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
            if not success:
                self.handle_error(response)

    async def delete_key_by_fingerprint(self, fingerprint: int):
        if self.use_local_keychain():
            self.keychain.delete_key_by_fingerprint(fingerprint)
        else:
            data = {"fingerprint": fingerprint}
            request = self.format_request("delete_key_by_fingerprint", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
            if not success:
                self.handle_error(response)

    async def get_all_private_keys(self) -> List[Tuple[PrivateKey, bytes]]:
        keys: List[Tuple[PrivateKey, bytes]] = []
        if self.use_local_keychain():
            keys = self.keychain.get_all_private_keys()
        else:
            data: Dict[str, Any] = {}
            request = self.format_request("get_all_private_keys", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
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

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
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
            data = {"fingerprint": fingerprint}
            request = self.format_request("get_key_for_fingerprint", data)
            response = await self._get(request)
            success = response["data"].get("success", False)
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


async def connect_to_keychain(
    self_hostname: str,
    daemon_port: int,
    ssl_context: Optional[ssl.SSLContext],
    log: logging.Logger,
    local_keychain: Optional[Keychain],
) -> KeychainProxy:
    """
    Connect to the local daemon.
    """

    client = KeychainProxy(f"wss://{self_hostname}:{daemon_port}", ssl_context, log, local_keychain)
    await client.start()
    return client


async def connect_to_keychain_and_validate(
    root_path: Path, log: logging.Logger, local_keychain: Optional[Keychain]
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
        ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path)
        connection = await connect_to_keychain(
            net_config["self_hostname"], net_config["daemon_port"], ssl_context, log, local_keychain
        )
        r = await connection.ping()

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception as e:
        print(f"Daemon not started yet: {e}")
        return None
    return None
