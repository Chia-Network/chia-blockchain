import logging
import ssl

from blspy import G1Element, PrivateKey
from chia.daemon.client import DaemonProxy
from chia.daemon.keychain_server import KEYCHAIN_ERR_LOCKED, KEYCHAIN_ERR_NO_KEYS
from chia.server.server import ssl_context_for_client
from chia.util.config import load_config
from chia.util.keychain import Keychain, KeyringIsLocked, supports_keyring_password
from pathlib import Path
from typing import Optional


class KeyringIsEmpty(Exception):
    pass


class KeychainProxy(DaemonProxy):
    keychain: Keychain  # If the keyring doesn't support a master password, we'll proxy calls locally
    log: logging.Logger

    def __init__(self, uri: str, ssl_context: Optional[ssl.SSLContext], log: logging.Logger):
        self.log = log
        if not supports_keyring_password():
            self.keychain = Keychain()  # Proxy locally, don't use RPC
        super().__init__(uri, ssl_context)

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        data = {"fingerprint": fingerprint}
        request = self.format_request("get_key_for_fingerprint", data)
        response = await self._get(request)
        key: Optional[PrivateKey] = None
        success = response["data"].get("success", False)
        if success:
            pk = response["data"].get("private_key", None)
            if not pk:
                self.log.error("Missing pk in get_key_for_fingerprint response")
                return None
            key = G1Element.from_bytes(bytes.fromhex(pk))
        else:
            error = response["data"].get("error", None)
            if error:
                if error == KEYCHAIN_ERR_LOCKED:
                    raise KeyringIsLocked()
                elif error == KEYCHAIN_ERR_NO_KEYS:
                    raise KeyringIsEmpty()
                else:
                    self.log.error(f"get_key_for_fingerprint failed with error: {error}")
                    raise Exception(error)

        return key


async def connect_to_keychain(self_hostname: str, daemon_port: int, ssl_context: Optional[ssl.SSLContext], log: logging.Logger) -> KeychainProxy:
    """
    Connect to the local daemon.
    """

    client = KeychainProxy(f"wss://{self_hostname}:{daemon_port}", ssl_context, log)
    await client.start()
    return client


async def connect_to_keychain_and_validate(root_path: Path, log: logging.Logger) -> Optional[KeychainProxy]:
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
        connection = await connect_to_keychain(net_config["self_hostname"], net_config["daemon_port"], ssl_context, log)
        r = await connection.ping()

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception as e:
        print(f"Daemon not started yet: {e}")
        return None
    return None
