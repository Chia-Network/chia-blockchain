from __future__ import annotations

import logging
from pathlib import Path
from typing import List

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
        res, _, _ = await write_files_for_root(data_store, tree_id, root, foldername, overwrite)
        return res


class S3Uploader:
    name: str
    """The name of the service.

    All lower case with underscores as needed.
    """

    def __init__(self, client, bucket: str, store_ids: List[bytes32]) -> None:  # type:ignore
        self.name = "file system uploader"
        self.boto_client = client
        self.store_ids = store_ids
        self.bucket = bucket

    async def check_store_id(
        self,
        store_id: bytes32,
        log: logging.Logger,
    ) -> bool:
        if store_id in self.store_ids:
            log.info(f"{self.name} uploader handles store {store_id}")
            return True
        return False

    async def upload(
        self,
        data_store: DataStore,
        tree_id: bytes32,
        root: Root,
        foldername: Path,
        log: logging.Logger,
        overwrite: bool = False,
    ) -> bool:
        """Download file return result"""
        res, full_tree_path, diff_path = await write_files_for_root(data_store, tree_id, root, foldername, overwrite)
        if not res:
            log.error("could not write files to disc before pushing to s3")

        # todo maybe add the option to set the prefix for where it will be saved in s3
        self.boto_client.upload_file(str(full_tree_path), self.bucket, full_tree_path.name)
        self.boto_client.upload_file(str(diff_path), self.bucket, diff_path.name)
        return True
