#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace clvm_length {

// Returns the byte length of a CLVM-serialized program starting at offset.
// Matches clvmr::serialized_length_from_bytes_trusted().
std::size_t serialized_length_trusted(const std::vector<uint8_t>& data, std::size_t offset);

}  // namespace clvm_length
