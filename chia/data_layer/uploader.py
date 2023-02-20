from __future__ import annotations

import logging
from pathlib import Path

from typing_extensions import Protocol

from chia.data_layer.data_layer_util import Root
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import write_files_for_root
from chia.types.blockchain_format.sized_bytes import bytes32


class DLUploader(Protocol):
    name: str
    """The name of the service.

    All lower case with underscores as needed.
    """

    def __init__(self) -> None:
        ...

    async def check_store_id(
        self,
        store_id: bytes32,
        log: logging.Logger,
    ) -> bool:
        "check if uploader handles store id"

    async def upload(
        self,
        data_store: DataStore,
        tree_id: bytes32,
        root: Root,
        foldername: Path,
        overwrite: bool = False,
    ) -> bool:
        """upload file return result"""


class FilesystemUploader:
    name: str
    """The name of the service.

    All lower case with underscores as needed.
    """

    def __init__(self) -> None:
        self.name = "file system uploader"

    async def check_store_id(
        self,
        store_id: bytes32,
        log: logging.Logger,
    ) -> bool:
        "default always return true"
        return True

    async def upload(
        self,
        data_store: DataStore,
        tree_id: bytes32,
        root: Root,
        foldername: Path,
        overwrite: bool = False,
    ) -> bool:
        """Download file return result"""
        return await write_files_for_root(data_store, tree_id, root, foldername, overwrite)
