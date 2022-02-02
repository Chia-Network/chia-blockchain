from math import ceil

import pytest

from chia.util.paginator import InvalidPageSizeError, PageOutOfBoundsError, Paginator


def test_constructor() -> None:
    for i in range(0, Paginator.page_sizes[-1] + 1):
        if i in Paginator.page_sizes:
            paginator: Paginator = Paginator([], i)
            assert paginator.page_size() == i
            assert paginator.page_count() == 1
            assert paginator.get_page(1) == []


def test_page_count() -> None:
    source = [i for i in range(0, Paginator.page_sizes[-1])]
    for page_size in Paginator.page_sizes:
        for i in range(0, len(source)):
            paginator: Paginator = Paginator(source[0:i], page_size)
            assert paginator.page_count() == max(1, ceil(i / page_size))


def test_get_page() -> None:
    # Empty source should lead to an empty first page
    assert Paginator([], 5).get_page(1) == []
    # Validate all pages are as expected
    source = [i for i in range(0, 17)]
    paginator: Paginator = Paginator(source, 5)
    assert paginator.get_page(1) == [0, 1, 2, 3, 4]
    assert paginator.get_page(2) == [5, 6, 7, 8, 9]
    assert paginator.get_page(3) == [10, 11, 12, 13, 14]
    assert paginator.get_page(4) == [15, 16]


def test_exceptions() -> None:
    source = [i for i in range(0, 17)]
    paginator: Paginator = Paginator(source, 5)
    with pytest.raises(PageOutOfBoundsError):
        paginator.get_page(-1)
    with pytest.raises(PageOutOfBoundsError):
        paginator.get_page(0)
    with pytest.raises(PageOutOfBoundsError):
        paginator.get_page(paginator.page_count() + 1)
    for i in range(0, Paginator.page_sizes[-1] + 1):
        if i not in Paginator.page_sizes:
            with pytest.raises(InvalidPageSizeError):
                Paginator([0], i)
