from __future__ import annotations

job_timeout = 60
parallel = False
install_timelord = True
checkout_blocks_and_plots = True
# The two slow files. test_start_simulator.py joins the last row.
matrix_shard_files: list[list[str]] = [
    ["test_simulator.py"],
    ["test_simulation.py"],
]
