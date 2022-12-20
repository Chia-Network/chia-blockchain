from typing import List, Optional

import blspy

from hsms.atoms import bytes32

from hsms.util.std_hash import std_hash
from hsms.util.bech32 import bech32_decode, bech32_encode, Encoding

from .BLSSignature import BLSSignature
from .BLSPublicKey import BLSPublicKey


BECH32M_PREFIX = "se"

GROUP_ORDER = (
    52435875175126190479447740508185965837690552500527637822603658699938581184513
)


class BLSSecretExponent:
    def __init__(self, sk: blspy.PrivateKey):
        self._sk = sk

    @classmethod
    def from_seed(cls, blob: bytes) -> "BLSSecretExponent":
        secret_exponent = int.from_bytes(std_hash(blob), "big")
        return cls.from_int(secret_exponent)

    @classmethod
    def from_int(cls, secret_exponent) -> "BLSSecretExponent":
        secret_exponent %= GROUP_ORDER
        blob = secret_exponent.to_bytes(32, "big")
        return cls.from_bytes(blob)

    @classmethod
    def from_bytes(cls, blob) -> "BLSSecretExponent":
        return cls(blspy.PrivateKey.from_bytes(blob))

    def fingerprint(self) -> int:
        return self._sk.get_g1().get_fingerprint()

    def sign(
        self, message_hash: bytes32, final_public_key: Optional[BLSPublicKey] = None
    ) -> BLSSignature:
        if final_public_key:
            return BLSSignature(
                blspy.AugSchemeMPL.sign(self._sk, message_hash, final_public_key._g1)
            )
        return BLSSignature(blspy.AugSchemeMPL.sign(self._sk, message_hash))

    def public_key(self) -> BLSPublicKey:
        return BLSPublicKey(self._sk.get_g1())

    def secret_exponent(self):
        return int.from_bytes(bytes(self), "big")

    def hardened_child(self, index: int) -> "BLSSecretExponent":
        return BLSSecretExponent(blspy.AugSchemeMPL.derive_child_sk(self._sk, index))

    def child(self, index: int) -> "BLSSecretExponent":
        return BLSSecretExponent(
            blspy.AugSchemeMPL.derive_child_sk_unhardened(self._sk, index)
        )

    def child_for_path(self, path: List[int]) -> "BLSSecretExponent":
        r = self
        for index in path:
            r = self.child(index)
        return r

    def as_bech32m(self):
        return bech32_encode(BECH32M_PREFIX, bytes(self), Encoding.BECH32M)

    @classmethod
    def from_bech32m(cls, text: str) -> "BLSSecretExponent":
        r = bech32_decode(text)
        if r is not None:
            prefix, base8_data, encoding = r
            if (
                encoding == Encoding.BECH32M
                and prefix == BECH32M_PREFIX
                and len(base8_data) == 33
            ):
                return cls.from_bytes(base8_data[:32])
        raise ValueError("not secret exponent")

    @classmethod
    def zero(cls) -> "BLSSecretExponent":
        return ZERO

    def __add__(self, other):
        return self.from_int(int(self) + int(other))

    def __int__(self):
        return self.secret_exponent()

    def __eq__(self, other):
        return int(self) == int(other)

    def __bytes__(self):
        return bytes(self._sk)

    def __str__(self):
        return "<prv for:%s>" % self.public_key()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)


ZERO = BLSSecretExponent.from_int(0)
