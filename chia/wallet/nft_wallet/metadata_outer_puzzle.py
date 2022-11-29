from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

NFT_STATE_LAYER_MOD = load_clvm_maybe_recompile("nft_state_layer.clvm")
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()


def match_metadata_layer_puzzle(puzzle: UncurriedPuzzle) -> Tuple[bool, List[Program]]:
    if puzzle.mod == NFT_STATE_LAYER_MOD:
        return True, list(puzzle.args.as_iter())
    return False, []


def puzzle_for_metadata_layer(metadata: Program, updater_hash: bytes32, inner_puzzle: Program) -> Program:
    return NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, updater_hash, inner_puzzle)


def solution_for_metadata_layer(amount: uint64, inner_solution: Program) -> Program:
    return Program.to([inner_solution, amount])  # type: ignore


@dataclass(frozen=True)
class MetadataOuterPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        matched, curried_args = match_metadata_layer_puzzle(puzzle)
        if matched:
            _, metadata, updater_hash, inner_puzzle = curried_args
            constructor_dict = {
                "type": "metadata",
                "metadata": disassemble(metadata),
                "updater_hash": "0x" + updater_hash.as_python().hex(),
            }
            next_constructor = self._match(uncurry_puzzle(inner_puzzle))
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None
        return None  # Uncomment above when match_metadata_layer_puzzle works

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["updater_hash"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        return puzzle_for_metadata_layer(constructor["metadata"], constructor["updater_hash"], inner_puzzle)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        matched, curried_args = match_metadata_layer_puzzle(puzzle_reveal)
        if matched:
            _, _, _, inner_puzzle = curried_args
            also = constructor.also()
            if also is not None:
                deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(also, uncurry_puzzle(inner_puzzle))
                return deep_inner_puzzle
            else:
                return inner_puzzle
        else:
            raise ValueError("This driver is not for the specified puzzle reveal")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.first()
        also = constructor.also()
        if also:
            deep_inner_solution: Optional[Program] = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin: Coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        also = constructor.also()
        if also is not None:
            inner_solution = self._solve(also, solver, inner_puzzle, inner_solution)
        return solution_for_metadata_layer(
            uint64(coin.amount),
            inner_solution,
        )
