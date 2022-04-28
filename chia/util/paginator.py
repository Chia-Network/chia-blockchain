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
        super().__init__(f"Page {page_size} out of bounds. Available pages: 1-{max_page_size}")


@dataclasses.dataclass
class Paginator:
    _source: Sequence[object]
    _page_size: int
    _page_size_limit: int = 100

    def __post_init__(self) -> None:
        if self._page_size_limit < 1:
            raise InvalidPageSizeLimit(self._page_size_limit)
        if self._page_size > self._page_size_limit:
            raise InvalidPageSizeError(self._page_size, self._page_size_limit)

    def page_size(self) -> int:
        return self._page_size

    def page_size_limit(self) -> int:
        return self._page_size_limit

    def page_count(self) -> int:
        return max(1, ceil(len(self._source) / self._page_size))

    def get_page(self, page: int) -> Sequence[object]:
        if page <= 0 or page > self.page_count():
            raise PageOutOfBoundsError(page, self.page_count())
        offset = (page - 1) * self._page_size
        return self._source[offset : offset + self._page_size]
