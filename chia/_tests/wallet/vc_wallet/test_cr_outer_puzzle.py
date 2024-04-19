from __future__ import annotations

from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.outer_puzzles import (
    construct_puzzle,
    create_asset_id,
    get_inner_puzzle,
    get_inner_solution,
    match_puzzle,
    solve_puzzle,
)
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.cr_cat_drivers import construct_cr_layer


def test_cat_outer_puzzle() -> None:
    authorized_providers: List[bytes32] = [bytes32([0] * 32), bytes32([0] * 32)]
    proofs_checker: Program = Program.to(None)
    ACS: Program = Program.to(1)
    cr_puzzle: Program = construct_cr_layer(authorized_providers, proofs_checker, ACS)
    double_cr_puzzle: Program = construct_cr_layer(authorized_providers, proofs_checker, cr_puzzle)
    uncurried_cr_puzzle = uncurry_puzzle(double_cr_puzzle)
    cr_driver: Optional[PuzzleInfo] = match_puzzle(uncurried_cr_puzzle)

    assert cr_driver is not None
    assert cr_driver.type() == "credential restricted"
    assert cr_driver["authorized_providers"] == authorized_providers
    assert cr_driver["proofs_checker"] == proofs_checker
    inside_cr_driver: Optional[PuzzleInfo] = cr_driver.also()
    assert inside_cr_driver is not None
    assert inside_cr_driver.type() == "credential restricted"
    assert inside_cr_driver["authorized_providers"] == authorized_providers
    assert inside_cr_driver["proofs_checker"] == proofs_checker
    assert construct_puzzle(cr_driver, ACS) == double_cr_puzzle
    assert get_inner_puzzle(cr_driver, uncurried_cr_puzzle) == ACS
    assert create_asset_id(cr_driver) is None

    # Set up for solve
    coin: Coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    coin_as_hex: str = (
        "0x" + coin.parent_coin_info.hex() + coin.puzzle_hash.hex() + uint64(coin.amount).stream_to_bytes().hex()
    )
    inner_solution = Program.to([[51, ACS.get_tree_hash(), 100]])
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
        ACS,
        inner_solution,
    )

    assert get_inner_solution(cr_driver, solution) == inner_solution
