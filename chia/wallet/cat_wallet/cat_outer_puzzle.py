from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chia_rs import CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.cat_wallet.cat_utils import (
    CAT,
    CATPuzzle,
    SpendableCAT,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.puzzle_drivers import UnknownPuzzle, UnknownSolution
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


@dataclass(frozen=True)
class CATOuterPuzzle:
    _match: Callable[[UncurriedPuzzle], PuzzleInfo | None]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle, Program | None], Program | None]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Program | None]

    def match(self, puzzle: UncurriedPuzzle) -> PuzzleInfo | None:
        matched_cat = CATPuzzle.match_uncurried(puzzle)
        if matched_cat is None:
            return None
        inner_puzzle = matched_cat.inner_puzzle.puzzle
        constructor_dict: dict[str, Any] = {
            "type": "CAT",
            "tail": "0x" + matched_cat.tail_hash.hex(),
        }
        next_constructor = self._match(uncurry_puzzle(inner_puzzle))
        if next_constructor is not None:
            constructor_dict["also"] = next_constructor.info
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle, solution: Program | None = None
    ) -> Program | None:
        matched_cat = CATPuzzle.match_uncurried(puzzle_reveal)
        if matched_cat is None:
            raise ValueError("This driver is not for the specified puzzle reveal")
        inner_puzzle = matched_cat.inner_puzzle.puzzle
        also = constructor.also()
        if also is not None:
            deep_inner_puzzle: Program | None = self._get_inner_puzzle(
                also, uncurry_puzzle(inner_puzzle), solution.first() if solution is not None else None
            )
            return deep_inner_puzzle
        else:
            return inner_puzzle

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Program | None:
        my_inner_solution: Program = solution.first()
        also = constructor.also()
        if also:
            deep_inner_solution: Program | None = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def asset_id(self, constructor: PuzzleInfo) -> bytes32 | None:
        return bytes32(constructor["tail"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        return CATPuzzle(
            tail_hash=bytes32(constructor["tail"]),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
        ).puzzle

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        tail_hash: bytes32 = constructor["tail"]
        spendable_cats = []
        target_coin: Coin | None = None
        ring = [
            *zip(
                solver["siblings"].as_iter(),
                solver["sibling_spends"].as_iter(),
                solver["sibling_puzzles"].as_iter(),
                solver["sibling_solutions"].as_iter(),
            ),
            (
                Program.to(solver["coin"]),
                Program.to(solver["parent_spend"]),
                inner_puzzle,
                inner_solution,
            ),
        ]
        ring.sort(key=lambda c: bytes(c[0]))  # deterministic sort to make sure all spends have the same ring order
        for coin_prog, spend_prog, puzzle, solution in ring:
            coin_bytes: bytes = coin_prog.as_python()
            coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
            if coin_bytes == solver["coin"]:
                target_coin = coin
            parent_spend: CoinSpend = CoinSpend.from_bytes(spend_prog.as_python())
            parent_coin: Coin = parent_spend.coin
            also = constructor.also()
            if also is not None:
                constructed_solution = self._solve(also, solver, puzzle, solution)
                constructed_puzzle = self._construct(also, puzzle)
            else:
                constructed_solution = solution
                constructed_puzzle = puzzle
            matched_cat = CATPuzzle.match_uncurried(uncurry_puzzle(parent_spend.puzzle_reveal))
            assert matched_cat is not None
            parent_inner_puzzle = matched_cat.inner_puzzle.puzzle
            spendable_cats.append(
                SpendableCAT(
                    cat=CAT(
                        coin=coin,
                        tail_hash=tail_hash,
                        inner_puzzle=UnknownPuzzle(known_puzzle=constructed_puzzle),
                        lineage_proof=LineageProof(
                            parent_coin.parent_coin_info,
                            parent_inner_puzzle.get_tree_hash(),
                            uint64(parent_coin.amount),
                        ),
                    ),
                    inner_solution=UnknownSolution(solution=constructed_solution),
                )
            )
        bundle = unsigned_spend_bundle_for_spendable_cats(spendable_cats)
        return next(Program.from_serialized(cs.solution) for cs in bundle.coin_spends if cs.coin == target_coin)
