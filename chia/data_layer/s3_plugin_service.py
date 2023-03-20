from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
from pathlib import Path
from urllib.parse import urlparse

import boto3 as boto3
import yaml
from aiohttp import web

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


with open("s3_plugin_config.yml", "r") as f:
    config = yaml.safe_load(f)

port = config["port"]
region = config["aws_credentials"]["region"]
aws_access_key_id = config["aws_credentials"]["access_key_id"]
aws_secret_access_key = config["aws_credentials"]["secret_access_key"]
store_ids = config["store_ids"]
bukets = config["buckets"]
urls = config["urls"]


boto_client = boto3.client(
    "s3",
    region_name=region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)


async def check_store_id(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception as e:
        print(f"failed parsing request {request} {e}")
        return web.json_response({"handles_url": False})
    store_id = bytes32.from_hexstr(data["id"])
    if store_id.hex() in store_ids:
        return web.json_response({"handles_store": True})
    return web.json_response({"handles_store": False})


async def upload(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception as e:
        print(f"failed parsing request {request} {e}")
        return web.json_response({"handles_url": False})
    store_id = bytes32.from_hexstr(data["id"])
    full_tree_path = data["full_tree_path"]
    diff_path = data["diff_path"]
    bucket = await get_bucket(store_id)
    # todo add try catch
    boto_client.upload_file(str(full_tree_path), bucket, full_tree_path)
    boto_client.upload_file(str(diff_path), bucket, diff_path)
    return web.json_response({"uploaded": True})


async def check_url(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception as e:
        print(f"failed parsing request {request} {e}")
        return web.json_response({"handles_url": False})
    parse_result = urlparse(data["url"])
    if parse_result.scheme == "s3" and data["url"] in urls:
        return web.json_response({"handles_url": True})
    return web.json_response({"handles_url": False})


async def download(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception as e:
        print(f"failed parsing request {request} {e}")
        return web.json_response({"handles_url": False})
    url = data["url"]
    client_folder = Path(data["client_folder"])
    filename = data["filename"]
    parse_result = urlparse(url)
    bucket = parse_result.netloc
    target_filename = client_folder.joinpath(filename)
    # Create folder for parent directory
    target_filename.parent.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        await asyncio.get_running_loop().run_in_executor(
            pool, functools.partial(boto_client.download_file, bucket, filename, str(target_filename))
        )

    return web.json_response({"downloaded": True})


async def get_bucket(store_id: bytes32) -> str:
    for bucket in bukets:
        if store_id.hex() in bukets[bucket]:
            return bucket
    raise Exception(f"bucket not found store id {store_id.hex()}")


async def make_app():
    app = web.Application()
    app.add_routes([web.post("/check_store_id", check_store_id)])
    app.add_routes([web.post("/upload", upload)])
    app.add_routes([web.post("/check_url", check_url)])
    app.add_routes([web.post("/download", download)])
    return app


web.run_app(make_app(), port=8999)
