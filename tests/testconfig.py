from __future__ import annotations

from typing import TYPE_CHECKING, List, Union

if TYPE_CHECKING:
    from typing_extensions import Literal

    Oses = Literal["macos", "ubuntu", "windows"]

# Defaults are conservative.
parallel: Union[bool, int, Literal["auto"]] = False
checkout_blocks_and_plots = False
install_timelord = False
check_resource_usage = False
job_timeout = 30
custom_vars: List[str] = []
os_skip: List[Oses] = []
