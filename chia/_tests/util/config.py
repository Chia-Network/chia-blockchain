from __future__ import annotations

job_timeout = 90
matrix_shards = 3
# Worker-minutes on Windows, the slowest OS for this directory (run 43897580454).
# Missing files weigh 1. Weights only balance shards; every file still runs.
matrix_shard_weights: dict[str, float] = {
    "test_full_block_utils.py": 64.9,
    "test_priority_mutex.py": 53.9,
    "test_pprint.py": 1.3,
}
