from enum import Enum
from typing import Optional

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


class CATOuterPuzzle:
    @staticmethod
    def asset_id(puzzle: Program) -> Optional[bytes32]:
        matched, curried_args = match_cat_puzzle(puzzle)
        if matched:
            _, tail_hash, _ = curried_args
            return bytes32(tail_hash.as_python())
        else:
            return None

    @staticmethod
    def construct(asset_id: bytes32, inner_puzzle: Program) -> Program:
        return construct_cat_puzzle(CAT_MOD, asset_id, inner_puzzle)

    @staticmethod
    def solve(coin: Coin, inner_puzzle: Program, inner_solution: Program, parent_spend: CoinSpend) -> Program:
        parent_coin: Coin = parent_spend.coin
        matched, curried_args = match_cat_puzzle(parent_spend.puzzle_reveal.to_program())
        assert matched
        _, tail_hash, parent_inner_puzzle = curried_args
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


OUTER_PUZZLES = {
    AssetType.CAT: CATOuterPuzzle,
}


def type_of_puzzle(puzzle: Program) -> Optional[AssetType]:
    for typ, outer in OUTER_PUZZLES.items():
        asset_id = outer.asset_id(puzzle)
        if asset_id is not None:
            return typ
    return None


def asset_id_of_puzzle(puzzle: Program) -> Optional[bytes32]:
    for type, outer in OUTER_PUZZLES.items():
        asset_id = outer.asset_id(puzzle)
        if asset_id is not None:
            return asset_id
    return None


def construct_puzzle(typ: AssetType, asset_id: bytes32, inner_puzzle: Program) -> Program:
    return OUTER_PUZZLES[typ].construct(asset_id, inner_puzzle)


def solve_puzzle(
    typ: AssetType, coin: Coin, inner_puzzle: Program, inner_solution: Program, parent_spend: CoinSpend
) -> Program:
    return OUTER_PUZZLES[typ].solve(coin, inner_puzzle, inner_solution, parent_spend)
