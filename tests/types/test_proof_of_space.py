from secrets import token_bytes
from src.types.proof_of_space import ProofOfSpace  # pylint: disable=E0401
from src.consensus.constants import constants
from src.types.classgroup import ClassgroupElement


class TestProofOfSpace:
    def test_can_create_proof(self):
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 40000
        success_count = 0
        target_filter = (2 ** constants.NUMBER_ZERO_BITS_PLOT_FILTER) * (2 ** constants.NUMBER_ZERO_BITS_ICP_FILTER)

        for _ in range(num_trials):
            challenge_hash = token_bytes(32)
            plot_id = token_bytes(32)
            icp_output = ClassgroupElement.get_default_element()
            if ProofOfSpace.can_create_proof(constants, plot_id, challenge_hash, icp_output):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.3
