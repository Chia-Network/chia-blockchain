from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import boto3
from typing_extensions import Protocol

from chia.data_layer.data_layer_util import ServerInfo


class DLDownloader(Protocol):
    name: str
    """The name of the service.

    All lower case with underscores as needed.
    """

    def __init__(self) -> None:
        ...

    @staticmethod
    def check_url(url: str, log: logging.Logger) -> bool:
        """Return the mapping of endpoints to handler callables."""
        ...

    async def download(
        self,
        client_folder: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: int,
        log: logging.Logger,
    ) -> bool:
        """Download file return result"""


class HttpDownloader(DLDownloader):
    def __init__(self) -> None:
        self.name = "http downloader"

    @staticmethod
    def check_url(url: str, log: logging.Logger) -> bool:
        parse_result = urlparse(url)
        if parse_result.scheme == "http" or parse_result.scheme == "https":
            return True
        return False

    async def download(
        self,
        client_folder: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: int,
        log: logging.Logger,
    ) -> bool:
        async with aiohttp.ClientSession() as session:
            headers = {"accept-encoding": "gzip"}
            async with session.get(
                server_info.url + "/" + filename, headers=headers, timeout=timeout, proxy=proxy_url
            ) as resp:
                resp.raise_for_status()
                size = int(resp.headers.get("content-length", 0))
                log.debug(f"Downloading delta file {filename}. Size {size} bytes.")
                progress_byte = 0
                progress_percentage = "{:.0%}".format(0)
                target_filename = client_folder.joinpath(filename)
                with target_filename.open(mode="wb") as f:
                    async for chunk, _ in resp.content.iter_chunks():
                        f.write(chunk)
                        progress_byte += len(chunk)
                        new_percentage = "{:.0%}".format(progress_byte / size)
                        if new_percentage != progress_percentage:
                            progress_percentage = new_percentage
                            log.info(f"Downloading delta file {filename}. {progress_percentage} of {size} bytes.")

        return True


class S3Downloader(DLDownloader):
    def __init__(self, pub_key: str, secret_key: str, region: str) -> None:
        self.name = "s3 downloader"
        self.boto_resource = boto3.resource(
            "s3", aws_access_key_id=pub_key, aws_secret_access_key=secret_key, region_name=region
        )

    @staticmethod
    def check_url(url: str, log: logging.Logger) -> bool:
        parse_result = urlparse(url)
        if parse_result.scheme == "s3":
            return True
        return False

    async def download(
        self,
        client_folder: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: int,
        log: logging.Logger,
    ) -> bool:
        bucket = self.boto_resource.Bucket(server_info.url)
        target_filename = client_folder.joinpath(filename)
        size = self.boto_resource.head_object(key_name=filename)["ContentLength"]
        log.debug(f"Downloading delta file {filename}. Size {size} bytes.")
        with target_filename.open(mode="wb") as f:
            bucket.download_file(filename, f)
        return True
