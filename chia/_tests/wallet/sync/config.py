from __future__ import annotations

job_timeout = 60
checkout_blocks_and_plots = True
# One file, split in collection order.
matrix_shard_files: list[list[str]] = [
    ["test_wallet_sync.py=0/2"],
    ["test_wallet_sync.py=1/2"],
]
