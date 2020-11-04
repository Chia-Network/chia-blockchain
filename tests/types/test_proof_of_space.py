from secrets import token_bytes
from blspy import AugSchemeMPL
from src.types.proof_of_space import ProofOfSpace  # pylint: disable=E0401

#  from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.types.classgroup import ClassgroupElement


class TestProofOfSpace:
    def test_can_create_proof(self):
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 40000
        success_count = 0
        target_filter = (2 ** constants.NUMBER_ZERO_BITS_PLOT_FILTER) * (2 ** constants.NUMBER_ZERO_BITS_SP_FILTER)
        sk = AugSchemeMPL.key_gen(bytes([0x44] * 32))
        sig = AugSchemeMPL.sign(sk, b"")
        for _ in range(num_trials):
            challenge_hash = token_bytes(32)
            plot_id = token_bytes(32)
            sp_output = ClassgroupElement.get_default_element()

            if ProofOfSpace.can_create_proof(constants, plot_id, challenge_hash, sp_output.get_hash(), sig):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.3
