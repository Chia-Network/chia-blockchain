import io

from typing import Any


class bin_methods:
    """
    Create "from_bin" and "as_bin" methods in terms of "parse" and "stream" methods.
    """
    @classmethod
    def from_bin(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)

    def as_bin(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())
