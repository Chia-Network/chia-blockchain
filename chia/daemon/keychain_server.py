import logging

from blspy import PrivateKey
from chia.cmds.init_funcs import check_keys
from chia.util.keychain import Keychain
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

# Commands that are handled by the KeychainServer
keychain_commands = [
    "add_private_key",
    "check_keys",
    "delete_all_keys",
    "delete_key_by_fingerprint",
    "get_all_private_keys",
    "get_first_private_key",
    "get_key_for_fingerprint",
]

log = logging.getLogger(__name__)

KEYCHAIN_ERR_KEYERROR = "key error"
KEYCHAIN_ERR_LOCKED = "keyring is locked"
KEYCHAIN_ERR_NO_KEYS = "no keys present"
KEYCHAIN_ERR_MALFORMED_REQUEST = "malformed request"


class KeychainServer:
    """
    Implements a remote keychain service for clients to perform key operations on
    """

    def __init__(self):
        self._default_keychain = Keychain()
        self._alt_keychains = {}

    def get_keychain_for_request(self, request: Dict[str, Any]):
        """
        Keychain instances can have user and service strings associated with them.
        The keychain backends ultimately point to the same data stores, but the user
        and service strings are used to partition those data stores. We attempt to
        maintain a mapping of user/service pairs to their corresponding Keychain.
        """
        keychain = None
        user = request.get("kc_user", self._default_keychain.user)
        service = request.get("kc_service", self._default_keychain.service)
        if user == self._default_keychain.user and service == self._default_keychain.service:
            keychain = self._default_keychain
        else:
            key = (user or "unnamed") + (service or "")
            if key in self._alt_keychains:
                keychain = self._alt_keychains[key]
            else:
                keychain = Keychain(user=user, service=service)
                self._alt_keychains[key] = keychain
        return keychain

    async def handle_command(self, command, data) -> Dict[str, Any]:
        if command == "add_private_key":
            return await self.add_private_key(cast(Dict[str, Any], data))
        elif command == "check_keys":
            return await self.check_keys(cast(Dict[str, Any], data))
        elif command == "delete_all_keys":
            return await self.delete_all_keys(cast(Dict[str, Any], data))
        elif command == "delete_key_by_fingerprint":
            return await self.delete_key_by_fingerprint(cast(Dict[str, Any], data))
        elif command == "get_all_private_keys":
            return await self.get_all_private_keys(cast(Dict[str, Any], data))
        elif command == "get_first_private_key":
            return await self.get_first_private_key(cast(Dict[str, Any], data))
        elif command == "get_key_for_fingerprint":
            return await self.get_key_for_fingerprint(cast(Dict[str, Any], data))
        return {}

    async def add_private_key(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        mnemonic = request.get("mnemonic", None)
        passphrase = request.get("passphrase", None)
        if mnemonic is None or passphrase is None:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": "missing mnemonic and/or passphrase"},
            }

        try:
            self.get_keychain_for_request(request).add_private_key(mnemonic, passphrase)
        except KeyError as e:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_KEYERROR,
                "error_details": {"message": f"The word '{e.args[0]}' is incorrect.'", "word": e.args[0]},
            }

        return {"success": True}

    async def check_keys(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        root_path = request.get("root_path", None)
        if root_path is None:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": "missing root_path"},
            }

        check_keys(Path(root_path))

        return {"success": True}

    async def delete_all_keys(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        self.get_keychain_for_request(request).delete_all_keys()

        return {"success": True}

    async def delete_key_by_fingerprint(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        fingerprint = request.get("fingerprint", None)
        if fingerprint is None:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": "missing fingerprint"},
            }

        self.get_keychain_for_request(request).delete_key_by_fingerprint(fingerprint)

        return {"success": True}

    async def get_all_private_keys(self, request: Dict[str, Any]) -> Dict[str, Any]:
        all_keys: List[Dict[str, Any]] = []
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        private_keys = self.get_keychain_for_request(request).get_all_private_keys()
        for sk, entropy in private_keys:
            all_keys.append({"pk": bytes(sk.get_g1()).hex(), "entropy": entropy.hex()})

        return {"success": True, "private_keys": all_keys}

    async def get_first_private_key(self, request: Dict[str, Any]) -> Dict[str, Any]:
        key: Dict[str, Any] = {}
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        sk_ent = self.get_keychain_for_request(request).get_first_private_key()
        if sk_ent is None:
            return {"success": False, "error": KEYCHAIN_ERR_NO_KEYS}

        pk_str = bytes(sk_ent[0].get_g1()).hex()
        ent_str = sk_ent[1].hex()
        key = {"pk": pk_str, "entropy": ent_str}

        return {"success": True, "private_key": key}

    async def get_key_for_fingerprint(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        private_keys = self.get_keychain_for_request(request).get_all_private_keys()
        if len(private_keys) == 0:
            return {"success": False, "error": KEYCHAIN_ERR_NO_KEYS}

        fingerprint = request.get("fingerprint", None)
        private_key: Optional[PrivateKey] = None
        entropy: Optional[bytes] = None
        if fingerprint is not None:
            for sk, entropy in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break
        else:
            private_key, entropy = private_keys[0]

        if not private_key or not entropy:
            return {"success": False, "error": KEYCHAIN_ERR_NO_KEYS}
        else:
            return {"success": True, "pk": bytes(private_key.get_g1()).hex(), "entropy": entropy.hex()}
