from dataclasses import dataclass
from typing import Dict, List, Union, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

from chia.util.ints import uint32


@dataclass(frozen=True)
class PuzzleRepresentation:
    """
    This class is intended to be vehicle for compression and serialization of an arbitrary configuration of
    "outer" and "inner" puzzles.  This can act as a generalized "driver" for an arbitrary puzle.
    The idea is that you make a complex stack of puzzles, represent it with this class, and then you don't have
    to worry about writing a whole new driver file for your unique stack, you can instead rely on the component
    drivers to work together as if it were a driver for the whole puzzle.
    """

    base: Optional[bytes32]
    args: Union[Program, List["PuzzleRepresentation"]]

    def construct(self, driver_dict) -> Program:
        if self.base is None:
            assert isinstance(self.args, Program)
            return self.args
        else:
            driver = driver_dict[self.base]
            return driver.construct(driver_dict, self.args)

    def solve(self, driver_dict, solution_dict: Dict[str, str]) -> Program:
        if self.base is None:
            assert "solution" in solution_dict
            return Program.fromhex(solution_dict["solution"])
        else:
            driver = driver_dict[self.base]
            return driver.solve(driver_dict, self.args, solution_dict)

    @classmethod
    def parse(cls, f) -> "PuzzleRepresentation":
        blob_len = int.from_bytes(f.read(4), "big")  # It's a uint32 so we read 4 bytes
        blob = f.read(blob_len)
        return cls.from_bytes(blob)

    def stream(self, f):
        blob = bytes(self)
        prefixed_blob = bytes(uint32(len(blob))) + blob
        f.write(prefixed_blob)

    def __bytes__(self) -> bytes:
        if self.base is None:
            total_bytes = b"\x00"
            assert isinstance(self.args, Program)
            arg_list: List[Union[Program, PuzzleRepresentation]] = [self.args]
        else:
            total_bytes = b"\x01" + self.base
            arg_list = self.args
        for arg in arg_list:
            byte_output = arg.__bytes__()
            total_bytes += bytes(uint32(len(byte_output)))
            total_bytes += byte_output
        return total_bytes

    @classmethod
    def from_bytes(cls, as_bytes: bytes) -> "PuzzleRepresentation":
        base = None if as_bytes[0:1] == b"\x00" else bytes32(as_bytes[1:33])
        arg_bytes = as_bytes[1:] if base is None else as_bytes[33:]
        args: Union[Program, List["PuzzleRepresentation"]] = []
        while arg_bytes != b"":
            num_bytes = int.from_bytes(arg_bytes[0:4], "big")
            end_index = 4 + num_bytes
            next_bytes = arg_bytes[4:end_index]
            if base is None:
                args = Program.from_bytes(next_bytes)
                break
            else:
                args.append(cls.from_bytes(next_bytes))
                arg_bytes = arg_bytes[end_index:]

        return cls(base, args)
