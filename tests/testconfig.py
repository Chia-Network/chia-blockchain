from __future__ import annotations

from typing import Literal, Union

# Defaults are conservative.
parallel: Union[bool, int, Literal["auto"]] = True
checkout_blocks_and_plots = False
install_timelord = False
check_resource_usage = False
job_timeout = 30
