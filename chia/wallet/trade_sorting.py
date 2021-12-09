import enum


class SortKey(enum.Enum):
    CREATED_AT_TIME = "order by created_at_time {DESC}"
    RELEVANCE = "order by status {ASC}, confirmed_at_index {DESC}, created_at_time {DESC}"

    def ascending(self) -> str:
        return self.value.format(ASC="ASC", DESC="DESC")

    def descending(self) -> str:
        return self.value.format(ASC="DESC", DESC="ASC")
