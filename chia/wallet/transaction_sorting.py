import enum


class SortKey(str, enum.Enum):
    # "?" will be mapped to either ASC or DESC (when reverse is set to true)
    CONFIRMED_AT_HEIGHT = "order by confirmed_at_height ASC"
    RELEVANCE = "order by confirmed ASC, confirmed_at_height DESC, created_at_time DESC"

    @staticmethod
    def reverse(query: str) -> str:
        reversed_query = query.replace("ASC", "TEMP")
        reversed_query = reversed_query.replace("DESC", "ASC")
        reversed_query = reversed_query.replace("TEMP", "DESC")
        return reversed_query
