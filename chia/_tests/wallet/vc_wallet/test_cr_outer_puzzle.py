from __future__ import annotations

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.outer_puzzles import (
    construct_puzzle,
    create_asset_id,
    get_inner_puzzle,
    get_inner_solution,
    match_puzzle,
    solve_puzzle,
)
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.puzzle_drivers import ACSPuzzle
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.cr_cat_drivers import CredentialRestrictionLayer, ProofsChecker


def test_cat_outer_puzzle() -> None:
    authorized_providers: list[bytes32] = [bytes32.zeros, bytes32.zeros]
    proofs_checker = ProofsChecker(flags=[])
    cr_puzzle = CredentialRestrictionLayer(
        authorized_providers=authorized_providers, proofs_checker=proofs_checker, inner_puzzle=ACSPuzzle()
    )
    double_cr_puzzle = CredentialRestrictionLayer(
        authorized_providers=authorized_providers, proofs_checker=proofs_checker, inner_puzzle=cr_puzzle
    )
    uncurried_cr_puzzle = uncurry_puzzle(double_cr_puzzle.puzzle)
    cr_driver: PuzzleInfo | None = match_puzzle(uncurried_cr_puzzle)

    assert cr_driver is not None
    assert cr_driver.type() == "credential restricted"
    assert cr_driver["authorized_providers"] == authorized_providers
    assert cr_driver["proofs_checker"] == proofs_checker.puzzle
    inside_cr_driver: PuzzleInfo | None = cr_driver.also()
    assert inside_cr_driver is not None
    assert inside_cr_driver.type() == "credential restricted"
    assert inside_cr_driver["authorized_providers"] == authorized_providers
    assert inside_cr_driver["proofs_checker"] == proofs_checker.puzzle
    assert construct_puzzle(cr_driver, ACSPuzzle().puzzle) == double_cr_puzzle.puzzle
    assert get_inner_puzzle(cr_driver, uncurried_cr_puzzle) == ACSPuzzle().puzzle
    assert create_asset_id(cr_driver) is None

    # Set up for solve
    coin: Coin = Coin(bytes32.zeros, bytes32.zeros, uint64(0))
    coin_as_hex: str = (
        "0x" + coin.parent_coin_info.hex() + coin.puzzle_hash.hex() + uint64(coin.amount).stream_to_bytes().hex()
    )
    inner_solution = Program.to([[51, ACSPuzzle().puzzle_hash, 100]])
    solution: Program = solve_puzzle(
        cr_driver,
        Solver(
            {
                "coin": coin_as_hex,
                "vc_authorizations": {
                    coin.name().hex(): [
                        "()",
                        "()",
                        "()",
                        "()",
                        "()",
                    ],
                },
            },
        ),
        ACSPuzzle().puzzle,
        inner_solution,
    )

    assert get_inner_solution(cr_driver, solution) == inner_solution
