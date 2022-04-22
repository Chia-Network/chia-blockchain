#!/usr/bin/env python3

import asyncio
import os
from pathlib import Path

from tools.test_full_sync import run_sync_test


def test_full_sync_test():
    file_path = os.path.realpath(__file__)
    db_file = Path(file_path).parent / "test-blockchain-db.sqlite"
    asyncio.run(run_sync_test(db_file, db_version=2, profile=False, single_thread=False, test_constants=False))
