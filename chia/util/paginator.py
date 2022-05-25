from __future__ import annotations

import dataclasses
from math import ceil
from typing import Sequence


class InvalidPageSizeLimit(Exception):
    def __init__(self, page_size_limit: int) -> None:
        super().__init__(f"Page size limit must be one or more, not: {page_size_limit}")


class InvalidPageSizeError(Exception):
    def __init__(self, page_size: int, page_size_limit: int) -> None:
        super().__init__(f"Invalid page size {page_size}. Must be between: 1 and {page_size_limit}")


class PageOutOfBoundsError(Exception):
    def __init__(self, page_size: int, max_page_size: int) -> None:
        super().__init__(f"Page {page_size} out of bounds. Available pages: 0-{max_page_size}")


@dataclasses.dataclass
class Paginator:
    _source: Sequence[object]
    _page_size: int

    @classmethod
    def create(cls, source: Sequence[object], page_size: int, page_size_limit: int = 100) -> Paginator:
        if page_size_limit < 1:
            raise InvalidPageSizeLimit(page_size_limit)
        if page_size > page_size_limit:
            raise InvalidPageSizeError(page_size, page_size_limit)
        return cls(source, page_size)

    def page_size(self) -> int:
        return self._page_size

    def page_count(self) -> int:
        return max(1, ceil(len(self._source) / self._page_size))

    def get_page(self, page: int) -> Sequence[object]:
        if page < 0 or page >= self.page_count():
            raise PageOutOfBoundsError(page, self.page_count() - 1)
        offset = page * self._page_size
        return self._source[offset : offset + self._page_size]
