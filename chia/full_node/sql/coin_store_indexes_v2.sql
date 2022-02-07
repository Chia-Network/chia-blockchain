CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index);
CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index);
CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash);
CREATE INDEX IF NOT EXISTS coin_parent_index on coin_record(coin_parent);
