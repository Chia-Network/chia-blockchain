from __future__ import annotations

from typing import Final

# The intended purpose is to know if this is too big before doing the decompression,
# in order to prevent eg. denial-of-service attacks if swap would be needed.

# RFC 8878 Zstandard Compression
# https://www.rfc-editor.org/rfc/rfc8878
#
# Heavily influenced by:
# https://github.com/facebook/zstd/blob/dev/lib/decompress/zstd_decompress.c


# These values are from the zstd module
ZSTD_MAGICNUMBER: Final[int] = 0xFD2FB528
ZSTD_CONTENTSIZE_UNKNOWN: Final[int] = -1
ZSTD_WINDOWLOG_MAX: Final[int] = 31
ZSTD_WINDOWLOG_ABSOLUTEMIN: Final[int] = 10

# These are our own specific error values
# NB: value -1 is already used by ZSTD_CONTENTSIZE_UNKNOWN
ZSTD_ERR_NOT_ENOUGH_BYTES: Final[int] = -2
ZSTD_ERR_NO_MAGIC_HEADER: Final[int] = -3
ZSTD_ERR_RESERVED_BIT_SET: Final[int] = -4
ZSTD_ERR_WINDOW_TOO_LARGE: Final[int] = -5


# reads 16 bits, little endian
def _readLE16(src: bytes) -> int:
    i: int
    i = src[1] << 8
    i += src[0]
    return i


# reads 32 bits, little endian
def _readLE32(src: bytes) -> int:
    i: int
    i = src[3] << 24
    i += src[2] << 16
    i += src[1] << 8
    i += src[0]
    return i


# reads 64 bits, little endian
def _readLE64(src: bytes) -> int:
    i: int
    i = src[7] << 56
    i += src[6] << 48
    i += src[5] << 40
    i += src[4] << 32
    i += src[3] << 24
    i += src[2] << 16
    i += src[1] << 8
    i += src[0]
    return i


def get_decompressed_size(data: bytes) -> int:
    """
    Reads the zstd header and returns the decompressed size as if these bytes were passed to zstd.decompress()
    If negative, the data was not valid Zstandard, or the size is unknown (ZSTD_CONTENTSIZE_UNKNOWN)
    """

    try:
        if _readLE32(data) != ZSTD_MAGICNUMBER:
            return ZSTD_ERR_NO_MAGIC_HEADER

        # Frame Header
        fhdByte = data[4]
        dictIDSizeCode = fhdByte & 3
        # checksumFlag = (fhdByte >> 2) & 1
        singleSegment = (fhdByte >> 5) & 1
        fcsID = fhdByte >> 6

        # windowSize = 0
        # dictID = 0
        frameContentSize = ZSTD_CONTENTSIZE_UNKNOWN

        if (fhdByte & 0x08) != 0:
            # print("Reserved bit, must be zero")
            return ZSTD_ERR_RESERVED_BIT_SET

        pos: int = 4 + 1   # magic bytes + frame header byte

        if singleSegment == 0:
            wlByte = data[pos]
            pos += 1
            windowLog = (wlByte >> 3) + ZSTD_WINDOWLOG_ABSOLUTEMIN
            if windowLog > ZSTD_WINDOWLOG_MAX:
                return ZSTD_ERR_WINDOW_TOO_LARGE
            # windowSize = 1 << windowLog
            # windowSize += (windowSize >> 3) * (wlByte & 7)

        if dictIDSizeCode == 0:
            pos += 0
        elif dictIDSizeCode == 1:
            # dictID = data[pos]
            pos += 1
        elif dictIDSizeCode == 2:
            # dictID = _readLE16(data[pos:])
            pos += 2
        elif dictIDSizeCode == 3:
            # dictID = _readLE32(data[pos:])
            pos += 4

        if fcsID == 0:
            if singleSegment:
                frameContentSize = data[pos]
        elif fcsID == 1:
            frameContentSize = _readLE16(data[pos:])
            frameContentSize += 256
        elif fcsID == 2:
            frameContentSize = _readLE32(data[pos:])
        elif fcsID == 3:
            frameContentSize = _readLE64(data[pos:])

        # if singleSegment:
        #     windowSize = frameContentSize

        return frameContentSize

    except IndexError:
        # Tried to read beyond 'data'
        return ZSTD_ERR_NOT_ENOUGH_BYTES
