CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height);
CREATE INDEX IF NOT EXISTS is_fully_compactified on full_blocks(is_fully_compactified);
CREATE INDEX IF NOT EXISTS height on block_records(height);
CREATE INDEX IF NOT EXISTS peak on block_records(is_peak);
