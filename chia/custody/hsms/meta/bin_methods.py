import io

from typing import Any

from .hexbytes import hexbytes


class bin_methods:
    """
    Create "from_bytes" and "__bytes__" methods in terms of "parse" and "stream" methods.
    """

    @classmethod
    def from_bytes(cls, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)

    def __bytes__(self) -> hexbytes:
        f = io.BytesIO()
        self.stream(f)
        return hexbytes(f.getvalue())
