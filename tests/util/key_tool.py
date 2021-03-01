from blspy import AugSchemeMPL, PrivateKey

from src.types.blockchain_format.program import Program
from src.util.condition_tools import (
    conditions_by_opcode,
    conditions_for_solution,
    pkm_pairs_for_conditions_dict,
)


class KeyTool(dict):
    @classmethod
    def __new__(cls, *args):
        return dict.__new__(*args)

    def add_secret_exponents(self, secret_exponents):
        for _ in secret_exponents:
            bls_private_key = PrivateKey.from_bytes(_.to_bytes(32, "big"))
            self[bls_private_key.get_g1()] = bls_private_key

    def sign(self, pk, msg):
        private = self.get(pk)
        if not private:
            raise ValueError("unknown pubkey %s" % pk)
        return AugSchemeMPL.sign(private, msg)

    def signature_for_solution(self, puzzle: Program, solution: Program, coin_name) -> AugSchemeMPL:
        signatures = []
        conditions = conditions_for_solution(puzzle, solution)
        assert conditions[1] is not None
        conditions_dict = conditions_by_opcode(conditions[1])
        for pk, msg in pkm_pairs_for_conditions_dict(conditions_dict, coin_name):
            signature = self.sign(pk, msg)
            signatures.append(signature)
        return AugSchemeMPL.aggregate(signatures)
