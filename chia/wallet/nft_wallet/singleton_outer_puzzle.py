from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER_HASH,
    match_singleton_puzzle,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


@dataclass(frozen=True)
class SingletonOuterPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        matched, curried_args = match_singleton_puzzle(puzzle)
        if matched:
            singleton_struct, inner_puzzle = curried_args
            constructor_dict = {
                "type": "singleton",
                "launcher_id": "0x" + singleton_struct.as_python()[1].hex(),
                "launcher_ph": "0x" + singleton_struct.as_python()[2].hex(),
            }
            next_constructor = self._match(uncurry_puzzle(inner_puzzle))
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["launcher_id"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        launcher_hash = constructor["launcher_ph"] if "launcher_ph" in constructor else SINGLETON_LAUNCHER_HASH
        return puzzle_for_singleton(constructor["launcher_id"], inner_puzzle, launcher_hash)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        matched, curried_args = match_singleton_puzzle(puzzle_reveal)
        if matched:
            _, inner_puzzle = curried_args
            also = constructor.also()
            if also is not None:
                deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(also, uncurry_puzzle(inner_puzzle))
                return deep_inner_puzzle
            else:
                return inner_puzzle
        else:
            raise ValueError("This driver is not for the specified puzzle reveal")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.at("rrf")
        also = constructor.also()
        if also:
            deep_inner_solution: Optional[Program] = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin: Coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        parent_spend: CoinSpend = CoinSpend.from_bytes(solver["parent_spend"])
        parent_coin: Coin = parent_spend.coin
        also = constructor.also()
        if also is not None:
            inner_solution = self._solve(also, solver, inner_puzzle, inner_solution)
        matched, curried_args = match_singleton_puzzle(uncurry_puzzle(parent_spend.puzzle_reveal.to_program()))
        assert matched
        _, parent_inner_puzzle = curried_args
        return solution_for_singleton(
            LineageProof(parent_coin.parent_coin_info, parent_inner_puzzle.get_tree_hash(), uint64(parent_coin.amount)),
            uint64(coin.amount),
            inner_solution,
        )
