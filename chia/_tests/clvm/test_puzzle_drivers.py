from __future__ import annotations

from typing import Any, Dict, Union

import pytest

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver


def test_puzzle_info() -> None:
    test_driver: Dict[str, Any] = {
        "string": "hello",
        "bytes": "0xcafef00d",
        "int": "123",
        "program": "(q . 'hello')",
        "zero": "0",
        "nil": "()",
    }
    test_also: Dict[str, Any] = {"type": "TEST", "string": "hello"}
    test_driver["also"] = test_also

    with pytest.raises(ValueError, match="A type is required"):
        PuzzleInfo(test_driver)
    solver = Solver(test_driver)

    test_driver["type"] = "TEST"
    puzzle_info = PuzzleInfo(test_driver)

    assert puzzle_info.type() == "TEST"
    assert puzzle_info.also() == PuzzleInfo(test_also)

    capitalize_bytes = test_driver.copy()
    capitalize_bytes["bytes"] = "0xCAFEF00D"
    assert solver == Solver(capitalize_bytes)
    assert puzzle_info == PuzzleInfo(capitalize_bytes)

    obj: Union[PuzzleInfo, Solver]
    for obj in (puzzle_info, solver):
        assert obj["string"] == "hello"
        assert obj["bytes"] == bytes.fromhex("cafef00d")
        assert obj["int"] == 123
        assert obj["program"] == Program.to((1, "hello"))
        assert obj["zero"] == 0
        assert obj["nil"] == Program.to([])
