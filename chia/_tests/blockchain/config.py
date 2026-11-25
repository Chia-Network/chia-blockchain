from __future__ import annotations

job_timeout = 120
checkout_blocks_and_plots = True
# Half of test_blockchain.py plus the next-slowest file on each row.
# Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_blockchain.py=0/2", "test_blockchain_transactions.py"],
    ["test_blockchain.py=1/2", "test_build_chains.py", "test_block_commitments.py"],
]
