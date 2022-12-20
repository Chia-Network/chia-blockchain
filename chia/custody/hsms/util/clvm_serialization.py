from typing import Any, Callable, Dict, List, Tuple, TypeVar

from clvm.casts import int_from_bytes
from clvm.CLVMObject import CLVMObject


K = TypeVar("K")
T = TypeVar("T")
V = TypeVar("V")


def transform_dict(program, dict_transformer_f):
    """
    Transform elements of the dict d using the xformer (also a dict,
    where the keys match the keys in d and the values of d are transformed
    by invoking the corresponding values in xformer.
    """
    try:
        r = clvm_to_list(program, lambda x: dict_transformer_f(x.pair[0], x.pair[1]))
    except Exception as ex:
        print(ex)
        breakpoint()
    d = dict(r)
    return d


def transform_by_key(
    key: CLVMObject,
    value: CLVMObject,
    transformation_lookup: Dict[str, Callable[[CLVMObject], Any]],
) -> Tuple[str, Any]:
    """
    Use this if the key is utf-8 and the value decoding depends on the key.
    """
    key_str = key.atom.decode()
    f = transformation_lookup.get(key_str, lambda x: x)
    final_value = f(value)
    return (key_str, final_value)


def transform_dict_by_key(
    transformation_lookup: Dict[str, Callable[[CLVMObject], Any]]
) -> Any:
    return lambda k, v: transform_by_key(k, v, transformation_lookup)


def transform_as_struct(items: CLVMObject, *struct_transformers) -> Tuple[Any, ...]:
    r = []
    for f in struct_transformers:
        r.append(f(items.pair[0]))
        items = items.pair[1]
    return tuple(r)


def clvm_to_list(
    item_list: CLVMObject, item_transformation_f: Callable[[CLVMObject], T]
) -> List[T]:
    r = []
    while item_list.pair:
        this_item, item_list = item_list.pair
        r.append(item_transformation_f(this_item))
    return r


def clvm_list_of_bytes_to_list(
    items: CLVMObject, from_bytes_f: Callable[[bytes], T]
) -> List[T]:
    return clvm_to_list(items, lambda obj: from_bytes_f(obj.atom))


def clvm_to_list_of_ints(items: CLVMObject) -> List[int]:
    return clvm_to_list(items, lambda obj: int_from_bytes(obj.atom))


def clvm_list_to_dict(
    items: CLVMObject,
    from_clvm_f_to_kv: Callable[[CLVMObject, CLVMObject], Tuple[K, V]],
) -> Dict[K, V]:
    r = clvm_to_list(items, lambda obj: from_clvm_f_to_kv(obj.pair[0], obj.pair[1]))
    return dict(r)
