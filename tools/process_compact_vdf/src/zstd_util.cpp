#include "zstd_util.hpp"

#include <zstd.h>

#include <stdexcept>

namespace zstd_util {

std::vector<uint8_t> decompress(const std::vector<uint8_t>& compressed) {
    if (compressed.empty()) {
        return {};
    }

    const unsigned long long frame_size = ZSTD_getFrameContentSize(compressed.data(), compressed.size());
    if (frame_size == ZSTD_CONTENTSIZE_ERROR) {
        throw std::runtime_error("invalid zstd frame");
    }

    std::vector<uint8_t> out;
    if (frame_size != ZSTD_CONTENTSIZE_UNKNOWN) {
        out.resize(static_cast<size_t>(frame_size));
        const size_t ret = ZSTD_decompress(out.data(), out.size(), compressed.data(), compressed.size());
        if (ZSTD_isError(ret)) {
            throw std::runtime_error(std::string("zstd decompress failed: ") + ZSTD_getErrorName(ret));
        }
        out.resize(ret);
        return out;
    }

    size_t capacity = compressed.size() * 4;
    if (capacity < 1024 * 1024) {
        capacity = 1024 * 1024;
    }
    while (capacity <= 256 * 1024 * 1024) {
        out.resize(capacity);
        const size_t ret = ZSTD_decompress(out.data(), out.size(), compressed.data(), compressed.size());
        if (!ZSTD_isError(ret)) {
            out.resize(ret);
            return out;
        }
        if (ZSTD_getErrorCode(ret) != ZSTD_error_dstSize_tooSmall) {
            throw std::runtime_error(std::string("zstd decompress failed: ") + ZSTD_getErrorName(ret));
        }
        capacity *= 2;
    }
    throw std::runtime_error("zstd decompress output too large");
}

std::vector<uint8_t> compress(const std::vector<uint8_t>& data) {
    if (data.empty()) {
        return {};
    }
    const size_t bound = ZSTD_compressBound(data.size());
    std::vector<uint8_t> out(bound);
    const size_t ret = ZSTD_compress(out.data(), out.size(), data.data(), data.size(), ZSTD_defaultCLevel());
    if (ZSTD_isError(ret)) {
        throw std::runtime_error(std::string("zstd compress failed: ") + ZSTD_getErrorName(ret));
    }
    out.resize(ret);
    return out;
}

}  // namespace zstd_util
