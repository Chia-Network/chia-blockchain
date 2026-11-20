from __future__ import annotations

job_timeout = 40
checkout_blocks_and_plots = True
# Two rows of roughly equal time. Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_new_wallet_protocol.py", "test_wallet_state_manager.py"],
    ["test_wallet.py"],
]
