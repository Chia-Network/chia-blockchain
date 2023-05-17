from __future__ import annotations

from secrets import token_bytes

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.proof_of_space import passes_plot_filter
from chia.types.blockchain_format.sized_bytes import bytes32


class TestProofOfSpace:
    @pytest.mark.parametrize("prefix_bits", [DEFAULT_CONSTANTS.NUMBER_ZERO_BITS_PLOT_FILTER, 8, 7, 6, 5, 1, 0])
    def test_can_create_proof(self, prefix_bits: int) -> None:
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 100000
        success_count = 0
        target_filter = 2**prefix_bits
        for _ in range(num_trials):
            challenge_hash = bytes32(token_bytes(32))
            plot_id = bytes32(token_bytes(32))
            sp_output = bytes32(token_bytes(32))

            if passes_plot_filter(prefix_bits, plot_id, challenge_hash, sp_output):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.35
