import blspy

from src.types.hashable.CoinSolution import CoinSolution
from src.types.hashable.SpendBundle import SpendBundle

from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.keychain import Keychain
from src.wallet.puzzles import p2_delegated_puzzle
from src.wallet.puzzles.puzzle_utils import make_create_coin_condition

HIERARCHICAL_PRIVATE_KEY = blspy.ExtendedPrivateKey.from_seed(b"foo")


def bls_private_key_for_index(index):
    return BLSPrivateKey.from_bytes(
        HIERARCHICAL_PRIVATE_KEY.private_child(index).get_private_key().serialize()
    )


def public_key_bytes_for_index(index):
    return HIERARCHICAL_PRIVATE_KEY.private_child(index).get_public_key().serialize()


def puzzle_program_for_index(index):
    return p2_delegated_puzzle.puzzle_for_pk(public_key_bytes_for_index(index))


def puzzle_hash_for_index(index):
    return puzzle_program_for_index(index).program_hash()


def conditions_for_payment(puzzle_hash_amount_pairs):
    conditions = [
        make_create_coin_condition(ph, amount)
        for ph, amount in puzzle_hash_amount_pairs
    ]
    return conditions


def make_default_keychain():
    keychain = Keychain()
    private_keys = [bls_private_key_for_index(_) for _ in range(10)]
    secret_exponents = [int.from_bytes(bytes(_), "big") for _ in private_keys]
    keychain.add_secret_exponents(secret_exponents)
    return keychain


DEFAULT_KEYCHAIN = make_default_keychain()


def spend_coin(coin, conditions, index, keychain=DEFAULT_KEYCHAIN):
    solution = p2_delegated_puzzle.solution_for_conditions(
        puzzle_program_for_index(index), conditions
    )
    return build_spend_bundle(coin, solution, keychain)


def build_spend_bundle(coin, solution, keychain=DEFAULT_KEYCHAIN):
    coin_solution = CoinSolution(coin, solution)
    signature = keychain.signature_for_solution(solution)
    return SpendBundle([coin_solution], signature)
