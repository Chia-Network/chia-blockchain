from __future__ import annotations

from unittest import TestCase

from chia.full_node.bundle_tools import (
    match_standard_transaction_at_any_index,
    match_standard_transaction_exactly_and_return_pubkey,
)
from chia.util.byte_types import hexstr_to_bytes

gen1 = hexstr_to_bytes(
    "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
)

EXPECTED_START = 46
PUBKEY_PLUS_SUFFIX = 48 + 4 + 1
EXPECTED_END = 337 - PUBKEY_PLUS_SUFFIX

STANDARD_TRANSACTION_1 = hexstr_to_bytes(
    """ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaff018080"""  # noqa
)

STANDARD_TRANSACTION_2 = hexstr_to_bytes(
    """ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbff018080"""  # noqa
)


class TestScan(TestCase):
    def test_match_generator(self):
        # match_standard_transaction_at_any_index(generator_body: bytes) -> (int,int):
        m = match_standard_transaction_at_any_index(gen1)
        assert m == (EXPECTED_START, EXPECTED_END)

        m = match_standard_transaction_at_any_index(b"\xff" + gen1 + b"\x80")
        assert m == (EXPECTED_START + 1, EXPECTED_END + 1)

        m = match_standard_transaction_at_any_index(gen1[47:])
        assert m is None

    def test_match_transaction(self):
        # match_standard_transaction_exactly_and_return_pubkey(transaction: bytes) -> Optional[bytes]:
        m = match_standard_transaction_exactly_and_return_pubkey(STANDARD_TRANSACTION_1)
        assert m == hexstr_to_bytes(
            "b0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        m = match_standard_transaction_exactly_and_return_pubkey(STANDARD_TRANSACTION_1 + b"\xfa")
        assert m is None

        m = match_standard_transaction_exactly_and_return_pubkey(b"\xba" + STANDARD_TRANSACTION_1 + b"\xfa")
        assert m is None

        m = match_standard_transaction_exactly_and_return_pubkey(b"\xba" + STANDARD_TRANSACTION_1)
        assert m is None

        m = match_standard_transaction_exactly_and_return_pubkey(
            gen1[EXPECTED_START : EXPECTED_END + PUBKEY_PLUS_SUFFIX]
        )
        assert m == hexstr_to_bytes(
            "b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3"
        )

        m = match_standard_transaction_exactly_and_return_pubkey(gen1)
        assert m is None
