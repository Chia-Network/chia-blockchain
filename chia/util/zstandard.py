# The intended purpose is to know if this is too big before doing the decompression,
# in order to prevent eg. denial-of-service attacks if swap would be needed.

# https://www.rfc-editor.org/rfc/rfc8878

# Heavily influenced by:
# https://github.com/facebook/zstd/blob/dev/lib/decompress/zstd_decompress.c


# The specific error values
ZSTD_ERR_NOT_ENOUGH_BYTES = -1
ZSTD_ERR_NO_MAGIC_HEADER = -2
ZSTD_ERR_RESERVED_BIT_SET = -3
ZSTD_ERR_SINGLESEGMENT_NOT_SET = -4  # Not a zstd error, but we don't handle it


def get_decompressed_size(data: bytes) -> int:
    """
    Reads the zstd header and returns the decompressed size as if these bytes were passed to zstd.decompress()
    If negative, the data was not valid Zstandard, or not single segment
    """

    try:

        # Magic header (little endian)
        if data[:4] != bytes([0x28, 0xB5, 0x2F, 0xFD]):
            return ZSTD_ERR_NO_MAGIC_HEADER

        # Frame Header
        fhdByte = data[4]
        dictIDSizeCode = fhdByte & 3
        # checksumFlag = (fhdByte >> 2) & 1
        singleSegment = (fhdByte >> 5) & 1
        fcsID = fhdByte >> 6

        if (fhdByte & 0x08) != 0:
            # print("Reserved bit, must be zero")
            return ZSTD_ERR_RESERVED_BIT_SET

        if singleSegment != 1:
            # print("For Chia, must be singlesegment")
            return ZSTD_ERR_SINGLESEGMENT_NOT_SET

        pos = 4 + 1  # magic bytes + frame header byte

        # not interested in the dictionary id, but need to know the size in order to skip it
        if dictIDSizeCode == 0:
            pos += 0
        elif dictIDSizeCode == 1:
            pos += 1
        elif dictIDSizeCode == 2:
            pos += 2
        elif dictIDSizeCode == 3:
            pos += 4

        sz: int = 0

        # The size is represented in little endian
        if fcsID == 0:
            if singleSegment:
                sz = data[pos]
        elif fcsID == 1:
            sz = data[pos + 1] << 8
            sz += data[pos + 0]
            sz += 256
        elif fcsID == 2:
            sz = data[pos + 3] << 24
            sz += data[pos + 2] << 16
            sz += data[pos + 1] << 8
            sz += data[pos + 0]
        elif fcsID == 3:
            sz = data[pos + 7] << 56
            sz += data[pos + 6] << 48
            sz += data[pos + 5] << 40
            sz += data[pos + 4] << 32
            sz += data[pos + 3] << 24
            sz += data[pos + 2] << 16
            sz += data[pos + 1] << 8
            sz += data[pos + 0]

        return sz

    except IndexError:
        # Tried to read beyond 'data'
        return ZSTD_ERR_NOT_ENOUGH_BYTES
