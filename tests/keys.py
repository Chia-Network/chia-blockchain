from blspy import AugSchemeMPL

from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle

from src.wallet.puzzles import p2_delegated_puzzle
from src.wallet.puzzles.puzzle_utils import make_create_coin_condition
from tests.util.key_tool import KeyTool
from src.util.ints import uint32
from src.wallet.derive_keys import master_sk_to_wallet_sk

MASTER_KEY = AugSchemeMPL.key_gen(bytes([1] * 32))


def puzzle_program_for_index(index: uint32):
    return p2_delegated_puzzle.puzzle_for_pk(
        bytes(master_sk_to_wallet_sk(MASTER_KEY, index).get_g1())
    )


def puzzle_hash_for_index(index: uint32):
    return puzzle_program_for_index(index).get_hash()


def conditions_for_payment(puzzle_hash_amount_pairs):
    conditions = [
        make_create_coin_condition(ph, amount)
        for ph, amount in puzzle_hash_amount_pairs
    ]
    return conditions


def make_default_keyUtil():
    keychain = KeyTool()
    private_keys = [master_sk_to_wallet_sk(MASTER_KEY, uint32(i)) for i in range(10)]
    secret_exponents = [int.from_bytes(bytes(_), "big") for _ in private_keys]
    keychain.add_secret_exponents(secret_exponents)
    return keychain


DEFAULT_KEYTOOL = make_default_keyUtil()


def spend_coin(coin, conditions, index, keychain=DEFAULT_KEYTOOL):
    solution = p2_delegated_puzzle.solution_for_conditions(
        puzzle_program_for_index(index), conditions
    )
    return build_spend_bundle(coin, solution, keychain)


def build_spend_bundle(coin, solution, keychain=DEFAULT_KEYTOOL):
    coin_solution = CoinSolution(coin, solution)
    signature = keychain.signature_for_solution(solution, bytes(coin))
    return SpendBundle([coin_solution], signature)
