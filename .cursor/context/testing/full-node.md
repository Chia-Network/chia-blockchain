# Full Node Tests

Verified: 2026-07-12 against a5647a9327e5. If source contradlicts this doc, trust source and update the doc.

## Scope

Use this when testing behavior driven by full node state transitions: sync,
block acceptance, mempool-to-block inclusion, wallet-connected flows, and reorg.

For harness selection and block/transaction patterns, see `patterns.md` and
`architecture.md`. For mempool-specific tests, see `mempool.md`.

## Key Tips

- For sync tests, assert both node height and peak equality — height alone can
  lag behind peak acceptance.
- Keep fixture scope narrow; large shared state increases intermittent failures.

## Starter Template

```python
from __future__ import annotations

import pytest

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.connection_utils import add_dummy_connection, connect_and_get_peer
from chia._tests.core.node_height import node_height_at_least
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.blockchain import Blockchain
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import wallet_protocol
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools


@pytest.mark.anyio
async def test_example(
    one_node_one_block: tuple[FullNodeAPI, ChiaServer, BlockTools],
) -> None:
    full_node_api, server, bt = one_node_one_block
    full_node = full_node_api.full_node

    blocks = bt.get_consecutive_blocks(3)
    for block in blocks:
        await full_node.add_block(block)

    await time_out_assert(10, node_height_at_least, True, full_node, 3)
```
