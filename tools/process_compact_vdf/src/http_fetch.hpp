#pragma once

#include <cstdint>
#include <string>

struct HttpFetchResult {
    long status_code{0};
    std::string body;
    std::string error;

    bool transport_ok() const { return error.empty(); }
};

HttpFetchResult http_get(const std::string& url, long timeout_seconds);
