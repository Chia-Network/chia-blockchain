from __future__ import annotations

import logging
import re
from collections.abc import Awaitable
from typing import Any, cast

import pytest
from chia_rs import FullBlock, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.core.full_node.test_full_node import find_reward_coin
from chia._tests.core.node_height import node_height_exactly
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.blockchain import StateChangeSummary
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.hash import std_hash
from chia.util.recursive_replace import recursive_replace

_SKIP_SIG_LOG = re.compile(r"block body validation proceeding without validated aggregate signature at height (\d+)")
_ASSUMEVALID_ENABLED_LOG = re.compile(
    r"assumevalid enabled: skipping aggregate signature validation for "
    r"blocks below height (\d+) \(hash ([0-9a-f]+)\)"
)


def _with_invalid_agg_sig(bt: BlockTools, block: FullBlock) -> FullBlock:
    """Corrupt agg-sig and re-seal foliage so only BLS verification fails."""
    assert block.transactions_info is not None
    block = recursive_replace(block, "transactions_info.aggregated_signature", G2Element.generator())
    assert block.transactions_info is not None
    block = recursive_replace(
        block, "foliage_transaction_block.transactions_info_hash", block.transactions_info.get_hash()
    )
    assert block.foliage_transaction_block is not None
    block = recursive_replace(
        block, "foliage.foliage_transaction_block_hash", block.foliage_transaction_block.get_hash()
    )
    new_m = block.foliage.foliage_transaction_block_hash
    assert new_m is not None
    new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
    return cast(FullBlock, recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig))


def _blocks_with_invalid_sig_at(bt: BlockTools, bad_height: int, after: int) -> list[FullBlock]:
    """Chain with a bad-agg-sig spend at ``bad_height``, then ``after`` more blocks on that tip."""
    assert bad_height >= 3
    blocks = bt.get_consecutive_blocks(
        bad_height,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=bt.pool_ph,
    )
    assert blocks[-1].height == bad_height - 1

    wt = bt.get_pool_wallet_tool()
    coin = find_reward_coin(blocks[2], bt.pool_ph)
    tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
    blocks = bt.get_consecutive_blocks(
        1,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        transaction_data=tx,
        farmer_reward_puzzle_hash=bt.pool_ph,
    )
    assert blocks[-1].height == bad_height
    blocks = [*blocks[:-1], _with_invalid_agg_sig(bt, blocks[-1])]

    if after > 0:
        blocks = bt.get_consecutive_blocks(after, block_list_input=blocks, farmer_reward_puzzle_hash=bt.pool_ph)
    return blocks


def _skip_sig_heights(caplog: pytest.LogCaptureFixture) -> list[int]:
    return [int(match.group(1)) for match in _SKIP_SIG_LOG.finditer(caplog.text)]


def _configure_assumevalid(full_node: FullNode, height: int, header_hash: bytes32) -> None:
    full_node.config["assumevalid_height"] = height
    full_node.config["assumevalid_hash"] = header_hash.hex()


async def _add_block_batch(full_node: FullNode, blocks: list[FullBlock]) -> tuple[bool, StateChangeSummary | None]:
    peer_info = PeerInfo("0.0.0.0", 0)
    blockchain = AugmentedBlockchain(full_node.blockchain)
    vs = ValidationState(
        full_node.constants.SUB_SLOT_ITERS_STARTING,
        full_node.constants.DIFFICULTY_STARTING,
        None,
    )
    fork_info = ForkInfo(-1, -1, full_node.constants.GENESIS_CHALLENGE)
    return await full_node.add_block_batch(blocks, peer_info, fork_info, vs, blockchain)


@pytest.mark.anyio
async def test_assumevalid_sync_skips_signatures_only_below_cutoff(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid agg-sig below assumevalid is accepted; signatures stay off only below H."""
    full_node_1, full_node_2, server_1, server_2, bt = two_nodes
    av_height = 4
    blocks = _blocks_with_invalid_sig_at(bt, bad_height=av_height - 1, after=1)
    av_block = next(b for b in blocks if b.height == av_height)
    bad_block = next(b for b in blocks if b.height == av_height - 1)
    assert bad_block.transactions_info is not None
    assert bad_block.transactions_info.aggregated_signature == G2Element.generator()

    # Node1 must also skip sigs below H to store/serve the corrupted block.
    _configure_assumevalid(full_node_1.full_node, av_height, av_block.header_hash)
    success, _ = await _add_block_batch(full_node_1.full_node, blocks)
    assert success
    peak = full_node_1.full_node.blockchain.get_peak()
    assert peak is not None
    assert peak.height == blocks[-1].height

    _configure_assumevalid(full_node_2.full_node, av_height, av_block.header_hash)
    assert full_node_2.full_node.get_assumevalid() == (av_block.header_hash, uint32(av_height))

    validate_signatures_by_height: dict[int, bool] = {}
    real_pre_validate_block = pre_validate_block

    async def spy_pre_validate_block(
        constants: Any,
        blockchain: Any,
        block: FullBlock,
        pool: Any,
        conds: Any,
        vs: Any,
        **kwargs: Any,
    ) -> Awaitable[PreValidationResult]:
        assert "validate_signatures" in kwargs, kwargs
        validate_signatures_by_height[int(block.height)] = bool(kwargs["validate_signatures"])
        return await real_pre_validate_block(constants, blockchain, block, pool, conds, vs, **kwargs)

    monkeypatch.setattr("chia.full_node.full_node.pre_validate_block", spy_pre_validate_block)

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    full_node_2.full_node.sync_store.peer_has_block(
        peak.header_hash, full_node_1.full_node.server.node_id, peak.weight, peak.height, True
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="chia.consensus.block_body_validation"):
        await full_node_2.full_node.sync_from_fork_point(uint32(0), peak.height, peak.header_hash, [])

    assert node_height_exactly(full_node_2, peak.height)
    assert full_node_2.full_node.blockchain.height_to_hash(uint32(av_height - 1)) == bad_block.header_hash

    assert validate_signatures_by_height, validate_signatures_by_height
    assert any(h < av_height for h in validate_signatures_by_height)
    assert any(h >= av_height for h in validate_signatures_by_height)
    assert all(
        (validate is False) if h < av_height else (validate is True)
        for h, validate in validate_signatures_by_height.items()
    ), validate_signatures_by_height

    skip_heights = _skip_sig_heights(caplog)
    assert skip_heights, f"expected skip-signature body-validation logs; caplog={caplog.text!r}"
    assert av_height - 1 in skip_heights, skip_heights
    assert max(skip_heights) < av_height

    assert full_node_2.full_node.assumevalid_satisfied()
    assert full_node_2.full_node.blockchain.height_to_hash(uint32(av_height)) == av_block.header_hash


@pytest.mark.anyio
async def test_assumevalid_rejects_invalid_signature_at_or_above_cutoff(
    one_node: SimulatorsAndWalletsServices,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid agg-sig at/above assumevalid height fails with BAD_AGGREGATE_SIGNATURE."""
    [full_node_service], _, bt = one_node
    full_node = full_node_service._node
    av_height = 4
    # Corrupt the spend at H+1 so the assumevalid hash at H stays a valid block.
    blocks = _blocks_with_invalid_sig_at(bt, bad_height=av_height + 1, after=0)
    av_block = next(b for b in blocks if b.height == av_height)
    bad_block = blocks[-1]
    assert bad_block.height == av_height + 1
    assert bad_block.transactions_info is not None
    assert bad_block.transactions_info.aggregated_signature == G2Element.generator()

    _configure_assumevalid(full_node, av_height, av_block.header_hash)
    assert full_node.get_assumevalid() == (av_block.header_hash, uint32(av_height))

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="chia.full_node.full_node"):
        success, summary = await _add_block_batch(full_node, blocks)

    assert success is False
    assert "BAD_AGGREGATE_SIGNATURE" in caplog.text
    assert f"height {av_height + 1}" in caplog.text

    peak = full_node.blockchain.get_peak()
    assert peak is not None
    assert peak.height == av_height
    assert peak.header_hash == av_block.header_hash
    assert summary is not None
    assert summary.peak.height == av_height
    assert full_node.assumevalid_satisfied()
    assert full_node.blockchain.height_to_hash(uint32(av_height + 1)) is None


@pytest.mark.parametrize("assumevalid_ok", [True, False])
@pytest.mark.anyio
async def test_assumevalid_long_sync(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    default_1000_blocks: list[FullBlock],
    self_hostname: str,
    caplog: pytest.LogCaptureFixture,
    assumevalid_ok: bool,
) -> None:
    """Long sync with assumevalid: correct hash finishes; wrong hash fails at cutoff."""
    full_node_1, full_node_2, server_1, server_2, bt = two_nodes
    blocks = default_1000_blocks[:600]
    assert len(blocks) > bt.constants.WEIGHT_PROOF_RECENT_BLOCKS
    assert len(blocks) > full_node_2.full_node.config["sync_blocks_behind_threshold"]

    success, _ = await _add_block_batch(full_node_1.full_node, blocks)
    assert success
    peak = full_node_1.full_node.blockchain.get_peak()
    assert peak is not None

    av_height = uint32(50)
    av_block = blocks[av_height]
    configured_hash = av_block.header_hash if assumevalid_ok else std_hash(b"wrong assumevalid hash")
    if not assumevalid_ok:
        assert configured_hash != av_block.header_hash
    _configure_assumevalid(full_node_2.full_node, int(av_height), configured_hash)
    assert full_node_2.full_node.get_assumevalid() == (configured_hash, av_height)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="chia.full_node.full_node"):
        await server_2.start_client(
            PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_2.full_node.on_connect
        )
        if assumevalid_ok:
            await time_out_assert(250, node_height_exactly, True, full_node_2, peak.height)
        else:
            await time_out_assert(120, lambda: "assumevalid mismatch" in caplog.text)

    if assumevalid_ok:
        enabled = _ASSUMEVALID_ENABLED_LOG.search(caplog.text)
        assert enabled is not None, caplog.text
        assert int(enabled.group(1)) == av_height
        assert enabled.group(2) == av_block.header_hash.hex()
        assert full_node_2.full_node.assumevalid_satisfied()
    else:
        assert "assumevalid mismatch" in caplog.text
        assert f"height {av_height}" in caplog.text
        assert configured_hash.hex() in caplog.text
        assert av_block.header_hash.hex() in caplog.text

        peak2 = full_node_2.full_node.blockchain.get_peak()
        assert peak2 is None or peak2.height < av_height
        assert not node_height_exactly(full_node_2, peak.height)
        assert not full_node_2.full_node.assumevalid_satisfied()
