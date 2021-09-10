from typing import Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm

MOD = load_clvm("everything_with_signature.clvm", package_or_requirement=__name__)


def create_genesis_sig_checker(pubkey: bytes32) -> Program:
    """
    Given a specific genesis coin id, create a `genesis_coin_mod` that allows
    both that coin id to issue a cc, or anyone to create a cc with amount 0.
    """
    genesis_coin_mod = MOD
    return genesis_coin_mod.curry(pubkey)


def pubkey_for_genesis_coin_checker(
    genesis_coin_checker: Program,
) -> Optional[bytes32]:
    """
    Given a `genesis_coin_checker` program, pull out the genesis coin id.
    """
    r = genesis_coin_checker.uncurry()
    if r is None:
        return r
    f, args = r
    if f != MOD:
        return None
    return args.first().as_atom()
