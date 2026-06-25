# process_compact_vdf

Standalone C++ utility for working with compact challenge-chain VDF witnesses on a **v2**
chia blockchain SQLite database. It supports two modes:

1. **Process** — read a `compactvdf` JSON-lines file, validate witnesses with **chiavdf**,
   apply compact proofs to blocks in `full_blocks`, and update `is_fully_compactified`.
2. **Export** — scan the main chain and write `compactvdf-*` JSON-lines files for blocks
   that already store `witness_type` 0 proofs.

The tool does not run a full node. It parses streamable `FullBlock` blobs from the database,
mutates VDF proof fields in memory, and writes compressed blocks back.

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

## Process mode

Apply a pending compactvdf file to the database:

```bash
./build/process_compact_vdf/process_compact_vdf \
  --db /path/to/blockchain_v2.sqlite \
  --compactvdf /path/to/compactvdf \
  [--batch-size 1000] \
  [--threads 8] \
  [--dryrun]
```

Steps:

1. Verify `database_version = 2`.
2. Read JSON lines from the compactvdf file (see [File format](#compactvdf-file-format)).
3. Load affected blocks from `full_blocks` (zstd-compressed `FullBlock` blobs keyed by
   `header_hash`).
4. Validate witnesses in parallel (`--threads`, default: hardware concurrency) using chiavdf.
5. Apply matching compact proofs to in-memory blocks.
6. Write blocks back and set `full_blocks.is_fully_compactified`.
7. Run `PRAGMA wal_checkpoint(TRUNCATE)` and delete the compactvdf file.

With `--dryrun`, steps 6–7 are skipped. The database is opened with `PRAGMA query_only=ON`
so no rows are written; the compactvdf file is not deleted.

### Lookup and validation

For each entry, the tool resolves which `VDFInfo` on the block the witness belongs to:

| `sub_slot_index` | Behavior |
|------------------|----------|
| Present (CC_EOS / ICC_EOS) | O(1) lookup via index into `finished_sub_slots`, then `validate_vdf` |
| Absent (CC_SP / CC_IP, or legacy files) | Try each candidate `VDFInfo` for the field until `validate_vdf` succeeds |

Entries that fail lookup or validation are skipped with a log message. Duplicate entries
(same `header_hash`, `field_vdf`, `witness`) are deduplicated within each batch.

Application uses the same field mapping as export (see below). Blocks are updated one at a
time per header hash; multiple entries for the same block are applied sequentially.

## Export mode

Scan the main chain and write compactvdf archives:

```bash
./build/process_compact_vdf/process_compact_vdf \
  --db /path/to/blockchain_v2_mainnet.sqlite \
  --export-compactvdf \
  [--export-chunk-size 10000] \
  [--output-dir .]
```

This writes files named `compactvdf-{start}to{end}` (inclusive height range) into
`--output-dir` (default: current directory). One file is produced per chunk from height 0
through the current peak.

Export includes one line per compressible proof on the block where:

- `witness_type == 0`, and
- `witness` is non-empty.

Only these fields are exported (matching `CompressibleVDFField`):

| `field_vdf` | Proof replaced | `sub_slot_index` in file |
|-------------|----------------|--------------------------|
| 1 | CC end-of-slot (`challenge_chain_slot_proof`) | yes — index in `finished_sub_slots` |
| 2 | ICC end-of-slot (`infused_challenge_chain_slot_proof`) | yes |
| 3 | CC signage point (`challenge_chain_sp_proof`) | omitted |
| 4 | CC infusion point (`challenge_chain_ip_proof`) | omitted |

Reward-chain proofs are not exported; they are not compressible under the current protocol.

## compactvdf file format

UTF-8 JSON Lines: one JSON object per line. Empty lines are ignored.

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `header_hash` | hex string (`0x…`, 32 bytes) | Block header hash (DB key) |
| `field_vdf` | integer | `1`–`4` (see table above) |
| `witness` | hex string | Compact witness bytes |

### Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `sub_slot_index` | integer | Index into `finished_sub_slots` for `field_vdf` 1 or 2 |

Legacy lines may nest the witness under `vdf_proof.witness`; the parser accepts both forms.

### Example

```json
{"field_vdf":1,"header_hash":"0x…","witness":"0x…","sub_slot_index":0}
{"field_vdf":4,"header_hash":"0x…","witness":"0x…"}
```

Each witness is applied as a compact proof: `witness_type = 0`,
`normalized_to_identity = true`. `VDFInfo` is read from the block at apply time; it is not
stored in the file.

## v2 database schema

Expected tables/columns:

- `database_version(version)` with value `2`
- `full_blocks(header_hash BLOB, block BLOB, is_fully_compactified TINYINT, ...)`

Blocks are stored as zstd-compressed chia streamable `FullBlock` bytes (v0 or v1 wire format).

`is_fully_compactified` is set when all compressible CC/ICC proofs on the header block are
compact (CC/ICC EOS, CC SP if present, CC IP).

## Notes

- Only v2 databases are supported.
- Stop the full node before running this tool against its database.
- Network constants use mainnet discriminant size (1024 bits).
