import os
import pytest
import shutil
import sys

from chia.util.files import write_file_async
from multiprocessing import Process
from pathlib import Path
from time import sleep


def keep_file_open_for_n_seconds(file_path: Path, seconds: int):
    f = os.open(str(file_path), os.O_CREAT | os.O_WRONLY)
    if f is not None:
        os.write(f, "hello".encode())
        sleep(seconds)


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_file(self, tmp_path: Path):
        dest_path: Path = tmp_path / "test_write_file.txt"
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.asyncio
    async def test_write_file_overwrite(self, tmp_path: Path):
        dest_path: Path = tmp_path / "test_write_file.txt"
        await write_file_async(dest_path, "test")
        await write_file_async(dest_path, "test2")
        assert dest_path.read_text() == "test2"

    @pytest.mark.asyncio
    async def test_write_file_create_intermediate_dirs(self, tmp_path: Path):
        dest_path: Path = tmp_path / "test_write_file/a/b/c/test_write_file.txt"
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.asyncio
    async def test_write_file_existing_intermediate_dirs(self, tmp_path: Path):
        dest_path: Path = tmp_path / "test_write_file/a/b/c/test_write_file.txt"
        dest_path.parent.mkdir(parents=True, exist_ok=False)
        assert dest_path.parent.exists()
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.asyncio
    async def test_write_file_default_permissions(self, tmp_path: Path):
        if sys.platform in ["win32", "cygwin"]:
            pytest.skip("Setting UNIX file permissions doesn't apply to Windows")

        dest_path: Path = tmp_path / "test_write_file/test_write_file.txt"
        assert not dest_path.parent.exists()
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"
        # Expect: parent directory has default permissions of 0o700
        assert oct(dest_path.parent.stat().st_mode)[-3:] == oct(0o700)[-3:]
        # Expect: file has default permissions of 0o600
        assert oct(dest_path.stat().st_mode)[-3:] == oct(0o600)[-3:]

    @pytest.mark.asyncio
    async def test_write_file_custom_permissions(self, tmp_path: Path):
        if sys.platform in ["win32", "cygwin"]:
            pytest.skip("Setting UNIX file permissions doesn't apply to Windows")

        dest_path: Path = tmp_path / "test_write_file/test_write_file.txt"
        await write_file_async(dest_path, "test", file_mode=0o642)
        assert dest_path.read_text() == "test"
        # Expect: file has custom permissions of 0o642
        assert oct(dest_path.stat().st_mode)[-3:] == oct(0o642)[-3:]

    @pytest.mark.asyncio
    async def test_write_file_os_replace_raising_permissionerror(self, tmp_path: Path, monkeypatch):
        def mock_os_replace(src, dst):
            raise PermissionError("test")
        monkeypatch.setattr(os, "replace", mock_os_replace)

        shutil_move_called: bool = False
        original_shutil_move = shutil.move

        def mock_shutil_move(src, dst):
            nonlocal shutil_move_called
            shutil_move_called = True
            original_shutil_move(src, dst)
        monkeypatch.setattr(shutil, "move", mock_shutil_move)

        dest_path: Path = tmp_path / "test_write_file/test_write_file.txt"
        await write_file_async(dest_path, "test")
        assert shutil_move_called is True

    @pytest.mark.asyncio
    async def test_write_file_already_open(self, tmp_path: Path):
        dest_path: Path = tmp_path / "test_write_file.txt"
        proc: Process = Process(target=keep_file_open_for_n_seconds, args=(dest_path, 3))
        proc.start()
        sleep(1.5)
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"
        proc.join()
