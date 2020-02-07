import io

from typing import Any


class bin_methods:
    """
    Create "from_bytes" and "__bytes__" methods in terms of "parse" and "stream" methods.
    """

    @classmethod
    def from_bytes(cls, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)  # type: ignore # noqa

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # type: ignore # noqa
        return f.getvalue()
