from __future__ import annotations

from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class TypedObserver(Observer):
    """This is an adapter to watchdog.observers.Observer to provide a typed interface"""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]

    def schedule(
        self,
        event_handler: FileSystemEventHandler,
        path: Path,
        recursive: bool = False,
    ) -> None:
        super().schedule(event_handler, path, recursive)  # type: ignore[no-untyped-call]

    def start(self) -> None:
        super().start()  # type: ignore[no-untyped-call]

    def stop(self) -> None:
        super().stop()  # type: ignore[no-untyped-call]
