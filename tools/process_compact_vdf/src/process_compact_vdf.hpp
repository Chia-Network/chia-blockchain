#pragma once

#include <cstddef>
#include <string>

struct ProcessCompactVdfOptions {
    std::string db_path;
    std::string compact_vdf_path;
    std::size_t batch_size{1000};
    unsigned thread_count{0};
    bool dry_run{false};
};

struct ProcessCompactVdfResult {
    std::size_t entries_total{};
    std::size_t entries_applied{};
    std::size_t blocks_processed{};
    double elapsed_seconds{};
    double vdf_seconds{};
    double db_read_seconds{};
    double db_flush_seconds{};
    double wal_checkpoint_seconds{};
};

ProcessCompactVdfResult process_compact_vdf_file(const ProcessCompactVdfOptions& options);
