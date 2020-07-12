from src.util.condition_tools import (
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
    conditions_for_solution,
)
from blspy import PrivateKey

class KeyTool(dict):
    @classmethod
    def __new__(cls, *args):
        return dict.__new__(*args)

    def add_secret_exponents(self, secret_exponents):
        for _ in secret_exponents:
            bls_private_key = PrivateKey.from_bytes(_.to_bytes(32, "big"))
            self[bls_private_key.get_g1()] = bls_private_key

    def sign(self, aggsig_pair):
        bls_private_key = self.get(aggsig_pair.public_key)
        if not bls_private_key:
            raise ValueError("unknown pubkey %s" % aggsig_pair.public_key)
        return bls_private_key.sign(aggsig_pair.message_hash)

    def signature_for_solution(self, solution, coin_name):
        signatures = []
        conditions = conditions_for_solution(solution)
        assert conditions[1] is not None
        conditions_dict = conditions_by_opcode(conditions[1])
        for _ in hash_key_pairs_for_conditions_dict(conditions_dict, coin_name):
            signature = self.sign(_)
            signatures.append(signature)
        return BLSSignature.aggregate(signatures)
