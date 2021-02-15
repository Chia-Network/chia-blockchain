from secrets import token_bytes
from src.types.blockchain_format.proof_of_space import ProofOfSpace  # pylint: disable=E0401

from src.consensus.default_constants import DEFAULT_CONSTANTS


class TestProofOfSpace:
    def test_can_create_proof(self):
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 100000
        success_count = 0
        target_filter = 2 ** DEFAULT_CONSTANTS.NUMBER_ZERO_BITS_PLOT_FILTER
        for _ in range(num_trials):
            challenge_hash = token_bytes(32)
            plot_id = token_bytes(32)
            sp_output = token_bytes(32)

            if ProofOfSpace.passes_plot_filter(DEFAULT_CONSTANTS, plot_id, challenge_hash, sp_output):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.35
