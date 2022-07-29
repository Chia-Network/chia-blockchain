from __future__ import annotations

import dataclasses
import io
import pprint
from enum import Enum
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple, Type, TypeVar, Union, get_type_hints

from blspy import G1Element, G2Element, PrivateKey
from typing_extensions import Literal, get_args, get_origin

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import int64, int512, uint32, uint64, uint128

pp = pprint.PrettyPrinter(indent=1, width=120, compact=True)


class StreamableError(Exception):
    pass


class DefinitionError(StreamableError):
    pass


# TODO: Remove hack, this allows streaming these objects from binary
size_hints = {
    "PrivateKey": PrivateKey.PRIVATE_KEY_SIZE,
    "G1Element": G1Element.SIZE,
    "G2Element": G2Element.SIZE,
    "ConditionOpcode": 1,
}
unhashable_types = [
    "PrivateKey",
    "G1Element",
    "G2Element",
    "Program",
    "SerializedProgram",
]
# JSON does not support big ints, so these types must be serialized differently in JSON
big_ints = [uint64, int64, uint128, int512]

_T_Streamable = TypeVar("_T_Streamable", bound="Streamable")

ParseFunctionType = Callable[[BinaryIO], object]
StreamFunctionType = Callable[[object, BinaryIO], None]


# Caches to store the fields and (de)serialization methods for all available streamable classes.
FIELDS_FOR_STREAMABLE_CLASS: Dict[Type[object], Dict[str, Type[object]]] = {}
STREAM_FUNCTIONS_FOR_STREAMABLE_CLASS: Dict[Type[object], List[StreamFunctionType]] = {}
PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS: Dict[Type[object], List[ParseFunctionType]] = {}


def is_type_List(f_type: object) -> bool:
    return get_origin(f_type) == list or f_type == list


def is_type_SpecificOptional(f_type: object) -> bool:
    """
    Returns true for types such as Optional[T], but not Optional, or T.
    """
    return get_origin(f_type) == Union and get_args(f_type)[1]() is None


def is_type_Tuple(f_type: object) -> bool:
    return get_origin(f_type) == tuple or f_type == tuple


def dataclass_from_dict(klass: Type[Any], d: Any) -> Any:
    """
    Converts a dictionary based on a dataclass, into an instance of that dataclass.
    Recursively goes through lists, optionals, and dictionaries.
    """
    if is_type_SpecificOptional(klass):
        # Type is optional, data is either None, or Any
        if d is None:
            return None
        return dataclass_from_dict(get_args(klass)[0], d)
    elif is_type_Tuple(klass):
        # Type is tuple, can have multiple different types inside
        i = 0
        klass_properties = []
        for item in d:
            klass_properties.append(dataclass_from_dict(klass.__args__[i], item))
            i = i + 1
        return tuple(klass_properties)
    elif dataclasses.is_dataclass(klass):
        # Type is a dataclass, data is a dictionary
        hints = get_type_hints(klass)
        fieldtypes = {f.name: hints.get(f.name, f.type) for f in dataclasses.fields(klass)}
        return klass(**{f: dataclass_from_dict(fieldtypes[f], d[f]) for f in d})
    elif is_type_List(klass):
        # Type is a list, data is a list
        return [dataclass_from_dict(get_args(klass)[0], item) for item in d]
    elif issubclass(klass, bytes):
        # Type is bytes, data is a hex string
        return klass(hexstr_to_bytes(d))
    elif klass.__name__ in unhashable_types:
        # Type is unhashable (bls type), so cast from hex string
        if hasattr(klass, "from_bytes_unchecked"):
            from_bytes_method: Callable[[bytes], Any] = klass.from_bytes_unchecked
        else:
            from_bytes_method = klass.from_bytes
        return from_bytes_method(hexstr_to_bytes(d))
    else:
        # Type is a primitive, cast with correct class
        return klass(d)


def recurse_jsonify(d: Any) -> Any:
    """
    Makes bytes objects and unhashable types into strings with 0x, and makes large ints into
    strings.
    """
    if dataclasses.is_dataclass(d):
        new_dict = {}
        for field in dataclasses.fields(d):
            new_dict[field.name] = recurse_jsonify(getattr(d, field.name))
        return new_dict

    elif isinstance(d, list) or isinstance(d, tuple):
        new_list = []
        for item in d:
            new_list.append(recurse_jsonify(item))
        return new_list

    elif isinstance(d, dict):
        new_dict = {}
        for name, val in d.items():
            new_dict[name] = recurse_jsonify(val)
        return new_dict

    elif type(d).__name__ in unhashable_types or issubclass(type(d), bytes):
        return f"0x{bytes(d).hex()}"
    elif isinstance(d, Enum):
        return d.name
    elif isinstance(d, bool):
        return d
    elif isinstance(d, int):
        return int(d)
    elif d is None or type(d) == str:
        return d
    raise ValueError(f"failed to jsonify {d} (type: {type(d)})")


def parse_bool(f: BinaryIO) -> bool:
    bool_byte = f.read(1)
    assert bool_byte is not None and len(bool_byte) == 1  # Checks for EOF
    if bool_byte == bytes([0]):
        return False
    elif bool_byte == bytes([1]):
        return True
    else:
        raise ValueError("Bool byte must be 0 or 1")


def parse_uint32(f: BinaryIO, byteorder: Literal["little", "big"] = "big") -> uint32:
    size_bytes = f.read(4)
    assert size_bytes is not None and len(size_bytes) == 4  # Checks for EOF
    return uint32(int.from_bytes(size_bytes, byteorder))


def write_uint32(f: BinaryIO, value: uint32, byteorder: Literal["little", "big"] = "big") -> None:
    f.write(value.to_bytes(4, byteorder))


def parse_optional(f: BinaryIO, parse_inner_type_f: ParseFunctionType) -> Optional[object]:
    is_present_bytes = f.read(1)
    assert is_present_bytes is not None and len(is_present_bytes) == 1  # Checks for EOF
    if is_present_bytes == bytes([0]):
        return None
    elif is_present_bytes == bytes([1]):
        return parse_inner_type_f(f)
    else:
        raise ValueError("Optional must be 0 or 1")


def parse_bytes(f: BinaryIO) -> bytes:
    list_size = parse_uint32(f)
    bytes_read = f.read(list_size)
    assert bytes_read is not None and len(bytes_read) == list_size
    return bytes_read


def parse_list(f: BinaryIO, parse_inner_type_f: ParseFunctionType) -> List[object]:
    full_list: List[object] = []
    # wjb assert inner_type != get_args(List)[0]
    list_size = parse_uint32(f)
    for list_index in range(list_size):
        full_list.append(parse_inner_type_f(f))
    return full_list


def parse_tuple(f: BinaryIO, list_parse_inner_type_f: List[ParseFunctionType]) -> Tuple[object, ...]:
    full_list: List[object] = []
    for parse_f in list_parse_inner_type_f:
        full_list.append(parse_f(f))
    return tuple(full_list)


def parse_size_hints(f: BinaryIO, f_type: Type[Any], bytes_to_read: int, unchecked: bool) -> Any:
    bytes_read = f.read(bytes_to_read)
    assert bytes_read is not None and len(bytes_read) == bytes_to_read
    if unchecked:
        return f_type.from_bytes_unchecked(bytes_read)
    else:
        return f_type.from_bytes(bytes_read)


def parse_str(f: BinaryIO) -> str:
    str_size = parse_uint32(f)
    str_read_bytes = f.read(str_size)
    assert str_read_bytes is not None and len(str_read_bytes) == str_size  # Checks for EOF
    return bytes.decode(str_read_bytes, "utf-8")


def stream_optional(stream_inner_type_func: StreamFunctionType, item: Any, f: BinaryIO) -> None:
    if item is None:
        f.write(bytes([0]))
    else:
        f.write(bytes([1]))
        stream_inner_type_func(item, f)


def stream_bytes(item: Any, f: BinaryIO) -> None:
    write_uint32(f, uint32(len(item)))
    f.write(item)


def stream_list(stream_inner_type_func: StreamFunctionType, item: Any, f: BinaryIO) -> None:
    write_uint32(f, uint32(len(item)))
    for element in item:
        stream_inner_type_func(element, f)


def stream_tuple(stream_inner_type_funcs: List[StreamFunctionType], item: Any, f: BinaryIO) -> None:
    assert len(stream_inner_type_funcs) == len(item)
    for i in range(len(item)):
        stream_inner_type_funcs[i](item[i], f)


def stream_str(item: Any, f: BinaryIO) -> None:
    str_bytes = item.encode("utf-8")
    write_uint32(f, uint32(len(str_bytes)))
    f.write(str_bytes)


def stream_bool(item: Any, f: BinaryIO) -> None:
    f.write(int(item).to_bytes(1, "big"))


def stream_streamable(item: object, f: BinaryIO) -> None:
    getattr(item, "stream")(f)


def stream_byte_convertible(item: object, f: BinaryIO) -> None:
    f.write(getattr(item, "__bytes__")())


def streamable(cls: Type[_T_Streamable]) -> Type[_T_Streamable]:
    """
    This decorator forces correct streamable protocol syntax/usage and populates the caches for types hints and
    (de)serialization methods for all members of the class. The correct usage is:

    @streamable
    @dataclass(frozen=True)
    class Example(Streamable):
        ...

    The order how the decorator are applied and the inheritance from Streamable are forced. The explicit inheritance is
    required because mypy doesn't analyse the type returned by decorators, so we can't just inherit from inside the
    decorator. The dataclass decorator is required to fetch type hints, let mypy validate constructor calls and restrict
    direct modification of objects by `frozen=True`.
    """

    correct_usage_string: str = (
        "Correct usage is:\n\n@streamable\n@dataclass(frozen=True)\nclass Example(Streamable):\n    ..."
    )

    if not dataclasses.is_dataclass(cls):
        raise DefinitionError(f"@dataclass(frozen=True) required first. {correct_usage_string}")

    try:
        # Ignore mypy here because we especially want to access a not available member to test if
        # the dataclass is frozen.
        object.__new__(cls)._streamable_test_if_dataclass_frozen_ = None  # type: ignore[attr-defined]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise DefinitionError(f"dataclass needs to be frozen. {correct_usage_string}")

    if not issubclass(cls, Streamable):
        raise DefinitionError(f"Streamable inheritance required. {correct_usage_string}")

    stream_functions = []
    parse_functions = []
    try:
        hints = get_type_hints(cls)
        fields = {field.name: hints.get(field.name, field.type) for field in dataclasses.fields(cls)}
    except Exception:
        fields = {}

    FIELDS_FOR_STREAMABLE_CLASS[cls] = fields

    for _, f_type in fields.items():
        stream_functions.append(cls.function_to_stream_one_item(f_type))
        parse_functions.append(cls.function_to_parse_one_item(f_type))

    STREAM_FUNCTIONS_FOR_STREAMABLE_CLASS[cls] = stream_functions
    PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS[cls] = parse_functions
    return cls


class Streamable:
    """
    This class defines a simple serialization format, and adds methods to parse from/to bytes and json. It also
    validates and parses all fields at construction in ´__post_init__` to make sure all fields have the correct type
    and can be streamed/parsed properly.

    The available primitives are:
    * Sized ints serialized in big endian format, e.g. uint64
    * Sized bytes serialized in big endian format, e.g. bytes32
    * BLS public keys serialized in bls format (48 bytes)
    * BLS signatures serialized in bls format (96 bytes)
    * bool serialized into 1 byte (0x01 or 0x00)
    * bytes serialized as a 4 byte size prefix and then the bytes.
    * ConditionOpcode is serialized as a 1 byte value.
    * str serialized as a 4 byte size prefix and then the utf-8 representation in bytes.

    An item is one of:
    * primitive
    * Tuple[item1, .. itemx]
    * List[item1, .. itemx]
    * Optional[item]
    * Custom item

    A streamable must be a Tuple at the root level (although a dataclass is used here instead).
    Iters are serialized in the following way:

    1. A tuple of x items is serialized by appending the serialization of each item.
    2. A List is serialized into a 4 byte size prefix (number of items) and the serialization of each item.
    3. An Optional is serialized into a 1 byte prefix of 0x00 or 0x01, and if it's one, it's followed by the
       serialization of the item.
    4. A Custom item is serialized by calling the .parse method, passing in the stream of bytes into it. An example is
       a CLVM program.

    All of the constituents must have parse/from_bytes, and stream/__bytes__ and therefore
    be of fixed size. For example, int cannot be a constituent since it is not a fixed size,
    whereas uint32 can be.

    Furthermore, a get_hash() member is added, which performs a serialization and a sha256.

    This class is used for deterministic serialization and hashing, for consensus critical
    objects such as the block header.

    Make sure to use the streamable decorator when inheriting from the Streamable class to prepare the streaming caches.
    """

    def post_init_parse(self, item: Any, f_name: str, f_type: Type[Any]) -> Any:
        if is_type_List(f_type):
            collected_list: List[Any] = []
            inner_type: Type[Any] = get_args(f_type)[0]
            # wjb assert inner_type != get_args(List)[0]  # type: ignore
            if not is_type_List(type(item)):
                raise ValueError(f"Wrong type for {f_name}, need a list.")
            for el in item:
                collected_list.append(self.post_init_parse(el, f_name, inner_type))
            return collected_list
        if is_type_SpecificOptional(f_type):
            if item is None:
                return None
            else:
                inner_type: Type = get_args(f_type)[0]  # type: ignore
                return self.post_init_parse(item, f_name, inner_type)
        if is_type_Tuple(f_type):
            collected_list = []
            if not is_type_Tuple(type(item)) and not is_type_List(type(item)):
                raise ValueError(f"Wrong type for {f_name}, need a tuple.")
            if len(item) != len(get_args(f_type)):
                raise ValueError(f"Wrong number of elements in tuple {f_name}.")
            for i in range(len(item)):
                inner_type = get_args(f_type)[i]
                tuple_item = item[i]
                collected_list.append(self.post_init_parse(tuple_item, f_name, inner_type))
            return tuple(collected_list)
        if not isinstance(item, f_type):
            try:
                item = f_type(item)
            except (TypeError, AttributeError, ValueError):
                if hasattr(f_type, "from_bytes_unchecked"):
                    from_bytes_method: Callable[[bytes], Any] = f_type.from_bytes_unchecked
                else:
                    from_bytes_method = f_type.from_bytes
                try:
                    item = from_bytes_method(item)
                except Exception:
                    item = from_bytes_method(bytes(item))
        if not isinstance(item, f_type):
            raise ValueError(f"Wrong type for {f_name}")
        return item

    def __post_init__(self) -> None:
        try:
            fields = FIELDS_FOR_STREAMABLE_CLASS[type(self)]
        except Exception:
            fields = {}
        data = self.__dict__
        for (f_name, f_type) in fields.items():
            if f_name not in data:
                raise ValueError(f"Field {f_name} not present")
            try:
                if not isinstance(data[f_name], f_type):
                    object.__setattr__(self, f_name, self.post_init_parse(data[f_name], f_name, f_type))
            except TypeError:
                # Throws a TypeError because we cannot call isinstance for subscripted generics like Optional[int]
                object.__setattr__(self, f_name, self.post_init_parse(data[f_name], f_name, f_type))

    @classmethod
    def function_to_parse_one_item(cls, f_type: Type[Any]) -> ParseFunctionType:
        """
        This function returns a function taking one argument `f: BinaryIO` that parses
        and returns a value of the given type.
        """
        inner_type: Type[Any]
        if f_type is bool:
            return parse_bool
        if is_type_SpecificOptional(f_type):
            inner_type = get_args(f_type)[0]
            parse_inner_type_f = cls.function_to_parse_one_item(inner_type)
            return lambda f: parse_optional(f, parse_inner_type_f)
        if hasattr(f_type, "parse"):
            # Ignoring for now as the proper solution isn't obvious
            return f_type.parse  # type: ignore[no-any-return]
        if f_type == bytes:
            return parse_bytes
        if is_type_List(f_type):
            inner_type = get_args(f_type)[0]
            parse_inner_type_f = cls.function_to_parse_one_item(inner_type)
            return lambda f: parse_list(f, parse_inner_type_f)
        if is_type_Tuple(f_type):
            inner_types = get_args(f_type)
            list_parse_inner_type_f = [cls.function_to_parse_one_item(_) for _ in inner_types]
            return lambda f: parse_tuple(f, list_parse_inner_type_f)
        if hasattr(f_type, "from_bytes_unchecked") and f_type.__name__ in size_hints:
            bytes_to_read = size_hints[f_type.__name__]
            return lambda f: parse_size_hints(f, f_type, bytes_to_read, unchecked=True)
        if hasattr(f_type, "from_bytes") and f_type.__name__ in size_hints:
            bytes_to_read = size_hints[f_type.__name__]
            return lambda f: parse_size_hints(f, f_type, bytes_to_read, unchecked=False)
        if f_type is str:
            return parse_str
        raise NotImplementedError(f"Type {f_type} does not have parse")

    @classmethod
    def parse(cls: Type[_T_Streamable], f: BinaryIO) -> _T_Streamable:
        # Create the object without calling __init__() to avoid unnecessary post-init checks in strictdataclass
        obj: _T_Streamable = object.__new__(cls)
        fields: Iterator[str] = iter(FIELDS_FOR_STREAMABLE_CLASS.get(cls, {}))
        values: Iterator[object] = (parse_f(f) for parse_f in PARSE_FUNCTIONS_FOR_STREAMABLE_CLASS[cls])
        for field, value in zip(fields, values):
            object.__setattr__(obj, field, value)

        # Use -1 as a sentinel value as it's not currently serializable
        if next(fields, -1) != -1:
            raise ValueError("Failed to parse incomplete Streamable object")
        if next(values, -1) != -1:
            raise ValueError("Failed to parse unknown data in Streamable object")
        return obj

    @classmethod
    def function_to_stream_one_item(cls, f_type: Type[Any]) -> StreamFunctionType:
        inner_type: Type[Any]
        if is_type_SpecificOptional(f_type):
            inner_type = get_args(f_type)[0]
            stream_inner_type_func = cls.function_to_stream_one_item(inner_type)
            return lambda item, f: stream_optional(stream_inner_type_func, item, f)
        elif f_type == bytes:
            return stream_bytes
        elif hasattr(f_type, "stream"):
            return stream_streamable
        elif hasattr(f_type, "__bytes__"):
            return stream_byte_convertible
        elif is_type_List(f_type):
            inner_type = get_args(f_type)[0]
            stream_inner_type_func = cls.function_to_stream_one_item(inner_type)
            return lambda item, f: stream_list(stream_inner_type_func, item, f)
        elif is_type_Tuple(f_type):
            inner_types = get_args(f_type)
            stream_inner_type_funcs = []
            for i in range(len(inner_types)):
                stream_inner_type_funcs.append(cls.function_to_stream_one_item(inner_types[i]))
            return lambda item, f: stream_tuple(stream_inner_type_funcs, item, f)
        elif f_type is str:
            return stream_str
        elif f_type is bool:
            return stream_bool
        else:
            raise NotImplementedError(f"can't stream {f_type}")

    def stream(self, f: BinaryIO) -> None:
        self_type = type(self)
        try:
            fields = FIELDS_FOR_STREAMABLE_CLASS[self_type]
            functions = STREAM_FUNCTIONS_FOR_STREAMABLE_CLASS[self_type]
        except Exception:
            fields = {}
            functions = []

        for field, stream_func in zip(fields, functions):
            stream_func(getattr(self, field), f)

    def get_hash(self) -> bytes32:
        return bytes32(std_hash(bytes(self)))

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        parsed = cls.parse(f)
        assert f.read() == b""
        return parsed

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self: Any) -> str:
        return pp.pformat(recurse_jsonify(self))

    def __repr__(self: Any) -> str:
        return pp.pformat(recurse_jsonify(self))

    def to_json_dict(self) -> Dict[str, Any]:
        ret: Dict[str, Any] = recurse_jsonify(self)
        return ret

    @classmethod
    def from_json_dict(cls: Any, json_dict: Dict[str, Any]) -> Any:
        return dataclass_from_dict(cls, json_dict)
