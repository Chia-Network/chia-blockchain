from typing import List

# Github actions template config.
oses = ["ubuntu", "macos"]

# Defaults are conservative.
parallel = False
checkout_blocks_and_plots = True
install_timelord = False
check_resource_usage = False
job_timeout = 30
custom_vars: List[str] = []
