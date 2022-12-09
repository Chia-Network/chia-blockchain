from __future__ import annotations

import unittest

from chia.util.significant_bits import count_significant_bits, truncate_to_significant_bits


class TestSignificantBits(unittest.TestCase):
    def test_truncate_to_significant_bits(self):
        a = -0b001101
        assert truncate_to_significant_bits(a, 2) == -0b1100
        a = -0b001111
        assert truncate_to_significant_bits(a, 2) == -0b1100
        a = 0b1111
        assert truncate_to_significant_bits(a, 2) == 0b1100
        a = 0b1000000111
        assert truncate_to_significant_bits(a, 8) == 0b1000000100
        a = 0b1000000111
        assert truncate_to_significant_bits(a, 0) == 0b0
        a = 0b1000000111
        assert truncate_to_significant_bits(a, 500) == a
        a = -0b1000000111
        assert truncate_to_significant_bits(a, 500) == a
        a = 0b10101
        assert truncate_to_significant_bits(a, 5) == a
        a = 0b10101
        assert truncate_to_significant_bits(a, 4) == 0b10100

    def test_count_significant_bits(self):
        assert count_significant_bits(0b0001) == 1
        assert count_significant_bits(0b00010) == 1
        assert count_significant_bits(0b01010) == 3
        assert count_significant_bits(-0b01010) == 3
        assert count_significant_bits(0b0) == 0
        assert count_significant_bits(0b1) == 1
        assert count_significant_bits(0b1000010101010000) == 12


if __name__ == "__main__":
    unittest.main()
