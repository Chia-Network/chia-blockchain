from __future__ import annotations

import dataclasses
import functools
from typing import Any, Tuple, Type, TypeVar


_field_metadata_key = "_chia_streamable"


@dataclasses.dataclass(frozen=True)
class _FieldMetadata:
    ignore: bool = False


@functools.wraps(wrapped=dataclasses.field)
def unstreamed_field(*args, **kwargs):
    metadata = kwargs.setdefault("metadata", {})
    metadata[_field_metadata_key] = _FieldMetadata(ignore=True)

    return dataclasses.field(*args, **kwargs)


_T_Field = TypeVar("_T_Field", bound="_Field")


@dataclasses.dataclass(frozen=True)
class _Field:
    name: str
    annotation: Any

    @classmethod
    def from_dataclass_field(cls: Type[_T_Field], field: dataclasses.Field) -> _T_Field:
        return cls(name=field.name, annotation=field.type)


_T_ClassMetadata = TypeVar("_T_ClassMetadata", bound="_ClassMetadata")


@dataclasses.dataclass(frozen=True)
class _ClassMetadata:
    fields: Tuple[_Field, ...] = ()

    @classmethod
    def from_dataclass(cls: Type[_T_ClassMetadata], dataclass) -> _T_ClassMetadata:
        fields = []
        for dataclass_field in dataclasses.fields(dataclass):
            metadata = dataclass_field.metadata.get(_field_metadata_key, _FieldMetadata())
            if metadata.ignore:
                continue
            fields.append(_Field.from_dataclass_field(field=dataclass_field))

        return cls(fields=tuple(fields))
