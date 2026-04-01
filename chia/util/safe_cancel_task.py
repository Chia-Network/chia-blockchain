# Package: utils

from __future__ import annotations

import asyncio
import logging


def cancel_task_safe(task: asyncio.Task[None] | None, log: logging.Logger | None = None) -> None:
    if task is not None:
        try:
            task.cancel()
        except Exception as e:
            if log is not None:
                log.error(f"Error while canceling task.{e} {task}")
