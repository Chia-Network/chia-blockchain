from secrets import token_bytes
from src.types.proof_of_space import ProofOfSpace  # pylint: disable=E0401


class TestProofOfSpace:
    def test_can_create_proof(self):
        """
        Tests that the change of getting a correct proof is exactly 1/256.
        """
        num_trials = 40000
        success_count = 0

        for _ in range(num_trials):
            challenge_hash = token_bytes(32)
            plot_seed = token_bytes(32)
            if ProofOfSpace.can_create_proof(plot_seed, challenge_hash, 8):
                success_count += 1

        assert abs((success_count * 256 / num_trials) - 1) < 0.3
