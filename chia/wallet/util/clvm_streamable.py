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


# This class is meant to be a context var shared by multiple calls to the methods on ClvmStreamable objects
# It is ideally thread/coroutine safe meaning when code flow is non-linear, changes in one branch do not affect others
@dataclass
class ClvmSerializationConfig:
    use: bool = False
    translation_layer: Optional[TranslationLayer] = None


class _ClvmSerializationMode:
    config = contextvars.ContextVar("config", default=threading.local())

    @classmethod
    def get_config(cls) -> ClvmSerializationConfig:
        return getattr(cls.config.get(), "config", ClvmSerializationConfig())

    @classmethod
    def set_config(cls, config: ClvmSerializationConfig) -> None:
        cls.config.get().config = config


@contextmanager
def clvm_serialization_mode(use: bool, translation_layer: Optional[TranslationLayer] = None) -> Iterator[None]:
    old_config = _ClvmSerializationMode.get_config()
    _ClvmSerializationMode.set_config(ClvmSerializationConfig(use=use, translation_layer=translation_layer))
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
_T_TLClvmStreamable = TypeVar("_T_TLClvmStreamable", bound="ClvmStreamable")


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
        translation_layer: Optional[TranslationLayer] = _ClvmSerializationMode.get_config().translation_layer
        if translation_layer is not None:
            new_self = translation_layer.serialize_for_translation(self)
        else:
            new_self = self

        if _ClvmSerializationMode.get_config().use:
            f.write(bytes(new_self.as_program()))
        else:
            super().stream(f)

    @classmethod
    def parse(cls: Type[_T_ClvmStreamable], f: BinaryIO) -> _T_ClvmStreamable:
        assert isinstance(f, BytesIO)
        translation_layer: Optional[TranslationLayer] = _ClvmSerializationMode.get_config().translation_layer
        if translation_layer is not None:
            cls_mapping: Optional[
                TranslationLayerMapping[_T_ClvmStreamable, ClvmStreamable]
            ] = translation_layer.get_mapping(cls)
            if cls_mapping is not None:
                new_cls: Type[Union[_T_ClvmStreamable, ClvmStreamable]] = cls_mapping.to_type
            else:
                new_cls = cls
        else:
            new_cls = cls

        # This try/except is to faciliate deserializing blobs that have been serialized according to either the
        # clvm_serde or streamable libraries.
        try:
            result = new_cls.from_program(Program.from_bytes(bytes(f.getbuffer())))
            f.read()
            if translation_layer is not None and cls_mapping is not None:
                deserialized_result = translation_layer.deserialize_from_translation(result)
                assert isinstance(deserialized_result, cls)
                return deserialized_result
            else:
                assert isinstance(result, cls)
                return result
        except Exception:
            return super().parse(f)

    def override_json_serialization(self, default_recurse_jsonify: Callable[[Any], Dict[str, Any]]) -> Any:
        translation_layer: Optional[TranslationLayer] = _ClvmSerializationMode.get_config().translation_layer
        if translation_layer is not None:
            new_self = translation_layer.serialize_for_translation(self)
        else:
            new_self = self

        if _ClvmSerializationMode.get_config().use:
            # If we are using clvm_serde, we stop JSON serialization at this point and instead return the clvm blob
            return bytes(self).hex()
        else:
            new_dict = {}
            for field in fields(new_self):
                new_dict[field.name] = default_recurse_jsonify(getattr(new_self, field.name))
            return new_dict

    @classmethod
    def from_json_dict(cls: Type[_T_ClvmStreamable], json_dict: Any) -> _T_ClvmStreamable:
        translation_layer: Optional[TranslationLayer] = _ClvmSerializationMode.get_config().translation_layer
        if translation_layer is not None:
            cls_mapping: Optional[
                TranslationLayerMapping[_T_ClvmStreamable, ClvmStreamable]
            ] = translation_layer.get_mapping(cls)
            if cls_mapping is not None:
                new_cls: Type[Union[_T_ClvmStreamable, ClvmStreamable]] = cls_mapping.to_type
            else:
                new_cls = cls
        else:
            new_cls = cls

        # If we have reached this point, the Streamable library has determined we are a responsible for deserializing
        # the value at this position in the dictionary. In order to preserve the ability to parse either streamable
        # or clvm_serde objects in any context, we first check whether the value to be deserialized is a string.
        # If it is, we know this value was serialized according to clvm_serde and we deserialize it as a clvm blob.
        # If it is not, we know it was serialized according to streamable and we deserialize as a normal JSON dict
        if isinstance(json_dict, str):
            try:
                byts = hexstr_to_bytes(json_dict)
            except ValueError as e:
                raise ConversionError(json_dict, new_cls, e)

            try:
                result = new_cls.from_program(Program.from_bytes(byts))
                if translation_layer is not None and cls_mapping is not None:
                    deserialized_result = translation_layer.deserialize_from_translation(result)
                    assert isinstance(deserialized_result, cls)
                    return deserialized_result
                else:
                    assert isinstance(result, cls)
                    return result
            except Exception as e:
                raise ConversionError(json_dict, new_cls, e)
        else:
            return super().from_json_dict(json_dict)


@dataclass(frozen=True)
class TranslationLayerMapping(Generic[_T_ClvmStreamable, _T_TLClvmStreamable]):
    from_type: Type[_T_ClvmStreamable]
    to_type: Type[_T_TLClvmStreamable]
    serialize_function: Callable[[_T_ClvmStreamable], _T_TLClvmStreamable]
    deserialize_function: Callable[[_T_TLClvmStreamable], _T_ClvmStreamable]


@dataclass(frozen=True)
class TranslationLayer:
    type_mappings: List[TranslationLayerMapping[Any, Any]]

    def get_mapping(
        self, _type: Type[_T_ClvmStreamable], for_serialized_type: bool = False
    ) -> Optional[TranslationLayerMapping[_T_ClvmStreamable, ClvmStreamable]]:
        if for_serialized_type:
            mappings: List[TranslationLayerMapping[_T_ClvmStreamable, ClvmStreamable]] = [
                m for m in self.type_mappings if m.to_type == _type
            ]
        else:
            mappings = [m for m in self.type_mappings if m.from_type == _type]
        if len(mappings) == 1:
            return mappings[0]
        elif len(mappings) == 0:
            return None
        else:  # pragma: no cover
            raise RuntimeError("Malformed TranslationLayer")

    def serialize_for_translation(self, instance: _T_ClvmStreamable) -> ClvmStreamable:
        mapping = self.get_mapping(instance.__class__)
        if mapping is None:
            return instance
        else:
            return mapping.serialize_function(instance)

    def deserialize_from_translation(self, instance: _T_ClvmStreamable) -> ClvmStreamable:
        mapping = self.get_mapping(instance.__class__, for_serialized_type=True)
        if mapping is None:
            return instance
        else:
            return mapping.deserialize_function(instance)
