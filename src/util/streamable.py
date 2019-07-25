import dataclasses
from blspy import PublicKey, Signature, PrependSignature
from typing import Type, BinaryIO, get_type_hints, Any
from src.util.ints import uint16

from .bin_methods import bin_methods


# TODO: Remove hack, this allows streaming these objects from binary
size_hints = {
    "PublicKey": PublicKey.PUBLIC_KEY_SIZE,
    "Signature": Signature.SIGNATURE_SIZE,
    "PrependSignature": PrependSignature.SIGNATURE_SIZE
}


def streamable(cls: Any):
    """
    This is a decorator for class definitions. It applies the dataclasses.dataclass
    decorator, and also allows fields to be cast to their expected type. The resulting
    class also gets parse and stream for free, as long as all its constituent elements
    have it.
    """

    class _local:
        def __init__(self, *args):
            fields = get_type_hints(self)
            la, lf = len(args), len(fields)
            if la != lf:
                raise ValueError("got %d and expected %d args" % (la, lf))
            for a, (f_name, f_type) in zip(args, fields.items()):
                if not isinstance(a, f_type):
                    a = f_type(a)
                if not isinstance(a, f_type):
                    raise ValueError("wrong type for %s" % f_name)
                object.__setattr__(self, f_name, a)

        @classmethod
        def parse(cls: Type[cls.__name__], f: BinaryIO) -> cls.__name__:
            values = []
            saw_bytes = False
            for f_name, f_type in get_type_hints(cls).items():
                if saw_bytes:
                    raise ValueError("Bytes can only be the last object")
                if hasattr(f_type, "parse"):
                    values.append(f_type.parse(f))
                elif hasattr(f_type, "from_bytes") and size_hints[f_type.__name__]:
                    values.append(f_type.from_bytes(f.read(size_hints[f_type.__name__])))
                elif f_type == bytes:
                    values.append(f.read())
                    saw_bytes = True
                else:
                    raise NotImplementedError
            return cls(*values)

        def stream(self, f: BinaryIO) -> None:
            for f_name, f_type in get_type_hints(self).items():
                v = getattr(self, f_name)
                if hasattr(f_type, "stream"):
                    v.stream(f)
                elif hasattr(f_type, "serialize"):
                    f.write(v.serialize())
                elif isinstance(v, bytes):
                    f.write(v)
                else:
                    raise NotImplementedError(f"can't stream {v}, {f_name}")

    cls1 = dataclasses.dataclass(_cls=cls, init=False, frozen=True)

    cls2 = type(cls.__name__, (cls1, bin_methods, _local), {})
    return cls2


def StreamableList(the_type):
    """
    This creates a streamable homogenous list of the given streamable object. It has
    a 16-bit unsigned prefix length, so lists are limited to a length of 65535.
    """

    cls_name = "%sList" % the_type.__name__

    def __init__(self, items):
        self._items = tuple(items)

    def __iter__(self):
        return iter(self._items)

    @classmethod
    def parse(cls: Type[cls_name], f: BinaryIO) -> cls_name:
        count = uint16.parse(f)
        items = []
        for _ in range(count):
            if hasattr(the_type, "parse"):
                items.append(the_type.parse(f))
            elif hasattr(the_type, "from_bytes") and size_hints[the_type.__name__]:
                items.append(the_type.from_bytes(f.read(size_hints[the_type.__name__])))
            else:
                raise ValueError("wrong type for %s" % the_type)
        return cls(items)

    def stream(self, f: BinaryIO) -> None:
        count = uint16(len(self._items))
        count.stream(f)
        for item in self._items:
            if hasattr(type(item), "stream"):
                item.stream(f)
            elif hasattr(type(item), "serialize"):
                f.write(item.serialize())
            else:
                raise NotImplementedError(f"can't stream {type(item)}")

    def __str__(self):
        return str(self._items)

    def __repr__(self):
        return repr(self._items)

    namespace = dict(
        __init__=__init__, __iter__=__iter__, parse=parse,
        stream=stream, __str__=__str__, __repr__=__repr__)
    streamable_list_type = type(cls_name, (bin_methods,), namespace)
    return streamable_list_type


def transform_to_streamable(d):
    """
    Drill down through dictionaries and lists and transform objects with "as_bin" to bytes.
    """
    if hasattr(d, "as_bin"):
        return d.as_bin()
    if isinstance(d, (str, bytes, int)):
        return d
    if isinstance(d, dict):
        new_d = {}
        for k, v in d.items():
            new_d[transform_to_streamable(k)] = transform_to_streamable(v)
        return new_d
    return [transform_to_streamable(_) for _ in d]
