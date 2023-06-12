from __future__ import annotations

from typing_extensions import Protocol


class ApiProtocol(Protocol):
    def ready(self) -> bool:
        ...
