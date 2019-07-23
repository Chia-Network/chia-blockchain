import dataclasses

from typing import Type, BinaryIO, get_type_hints

from .bin_methods import bin_methods


def streamable(cls):
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
                    to_write = v.serialize()
                    f.write(to_write)
                elif isinstance(v, bytes):
                    f.write(v)
                else:
                    raise NotImplementedError(f"can't stream {v}, {f_name}")

    cls1 = dataclasses.dataclass(_cls=cls, frozen=True, init=False)

    cls2 = type(cls.__name__, (cls1, bin_methods, _local), {})
    return cls2


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
