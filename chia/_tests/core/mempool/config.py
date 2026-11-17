from __future__ import annotations

job_timeout = 70
checkout_blocks_and_plots = True
matrix_shards = 2
# Worker-minutes on macOS Intel (run 43897580454). Missing files weigh 1.
matrix_shard_weights: dict[str, float] = {
    "test_mempool.py": 57.9,
    "test_mempool_manager.py": 74.8,
}
