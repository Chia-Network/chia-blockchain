from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Optional

from chia._tests.util.misc import Marks, datacases
from chia.util.layered_dict import LayeredDict


@dataclass
class Case:
    dicts: list[MutableMapping[str, Any]]
    path: list[str]
    expected: object
    id: str
    set_value: Optional[object] = None
    marks: Marks = ()


@datacases(
    Case(dicts=[{"a": 1}, {"a": 2}], path=["a"], expected=1, id="first one layer"),
    Case(dicts=[{"a": {"b": 1}}, {"a": {"b": 2}}], path=["a", "b"], expected=1, id="first two layers"),
    Case(
        dicts=[{"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "c"],
        expected=1,
        id="first three layers",
    ),
    Case(dicts=[{}, {"a": 2}], path=["a"], expected=2, id="fall through first layer"),
    Case(dicts=[{"a": {}}, {"a": {"b": 2}}], path=["a", "b"], expected=2, id="fall through second layer"),
    Case(
        dicts=[{"a": {"b": {}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "c"],
        expected=2,
        id="fall through third layer",
    ),
    Case(dicts=[{}, {"a": {"b": 2}}], path=["a", "b"], expected=2, id="fall through partial path"),
)
def test_indexing(case: Case) -> None:
    layered_dict = LayeredDict(dicts=case.dicts, path=[])

    assert case.set_value is None

    child = layered_dict
    for key in case.path:
        print(child)
        child = child[key]

    assert child == case.expected


@datacases(
    Case(
        dicts=[{"a": {"b": {}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "c"],
        expected=2,
        id="get returns value when present",
    ),
    Case(
        dicts=[{"a": {}}, {"a": {"b": {}}}],
        path=["a", "b", "c"],
        expected=None,
        id="get returns default when not present",
    ),
)
def test_get(case: Case) -> None:
    layered_dict = LayeredDict(dicts=case.dicts, path=[])

    child = layered_dict
    for key in case.path[:-1]:
        print(child)
        child = child[key]
    print(child)

    assert child.get(case.path[-1]) == case.expected


@datacases(
    Case(dicts=[{}, {"a": 2}], path=["a"], expected=3, set_value=3, id="set first layer"),
    Case(dicts=[{"a": {}}, {"a": {"b": 2}}], path=["a", "b"], expected=3, set_value=3, id="set second layer"),
    Case(
        dicts=[{"a": {"b": {}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "c"],
        expected=3,
        set_value=3,
        id="set third layer",
    ),
)
def test_assignment(case: Case) -> None:
    layered_dict = LayeredDict(dicts=case.dicts, path=[])

    assert case.set_value is not None

    child = layered_dict
    for key in case.path[:-1]:
        child = child[key]
    child[case.path[-1]] = case.set_value

    child = layered_dict
    for key in case.path:
        print(child)
        child = child[key]

    assert child == case.expected


@datacases(
    Case(dicts=[{}, {"a": 2}], path=["a"], expected=2, set_value=3, id="already set first layer"),
    Case(dicts=[{"a": {}}, {"a": {"b": 2}}], path=["a", "b"], expected=2, set_value=3, id="already set second layer"),
    Case(
        dicts=[{"a": {"b": {}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "c"],
        expected=2,
        set_value=3,
        id="already set third layer",
    ),
    Case(dicts=[{}, {"a": 2}], path=["b"], expected=3, set_value=3, id="not preset first layer"),
    Case(dicts=[{"a": {}}, {"a": {"b": 2}}], path=["a", "c"], expected=3, set_value=3, id="not preset second layer"),
    Case(
        dicts=[{"a": {"b": {}}}, {"a": {"b": {"c": 2}}}],
        path=["a", "b", "d"],
        expected=3,
        set_value=3,
        id="not preset third layer",
    ),
)
def test_setdefault(case: Case) -> None:
    layered_dict = LayeredDict(dicts=case.dicts, path=[])

    assert case.set_value is not None

    child = layered_dict
    for key in case.path[:-1]:
        child = child[key]
    result = child.setdefault(case.path[-1], case.set_value)
    indexed = child[case.path[-1]]

    assert result == case.expected
    assert result is indexed
