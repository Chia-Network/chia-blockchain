from __future__ import annotations

job_timeout = 110
checkout_blocks_and_plots = True
# test_long_reorg and test_long_reorg_nodes are about a quarter of this
# directory and used to land on one slice. They get their own row; the rest
# of test_full_node.py is split in two. Unlisted files join the last row.
matrix_shard_files: list[list[str]] = [
    ["test_full_node.py::test_long_reorg", "test_full_node.py::test_long_reorg_nodes"],
    ["test_full_node.py::~test_long_reorg,~test_long_reorg_nodes=0/2"],
    ["test_full_node.py::~test_long_reorg,~test_long_reorg_nodes=1/2"],
    ["test_conditions.py"],
]
