import json
from typing import Dict, List

import pytest

from tests.core.data_layer.util import ChiaRoot


@pytest.mark.asyncio
async def test_help(chia_root: ChiaRoot) -> None:
    """Just a trivial test to make sure the subprocessing is at least working and the
    data executable does run.
    """
    completed_process = chia_root.run(args=["data", "--help"])
    assert "Show this message and exit" in completed_process.stdout


@pytest.mark.xfail(strict=True)
@pytest.mark.asyncio
def test_round_trip(chia_root: ChiaRoot, chia_daemon: None, chia_data: None) -> None:
    """Create a table, insert a row, get the row by its hash."""

    with chia_root.print_log_after():
        row_data = "ffff8353594d8083616263"
        row_hash = "1a6f915513173902a7216e7d9e4a16bfd088e20683f45de3b432ce72e9cc7aa8"

        changelist: List[Dict[str, str]] = [{"action": "insert", "row_data": row_data}]

        create = chia_root.run(args=["data", "create_table", "--table", "test table"])
        print(f"create {create}")
        # TODO get store id from cli response
        store_id = "0102030405060708091011121314151617181920212223242526272829303132"
        update = chia_root.run(
            args=["data", "update_table", "--table", store_id, "--changelist", json.dumps(changelist)]
        )
        print(f"update {update}")
        completed_process = chia_root.run(args=["data", "get_row", "--table", store_id, "--row_hash", row_hash])
        parsed = json.loads(completed_process.stdout)
        expected = {"row_data": row_data, "row_hash": row_hash, "success": True}

        assert parsed == expected
