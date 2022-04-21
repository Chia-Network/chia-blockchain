from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof


class AssetType(Enum):
    CAT = "CAT"


@dataclass(frozen=True)
class PuzzleInfo:
    info: Dict[str, Any]


@dataclass(frozen=True)
class Solver:
    info: Dict[str, Any]


class CATOuterPuzzle:
    @classmethod
    def match(cls, puzzle: Program) -> Optional[PuzzleInfo]:
        matched, curried_args = match_cat_puzzle(puzzle)
        if matched:
            _, tail_hash, inner_puzzle = curried_args
            constructor_dict = {
                "type": AssetType.CAT,
                "tail": bytes32(tail_hash.as_python()),
            }
            next_constructor = match_puzzle(inner_puzzle)
            if next_constructor is not None:
                constructor_dict["and"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    @classmethod
    def asset_id(cls, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor.info["tail"])

    @classmethod
    def construct(cls, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if "and" in constructor.info:
            inner_puzzle = construct_puzzle(constructor.info["and"], inner_puzzle)
        return construct_cat_puzzle(CAT_MOD, constructor.info["tail"], inner_puzzle)

    @classmethod
    def solve(cls, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        tail_hash: bytes32 = constructor.info["tail"]
        coin: Coin = solver.info["coin"]
        parent_spend: CoinSpend = solver.info["parent_spend"]
        parent_coin: Coin = parent_spend.coin
        if "and" in constructor.info:
            inner_puzzle = construct_puzzle(PuzzleInfo(constructor.info["and"]), inner_puzzle)
            inner_solution = solve_puzzle(PuzzleInfo(constructor.info["and"]), solver, inner_puzzle, inner_solution)
        matched, curried_args = match_cat_puzzle(parent_spend.puzzle_reveal.to_program())
        assert matched
        _, _, parent_inner_puzzle = curried_args
        spendable_cat = SpendableCAT(
            coin,
            tail_hash,
            inner_puzzle,
            inner_solution,
            lineage_proof=LineageProof(
                parent_coin.parent_coin_info, parent_inner_puzzle.get_tree_hash(), parent_coin.amount
            ),
        )
        return unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [spendable_cat]).coin_spends[0].solution.to_program()


driver_lookup: Dict[AssetType, Any] = {
    AssetType.CAT: CATOuterPuzzle,
}


def match_puzzle(puzzle: Program) -> Optional[PuzzleInfo]:
    for driver in driver_lookup.values():
        potential_info: Optional[PuzzleInfo] = driver.match(puzzle)
        if potential_info is not None:
            return potential_info
    return None


def construct_puzzle(constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
    return driver_lookup[constructor.info["type"]].construct(constructor, inner_puzzle)  # type: ignore


def solve_puzzle(constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
    return driver_lookup[constructor.info["type"]].solve(  # type: ignore
        constructor, solver, inner_puzzle, inner_solution
    )


def create_asset_id(constructor: PuzzleInfo) -> bytes32:
    return driver_lookup[constructor.info["type"]].asset_id(constructor)  # type: ignore
