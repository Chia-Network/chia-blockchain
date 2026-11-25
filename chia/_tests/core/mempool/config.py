from __future__ import annotations

job_timeout = 70
checkout_blocks_and_plots = True
# The two slow files are split. Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_mempool_manager.py"],
    ["test_mempool.py"],
]
