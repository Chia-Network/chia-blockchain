from dataclasses import dataclass
from typing import Any, Optional

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


@dataclass(frozen=True)
class SingletonOuterPuzzle:
    _match: Any
    _asset_id: Any
    _construct: Any
    _solve: Any
    _get_inner_puzzle: Any
    _get_inner_solution: Any

    def match(self, puzzle: Program) -> Optional[PuzzleInfo]:
        matched, curried_args = match_singleton_puzzle(puzzle)
        if matched:
            singleton_struct, inner_puzzle = curried_args
            constructor_dict = {
                "type": "singleton",
                "launcher_id": "0x" + singleton_struct.as_python()[1].hex(),
                "launcher_ph": "0x" + singleton_struct.as_python()[2].hex(),
            }
            next_constructor = self._match(inner_puzzle)
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["launcher_id"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
        launcher_hash = constructor["launcher_ph"] if "launcher_ph" in constructor else SINGLETON_LAUNCHER_HASH
        return puzzle_for_singleton(constructor["launcher_id"], inner_puzzle, launcher_hash)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: Program) -> Optional[Program]:
        matched, curried_args = match_singleton_puzzle(puzzle_reveal)
        if matched:
            _, inner_puzzle = curried_args
            if constructor.also() is not None:
                deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(constructor.also(), inner_puzzle)
                return deep_inner_puzzle
            else:
                return inner_puzzle
        else:
            raise ValueError("This driver is not for the specified puzzle reveal")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.at("rrf")
        if constructor.also():
            deep_inner_solution: Optional[Program] = self._get_inner_solution(constructor.also(), my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin: Coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        parent_spend: CoinSpend = CoinSpend.from_bytes(solver["parent_spend"])
        parent_coin: Coin = parent_spend.coin
        if constructor.also() is not None:
            inner_solution = self._solve(constructor.also(), solver, inner_puzzle, inner_solution)
        matched, curried_args = match_singleton_puzzle(parent_spend.puzzle_reveal.to_program())
        assert matched
        _, parent_inner_puzzle = curried_args
        return solution_for_singleton(
            LineageProof(parent_coin.parent_coin_info, parent_inner_puzzle.get_tree_hash(), uint64(parent_coin.amount)),
            uint64(coin.amount),
            inner_solution,
        )
