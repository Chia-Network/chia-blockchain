from __future__ import annotations

import dataclasses
import functools
from types import MappingProxyType
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar, Union, get_args, get_type_hints

from hsms.clvm_serde import from_program_for_type, to_program_for_type
from typing_extensions import TypeGuard

from chia.types.blockchain_format.program import Program
from chia.util.streamable import (
    Streamable,
    function_to_convert_one_item,
    is_type_List,
    is_type_SpecificOptional,
    is_type_Tuple,
    recurse_jsonify,
    streamable,
)

_T_Streamable = TypeVar("_T_Streamable", bound=Streamable)


def clvm_streamable(cls: Type[Streamable]) -> Type[Streamable]:
    wrapped_cls: Type[Streamable] = streamable(cls)
    setattr(wrapped_cls, "_clvm_streamable", True)

    hints = get_type_hints(cls)
    # no way to hint that wrapped_cls is a dataclass here but @streamable checks that
    for field in dataclasses.fields(wrapped_cls):  # type: ignore[arg-type]
        field.metadata = MappingProxyType({"key": field.name, **field.metadata})
        if is_type_Tuple(hints[field.name]):
            raise ValueError("@clvm_streamable does not support tuples")

    return wrapped_cls


def program_serialize_clvm_streamable(
    clvm_streamable: Streamable, translation_layer: Optional[TranslationLayer] = None
) -> Program:
    if translation_layer is not None:
        mapping = translation_layer.get_mapping(clvm_streamable.__class__)
        if mapping is not None:
            clvm_streamable = translation_layer.serialize_for_translation(clvm_streamable, mapping)
    # Underlying hinting problem with clvm_serde
    return to_program_for_type(type(clvm_streamable))(clvm_streamable)  # type: ignore[no-any-return]


def byte_serialize_clvm_streamable(
    clvm_streamable: Streamable, translation_layer: Optional[TranslationLayer] = None
) -> bytes:
    return bytes(program_serialize_clvm_streamable(clvm_streamable, translation_layer=translation_layer))


def json_serialize_with_clvm_streamable(
    streamable: object,
    next_recursion_step: Optional[Callable[..., Dict[str, Any]]] = None,
    translation_layer: Optional[TranslationLayer] = None,
    **next_recursion_env: Any,
) -> Union[str, Dict[str, Any]]:
    if next_recursion_step is None:
        next_recursion_step = recurse_jsonify
    if is_clvm_streamable(streamable):
        # If we are using clvm_serde, we stop JSON serialization at this point and instead return the clvm blob
        return byte_serialize_clvm_streamable(streamable, translation_layer=translation_layer).hex()
    else:
        return next_recursion_step(
            streamable, json_serialize_with_clvm_streamable, translation_layer=translation_layer, **next_recursion_env
        )


def program_deserialize_clvm_streamable(
    program: Program, clvm_streamable_type: Type[_T_Streamable], translation_layer: Optional[TranslationLayer] = None
) -> _T_Streamable:
    type_to_deserialize_from: Type[Streamable] = clvm_streamable_type
    if translation_layer is not None:
        mapping = translation_layer.get_mapping(clvm_streamable_type)
        if mapping is not None:
            type_to_deserialize_from = mapping.to_type
    as_instance = from_program_for_type(type_to_deserialize_from)(program)
    if translation_layer is not None and mapping is not None:
        return translation_layer.deserialize_from_translation(as_instance, mapping)
    else:
        # Underlying hinting problem with clvm_serde
        return as_instance  # type: ignore[no-any-return]


def byte_deserialize_clvm_streamable(
    blob: bytes, clvm_streamable_type: Type[_T_Streamable], translation_layer: Optional[TranslationLayer] = None
) -> _T_Streamable:
    return program_deserialize_clvm_streamable(
        Program.from_bytes(blob), clvm_streamable_type, translation_layer=translation_layer
    )


def is_compound_type(typ: Any) -> bool:
    return is_type_SpecificOptional(typ) or is_type_Tuple(typ) or is_type_List(typ)


# TODO: this is more than _just_ a Streamable, but it is also a Streamable and that's
#       useful for now
def is_clvm_streamable_type(v: Type[object]) -> TypeGuard[Type[Streamable]]:
    return issubclass(v, Streamable) and hasattr(v, "_clvm_streamable")


# TODO: this is more than _just_ a Streamable, but it is also a Streamable and that's
#       useful for now
def is_clvm_streamable(v: object) -> TypeGuard[Streamable]:
    return isinstance(v, Streamable) and hasattr(v, "_clvm_streamable")


def json_deserialize_with_clvm_streamable(
    json_dict: Union[str, Dict[str, Any]],
    streamable_type: Type[_T_Streamable],
    translation_layer: Optional[TranslationLayer] = None,
) -> _T_Streamable:
    if isinstance(json_dict, str):
        return byte_deserialize_clvm_streamable(
            bytes.fromhex(json_dict), streamable_type, translation_layer=translation_layer
        )
    else:
        old_streamable_fields = streamable_type.streamable_fields()
        new_streamable_fields = []
        for old_field in old_streamable_fields:
            if is_compound_type(old_field.type):
                inner_type = get_args(old_field.type)[0]
                if is_clvm_streamable_type(inner_type):
                    new_streamable_fields.append(
                        dataclasses.replace(
                            old_field,
                            convert_function=function_to_convert_one_item(
                                old_field.type,
                                functools.partial(
                                    json_deserialize_with_clvm_streamable,
                                    streamable_type=inner_type,
                                    translation_layer=translation_layer,
                                ),
                            ),
                        )
                    )
                else:
                    new_streamable_fields.append(old_field)
            elif is_clvm_streamable_type(old_field.type):
                new_streamable_fields.append(
                    dataclasses.replace(
                        old_field,
                        convert_function=functools.partial(
                            json_deserialize_with_clvm_streamable,
                            streamable_type=old_field.type,
                            translation_layer=translation_layer,
                        ),
                    )
                )
            else:
                new_streamable_fields.append(old_field)

        setattr(streamable_type, "_streamable_fields", tuple(new_streamable_fields))
        return streamable_type.from_json_dict(json_dict)


_T_ClvmStreamable = TypeVar("_T_ClvmStreamable", bound="Streamable")
_T_TLClvmStreamable = TypeVar("_T_TLClvmStreamable", bound="Streamable")


@dataclasses.dataclass(frozen=True)
class TranslationLayerMapping(Generic[_T_ClvmStreamable, _T_TLClvmStreamable]):
    from_type: Type[_T_ClvmStreamable]
    to_type: Type[_T_TLClvmStreamable]
    serialize_function: Callable[[_T_ClvmStreamable], _T_TLClvmStreamable]
    deserialize_function: Callable[[_T_TLClvmStreamable], _T_ClvmStreamable]


@dataclasses.dataclass(frozen=True)
class TranslationLayer:
    type_mappings: List[TranslationLayerMapping[Any, Any]]

    def get_mapping(
        self, _type: Type[_T_ClvmStreamable]
    ) -> Optional[TranslationLayerMapping[_T_ClvmStreamable, Streamable]]:
        mappings = [m for m in self.type_mappings if m.from_type == _type]
        if len(mappings) == 1:
            return mappings[0]
        elif len(mappings) == 0:
            return None
        else:  # pragma: no cover
            raise RuntimeError("Malformed TranslationLayer")

    def serialize_for_translation(
        self, instance: _T_ClvmStreamable, mapping: TranslationLayerMapping[_T_ClvmStreamable, _T_TLClvmStreamable]
    ) -> _T_TLClvmStreamable:
        if mapping is None:
            return instance
        else:
            return mapping.serialize_function(instance)

    def deserialize_from_translation(
        self, instance: _T_TLClvmStreamable, mapping: TranslationLayerMapping[_T_ClvmStreamable, _T_TLClvmStreamable]
    ) -> _T_ClvmStreamable:
        if mapping is None:
            return instance
        else:
            return mapping.deserialize_function(instance)
