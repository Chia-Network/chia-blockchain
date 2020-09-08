from typing import Optional

from clvm_tools.curry import curry as ct_curry, uncurry

from src.types.coin import Coin
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.wallet.puzzles.load_clvm import load_clvm


MOD = load_clvm("genesis-by-puzzle-hash-with-0.clvm", package_or_requirement=__name__)


def curry(*args, **kwargs):
    """
    The clvm_tools version of curry returns `cost, program` for now.
    Eventually it will just return `program`. This placeholder awaits that day.
    """
    cost, prog = ct_curry(*args, **kwargs)
    return Program.to(prog)


def create_genesis_puzzle_or_zero_coin_checker(genesis_puzzle_hash: bytes32) -> Program:
    """
    Given a specific genesis coin id, create a `genesis_coin_mod` that allows
    both that coin id to issue a cc, or anyone to create a cc with amount 0.
    """
    genesis_coin_mod = MOD
    return curry(genesis_coin_mod, [genesis_puzzle_hash])


def genesis_puzzle_hash_for_genesis_coin_checker(
    genesis_coin_checker: Program,
) -> Optional[bytes32]:
    """
    Given a `genesis_coin_checker` program, pull out the genesis puzzle hash.
    """
    r = uncurry(genesis_coin_checker)
    if r is None:
        return r
    f, args = r
    if f != MOD:
        return None
    return args.first().as_atom()


def lineage_proof_for_genesis_puzzle(parent_coin: Coin) -> Program:
    return Program.to((0, [parent_coin.as_list(), 0]))


def lineage_proof_for_zero(parent_coin: Coin) -> Program:
    return Program.to((0, [parent_coin.as_list(), 1]))


def lineage_proof_for_coin(parent_coin: Coin) -> Program:
    breakpoint()
    if parent_coin.amount == 0:
        return lineage_proof_for_zero(parent_coin)
    return lineage_proof_for_genesis_puzzle(parent_coin)
