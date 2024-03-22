from __future__ import annotations

from dataclasses import dataclass

import pytest

from chia._tests.util.misc import Marks, datacases, named_datacases


@dataclass
class DataCase:
    id: str
    marks: Marks


sample_cases = [
    DataCase(id="id_a", marks=[pytest.mark.test_mark_a1, pytest.mark.test_mark_a2]),
    DataCase(id="id_b", marks=[pytest.mark.test_mark_b1, pytest.mark.test_mark_b2]),
]


def sample_result(name: str) -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        argnames=name,
        argvalues=[pytest.param(case, id=case.id, marks=case.marks) for case in sample_cases],
    )


def test_datacases() -> None:
    result = datacases(*sample_cases)

    assert result == sample_result(name="case")


def test_named_datacases() -> None:
    result = named_datacases("Sharrilanda")(*sample_cases)

    assert result == sample_result(name="Sharrilanda")
