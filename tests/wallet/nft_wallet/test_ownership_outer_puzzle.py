from typing import Optional

from clvm_tools.binutils import assemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.nft_wallet.ownership_outer_puzzle import puzzle_for_ownership_layer
from chia.wallet.outer_puzzles import construct_puzzle, create_asset_id, get_inner_puzzle, match_puzzle, solve_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver


def test_ownership_outer_puzzle() -> None:
    ACS = Program.to(1)
    NIL = Program.to([])
    owner = bytes32([0] * 32)
    # (mod (current_owner conditions solution)
    #     (list current_owner () conditions)
    # )
    transfer_program = assemble(  # type: ignore
        """
        (c 2 (c () (c 5 ())))
        """
    )
    ownership_puzzle: Program = puzzle_for_ownership_layer(owner, transfer_program, ACS)
    ownership_puzzle_empty: Program = puzzle_for_ownership_layer(NIL, transfer_program, ACS)
    ownership_driver: Optional[PuzzleInfo] = match_puzzle(ownership_puzzle)
    ownership_driver_empty: Optional[PuzzleInfo] = match_puzzle(ownership_puzzle_empty)

    assert ownership_driver is not None
    assert ownership_driver_empty is not None
    assert ownership_driver.type() == "ownership"
    assert ownership_driver["owner"] == owner
    assert ownership_driver_empty["owner"] == NIL
    assert ownership_driver["transfer_program"] == transfer_program
    assert construct_puzzle(ownership_driver, ACS) == ownership_puzzle
    assert construct_puzzle(ownership_driver_empty, ACS) == ownership_puzzle_empty
    assert get_inner_puzzle(ownership_driver, ownership_puzzle) == ACS
    assert create_asset_id(ownership_driver) is None

    # Set up for solve
    inner_solution = Program.to(
        [
            [51, ACS.get_tree_hash(), 1],
            [-10],
        ]
    )
    solution: Program = solve_puzzle(
        ownership_driver,
        Solver({}),
        ACS,
        inner_solution,
    )
    ownership_puzzle.run(solution)
