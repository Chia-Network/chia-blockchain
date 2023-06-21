from __future__ import annotations

from typing import ClassVar

from chia.util.struct_stream import StructStream, parse_metadata_from_name


@parse_metadata_from_name
class int8(StructStream):
    MINIMUM: ClassVar[int8]
    MAXIMUM: ClassVar[int8]


@parse_metadata_from_name
class uint8(StructStream):
    MINIMUM: ClassVar[uint8]
    MAXIMUM: ClassVar[uint8]


@parse_metadata_from_name
class int16(StructStream):
    MINIMUM: ClassVar[int16]
    MAXIMUM: ClassVar[int16]


@parse_metadata_from_name
class uint16(StructStream):
    MINIMUM: ClassVar[uint16]
    MAXIMUM: ClassVar[uint16]


@parse_metadata_from_name
class int32(StructStream):
    MINIMUM: ClassVar[int32]
    MAXIMUM: ClassVar[int32]


@parse_metadata_from_name
class uint32(StructStream):
    MINIMUM: ClassVar[uint32]
    MAXIMUM: ClassVar[uint32]


@parse_metadata_from_name
class int64(StructStream):
    MINIMUM: ClassVar[int64]
    MAXIMUM: ClassVar[int64]


@parse_metadata_from_name
class uint64(StructStream):
    MINIMUM: ClassVar[uint64]
    MAXIMUM: ClassVar[uint64]


@parse_metadata_from_name
class uint128(StructStream):
    MINIMUM: ClassVar[uint128]
    MAXIMUM: ClassVar[uint128]


class int512(StructStream):
    PACK = None

    # Uses 65 bytes to fit in the sign bit
    SIZE = 65
    BITS = 512
    SIGNED = True

    # note that the boundaries for int512 is not what you might expect. We
    # encode these with one extra byte, but only allow a range of
    # [-INT512_MAX, INT512_MAX]
    MINIMUM: ClassVar[int512] = -(2**BITS) + 1
    MAXIMUM: ClassVar[int512] = (2**BITS) - 1


int512.MINIMUM = int512(int512.MINIMUM)
int512.MAXIMUM = int512(int512.MAXIMUM)
