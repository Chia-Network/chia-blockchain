from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


@dataclass(frozen=True)
class CATOuterPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        args = match_cat_puzzle(puzzle)
        if args is None:
            return None
        _, tail_hash, inner_puzzle = args
        constructor_dict = {
            "type": "CAT",
            "tail": "0x" + tail_hash.as_python().hex(),
        }
        next_constructor = self._match(uncurry_puzzle(inner_puzzle))
        if next_constructor is not None:
            constructor_dict["also"] = next_constructor.info
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        args = match_cat_puzzle(puzzle_reveal)
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
        my_inner_solution: Program = solution.first()
        also = constructor.also()
        if also:
            deep_inner_solution: Optional[Program] = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["tail"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        return construct_cat_puzzle(CAT_MOD, constructor["tail"], inner_puzzle)

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        tail_hash: bytes32 = constructor["tail"]
        spendable_cats: List[SpendableCAT] = []
        target_coin: Coin
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
                puzzle = self._construct(also, puzzle)
                solution = self._solve(also, solver, inner_puzzle, inner_solution)
            args = match_cat_puzzle(uncurry_puzzle(parent_spend.puzzle_reveal.to_program()))
            assert args is not None
            _, _, parent_inner_puzzle = args
            spendable_cats.append(
                SpendableCAT(
                    coin,
                    tail_hash,
                    puzzle,
                    solution,
                    lineage_proof=LineageProof(
                        parent_coin.parent_coin_info, parent_inner_puzzle.get_tree_hash(), uint64(parent_coin.amount)
                    ),
                )
            )
        bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cats)
        return next(cs.solution.to_program() for cs in bundle.coin_spends if cs.coin == target_coin)
