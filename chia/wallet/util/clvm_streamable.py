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


# This class is meant to be a context var shared by multiple calls to the methods on ClvmStreamable objects
# It is ideally thread/coroutine safe meaning when code flow is non-linear, changes in one branch do not affect others
@dataclass
class ClvmSerializationConfig:
    use: bool = False


class _ClvmSerializationMode:
    config = contextvars.ContextVar("config", default=threading.local())

    @classmethod
    def get_config(cls) -> ClvmSerializationConfig:
        return getattr(cls.config.get(), "config", ClvmSerializationConfig())

    @classmethod
    def set_config(cls, config: ClvmSerializationConfig) -> None:
        cls.config.get().config = config


@contextmanager
def clvm_serialization_mode(use: bool) -> Iterator[None]:
    old_config = _ClvmSerializationMode.get_config()
    _ClvmSerializationMode.set_config(ClvmSerializationConfig(use=use))
    yield
    _ClvmSerializationMode.set_config(old_config)


@dataclass_transform()
class ClvmStreamableMeta(type):
    """
    We use a metaclass to define custom behavior during class initialization.  We define logic such that classes that
    inherit from ClvmStreamable (which uses this metaclass) behave as if they had been defined like this:

    @streamable
    @dataclass(frozen=True)
    class ChildClass(Streamable):
        # custom streamable functions + hsms clvm_serde as/from_program methods
        ...

    To streamline the process above and prevent mistakes/inconsistencies, we use the metaclass.

    TODO: Metaclasses are generally considered bad practice and we should probably pivot from this approach.
    What is unclear, however, is how to keep the existing simple ergonomics and still hint that every class that this
    logic has been applied to has all of the proper properties. Manadatory inheritance from a class that uses this
    metaclass makes this simple because you simply need to check that something is ClvmStreamable to have those
    guarantees. Perhaps in the future a decorator can be used to something like the effect of this metaclass.
    """

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
    """
    Classes that inherit from this base class gain access to clvm serialization from hsms clvm_serde library.
    Children also gain the ability to serialize differently under the clvm_serialization_mode context manager above.
    If not called under the context manager, they will serialize according to the Streamable protocol.
    """

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
        # This try/except is to faciliate deserializing blobs that have been serialized according to either the
        # clvm_serde or streamable libraries.
        try:
            result = cls.from_program(Program.from_bytes(bytes(f.getbuffer())))
            f.read()
            return result
        except Exception:
            return super().parse(f)

    def override_json_serialization(self, default_recurse_jsonify: Callable[[Any], Dict[str, Any]]) -> Any:
        if _ClvmSerializationMode.get_config().use:
            # If we are using clvm_serde, we stop JSON serialization at this point and instead return the clvm blob
            return bytes(self).hex()
        else:
            new_dict = {}
            for field in fields(self):
                new_dict[field.name] = default_recurse_jsonify(getattr(self, field.name))
            return new_dict

    @classmethod
    def from_json_dict(cls: Type[_T_ClvmStreamable], json_dict: Any) -> _T_ClvmStreamable:
        # If we have reached this point, the Streamable library has determined we are a responsible for deserializing
        # the value at this position in the dictionary. In order to preserve the ability to parse either streamable
        # or clvm_serde objects in any context, we first check whether the value to be deserialized is a string.
        # If it is, we know this value was serialized according to clvm_serde and we deserialize it as a clvm blob.
        # If it is not, we know it was serialized according to streamable and we deserialize as a normal JSON dict
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
