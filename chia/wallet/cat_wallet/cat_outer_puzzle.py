from dataclasses import dataclass
from typing import Any, List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver


@dataclass(frozen=True)
class CATOuterPuzzle:
    _match: Any
    _asset_id: Any
    _construct: Any
    _solve: Any
    _get_inner_puzzle: Any
    _get_inner_solution: Any

    def match(self, puzzle: Program) -> Optional[PuzzleInfo]:
        args = match_cat_puzzle(*puzzle.uncurry())
        if args is None:
            return None
        _, tail_hash, inner_puzzle = args
        constructor_dict = {
            "type": "CAT",
            "tail": "0x" + tail_hash.as_python().hex(),
        }
        next_constructor = self._match(inner_puzzle)
        if next_constructor is not None:
            constructor_dict["also"] = next_constructor.info
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: Program) -> Optional[Program]:
        args = match_cat_puzzle(*puzzle_reveal.uncurry())
        if args is None:
            raise ValueError("This driver is not for the specified puzzle reveal")
        _, _, inner_puzzle = args
        if constructor.also() is not None:
            deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(constructor.also(), inner_puzzle)
            return deep_inner_puzzle
        else:
            return inner_puzzle

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.first()
        if constructor.also():
            deep_inner_solution: Optional[Program] = self._get_inner_solution(constructor.also(), my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["tail"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
        return construct_cat_puzzle(CAT_MOD, constructor["tail"], inner_puzzle)

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        tail_hash: bytes32 = constructor["tail"]
        spendable_cats: List[SpendableCAT] = []
        target_coin: Coin
        for coin_prog, spend_prog, puzzle, solution in [
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
        ]:
            coin_bytes: bytes = coin_prog.as_python()
            coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
            if coin_bytes == solver["coin"]:
                target_coin = coin
            parent_spend: CoinSpend = CoinSpend.from_bytes(spend_prog.as_python())
            parent_coin: Coin = parent_spend.coin
            if constructor.also() is not None:
                puzzle = self._construct(constructor.also(), puzzle)
                solution = self._solve(constructor.also(), solver, inner_puzzle, inner_solution)
            args = match_cat_puzzle(*parent_spend.puzzle_reveal.to_program().uncurry())
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
