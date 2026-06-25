#include "export_compact_vdf.hpp"

#include "chia_protocol.hpp"
#include "db_v2.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace {

double seconds_since(const std::chrono::steady_clock::time_point& start) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

std::string compact_vdf_entry_to_json(const chia::CompactVdfEntry& entry) {
    std::ostringstream out;
    out << "{\"field_vdf\":" << static_cast<unsigned>(entry.field_vdf) << ",\"header_hash\":\"0x"
        << chia::bytes32_to_db_hex(entry.header_hash) << "\",\"witness\":\"0x"
        << chia::bytes_to_hex(entry.witness.data(), entry.witness.size()) << "\"";
    if (entry.sub_slot_index.has_value()) {
        out << ",\"sub_slot_index\":" << static_cast<unsigned>(*entry.sub_slot_index);
    }
    out << "}\n";
    return out.str();
}

std::string chunk_filename(uint32_t start_height, uint32_t end_height) {
    return "compactvdf-" + std::to_string(start_height) + "to" + std::to_string(end_height);
}

}  // namespace

ExportCompactVdfResult export_compact_vdf_files(const ExportCompactVdfOptions& options) {
    if (options.chunk_size == 0) {
        throw std::invalid_argument("chunk size must be greater than zero");
    }

    const auto total_start = std::chrono::steady_clock::now();
    ExportCompactVdfResult result;

    const std::filesystem::path output_dir = std::filesystem::absolute(options.output_dir);
    if (!std::filesystem::exists(output_dir)) {
        throw std::runtime_error("output directory does not exist: " + output_dir.string());
    }
    if (!std::filesystem::is_directory(output_dir)) {
        throw std::runtime_error("output path is not a directory: " + output_dir.string());
    }

    db_v2::Database db(options.db_path, true);
    db.ensure_v2();

    const auto max_height = db.max_main_chain_height();
    if (!max_height.has_value()) {
        result.elapsed_seconds = seconds_since(total_start);
        std::cout << "No main-chain blocks found; nothing to export\n";
        return result;
    }

    result.max_height = *max_height;
    std::cout << "Exporting witness_type 0 compact VDF proofs from main chain heights 0 to " << result.max_height
              << " in chunks of " << options.chunk_size << " to " << output_dir.string() << '\n';

    for (uint32_t start_height = 0; start_height <= result.max_height; start_height += static_cast<uint32_t>(options.chunk_size)) {
        const uint32_t end_height =
            std::min(start_height + static_cast<uint32_t>(options.chunk_size) - 1U, result.max_height);
        const auto rows = db.get_main_chain_blocks_in_height_range(start_height, end_height);

        const std::filesystem::path output_path = output_dir / chunk_filename(start_height, end_height);
        std::ofstream out(output_path);
        if (!out.is_open()) {
            throw std::runtime_error("failed to open output file: " + output_path.string());
        }

        std::size_t chunk_entries = 0;
        for (const auto& row : rows) {
            ++result.blocks_scanned;
            try {
                const auto block = chia::FullBlock::from_bytes(row.block_bytes);
                if (block.height() != row.height) {
                    std::cerr << "Block height mismatch at DB height " << row.height << ": parsed "
                              << block.height() << '\n';
                }
                for (const auto& entry : chia::extract_witness_type_zero_entries(row.header_hash, block)) {
                    out << compact_vdf_entry_to_json(entry);
                    ++chunk_entries;
                    ++result.entries_written;
                }
            } catch (const std::exception& e) {
                std::cerr << "Failed to parse block at height " << row.height << " header_hash "
                          << chia::bytes32_to_db_hex(row.header_hash) << ": " << e.what() << '\n';
            }
        }

        out.close();
        ++result.files_written;
        std::cout << "Wrote " << output_path.filename().string() << ": " << chunk_entries << " entries from "
                  << rows.size() << " blocks (heights " << start_height << " to " << end_height << ")\n"
                  << std::flush;
    }

    result.elapsed_seconds = seconds_since(total_start);
    std::cout << "Finished export: " << result.entries_written << " entries across " << result.blocks_scanned
              << " blocks in " << result.files_written << " files, time taken: " << result.elapsed_seconds << "s\n";
    return result;
}
