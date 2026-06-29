#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

constexpr uint32_t kCompactVdfHeightChunkSize = 10000;

struct ProcessCompactVdfOptions {
    std::string db_path;
    std::string compact_vdf_path;
    std::string remote_compact_vdf_base_url;
    std::size_t batch_size{1000};
    unsigned thread_count{0};
    bool dry_run{false};
};

struct ProcessCompactVdfResult {
    std::size_t entries_total{};
    std::size_t entries_applied{};
    std::size_t blocks_processed{};
    std::size_t chunks_processed{};
    double elapsed_seconds{};
    double vdf_seconds{};
    double db_read_seconds{};
    double db_flush_seconds{};
    double wal_checkpoint_seconds{};
    double download_seconds{};
};

ProcessCompactVdfResult process_compact_vdf_file(const ProcessCompactVdfOptions& options);
ProcessCompactVdfResult process_compact_vdf_remote(const ProcessCompactVdfOptions& options);
