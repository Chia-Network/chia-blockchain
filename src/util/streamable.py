from __future__ import annotations
from typing import Type, BinaryIO, get_type_hints, Any, List
from hashlib import sha256
from blspy import PublicKey, Signature, PrependSignature
from src.util.type_checking import strictdataclass, is_type_List, is_type_SpecificOptional
from src.types.sized_bytes import bytes32
from src.util.bin_methods import BinMethods
from src.util.ints import uint32


# TODO: Remove hack, this allows streaming these objects from binary
size_hints = {
    "PublicKey": PublicKey.PUBLIC_KEY_SIZE,
    "Signature": Signature.SIGNATURE_SIZE,
    "PrependSignature": PrependSignature.SIGNATURE_SIZE
}


def streamable(cls: Any):
    """
    This is a decorator for class definitions. It applies the strictdataclass decorator,
    which checks all types at construction. It also defines a simple serialization format,
    and adds parse, from bytes, stream, and serialize methods.

    Serialization format:
    - Each field is serialized in order, by calling parse/serialize.
    - For Lists, there is a 4 byte prefix for the list length.
    - For Optionals, there is a one byte prefix, 1 iff object is present, 0 iff not.

    All of the constituents must have parse/from_bytes, and stream/serialize and therefore
    be of fixed size. For example, int cannot be a constituent since it is not a fixed size,
    whereas uint32 can be.

    Furthermore, a get_hash() member is added, which performs a serialization and a sha256.

    This class is used for deterministic serialization and hashing, for consensus critical
    objects such as the block header.
    """

    class _Local:
        @classmethod
        def parse_one_item(cls: Type[cls.__name__], f_type: Type, f: BinaryIO):
            if is_type_List(f_type):
                inner_type: Type = f_type.__args__[0]
                full_list: List[inner_type] = []
                assert inner_type != List.__args__[0]
                list_size: uint32 = int.from_bytes(f.read(4), "big")
                for list_index in range(list_size):
                    full_list.append(cls.parse_one_item(inner_type, f))
                return full_list
            if is_type_SpecificOptional(f_type):
                inner_type: Type = f_type.__args__[0]
                is_present: bool = f.read(1) == bytes([1])
                if is_present:
                    return cls.parse_one_item(inner_type, f)
                else:
                    return None
            if hasattr(f_type, "parse"):
                return f_type.parse(f)
            if hasattr(f_type, "from_bytes") and size_hints[f_type.__name__]:
                return f_type.from_bytes(f.read(size_hints[f_type.__name__]))
            else:
                raise RuntimeError(f"Type {f_type} does not have parse")

        @classmethod
        def parse(cls: Type[cls.__name__], f: BinaryIO) -> cls.__name__:
            values = []
            for _, f_type in get_type_hints(cls).items():
                values.append(cls.parse_one_item(f_type, f))
            return cls(*values)

        def stream_one_item(self, f_type: Type, item, f: BinaryIO) -> None:
            if is_type_List(f_type):
                assert is_type_List(type(item))
                f.write(uint32(len(item)).to_bytes(4, "big"))
                inner_type: Type = f_type.__args__[0]
                assert inner_type != List.__args__[0]
                for element in item:
                    self.stream_one_item(inner_type, element, f)
            elif is_type_SpecificOptional(f_type):
                inner_type: Type = f_type.__args__[0]
                if item is None:
                    f.write(bytes([0]))
                else:
                    f.write(bytes([1]))
                    self.stream_one_item(inner_type, item, f)
            elif hasattr(f_type, "stream"):
                item.stream(f)
            elif hasattr(f_type, "serialize"):
                f.write(item.serialize())
            else:
                raise NotImplementedError(f"can't stream {item}, {f_type}")

        def stream(self, f: BinaryIO) -> None:
            for f_name, f_type in get_type_hints(self).items():
                self.stream_one_item(f_type, getattr(self, f_name), f)

        def get_hash(self) -> bytes32:
            return bytes32(sha256(self.serialize()).digest())

    cls1 = strictdataclass(cls)
    return type(cls.__name__, (cls1, BinMethods, _Local), {})
