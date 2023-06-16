from __future__ import annotations

from chia.util.struct_stream import StructStream, parse_metadata_from_name


@parse_metadata_from_name
class int8(StructStream):
    pass


@parse_metadata_from_name
class uint8(StructStream):
    pass


@parse_metadata_from_name
class int16(StructStream):
    pass


@parse_metadata_from_name
class uint16(StructStream):
    pass


@parse_metadata_from_name
class int32(StructStream):
    pass


@parse_metadata_from_name
class uint32(StructStream):
    pass


@parse_metadata_from_name
class int64(StructStream):
    pass


@parse_metadata_from_name
class uint64(StructStream):
    pass


@parse_metadata_from_name
class uint128(StructStream):
    pass


class int512(StructStream):
    PACK = None

    # Uses 65 bytes to fit in the sign bit
    SIZE = 65
    BITS = 512
    SIGNED = True

    # note that the boundaries for int512 is not what you might expect. We
    # encode these with one extra byte, but only allow a range of
    # [-INT512_MAX, INT512_MAX]
    MAXIMUM_EXCLUSIVE = 2**BITS
    MINIMUM = -(2**BITS) + 1
