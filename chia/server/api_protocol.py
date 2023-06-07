from __future__ import annotations

from typing_extensions import Protocol


class ApiProtocol(Protocol):
    @property
    def api_ready(self) -> bool:
        ...
