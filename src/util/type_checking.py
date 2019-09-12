from typing import Any, Type, get_type_hints, List, Union
import dataclasses


def is_type_List(f_type: Type) -> bool:
    return (hasattr(f_type, "__origin__") and f_type.__origin__ == list) or f_type == list


def is_type_SpecificOptional(f_type) -> bool:
    """
    Returns true for types such as Optional[T], but not Optional, or T.
    """
    return (hasattr(f_type, "__origin__") and f_type.__origin__ == Union
            and f_type.__args__[1]() is None)


def strictdataclass(cls: Any):
    class _Local():
        """
        Dataclass where all fields must be type annotated, and type checking is performed
        at initialization, even recursively through Lists. Non-annotated fields are ignored.
        Also, for any fields which have a type with .from_bytes(bytes) or constructor(bytes),
        bytes can be passed in and the type can be constructed.
        """
        def parse_item(self, item: Any, f_name: str, f_type: Type) -> Any:
            if is_type_List(f_type):
                collected_list: f_type = []
                inner_type: Type = f_type.__args__[0]
                assert inner_type != List.__args__[0]
                if not is_type_List(type(item)):
                    raise ValueError(f"Wrong type for {f_name}, need a list.")
                for el in item:
                    collected_list.append(self.parse_item(el, f_name, inner_type))
                return collected_list
            if is_type_SpecificOptional(f_type):
                if item is None:
                    return None
                else:
                    inner_type: Type = f_type.__args__[0]
                    return self.parse_item(item, f_name, inner_type)
            if not isinstance(item, f_type):
                try:
                    item = f_type(item)
                except (TypeError, AttributeError, ValueError):
                    item = f_type.from_bytes(item)
            if not isinstance(item, f_type):
                raise ValueError(f"Wrong type for {f_name}")
            return item

        def __init__(self, *args):
            fields = get_type_hints(self)
            la, lf = len(args), len(fields)
            if la != lf:
                raise ValueError("got %d and expected %d args" % (la, lf))
            for a, (f_name, f_type) in zip(args, fields.items()):
                object.__setattr__(self, f_name, self.parse_item(a, f_name, f_type))

    class NoTypeChecking:
        __no_type_check__ = True

    cls1 = dataclasses.dataclass(_cls=cls, init=False, frozen=True)
    if dataclasses.fields(cls1) == ():
        return type(cls.__name__, (cls1, _Local, NoTypeChecking), {})
    return type(cls.__name__, (cls1, _Local), {})
