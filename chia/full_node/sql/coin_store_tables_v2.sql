CREATE TABLE IF NOT EXISTS coin_record(coin_name blob PRIMARY KEY, confirmed_index bigint, spent_index bigint, coinbase int, puzzle_hash blob, coin_parent blob, amount blob, timestamp bigint);
