from __future__ import annotations

job_timeout = 60
checkout_blocks_and_plots = True
matrix_shards = 2
# Worker-minutes on macOS Intel (run 43897580454). Missing files weigh 1.
matrix_shard_weights: dict[str, float] = {
    "test_assumevalid_sync.py": 30.1,
    "test_full_sync.py": 81.6,
}
