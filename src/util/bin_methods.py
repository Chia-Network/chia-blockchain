import io

from typing import Any


class BinMethods:
    """
    Create "from_bytes" and "serialize" methods in terms of "parse" and "stream" methods.
    """
    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)

    def serialize(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())
