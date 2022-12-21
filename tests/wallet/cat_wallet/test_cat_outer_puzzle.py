from __future__ import annotations

from typing import Optional

import pytest
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.outer_puzzles import construct_puzzle, get_inner_puzzle, get_inner_solution, match_puzzle, solve_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.uncurried_puzzle import uncurry_puzzle


def test_cat_outer_puzzle() -> None:
    ACS = Program.to(1)
    tail = bytes32([0] * 32)
    cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail, ACS)
    double_cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail, cat_puzzle)
    uncurried_cat_puzzle = uncurry_puzzle(double_cat_puzzle)
    cat_driver: Optional[PuzzleInfo] = match_puzzle(uncurried_cat_puzzle)

    assert cat_driver is not None
    assert cat_driver.type() == "CAT"
    assert cat_driver["tail"] == tail
    inside_cat_driver: Optional[PuzzleInfo] = cat_driver.also()
    assert inside_cat_driver is not None
    assert inside_cat_driver.type() == "CAT"
    assert inside_cat_driver["tail"] == tail
    assert construct_puzzle(cat_driver, ACS) == double_cat_puzzle
    assert get_inner_puzzle(cat_driver, uncurried_cat_puzzle) == ACS

    # Set up for solve
    parent_coin = Coin(tail, double_cat_puzzle.get_tree_hash(), uint64(100))
    child_coin = Coin(parent_coin.name(), double_cat_puzzle.get_tree_hash(), uint64(100))
    parent_spend = CoinSpend(parent_coin, double_cat_puzzle.to_serialized_program(), Program.to([]))
    child_coin_as_hex: str = (
        "0x" + child_coin.parent_coin_info.hex() + child_coin.puzzle_hash.hex() + bytes(uint64(child_coin.amount)).hex()
    )
    parent_spend_as_hex: str = "0x" + bytes(parent_spend).hex()
    inner_solution = Program.to([[51, ACS.get_tree_hash(), 100]])

    solution: Program = solve_puzzle(
        cat_driver,
        Solver(
            {
                "coin": child_coin_as_hex,
                "parent_spend": parent_spend_as_hex,
                "siblings": "(" + child_coin_as_hex + ")",
                "sibling_spends": "(" + parent_spend_as_hex + ")",
                "sibling_puzzles": "(" + disassemble(ACS) + ")",
                "sibling_solutions": "(" + disassemble(inner_solution) + ")",
            }
        ),
        ACS,
        inner_solution,
    )
    with pytest.raises(ValueError, match="clvm raise"):
        double_cat_puzzle.run(solution)

    assert get_inner_solution(cat_driver, solution) == inner_solution
