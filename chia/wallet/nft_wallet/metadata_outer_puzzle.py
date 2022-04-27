from dataclasses import dataclass
from typing import Any, Optional

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64

# from chia.wallet.nft_wallet.nft_puzzles import (
#     match_metadata_layer_puzzle,
#     puzzle_for_metadata_layer,
#     solution_for_metadata_layer,
# )
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver


# TODO: This driver won't work until the following functions exist and are imported above
def match_metadata_layer_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:  # type: ignore
    pass


def puzzle_for_metadata_layer(metadata: Program, updater_hash: bytes32, inner_puzzle: Program) -> Program:
    pass


def solution_for_metadata_layer(amount: uint64, inner_solution: Program) -> Program:
    pass


@dataclass(frozen=True)
class MetadataOuterPuzzle:
    _match: Any
    _asset_id: Any
    _construct: Any
    _solve: Any

    def match(self, puzzle: Program) -> Optional[PuzzleInfo]:
        matched, curried_args = match_metadata_layer_puzzle(puzzle)
        if matched:
            _, metadata, updater_hash, inner_puzzle = curried_args
            constructor_dict = {
                "type": "metadata",
                "metadata": disassemble(metadata),  # type: ignore
                "updater_hash": "0x" + updater_hash.as_python().hex(),
            }
            next_constructor = self._match(inner_puzzle)
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return bytes32(constructor["updater_hash"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
        return puzzle_for_metadata_layer(constructor["metadata"], constructor["updater_hash"], inner_puzzle)

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin: Coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        if constructor.also() is not None:
            inner_solution = self._solve(constructor.also(), solver, inner_puzzle, inner_solution)
        return solution_for_metadata_layer(
            coin.amount,
            inner_solution,
        )
