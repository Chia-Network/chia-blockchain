import pytest
from typing import Optional

from tests.setup_nodes import setup_two_nodes, test_constants


@pytest.fixture()
def worker_number(worker_id) -> Optional[int]:
    if worker_id.startswith("gw"):
        return int(worker_id[2:])
    return None


@pytest.fixture()
def worker_port(worker_number) -> int:
    if worker_number is None:
        return 30000
    return 40000 + worker_number * 10


@pytest.fixture(scope="function")
async def two_nodes(worker_port):
    async for _ in setup_two_nodes(test_constants, worker_port):  # xxx may need spacing for multiple full nodes
        yield _
