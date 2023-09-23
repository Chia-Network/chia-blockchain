#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tools.test_full_sync import run_sync_test


@pytest.mark.parametrize("keep_up", [True, False])
def test_full_sync_test(keep_up: bool) -> None:
    file_path = os.path.realpath(__file__)
    db_file = Path(file_path).parent / "test-blockchain-db.sqlite"
    asyncio.run(
        run_sync_test(
            db_file,
            db_version=2,
            profile=False,
            single_thread=False,
            test_constants=False,
            keep_up=keep_up,
            db_sync="off",
            node_profiler=False,
            start_at_checkpoint=None,
        )
    )
