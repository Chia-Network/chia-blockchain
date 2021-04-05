from typing import List

from blspy import AugSchemeMPL, G2Element, PrivateKey

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.util.condition_tools import conditions_by_opcode, conditions_for_solution, pkm_pairs_for_conditions_dict
from tests.core.make_block_generator import GROUP_ORDER, int_to_public_key


class KeyTool(dict):
    @classmethod
    def __new__(cls, *args):
        return dict.__new__(*args)

    def add_secret_exponents(self, secret_exponents: List[int]) -> None:
        for _ in secret_exponents:
            self[bytes(int_to_public_key(_))] = _ % GROUP_ORDER

    def sign(self, public_key: bytes, message_hash: bytes32) -> G2Element:
        secret_exponent = self.get(public_key)
        if not secret_exponent:
            raise ValueError("unknown pubkey %s" % public_key.hex())
        bls_private_key = PrivateKey.from_bytes(secret_exponent.to_bytes(32, "big"))
        return AugSchemeMPL.sign(bls_private_key, message_hash)

    def signature_for_solution(self, coin_solution: CoinSolution) -> AugSchemeMPL:
        signatures = []
        err, conditions, cost = conditions_for_solution(coin_solution.puzzle_reveal, coin_solution.solution)
        assert conditions is not None
        conditions_dict = conditions_by_opcode(conditions)
        for public_key, message_hash in pkm_pairs_for_conditions_dict(conditions_dict, coin_solution.coin.name()):
            signature = self.sign(bytes(public_key), message_hash)
            signatures.append(signature)
        return AugSchemeMPL.aggregate(signatures)
