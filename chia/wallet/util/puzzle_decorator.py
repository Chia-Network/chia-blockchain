from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from typing_extensions import Protocol

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.puzzle_decorator import ClawbackPuzzleDecorator
from chia.wallet.util.puzzle_decorator_type import PuzzleDecoratorType


class PuzzleDecoratorProtocol(Protocol):
    @staticmethod
    def create(config: Dict[str, Any]) -> PuzzleDecoratorProtocol: ...

    def decorate(self, inner_puzzle: Program) -> Program: ...

    def decorate_target_puzzle_hash(
        self, inner_puzzle: Program, target_puzzle_hash: bytes32
    ) -> Tuple[Program, bytes32]: ...

    def decorate_memos(
        self, inner_puzzle: Program, target_puzzle_hash: bytes32, memos: List[bytes]
    ) -> Tuple[Program, List[bytes]]: ...

    def solve(self, puzzle: Program, primaries: List[Payment], inner_solution: Program) -> Tuple[Program, Program]: ...


class PuzzleDecoratorManager:
    decorator_list: List[PuzzleDecoratorProtocol]
    log: logging.Logger

    @staticmethod
    def create(config: List[Dict[str, Any]]) -> PuzzleDecoratorManager:
        """
        Create a new puzzle decorator manager
        :param config: Config
        :return:
        """
        self = PuzzleDecoratorManager()
        self.log = logging.getLogger(__name__)
        self.decorator_list = []
        for decorator in config:
            if "decorator" not in decorator:
                logging.error(f"Undefined decorator: {decorator}")
                continue
            decorator_name = decorator["decorator"]
            if decorator_name == PuzzleDecoratorType.CLAWBACK.name:
                self.decorator_list.append(ClawbackPuzzleDecorator.create(decorator))
            else:
                logging.error(f"Unknown puzzle decorator type: {decorator}")
        return self

    def decorate(self, inner_puzzle: Program) -> Program:
        """
        Decorator a puzzle
        :param inner_puzzle: Inner puzzle
        :return: Decorated inner puzzle
        """
        for decorator in self.decorator_list:
            inner_puzzle = decorator.decorate(inner_puzzle)
        return inner_puzzle

    def decorate_target_puzzle_hash(self, inner_puzzle: Program, target_puzzle_hash: bytes32) -> bytes32:
        """
        Decorate a target puzzle hash
        :param target_puzzle_hash: Target puzzle hash
        :param inner_puzzle: Inner puzzle
        :return: Decorated target puzzle hash
        """
        for decorator in self.decorator_list:
            inner_puzzle, target_puzzle_hash = decorator.decorate_target_puzzle_hash(inner_puzzle, target_puzzle_hash)
        return target_puzzle_hash

    def solve(self, inner_puzzle: Program, primaries: List[Payment], inner_solution: Program) -> Program:
        """
        Generate the solution of the puzzle
        :param inner_puzzle: Inner puzzle
        :param primaries: Primaries list
        :param inner_solution: Solution of the inner puzzle
        :return: Decorated inner puzzle solution
        """
        for decorator in self.decorator_list:
            inner_puzzle, inner_solution = decorator.solve(inner_puzzle, primaries, inner_solution)
        return inner_solution

    def decorate_memos(self, inner_puzzle: Program, target_puzzle_hash: bytes32, memos: List[bytes]) -> List[bytes]:
        """
        Decorate a memo list
        :param inner_puzzle: Inner puzzle
        :param target_puzzle_hash: Target puzzle hash
        :param memos: memo list
        :return: Decorated memo
        """
        for decorator in self.decorator_list:
            inner_puzzle, memos = decorator.decorate_memos(inner_puzzle, target_puzzle_hash, memos)
        return memos
