import dataclasses
import sys
from typing import Any, List, Optional, Tuple, Type, Union, get_type_hints

if sys.version_info < (3, 8):

    def get_args(t: Type[Any]) -> Tuple[Any, ...]:
        return getattr(t, "__args__", ())

    def get_origin(t: Type[Any]) -> Optional[Type[Any]]:
        return getattr(t, "__origin__", None)


else:

    from typing import get_args, get_origin


def is_type_List(f_type: Type) -> bool:
    return (get_origin(f_type) is not None and get_origin(f_type) == list) or f_type == list


def is_type_SpecificOptional(f_type) -> bool:
    """
    Returns true for types such as Optional[T], but not Optional, or T.
    """
    return get_origin(f_type) is not None and f_type.__origin__ == Union and get_args(f_type)[1]() is None


def is_type_Tuple(f_type: Type) -> bool:
    return (get_origin(f_type) is not None and get_origin(f_type) == tuple) or f_type == tuple


def strictdataclass(cls: Any):
    class _Local:
        """
        Dataclass where all fields must be type annotated, and type checking is performed
        at initialization, even recursively through Lists. Non-annotated fields are ignored.
        Also, for any fields which have a type with .from_bytes(bytes) or constructor(bytes),
        bytes can be passed in and the type can be constructed.
        """

        def parse_item(self, item: Any, f_name: str, f_type: Type) -> Any:
            if is_type_List(f_type):
                collected_list: List = []
                inner_type: Type = get_args(f_type)[0]
                # wjb assert inner_type != get_args(List)[0]  # type: ignore
                if not is_type_List(type(item)):
                    raise ValueError(f"Wrong type for {f_name}, need a list.")
                for el in item:
                    collected_list.append(self.parse_item(el, f_name, inner_type))
                return collected_list
            if is_type_SpecificOptional(f_type):
                if item is None:
                    return None
                else:
                    inner_type: Type = get_args(f_type)[0]  # type: ignore
                    return self.parse_item(item, f_name, inner_type)
            if is_type_Tuple(f_type):
                collected_list = []
                if not is_type_Tuple(type(item)) and not is_type_List(type(item)):
                    raise ValueError(f"Wrong type for {f_name}, need a tuple.")
                if len(item) != len(get_args(f_type)):
                    raise ValueError(f"Wrong number of elements in tuple {f_name}.")
                for i in range(len(item)):
                    inner_type = get_args(f_type)[i]
                    tuple_item = item[i]
                    collected_list.append(self.parse_item(tuple_item, f_name, inner_type))
                return tuple(collected_list)
            if not isinstance(item, f_type):
                try:
                    item = f_type(item)
                except (TypeError, AttributeError, ValueError):
                    try:
                        item = f_type.from_bytes(item)
                    except Exception:
                        item = f_type.from_bytes(bytes(item))
            if not isinstance(item, f_type):
                raise ValueError(f"Wrong type for {f_name}")
            return item

        def __post_init__(self):
            fields = get_type_hints(self)
            data = self.__dict__
            for (f_name, f_type) in fields.items():
                if f_name not in data:
                    raise ValueError(f"Field {f_name} not present")
                object.__setattr__(self, f_name, self.parse_item(data[f_name], f_name, f_type))

    class NoTypeChecking:
        __no_type_check__ = True

    cls1 = dataclasses.dataclass(cls, init=False, frozen=True)  # type: ignore
    if dataclasses.fields(cls1) == ():
        return type(cls.__name__, (cls1, _Local, NoTypeChecking), {})
    return type(cls.__name__, (cls1, _Local), {})
