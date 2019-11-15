# flake8: noqa
from __future__ import annotations
import io
import dataclasses
import pprint
from typing import Type, BinaryIO, get_type_hints, Any, List
from hashlib import sha256
from blspy import (PrivateKey, PublicKey, InsecureSignature, Signature, PrependSignature,
                   ExtendedPrivateKey, ExtendedPublicKey, ChainCode)
from src.util.type_checking import strictdataclass, is_type_List, is_type_SpecificOptional
from src.types.sized_bytes import bytes32
from src.util.ints import uint32

pp = pprint.PrettyPrinter(indent=1, width=120, compact=True)

# TODO: Remove hack, this allows streaming these objects from binary
size_hints = {
    "PrivateKey": PrivateKey.PRIVATE_KEY_SIZE,
    "PublicKey": PublicKey.PUBLIC_KEY_SIZE,
    "Signature": Signature.SIGNATURE_SIZE,
    "InsecureSignature": InsecureSignature.SIGNATURE_SIZE,
    "PrependSignature": PrependSignature.SIGNATURE_SIZE,
    "ExtendedPublicKey": ExtendedPublicKey.EXTENDED_PUBLIC_KEY_SIZE,
    "ExtendedPrivateKey": ExtendedPrivateKey.EXTENDED_PRIVATE_KEY_SIZE,
    "ChainCode": ChainCode.CHAIN_CODE_KEY_SIZE
}
unhashable_types = [PrivateKey, PublicKey, Signature, PrependSignature, InsecureSignature,
                    ExtendedPublicKey, ExtendedPrivateKey, ChainCode]


def streamable(cls: Any):
    """
    This is a decorator for class definitions. It applies the strictdataclass decorator,
    which checks all types at construction. It also defines a simple serialization format,
    and adds parse, from bytes, stream, and __bytes__ methods.

    Serialization format:
    - Each field is serialized in order, by calling from_bytes/__bytes__.
    - For Lists, there is a 4 byte prefix for the list length.
    - For Optionals, there is a one byte prefix, 1 iff object is present, 0 iff not.

    All of the constituents must have parse/from_bytes, and stream/__bytes__ and therefore
    be of fixed size. For example, int cannot be a constituent since it is not a fixed size,
    whereas uint32 can be.

    Furthermore, a get_hash() member is added, which performs a serialization and a sha256.

    This class is used for deterministic serialization and hashing, for consensus critical
    objects such as the block header.

    Make sure to use the Streamable class as a parent class when using the streamable decorator,
    as it will allow linters to recognize the methods that are added by the decorator. Also,
    use the @dataclass(frozen=True) decorator as well, for linters to recognize constructor
    arguments.
    """

    cls1 = strictdataclass(cls)
    return type(cls.__name__, (cls1, Streamable), {})


class Streamable:
    @classmethod
    def parse_one_item(cls: Type[cls.__name__], f_type: Type, f: BinaryIO):  # type: ignore
        inner_type: Type
        if is_type_List(f_type):
            inner_type = f_type.__args__[0]
            full_list: List[inner_type] = []  # type: ignore
            assert inner_type != List.__args__[0]  # type: ignore
            list_size: uint32 = uint32(int.from_bytes(f.read(4), "big"))
            for list_index in range(list_size):
                full_list.append(cls.parse_one_item(inner_type, f))  # type: ignore
            return full_list
        if is_type_SpecificOptional(f_type):
            inner_type = f_type.__args__[0]
            is_present: bool = f.read(1) == bytes([1])
            if is_present:
                return cls.parse_one_item(inner_type, f)  # type: ignore
            else:
                return None
        if hasattr(f_type, "parse"):
            return f_type.parse(f)
        if hasattr(f_type, "from_bytes") and size_hints[f_type.__name__]:
            return f_type.from_bytes(f.read(size_hints[f_type.__name__]))
        if f_type is str:
            str_size: uint32 = uint32(int.from_bytes(f.read(4), "big"))
            return bytes.decode(f.read(str_size))
        else:
            raise RuntimeError(f"Type {f_type} does not have parse")

    @classmethod
    def parse(cls: Type[cls.__name__], f: BinaryIO) -> cls.__name__:  # type: ignore
        values = []
        for _, f_type in get_type_hints(cls).items():
            values.append(cls.parse_one_item(f_type, f))  # type: ignore
        return cls(*values)

    def stream_one_item(self, f_type: Type, item, f: BinaryIO) -> None:
        inner_type: Type
        if is_type_List(f_type):
            assert is_type_List(type(item))
            f.write(uint32(len(item)).to_bytes(4, "big"))
            inner_type = f_type.__args__[0]
            assert inner_type != List.__args__[0]  # type: ignore
            for element in item:
                self.stream_one_item(inner_type, element, f)
        elif is_type_SpecificOptional(f_type):
            inner_type = f_type.__args__[0]
            if item is None:
                f.write(bytes([0]))
            else:
                f.write(bytes([1]))
                self.stream_one_item(inner_type, item, f)
        elif hasattr(f_type, "stream"):
            item.stream(f)
        elif hasattr(f_type, "__bytes__"):
            f.write(bytes(item))
        elif f_type is str:
            f.write(uint32(len(item)).to_bytes(4, "big"))
            f.write(item.encode())
        else:
            raise NotImplementedError(f"can't stream {item}, {f_type}")

    def stream(self, f: BinaryIO) -> None:
        for f_name, f_type in get_type_hints(self).items():  # type: ignore
            self.stream_one_item(f_type, getattr(self, f_name), f)

    def get_hash(self) -> bytes32:
        return bytes32(sha256(bytes(self)).digest())

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self: Any) -> str:
        return pp.pformat(self.recurse_str(dataclasses.asdict(self)))

    def __repr__(self: Any) -> str:
        return pp.pformat(self.recurse_str(dataclasses.asdict(self)))

    def recurse_str(self, d):
        for key, value in d.items():
            if type(value) in unhashable_types:
                d[key] = str(value)
            if isinstance(value, dict):
                self.recurse_str(value)
        return d

