import asyncio

from dataclasses import dataclass
from typing import Type


@dataclass
class Response:
    future: asyncio.Future
    return_type: Type

    def __hash__(self):
        return id(self)
