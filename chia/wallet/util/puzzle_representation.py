from typing import Dict, List, Union

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

from chia.util.ints import uint32


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

    def construct(self, driver_dict) -> Program:
        driver = driver_dict[self.base]
        return driver.construct(driver_dict, self.args)

    def solve(self, driver_dict, solution_dict: Dict[str, str]) -> Program:
        driver = driver_dict[self.base]
        return driver.solve(driver_dict, self.args, solution_dict)

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
