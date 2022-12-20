import dataclasses

from typing import Type, BinaryIO, TypeVar, get_type_hints

from .bin_methods import bin_methods


T = TypeVar("T")


def streamable(cls: T) -> T:
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
            for f_name, f_type in get_type_hints(cls).items():
                if hasattr(f_type, "parse"):
                    values.append(f_type.parse(f))
                else:
                    raise NotImplementedError
            return cls(*values)

        def stream(self, f: BinaryIO) -> None:
            for f_name, f_type in get_type_hints(self).items():
                v = getattr(self, f_name)
                if hasattr(f_type, "stream"):
                    v.stream(f)
                else:
                    raise NotImplementedError("can't stream %s: %s" % (v, f_name))

    cls1 = dataclasses.dataclass(cls, frozen=True, init=False)

    cls2 = type(cls.__name__, (cls1, bin_methods, _local), {})
    return cls2
