from __future__ import annotations

from typing import Optional

from clvm_tools.binutils import assemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16
from chia.wallet.nft_wallet.ownership_outer_puzzle import puzzle_for_ownership_layer
from chia.wallet.nft_wallet.transfer_program_puzzle import puzzle_for_transfer_program
from chia.wallet.outer_puzzles import construct_puzzle, get_inner_puzzle, get_inner_solution, match_puzzle, solve_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import uncurry_puzzle


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
    transfer_program_default: Program = puzzle_for_transfer_program(bytes32([1] * 32), bytes32([2] * 32), uint16(5000))
    ownership_puzzle: Program = puzzle_for_ownership_layer(owner, transfer_program, ACS)
    ownership_puzzle_empty: Program = puzzle_for_ownership_layer(NIL, transfer_program, ACS)
    ownership_puzzle_default: Program = puzzle_for_ownership_layer(owner, transfer_program_default, ACS)
    ownership_driver: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(ownership_puzzle))
    ownership_driver_empty: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(ownership_puzzle_empty))
    ownership_driver_default: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(ownership_puzzle_default))
    transfer_program_driver: Optional[PuzzleInfo] = match_puzzle(uncurry_puzzle(transfer_program_default))

    assert ownership_driver is not None
    assert ownership_driver_empty is not None
    assert ownership_driver_default is not None
    assert transfer_program_driver is not None
    assert ownership_driver.type() == "ownership"
    assert ownership_driver["owner"] == owner
    assert ownership_driver_empty["owner"] == NIL
    assert ownership_driver["transfer_program"] == transfer_program
    assert ownership_driver_default["transfer_program"] == transfer_program_driver
    assert transfer_program_driver.type() == "royalty transfer program"
    assert transfer_program_driver["launcher_id"] == bytes32([1] * 32)
    assert transfer_program_driver["royalty_address"] == bytes32([2] * 32)
    assert transfer_program_driver["royalty_percentage"] == 5000
    assert construct_puzzle(ownership_driver, ACS) == ownership_puzzle
    assert construct_puzzle(ownership_driver_empty, ACS) == ownership_puzzle_empty
    assert construct_puzzle(ownership_driver_default, ACS) == ownership_puzzle_default
    assert get_inner_puzzle(ownership_driver, uncurry_puzzle(ownership_puzzle)) == ACS

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
    assert get_inner_solution(ownership_driver, solution) == inner_solution
