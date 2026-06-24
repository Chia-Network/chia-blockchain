#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

namespace mini_json {

// Minimal JSON object parser for compactvdf lines: string keys to string or number values.
class Object {
  public:
    static Object parse(const std::string& text);
    bool has(const std::string& key) const;
    std::optional<std::string> get_string(const std::string& key) const;
    std::optional<uint64_t> get_uint64(const std::string& key) const;
    const Object* get_object(const std::string& key) const;

    std::unordered_map<std::string, std::string> strings_;
    std::unordered_map<std::string, uint64_t> numbers_;
    std::unordered_map<std::string, Object> objects_;
};

}  // namespace mini_json
