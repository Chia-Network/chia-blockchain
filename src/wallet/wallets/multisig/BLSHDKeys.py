import hashlib

import blspy
from chiasim.hashable.BLSSignature import BLSPublicKey
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey


def fingerprint_for_pk(pk):
    """
    Take a public key and get the fingerprint for it.
    It's just the last four bytes of the sha256 hash.
    """
    return hashlib.sha256(bytes(pk)).digest()[-4:]


class BLSPublicHDKey:
    """
    A class for public hierarchical deterministic bls keys.
    """

    @classmethod
    def from_bytes(cls, blob):
        bls_public_hd_key = blspy.ExtendedPublicKey.from_bytes(blob)
        return cls(bls_public_hd_key)

    def __init__(self, bls_public_hd_key):
        self._bls_public_hd_key = bls_public_hd_key

    def public_hd_child(self, idx) -> "BLSPublicHDKey":
        return self.from_bytes(self._bls_public_hd_key.public_child(idx).serialize())

    def public_child(self, idx) -> BLSPublicKey:
        return self.public_hd_child(idx).public_key()

    def public_key(self):
        return BLSPublicKey.from_bytes(
            self._bls_public_hd_key.get_public_key().serialize()
        )

    def fingerprint(self):
        return fingerprint_for_pk(self.public_key())

    def __bytes__(self):
        return self._bls_public_hd_key.serialize()

    def __str__(self):
        return bytes(self).hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)


class BLSPrivateHDKey:
    """
    A class for private hierarchical deterministic bls keys.
    """

    @classmethod
    def from_seed(cls, seed_bytes):
        bls_private_hd_key = blspy.ExtendedPrivateKey.from_seed(seed_bytes)
        return cls(bls_private_hd_key)

    @classmethod
    def from_bytes(cls, blob):
        bls_private_hd_key = blspy.ExtendedPrivateKey.from_bytes(blob)
        return cls(bls_private_hd_key)

    def __init__(self, bls_private_hd_key):
        self._bls_private_hd_key = bls_private_hd_key

    def public_hd_key(self):
        blob = self._bls_private_hd_key.get_extended_public_key().serialize()
        return BLSPublicHDKey.from_bytes(blob)

    def private_hd_child(self, idx):
        return self.__class__(self._bls_private_hd_key.private_child(idx))

    def public_hd_child(self, idx):
        return self.public_hd_key().public_hd_child(idx)

    def private_child(self, idx):
        return self.private_hd_child(idx).private_key()

    def public_child(self, idx):
        return self.public_hd_child(idx).public_key()

    def private_key(self):
        return BLSPrivateKey(self._bls_private_hd_key.get_private_key())

    def public_key(self):
        return self.public_hd_key().public_key()

    def fingerprint(self):
        return fingerprint_for_pk(self.public_key())

    def __bytes__(self):
        return self._bls_private_hd_key.serialize()

    def __str__(self):
        return "<prv for:%s>" % self.public_key()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)
