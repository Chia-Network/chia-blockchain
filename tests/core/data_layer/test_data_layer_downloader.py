from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import boto3
import botocore
import botocore.retries.adaptive
from moto import mock_s3

from chia.data_layer.data_layer_util import ServerInfo
from chia.data_layer.downloader import S3Downloader

MY_BUCKET = "my_bucket"
MY_PREFIX = "mock_folder"
ACCESS_KEY = "fake_access_key"
SECRET_KEY = "fake_secret_key"
REGION = "us-east-1"

log = logging.getLogger(__name__)


@mock_s3
class TestS3:
    def setUp(self) -> None:
        log.info("setUp")
        self.client = boto3.client(
            "s3",
            region_name=REGION,
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
        )
        try:
            self.s3 = boto3.resource(
                "s3",
                region_name=REGION,
                aws_access_key_id=ACCESS_KEY,
                aws_secret_access_key=SECRET_KEY,
            )
            self.s3.meta.client.head_bucket(Bucket=MY_BUCKET)
        except botocore.exceptions.ClientError:
            pass
        else:
            err = "{bucket} should not exist.".format(bucket=MY_BUCKET)
            raise EnvironmentError(err)
        self.client.create_bucket(Bucket=MY_BUCKET)

    def create_file(self) -> str:
        self.client.create_bucket(Bucket=MY_BUCKET)
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(bytes(fp.name, "utf-8"))
            log.info(f"upload file {fp.name}")
            key = os.path.basename(fp.name)
            self.client.upload_file(Filename=fp.name, Bucket=MY_BUCKET, Key=key)
            return fp.name

    def list_files(self) -> None:
        bucket = self.s3.Bucket(MY_BUCKET)
        log.info("list files in bucket")
        for my_bucket_object in bucket.objects.all():
            log.info(f"            bucket file: {my_bucket_object.key}")

    def tearDown(self) -> None:
        log.info("tearDown")
        bucket = self.s3.Bucket(MY_BUCKET)
        for file in bucket.objects.all():
            log.info(f"delete bucket file: {file.key}")
            file.delete()
        assert len(list(bucket.objects.all())) == 0
        bucket.delete()

    def get_resource(self):  # type:ignore
        return self.s3

    def get_client(self):  # type:ignore
        return self.client

    def test_download(self) -> None:
        self.setUp()
        file_name = os.path.basename(self.create_file())
        try:
            downloader = S3Downloader(self.get_resource())  # type:ignore
            with tempfile.TemporaryDirectory() as tmpdir:
                server_info = ServerInfo(f"s3://{MY_BUCKET}/", 0, 0)
                assert os.path.exists(Path(tmpdir).joinpath(file_name)) is False
                loop = asyncio.get_event_loop()
                coroutine = downloader.download(Path(tmpdir), file_name, "", server_info, 10, log)
                loop.run_until_complete(coroutine)
                assert os.path.exists(Path(tmpdir).joinpath(file_name))
        except Exception as e:
            log.error(f"something went wrong {e}")
        self.tearDown()
