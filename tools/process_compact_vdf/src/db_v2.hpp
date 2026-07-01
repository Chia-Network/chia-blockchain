#pragma once

#include "chia_protocol.hpp"

#include <optional>
#include <string>
#include <vector>

struct sqlite3;

namespace db_v2 {

struct MainChainBlockRow {
    chia::Bytes32 header_hash{};
    uint32_t height{};
    std::vector<uint8_t> block_bytes;
};

class Database {
  public:
    explicit Database(const std::string& path, bool readonly = false);
    ~Database();

    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    void ensure_v2();
    std::optional<uint32_t> max_main_chain_height();
    std::vector<MainChainBlockRow> get_main_chain_blocks_in_height_range(uint32_t start_height, uint32_t end_height);
    std::optional<std::vector<uint8_t>> get_block_bytes(const chia::Bytes32& header_hash);
    bool replace_block(const chia::Bytes32& header_hash, const std::vector<uint8_t>& block_bytes,
                       bool is_fully_compactified);
    void wal_checkpoint_truncate();

  private:
    sqlite3* db_{nullptr};
};

}  // namespace db_v2
