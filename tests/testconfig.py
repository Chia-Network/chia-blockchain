from __future__ import annotations

from typing import Literal, Union

# Defaults are conservative.
parallel: Union[bool, int, Literal["auto"]] = True
checkout_blocks_and_plots = False
install_timelord = False
# NOTE: do not use until the hangs are fixed
#       https://github.com/CFMTech/pytest-monitor/issues/53
#       https://github.com/pythonprofilers/memory_profiler/issues/342
check_resource_usage = False
job_timeout = 30
