#include "mini_json.hpp"

#include <cctype>
#include <stdexcept>

namespace mini_json {
namespace {

class Parser {
  public:
    explicit Parser(const std::string& text) : text_(text) {}

    Object parse_object() {
        expect('{');
        Object obj;
        if (peek() == '}') {
            ++pos_;
            return obj;
        }
        while (true) {
            const std::string key = parse_string();
            expect(':');
            if (peek() == '"') {
                obj.strings_[key] = parse_string();
            } else if (peek() == '{') {
                obj.objects_[key] = parse_object();
            } else if (std::isdigit(static_cast<unsigned char>(peek())) || peek() == '-') {
                obj.numbers_[key] = parse_uint64();
            } else {
                throw std::runtime_error("unsupported json value");
            }
            if (peek() == ',') {
                ++pos_;
                continue;
            }
            expect('}');
            return obj;
        }
    }

  private:
    char peek() {
        skip_ws();
        return pos_ < text_.size() ? text_[pos_] : '\0';
    }

    void expect(char c) {
        skip_ws();
        if (pos_ >= text_.size() || text_[pos_] != c) {
            throw std::runtime_error("json parse error");
        }
        ++pos_;
    }

    void skip_ws() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_]))) {
            ++pos_;
        }
    }

    std::string parse_string() {
        expect('"');
        std::string out;
        while (pos_ < text_.size() && text_[pos_] != '"') {
            if (text_[pos_] == '\\') {
                ++pos_;
                if (pos_ >= text_.size()) {
                    throw std::runtime_error("invalid escape");
                }
            }
            out.push_back(text_[pos_++]);
        }
        expect('"');
        return out;
    }

    uint64_t parse_uint64() {
        skip_ws();
        size_t start = pos_;
        while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) {
            ++pos_;
        }
        if (start == pos_) {
            throw std::runtime_error("expected number");
        }
        return std::stoull(text_.substr(start, pos_ - start));
    }

    const std::string& text_;
    size_t pos_{0};
};

}  // namespace

Object Object::parse(const std::string& text) {
    Parser parser(text);
    return parser.parse_object();
}

bool Object::has(const std::string& key) const {
    return strings_.count(key) > 0 || numbers_.count(key) > 0 || objects_.count(key) > 0;
}

std::optional<std::string> Object::get_string(const std::string& key) const {
    const auto it = strings_.find(key);
    if (it == strings_.end()) {
        return std::nullopt;
    }
    return it->second;
}

std::optional<uint64_t> Object::get_uint64(const std::string& key) const {
    const auto it = numbers_.find(key);
    if (it == numbers_.end()) {
        return std::nullopt;
    }
    return it->second;
}

const Object* Object::get_object(const std::string& key) const {
    const auto it = objects_.find(key);
    if (it == objects_.end()) {
        return nullptr;
    }
    return &it->second;
}

}  // namespace mini_json
