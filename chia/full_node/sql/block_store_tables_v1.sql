CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, height bigint, is_block tinyint, is_fully_compactified tinyint, block blob);
CREATE TABLE IF NOT EXISTS block_records(header_hash sqlite_ddl_files text PRIMARY KEY, prev_hash text, height bigint, block blob, sub_epoch_summary blob, is_peak tinyint, is_block tinyint);
