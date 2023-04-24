from __future__ import annotations

import multiprocessing

try:
    multiprocessing.set_start_method("spawn")
except RuntimeError:
    pass
