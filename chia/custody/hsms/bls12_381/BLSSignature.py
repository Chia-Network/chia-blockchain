from typing import Iterator, List, Tuple

import blspy

from hsms.meta import streamable

from hsms.streamables import bytes32, bytes96

from .BLSPublicKey import BLSPublicKey

ZERO96 = bytes96([0] * 96)


@streamable
class BLSSignature:
    """
    This wraps the blspy version and resolves a couple edge cases around aggregation and validation.
    """

    @streamable
    class aggsig_pair:
        public_key: BLSPublicKey
        message_hash: bytes32

    def __init__(self, g2: blspy.G2Element):
        assert isinstance(g2, blspy.G2Element)
        self._g2 = g2

    @classmethod
    def from_bytes(cls, blob):
        bls_public_hd_key = blspy.G2Element.from_bytes(blob)
        return cls(bls_public_hd_key)

    @classmethod
    def generator(cls):
        return cls(blspy.G2Element.generator())

    @classmethod
    def zero(cls):
        return cls(blspy.G2Element())

    def __add__(self, other):
        return self.__class__(self._g2 + other._g2)

    def __eq__(self, other):
        return bytes(self) == bytes(other)

    def __bytes__(self) -> bytes:
        return bytes(self._g2)

    def __str__(self):
        return bytes(self._g2).hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)

    def validate(self, hash_key_pairs: Iterator[aggsig_pair]) -> bool:
        return self.verify([(_.public_key, _.message_hash) for _ in hash_key_pairs])

    def verify(self, hash_key_pairs: List[Tuple[BLSPublicKey, bytes32]]) -> bool:
        public_keys: List[blspy.G1Element] = [_[0]._g1 for _ in hash_key_pairs]
        message_hashes: List[bytes32] = [_[1] for _ in hash_key_pairs]

        return blspy.AugSchemeMPL.aggregate_verify(
            public_keys, message_hashes, self._g2
        )
