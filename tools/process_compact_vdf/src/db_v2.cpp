#include "db_v2.hpp"

#include "zstd_util.hpp"

#include <sqlite3.h>

#include <algorithm>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace db_v2 {
namespace {

void check_sqlite(int rc, sqlite3* db, const char* context) {
    if (rc != SQLITE_OK && rc != SQLITE_DONE && rc != SQLITE_ROW) {
        const char* err = db != nullptr ? sqlite3_errmsg(db) : "unknown sqlite error";
        throw std::runtime_error(std::string(context) + ": " + err);
    }
}

void validate_db_path(const std::string& path) {
    const std::filesystem::path db_path(path);
    if (!std::filesystem::exists(db_path)) {
        throw std::runtime_error("database file not found: " + path);
    }
    if (!std::filesystem::is_regular_file(db_path)) {
        throw std::runtime_error("database path is not a file: " + path);
    }
}

}  // namespace

Database::Database(const std::string& path, bool readonly) {
    validate_db_path(path);

    // Chia uses WAL journal mode. Opening SQLITE_OPEN_READONLY often fails on the
    // first query because SQLite cannot access the -wal/-shm sidecar files correctly.
    // Open read-write and use query_only for dry-run instead.
    check_sqlite(sqlite3_open_v2(path.c_str(), &db_, SQLITE_OPEN_READWRITE, nullptr), db_, "open database");
    sqlite3_busy_timeout(db_, 30'000);

    if (readonly) {
        check_sqlite(sqlite3_exec(db_, "PRAGMA query_only=ON", nullptr, nullptr, nullptr), db_, "enable query_only");
    }
}

Database::~Database() {
    if (db_ != nullptr) {
        sqlite3_close(db_);
    }
}

void Database::ensure_v2() {
    sqlite3_stmt* stmt = nullptr;
    check_sqlite(sqlite3_prepare_v2(db_, "SELECT version FROM database_version LIMIT 1", -1, &stmt, nullptr), db_,
                 "prepare database_version");
    const int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        const int version = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        if (version != 2) {
            throw std::runtime_error("database is not v2 format (version=" + std::to_string(version) + ")");
        }
        return;
    }
    sqlite3_finalize(stmt);
    throw std::runtime_error("database_version table missing; expected v2 blockchain database");
}

std::optional<std::vector<uint8_t>> Database::get_block_bytes(const chia::Bytes32& header_hash) {
    sqlite3_stmt* stmt = nullptr;
    check_sqlite(sqlite3_prepare_v2(db_, "SELECT block FROM full_blocks WHERE header_hash = ?", -1, &stmt, nullptr),
                 db_, "prepare get block");
    check_sqlite(sqlite3_bind_blob(stmt, 1, header_hash.data(), static_cast<int>(header_hash.size()), SQLITE_TRANSIENT),
                 db_, "bind header hash");

    std::optional<std::vector<uint8_t>> result;
    const int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        const void* blob = sqlite3_column_blob(stmt, 0);
        const int len = sqlite3_column_bytes(stmt, 0);
        if (blob != nullptr && len > 0) {
            const auto* bytes = static_cast<const uint8_t*>(blob);
            result = zstd_util::decompress(std::vector<uint8_t>(bytes, bytes + len));
        } else {
            result = std::vector<uint8_t>{};
        }
    } else if (rc != SQLITE_DONE) {
        check_sqlite(rc, db_, "get block step");
    }
    sqlite3_finalize(stmt);
    return result;
}

std::optional<uint32_t> Database::max_main_chain_height() {
    sqlite3_stmt* stmt = nullptr;
    check_sqlite(sqlite3_prepare_v2(db_, "SELECT MAX(height) FROM full_blocks WHERE in_main_chain=1", -1, &stmt,
                                      nullptr),
                 db_, "prepare max height");
    std::optional<uint32_t> result;
    const int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW && sqlite3_column_type(stmt, 0) != SQLITE_NULL) {
        result = static_cast<uint32_t>(sqlite3_column_int64(stmt, 0));
    } else if (rc != SQLITE_DONE) {
        check_sqlite(rc, db_, "max height step");
    }
    sqlite3_finalize(stmt);
    return result;
}

std::vector<MainChainBlockRow> Database::get_main_chain_blocks_in_height_range(uint32_t start_height,
                                                                               uint32_t end_height) {
    sqlite3_stmt* stmt = nullptr;
    check_sqlite(
        sqlite3_prepare_v2(db_,
                           "SELECT header_hash, height, block FROM full_blocks "
                           "WHERE in_main_chain=1 AND height >= ? AND height <= ? ORDER BY height ASC",
                           -1, &stmt, nullptr),
        db_, "prepare blocks in height range");
    check_sqlite(sqlite3_bind_int64(stmt, 1, start_height), db_, "bind start height");
    check_sqlite(sqlite3_bind_int64(stmt, 2, end_height), db_, "bind end height");

    std::vector<MainChainBlockRow> rows;
    while (true) {
        const int rc = sqlite3_step(stmt);
        if (rc == SQLITE_DONE) {
            break;
        }
        if (rc != SQLITE_ROW) {
            check_sqlite(rc, db_, "blocks in height range step");
        }

        MainChainBlockRow row;
        if (sqlite3_column_bytes(stmt, 0) != static_cast<int>(row.header_hash.size())) {
            throw std::runtime_error("invalid header_hash length in database");
        }
        std::copy_n(static_cast<const uint8_t*>(sqlite3_column_blob(stmt, 0)), row.header_hash.size(),
                    row.header_hash.begin());
        row.height = static_cast<uint32_t>(sqlite3_column_int64(stmt, 1));

        const void* blob = sqlite3_column_blob(stmt, 2);
        const int len = sqlite3_column_bytes(stmt, 2);
        if (blob != nullptr && len > 0) {
            const auto* bytes = static_cast<const uint8_t*>(blob);
            row.block_bytes = zstd_util::decompress(std::vector<uint8_t>(bytes, bytes + len));
        }
        rows.push_back(std::move(row));
    }
    sqlite3_finalize(stmt);
    return rows;
}

bool Database::replace_block(const chia::Bytes32& header_hash, const std::vector<uint8_t>& block_bytes,
                             bool is_fully_compactified) {
    const std::vector<uint8_t> compressed = zstd_util::compress(block_bytes);

    sqlite3_stmt* stmt = nullptr;
    check_sqlite(
        sqlite3_prepare_v2(db_, "UPDATE full_blocks SET block = ?, is_fully_compactified = ? WHERE header_hash = ?", -1,
                           &stmt, nullptr),
        db_, "prepare replace block");
    check_sqlite(sqlite3_bind_blob(stmt, 1, compressed.data(), static_cast<int>(compressed.size()), SQLITE_TRANSIENT),
                 db_, "bind block blob");
    check_sqlite(sqlite3_bind_int(stmt, 2, is_fully_compactified ? 1 : 0), db_, "bind compact flag");
    check_sqlite(sqlite3_bind_blob(stmt, 3, header_hash.data(), static_cast<int>(header_hash.size()), SQLITE_TRANSIENT),
                 db_, "bind header hash");
    check_sqlite(sqlite3_step(stmt), db_, "replace block step");
    const int changed = sqlite3_changes(db_);
    sqlite3_finalize(stmt);
    return changed > 0;
}

void Database::wal_checkpoint_truncate() {
    sqlite3_stmt* stmt = nullptr;
    check_sqlite(sqlite3_prepare_v2(db_, "PRAGMA wal_checkpoint(TRUNCATE)", -1, &stmt, nullptr), db_,
                 "prepare wal checkpoint");
    check_sqlite(sqlite3_step(stmt), db_, "wal checkpoint step");
    sqlite3_finalize(stmt);
}

}  // namespace db_v2
