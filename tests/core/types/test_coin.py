from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.hash import std_hash
import io


def coin_serialize(amount: uint64, clvm_serialize: bytes, full_serialize: bytes):

    c = Coin(bytes32(b"a" * 32), bytes32(b"b" * 32), amount)
    expected_hash = (b"a" * 32) + (b"b" * 32) + clvm_serialize

    expected_serialization = (b"a" * 32) + (b"b" * 32) + full_serialize

    assert c.get_hash() == std_hash(expected_hash)
    assert c.name() == std_hash(expected_hash)
    f = io.BytesIO()
    c.stream(f)
    assert bytes(f.getvalue()) == expected_serialization

    # make sure the serialization round-trips
    f = io.BytesIO(expected_serialization)
    c2 = Coin.parse(f)
    assert c2 == c


class TestCoin:
    def test_coin_serialization(self):

        coin_serialize(uint64(0xFFFF), bytes([0, 0xFF, 0xFF]), bytes([0, 0, 0, 0, 0, 0, 0xFF, 0xFF]))
        coin_serialize(uint64(1337000000), bytes([0x4F, 0xB1, 0x00, 0x40]), bytes([0, 0, 0, 0, 0x4F, 0xB1, 0x00, 0x40]))

        # if the amount is 0, the amount is omitted in the "short" format,
        # that's hashed
        coin_serialize(uint64(0), b"", bytes([0, 0, 0, 0, 0, 0, 0, 0]))

        # when amount is > INT64_MAX, the "short" serialization format is 1 byte
        # longer, since it needs a leading zero to make it positive
        coin_serialize(
            uint64(0xFFFFFFFFFFFFFFFF),
            bytes([0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
            bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),
        )
