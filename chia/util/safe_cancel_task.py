from __future__ import annotations

import asyncio
import logging
from typing import Optional


def cancel_task_safe(task: Optional[asyncio.Task], log: Optional[logging.Logger] = None):
    if task is not None:
        try:
            task.cancel()
        except Exception as e:
            if log is not None:
                log.error(f"Error while canceling task.{e} {task}")
