from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import boto3 as boto3
import yaml
from aiohttp import web
from botocore.exceptions import ClientError

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoreId:
    id: bytes32
    bucket: Optional[str]
    urls: Set[str]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StoreId:
        return StoreId(bytes32.from_hexstr(d["id"]), d.get("bucket", None), d.get("urls", set()))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id.hex(), "bucket": self.bucket, "urls": self.urls}


class S3Plugin:
    boto_client: boto3.client
    port: int
    region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    store_ids: List[StoreId]
    instance_name: str

    def __init__(
        self,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        store_ids: List[StoreId],
        instance_name: str,
    ):
        self.boto_client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        self.store_ids = store_ids
        self.instance_name = instance_name

    async def handle_upload(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_upload": False})

        id = bytes32.from_hexstr(data["id"])
        for store_id in self.store_ids:
            if store_id.id == id and store_id.bucket and len(store_id.bucket) > 0:
                return web.json_response({"handles_upload": True, "bucket": store_id.bucket})

        return web.json_response({"handles_upload": False})

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

    async def handle_download(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            print(f"failed parsing request {request} {e}")
            return web.json_response({"handles_download": False})

        id = bytes32.from_hexstr(data["id"])
        parse_result = urlparse(data["url"])
        for store_id in self.store_ids:
            if store_id.id == id and parse_result.scheme == "s3" and data["url"] in store_id.urls:
                return web.json_response({"handles_download": True, "urls": list(store_id.urls)})

        return web.json_response({"handles_download": False})

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

    def get_bucket(self, id: bytes32) -> str:
        for store_id in self.store_ids:
            if store_id.id == id and store_id.bucket and len(store_id.bucket) > 0:
                return store_id.bucket

        raise Exception(f"bucket not found for store id {id.hex()}")

    def update_instance_from_config(self) -> None:
        config = load_config(self.instance_name)
        store_ids = []
        for store in config["store_ids"]:
            store_ids.append(StoreId.from_dict(store))

        self.store_ids = store_ids


def make_app(config: Dict[str, Any], instance_name: str):  # type: ignore
    try:
        region = config["aws_credentials"]["region"]
        aws_access_key_id = config["aws_credentials"]["access_key_id"]
        aws_secret_access_key = config["aws_credentials"]["secret_access_key"]
    except KeyError as e:
        sys.exit(
            "config file must have aws_credentials with region, access_key_id, and secret_access_key. "
            f"Missing config key: {e}"
        )
    store_ids = []
    for store in config.get("store_ids", []):
        store_ids.append(StoreId.from_dict(store))

    s3_client = S3Plugin(region, aws_access_key_id, aws_secret_access_key, store_ids, instance_name)
    app = web.Application()
    app.add_routes([web.post("/handle_upload", s3_client.handle_upload)])
    app.add_routes([web.post("/upload", s3_client.upload)])
    app.add_routes([web.post("/handle_download", s3_client.handle_download)])
    app.add_routes([web.post("/download", s3_client.download)])
    return app


def load_config(instance: str) -> Any:
    with open("s3_plugin_config.yml", "r") as f:
        full_config = yaml.safe_load(f)
    return full_config[instance]


def run_server() -> None:
    instance_name = sys.argv[1]
    try:
        config = load_config(instance_name)
    except KeyError:
        sys.exit(f"Config for instance {instance_name} not found.")

    if not config:
        sys.exit(f"Config for instance {instance_name} is empty.")

    try:
        port = config["port"]
    except KeyError:
        sys.exit("Missing port in config file.")

    print(f"run instance {instance_name}")
    web.run_app(make_app(config, instance_name), port=port)


if __name__ == "__main__":
    run_server()
