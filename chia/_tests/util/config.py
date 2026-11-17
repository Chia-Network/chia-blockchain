from __future__ import annotations

job_timeout = 90
# The two slow files each get a row. Every other file joins the last row so a
# new test is still run and does not become a setup-only job.
matrix_shard_files: list[list[str]] = [
    ["test_full_block_utils.py"],
    ["test_priority_mutex.py"],
]
