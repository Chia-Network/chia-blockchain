from dataclasses import dataclass
from typing import Any, Optional, Tuple, Iterator

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm

NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()

def match_metadata_layer_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    mod, meta_args = puzzle.uncurry()
    if mod == NFT_STATE_LAYER_MOD:
        return True, list(meta_args.as_iter())
    return False, Program.to([])


def puzzle_for_metadata_layer(metadata: Program, updater_hash: bytes32, inner_puzzle: Program) -> Program:
    metadata_puzzle = NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, updater_hash, inner_puzzle)
    return metadata_puzzle


def solution_for_metadata_layer(amount: uint64, inner_solution: Program) -> Program:
    return Program.to([inner_solution, amount])


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
        return None  # Uncomment above when match_metadata_layer_puzzle works

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
