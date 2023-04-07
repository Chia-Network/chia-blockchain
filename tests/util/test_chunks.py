from __future__ import annotations

from chia.util.chunks import chunks


def test_chunks() -> None:
    assert list(chunks([], 0)) == []
    assert list(chunks(["a"], 0)) == [["a"]]
    assert list(chunks(["a", "b"], 0)) == [["a"], ["b"]]

    assert list(chunks(["a", "b", "c", "d"], -1)) == [["a"], ["b"], ["c"], ["d"]]
    assert list(chunks(["a", "b", "c", "d"], 0)) == [["a"], ["b"], ["c"], ["d"]]
    assert list(chunks(["a", "b", "c", "d"], 1)) == [["a"], ["b"], ["c"], ["d"]]
    assert list(chunks(["a", "b", "c", "d"], 2)) == [["a", "b"], ["c", "d"]]
    assert list(chunks(["a", "b", "c", "d"], 3)) == [["a", "b", "c"], ["d"]]
    assert list(chunks(["a", "b", "c", "d"], 4)) == [["a", "b", "c", "d"]]
    assert list(chunks(["a", "b", "c", "d"], 200)) == [["a", "b", "c", "d"]]
