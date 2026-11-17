from __future__ import annotations

job_timeout = 110
checkout_blocks_and_plots = True
# test_full_node.py is most of this directory. Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_full_node.py=0/2"],
    ["test_full_node.py=1/2"],
    ["test_conditions.py"],
]
