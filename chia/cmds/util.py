from __future__ import annotations

import dataclasses
import pathlib
from typing import ClassVar, Optional, cast, final

import click

from chia.util.default_root import DEFAULT_ROOT_PATH


@final
@dataclasses.dataclass
class ChiaCliContext:
    context_dict_key: ClassVar[str] = "_chia_cli_context"

    root_path: pathlib.Path = DEFAULT_ROOT_PATH
    expected_prefix: Optional[str] = None
    rpc_port: Optional[int] = None

    @classmethod
    def from_click(cls, ctx: click.Context) -> ChiaCliContext:
        if ctx.obj is None:
            return cls()

        existing = cast(Optional[ChiaCliContext], ctx.obj.get(cls.context_dict_key))
        if existing is None:
            return cls()

        return existing

    def to_click(self) -> dict[str, object]:
        return {self.context_dict_key: self}
