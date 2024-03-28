from __future__ import annotations

import dataclasses
import functools
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union, get_args, get_type_hints

from hsms.clvm_serde import from_program_for_type, to_program_for_type

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
        if is_type_Tuple(hints[field.name]):
            raise ValueError("@clvm_streamable does not support tuples")

    return wrapped_cls


def program_serialize_clvm_streamable(clvm_streamable: Streamable) -> Program:
    # Underlying hinting problem with clvm_serde
    return to_program_for_type(type(clvm_streamable))(clvm_streamable)  # type: ignore[no-any-return]


def byte_serialize_clvm_streamable(clvm_streamable: Streamable) -> bytes:
    return bytes(program_serialize_clvm_streamable(clvm_streamable))


def json_serialize_with_clvm_streamable(
    streamable: Any, next_recursion_step: Optional[Callable[[Any, Any], Dict[str, Any]]] = None
) -> Union[str, Dict[str, Any]]:
    if next_recursion_step is None:
        next_recursion_step = recurse_jsonify
    if hasattr(streamable, "_clvm_streamable"):
        # If we are using clvm_serde, we stop JSON serialization at this point and instead return the clvm blob
        return byte_serialize_clvm_streamable(streamable).hex()
    else:
        return next_recursion_step(streamable, json_serialize_with_clvm_streamable)


def program_deserialize_clvm_streamable(program: Program, clvm_streamable_type: Type[_T_Streamable]) -> _T_Streamable:
    # Underlying hinting problem with clvm_serde
    return from_program_for_type(clvm_streamable_type)(program)  # type: ignore[no-any-return]


def byte_deserialize_clvm_streamable(blob: bytes, clvm_streamable_type: Type[_T_Streamable]) -> _T_Streamable:
    return program_deserialize_clvm_streamable(Program.from_bytes(blob), clvm_streamable_type)


def is_compound_type(typ: Any) -> bool:
    return is_type_SpecificOptional(typ) or is_type_Tuple(typ) or is_type_List(typ)


def json_deserialize_with_clvm_streamable(
    json_dict: Union[str, Dict[str, Any]], streamable_type: Type[_T_Streamable]
) -> _T_Streamable:
    if isinstance(json_dict, str):
        return byte_deserialize_clvm_streamable(bytes.fromhex(json_dict), streamable_type)
    else:
        old_streamable_fields = streamable_type.streamable_fields()
        new_streamable_fields = []
        for old_field in old_streamable_fields:
            if is_compound_type(old_field.type):
                inner_type = get_args(old_field.type)[0]
                if hasattr(inner_type, "_clvm_streamable"):
                    new_streamable_fields.append(
                        dataclasses.replace(
                            old_field,
                            convert_function=function_to_convert_one_item(
                                old_field.type,
                                functools.partial(json_deserialize_with_clvm_streamable, streamable_type=inner_type),
                            ),
                        )
                    )
                else:
                    new_streamable_fields.append(old_field)
            elif hasattr(old_field.type, "_clvm_streamable"):
                new_streamable_fields.append(
                    dataclasses.replace(
                        old_field,
                        convert_function=functools.partial(
                            json_deserialize_with_clvm_streamable, streamable_type=old_field.type
                        ),
                    )
                )
            else:
                new_streamable_fields.append(old_field)

        setattr(streamable_type, "_streamable_fields", tuple(new_streamable_fields))
        return streamable_type.from_json_dict(json_dict)
