from typing import Dict, Tuple, List, Union, Any

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32
from chia.wallet.util.puzzle_representation import PuzzleRepresentation

# These imports should be temporary
from blspy import G1Element
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle as standard_puzzle
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

OFFER_MOD = load_clvm("settlement_payments.clvm")

"""
The following are example classes.
Ideally, all of our current driver code would be put into a puzzle driver class and registered with the PuzzleCompressor
structure below.  They must all have three methods implemented:
- match: Take the result of a uncurry() call and return the relevant list of args that will be put into the
         PuzzleRepresentation. (The criteria for this list of args is that you should be able to fully construct
         the puzzle with them, which is the next function)
- construct: Receive a list of args from a PuzzleRepresentation and construct a full puzzle reveal
- solve: Receive an opaque piece of JSON, and return a solution reveal.  The reason this argument is an opaque piece
         of JSON is because the api needs to be the same for all drivers, but obviously all programs will need unique
         arguments for their solution.  This makes it potentially easy for a UI to craft this as a field on a request
         which the wallet can blindly hand to the driver it has, and recieve a solution to build the spend with.
"""


class StandardPuzzle:
    @staticmethod
    def match(puzzle: Program, compressor: "PuzzleCompressor") -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        uncurried_mod, curried_args = puzzle.uncurry()
        if standard_puzzle.MOD == uncurried_mod:
            synthetic_pubkey = curried_args.first()
            return True, [synthetic_pubkey]
        else:
            return False, []

    @staticmethod
    def construct(driver_dict, args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        return standard_puzzle.MOD.curry(args[0])

    @staticmethod
    def solve(driver_dict, args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        assert "hidden_reveal" in solution_dict
        if solution_dict["hidden_reveal"]:
            assert all(arg in solution_dict for arg in ["hidden_public_key", "hidden_puzzle", "solution"])
            return standard_puzzle.solution_for_hidden_puzzle(
                G1Element.from_bytes(hexstr_to_bytes(solution_dict["hidden_public_key"])),
                Program.from_bytes(hexstr_to_bytes(solution_dict["hidden_puzzle"])),
                Program.from_bytes(hexstr_to_bytes(solution_dict["solution"])),
            )
        else:
            assert all(arg in solution_dict for arg in ["delegated_puzzle", "solution"])
            return standard_puzzle.solution_for_delegated_puzzle(
                Program.from_bytes(hexstr_to_bytes(solution_dict["delegated_puzzle"])),
                Program.from_bytes(hexstr_to_bytes(solution_dict["solution"])),
            )


class CATPuzzle:
    @staticmethod
    def match(puzzle: Program, compressor: "PuzzleCompressor") -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        uncurried_mod, curried_args = puzzle.uncurry()
        if CC_MOD == uncurried_mod:
            tail_hash = curried_args.rest().first()
            innerpuz = curried_args.rest().rest().first()
            _, matched_inner = compressor.match_puzzle(innerpuz)
            return True, [tail_hash, matched_inner]
        else:
            return False, []

    @staticmethod
    def construct(driver_dict, args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        assert isinstance(args[0], Program)
        innerpuz = args[1]
        if isinstance(args[1], PuzzleRepresentation):
            innerpuz = args[1].construct(driver_dict)
        return CC_MOD.curry(CC_MOD.get_tree_hash(), args[0].as_python(), innerpuz)

    @staticmethod
    def solve(driver_dict, args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        # TODO: implement this
        return Program.to([])


class OfferPuzzle:
    @staticmethod
    def match(puzzle: Program, compressor: "PuzzleCompressor") -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        if OFFER_MOD == puzzle:
            return True, []
        else:
            return False, []

    @staticmethod
    def construct(driver_dict, args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        return OFFER_MOD

    @staticmethod
    def solve(driver_dict, args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        # TODO: implement this
        return Program.to([])


"""
Below is a dictionary that contains version numbers mapped to dictionaries of identifiers mapped to puzzle drivers.
The idea is that specifying a compression version will determine what puzzles you can interpret.
All version numbers will support all versions lower than themselves to ensure backwards compatibility.
It's a dict with numbers as the keys rather than a list to be clear that the order needs to be preserved.
"""

HASH_TO_DRIVER: Dict[uint16, Dict[bytes32, Any]] = {
    uint16(0): {
        standard_puzzle.MOD.get_tree_hash(): StandardPuzzle,
        CC_MOD.get_tree_hash(): CATPuzzle,
        OFFER_MOD.get_tree_hash(): OfferPuzzle,
    }
    # TODO: Add version tests when there are more versions :)
}

LATEST_VERSION: uint16 = uint16(max(HASH_TO_DRIVER.keys()))

class CompressionVersionError(Exception):
    pass

class PuzzleCompressor:
    """
    This class represents an instance of the global HASH_TO_DRIVER map above.

    You can either specify a version number which will use the identifiers that are defined up to that version,
    or you can specify an entirely custom dictionary of drivers that is not a valid version.
    """

    version_number: uint16
    driver_dict: Dict[bytes32, Any]

    def __init__(self, version: uint16 = LATEST_VERSION, driver_dict: Dict[bytes32, Any] = None):
        if driver_dict is None:
            assert version in HASH_TO_DRIVER.keys()
            self.version_number = uint16(version)
            final_dict: Dict[bytes32, Any] = {}
            for key in range(0, version + 1):
                final_dict = final_dict | HASH_TO_DRIVER[uint16(key)]
            self.driver_dict = final_dict
        else:
            self.version_number = uint16(65535)  # Just set it to max so it always passes any version checks
            self.driver_dict = driver_dict

    def match_puzzle(self, puzzle: Program) -> Tuple[bool, Union[PuzzleRepresentation, Program]]:
        for identifier, driver in self.driver_dict.items():
            matched, args = driver.match(puzzle, self)
            if matched:
                return True, PuzzleRepresentation(identifier, args)
        return False, puzzle

    def serialize(self, puzzle: Program) -> bytes:
        _, rep = self.match_puzzle(puzzle)
        return bytes(self.version_number) + bytes(rep)

    def deserialize(self, object_bytes: bytes) -> Program:
        if int.from_bytes(object_bytes[0:2], "big") > self.version_number:
            raise CompressionVersionError()
        else:
            deversioned_bytes = object_bytes[2:]
            try:
                program = PuzzleRepresentation.from_bytes(deversioned_bytes).construct(self.driver_dict)
            except Exception:
                program = Program.from_bytes(deversioned_bytes)
            return program

    @classmethod
    def get_identifier_version(cls, identifier: bytes32) -> "PuzzleCompressor":
        for id, driver_dict in HASH_TO_DRIVER.items():
            if identifier in driver_dict:
                return cls(id)
        raise ValueError("The given identifier does not have a puzzle driver mapping")

    @classmethod
    def lowest_compatible_version(
        cls, matched_puzzles: List[Union[PuzzleRepresentation, Program]]
    ) -> "PuzzleCompressor":
        highest_version = uint16(0)
        for puz in matched_puzzles:
            if isinstance(puz, PuzzleRepresentation):
                highest_version = uint16(
                    max(
                        highest_version,
                        cls.get_identifier_version(puz.base).version_number,
                        cls.lowest_compatible_version(puz.args).version_number,
                    )
                )
        return cls(highest_version)