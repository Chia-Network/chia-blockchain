from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
from typing import List
from urllib.parse import urlparse

import boto3 as boto3
from aiohttp import web

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


store_ids: List[bytes32] = []
boto_client = boto3.client(
    "s3",
    region_name="us-east-1",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)


async def check_store_id(request: web.Request) -> web.Response:
    data = await request.json()
    store_id = bytes32.from_hexstr(data["id"])
    log.info(f"check uploader {store_id} {store_ids}")
    for store in store_ids:
        if store_id == store:
            log.info(f"s3 uploader handles store {store}")
            return web.json_response({"handles_store": True})
    return web.json_response({"handles_store": False})


async def upload(request: web.Request) -> web.Response:
    data = await request.json()
    store_id = bytes32.from_hexstr(data["id"])
    full_tree_path = data["full_tree_path"]
    diff_path = data["diff_path"]
    bucket = get_bucket(store_id)
    # todo add try catch
    boto_client.upload_file(str(full_tree_path), bucket, full_tree_path)
    boto_client.upload_file(str(diff_path), bucket, diff_path)
    return web.json_response({"uploaded": True})


async def check_url(request: web.Request) -> web.Response:
    data = await request.json()
    parse_result = urlparse(data["url"])
    if parse_result.scheme == "s3":
        return web.json_response({"handles_url": True})
    return web.json_response({"handles_url": False})


async def download(request: web.Request) -> web.Response:
    data = await request.json()
    url = data["url"]
    client_folder = data["client_folder"]
    filename = data["filename"]
    parse_result = urlparse(url)
    bucket = parse_result.netloc
    target_filename = client_folder.joinpath(filename)
    log.debug(f"target file name {target_filename} bucket {bucket}")
    # Create folder for parent directory
    target_filename.parent.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        await asyncio.get_running_loop().run_in_executor(
            pool, functools.partial(boto_client.download_file, bucket, filename, str(target_filename))
        )

    return web.json_response({"downloaded": True})


async def get_bucket(bucket: bytes32) -> str:
    return "chia-datalayer-test-bucket"


async def make_app() -> None:
    app = web.Application()
    app.add_routes([web.get("/check_store_id", check_store_id)])
    app.add_routes([web.get("/upload", upload)])
    app.add_routes([web.get("/check_url", check_url)])
    app.add_routes([web.get("/download", download)])


web.run_app(make_app())
