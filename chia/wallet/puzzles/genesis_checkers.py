from typing import Tuple, Dict, List

from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.puzzles.load_clvm import load_clvm

GENESIS_BY_ID_MOD = load_clvm("genesis-by-coin-id-with-0.clvm")
GENESIS_BY_PUZHASH_MOD = load_clvm("genesis-by-puzzle-hash-with-0.clvm")
EVERYTHING_WITH_SIG_MOD = load_clvm("everything_with_signature.clvm")
DELEGATED_LIMITATIONS_MOD = load_clvm("delegated_genesis_checker.clvm")


class LimitationsProgram:
    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        raise NotImplementedError("Need to implement 'match' on limitations programs")

    @staticmethod
    def construct(args: List[Program]) -> Program:
        raise NotImplementedError("Need to implement 'construct' on limitations programs")

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        raise NotImplementedError("Need to implement 'solve' on limitations programs")


class GenesisById(LimitationsProgram):
    """
    This TAIL allows for coins to be issued only by a specific "genesis" coin ID.
    There can therefore only be one issuance. There is no minting or melting allowed.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == GENESIS_BY_ID_MOD:
            genesis_id = curried_args.first()
            return True, [genesis_id]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return GENESIS_BY_ID_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        return Program.to([])


class GenesisByPuzhash(LimitationsProgram):
    """
    This TAIL allows for issuance of a certain coin only by a specific puzzle hash.
    There is no minting or melting allowed.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == GENESIS_BY_PUZHASH_MOD:
            genesis_puzhash = curried_args.first()
            return True, [genesis_puzhash]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return GENESIS_BY_PUZHASH_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        pid = hexstr_to_bytes(solution_dict["parent_coin_info"])
        return Program.to([pid, solution_dict["amount"]])


class EverythingWithSig(LimitationsProgram):
    """
    This TAIL allows for issuance, minting, and melting as long as you provide a signature with the spend.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == EVERYTHING_WITH_SIG_MOD:
            pubkey = curried_args.first()
            return True, [pubkey]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return EVERYTHING_WITH_SIG_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        return Program.to([])


class DelegatedLimitations(LimitationsProgram):
    """
    This TAIL allows for another TAIL to be used, as long as a signature of that TAIL's puzzlehash is included.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == DELEGATED_LIMITATIONS_MOD:
            pubkey = curried_args.first()
            return True, [pubkey]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return DELEGATED_LIMITATIONS_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        signed_program = ALL_LIMITATIONS_PROGRAMS[solution_dict["signed_program"]["identifier"]]
        inner_program_args = [Program.fromhex(item) for item in solution_dict["signed_program"]["args"]]
        inner_solution_dict = solution_dict["program_arguments"]
        return Program.to(
            [
                signed_program.construct(inner_program_args),
                signed_program.solve(inner_program_args, inner_solution_dict),
            ]
        )


ALL_LIMITATIONS_PROGRAMS = {
    "genesis_by_id": GenesisById,
    "genesis_by_puzhash": GenesisByPuzhash,
    "everything_with_signature": EverythingWithSig,
    "delegated_limitations": DelegatedLimitations,
}
