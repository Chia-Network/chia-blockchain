from typing import List

import blspy

from hsms.atoms import hexbytes
from hsms.util.bech32 import bech32_decode, bech32_encode, Encoding

BECH32M_PREFIX = "bls1238"


class BLSPublicKey:
    def __init__(self, g1: blspy.G1Element):
        assert isinstance(g1, blspy.G1Element)
        self._g1 = g1

    @classmethod
    def from_bytes(cls, blob):
        bls_public_hd_key = blspy.G1Element.from_bytes(blob)
        return BLSPublicKey(bls_public_hd_key)

    @classmethod
    def generator(cls):
        return BLSPublicKey(blspy.G1Element.generator())

    @classmethod
    def zero(cls):
        return cls(blspy.G1Element())

    def __add__(self, other):
        return BLSPublicKey(self._g1 + other._g1)

    def __mul__(self, other):
        if other == 0:
            return self.zero()
        if other == 1:
            return self
        parity = other & 1
        v = self.__mul__(other >> 1)
        v += v
        if parity:
            v += self
        return v

    def __rmul__(self, other):
        return self.__mul__(other)

    def __eq__(self, other):
        return bytes(self) == bytes(other)

    def __bytes__(self) -> bytes:
        return hexbytes(self._g1)

    def child(self, index: int) -> "BLSPublicKey":
        return BLSPublicKey(
            blspy.AugSchemeMPL.derive_child_pk_unhardened(self._g1, index)
        )

    def child_for_path(self, path: List[int]) -> "BLSPublicKey":
        r = self
        for index in path:
            r = self.child(index)
        return r

    def fingerprint(self):
        return self._g1.get_fingerprint()

    def as_bech32m(self):
        return bech32_encode(BECH32M_PREFIX, bytes(self), Encoding.BECH32M)

    @classmethod
    def from_bech32m(cls, text: str) -> "BLSPublicKey":
        r = bech32_decode(text, max_length=91)
        if r is not None:
            prefix, base8_data, encoding = r
            if (
                encoding == Encoding.BECH32M
                and prefix == BECH32M_PREFIX
                and len(base8_data) == 49
            ):
                return cls.from_bytes(base8_data[:48])
        raise ValueError("not bls12_381 bech32m pubkey")

    def __hash__(self):
        return bytes(self).__hash__()

    def __str__(self):
        return self.as_bech32m()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)
