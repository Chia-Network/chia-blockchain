from __future__ import annotations

from typing import Literal

# Defaults are conservative.
parallel: bool | int | Literal["auto"] = True
checkout_blocks_and_plots = False
install_timelord = False
# NOTE: do not use until the hangs are fixed
#       https://github.com/CFMTech/pytest-monitor/issues/53
#       https://github.com/pythonprofilers/memory_profiler/issues/342
check_resource_usage = False
job_timeout = 30
# 1 keeps a directory as a single matrix row. Directories set a higher value to
# split their files across that many rows (see matrix_shard.py).
matrix_shards = 1
# Directories whose slowest OS finished in <= 8.5 min on baseline run
# 43897580454 (2026-11-16). Packed into shared rows so one setup covers about
# 15-21 min of that OS's job time. parallel / install_timelord must match
# inside a group; core/services stays alone because parallel is False.
# Paths are relative to chia/_tests.
matrix_packs: list[list[str]] = [
    ["clvm", "core/ssl", "solver", "tools"],
    ["core/consensus", "core/consensus/stores", "rpc", "wallet/remote_wallet"],
    ["cmds/wallet", "db", "wallet/simple_sync"],
]
