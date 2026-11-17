from __future__ import annotations

parallel = 4
job_timeout = 80
checkout_blocks_and_plots = True
matrix_shards = 2
# Worker-minutes on macOS Intel (run 43897580454). Missing files weigh 1.
matrix_shard_weights: dict[str, float] = {
    "test_data_rpc.py": 102.1,
    "test_data_store.py": 17.5,
}
