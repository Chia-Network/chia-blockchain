from dataclasses import dataclass
from typing import Any, Optional

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

    def match(self, puzzle: Program) -> Optional[PuzzleInfo]:
        matched, curried_args = match_cat_puzzle(puzzle)
        if matched:
            _, tail_hash, inner_puzzle = curried_args
            constructor_dict = {
                "type": "CAT",
                "tail": "0x" + tail_hash.as_python().hex(),
            }
            next_constructor = self._match(inner_puzzle)
            if next_constructor is not None:
                constructor_dict["and"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["tail"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
        return construct_cat_puzzle(CAT_MOD, constructor["tail"], inner_puzzle)

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        tail_hash: bytes32 = constructor["tail"]
        coin_bytes: bytes = solver["coin"]
        coin: Coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        parent_spend: CoinSpend = CoinSpend.from_bytes(solver["parent_spend"])
        parent_coin: Coin = parent_spend.coin
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
            inner_solution = self._solve(constructor.also(), solver, inner_puzzle, inner_solution)
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
