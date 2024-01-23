from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass, fields
from io import BytesIO
from typing import Any, BinaryIO, Callable, Dict, Generic, Iterator, List, Optional, Type, TypeVar, Union

from hsms.clvm_serde import from_program_for_type, to_program_for_type
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import ConversionError, Streamable, streamable


@dataclass
class ClvmSerializationConfig:
    use: bool = False
    transport_layer: Optional[TransportLayer] = None


class _ClvmSerializationMode:
    config = contextvars.ContextVar("config", default=threading.local())

    @classmethod
    def get_config(cls) -> ClvmSerializationConfig:
        return getattr(cls.config.get(), "config", ClvmSerializationConfig())

    @classmethod
    def set_config(cls, config: ClvmSerializationConfig) -> None:
        cls.config.get().config = config


@contextmanager
def clvm_serialization_mode(use: bool, transport_layer: Optional[TransportLayer] = None) -> Iterator[None]:
    old_config = _ClvmSerializationMode.get_config()
    _ClvmSerializationMode.set_config(ClvmSerializationConfig(use=use, transport_layer=transport_layer))
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
_T_TLClvmStreamable = TypeVar("_T_TLClvmStreamable", bound="ClvmStreamable")


class ClvmStreamable(Streamable, metaclass=ClvmStreamableMeta):
    def as_program(self) -> Program:
        raise NotImplementedError()  # pragma: no cover

    @classmethod
    def from_program(cls: Type[_T_ClvmStreamable], prog: Program) -> _T_ClvmStreamable:
        raise NotImplementedError()  # pragma: no cover

    def stream(self, f: BinaryIO) -> None:
        transport_layer: Optional[TransportLayer] = _ClvmSerializationMode.get_config().transport_layer
        if transport_layer is not None:
            new_self = transport_layer.serialize_for_transport(self)
        else:
            new_self = self

        if _ClvmSerializationMode.get_config().use:
            f.write(bytes(new_self.as_program()))
        else:
            super().stream(f)

    @classmethod
    def parse(cls: Type[_T_ClvmStreamable], f: BinaryIO) -> _T_ClvmStreamable:
        assert isinstance(f, BytesIO)
        transport_layer: Optional[TransportLayer] = _ClvmSerializationMode.get_config().transport_layer
        if transport_layer is not None:
            cls_mapping: Optional[
                TransportLayerMapping[_T_ClvmStreamable, ClvmStreamable]
            ] = transport_layer.get_mapping(cls)
            if cls_mapping is not None:
                new_cls: Type[Union[_T_ClvmStreamable, ClvmStreamable]] = cls_mapping.to_type
            else:
                new_cls = cls
        else:
            new_cls = cls

        try:
            result = new_cls.from_program(Program.from_bytes(bytes(f.getbuffer())))
            f.read()
            if transport_layer is not None and cls_mapping is not None:
                deserialized_result: _T_ClvmStreamable = cls_mapping.deserialize_function(result)
                return deserialized_result
            else:
                assert isinstance(result, cls)
                return result
        except Exception:
            return super().parse(f)

    def override_json_serialization(self, default_recurse_jsonify: Callable[[Any], Dict[str, Any]]) -> Any:
        transport_layer: Optional[TransportLayer] = _ClvmSerializationMode.get_config().transport_layer
        if transport_layer is not None:
            new_self = transport_layer.serialize_for_transport(self)
        else:
            new_self = self

        if _ClvmSerializationMode.get_config().use:
            return bytes(self).hex()
        else:
            new_dict = {}
            for field in fields(new_self):
                new_dict[field.name] = default_recurse_jsonify(getattr(new_self, field.name))
            return new_dict

    @classmethod
    def from_json_dict(cls: Type[_T_ClvmStreamable], json_dict: Any) -> _T_ClvmStreamable:
        transport_layer: Optional[TransportLayer] = _ClvmSerializationMode.get_config().transport_layer
        if transport_layer is not None:
            cls_mapping: Optional[
                TransportLayerMapping[_T_ClvmStreamable, ClvmStreamable]
            ] = transport_layer.get_mapping(cls)
            if cls_mapping is not None:
                new_cls: Type[Union[_T_ClvmStreamable, ClvmStreamable]] = cls_mapping.to_type
            else:
                new_cls = cls
        else:
            new_cls = cls

        if isinstance(json_dict, str):
            try:
                byts = hexstr_to_bytes(json_dict)
            except ValueError as e:
                raise ConversionError(json_dict, new_cls, e)

            try:
                result = new_cls.from_program(Program.from_bytes(byts))
                if transport_layer is not None and cls_mapping is not None:
                    deserialized_result: _T_ClvmStreamable = cls_mapping.deserialize_function(result)
                    return deserialized_result
                else:
                    assert isinstance(result, cls)
                    return result
            except Exception as e:
                raise ConversionError(json_dict, new_cls, e)
        else:
            return super().from_json_dict(json_dict)


@dataclass(frozen=True)
class TransportLayerMapping(Generic[_T_ClvmStreamable, _T_TLClvmStreamable]):
    from_type: Type[_T_ClvmStreamable]
    to_type: Type[_T_TLClvmStreamable]
    serialize_function: Callable[[_T_ClvmStreamable], _T_TLClvmStreamable]
    deserialize_function: Callable[[_T_TLClvmStreamable], _T_ClvmStreamable]


@dataclass(frozen=True)
class TransportLayer:
    type_mappings: List[TransportLayerMapping[Any, Any]]

    def get_mapping(
        self, _type: Type[_T_ClvmStreamable]
    ) -> Optional[TransportLayerMapping[_T_ClvmStreamable, ClvmStreamable]]:
        mappings: List[TransportLayerMapping[_T_ClvmStreamable, ClvmStreamable]] = [
            m for m in self.type_mappings if m.from_type == _type
        ]
        if len(mappings) == 1:
            return mappings[0]
        elif len(mappings) == 0:
            return None
        else:
            raise RuntimeError("Malformed TransportLayer")

    def serialize_for_transport(self, instance: _T_ClvmStreamable) -> ClvmStreamable:
        mappings: List[TransportLayerMapping[_T_ClvmStreamable, ClvmStreamable]] = [
            m for m in self.type_mappings if m.from_type == instance.__class__
        ]
        if len(mappings) == 1:
            return mappings[0].serialize_function(instance)
        elif len(mappings) == 0:
            return instance
        else:
            raise RuntimeError("Malformed TransportLayer")

    def deserialize_from_transport(self, instance: _T_ClvmStreamable) -> ClvmStreamable:
        mappings: List[TransportLayerMapping[ClvmStreamable, _T_ClvmStreamable]] = [
            m for m in self.type_mappings if m.to_type == instance.__class__
        ]
        if len(mappings) == 1:
            return mappings[0].deserialize_function(instance)
        elif len(mappings) == 0:
            return instance
        else:
            raise RuntimeError("Malformed TransportLayer")
