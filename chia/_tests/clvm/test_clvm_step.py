from __future__ import annotations

from typing import Any, Optional

from clvm_tools_rs import start_clvm_program

factorial = (
    "ff02ffff01ff02ff02ffff04ff02ffff04ff05ff80808080ffff04ffff01ff02"
    + "ffff03ffff09ff05ffff010180ffff01ff0101ffff01ff12ff05ffff02ff02ff"
    + "ff04ff02ffff04ffff11ff05ffff010180ff808080808080ff0180ff018080"
)

factorial_function_hash = "de3687023fa0a095d65396f59415a859dd46fc84ed00504bf4c9724fca08c9de"
factorial_sym = {factorial_function_hash: "factorial"}


def test_simple_program_run() -> None:
    p = start_clvm_program(factorial, "ff0580", factorial_sym)

    last: Optional[Any] = None
    location: Optional[Any] = None

    while not p.is_ended():
        step_result = p.step()
        if step_result is not None:
            last = step_result
            assert "Failure" not in last

            if "Operator-Location" in last:
                location = last["Operator-Location"]

    assert last is not None
    assert location is not None
    if last is not None and location is not None:
        assert "Final" in last
        assert int(last["Final"]) == 120
        assert location.startswith("factorial")
