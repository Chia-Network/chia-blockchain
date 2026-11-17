from __future__ import annotations

parallel = 4
job_timeout = 80
checkout_blocks_and_plots = True
# test_data_rpc.py is most of this directory. Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_data_rpc.py=0/2", "test_data_store.py"],
    ["test_data_rpc.py=1/2"],
]
