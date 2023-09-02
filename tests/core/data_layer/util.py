from __future__ import annotations

import contextlib
import functools
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Union

from chia.data_layer.data_layer_util import NodeType, Side, Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

# from subprocess.pyi
_FILE = Union[None, int, IO[Any]]


if TYPE_CHECKING:
    # these require Python 3.9 at runtime
    os_PathLike_str = os.PathLike[str]
    subprocess_CompletedProcess_str = subprocess.CompletedProcess[str]
else:
    os_PathLike_str = os.PathLike
    subprocess_CompletedProcess_str = subprocess.CompletedProcess


async def general_insert(
    data_store: DataStore,
    tree_id: bytes32,
    key: bytes,
    value: bytes,
    reference_node_hash: bytes32,
    side: Optional[Side],
) -> bytes32:
    insert_result = await data_store.insert(
        key=key,
        value=value,
        tree_id=tree_id,
        reference_node_hash=reference_node_hash,
        side=side,
        status=Status.COMMITTED,
    )
    return insert_result.node_hash


@dataclass(frozen=True)
class Example:
    expected: Program
    terminal_nodes: List[bytes32]


async def add_0123_example(data_store: DataStore, tree_id: bytes32) -> Example:
    expected = Program.to(
        (
            (
                (b"\x00", b"\x10\x00"),
                (b"\x01", b"\x11\x01"),
            ),
            (
                (b"\x02", b"\x12\x02"),
                (b"\x03", b"\x13\x03"),
            ),
        ),
    )

    insert = functools.partial(general_insert, data_store=data_store, tree_id=tree_id)

    c_hash = await insert(key=b"\x02", value=b"\x12\x02", reference_node_hash=None, side=None)
    b_hash = await insert(key=b"\x01", value=b"\x11\x01", reference_node_hash=c_hash, side=Side.LEFT)
    d_hash = await insert(key=b"\x03", value=b"\x13\x03", reference_node_hash=c_hash, side=Side.RIGHT)
    a_hash = await insert(key=b"\x00", value=b"\x10\x00", reference_node_hash=b_hash, side=Side.LEFT)

    return Example(expected=expected, terminal_nodes=[a_hash, b_hash, c_hash, d_hash])


async def add_01234567_example(data_store: DataStore, tree_id: bytes32) -> Example:
    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (
                    (b"\x02", b"\x12\x02"),
                    (b"\x03", b"\x13\x03"),
                ),
            ),
            (
                (
                    (b"\x04", b"\x14\x04"),
                    (b"\x05", b"\x15\x05"),
                ),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    insert = functools.partial(general_insert, data_store=data_store, tree_id=tree_id)

    g_hash = await insert(key=b"\x06", value=b"\x16\x06", reference_node_hash=None, side=None)

    c_hash = await insert(key=b"\x02", value=b"\x12\x02", reference_node_hash=g_hash, side=Side.LEFT)
    b_hash = await insert(key=b"\x01", value=b"\x11\x01", reference_node_hash=c_hash, side=Side.LEFT)
    d_hash = await insert(key=b"\x03", value=b"\x13\x03", reference_node_hash=c_hash, side=Side.RIGHT)
    a_hash = await insert(key=b"\x00", value=b"\x10\x00", reference_node_hash=b_hash, side=Side.LEFT)

    f_hash = await insert(key=b"\x05", value=b"\x15\x05", reference_node_hash=g_hash, side=Side.LEFT)
    h_hash = await insert(key=b"\x07", value=b"\x17\x07", reference_node_hash=g_hash, side=Side.RIGHT)
    e_hash = await insert(key=b"\x04", value=b"\x14\x04", reference_node_hash=f_hash, side=Side.LEFT)

    return Example(expected=expected, terminal_nodes=[a_hash, b_hash, c_hash, d_hash, e_hash, f_hash, g_hash, h_hash])


@dataclass
class ChiaRoot:
    path: pathlib.Path
    scripts_path: pathlib.Path

    def run(
        self,
        args: List[Union[str, os_PathLike_str]],
        *other_args: Any,
        check: bool = True,
        encoding: str = "utf-8",
        stdout: Optional[_FILE] = subprocess.PIPE,
        stderr: Optional[_FILE] = subprocess.PIPE,
        **kwargs: Any,
    ) -> subprocess_CompletedProcess_str:
        # TODO: --root-path doesn't seem to work here...
        kwargs.setdefault("env", {})
        kwargs["env"]["CHIA_ROOT"] = os.fspath(self.path)
        kwargs["env"]["CHIA_KEYS_ROOT"] = os.fspath(self.path)

        # This is for windows
        if "SYSTEMROOT" in os.environ:
            kwargs["env"]["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

        modified_args: List[Union[str, os_PathLike_str]] = [
            self.scripts_path.joinpath("chia"),
            "--root-path",
            self.path,
            *args,
        ]
        processed_args: List[str] = [os.fspath(element) for element in modified_args]
        final_args = [processed_args, *other_args]

        kwargs["check"] = check
        kwargs["encoding"] = encoding
        kwargs["stdout"] = stdout
        kwargs["stderr"] = stderr

        return subprocess.run(*final_args, **kwargs)

    def read_log(self) -> str:
        return self.path.joinpath("log", "debug.log").read_text(encoding="utf-8")

    def print_log(self) -> None:
        log_text: Optional[str]

        try:
            log_text = self.read_log()
        except FileNotFoundError:
            log_text = None

        if log_text is None:
            print(f"---- no log at: {self.path}")
        else:
            print(f"---- start of: {self.path}")
            print(log_text)
            print(f"---- end of: {self.path}")

    @contextlib.contextmanager
    def print_log_after(self) -> Iterator[None]:
        try:
            yield
        finally:
            self.print_log()


def create_valid_node_values(
    node_type: NodeType,
    left_hash: Optional[bytes32] = None,
    right_hash: Optional[bytes32] = None,
) -> Dict[str, Any]:
    if node_type == NodeType.INTERNAL:
        return {
            "hash": Program.to((left_hash, right_hash)).get_tree_hash_precalc(left_hash, right_hash),
            "node_type": node_type,
            "left": left_hash,
            "right": right_hash,
            "key": None,
            "value": None,
        }
    elif node_type == NodeType.TERMINAL:
        key = b""
        value = b""
        return {
            "hash": Program.to((key, value)).get_tree_hash(),
            "node_type": node_type,
            "left": None,
            "right": None,
            "key": key,
            "value": value,
        }

    raise Exception(f"Unhandled node type: {node_type!r}")
