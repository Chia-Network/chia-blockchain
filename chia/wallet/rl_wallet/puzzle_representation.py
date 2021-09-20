from typing import Dict, Tuple, List, Union
from enum import IntEnum

from chia.types.blockchain_format.program import Program

from chia.util.ints import uint8, uint32

# These imports should be temporary
from blspy import G1Element
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle as standard_puzzle
from chia.clvm.singletons import singleton_drivers as singletons

class PuzzleIdentifier(IntEnum):
    STANDARD_PUZZLE = 1
    NO_TRUTHS_WRAPPER = 2

class PuzzleRepresentation:
    '''
    This class is intended to be vehicle for compression and serialization of an arbitrary configuration of
    "outer" and "inner" puzzles.  This can be included as a member object on Streamable, as well as act as a
    generalized "driver" for an arbitrary puzle.

    The idea is that you make a complex stack of puzzles, represent it with this class, and then you don't have
    to worry about writing a whole new driver file for your unique stack, you can instead rely on the component
    drivers to work together as if it were a driver for the whole puzzle.
    '''
    base: PuzzleIdentifier
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
        blob_len = int.from_bytes(f.read(4), "big") # It's a uint32 so we read 4 bytes
        blob = f.read(blob_len)
        return cls.from_bytes(blob)

    def stream(self, f):
        blob = bytes(self)
        prefixed_blob = bytes.fromhex(bytes(uint32(len(blob))).hex() + blob.hex())
        f.write(prefixed_blob)

    def __bytes__(self) -> bytes:
        total_bytes = bytes(uint8(self.base)).hex()
        for arg in self.args:
            byte_output = bytes(arg)
            if type(arg) == type(self):
                total_bytes += '00'
            else:
                total_bytes += '01'
            total_bytes += bytes(uint32(len(byte_output))).hex()
            total_bytes += byte_output.hex()
        return bytes.fromhex(total_bytes)

    @classmethod
    def from_bytes(cls, as_bytes: bytes) -> "PuzzleRepresentation":
        as_hex = as_bytes.hex()
        base = PuzzleIdentifier(int.from_bytes(bytes.fromhex(as_hex[0:2]), "big"))
        as_hex = as_hex[2:]
        args = []
        while as_hex != "":
            num_bytes = int.from_bytes(bytes.fromhex(as_hex[2:10]), "big")
            end_index = (10 + num_bytes*2)
            next_bytes = bytes.fromhex(as_hex[10:end_index])
            if as_hex[0:2] == '00':
                args.append(cls.from_bytes(next_bytes))
            else:
                args.append(Program.from_bytes(next_bytes))
            as_hex = as_hex[end_index:]

        return cls(base, args)

# This should be a super class for component puzzle drivers and is purely for typing purposes
class PuzzleDriver():
    pass

'''
The following two classes are example classes.

Ideally, all of our current driver code would be put into a PuzzleDriver class and registered with the KnownPuzzles
structure below.  They must all have three methods implemented:
- match: Take the result of a uncurry() call and return the relevant list of args that will be put into the
         PuzzleRepresentation. (The criteria for this list of args is that you should be able to fully construct
         the puzzle with them, which is the next function)

- construct: Receive a list of args from a PuzzleRepresentation and construct a full puzzle reveal

- solve: Receive an opaque piece of JSON, and return a solution reveal.  The reason this argument is an opaque piece
         of JSON is because the api needs to be the same for all drivers, but obviously all programs will need unique
         arguments for their solution.  This makes it potentially easy for a UI to craft this as a field on a request
         which the wallet can blindly hand to the driver it has, and recieve a solution to build the spend with.
'''
class StandardPuzzle(PuzzleDriver):
    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
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
            assert all(arg in solution_dict for arg in ["delegated_puzzle","solution"])
            return standard_puzzle.solution_for_delegated_puzzle(
                Program.from_bytes(hexstr_to_bytes(solution_dict["delegated_puzzle"])),
                Program.from_bytes(hexstr_to_bytes(solution_dict["solution"])),
            )


class NoTruthsWrapper(PuzzleDriver):
    '''
    This class shows that you are not necessarily building PuzzleRepresentations from curried args, it could be anything
    like an inner puzzle that it needs to "wrap"
    '''
    @staticmethod
    def match(uncurried_mod: Program, args: Program) -> Tuple[bool, List[Union[PuzzleRepresentation, Program]]]:
        if (uncurried_mod.first() == Program.to(2)) and (uncurried_mod.rest().rest().first() == Program.to([6, 1])):
            inner_puz = uncurried_mod.rest().first().rest()
            _, inner_puz_rep = KnownPuzzles.match_puzzle(inner_puz)
            return True, [inner_puz_rep]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Union[PuzzleRepresentation, Program]]) -> Program:
        return singletons.adapt_inner_to_singleton(args[0].construct())

    @staticmethod
    def solve(args: List[Union[PuzzleRepresentation, Program]], solution_dict: Dict[str, str]) -> Program:
        return args[0].solve(solution_dict)

'''
This may not need to be a class, it was just how I conceived of it.
All known puzzle drivers should get registered to this object, and then they can be retrieved or
searched through as necessary.
'''
class KnownPuzzles:
    map: Dict[PuzzleIdentifier, PuzzleDriver] = {
        PuzzleIdentifier.STANDARD_PUZZLE: StandardPuzzle,
        PuzzleIdentifier.NO_TRUTHS_WRAPPER: NoTruthsWrapper,
    }

    @classmethod
    def get_driver(cls, identifier: PuzzleIdentifier) -> PuzzleDriver:
        return cls.map[identifier]

    @classmethod
    def match_puzzle(cls, puzzle: Program) -> Tuple[bool, Union[PuzzleRepresentation, Program]]:
        uncurried_mod, curried_args = puzzle.uncurry()
        for identifier, driver in cls.map.items():
            matched, args = driver.match(uncurried_mod, curried_args)
            if matched:
                return True, PuzzleRepresentation(identifier, args)
        return False,puzzle