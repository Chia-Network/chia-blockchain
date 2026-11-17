from __future__ import annotations

job_timeout = 60
checkout_blocks_and_plots = True
# test_full_sync.py is about three times test_assumevalid_sync.py. Two thirds
# of it share a row; the last third shares a row with the smaller file.
matrix_shard_files: list[list[str]] = [
    ["test_full_sync.py=0/3", "test_full_sync.py=1/3"],
    ["test_full_sync.py=2/3", "test_assumevalid_sync.py"],
]
