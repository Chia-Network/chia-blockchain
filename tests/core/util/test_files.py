import os
import pytest
import shutil
import sys

from chia.util.files import move_file, move_file_async, write_file_async
from pathlib import Path


class TestMoveFile:
    def test_move_file(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_with_overwrite(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        dst_path.write_text("destination")
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_create_intermediate_dirs(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination" / "destination.txt"
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_existing_intermediate_dirs(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination" / "destination.txt"
        dst_path.parent.mkdir(parents=True, exist_ok=False)
        assert dst_path.parent.exists()
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_source_missing(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is False

    def test_move_file_os_replace_raising_permissionerror(self, tmp_path: Path, monkeypatch):
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

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        move_file(src_path, dst_path)
        assert shutil_move_called is True
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_overwrite_os_replace_raising_permissionerror(self, tmp_path: Path, monkeypatch):
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

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        dst_path.write_text("destination")
        move_file(src_path, dst_path)
        assert shutil_move_called is True
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    def test_move_file_os_replace_raising_unexpected_exception(self, tmp_path: Path, monkeypatch):
        def mock_os_replace(src, dst):
            raise RuntimeError("test")
        monkeypatch.setattr(os, "replace", mock_os_replace)

        shutil_move_called: bool = False
        original_shutil_move = shutil.move

        def mock_shutil_move(src, dst):
            nonlocal shutil_move_called
            shutil_move_called = True
            original_shutil_move(src, dst)
        monkeypatch.setattr(shutil, "move", mock_shutil_move)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(RuntimeError):
            move_file(src_path, dst_path)
        assert shutil_move_called is False
        assert src_path.exists() is True
        assert dst_path.exists() is False

    def test_move_file_failing(self, tmp_path: Path, monkeypatch):
        def mock_os_replace(src, dst):
            raise RuntimeError("test")
        monkeypatch.setattr(os, "replace", mock_os_replace)

        def mock_shutil_move(src, dst):
            raise RuntimeError("test2")
        monkeypatch.setattr(shutil, "move", mock_shutil_move)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(RuntimeError):
            move_file(src_path, dst_path)
        assert src_path.exists() is True
        assert dst_path.exists() is False


class TestMoveFileAsync:
    @pytest.mark.asyncio
    async def test_move_file_async(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        await move_file_async(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    @pytest.mark.asyncio
    async def test_move_file_async_failure_no_reattempts(self, tmp_path: Path):
        src_path: Path = tmp_path / "source.txt"
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            await move_file_async(src_path, dst_path, reattempts=0)
        assert src_path.exists() is False
        assert dst_path.exists() is False

    @pytest.mark.asyncio
    async def test_move_file_async_success_on_reattempt(self, tmp_path: Path, monkeypatch):
        failed_attempts: int = 2
        reattempts: int = 0
        original_os_replace = os.replace

        def mock_os_replace(src, dst):
            nonlocal failed_attempts, reattempts
            if reattempts < failed_attempts:
                reattempts += 1
                raise Exception("test")
            else:
                original_os_replace(src, dst)
        monkeypatch.setattr(os, "replace", mock_os_replace)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        await move_file_async(src_path, dst_path, reattempts=failed_attempts + 1)
        assert reattempts == 2
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    @pytest.mark.asyncio
    async def test_move_file_async_failure_on_reattempt(self, tmp_path: Path, monkeypatch):
        failed_attempts: int = 3
        reattempts: int = 0
        original_os_replace = os.replace

        def mock_os_replace(src, dst):
            nonlocal failed_attempts, reattempts
            if reattempts < failed_attempts:
                reattempts += 1
                raise Exception("test")
            else:
                original_os_replace(src, dst)
        monkeypatch.setattr(os, "replace", mock_os_replace)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            await move_file_async(src_path, dst_path, reattempts=failed_attempts)
        assert reattempts == 3
        assert src_path.exists() is True
        assert dst_path.exists() is False


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
