from __future__ import annotations

from typing import List

import pytest

from chia.types.full_block import FullBlock

# These test targets are used to trigger a build of the test chains.
# On CI we clone the test-cache repository to load the chains from, so they
# don't need to be re-generated.

# When running tests in parallel (with pytest-xdist) it's faster to first
# generate all the chains, so the same chains aren't being created in parallel.

# The cached test chains are stored in ~/.chia/blocks

# To generate the chains, run:

# pytest -m build_test_chains


@pytest.mark.build_test_chains
def test_trigger_default_400(default_400_blocks: List[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_1000(default_1000_blocks: List[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_pre_genesis_empty_1000(pre_genesis_empty_slots_1000_blocks: List[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_1500(default_1500_blocks: List[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_10000(
    default_10000_blocks: List[FullBlock],
    test_long_reorg_blocks: List[FullBlock],
    test_long_reorg_blocks_light: List[FullBlock],
    test_long_reorg_1500_blocks: List[FullBlock],
    test_long_reorg_1500_blocks_light: List[FullBlock],
) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_2000_compact(default_2000_blocks_compact: List[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_10000_compact(default_10000_blocks_compact: List[FullBlock]) -> None:
    pass
