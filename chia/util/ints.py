from __future__ import annotations

from chia.util.struct_stream import StructStream, parse_metadata_from_name


@parse_metadata_from_name
class int8(StructStream):
    MINIMUM: int8
    MAXIMUM: int8


@parse_metadata_from_name
class uint8(StructStream):
    MINIMUM: uint8
    MAXIMUM: uint8


@parse_metadata_from_name
class int16(StructStream):
    MINIMUM: int16
    MAXIMUM: int16


@parse_metadata_from_name
class uint16(StructStream):
    MINIMUM: uint16
    MAXIMUM: uint16


@parse_metadata_from_name
class int32(StructStream):
    MINIMUM: int32
    MAXIMUM: int32


@parse_metadata_from_name
class uint32(StructStream):
    MINIMUM: uint32
    MAXIMUM: uint32


@parse_metadata_from_name
class int64(StructStream):
    MINIMUM: int64
    MAXIMUM: int64


@parse_metadata_from_name
class uint64(StructStream):
    MINIMUM: uint64
    MAXIMUM: uint64


@parse_metadata_from_name
class uint128(StructStream):
    MINIMUM: uint128
    MAXIMUM: uint128


class int512(StructStream):
    PACK = None

    # Uses 65 bytes to fit in the sign bit
    SIZE = 65
    BITS = 512
    SIGNED = True

    # note that the boundaries for int512 is not what you might expect. We
    # encode these with one extra byte, but only allow a range of
    # [-INT512_MAX, INT512_MAX]
    MAXIMUM: int512 = 2**BITS - 1
    MINIMUM: int512 = -(2**BITS) + 1


int512.MINIMUM = int512(int512.MINIMUM)
int512.MAXIMUM = int512(int512.MAXIMUM)
