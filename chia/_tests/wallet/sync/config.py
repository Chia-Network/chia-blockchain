from __future__ import annotations

job_timeout = 60
checkout_blocks_and_plots = True
# test_long_reorg_nodes_and_wallet is most of this file and its slow cases
# sit in the second half. Its halves go on separate rows and the rest of the
# file joins the lighter half on the last row.
matrix_shard_files: list[list[str]] = [
    ["test_wallet_sync.py::test_long_reorg_nodes_and_wallet=1/2"],
    ["test_wallet_sync.py::test_long_reorg_nodes_and_wallet=0/2"],
]
