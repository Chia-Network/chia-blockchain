from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Type

from chia_rs import PrivateKey

from chia.cmds.init_funcs import check_keys
from chia.util.errors import KeychainException, KeychainFingerprintNotFound
from chia.util.ints import uint32
from chia.util.keychain import Keychain, KeyData
from chia.util.streamable import Streamable, streamable

# Commands that are handled by the KeychainServer
keychain_commands = [
    "add_private_key",
    "add_key",
    "check_keys",
    "delete_all_keys",
    "delete_key_by_fingerprint",
    "get_all_private_keys",
    "get_first_private_key",
    "get_key_for_fingerprint",
    "get_key",
    "get_keys",
    "get_public_key",
    "get_public_keys",
    "set_label",
    "delete_label",
]

log = logging.getLogger(__name__)

KEYCHAIN_ERR_KEYERROR = "key error"
KEYCHAIN_ERR_LOCKED = "keyring is locked"
KEYCHAIN_ERR_NO_KEYS = "no keys present"
KEYCHAIN_ERR_KEY_NOT_FOUND = "key not found"
KEYCHAIN_ERR_MALFORMED_REQUEST = "malformed request"


@streamable
@dataclass(frozen=True)
class EmptyResponse(Streamable):
    pass


@streamable
@dataclass(frozen=True)
class GetKeyResponse(Streamable):
    key: KeyData


@streamable
@dataclass(frozen=True)
class GetKeyRequest(Streamable):
    fingerprint: uint32
    include_secrets: bool = False

    def run(self, keychain: Keychain) -> GetKeyResponse:
        return GetKeyResponse(key=keychain.get_key(self.fingerprint, self.include_secrets))


@streamable
@dataclass(frozen=True)
class GetKeysResponse(Streamable):
    keys: List[KeyData]


@streamable
@dataclass(frozen=True)
class GetKeysRequest(Streamable):
    include_secrets: bool = False

    def run(self, keychain: Keychain) -> GetKeysResponse:
        return GetKeysResponse(keys=keychain.get_keys(self.include_secrets))


@streamable
@dataclass(frozen=True)
class GetPublicKeyRequest(Streamable):
    fingerprint: uint32

    def run(self, keychain: Keychain) -> GetPublicKeyResponse:
        return GetPublicKeyResponse(key=keychain.get_key(self.fingerprint, include_secrets=False))


@streamable
@dataclass(frozen=True)
class GetPublicKeyResponse(Streamable):
    key: KeyData

    def to_json_dict(self) -> Dict[str, Any]:
        # Ensure that only approved keys are returned
        approved_keys = ["fingerprint", "public_key", "label"]
        key_dict = self.key.to_json_dict()
        return {"key": {key: key_dict[key] for key in approved_keys if key in key_dict}}


@streamable
@dataclass(frozen=True)
class GetPublicKeysRequest(Streamable):
    def run(self, keychain: Keychain) -> GetPublicKeysResponse:
        return GetPublicKeysResponse(keys=keychain.get_keys(include_secrets=False))


@streamable
@dataclass(frozen=True)
class GetPublicKeysResponse(Streamable):
    keys: List[KeyData]

    def to_json_dict(self) -> Dict[str, Any]:
        # Ensure that only approved keys are returned
        approved_keys = ["fingerprint", "public_key", "label"]
        return {
            "keys": [
                {key: key_data_dict[key] for key in approved_keys if key in key_data_dict}
                for key_data_dict in (key_data.to_json_dict() for key_data in self.keys)
            ]
        }


@streamable
@dataclass(frozen=True)
class SetLabelRequest(Streamable):
    fingerprint: uint32
    label: str

    def run(self, keychain: Keychain) -> EmptyResponse:
        keychain.set_label(int(self.fingerprint), self.label)
        return EmptyResponse()


@streamable
@dataclass(frozen=True)
class DeleteLabelRequest(Streamable):
    fingerprint: uint32

    def run(self, keychain: Keychain) -> EmptyResponse:
        keychain.delete_label(self.fingerprint)
        return EmptyResponse()


@dataclass
class KeychainServer:
    """
    Implements a remote keychain service for clients to perform key operations on
    """

    _default_keychain: Keychain = field(default_factory=Keychain)
    _alt_keychains: Dict[str, Keychain] = field(default_factory=dict)

    def get_keychain_for_request(self, request: Dict[str, Any]) -> Keychain:
        """
        Keychain instances can have user and service strings associated with them.
        The keychain backends ultimately point to the same data stores, but the user
        and service strings are used to partition those data stores. We attempt to
        maintain a mapping of user/service pairs to their corresponding Keychain.
        """
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

    async def handle_command(self, command: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if command == "add_private_key":
                data["private"] = True
                data["mnemonic_or_pk"] = data.get("mnemonic_or_pk", data.get("mnemonic", None))
                return await self.add_key(data)
            elif command == "add_key":
                return await self.add_key(data)
            elif command == "check_keys":
                return await self.check_keys(data)
            elif command == "delete_all_keys":
                return await self.delete_all_keys(data)
            elif command == "delete_key_by_fingerprint":
                return await self.delete_key_by_fingerprint(data)
            elif command == "get_all_private_keys":
                return await self.get_all_private_keys(data)
            elif command == "get_first_private_key":
                return await self.get_first_private_key(data)
            elif command == "get_key_for_fingerprint":
                return await self.get_key_for_fingerprint(data)
            elif command == "get_key":
                return await self.run_request(data, GetKeyRequest)
            elif command == "get_keys":
                return await self.run_request(data, GetKeysRequest)
            elif command == "get_public_key":
                return await self.run_request(data, GetPublicKeyRequest)
            elif command == "get_public_keys":
                return await self.run_request(data, GetPublicKeysRequest)
            elif command == "set_label":
                return await self.run_request(data, SetLabelRequest)
            elif command == "delete_label":
                return await self.run_request(data, DeleteLabelRequest)
            return {}
        except Exception as e:
            log.exception(e)
            return {"success": False, "error": str(e), "command": command}

    async def add_key(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self.get_keychain_for_request(request).is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        mnemonic_or_pk = request.get("mnemonic_or_pk", None)
        label = request.get("label", None)
        private = request.get("private", True)

        if mnemonic_or_pk is None:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": "missing key information"},
            }

        try:
            key = self.get_keychain_for_request(request).add_key(mnemonic_or_pk, label, private)
        except KeyError as e:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_KEYERROR,
                "error_details": {"message": f"The word '{e.args[0]}' is incorrect.'", "word": e.args[0]},
            }
        except ValueError as e:
            log.exception(e)
            return {
                "success": False,
                "error": str(e),
            }

        if isinstance(key, PrivateKey):
            fingerprint = key.get_g1().get_fingerprint()
        else:
            fingerprint = key.get_fingerprint()

        return {"success": True, "fingerprint": fingerprint}

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

    async def run_request(self, request_dict: Dict[str, Any], request_type: Type[Any]) -> Dict[str, Any]:
        keychain = self.get_keychain_for_request(request_dict)
        if keychain.is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        try:
            request = request_type.from_json_dict(request_dict)
        except Exception as e:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": str(e)},
            }

        try:
            return {"success": True, **request.run(keychain).to_json_dict()}
        except KeychainFingerprintNotFound as e:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_KEY_NOT_FOUND,
                "error_details": {"fingerprint": e.fingerprint},
            }
        except KeychainException as e:
            return {
                "success": False,
                "error": KEYCHAIN_ERR_MALFORMED_REQUEST,
                "error_details": {"message": str(e)},
            }

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
        keychain = self.get_keychain_for_request(request)
        if keychain.is_keyring_locked():
            return {"success": False, "error": KEYCHAIN_ERR_LOCKED}

        private = request.get("private", True)
        keys = keychain.get_keys(include_secrets=private)
        if len(keys) == 0:
            return {"success": False, "error": KEYCHAIN_ERR_NO_KEYS}

        try:
            if request["fingerprint"] is None:
                key_data = keys[0]
            else:
                key_data = keychain.get_key(request["fingerprint"], include_secrets=private)
        except KeychainFingerprintNotFound:
            return {"success": False, "error": KEYCHAIN_ERR_KEY_NOT_FOUND}

        return {
            "success": True,
            "pk": bytes(key_data.public_key).hex(),
            "entropy": key_data.entropy.hex() if private else None,
        }
