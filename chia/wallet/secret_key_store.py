from __future__ import annotations

from typing import Dict, Optional

from blspy import G1Element, PrivateKey

GROUP_ORDER = 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001


class SecretKeyStore:
    _pk2sk: Dict[G1Element, PrivateKey]

    def __init__(self):
        self._pk2sk = {}

    def save_secret_key(self, secret_key: PrivateKey):
        public_key = secret_key.get_g1()
        self._pk2sk[bytes(public_key)] = secret_key

    def secret_key_for_public_key(self, public_key: G1Element) -> Optional[PrivateKey]:
        return self._pk2sk.get(bytes(public_key))
