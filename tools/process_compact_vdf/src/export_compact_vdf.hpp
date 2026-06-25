#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

struct ExportCompactVdfOptions {
    std::string db_path;
    std::size_t chunk_size{10000};
    std::string output_dir{"."};
};

struct ExportCompactVdfResult {
    uint32_t max_height{};
    std::size_t files_written{};
    std::size_t entries_written{};
    std::size_t blocks_scanned{};
    double elapsed_seconds{};
};

ExportCompactVdfResult export_compact_vdf_files(const ExportCompactVdfOptions& options);
