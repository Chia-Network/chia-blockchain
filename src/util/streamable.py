import dataclasses
from blspy import PublicKey, Signature, PrependSignature
from typing import Type, BinaryIO, get_type_hints, Any, Optional, List
from src.util.ints import uint32, uint8
from src.util.type_checking import ArgTypeChecker
from src.util.bin_methods import BinMethods


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

    class _Local:
        @classmethod
        def parse(cls: Type[cls.__name__], f: BinaryIO) -> cls.__name__:
            values = []
            for f_name, f_type in get_type_hints(cls).items():
                if hasattr(f_type, "parse"):
                    values.append(f_type.parse(f))
                elif hasattr(f_type, "from_bytes") and size_hints[f_type.__name__]:
                    values.append(f_type.from_bytes(f.read(size_hints[f_type.__name__])))
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
                else:
                    raise NotImplementedError(f"can't stream {v}, {f_name}")

    cls1 = dataclasses.dataclass(_cls=cls, init=False, frozen=True)
    return type(cls.__name__, (cls1, BinMethods, ArgTypeChecker, _Local), {})


def StreamableList(the_type):
    """
    This creates a streamable homogenous list of the given streamable object. It has
    a 32-bit unsigned prefix length, so lists are limited to a length of 2^32 - 1.
    """

    cls_name = "%sList" % the_type.__name__

    def __init__(self, items: List[the_type]):
        self._items = tuple(items)

    def __iter__(self):
        return iter(self._items)

    @classmethod
    def parse(cls: Type[cls_name], f: BinaryIO) -> cls_name:
        count = uint32.parse(f)
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
        count = uint32(len(self._items))
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
    streamable_list_type = type(cls_name, (BinMethods,), namespace)
    return streamable_list_type


def StreamableOptional(the_type):
    """
    This creates a streamable optional of the given streamable object. It has
    a 1 byte big-endian prefix which is equal to 1 if the element is there,
    and 0 if the element is not there.
    """

    cls_name = "%sOptional" % the_type.__name__

    def __init__(self, item: Optional[the_type]):
        self._item = item

    @classmethod
    def parse(cls: Type[cls_name], f: BinaryIO) -> cls_name:
        is_present: bool = (uint8.parse(f) == 1)
        item: Optional[the_type] = None
        if is_present:
            if hasattr(the_type, "parse"):
                item = the_type.parse(f)
            elif hasattr(the_type, "from_bytes") and size_hints[the_type.__name__]:
                item = the_type.from_bytes(f.read(size_hints[the_type.__name__]))
            else:
                raise ValueError("wrong type for %s" % the_type)
        return cls(item)

    def stream(self, f: BinaryIO) -> None:
        is_present: uint8 = uint8(1) if self._item else uint8(0)
        is_present.stream(f)
        if is_present == 1:
            if hasattr(type(self._item), "stream"):
                self._item.stream(f)
            elif hasattr(type(self._item), "serialize"):
                f.write(self._item.serialize())
            else:
                raise NotImplementedError(f"can't stream {type(self._item)}")

    def __str__(self):
        return str(self._item)

    def __repr__(self):
        return repr(self._item)

    namespace = dict(
        __init__=__init__, parse=parse,
        stream=stream, __str__=__str__, __repr__=__repr__)
    streamable_optional_type = type(cls_name, (BinMethods,), namespace)
    return streamable_optional_type
