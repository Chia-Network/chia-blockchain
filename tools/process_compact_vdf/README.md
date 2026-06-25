# process_compact_vdf

Standalone C++ utility that applies pending compact VDF proofs from a `compactvdf`
JSON-lines file to a **v2** chia blockchain SQLite database.

This mirrors `chia.full_node.compact_vdf_file.process_compact_vdf_file()` but runs
outside the Python full node. VDF validation uses the **chiavdf** C++ library only.

## Requirements

- CMake 3.18+
- C++17 compiler
- SQLite3 development headers
- GMP / GMPXX
- libzstd
- chiavdf sources (sibling checkout at `../../../chiavdf` by default)

## Build

```bash
cmake -S tools/process_compact_vdf -B build/process_compact_vdf \
  -DCHIAVDF_SRC=/path/to/chiavdf/src
cmake --build build/process_compact_vdf -j
```

## Usage

```bash
./build/process_compact_vdf/process_compact_vdf \
  --db /path/to/blockchain_v2.sqlite \
  --compactvdf /path/to/db/compactvdf \
  [--batch-size 1000] \
  [--threads 8] \
  [--dryrun]
```

The tool:

1. Verifies the database has `database_version = 2`.
2. Reads JSON lines from the compactvdf file (`header_hash`, `field_vdf`, `witness`, optional `sub_slot_index`).
3. Loads affected blocks from `full_blocks` (binary `header_hash`, zstd-compressed `block` blob).
4. Validates witnesses with chiavdf and applies compact proofs to the in-memory blocks.
5. Writes zstd-compressed blocks back and updates `full_blocks.is_fully_compactified`.
6. Runs `PRAGMA wal_checkpoint(TRUNCATE)` and deletes the compactvdf file.

With `--dryrun`, steps 5–6 are skipped and `PRAGMA query_only=ON` prevents any SQL
writes. The database file is still opened read-write so WAL sidecar files work.

## Export compactvdf files from database

Scan the main chain and write compactvdf JSON-lines files containing proofs that
already use `witness_type` 0:

```bash
./build/process_compact_vdf/process_compact_vdf \
  --db /path/to/blockchain_v2_mainnet.sqlite \
  --export-compactvdf \
  [--export-chunk-size 10000] \
  [--output-dir .]
```

This writes files like `compactvdf-0to9999`, `compactvdf-10000to19999`, etc.
into the output directory (current directory by default). Each line matches the
runtime compactvdf format: `header_hash`, `field_vdf`, `witness`, and `sub_slot_index`
(for CC_EOS / ICC_EOS entries; omitted for CC_SP / CC_IP).

## v2 database schema

Expected tables/columns:

- `database_version(version)` with value `2`
- `full_blocks(header_hash BLOB, block BLOB, is_fully_compactified TINYINT, ...)`

Blocks are stored as zstd-compressed chia streamable `FullBlock` bytes (v0 or v1 wire format).

## Notes

- Only v2 databases are supported.
- Stop the full node before running this tool against its database.
- Network constants use mainnet discriminant size (1024 bits).
