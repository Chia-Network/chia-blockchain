from __future__ import annotations

import pytest

from chia.util.ints import uint32
from chia.util.key_types import Secp256r1PrivateKey, Secp256r1PublicKey
from chia.util.keychain import generate_mnemonic, mnemonic_to_seed


def test_key_drivers() -> None:
    """
    This tests that the chia.util.key_types drivers for these keys works properly, it does not test the sanity of the
    underlying library.
    """
    mnemonic = generate_mnemonic()
    sk = Secp256r1PrivateKey.from_seed(mnemonic_to_seed(mnemonic))
    assert Secp256r1PrivateKey.from_bytes(bytes(sk)) == sk
    with pytest.raises(NotImplementedError):
        sk.derive_hardened(1)
    with pytest.raises(NotImplementedError):
        sk.derive_unhardened(1)

    pk = sk.public_key()
    assert Secp256r1PublicKey.from_bytes(bytes(pk)) == pk
    assert pk.get_fingerprint() < uint32.MAXIMUM
