from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from chia.util import files
from chia.util.files import move_file, move_file_async, write_file_async


class TestMoveFile:
    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file(self, tmp_path: Path):
        """
        Move a file from one location to another and verify the contents.
        """

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_with_overwrite(self, tmp_path: Path):
        """
        Move a file from one location to another, overwriting the destination.
        """

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        dst_path.write_text("destination")
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_create_intermediate_dirs(self, tmp_path: Path):
        """
        Move a file from one location to another, creating intermediate directories at the destination.
        """

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination" / "destination.txt"
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_existing_intermediate_dirs(self, tmp_path: Path):
        """
        Move a file from one location to another, where intermediate directories already exist at the destination.
        """

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination" / "destination.txt"
        dst_path.parent.mkdir(parents=True, exist_ok=False)
        assert dst_path.parent.exists()
        move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_source_missing(self, tmp_path: Path):
        """
        Expect failure when moving a file from one location to another, where the source does not exist.
        """

        src_path: Path = tmp_path / "source.txt"
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            move_file(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is False

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_os_replace_raising_permissionerror(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file with os.replace raising a PermissionError. The move should succeed
        after using shutil.move to move the file.
        """

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

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_overwrite_os_replace_raising_exception(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file with os.replace raising an exception. The move should succeed,
        overwriting the destination.
        """

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

    # use tmp_path pytest fixture to create a temporary directory
    def test_move_file_failing(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file with both os.replace and shutil.move raising exceptions. The move should fail.
        """

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
    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_move_file_async(self, tmp_path: Path):
        """
        Move a file from one location to another.
        """

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        await move_file_async(src_path, dst_path)
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_move_file_async_failure_no_reattempts(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file where the move fails and no reattempts are made. The move should fail.
        """

        move_file_called: bool = False

        def mock_move_file(src, dst):
            nonlocal move_file_called
            move_file_called = True
            raise Exception("test")

        monkeypatch.setattr(files, "move_file", mock_move_file)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            await move_file_async(src_path, dst_path, reattempts=0)
        assert move_file_called is True
        assert src_path.exists() is True
        assert dst_path.exists() is False

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_move_file_async_success_on_reattempt(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file where the move initially fails and then succeeds after reattempting.
        The move should succeed.
        """

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

        def mock_shutil_move(src, dst):
            raise Exception("test2")

        monkeypatch.setattr(shutil, "move", mock_shutil_move)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        await move_file_async(src_path, dst_path, reattempts=failed_attempts + 1)
        assert reattempts == 2
        assert src_path.exists() is False
        assert dst_path.exists() is True
        assert dst_path.read_text() == "source"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_move_file_async_failure_on_reattempt(self, tmp_path: Path, monkeypatch):
        """
        Simulate moving a file where the move fails and exhausts all reattempts. The move should fail.
        """

        total_allowed_attempts: int = 3
        attempts: int = 0

        def mock_os_replace(src, dst):
            nonlocal attempts
            attempts += 1
            raise Exception("test")

        monkeypatch.setattr(os, "replace", mock_os_replace)

        def mock_shutil_move(src, dst):
            raise Exception("test2")

        monkeypatch.setattr(shutil, "move", mock_shutil_move)

        src_path: Path = tmp_path / "source.txt"
        src_path.write_text("source")
        dst_path: Path = tmp_path / "destination.txt"
        with pytest.raises(FileNotFoundError):
            await move_file_async(src_path, dst_path, reattempts=total_allowed_attempts - 1)
        assert attempts == total_allowed_attempts
        assert src_path.exists() is True
        assert dst_path.exists() is False


class TestWriteFile:
    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file(self, tmp_path: Path):
        """
        Write a file to a location.
        """

        dest_path: Path = tmp_path / "test_write_file.txt"
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_overwrite(self, tmp_path: Path):
        """
        Write a file to a location and overwrite the file if it already exists.
        """

        dest_path: Path = tmp_path / "test_write_file.txt"
        dest_path.write_text("test")
        await write_file_async(dest_path, "test2")
        assert dest_path.read_text() == "test2"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_create_intermediate_dirs(self, tmp_path: Path):
        """
        Write a file to a location and create intermediate directories if they do not exist.
        """

        dest_path: Path = tmp_path / "test_write_file/a/b/c/test_write_file.txt"
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_existing_intermediate_dirs(self, tmp_path: Path):
        """
        Write a file to a location and where intermediate directories aleady exist.
        """

        dest_path: Path = tmp_path / "test_write_file/a/b/c/test_write_file.txt"
        dest_path.parent.mkdir(parents=True, exist_ok=False)
        assert dest_path.parent.exists()
        await write_file_async(dest_path, "test")
        assert dest_path.read_text() == "test"

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_default_permissions(self, tmp_path: Path):
        """
        Write a file to a location and use the default permissions.
        """

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

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_custom_permissions(self, tmp_path: Path):
        """
        Write a file to a location and use custom permissions.
        """

        if sys.platform in ["win32", "cygwin"]:
            pytest.skip("Setting UNIX file permissions doesn't apply to Windows")

        dest_path: Path = tmp_path / "test_write_file/test_write_file.txt"
        await write_file_async(dest_path, "test", file_mode=0o642)
        assert dest_path.read_text() == "test"
        # Expect: file has custom permissions of 0o642
        assert oct(dest_path.stat().st_mode)[-3:] == oct(0o642)[-3:]

    @pytest.mark.anyio
    # use tmp_path pytest fixture to create a temporary directory
    async def test_write_file_os_replace_raising_permissionerror(self, tmp_path: Path, monkeypatch):
        """
        Write a file to a location where os.replace raises PermissionError.
        """

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
