from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import boto3 as boto3
import yaml
from aiohttp import web
from botocore.exceptions import ClientError

from chia.data_layer.download_data import is_filename_valid
from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)
plugin_name = "Chia S3 Datalayer plugin"
plugin_version = "0.1.0"


@dataclass(frozen=True)
class StoreConfig:
    id: bytes32
    bucket: Optional[str]
    urls: Set[str]

    @classmethod
    def unmarshal(cls, d: Dict[str, Any]) -> StoreConfig:
        upload_bucket = d.get("upload_bucket", None)
        if upload_bucket and len(upload_bucket) == 0:
            upload_bucket = None

        return StoreConfig(bytes32.from_hexstr(d["store_id"]), upload_bucket, d.get("download_urls", set()))

    def marshal(self) -> Dict[str, Any]:
        return {"store_id": self.id.hex(), "upload_bucket": self.bucket, "download_urls": self.urls}


class S3Plugin:
    boto_client: boto3.client
    port: int
    region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    server_files_path: Path
    stores: List[StoreConfig]
    instance_name: str

    def __init__(
        self,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        server_files_path: Path,
        stores: List[StoreConfig],
        instance_name: str,
    ):
        self.boto_client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        self.stores = stores
        self.instance_name = instance_name
        self.server_files_path = server_files_path

    async def add_store_id(self, request: web.Request) -> web.Response:
        #        self.update_instance_from_config()
        #        try:
        #            data = await request.json()
        #        except Exception as e:
        #            print(f"failed parsing request {request} {e}")
        #           return web.json_response({"success": False})
        #       store_id = bytes32.from_hexstr(data["id"])
        #       bucket = data.get("bucket", None)
        #       dirty = False
        #       if store_id not in self.store_ids:
        #           self.store_ids.append(store_id)
        #           dirty = True
        #       if bucket is not None:
        #           if bucket not in self.buckets:
        #               self.buckets[bucket] = [store_id.hex()]
        #               dirty = True
        #           elif store_id.hex() not in self.buckets[bucket]:
        #               self.buckets[bucket].append(store_id.hex())
        #               dirty = True
        #       if dirty:
        #           try:
        #               self.update_config()
        #           except Exception as e:
        #               print(f"failed handling request {request} {e}")
        #               return web.json_response({"success": False})

        # return web.json_response({"success": True, "id": store_id.hex()})
        return web.json_response({"success": False})

    async def remove_store_id(self, request: web.Request) -> web.Response:
        #       self.update_instance_from_config()
        #       try:
        #           data = await request.json()
        #       except Exception as e:
        #           print(f"failed parsing request {request} {e}")
        #           return web.json_response({"success": False})
        #       store_id = bytes32.from_hexstr(data["id"])
        #       bucket = data.get("bucket", None)
        #       try:
        #           self.store_ids.remove(store_id)
        #           if bucket is not None:
        #               self.buckets[bucket].remove(store_id.hex())
        #           self.update_config()
        #       except Exception as e:
        #           if not isinstance(e, ValueError):
        #               print(f"failed handling request {request} {e}")
        #               return web.json_response({"success": False})

        # return web.json_response({"success": True, "id": store_id.hex()})
        return web.json_response({"success": False})

    async def handle_upload(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            log.error(f"failed parsing request {request} {type(e).__name__} {e}")
            return web.json_response({"handle_upload": False})

        store_id = bytes32.from_hexstr(data["store_id"])
        for store in self.stores:
            if store.id == store_id and store.bucket:
                return web.json_response({"handle_upload": True, "bucket": store.bucket})

        return web.json_response({"handle_upload": False})

    async def upload(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            store_id = bytes32.from_hexstr(data["store_id"])
            bucket = self.get_bucket(store_id)
            full_tree_name: str = data["full_tree_filename"]
            diff_name: str = data["diff_filename"]

            # filenames must follow the DataLayer naming convention
            if not is_filename_valid(full_tree_name) or not is_filename_valid(diff_name):
                return web.json_response({"uploaded": False})

            # Pull the store_id from the filename to make sure we only upload for configured stores
            full_tree_id = bytes32.fromhex(full_tree_name[:64])
            diff_tree_id = bytes32.fromhex(diff_name[:64])

            if not (full_tree_id == diff_tree_id == store_id):
                return web.json_response({"uploaded": False})

            full_tree_path = self.server_files_path.joinpath(full_tree_name)
            diff_path = self.server_files_path.joinpath(diff_name)

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
                log.error(f"failed uploading file to aws {type(e).__name__} {e}")
                return web.json_response({"uploaded": False})
        except Exception as e:
            log.error(f"failed handling request {request} {type(e).__name__} {e}")
            return web.json_response({"uploaded": False})
        return web.json_response({"uploaded": True})

    async def healthz(self, request: web.Request) -> web.Response:
        return web.json_response({"success": True})

    async def plugin_info(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "name": plugin_name,
                "version": plugin_version,
                "instance": self.instance_name,
            }
        )

    async def handle_download(self, request: web.Request) -> web.Response:
        self.update_instance_from_config()
        try:
            data = await request.json()
        except Exception as e:
            log.error(f"failed parsing request {request} {type(e).__name__} {e}")
            return web.json_response({"handle_download": False})

        store_id = bytes32.from_hexstr(data["store_id"])
        parse_result = urlparse(data["url"])
        for store in self.stores:
            if store.id == store_id and parse_result.scheme == "s3" and data["url"] in store.urls:
                return web.json_response({"handle_download": True, "urls": list(store.urls)})

        return web.json_response({"handle_download": False})

    async def download(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            url = data["url"]
            filename = data["filename"]

            # filename must follow the DataLayer naming convention
            if not is_filename_valid(filename):
                return web.json_response({"downloaded": False})

            # Pull the store_id from the filename to make sure we only download for configured stores
            filename_tree_id = bytes32.fromhex(filename[:64])
            parse_result = urlparse(url)
            should_download = False
            for store in self.stores:
                if store.id == filename_tree_id and parse_result.scheme == "s3" and url in store.urls:
                    should_download = True
                    break

            if not should_download:
                return web.json_response({"downloaded": False})

            bucket = parse_result.netloc
            target_filename = self.server_files_path.joinpath(filename)
            # Create folder for parent directory
            target_filename.parent.mkdir(parents=True, exist_ok=True)
            log.info(f"downloading {url} to {target_filename}...")
            with concurrent.futures.ThreadPoolExecutor() as pool:
                await asyncio.get_running_loop().run_in_executor(
                    pool, functools.partial(self.boto_client.download_file, bucket, filename, str(target_filename))
                )
        except Exception as e:
            log.error(f"failed parsing request {request} {type(e).__name__} {e}")
            return web.json_response({"downloaded": False})
        return web.json_response({"downloaded": True})

    def get_bucket(self, store_id: bytes32) -> str:
        for store in self.stores:
            if store.id == store_id and store.bucket:
                return store.bucket

        raise Exception(f"bucket not found for store id {store_id.hex()}")

    def update_instance_from_config(self) -> None:
        config = load_config(self.instance_name)
        self.stores = read_store_ids_from_config(config)

    def update_config(self) -> None:
        return

    #      store_ids = []
    #      for store_id in self.store_ids:
    #          store_ids.append(store_id.hex())

    #     with open("s3_plugin_config.yml", "r") as file:
    #         full_config = yaml.safe_load(file)

    #     full_config[self.instance_name]["store_ids"] = store_ids
    #     full_config[self.instance_name]["buckets"] = self.buckets
    #     self.save_config("s3_plugin_config.yml", full_config)

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


def read_store_ids_from_config(config: Dict[str, Any]) -> List[StoreConfig]:
    stores = []
    for store in config.get("stores", []):
        try:
            stores.append(StoreConfig.unmarshal(store))
        except Exception as e:
            if "store_id" in store:
                bad_store_id = f"{store['store_id']!r}"
            else:
                bad_store_id = "<missing>"
            log.info(f"Ignoring invalid store id: {bad_store_id}: {type(e).__name__} {e}")
            pass

    return stores


def make_app(config: Dict[str, Any], instance_name: str) -> web.Application:
    try:
        region = config["aws_credentials"]["region"]
        aws_access_key_id = config["aws_credentials"]["access_key_id"]
        aws_secret_access_key = config["aws_credentials"]["secret_access_key"]
        server_files_location = config["server_files_location"]
        server_files_path = Path(server_files_location).resolve()
    except KeyError as e:
        sys.exit(
            "config file must have server_files_location, aws_credentials with region, access_key_id. "
            f", and secret_access_key. Missing config key: {e.args[0]!r}"
        )

    stores = read_store_ids_from_config(config)

    s3_client = S3Plugin(
        region=region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        server_files_path=server_files_path,
        stores=stores,
        instance_name=instance_name,
    )
    app = web.Application()
    app.add_routes([web.post("/handle_upload", s3_client.handle_upload)])
    app.add_routes([web.post("/upload", s3_client.upload)])
    app.add_routes([web.post("/handle_download", s3_client.handle_download)])
    app.add_routes([web.post("/download", s3_client.download)])
    app.add_routes([web.post("/add_store_id", s3_client.add_store_id)])
    app.add_routes([web.post("/remove_store_id", s3_client.remove_store_id)])
    app.add_routes([web.post("/plugin_info", s3_client.plugin_info)])
    app.add_routes([web.post("/healthz", s3_client.healthz)])
    logging.basicConfig(level=logging.INFO, filename=config.get("log_filename", "s3_plugin.log"))
    log.info(f"Starting s3 plugin {instance_name} on port {config['port']}")
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

    web.run_app(make_app(config, instance_name), port=port, host="localhost")
    log.info(f"Stopped s3 plugin {instance_name}")


if __name__ == "__main__":
    run_server()
