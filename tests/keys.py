from blspy import AugSchemeMPL

from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from src.util.ints import uint32
from src.wallet.derive_keys import master_sk_to_wallet_sk

MASTER_KEY = AugSchemeMPL.key_gen(bytes([1] * 32))


def puzzle_program_for_index(index: uint32):
    return puzzle_for_pk(bytes(master_sk_to_wallet_sk(MASTER_KEY, index).get_g1()))
