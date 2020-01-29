import utilities.puzzle_utilities as pu
from standard_wallet.wallet import Wallet
from binascii import hexlify
import pytest


def test_pubkey_format():
    wallet = Wallet()
    pubkey = wallet.get_next_public_key()
    assert pu.pubkey_format(pubkey) == f"0x{hexlify(pubkey.serialize()).decode('ascii')}"
    assert pu.pubkey_format(pubkey.serialize()) == f"0x{hexlify(pubkey.serialize()).decode('ascii')}"
    assert pu.pubkey_format(hexlify(pubkey.serialize()).decode('ascii')) == f"0x{hexlify(pubkey.serialize()).decode('ascii')}"
    assert pu.pubkey_format(f"0x{hexlify(pubkey.serialize()).decode('ascii')}") == f"0x{hexlify(pubkey.serialize()).decode('ascii')}"


def test_pubkey_format_exception():
    with pytest.raises(ValueError):
        assert pu.pubkey_format("gibberish")


def test_pubkey_format_invalid_pubkey():
    with pytest.raises(ValueError):
        assert pu.pubkey_format("0xdeadbeef")
