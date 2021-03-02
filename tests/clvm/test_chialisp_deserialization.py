from unittest import TestCase

from src.wallet.puzzles.load_clvm import load_clvm
from src.util.byte_types import hexstr_to_bytes


DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clvm", package_or_requirement="src.wallet.puzzles")


class TestClvmNativeDeserialization(TestCase):
    """
    Test clvm deserialization done from within the clvm
    """

    def test_deserialization_simple_list(self):
        b = hexstr_to_bytes("ff8568656c6c6fff86667269656e6480")
        cost, output = DESERIALIZE_MOD.run_with_cost([b])
        print(cost, output)
