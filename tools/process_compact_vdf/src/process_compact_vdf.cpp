#include "process_compact_vdf.hpp"

#include "db_v2.hpp"
#include "mini_json.hpp"
#include "vdf_validate.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <future>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

struct CompactVdfEntry {
    chia::Bytes32 header_hash{};
    uint8_t field_vdf{};
    std::vector<uint8_t> witness;
};

struct EntryKey {
    chia::Bytes32 header_hash{};
    std::vector<uint8_t> witness;
    uint8_t field_vdf{};

    bool operator==(const EntryKey& other) const {
        return field_vdf == other.field_vdf && header_hash == other.header_hash && witness == other.witness;
    }
};

struct EntryKeyHash {
    std::size_t operator()(const EntryKey& key) const {
        std::size_t h = std::hash<uint8_t>{}(key.field_vdf);
        for (const auto b : key.header_hash) {
            h = h * 31 + b;
        }
        for (const auto b : key.witness) {
            h = h * 31 + b;
        }
        return h;
    }
};

double seconds_since(const std::chrono::steady_clock::time_point& start) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

CompactVdfEntry parse_entry_json(const mini_json::Object& data) {
    CompactVdfEntry entry;
    const auto header_hash = data.get_string("header_hash");
    if (!header_hash.has_value()) {
        throw std::runtime_error("missing header_hash");
    }
    const auto hash_bytes = chia::hex_to_bytes(*header_hash);
    if (hash_bytes.size() != 32) {
        throw std::runtime_error("header_hash must be 32 bytes");
    }
    std::copy(hash_bytes.begin(), hash_bytes.end(), entry.header_hash.begin());

    const auto field_vdf = data.get_uint64("field_vdf");
    if (!field_vdf.has_value()) {
        throw std::runtime_error("missing field_vdf");
    }
    entry.field_vdf = static_cast<uint8_t>(*field_vdf);

    if (const auto witness = data.get_string("witness")) {
        entry.witness = chia::hex_to_bytes(*witness);
    } else if (const mini_json::Object* vdf_proof = data.get_object("vdf_proof")) {
        const auto witness = vdf_proof->get_string("witness");
        if (!witness.has_value()) {
            throw std::runtime_error("missing witness");
        }
        entry.witness = chia::hex_to_bytes(*witness);
    } else {
        throw std::runtime_error("missing witness");
    }
    return entry;
}

std::vector<CompactVdfEntry> read_entries(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        return {};
    }
    std::vector<CompactVdfEntry> entries;
    std::string line;
    int line_no = 0;
    while (std::getline(in, line)) {
        ++line_no;
        const auto start = line.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) {
            continue;
        }
        try {
            entries.push_back(parse_entry_json(mini_json::Object::parse(line)));
        } catch (const std::exception& e) {
            std::cerr << "Skipping invalid compactvdf line " << line_no << ": " << e.what() << '\n';
        }
    }
    return entries;
}

std::vector<chia::Bytes32> ordered_unique_header_hashes(const std::vector<CompactVdfEntry>& entries) {
    std::vector<chia::Bytes32> unique;
    std::unordered_set<chia::Bytes32, chia::Bytes32Hash> seen;
    for (const auto& entry : entries) {
        if (seen.insert(entry.header_hash).second) {
            unique.push_back(entry.header_hash);
        }
    }
    return unique;
}

}  // namespace

ProcessCompactVdfResult process_compact_vdf_file(const ProcessCompactVdfOptions& options) {
    ProcessCompactVdfResult result;
    const auto total_start = std::chrono::steady_clock::now();

    auto entries = read_entries(options.compact_vdf_path);
    if (entries.empty()) {
        if (!options.dry_run && std::filesystem::exists(options.compact_vdf_path)) {
            std::filesystem::remove(options.compact_vdf_path);
        }
        result.elapsed_seconds = seconds_since(total_start);
        return result;
    }

    std::sort(entries.begin(), entries.end(), [](const CompactVdfEntry& a, const CompactVdfEntry& b) {
        return a.header_hash < b.header_hash;
    });

    const auto unique_hashes = ordered_unique_header_hashes(entries);
    result.entries_total = entries.size();
    const std::size_t blocks_total = unique_hashes.size();

    std::cout << "Starting compact VDF file processing: " << entries.size() << " entries across " << blocks_total
              << " blocks from " << options.compact_vdf_path;
    if (options.dry_run) {
        std::cout << " (dry run: no writes)";
    }
    std::cout << '\n';

    db_v2::Database db(options.db_path, options.dry_run);
    db.ensure_v2();

    const unsigned thread_count =
        options.thread_count == 0 ? std::max(1u, std::thread::hardware_concurrency()) : options.thread_count;

    std::size_t blocks_processed = 0;
    const std::size_t num_batches = (blocks_total + options.batch_size - 1) / options.batch_size;

    for (std::size_t batch_index = 0; batch_index < num_batches; ++batch_index) {
        const std::size_t batch_start = batch_index * options.batch_size;
        const std::size_t batch_end = std::min(batch_start + options.batch_size, blocks_total);
        std::unordered_set<chia::Bytes32, chia::Bytes32Hash> batch_hash_set(
            unique_hashes.begin() + static_cast<std::ptrdiff_t>(batch_start),
            unique_hashes.begin() + static_cast<std::ptrdiff_t>(batch_end));

        std::vector<CompactVdfEntry> batch_entries;
        batch_entries.reserve(entries.size());
        for (const auto& entry : entries) {
            if (batch_hash_set.count(entry.header_hash) > 0) {
                batch_entries.push_back(entry);
            }
        }

        std::cout << "Compact VDF batch " << (batch_index + 1) << "/" << num_batches << ": " << batch_hash_set.size()
                  << " blocks, " << batch_entries.size() << " entries\n";

        std::unordered_map<chia::Bytes32, chia::FullBlock, chia::Bytes32Hash> blocks;
        std::vector<chia::Bytes32> batch_hashes(batch_hash_set.begin(), batch_hash_set.end());
        std::sort(batch_hashes.begin(), batch_hashes.end());

        const auto db_read_start = std::chrono::steady_clock::now();
        for (std::size_t block_index = 0; block_index < batch_hashes.size(); ++block_index) {
            const auto& header_hash = batch_hashes[block_index];
            std::cout << "Reading block " << (block_index + 1) << "/" << batch_hashes.size() << " header_hash "
                      << chia::bytes32_to_db_hex(header_hash) << "...\n"
                      << std::flush;

            const auto block_bytes = db.get_block_bytes(header_hash);
            if (!block_bytes.has_value()) {
                std::cerr << "Can't find block for pending compact VDF. Header hash: "
                          << chia::bytes32_to_db_hex(header_hash) << '\n';
                continue;
            }
            try {
                const auto block = chia::FullBlock::from_bytes(*block_bytes);
                std::cout << "Read block " << (block_index + 1) << "/" << batch_hashes.size() << " height "
                          << block.height() << " header_hash " << chia::bytes32_to_db_hex(header_hash) << " ("
                          << block_bytes->size() << " bytes)\n"
                          << std::flush;
                blocks.emplace(header_hash, std::move(block));
            } catch (const std::exception& e) {
                std::cerr << "Failed to parse block " << chia::bytes32_to_db_hex(header_hash) << ": " << e.what()
                          << '\n';
            }
        }
        result.db_read_seconds += seconds_since(db_read_start);
        std::cout << "Loaded " << blocks.size() << "/" << batch_hashes.size() << " blocks from DB\n" << std::flush;

        std::vector<CompactVdfEntry> deduped_entries;
        deduped_entries.reserve(batch_entries.size());
        std::unordered_set<EntryKey, EntryKeyHash> seen_keys;
        for (const auto& entry : batch_entries) {
            EntryKey key{entry.header_hash, entry.witness, entry.field_vdf};
            if (!seen_keys.insert(key).second) {
                continue;
            }
            deduped_entries.push_back(entry);
        }

        struct ValidationItem {
            CompactVdfEntry entry;
            std::optional<chia::VDFInfo> vdf_info;
        };

        std::vector<ValidationItem> validation_items;
        validation_items.reserve(deduped_entries.size());
        for (const auto& entry : deduped_entries) {
            if (blocks.find(entry.header_hash) == blocks.end()) {
                continue;
            }
            validation_items.push_back({entry, std::nullopt});
        }

        const auto vdf_start = std::chrono::steady_clock::now();
        std::cout << "Validating " << validation_items.size() << " compact proofs with " << thread_count
                  << " threads...\n"
                  << std::flush;

        std::atomic<std::size_t> next_index{0};
        std::atomic<std::size_t> validated_count{0};
        std::mutex log_mutex;
        std::vector<std::thread> workers;
        workers.reserve(thread_count);
        for (unsigned i = 0; i < thread_count; ++i) {
            workers.emplace_back([&]() {
                while (true) {
                    const std::size_t idx = next_index.fetch_add(1);
                    if (idx >= validation_items.size()) {
                        break;
                    }
                    auto& item = validation_items[idx];
                    const auto& block = blocks.at(item.entry.header_hash);
                    const auto field = static_cast<chia::CompressibleVDFField>(item.entry.field_vdf);
                    const auto proof = chia::VDFProof::compact(item.entry.witness);
                    {
                        const std::lock_guard<std::mutex> lock(log_mutex);
                        std::cout << "Validating proof " << (idx + 1) << "/" << validation_items.size()
                                  << " block height " << block.height() << " field_vdf "
                                  << static_cast<unsigned>(item.entry.field_vdf) << "...\n"
                                  << std::flush;
                    }
                    item.vdf_info = vdf::find_vdf_info_for_proof(block, field, proof);

                    const auto done = validated_count.fetch_add(1) + 1;
                    const std::lock_guard<std::mutex> lock(log_mutex);
                    std::cout << "Validated proof " << done << "/" << validation_items.size() << " block height "
                              << block.height() << " field_vdf " << static_cast<unsigned>(item.entry.field_vdf) << " "
                              << (item.vdf_info.has_value() ? "ok" : "invalid") << '\n'
                              << std::flush;
                }
            });
        }
        for (auto& worker : workers) {
            worker.join();
        }
        result.vdf_seconds += seconds_since(vdf_start);

        std::unordered_map<EntryKey, std::optional<chia::VDFInfo>, EntryKeyHash> validated;
        for (const auto& item : validation_items) {
            EntryKey key{item.entry.header_hash, item.entry.witness, item.entry.field_vdf};
            validated.emplace(key, item.vdf_info);
        }

        std::optional<chia::Bytes32> current_hash;
        std::vector<CompactVdfEntry> current_block_entries;
        auto flush_current_block = [&]() {
            if (!current_hash.has_value()) {
                return;
            }
            auto block_it = blocks.find(*current_hash);
            if (block_it == blocks.end()) {
                current_hash = std::nullopt;
                current_block_entries.clear();
                return;
            }

            const std::string header_hash_hex = chia::bytes32_to_db_hex(*current_hash);
            std::size_t applied_for_block = 0;
            for (const auto& entry : current_block_entries) {
                const auto field = static_cast<chia::CompressibleVDFField>(entry.field_vdf);
                const auto proof = chia::VDFProof::compact(entry.witness);
                EntryKey key{entry.header_hash, entry.witness, entry.field_vdf};
                const auto validated_it = validated.find(key);
                if (validated_it == validated.end() || !validated_it->second.has_value()) {
                    std::cerr << "Pending compact VDF proof is not valid for block " << header_hash_hex << '\n';
                    continue;
                }
                if (!chia::needs_compact_proof(*validated_it->second, block_it->second, field)) {
                    std::cout << "Duplicate pending compact proof for block " << header_hash_hex << '\n';
                    continue;
                }
                if (!chia::apply_compact_proof(block_it->second, *validated_it->second, proof, field)) {
                    std::cerr << "Could not apply pending compact proof for block " << header_hash_hex << '\n';
                    continue;
                }
                ++applied_for_block;
                ++result.entries_applied;
            }

            ++blocks_processed;
            std::cout << "Processed block " << blocks_processed << "/" << blocks_total << " height "
                      << block_it->second.height() << " header_hash " << header_hash_hex << " applied "
                      << applied_for_block << "/" << current_block_entries.size() << " proofs";
            if (options.dry_run) {
                std::cout << ", skipping DB write (dry run)\n" << std::flush;
            } else {
                std::cout << ", flushing to DB\n" << std::flush;
            }

            if (!options.dry_run) {
                const auto db_flush_start = std::chrono::steady_clock::now();
                const auto bytes = block_it->second.to_bytes();
                if (!db.replace_block(*current_hash, bytes, block_it->second.is_fully_compactified())) {
                    std::cerr << "Failed to update block in database: " << header_hash_hex << '\n';
                }
                result.db_flush_seconds += seconds_since(db_flush_start);
            }

            current_hash = std::nullopt;
            current_block_entries.clear();
        };

        for (const auto& entry : deduped_entries) {
            if (!current_hash.has_value()) {
                current_hash = entry.header_hash;
            } else if (entry.header_hash != *current_hash) {
                flush_current_block();
                current_hash = entry.header_hash;
            }
            current_block_entries.push_back(entry);
        }
        flush_current_block();
    }

    if (blocks_processed > 0 && !options.dry_run) {
        const auto wal_start = std::chrono::steady_clock::now();
        db.wal_checkpoint_truncate();
        result.wal_checkpoint_seconds = seconds_since(wal_start);
    }

    if (!options.dry_run) {
        std::filesystem::remove(options.compact_vdf_path);
    }

    result.blocks_processed = blocks_processed;
    result.elapsed_seconds = seconds_since(total_start);
    const double other_seconds =
        std::max(0.0, result.elapsed_seconds - result.vdf_seconds - result.db_read_seconds - result.db_flush_seconds -
                              result.wal_checkpoint_seconds);

    std::cout << "Finished processing compact VDF file: " << result.entries_applied << " proofs applied across "
              << result.blocks_processed << " blocks, time taken: " << result.elapsed_seconds << "s (vdf "
              << result.vdf_seconds << "s, db read " << result.db_read_seconds << "s, db flush "
              << result.db_flush_seconds << "s, wal checkpoint " << result.wal_checkpoint_seconds << "s, other "
              << other_seconds << "s)";
    if (options.dry_run) {
        std::cout << ", dry run (no writes)";
    } else {
        std::cout << ", removed " << options.compact_vdf_path;
    }
    std::cout << '\n';

    return result;
}
