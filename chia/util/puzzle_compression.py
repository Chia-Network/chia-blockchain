from typing import Dict, Tuple, List, Union, Any

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

from chia.util.ints import uint16, uint32

# These imports should be temporary
from blspy import G1Element
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle as standard_puzzle
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

OFFER_MOD = load_clvm("settlement_payments.clvm")


class PuzzleRepresentation:
    """
    This class is intended to be vehicle for compression and serialization of an arbitrary configuration of
    "outer" and "inner" puzzles.  This can act as a generalized "driver" for an arbitrary puzle.
    The idea is that you make a complex stack of puzzles, represent it with this class, and then you don't have
    to worry about writing a whole new driver file for your unique stack, you can instead rely on the component
    drivers to work together as if it were a driver for the whole puzzle.
    """

    base: bytes32
    args: List[Union["PuzzleRepresentation", Program]]

    def __init__(self, base, args):
        self.base = base
        self.args = args

    def construct(self) -> Program:
        driver = KnownPuzzles.get_driver(self.base)
        return driver.construct(self.args)

    def solve(self, solution_dict: Dict[str, str]) -> Program:
        driver = KnownPuzzles.get_driver(self.base)
        return driver.solve(self.args, solution_dict)

    @classmethod
    def parse(cls, f) -> "PuzzleRepresentation":
        blob_len = int.from_bytes(f.read(4), "big")  # It's a uint32 so we read 4 bytes
        blob = f.read(blob_len)
        return cls.from_bytes(blob)

    def stream(self, f):
        blob = bytes(self)
        prefixed_blob = bytes.fromhex(bytes(uint32(len(blob))).hex() + blob.hex())
        f.write(prefixed_blob)

    def __bytes__(self) -> bytes:
        total_bytes = self.base.hex()
        for arg in self.args:
            byte_output = bytes(arg)
            if type(arg) == type(self):
                total_bytes += "00"
            else:
                total_bytes += "01"
            total_bytes += bytes(uint32(len(byte_output))).hex()
            total_bytes += byte_output.hex()
        return bytes.fromhex(total_bytes)

    @classmethod
    def from_bytes(cls, as_bytes: bytes) -> "PuzzleRepresentation":
        as_hex = as_bytes.hex()
        base = bytes32(bytes.fromhex(as_hex[0:64]))
        as_hex = as_hex[64:]
        args = []
        while as_hex != "":
            num_bytes = int.from_bytes(bytes.fromhex(as_hex[2:10]), "big")
            end_index = 10 + num_bytes * 2
            next_bytes = bytes.fromhex(as_hex[10:end_index])
            if as_hex[0:2] == "00":
                args.append(cls.from_bytes(next_bytes))
            else:
                args.append(Program.from_bytes(next_bytes))
            as_hex = as_hex[end_index:]

        return cls(base, args)


"""
The following are example classes.
Ideally, all of our current driver code would be put into a puzzle driver class and registered with the KnownPuzzles
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
    def match(puzzle: Program) -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        uncurried_mod, curried_args = puzzle.uncurry()
        if standard_puzzle.MOD == uncurried_mod:
            synthetic_pubkey = curried_args.first()
            return True, [synthetic_pubkey]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        return standard_puzzle.MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
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
    def match(puzzle: Program) -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        uncurried_mod, curried_args = puzzle.uncurry()
        if CC_MOD == uncurried_mod:
            tail_hash = curried_args.rest().first()
            innerpuz = curried_args.rest().rest().first()
            _, matched_inner = KnownPuzzles.match_puzzle(innerpuz)
            return True, [tail_hash, matched_inner]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        assert isinstance(args[0], Program)
        innerpuz = args[1]
        if isinstance(args[1], PuzzleRepresentation):
            innerpuz = args[1].construct()
        return CC_MOD.curry(CC_MOD.get_tree_hash(), args[0].as_python(), innerpuz)

    @staticmethod
    def solve(args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        # TODO: implement this
        return Program.to([])


class OfferPuzzle:
    @staticmethod
    def match(puzzle: Program) -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        if OFFER_MOD == puzzle:
            return True, []
        else:
            return False, []

    @staticmethod
    def construct(args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        return OFFER_MOD

    @staticmethod
    def solve(args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        # TODO: implement this
        return Program.to([])


class CompressionVersionError(Exception):
    pass

"""
This may not need to be a class, it was just how I conceived of it.
All known puzzle drivers should get registered to this object, and then they can be retrieved or
searched through as necessary.
"""


class KnownPuzzles:
    version: uint16 = 1  # This needs to be incremented whenever the map below changes
    map: Dict[bytes32, Any] = {
        standard_puzzle.MOD.get_tree_hash(): StandardPuzzle,
        CC_MOD.get_tree_hash(): CATPuzzle,
        OFFER_MOD.get_tree_hash(): OfferPuzzle,
    }

    @classmethod
    def get_driver(cls, identifier: bytes32) -> Any:
        return cls.map[identifier]

    @classmethod
    def match_puzzle(cls, puzzle: Program) -> Tuple[bool, Union[PuzzleRepresentation, Program]]:
        for identifier, driver in cls.map.items():
            matched, args = driver.match(puzzle)
            if matched:
                return True, PuzzleRepresentation(identifier, args)
        return False, puzzle

    @classmethod
    def serialize_and_version(cls, rep: Union[PuzzleRepresentation, Program]) -> bytes:
        return bytes(uint16(cls.version)) + bytes(rep)

    @classmethod
    def check_version(cls, object_bytes: bytes) -> bytes:
        if int.from_bytes(object_bytes[0:2], "big") > cls.version:
            raise CompressionVersionError()
        else:
            return object_bytes[2:]
