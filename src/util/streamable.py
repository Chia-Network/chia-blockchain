# flake8: noqa
from __future__ import annotations

import dataclasses
import io
import pprint
import json
from enum import Enum
from typing import Any, BinaryIO, List, Type, get_type_hints, Union, Dict
from src.util.byte_types import hexstr_to_bytes
from src.types.program import Program
from src.util.hash import std_hash

from blspy import (
    ChainCode,
    ExtendedPrivateKey,
    ExtendedPublicKey,
    InsecureSignature,
    PrependSignature,
    PrivateKey,
    PublicKey,
    Signature,
)

from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint8, uint64, int64, uint128, int512
from src.util.type_checking import (
    is_type_List,
    is_type_Tuple,
    is_type_SpecificOptional,
    strictdataclass,
)
from src.wallet.util.wallet_types import WalletType

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
    "ChainCode": ChainCode.CHAIN_CODE_KEY_SIZE,
}
unhashable_types = [
    PrivateKey,
    PublicKey,
    Signature,
    PrependSignature,
    InsecureSignature,
    ExtendedPublicKey,
    ExtendedPrivateKey,
    ChainCode,
    Program,
]
# JSON does not support big ints, so these types must be serialized differently in JSON
big_ints = [uint64, int64, uint128, int512]


def dataclass_from_dict(klass, d):
    """
    Converts a dictionary based on a dataclass, into an instance of that dataclass.
    Recursively goes through lists, optionals, and dictionaries.
    """
    if is_type_SpecificOptional(klass):
        # Type is optional, data is either None, or Any
        if not d:
            return None
        return dataclass_from_dict(klass.__args__[0], d)
    if dataclasses.is_dataclass(klass):
        # Type is a dataclass, data is a dictionary
        fieldtypes = {f.name: f.type for f in dataclasses.fields(klass)}
        return klass(**{f: dataclass_from_dict(fieldtypes[f], d[f]) for f in d})
    elif is_type_List(klass):
        # Type is a list, data is a list
        return [dataclass_from_dict(klass.__args__[0], item) for item in d]
    elif issubclass(klass, bytes):
        # Type is bytes, data is a hex string
        return klass(hexstr_to_bytes(d))
    elif klass in unhashable_types:
        # Type is unhashable (bls type), so cast from hex string
        return klass.from_bytes(hexstr_to_bytes(d))
    else:
        # Type is a primitive, cast with correct class
        return klass(d)


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
        if is_type_Tuple(f_type):
            inner_types = f_type.__args__
            full_list = []
            for inner_type in inner_types:
                full_list.append(cls.parse_one_item(inner_type, f))  # type: ignore
            return tuple(full_list)
        if f_type is bool:
            return bool.from_bytes(f.read(4), "big")
        if f_type == bytes:
            list_size = uint32(int.from_bytes(f.read(4), "big"))
            return f.read(list_size)
        if hasattr(f_type, "parse"):
            return f_type.parse(f)
        if hasattr(f_type, "from_bytes") and size_hints[f_type.__name__]:
            return f_type.from_bytes(f.read(size_hints[f_type.__name__]))
        if f_type is str:
            str_size: uint32 = uint32(int.from_bytes(f.read(4), "big"))
            return bytes.decode(f.read(str_size), "utf-8")
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
        elif is_type_Tuple(f_type):
            inner_types = f_type.__args__
            assert len(item) == len(inner_types)
            for i in range(len(item)):
                self.stream_one_item(inner_types[i], item[i], f)
        elif f_type == bytes:
            f.write(uint32(len(item)).to_bytes(4, "big"))
            f.write(item)
        elif hasattr(f_type, "stream"):
            item.stream(f)
        elif hasattr(f_type, "__bytes__"):
            f.write(bytes(item))
        elif f_type is str:
            f.write(uint32(len(item)).to_bytes(4, "big"))
            f.write(item.encode("utf-8"))
        elif f_type is bool:
            f.write(int(item).to_bytes(4, "big"))
        else:
            raise NotImplementedError(f"can't stream {item}, {f_type}")

    def stream(self, f: BinaryIO) -> None:
        for f_name, f_type in get_type_hints(self).items():  # type: ignore
            self.stream_one_item(f_type, getattr(self, f_name), f)

    def get_hash(self) -> bytes32:
        return bytes32(std_hash(bytes(self)))

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self: Any) -> str:
        return pp.pformat(self.recurse_jsonify(dataclasses.asdict(self)))

    def __repr__(self: Any) -> str:
        return pp.pformat(self.recurse_jsonify(dataclasses.asdict(self)))

    def to_json_dict(self) -> Dict:
        return self.recurse_jsonify(dataclasses.asdict(self))

    @classmethod
    def from_json_dict(cls: Any, json_dict: Dict) -> Any:
        return dataclass_from_dict(cls, json_dict)

    def recurse_jsonify(self, d):
        """
        Makes bytes objects and unhashable types into strings with 0x, and makes large ints into
        strings.
        """
        if isinstance(d, list):
            new_list = []
            for item in d:
                if type(item) in unhashable_types or issubclass(type(item), bytes):
                    item = f"0x{bytes(item).hex()}"
                if isinstance(item, dict):
                    self.recurse_jsonify(item)
                if isinstance(item, list):
                    self.recurse_jsonify(item)
                if isinstance(item, Enum):
                    item = item.name
                if isinstance(item, int) and type(item) in big_ints:
                    item = str(item)
                new_list.append(item)
            d = new_list

        else:
            for key, value in d.items():
                if type(value) in unhashable_types or issubclass(type(value), bytes):
                    d[key] = f"0x{bytes(value).hex()}"
                if isinstance(value, dict):
                    self.recurse_jsonify(value)
                if isinstance(value, list):
                    self.recurse_jsonify(value)
                if isinstance(value, Enum):
                    d[key] = value.name
                if isinstance(value, int) and type(value) in big_ints:
                    d[key] = str(value)
        return d
