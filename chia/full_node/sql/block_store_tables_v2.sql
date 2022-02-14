CREATE TABLE IF NOT EXISTS full_blocks(header_hash blob PRIMARY KEY, prev_hash blob, height bigint, sub_epoch_summary blob, is_fully_compactified tinyint, in_main_chain tinyint, block blob, block_record blob);
CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob);
