import pytest

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver

def test_puzzle_info():
    test_driver = {
        "string": "hello",
        "bytes": "0xcafef00d",
        "int": "123",
        "program": "(q . 'hello')",
        "zero": "0",
        "nil": "()",
    }
    test_also = {
        "type": "TEST",
        "string": "hello"
    }
    test_driver["also"] = test_also

    with pytest.raises(ValueError, match="A type is required"):
        PuzzleInfo(test_driver)
    solver = Solver(test_driver)

    test_driver["type"] = "TEST"
    puzzle_info = PuzzleInfo(test_driver)

    assert puzzle_info.also() == PuzzleInfo(test_also)

    for obj in (puzzle_info, solver):
        assert obj["string"] == "hello"
        assert obj["bytes"] == bytes.fromhex("cafef00d")
        assert obj["int"] == 123
        assert obj["program"] == Program.to((1, "hello"))
        assert obj["zero"] == 0
        assert obj["nil"] == Program.to([])