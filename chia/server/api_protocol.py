from __future__ import annotations

from logging import Logger

from typing_extensions import Protocol


class ApiProtocol(Protocol):
    log: Logger

    def ready(self) -> bool:
        ...
