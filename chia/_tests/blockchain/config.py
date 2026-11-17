from __future__ import annotations

job_timeout = 120
checkout_blocks_and_plots = True
matrix_shards = 2
# Worker-minutes on Windows (run 43897580454). Missing files weigh 1.
matrix_shard_weights: dict[str, float] = {
    "test_augmented_chain.py": 1.7,
    "test_block_commitments.py": 8.0,
    "test_blockchain.py": 76.8,
    "test_blockchain_transactions.py": 22.1,
    "test_build_chains.py": 9.4,
}
