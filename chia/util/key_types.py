from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from chia.util.hash import std_hash


# A wrapper for VerifyingKey that conforms to the ObservationRoot protocol
@dataclass(frozen=True)
class Secp256r1PublicKey:
    _public_key: ec.EllipticCurvePublicKey

    def get_fingerprint(self) -> int:
        hash_bytes = std_hash(bytes(self))
        return int.from_bytes(hash_bytes[0:4], "big")

    def __bytes__(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @classmethod
    def from_bytes(cls, blob: bytes) -> Secp256r1PublicKey:
        pk = serialization.load_der_public_key(blob)
        if isinstance(pk, ec.EllipticCurvePublicKey):
            return Secp256r1PublicKey(pk)
        else:
            raise ValueError("Could not load EllipticCurvePublicKey provided blob")

    def derive_unhardened(self, index: int) -> Secp256r1PublicKey:
        raise NotImplementedError("SECP keys do not support derivation")


@dataclass(frozen=True)
class Secp256r1Signature:
    _buf: bytes

    def __bytes__(self) -> bytes:
        return self._buf


# A wrapper for SigningKey that conforms to the SecretInfo protocol
@dataclass(frozen=True)
class Secp256r1PrivateKey:
    _private_key: ec.EllipticCurvePrivateKey

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secp256r1PrivateKey) and self.public_key() == other.public_key()

    def __bytes__(self) -> bytes:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @classmethod
    def from_bytes(cls, blob: bytes) -> Secp256r1PrivateKey:
        sk = serialization.load_der_private_key(blob, password=None)
        if isinstance(sk, ec.EllipticCurvePrivateKey):
            return Secp256r1PrivateKey(sk)
        else:
            raise ValueError("Could not load EllipticCurvePrivateKey provided blob")

    def public_key(self) -> Secp256r1PublicKey:
        return Secp256r1PublicKey(self._private_key.public_key())

    @classmethod
    def from_seed(cls, seed: bytes) -> Secp256r1PrivateKey:
        return Secp256r1PrivateKey(
            ec.derive_private_key(int.from_bytes(std_hash(seed), "big"), ec.SECP256R1(), default_backend())
        )

    def sign(self, msg: bytes, final_pk: Optional[Secp256r1PublicKey] = None) -> Secp256r1Signature:
        if final_pk is not None:
            raise ValueError("SECP256r1 does not support signature aggregation")
        der_sig = self._private_key.sign(msg, ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
        r, s = decode_dss_signature(der_sig)
        sig = r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big")
        return Secp256r1Signature(sig)

    def derive_hardened(self, index: int) -> Secp256r1PrivateKey:
        raise NotImplementedError("SECP keys do not support derivation")

    def derive_unhardened(self, index: int) -> Secp256r1PrivateKey:
        raise NotImplementedError("SECP keys do not support derivation")
