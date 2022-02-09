CREATE INDEX IF NOT EXISTS height ON full_blocks(height);
CREATE INDEX IF NOT EXISTS is_fully_compactified ON full_blocks(is_fully_compactified, in_main_chain) WHERE in_main_chain=1;
CREATE INDEX IF NOT EXISTS main_chain ON full_blocks(height, in_main_chain) WHERE in_main_chain=1;
