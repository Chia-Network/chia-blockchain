"""
Regression tests for FullNode.add_prevalidated_blocks().

SEC-349: Prevalidation failures must return typed errors instead of raising
AssertionError, so the caller can ban the offending peer.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node import FullNode
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.errors import Err


def _make_fake_self() -> SimpleNamespace:
    return SimpleNamespace(
        blockchain=SimpleNamespace(
            get_block_record_from_db=AsyncMock(return_value=None),
        ),
        weight_proof_handler=None,
        log=logging.getLogger("test.add_prevalidated_blocks"),
        _state_changed=lambda *a, **kw: None,
    )


def _make_fake_block(height: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        header_hash=bytes32(b"\xaa" * 32),
        prev_header_hash=bytes32(b"\xbb" * 32),
        finished_sub_slots=[],
        height=uint32(height),
    )


def _make_fork_info() -> ForkInfo:
    return ForkInfo(
        fork_height=-1,
        peak_height=-1,
        peak_hash=bytes32(b"\x00" * 32),
    )


def _make_validation_state() -> ValidationState:
    return ValidationState(
        ssi=uint64(0),
        difficulty=uint64(0),
        prev_ses_block=None,
    )


@pytest.mark.anyio
async def test_prevalidation_error_returns_err_not_assert() -> None:
    """A PreValidationResult with error != None must produce a typed Err return,
    not an AssertionError. This ensures the caller's peer-ban path executes."""
    fake_self = _make_fake_self()
    block = _make_fake_block()
    invalid_result = PreValidationResult(
        error=uint16(Err.INVALID_POSPACE.value),
        required_iters=None,
        conds=None,
        timing=uint32(0),
    )
    blockchain = SimpleNamespace(block_record=lambda _: None, remove_extra_block=lambda _: None)
    peer_info = PeerInfo("127.0.0.1", uint16(8444))

    summary, err = await FullNode.add_prevalidated_blocks(
        fake_self,  # type: ignore[arg-type]
        blockchain,  # type: ignore[arg-type]
        [block],  # type: ignore[list-item]
        [invalid_result],
        _make_fork_info(),
        peer_info,
        _make_validation_state(),
    )

    assert err is not None, "Expected an error to be returned"
    assert err == Err.INVALID_POSPACE
    assert summary is None


@pytest.mark.anyio
async def test_prevalidation_none_required_iters_returns_err() -> None:
    """A PreValidationResult with no error but required_iters=None must return
    Err.UNKNOWN instead of raising AssertionError."""
    fake_self = _make_fake_self()
    block = _make_fake_block()
    bad_result = PreValidationResult(
        error=None,
        required_iters=None,
        conds=None,
        timing=uint32(0),
    )
    blockchain = SimpleNamespace(block_record=lambda _: None, remove_extra_block=lambda _: None)
    peer_info = PeerInfo("127.0.0.1", uint16(8444))

    summary, err = await FullNode.add_prevalidated_blocks(
        fake_self,  # type: ignore[arg-type]
        blockchain,  # type: ignore[arg-type]
        [block],  # type: ignore[list-item]
        [bad_result],
        _make_fork_info(),
        peer_info,
        _make_validation_state(),
    )

    assert err is not None, "Expected an error to be returned"
    assert err == Err.UNKNOWN
    assert summary is None
