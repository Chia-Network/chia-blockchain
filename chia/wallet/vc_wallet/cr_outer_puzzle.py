from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.puzzle_drivers import UnknownPuzzle, UnknownSolution
from chia.wallet.vc_wallet.cr_cat_drivers import (
    CredentialRestrictionLayer,
    CredentialRestrictionLayerSolution,
    ProofsChecker,
)


@dataclass(frozen=True)
class CROuterPuzzle:
    _match: Callable[[UnknownPuzzle], PuzzleInfo | None]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UnknownPuzzle, Program | None], Program | None]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Program | None]

    def match(self, puzzle: UnknownPuzzle) -> PuzzleInfo | None:
        cr_match: CredentialRestrictionLayer[UnknownPuzzle] | None = CredentialRestrictionLayer.match(
            unknown_puzzle=puzzle
        )
        if cr_match is None:
            return None
        constructor_dict: dict[str, Any] = {
            "type": "credential restricted",
            "authorized_providers": ["0x" + ap.hex() for ap in cr_match.authorized_providers],
            "proofs_checker": disassemble(cr_match.proofs_checker.program),
        }
        next_constructor = self._match(UnknownPuzzle(known_program=cr_match.inner_puzzle.program))
        if next_constructor is not None:
            constructor_dict["also"] = next_constructor.info
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UnknownPuzzle, solution: Program | None = None
    ) -> Program | None:
        cr_match: CredentialRestrictionLayer[UnknownPuzzle] | None = CredentialRestrictionLayer.match(
            unknown_puzzle=puzzle_reveal
        )
        if cr_match is None:
            raise ValueError("This driver is not for the specified puzzle reveal")  # pragma: no cover
        also = constructor.also()
        if also is not None:
            deep_inner_puzzle: Program | None = self._get_inner_puzzle(
                also, UnknownPuzzle(known_program=cr_match.inner_puzzle.program), None
            )
            return deep_inner_puzzle
        else:
            return cr_match.inner_puzzle.program

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Program | None:
        my_inner_solution: Program = solution.at("rrrrrrf")
        also = constructor.also()
        if also:
            deep_inner_solution: Program | None = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def asset_id(self, constructor: PuzzleInfo) -> bytes32 | None:
        return None

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        proof_checker_match = ProofsChecker.match(
            unknown_puzzle=UnknownPuzzle(known_program=constructor["proofs_checker"])
        )
        if proof_checker_match is None:
            raise ValueError("An unknown proofs checker was supplied to constructor")
        return CredentialRestrictionLayer(
            authorized_providers=constructor["authorized_providers"],
            proofs_checker=proof_checker_match,
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle),
        ).program

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        coin_bytes: bytes = solver["coin"]
        coin = Coin(bytes32(coin_bytes[0:32]), bytes32(coin_bytes[32:64]), uint64.from_bytes(coin_bytes[64:72]))
        coin_name: str = coin.name().hex()
        if "vc_authorizations" in solver.info:
            vc_info: tuple[Program, Program, bytes32, bytes32 | None, bytes32 | None] = tuple(
                solver["vc_authorizations"][coin_name]
            )
        else:
            proofs_checker_args = UnknownPuzzle(known_program=constructor["proofs_checker"]).curried_args
            assert proofs_checker_args is not None
            vc_info = (
                # TODO: This is something of a hack here, doesn't really work for proofs checkers generally.
                # The problem is that the CAT driver above us is running its inner puzzle (us) in order to get the
                # conditions that are output. This is bad practice on the CAT driver's part, the protocol should support
                # asking inner drivers for what conditions they return. Alas, since this is not supported, we have to
                # do a hack that we know will work for the one known proof checker we currently have.
                proofs_checker_args[0],
                Program.NIL,
                constructor["authorized_providers"][0],  # Hack for similar reasons as above, we need a valid provider
                None,
                None,
            )

        also = constructor.also()
        if also is not None:
            inner_solution = self._solve(also, solver, inner_puzzle, inner_solution)

        return CredentialRestrictionLayerSolution(
            proof_of_inclusions=vc_info[0],
            proof_checker_solution=UnknownSolution(program=vc_info[1]),
            provider_id=vc_info[2],
            vc_launcher_id=vc_info[3],
            vc_inner_puzhash=vc_info[4],
            my_coin_id=coin.name(),
            inner_solution=UnknownSolution(program=inner_solution),
        ).program
