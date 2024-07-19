from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Optional

from ecdsa import NIST256p, SigningKey, VerifyingKey

from chia.util.hash import std_hash


# A wrapper for VerifyingKey that conforms to the ObservationRoot protocol
@dataclass(frozen=True)
class Secp256r1PublicKey:
    _verifying_key: VerifyingKey

    def get_fingerprint(self) -> int:
        hash_bytes = std_hash(bytes(self))
        return int.from_bytes(hash_bytes[0:4], "big")

    def __bytes__(self) -> bytes:
        return self._verifying_key.to_string()  # type: ignore[no-any-return]

    @classmethod
    def from_bytes(cls, blob: bytes) -> Secp256r1PublicKey:
        return Secp256r1PublicKey(VerifyingKey.from_string(blob, curve=NIST256p, hashfunc=sha256))

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
    _signing_key: SigningKey

    def __bytes__(self) -> bytes:
        return self._signing_key.to_string()  # type: ignore[no-any-return]

    @classmethod
    def from_bytes(cls, blob: bytes) -> Secp256r1PrivateKey:
        return Secp256r1PrivateKey(SigningKey.from_string(blob, curve=NIST256p, hashfunc=sha256))

    def public_key(self) -> Secp256r1PublicKey:
        return Secp256r1PublicKey(self._signing_key.verifying_key)

    @classmethod
    def from_seed(cls, seed: bytes) -> Secp256r1PrivateKey:
        def entropy(size: int) -> bytes:
            assert len(seed) >= size, f"Cannot initialize a Secp256r1PrivateKey with a seed < {NIST256p.baselen} bytes"
            return seed[:size]

        return Secp256r1PrivateKey(SigningKey.generate(curve=NIST256p, entropy=entropy, hashfunc=sha256))

    def sign(self, msg: bytes, final_pk: Optional[Secp256r1PublicKey] = None) -> Secp256r1Signature:
        if final_pk is not None:
            raise ValueError("SECP256r1 does not support signature aggregation")
        return Secp256r1Signature(self._signing_key.sign_deterministic(msg))

    def derive_hardened(self, index: int) -> Secp256r1PrivateKey:
        raise NotImplementedError("SECP keys do not support derivation")

    def derive_unhardened(self, index: int) -> Secp256r1PrivateKey:
        raise NotImplementedError("SECP keys do not support derivation")
