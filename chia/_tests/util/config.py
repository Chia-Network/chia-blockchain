from __future__ import annotations

job_timeout = 90
# test_parser and test_header_block are the two slow groups in the same file, so
# a file slice would put both on the last shard. Function selectors split them.
# Every other file joins the last row so a new test is still run and does not
# become a setup-only job.
matrix_shard_files: list[list[str]] = [
    ["test_full_block_utils.py::test_parser"],
    ["test_full_block_utils.py::test_header_block"],
    ["test_priority_mutex.py"],
]
