from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3 as boto3
import yaml
from aiohttp import web
from botocore.exceptions import ClientError

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)
plugin_id = "2bdf9ed6-f3bc-44f6-a69d-06602c0688d9"
plugin_version = "Chia S3 Datalayer plugin 0.1.0"


class S3Plugin:
    boto_client: boto3.client
    port: int
    region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    store_ids: List[bytes32]
    bukets: Dict[str, List[str]]
    urls: List[str]
    instance_name: str

    def __init__(
        self,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        store_ids: List[bytes32],
        buckets: Dict[str, List[str]],
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
        self.buckets = buckets
        self.urls = urls
        self.instance_name = instance_name

    async def add_store_id(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"success": False})
        store_id = bytes32.from_hexstr(data["id"])
        if store_id not in self.store_ids:
            self.store_ids.append(store_id)
            try:
                self.update_config()
            except Exception as e:
                print(f"failed handling request {request} {e}")
                return web.json_response({"success": False})

        return web.json_response({"success": True, "id": store_id.hex()})

    async def remove_store_id(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"success": False})
        store_id = bytes32.from_hexstr(data["id"])
        try:
            self.store_ids.remove(store_id)
            self.update_config()
        except Exception as e:
            if not isinstance(e, ValueError):
                print(f"failed handling request {request} {e}")
                return web.json_response({"success": False})

        return web.json_response({"success": True, "id": store_id.hex()})

    async def check_store_id(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_url": False})
        store_id = bytes32.from_hexstr(data["id"])
        if store_id in self.store_ids:
            return web.json_response({"handles_store": True})
        return web.json_response({"handles_store": False})

    async def upload(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            store_id = bytes32.from_hexstr(data["id"])
            bucket = self.get_bucket(store_id)
            full_tree_path = Path(data["full_tree_path"])
            diff_path = Path(data["diff_path"])
            try:
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    await asyncio.get_running_loop().run_in_executor(
                        pool,
                        functools.partial(self.boto_client.upload_file, full_tree_path, bucket, full_tree_path.name),
                    )
                    await asyncio.get_running_loop().run_in_executor(
                        pool, functools.partial(self.boto_client.upload_file, diff_path, bucket, diff_path.name)
                    )
            except ClientError as e:
                print(f"failed uploading file to aws {e}")
                return web.json_response({"uploaded": False})
        except Exception as e:
            print(f"failed handling request {request} {e}")
            return web.json_response({"handles_url": False})
        return web.json_response({"uploaded": True})

    async def plugin_id(self, request: web.Request) -> web.Response:
        return web.json_response({"id": plugin_id, "version": plugin_version})

    async def healthz(self, request: web.Request) -> web.Response:
        return web.json_response({"success": True})

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
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"downloaded": False})
        return web.json_response({"downloaded": True})

    def get_bucket(self, store_id: bytes32) -> str:
        for bucket in self.buckets:
            if store_id.hex() in self.buckets[bucket]:
                return bucket
        raise Exception(f"bucket not found for store id {store_id.hex()}")

    def update_instance_from_config(self) -> None:
        config = load_config(self.instance_name)
        # TODO: dedup from startup code in make_app
        store_ids = []
        for store in config["store_ids"]:
            store_ids.append(bytes32.from_hexstr(store))
        buckets: Dict[str, List[str]] = config["buckets"]
        urls = config["urls"]
        self.buckets = buckets
        self.store_ids = store_ids
        self.urls = urls

    def update_config(self) -> None:
        store_ids = []
        for store_id in self.store_ids:
            store_ids.append(store_id.hex())

        with open("s3_plugin_config.yml", "r") as file:
            full_config = yaml.safe_load(file)

        full_config[self.instance_name]["store_ids"] = store_ids
        self.save_config("s3_plugin_config.yml", full_config)

    def save_config(self, filename: str, config_data: Any) -> None:
        path: Path = Path(filename)
        with tempfile.TemporaryDirectory(dir=path.parent) as tmp_dir:
            tmp_path: Path = Path(tmp_dir) / Path(filename)
            with open(tmp_path, "w") as f:
                yaml.safe_dump(config_data, f)
            try:
                os.replace(str(tmp_path), path)
            except PermissionError:
                shutil.move(str(tmp_path), str(path))


def make_app(config: Dict[str, Any], instance_name: str):  # type: ignore
    region = config["aws_credentials"]["region"]
    aws_access_key_id = config["aws_credentials"]["access_key_id"]
    aws_secret_access_key = config["aws_credentials"]["secret_access_key"]
    store_ids = []
    for store in config["store_ids"]:
        store_ids.append(bytes32.from_hexstr(store))
    buckets: Dict[str, List[str]] = config["buckets"]
    urls = config["urls"]
    s3_client = S3Plugin(region, aws_access_key_id, aws_secret_access_key, store_ids, buckets, urls, instance_name)
    app = web.Application()
    app.add_routes([web.post("/check_store_id", s3_client.check_store_id)])
    app.add_routes([web.post("/upload", s3_client.upload)])
    app.add_routes([web.post("/check_url", s3_client.check_url)])
    app.add_routes([web.post("/download", s3_client.download)])
    app.add_routes([web.post("/plugin_id", s3_client.plugin_id)])
    app.add_routes([web.post("/healthz", s3_client.healthz)])
    app.add_routes([web.post("/add_store_id", s3_client.add_store_id)])
    app.add_routes([web.post("/remove_store_id", s3_client.remove_store_id)])

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
