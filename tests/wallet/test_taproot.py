from blspy import G1Element

from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE,
    calculate_synthetic_offset,
    calculate_synthetic_public_key,
)


class TestTaproot:
    def test_1(self):
        for main_secret_exponent in range(500, 600):
            hidden_puzzle_hash = DEFAULT_HIDDEN_PUZZLE.get_tree_hash()
            main_pubkey = G1Element.generator() * main_secret_exponent
            offset = calculate_synthetic_offset(main_pubkey, hidden_puzzle_hash)
            offset_pubkey = G1Element.generator() * offset
            spk1 = main_pubkey + offset_pubkey
            spk2 = calculate_synthetic_public_key(main_pubkey, hidden_puzzle_hash)
            assert spk1 == spk2

        return 0
