from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any
from urllib.parse import urlparse

import boto3 as boto3
import yaml
from aiohttp import web

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


class S3Plugin:
    boto_client: boto3.client
    port: int
    region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    store_ids: List[str]
    bukets: Dict[str, List[str]]
    urls: List[str]
    instance_name: str

    def __init__(
        self,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        store_ids: List[str],
        bukets: Dict[str, List[str]],
        urls: List[str],
        instance_name: str,
    ):
        self.boto_client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        self.store_ids = store_ids
        self.bukets = bukets
        self.urls = urls
        self.instance_name = instance_name

    async def check_store_id(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_url": False})
        store_id = bytes32.from_hexstr(data["id"])
        if store_id.hex() in self.store_ids:
            return web.json_response({"handles_store": True})
        return web.json_response({"handles_store": False})

    async def upload(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_url": False})
        store_id = bytes32.from_hexstr(data["id"])
        full_tree_path = data["full_tree_path"]
        diff_path = data["diff_path"]
        bucket = self.get_bucket(store_id)
        # todo add try catch
        self.boto_client.upload_file(str(full_tree_path), bucket, full_tree_path)
        self.boto_client.upload_file(str(diff_path), bucket, diff_path)
        return web.json_response({"uploaded": True})

    async def check_url(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_url": False})
        parse_result = urlparse(data["url"])
        if parse_result.scheme == "s3" and data["url"] in self.urls:
            return web.json_response({"handles_url": True})
        return web.json_response({"handles_url": False})

    async def download(self, request: web.Request) -> web.Response:
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
                pool, functools.partial(self.boto_client.download_file, bucket, filename, str(target_filename))
            )

        return web.json_response({"downloaded": True})

    def get_bucket(self, store_id: bytes32) -> str:
        for bucket in self.bukets:
            if store_id.hex() in self.bukets[bucket]:
                return bucket
        raise Exception(f"bucket not found for store id {store_id.hex()}")

    def update_instance_from_config(self) -> None:
        config = load_config(self.instance_name)
        store_ids = config["store_ids"]
        buckets: Dict[str, List[str]] = config["buckets"]
        urls = config["urls"]
        self.buckets = buckets
        self.store_ids = store_ids
        self.urls = urls


def make_app(config: Dict[str, Any], instance_name: str):  # type: ignore
    region = config["aws_credentials"]["region"]
    aws_access_key_id = config["aws_credentials"]["access_key_id"]
    aws_secret_access_key = config["aws_credentials"]["secret_access_key"]
    store_ids = config["store_ids"]
    buckets: Dict[str, List[str]] = config["buckets"]
    urls = config["urls"]
    s3_client = S3Plugin(region, aws_access_key_id, aws_secret_access_key, store_ids, buckets, urls, instance_name)
    app = web.Application()
    app.add_routes([web.post("/check_store_id", s3_client.check_store_id)])
    app.add_routes([web.post("/upload", s3_client.upload)])
    app.add_routes([web.post("/check_url", s3_client.check_url)])
    app.add_routes([web.post("/download", s3_client.download)])
    return app


def load_config(instance: str) -> Any:
    with open("s3_plugin_config.yml", "r") as f:
        full_config = yaml.safe_load(f)
    return full_config[instance]


def run_server() -> None:
    instance_name = sys.argv[1]
    print(f"run instance {instance_name}")
    config = load_config(instance_name)
    port = config["port"]
    web.run_app(make_app(config, instance_name), port=port)


# run this
run_server()
