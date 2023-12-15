from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass, fields
from io import BytesIO
from typing import Any, BinaryIO, Callable, Dict, Iterator, Type, TypeVar

from hsms.clvm_serde import from_program_for_type, to_program_for_type
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import ConversionError, Streamable, streamable


@dataclass
class ClvmSerializationConfig:
    use: bool = False


class _ClvmSerializationMode:
    config = contextvars.ContextVar("config", default=threading.local())

    @classmethod
    def get_config(cls) -> ClvmSerializationConfig:
        return cls.config.get().config  # type: ignore[no-any-return]

    @classmethod
    def set_config(cls, config: ClvmSerializationConfig) -> None:
        cls.config.get().config = config


_ClvmSerializationMode.set_config(ClvmSerializationConfig())


@contextmanager
def clvm_serialization_mode(use: bool) -> Iterator[None]:
    old_config = _ClvmSerializationMode.get_config()
    _ClvmSerializationMode.set_config(ClvmSerializationConfig(use=use))
    yield
    _ClvmSerializationMode.set_config(old_config)


@dataclass_transform()
class ClvmStreamableMeta(type):
    def __init__(cls: ClvmStreamableMeta, *args: Any) -> None:
        if cls.__name__ == "ClvmStreamable":
            return
        # Not sure how to fix the hints here, but it works
        dcls: Type[ClvmStreamable] = streamable(dataclass(frozen=True)(cls))  # type: ignore[arg-type]
        # Iterate over the fields of the class
        for field_obj in fields(dcls):
            field_name = field_obj.name
            field_metadata = {"key": field_name}
            field_metadata.update(field_obj.metadata)
            setattr(field_obj, "metadata", field_metadata)
        setattr(dcls, "as_program", to_program_for_type(dcls))
        setattr(dcls, "from_program", lambda prog: from_program_for_type(dcls)(prog))
        super().__init__(*args)


_T_ClvmStreamable = TypeVar("_T_ClvmStreamable", bound="ClvmStreamable")


class ClvmStreamable(Streamable, metaclass=ClvmStreamableMeta):
    def as_program(self) -> Program:
        raise NotImplementedError()  # pragma: no cover

    @classmethod
    def from_program(cls: Type[_T_ClvmStreamable], prog: Program) -> _T_ClvmStreamable:
        raise NotImplementedError()  # pragma: no cover

    def stream(self, f: BinaryIO) -> None:
        if _ClvmSerializationMode.get_config().use:
            f.write(bytes(self.as_program()))
        else:
            super().stream(f)

    @classmethod
    def parse(cls: Type[_T_ClvmStreamable], f: BinaryIO) -> _T_ClvmStreamable:
        assert isinstance(f, BytesIO)
        try:
            result = cls.from_program(Program.from_bytes(bytes(f.getbuffer())))
            f.read()
            return result
        except Exception:
            return super().parse(f)

    def override_json_serialization(self, default_recurse_jsonify: Callable[[Any], Dict[str, Any]]) -> Any:
        if _ClvmSerializationMode.get_config().use:
            return bytes(self).hex()
        else:
            new_dict = {}
            for field in fields(self):
                new_dict[field.name] = default_recurse_jsonify(getattr(self, field.name))
            return new_dict

    @classmethod
    def from_json_dict(cls: Type[_T_ClvmStreamable], json_dict: Any) -> _T_ClvmStreamable:
        if isinstance(json_dict, str):
            try:
                byts = hexstr_to_bytes(json_dict)
            except ValueError as e:
                raise ConversionError(json_dict, cls, e)

            try:
                return cls.from_program(Program.from_bytes(byts))
            except Exception as e:
                raise ConversionError(json_dict, cls, e)
        else:
            return super().from_json_dict(json_dict)
