#include "clvm_length.hpp"

#include <stdexcept>

namespace clvm_length {
namespace {

constexpr uint8_t kConsBoxMarker = 0xff;
constexpr uint8_t kBackReference = 0xfe;
constexpr uint8_t kMaxSingleByte = 0x7f;

class ParseError : public std::runtime_error {
  public:
    using runtime_error::runtime_error;
};

std::size_t leading_ones(uint8_t value) {
    std::size_t count = 0;
    for (int bit = 7; bit >= 0; --bit) {
        if ((value & (1u << bit)) != 0) {
            ++count;
        } else {
            break;
        }
    }
    return count;
}

std::size_t decode_size(const std::vector<uint8_t>& data, std::size_t& pos, uint8_t initial_b) {
    if ((initial_b & 0x80) == 0) {
        throw ParseError("invalid CLVM atom size prefix");
    }

    const std::size_t prefix_len = leading_ones(initial_b);
    if (prefix_len >= 8) {
        throw ParseError("invalid CLVM atom size prefix");
    }

    const uint8_t bit_mask = static_cast<uint8_t>(0xff >> prefix_len);
    uint64_t atom_size = initial_b & bit_mask;
    for (std::size_t i = 1; i < prefix_len; ++i) {
        if (pos >= data.size()) {
            throw ParseError("unexpected end of buffer");
        }
        atom_size = (atom_size << 8) + data[pos++];
    }
    if (atom_size >= 0x400000000ULL) {
        throw ParseError("CLVM atom too large");
    }
    return static_cast<std::size_t>(atom_size);
}

std::size_t serialized_length_trusted_impl(const std::vector<uint8_t>& data, std::size_t start) {
    std::size_t pos = start;
    std::size_t ops_counter = 1;

    while (ops_counter > 0) {
        if (pos >= data.size()) {
            throw ParseError("unexpected end of buffer");
        }
        ops_counter -= 1;
        const uint8_t marker = data[pos++];

        if (marker == kConsBoxMarker) {
            ops_counter += 2;
            continue;
        }

        if (marker == kBackReference) {
            if (pos >= data.size()) {
                throw ParseError("unexpected end of buffer");
            }
            const uint8_t first_byte = data[pos++];
            if (first_byte > kMaxSingleByte) {
                const std::size_t path_size = decode_size(data, pos, first_byte);
                pos += path_size;
            }
            if (pos > data.size()) {
                throw ParseError("unexpected end of buffer");
            }
            continue;
        }

        if (marker == 0x80 || marker <= kMaxSingleByte) {
            continue;
        }

        const std::size_t blob_size = decode_size(data, pos, marker);
        pos += blob_size;
        if (pos > data.size()) {
            throw ParseError("unexpected end of buffer");
        }
    }

    return pos - start;
}

}  // namespace

std::size_t serialized_length_trusted(const std::vector<uint8_t>& data, std::size_t offset) {
    return serialized_length_trusted_impl(data, offset);
}

}  // namespace clvm_length
