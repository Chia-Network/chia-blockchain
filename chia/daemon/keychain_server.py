import logging

from blspy import PrivateKey
from chia.util.keychain import Keychain
from typing import Any, Dict, Optional, cast

keychain_commands = ["get_key_for_fingerprint"]

log = logging.getLogger(__name__)

KEYCHAIN_ERR_LOCKED = "keyring is locked"
KEYCHAIN_ERR_NO_KEYS = "no keys present"


class KeychainServer:
    def __init__(self):
        self.keychain = Keychain()

    async def handle_command(self, command, data) -> Dict[str, Any]:
        if command == "get_key_for_fingerprint":
            return await self.get_key_for_fingerprint(cast(Dict[str, Any], data))
        return {}

    async def get_key_for_fingerprint(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.keychain.is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            return {"success": False, "error": KEYCHAIN_ERR_NO_KEYS}

        fingerprint = request.get("fingerprint", None)
        private_key: Optional[PrivateKey] = None
        if fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]

        return {"success": True, "private_key": bytes(private_key.get_g1()).hex()}