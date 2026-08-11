from __future__ import annotations

import pytest
from chia_rs.sized_ints import uint32

from chia.full_node.full_node_api import ses_intervals_for_range


@pytest.mark.parametrize(
    "ses_heights, start, end, expected",
    [
        # Too few SES entries → empty.
        ([], 10, 20, []),
        ([100], 50, 150, []),
        # start before the first SES height.
        ([100, 200, 300, 400], 50, 150, []),
        # start after the last SES height.
        ([100, 200, 300, 400], 400, 500, []),
        ([100, 200, 300, 400], 500, 600, []),
        # Entire request inside one SES interval.
        ([100, 200, 300, 400], 100, 150, [(100, 200)]),
        ([100, 200, 300, 400], 150, 199, [(100, 200)]),
        # end on the next boundary is treated as spanning (strict upper bound).
        ([100, 200, 300, 400], 150, 200, [(100, 200), (200, 300)]),
        # Request spans two SES intervals.
        ([100, 200, 300, 400], 150, 250, [(100, 200), (200, 300)]),
        # start exactly on an SES boundary.
        ([100, 200, 300, 400], 200, 250, [(200, 300)]),
        ([100, 200, 300, 400], 200, 350, [(200, 300), (300, 400)]),
        # Last interval: cannot append a following SES even if end is past it.
        ([100, 200, 300, 400], 350, 999, [(300, 400)]),
    ],
    ids=[
        "empty_heights",
        "single_height",
        "before_first",
        "at_last_height",
        "after_last",
        "first_interval_at_start",
        "first_interval_interior",
        "end_on_next_boundary_spans",
        "spans_two",
        "on_boundary_same_interval",
        "on_boundary_spans",
        "last_interval_only",
    ],
)
def test_ses_intervals_for_range(
    ses_heights: list[int],
    start: int,
    end: int,
    expected: list[tuple[int, int]],
) -> None:
    result = ses_intervals_for_range(
        [uint32(h) for h in ses_heights],
        uint32(start),
        uint32(end),
    )
    assert [(int(a), int(b)) for a, b in result] == expected
