#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace streamable {

using u128 = __uint128_t;

class ParseError : public std::runtime_error {
  public:
    using runtime_error::runtime_error;
};

class Reader {
  public:
    explicit Reader(const std::vector<uint8_t>& data) : data_(data), pos_(0) {}

    size_t remaining() const { return data_.size() - pos_; }
    size_t position() const { return pos_; }
    const std::vector<uint8_t>& buffer() const { return data_; }

    void read_exact(uint8_t* out, size_t len) {
        if (pos_ + len > data_.size()) {
            throw ParseError("unexpected end of buffer at offset " + std::to_string(pos_));
        }
        std::copy(data_.begin() + static_cast<std::ptrdiff_t>(pos_),
                  data_.begin() + static_cast<std::ptrdiff_t>(pos_ + len), out);
        pos_ += len;
    }

    uint8_t read_u8() {
        uint8_t v{};
        read_exact(&v, 1);
        return v;
    }

    uint16_t read_u16_be() {
        uint8_t b[2]{};
        read_exact(b, 2);
        return static_cast<uint16_t>((static_cast<uint16_t>(b[0]) << 8) | b[1]);
    }

    uint32_t read_u32_be() {
        uint8_t b[4]{};
        read_exact(b, 4);
        return (static_cast<uint32_t>(b[0]) << 24) | (static_cast<uint32_t>(b[1]) << 16) |
               (static_cast<uint32_t>(b[2]) << 8) | static_cast<uint32_t>(b[3]);
    }

    uint64_t read_u64_be() {
        uint8_t b[8]{};
        read_exact(b, 8);
        uint64_t v = 0;
        for (int i = 0; i < 8; ++i) {
            v = (v << 8) | b[i];
        }
        return v;
    }

    u128 read_u128_be() {
        return (static_cast<u128>(read_u64_be()) << 64) | read_u64_be();
    }

    bool read_bool() {
        const uint8_t v = read_u8();
        if (v == 0) {
            return false;
        }
        if (v == 1) {
            return true;
        }
        throw ParseError("invalid bool");
    }

    std::vector<uint8_t> read_bytes() {
        const uint32_t len = read_u32_be();
        std::vector<uint8_t> out(len);
        if (len > 0) {
            read_exact(out.data(), len);
        }
        return out;
    }

    void skip_bytes(std::size_t len) {
        if (pos_ + len > data_.size()) {
            throw ParseError("unexpected end of buffer at offset " + std::to_string(pos_));
        }
        pos_ += len;
    }

    template <size_t N>
    std::array<uint8_t, N> read_fixed() {
        std::array<uint8_t, N> out{};
        read_exact(out.data(), N);
        return out;
    }

  private:
    const std::vector<uint8_t>& data_;
    size_t pos_;
};

class Writer {
  public:
    void write_u8(uint8_t v) { out_.push_back(v); }

    void write_u16_be(uint16_t v) {
        write_u8(static_cast<uint8_t>((v >> 8) & 0xff));
        write_u8(static_cast<uint8_t>(v & 0xff));
    }

    void write_u32_be(uint32_t v) {
        write_u8(static_cast<uint8_t>((v >> 24) & 0xff));
        write_u8(static_cast<uint8_t>((v >> 16) & 0xff));
        write_u8(static_cast<uint8_t>((v >> 8) & 0xff));
        write_u8(static_cast<uint8_t>(v & 0xff));
    }

    void write_u64_be(uint64_t v) {
        for (int i = 7; i >= 0; --i) {
            write_u8(static_cast<uint8_t>((v >> (i * 8)) & 0xff));
        }
    }

    void write_u128_be(u128 v) {
        write_u64_be(static_cast<uint64_t>(v >> 64));
        write_u64_be(static_cast<uint64_t>(v));
    }

    void write_bool(bool v) { write_u8(v ? 1 : 0); }

    void write_bytes(const std::vector<uint8_t>& bytes) {
        if (bytes.size() > std::numeric_limits<uint32_t>::max()) {
            throw ParseError("bytes too large");
        }
        write_u32_be(static_cast<uint32_t>(bytes.size()));
        out_.insert(out_.end(), bytes.begin(), bytes.end());
    }

    void write_bytes_raw(const std::vector<uint8_t>& bytes) { out_.insert(out_.end(), bytes.begin(), bytes.end()); }

    template <size_t N>
    void write_fixed(const std::array<uint8_t, N>& bytes) {
        out_.insert(out_.end(), bytes.begin(), bytes.end());
    }

    const std::vector<uint8_t>& bytes() const { return out_; }
    std::vector<uint8_t> take() { return std::move(out_); }

  private:
    std::vector<uint8_t> out_;
};

}  // namespace streamable
