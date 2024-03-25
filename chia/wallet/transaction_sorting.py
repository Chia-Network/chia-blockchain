from __future__ import annotations

import enum


class SortKey(enum.Enum):
    CONFIRMED_AT_HEIGHT = "ORDER BY confirmed_at_height {ASC}"
    RELEVANCE = "ORDER BY confirmed {ASC}, confirmed_at_height {DESC}, created_at_time {DESC}"

    def ascending(self) -> str:
        return self.value.format(ASC="ASC", DESC="DESC")

    def descending(self) -> str:
        return self.value.format(ASC="DESC", DESC="ASC")
