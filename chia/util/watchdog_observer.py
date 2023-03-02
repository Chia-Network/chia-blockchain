from __future__ import annotations

from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class TypedObserver(Observer):  # type: ignore[misc]
    """This is an adapter to watchdog.observers.Observer to provide a typed interface"""

    def __init__(self) -> None:
        super().__init__()

    def schedule(  # type:ignore[no-untyped-def]
        self, event_handler: FileSystemEventHandler, path: Path, recursive=False
    ) -> None:
        super().schedule(event_handler, path, recursive)

    def start(self) -> None:
        super().start()

    def stop(self) -> None:
        super().stop()
