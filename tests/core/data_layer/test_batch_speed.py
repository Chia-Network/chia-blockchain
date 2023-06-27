from __future__ import annotations

import logging
from random import Random
from typing import Any, Dict, List

import pytest
from _pytest.fixtures import SubRequest

from chia.data_layer.data_layer_util import Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from tests.util.misc import assert_runtime

log = logging.getLogger(__name__)

random = Random()
random.seed(100, version=2)

pytestmark = pytest.mark.data_layer

#
# This isn't really a good benchmark test, it's more my internal testing to see if changes I made
# are improvements or not. Should be converted to something more benchmarky.
#


@pytest.mark.benchmark
@pytest.mark.parametrize("num_keys", [1, 100, 250, 500, 1_000, 5_000, 10_000])
@pytest.mark.asyncio
async def test_insert_batch_speed(data_store: DataStore, tree_id: bytes32, request: SubRequest, num_keys: int) -> None:
    changelist: List[Dict[str, Any]] = []

    await data_store.create_tree(tree_id=tree_id, status=Status.COMMITTED)

    for _ in range(num_keys):
        key = random.getrandbits(256).to_bytes(32, byteorder="big").hex()
        value = random.getrandbits(8192).to_bytes(1024, byteorder="big").hex()

        changelist.append({"action": "insert", "key": hexstr_to_bytes(key), "value": hexstr_to_bytes(value)})

    with assert_runtime(seconds=999999999999999999, label=request.node.name) as results_future:
        await data_store.insert_batch(tree_id=tree_id, changelist=changelist, status=Status.COMMITTED)

    data = await data_store.get_keys_values_dict(tree_id=tree_id)
    for change in changelist:
        change_key: bytes = change["key"]
        change_value = change["value"]
        assert data[change_key] == change_value

    result = results_future.result()
    per = result.duration / num_keys

    # print(f"{data_store.total=}")
    assert False, f"Insert {num_keys} items took {result.duration} seconds, {per} seconds per item"

    await data_store.close()
