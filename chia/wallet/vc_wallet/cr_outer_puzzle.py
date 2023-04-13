from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.vc_wallet.cr_cat_drivers import PROOF_FLAGS_CHECKER, construct_cr_layer, match_cr_layer, solve_cr_layer


@dataclass(frozen=True)
class CROuterPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        args: Optional[Tuple[List[bytes32], Program, Program]] = match_cr_layer(puzzle)
        if args is None:
            return None
        authorized_providers, proofs_checker, inner_puzzle = args
        constructor_dict: Dict[str, Any] = {
            "type": "CR",
            "authorized_providers": ["0x" + ap.hex() for ap in authorized_providers],
            # TODO: Add proofs checker return here. Not adding it now for optimization purposes.
        }
        next_constructor = self._match(uncurry_puzzle(inner_puzzle))
        if next_constructor is not None:
            constructor_dict["also"] = next_constructor.info
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        args: Optional[Tuple[List[bytes32], Program, Program]] = match_cr_layer(puzzle_reveal)
        if args is None:
            raise ValueError("This driver is not for the specified puzzle reveal")
        _, _, inner_puzzle = args
        also = constructor.also()
        if also is not None:
            deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(also, uncurry_puzzle(inner_puzzle))
            return deep_inner_puzzle
        else:
            return inner_puzzle

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.at("rrrrrrf")
        also = constructor.also()
        if also:
            deep_inner_solution: Optional[Program] = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return None

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        return construct_cr_layer(
            constructor["authorized_providers"],
            constructor["proofs_checker"] if "proofs_checker" in constructor else PROOF_FLAGS_CHECKER,
            inner_puzzle,
        )

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        if "vc_authorizations" in solver.info:
            vc_info: List[Optional[bytes32]] = [bytes32(val) for val in solver["vc_authorizations"][coin.name().hex()]]
        else:
            vc_info = [None, None, None]
        return solve_cr_layer(
            solver["proof_of_inclusions"],
            solver["proof_of_inclusions"] if "proof_of_inclusions" in solver.info else Program.to(None),
            *vc_info,  # type: ignore
            coin.name(),
            inner_solution,
        )
