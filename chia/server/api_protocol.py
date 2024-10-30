from __future__ import annotations

from collections.abc import Mapping
from logging import Logger
from typing import Callable, ClassVar

from typing_extensions import Protocol

ApiMethods = Mapping[str, Callable[..., object]]


class ApiProtocol(Protocol):
    log: Logger
    api_methods: ClassVar[ApiMethods]

    def ready(self) -> bool: ...
