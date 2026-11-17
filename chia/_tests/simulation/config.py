from __future__ import annotations

job_timeout = 60
parallel = False
install_timelord = True
checkout_blocks_and_plots = True
matrix_shards = 2
# Serial minutes on Ubuntu (the only OS that runs this directory; run 43897580454).
matrix_shard_weights: dict[str, float] = {
    "test_simulation.py": 11.3,
    "test_simulator.py": 16.8,
}
