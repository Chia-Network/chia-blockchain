from __future__ import annotations

job_timeout = 110
checkout_blocks_and_plots = True
matrix_shards = 3
# Worker-minutes on macOS Intel (run 43897580454). Missing files weigh 1.
matrix_shard_weights: dict[str, float] = {
    "test_block_height_map.py": 3.6,
    "test_conditions.py": 44.2,
    "test_full_node.py": 152.5,
    "test_prev_tx_block.py": 11.0,
    "test_transactions.py": 6.7,
    "test_tx_processing_queue.py": 4.1,
}
