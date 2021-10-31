from typing import Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm

MOD = load_clvm("genesis-by-coin-id-with-0.clvm", package_or_requirement=__name__)


def create_genesis_or_zero_coin_checker(genesis_coin_id: bytes32) -> Program:
    """
    Given a specific genesis coin id, create a `genesis_coin_mod` that allows
    both that coin id to issue a cc, or anyone to create a cc with amount 0.
    """
    genesis_coin_mod = MOD
    return genesis_coin_mod.curry(genesis_coin_id)


def genesis_coin_id_for_genesis_coin_checker(
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


def lineage_proof_for_genesis(parent_coin: Coin) -> Program:
    return Program.to((0, [parent_coin.as_list(), 0]))


def lineage_proof_for_zero(parent_coin: Coin) -> Program:
    return Program.to((0, [parent_coin.as_list(), 1]))


def lineage_proof_for_coin(parent_coin: Coin) -> Program:
    if parent_coin.amount == 0:
        return lineage_proof_for_zero(parent_coin)
    return lineage_proof_for_genesis(parent_coin)
