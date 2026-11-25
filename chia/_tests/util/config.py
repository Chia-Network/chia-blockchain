from __future__ import annotations

job_timeout = 90
# test_parser and test_header_block are the two slow groups in the same file.
# test_parser's four cases are split two per row so each case gets its own
# core on two-core hyperthreaded runners. Every other file joins the last row
# so a new test is still run and does not become a setup-only job.
matrix_shard_files: list[list[str]] = [
    ["test_full_block_utils.py::test_parser=0/2"],
    ["test_full_block_utils.py::test_parser=1/2"],
    ["test_full_block_utils.py::test_header_block"],
    ["test_priority_mutex.py"],
]
