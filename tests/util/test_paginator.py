from __future__ import annotations

from math import ceil
from typing import List, Type

import pytest

from chia.util.paginator import InvalidPageSizeError, InvalidPageSizeLimit, PageOutOfBoundsError, Paginator


@pytest.mark.parametrize(
    "source, page_size, page_size_limit",
    [([], 1, 1), ([1], 1, 2), ([1, 2], 2, 2), ([], 10, 100), ([1, 2, 10], 1000, 1000)],
)
def test_constructor_valid_inputs(source: List[int], page_size: int, page_size_limit: int) -> None:
    paginator: Paginator = Paginator.create(source, page_size, page_size_limit)
    assert paginator.page_size() == page_size
    assert paginator.page_count() == 1
    assert paginator.get_page(0) == source


@pytest.mark.parametrize(
    "page_size, page_size_limit, exception",
    [
        (5, -1, InvalidPageSizeLimit),
        (5, 0, InvalidPageSizeLimit),
        (2, 1, InvalidPageSizeError),
        (100, 1, InvalidPageSizeError),
        (1001, 1000, InvalidPageSizeError),
    ],
)
def test_constructor_invalid_inputs(page_size: int, page_size_limit: int, exception: Type[Exception]) -> None:
    with pytest.raises(exception):
        Paginator.create([], page_size, page_size_limit)


def test_page_count() -> None:
    for page_size in range(1, 10):
        for i in range(0, 10):
            assert Paginator.create(range(0, i), page_size).page_count() == max(1, ceil(i / page_size))


@pytest.mark.parametrize(
    "length, page_size, page, expected_data",
    [
        (17, 5, 0, [0, 1, 2, 3, 4]),
        (17, 5, 1, [5, 6, 7, 8, 9]),
        (17, 5, 2, [10, 11, 12, 13, 14]),
        (17, 5, 3, [15, 16]),
        (3, 4, 0, [0, 1, 2]),
        (3, 3, 0, [0, 1, 2]),
        (3, 2, 0, [0, 1]),
        (3, 2, 1, [2]),
        (3, 1, 0, [0]),
        (3, 1, 1, [1]),
        (3, 1, 2, [2]),
        (2, 2, 0, [0, 1]),
        (2, 1, 0, [0]),
        (2, 1, 1, [1]),
        (1, 2, 0, [0]),
        (0, 2, 0, []),
        (0, 10, 0, []),
    ],
)
def test_get_page_valid(length: int, page: int, page_size: int, expected_data: List[int]) -> None:
    assert Paginator.create(list(range(0, length)), page_size).get_page(page) == expected_data


@pytest.mark.parametrize("page", [-1000, -10, -1, 5, 10, 1000])
def test_get_page_invalid(page: int) -> None:
    with pytest.raises(PageOutOfBoundsError):
        Paginator.create(range(0, 17), 5).get_page(page)
