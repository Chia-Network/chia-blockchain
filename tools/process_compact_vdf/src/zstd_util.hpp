#pragma once

#include <cstdint>
#include <vector>

namespace zstd_util {

std::vector<uint8_t> decompress(const std::vector<uint8_t>& compressed);
std::vector<uint8_t> compress(const std::vector<uint8_t>& data);

}  // namespace zstd_util
