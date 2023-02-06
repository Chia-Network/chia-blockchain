import logging
from pathlib import Path

import aiohttp

from chia.data_layer.data_layer_util import ServerInfo
from typing_extensions import Protocol


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

    @staticmethod
    async def download(
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
        # todo only return true for http download urls
        return True

    @staticmethod
    async def download(
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
                # log.debug(f"Downloading delta file {filename}. Size {size} bytes.")
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
